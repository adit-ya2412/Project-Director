"""Feature A - word-level caption highlighting (style_extensions.md §3):
`app/renderer/captions.py`, pure string composition, no ffmpeg needed for
the structural cases. Real burn-in of the generated .ass is proven
separately below with an actual libass render when ffmpeg is available,
mirroring tests/integration/test_render_captions_determinism.py.

Timing values here are hand-built CaptionCue/CaptionWord objects because
these tests assert SERIALIZATION STRUCTURE (line counts, tiling, tag
placement), not alignment-derived timing - the derivation side is covered
by test_captions.py against the real fixture, including one invariant here
that derived words reproduce each cue's text exactly.
"""

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from app.models.narration import NarrationModel
from app.renderer.captions import (
    CaptionCue,
    CaptionStyle,
    CaptionWord,
    cue_list_content_hash,
    derive_caption_cues,
    format_ass_time,
    highlight_colour_to_ass,
    serialize_ass,
)
from app.renderer.video_filters import escape_ffmpeg_filter_path
from app.schemas.timeline import Timeline

_STYLE = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "captions_test_project.json"

_TAG_PATTERN = re.compile(r"\{\\[^}]*\}")


def _cue(
    text: str, start: float, end: float, *word_windows: tuple[str, float, float]
) -> CaptionCue:
    return CaptionCue(
        start_s=start,
        end_s=end,
        text=text,
        words=tuple(CaptionWord(text=t, start_s=s, end_s=e) for t, s, e in word_windows),
    )


def _dialogue_lines(ass: str) -> list[str]:
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


# ---------------------------------------------------------------------------
# Backward compatibility: word-less cues are byte-for-byte unchanged
# ---------------------------------------------------------------------------


def test_a_word_less_cue_serializes_as_the_single_plain_line_it_always_did():
    cue = CaptionCue(start_s=7.059, end_s=10.5, text="hello world")
    ass = serialize_ass([cue], _STYLE)
    dialogue = _dialogue_lines(ass)
    assert dialogue == ["Dialogue: 0,0:00:07.06,0:00:10.50,Caption,,0,0,0,,hello world"]


# ---------------------------------------------------------------------------
# Option 2 emission shape (style_extensions.md §3.3)
# ---------------------------------------------------------------------------


def test_each_word_gets_its_own_dialogue_line_with_only_that_word_wrapped():
    cue = _cue(
        "no one will say",
        1.0,
        2.0,
        ("no", 1.0, 1.2),
        ("one", 1.2, 1.5),
        ("will", 1.5, 1.7),
        ("say", 1.7, 2.0),
    )
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))
    assert len(dialogue) == 4
    # Whole phrase re-emitted on every line (tags stripped for comparison -
    # the override tags sit between tokens on tagged lines)...
    assert all(
        _TAG_PATTERN.sub("", line).split("Caption,,0,0,0,,", 1)[1] == "no one will say"
        for line in dialogue
    )
    # ...with exactly the active word wrapped in the yellow override.
    assert "{\\c&H00FFFF&}no{\\r} one will say" in dialogue[0]
    assert "no {\\c&H00FFFF&}one{\\r} will say" in dialogue[1]
    assert "no one {\\c&H00FFFF&}will{\\r} say" in dialogue[2]
    assert "no one will {\\c&H00FFFF&}say{\\r}" in dialogue[3]


def test_word_windows_tile_the_cue_exactly_with_no_gaps_or_overlaps():
    cue = _cue(
        "alpha beta gamma",
        10.0,
        13.5,
        ("alpha", 10.4, 11.0),
        ("beta", 11.25, 12.0),
        ("gamma", 12.5, 13.0),
    )
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))

    def window(line: str) -> tuple[str, str]:
        fields = line.split(",")
        return fields[1], fields[2]

    windows = [window(line) for line in dialogue]
    assert len(windows) == 3
    # First window opens at the cue's start even if the first word starts late.
    assert windows[0][0] == format_ass_time(10.0)
    # Line i ends exactly where line i+1 begins (inter-word pauses stay lit).
    assert windows[0][1] == windows[1][0] == format_ass_time(11.25)
    assert windows[1][1] == windows[2][0] == format_ass_time(12.5)
    # Last window runs to the cue's end even if the last word ends early.
    assert windows[2][1] == format_ass_time(13.5)


def test_a_single_word_cue_is_one_line_spanning_the_whole_cue():
    cue = _cue("boom", 5.0, 6.0, ("boom", 5.1, 5.9))
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))
    assert len(dialogue) == 1
    assert dialogue[0].startswith("Dialogue: 0,0:00:05.00,0:00:06.00,Caption")
    assert "{\\c&H00FFFF&}boom{\\r}" in dialogue[0]


def test_punctuation_stays_attached_inside_the_highlight_wrap():
    cue = _cue("unbelievable, right?", 0.0, 2.0, ("unbelievable,", 0.0, 1.0), ("right?", 1.0, 2.0))
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))
    assert "{\\c&H00FFFF&}unbelievable,{\\r}" in dialogue[0]
    assert "{\\c&H00FFFF&}right?{\\r}" in dialogue[1]


# ---------------------------------------------------------------------------
# Edge cases from style_extensions.md §3.5
# ---------------------------------------------------------------------------


def test_a_zero_duration_middle_word_emits_no_line_and_coverage_survives():
    """libass rejects zero-duration events (§3.5): the dead word gets no
    line of its own; its instant is covered by the neighbouring window."""
    cue = _cue(
        "gone fast slow",
        0.0,
        3.0,
        ("gone", 0.0, 1.0),
        ("fast", 1.0, 1.0),  # collapsed alignment window
        ("slow", 1.0, 3.0),
    )
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))
    assert len(dialogue) == 2
    for line in dialogue:
        fields = line.split(",")
        assert fields[2] > fields[1], f"zero-duration event emitted: {line}"
    assert "{\\c&H00FFFF&}gone{\\r}" in dialogue[0]
    assert "{\\c&H00FFFF&}slow{\\r}" in dialogue[1]


def test_a_collapsed_single_word_cue_still_covers_the_whole_cue():
    """A lone word whose alignment collapsed gets its line clamped to the
    cue's own bounds - never a zero-duration event, and consistent with
    the single-word rule above (one word = highlighted across its cue)."""
    cue = _cue("stuck", 0.0, 1.0, ("stuck", 0.5, 0.5))
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))
    assert dialogue == [
        "Dialogue: 0,0:00:00.00,0:00:01.00,Caption,,0,0,0,,{\\c&H00FFFF&}stuck{\\r}"
    ]


def test_braces_and_backslashes_in_words_are_escaped_inside_the_tag_wrap():
    cue = _cue("a {b} c", 0.0, 2.0, ("a", 0.0, 0.5), ("{b}", 0.5, 1.5), ("c", 1.5, 2.0))
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))
    # The escaped token sits between the override tags unharmed.
    assert "{\\c&H00FFFF&}\\{b\\}{\\r}" in dialogue[1]


def test_non_ascii_hinglish_tokens_pass_through_unmangled():
    cue = _cue("yeh kya hai", 0.0, 2.0, ("yeh", 0.0, 0.6), ("kya", 0.6, 1.3), ("hai", 1.3, 2.0))
    ass = serialize_ass([cue], _STYLE)
    # Tags stripped: every line carries the unmangled Hinglish phrase.
    for line in _dialogue_lines(ass):
        assert _TAG_PATTERN.sub("", line).split("Caption,,0,0,0,,", 1)[1] == "yeh kya hai"
    assert "{\\c&H00FFFF&}kya{\\r}" in ass


def test_highlighted_serialization_is_deterministic():
    cue = _cue(
        "same words twice",
        0.0,
        2.0,
        ("same", 0.0, 0.7),
        ("words", 0.7, 1.4),
        ("twice", 1.4, 2.0),
    )
    assert serialize_ass([cue], _STYLE) == serialize_ass([cue], _STYLE)


# ---------------------------------------------------------------------------
# K16.2: size + weight on the highlight (retention_fast only)
# ---------------------------------------------------------------------------


_RETENTION_HIGHLIGHT = CaptionStyle(
    resolution=(720, 1280),
    font_family="Noto Sans Devanagari",
    highlight_size_fraction=0.08,
    highlight_bold=True,
)
# 0.08 * max(720, 1280) = 0.08 * 1280 = 102
_RETENTION_OVERRIDE = "{\\fs102\\b1\\c&H00FFFF&}"


def test_default_caption_style_highlight_is_colour_only_no_fs_no_bold():
    """K16.2: unset size/bold keep the historical yellow-only override."""
    cue = _cue("no one", 0.0, 1.0, ("no", 0.0, 0.5), ("one", 0.5, 1.0))
    dialogue = _dialogue_lines(serialize_ass([cue], _STYLE))
    assert "{\\c&H00FFFF&}no{\\r}" in dialogue[0]
    assert "\\fs" not in dialogue[0]
    assert "\\b1" not in dialogue[0]


def test_retention_fast_highlight_override_is_fs102_bold_yellow_on_720x1280():
    """K16.2: pin the exact override string and the 102px arithmetic.
    Colour-only default stays yellow; palette accent is a separate pin."""
    cue = _cue("no one", 0.0, 1.0, ("no", 0.0, 0.5), ("one", 0.5, 1.0))
    dialogue = _dialogue_lines(serialize_ass([cue], _RETENTION_HIGHLIGHT))
    assert f"{_RETENTION_OVERRIDE}no{{\\r}}" in dialogue[0]
    assert dialogue[0].count(_RETENTION_OVERRIDE) == 1
    assert round(1280 * 0.08) == 102


def test_highlight_colour_hex_to_ass_bbggrr():
    """K16.3: `#RRGGBB` → ASS `&HBBGGRR&`; invalid/missing → yellow."""
    assert highlight_colour_to_ass("#00D9FF") == "\\c&HFFD900&"
    assert highlight_colour_to_ass("#FFC300") == "\\c&H00C3FF&"
    assert highlight_colour_to_ass(None) == "\\c&H00FFFF&"
    assert highlight_colour_to_ass("not-a-hex") == "\\c&H00FFFF&"
    assert highlight_colour_to_ass("#00D9F") == "\\c&H00FFFF&"


def test_retention_highlight_with_cyan_accent_is_fs102_bold_cyan():
    """K16.3: CaptionStyle.highlight_colour `#00D9FF` + size 0.08 bold
    → `{\\fs102\\b1\\c&HFFD900&}` on 720×1280."""
    style = CaptionStyle(
        resolution=(720, 1280),
        font_family="Noto Sans Devanagari",
        highlight_size_fraction=0.08,
        highlight_bold=True,
        highlight_colour="#00D9FF",
    )
    cue = _cue("no one", 0.0, 1.0, ("no", 0.0, 0.5), ("one", 0.5, 1.0))
    dialogue = _dialogue_lines(serialize_ass([cue], style))
    override = "{\\fs102\\b1\\c&HFFD900&}"
    assert f"{override}no{{\\r}}" in dialogue[0]
    assert "\\c&H00FFFF&" not in dialogue[0]


def test_word_less_cues_stay_byte_identical_under_retention_highlight_style():
    """K16.2: size/weight only wrap worded cues; plain Dialogue lines
    stay byte-identical to a same-resolution colour-only style."""
    cue = CaptionCue(start_s=7.059, end_s=10.5, text="hello world")
    same_res_plain = CaptionStyle(
        resolution=(720, 1280), font_family="Noto Sans Devanagari"
    )
    retention_lines = _dialogue_lines(serialize_ass([cue], _RETENTION_HIGHLIGHT))
    plain_lines = _dialogue_lines(serialize_ass([cue], same_res_plain))
    assert retention_lines == [
        "Dialogue: 0,0:00:07.06,0:00:10.50,Caption,,0,0,0,,hello world"
    ]
    assert retention_lines == plain_lines
    assert serialize_ass([cue], _RETENTION_HIGHLIGHT) == serialize_ass(
        [cue], same_res_plain
    )


# ---------------------------------------------------------------------------
# Fingerprint coupling (style_extensions.md §9 RV-A1)
# ---------------------------------------------------------------------------


def test_the_content_hash_changes_when_a_cue_gains_word_timing():
    """RV-A1 regression, mirroring analysis.md's `sfx_whoosh_enabled`
    fingerprint test: a Feature-A cue must hash DIFFERENTLY from its
    pre-Feature-A equivalent, or `get_completed_by_fingerprint` would
    serve every already-rendered project its old non-highlighted bytes
    forever (cache HIT = stale output)."""
    plain = CaptionCue(start_s=1.0, end_s=2.0, text="no one will say")
    worded = _cue(
        "no one will say",
        1.0,
        2.0,
        ("no", 1.0, 1.2),
        ("one", 1.2, 1.5),
        ("will", 1.5, 1.7),
        ("say", 1.7, 2.0),
    )
    assert cue_list_content_hash([plain]) != cue_list_content_hash([worded])


def test_the_content_hash_changes_when_word_timings_change_but_text_does_not():
    cue_a = _cue("hello world", 0.0, 2.0, ("hello", 0.0, 1.0), ("world", 1.0, 2.0))
    cue_b = _cue("hello world", 0.0, 2.0, ("hello", 0.0, 1.4), ("world", 1.4, 2.0))
    assert cue_list_content_hash([cue_a]) != cue_list_content_hash([cue_b])


def test_the_content_hash_remains_deterministic_for_word_carrying_cues():
    cue = _cue("hello world", 0.0, 2.0, ("hello", 0.0, 1.0), ("world", 1.0, 2.0))
    assert cue_list_content_hash([cue]) == cue_list_content_hash(list([cue]))


def test_the_content_hash_of_word_less_cues_is_stable_and_legacy_shaped():
    plain = CaptionCue(start_s=1.0, end_s=2.0, text="hello world")
    assert cue_list_content_hash([plain]) == cue_list_content_hash(list([plain]))


# ---------------------------------------------------------------------------
# Derivation wiring: real fixture, real alignment arrays
# ---------------------------------------------------------------------------


def _fixture_timeline_and_rows() -> tuple[Timeline, list[NarrationModel]]:
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    timeline = Timeline.model_validate(data["timeline_document"])

    def row(entry: dict) -> NarrationModel:
        return NarrationModel(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            scene_id=entry["scene_id"],
            provider=entry["provider"],
            voice_id=entry["voice_id"],
            model_id=entry["model_id"],
            output_format=entry["output_format"],
            text=entry["text"],
            content_hash=entry["content_hash"],
            local_path=f"/fake/{entry['content_hash']}.mp3",
            alignment=entry["alignment"],
            character_count=entry["character_count"],
            cost_cents=entry["cost_cents"],
        )

    voice_id = timeline.metadata.voice_id
    by_scene_and_voice = {(n["scene_id"], n["voice_id"]): n for n in data["narrations"]}
    rows = [row(by_scene_and_voice[(scene.id, voice_id)]) for scene in timeline.scenes]
    return timeline, rows


def test_derived_cues_carry_words_reproducing_their_own_text_from_real_alignment():
    """The words tuple must come from the SAME alignment arrays as the cue
    times (§3.2): reconstructed-by-whitespace cue text must equal the cue's
    text, normalized. Any drift means a second timing source crept in."""
    timeline, rows = _fixture_timeline_and_rows()
    cues = derive_caption_cues(timeline, rows)
    assert cues
    for cue in cues:
        assert cue.words
        assert " ".join(w.text for w in cue.words) == " ".join(cue.text.split())
        # Every word lives inside its cue's window.
        for word in cue.words:
            assert cue.start_s - 1e-6 <= word.start_s <= word.end_s <= cue.end_s + 1e-6


def test_derived_fixture_cues_serialize_with_highlight_lines():
    timeline, rows = _fixture_timeline_and_rows()
    cues = derive_caption_cues(timeline, rows)
    ass = serialize_ass(cues, _STYLE)
    dialogue = _dialogue_lines(ass)
    assert all("{\\c&H00FFFF&}" in line for line in dialogue)


# ---------------------------------------------------------------------------
# Real burn-in: the generated .ass must survive an actual libass render
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_generated_ass_burns_through_a_real_libass_render(tmp_path: Path):
    """Known flake (§9 RV-A4): under some combined-suite run orders on
    Windows this has failed with a DLL-load-class exit code while passing
    reliably in isolation - pytest capture interacting with ffmpeg/
    fontconfig file handles, not a captions.py defect. If it flakes in CI,
    isolate it into its own pytest session before treating it as a
    regression."""
    cue = _cue(
        "this actually works",
        0.0,
        2.0,
        ("this", 0.0, 0.6),
        ("actually", 0.6, 1.3),
        ("works", 1.3, 2.0),
    )
    ass_path = tmp_path / "highlight.ass"
    ass_path.write_text(serialize_ass([cue], _STYLE), encoding="utf-8")
    out_path = tmp_path / "out.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=2:r=10",
            "-vf",
            f"subtitles=filename='{escape_ffmpeg_filter_path(ass_path)}'",
            "-frames:v",
            "20",
            "-y",
            out_path.as_posix(),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out_path.stat().st_size > 0
