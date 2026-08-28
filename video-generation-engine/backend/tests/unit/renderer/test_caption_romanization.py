"""Caption romanization consumption (caption_romanization.md §3.4 / §4).

Pure functions of fixtures. No DB, no live LLM. Run with `--noconftest`.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.models.narration import NarrationModel
from app.renderer.captions import (
    CaptionStyle,
    cue_list_content_hash,
    derive_caption_cues,
    serialize_ass,
)
from app.renderer.text_cards import derive_text_card_cues
from app.schemas.timeline import ProducedBy, Scene, Shot, ShotIntent, Timeline, TimelineStatus

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "captions_test_project.json"

_SRC = "एक Indian guru जिसके पास 90 Rolls-Royce थीं।"
_CAP = "ek Indian guru jiske paas 90 Rolls-Royce theen."

_STYLE = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")


def _load_fixture() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _timeline() -> Timeline:
    return Timeline.model_validate(_load_fixture()["timeline_document"])


def _narration_row(entry: dict) -> NarrationModel:
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


def _active_voice_rows(timeline: Timeline) -> list[NarrationModel]:
    narrations = _load_fixture()["narrations"]
    by_scene_and_voice = {(n["scene_id"], n["voice_id"]): n for n in narrations}
    voice_id = timeline.metadata.voice_id
    return [_narration_row(by_scene_and_voice[(scene.id, voice_id)]) for scene in timeline.scenes]


def _end_after_n_words(text: str, n: int) -> int:
    """Exclusive character offset just past the nth whitespace-delimited
    token — a shot-span boundary that sits on a word boundary, never
    mid-token."""
    seen = 0
    in_token = False
    last = 0
    for i, ch in enumerate(text):
        if ch.isspace():
            if in_token and seen == n:
                return i
            in_token = False
        else:
            if not in_token:
                seen += 1
                in_token = True
            last = i
            if seen == n and i + 1 == len(text):
                return i + 1
    return last + 1


def _uniform_row(scene_id: str, text: str) -> NarrationModel:
    n = len(text)
    return NarrationModel(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        scene_id=scene_id,
        provider="elevenlabs",
        voice_id="v1",
        model_id="m1",
        output_format="mp3_44100_128",
        text=text,
        content_hash="deadbeef",
        local_path="/fake/deadbeef.mp3",
        alignment={
            "characters": list(text),
            "character_start_times_seconds": [i * 0.1 for i in range(n)],
            "character_end_times_seconds": [(i + 1) * 0.1 for i in range(n)],
        },
        character_count=n,
        cost_cents=0,
    )


def _mixed_timeline(
    *,
    caption_text: str | None,
    shot_spans: list[tuple[int, int]],
    narration_text: str = _SRC,
    caption_word_groups: list[int] | None = None,
) -> Timeline:
    fixture = _load_fixture()["timeline_document"]
    template = Timeline.model_validate(fixture)
    scene = template.scenes[0].model_copy(deep=True)
    scene.narration_text = narration_text
    scene.caption_text = caption_text
    scene.caption_word_groups = caption_word_groups
    scene.shots = [
        scene.shots[0].model_copy(
            update={"id": f"sh_{i}", "narration_span": span, "text_card": None}
        )
        for i, span in enumerate(shot_spans)
    ]
    return template.model_copy(update={"scenes": [scene]})


# ---------------------------------------------------------------------------
# Fallback: caption_text=None is today's output
# ---------------------------------------------------------------------------


def test_caption_text_none_matches_todays_fixture_output():
    timeline = _timeline()
    assert all(scene.caption_text is None for scene in timeline.scenes)
    rows = _active_voice_rows(timeline)
    assert derive_caption_cues(timeline, rows) == derive_caption_cues(
        timeline.model_copy(deep=True), rows
    )


def test_explicit_none_matches_omitted_caption_text():
    timeline = _mixed_timeline(caption_text=None, shot_spans=[(0, len(_SRC))])
    rows = [_uniform_row(timeline.scenes[0].id, _SRC)]
    omitted = derive_caption_cues(timeline, rows)
    explicit = derive_caption_cues(
        timeline.model_copy(
            update={"scenes": [timeline.scenes[0].model_copy(update={"caption_text": None})]}
        ),
        rows,
    )
    assert omitted == explicit


# ---------------------------------------------------------------------------
# Word-index bridge
# ---------------------------------------------------------------------------


def test_cue_text_maps_to_caption_text_words_by_index():
    """A two-shot split on a word boundary: each cue displays the
    corresponding caption_text words, not a character slice of
    caption_text (those offsets are not comparable)."""
    split_at = _end_after_n_words(_SRC, 3)
    assert _SRC[split_at - 1] != " "  # ended on the third word, not a space
    timeline = _mixed_timeline(caption_text=_CAP, shot_spans=[(0, split_at), (split_at, len(_SRC))])
    rows = [_uniform_row(timeline.scenes[0].id, _SRC)]
    cues = derive_caption_cues(timeline, rows)

    assert [c.text for c in cues] == [
        "ek Indian guru",
        "jiske paas 90 Rolls-Royce theen.",
    ]
    assert [w.text for w in cues[0].words] == ["ek", "Indian", "guru"]
    assert [w.text for w in cues[1].words] == ["jiske", "paas", "90", "Rolls-Royce", "theen."]
    # Latin words copied through at the same index.
    assert "Indian" in cues[0].text
    assert "90" in cues[1].text
    assert "Rolls-Royce" in cues[1].text
    # No residual Devanagari on screen.
    assert not any("\u0900" <= ch <= "\u097f" for c in cues for ch in c.text)


def test_per_word_timings_are_byte_identical_with_and_without_romanization():
    """§2.1, pinned: swapping the displayed string changes nothing about
    timing as long as word structure lines up."""
    split_at = _end_after_n_words(_SRC, 3)
    spans = [(0, split_at), (split_at, len(_SRC))]
    plain = _mixed_timeline(caption_text=None, shot_spans=spans)
    romanized = _mixed_timeline(caption_text=_CAP, shot_spans=spans)
    rows = [_uniform_row(plain.scenes[0].id, _SRC)]

    plain_cues = derive_caption_cues(plain, rows)
    roman_cues = derive_caption_cues(romanized, rows)

    assert len(plain_cues) == len(roman_cues)
    for p, r in zip(plain_cues, roman_cues, strict=True):
        assert p.start_s == r.start_s
        assert p.end_s == r.end_s
        assert len(p.words) == len(r.words)
        for pw, rw in zip(p.words, r.words, strict=True):
            assert pw.start_s == rw.start_s
            assert pw.end_s == rw.end_s
            assert pw.text != rw.text or pw.text.isascii()


def test_word_count_mismatch_falls_back_to_narration_text():
    """A corrupt caption_text must not desync Feature A highlighting."""
    spans = [(0, len(_SRC))]
    plain = _mixed_timeline(caption_text=None, shot_spans=spans)
    bad = _mixed_timeline(caption_text="ek Indian guru", shot_spans=spans)
    rows = [_uniform_row(plain.scenes[0].id, _SRC)]
    assert derive_caption_cues(plain, rows) == derive_caption_cues(bad, rows)


def test_real_fixture_timings_identical_under_same_word_count_placeholder():
    """Same claim as the crafted two-shot case, against real alignment
    arrays: placeholder tokens (one per narration word) must not move
    any cue or word window."""
    timeline = _timeline()
    rows = _active_voice_rows(timeline)
    plain = derive_caption_cues(timeline, rows)

    romanized_scenes = []
    for scene in timeline.scenes:
        n = len(scene.narration_text.split())
        placeholder = " ".join(f"w{i}" for i in range(n))
        romanized_scenes.append(scene.model_copy(update={"caption_text": placeholder}))
    romanized = timeline.model_copy(update={"scenes": romanized_scenes})
    roman = derive_caption_cues(romanized, rows)

    assert len(plain) == len(roman)
    for p, r in zip(plain, roman, strict=True):
        assert (p.start_s, p.end_s) == (r.start_s, r.end_s)
        assert [(w.start_s, w.end_s) for w in p.words] == [(w.start_s, w.end_s) for w in r.words]


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def test_romanized_cues_hash_differently_from_unromanized():
    spans = [(0, len(_SRC))]
    plain = _mixed_timeline(caption_text=None, shot_spans=spans)
    romanized = _mixed_timeline(caption_text=_CAP, shot_spans=spans)
    rows = [_uniform_row(plain.scenes[0].id, _SRC)]
    h_plain = cue_list_content_hash(derive_caption_cues(plain, rows))
    h_roman = cue_list_content_hash(derive_caption_cues(romanized, rows))
    assert h_plain != h_roman
    assert h_roman == cue_list_content_hash(derive_caption_cues(romanized, rows))


# ---------------------------------------------------------------------------
# Non-ASCII / ASS escaping
# ---------------------------------------------------------------------------


_TAG_PATTERN = re.compile(r"\{\\[^}]*\}")


def test_hinglish_round_trips_through_ass_without_mangling():
    spans = [(0, len(_SRC))]
    timeline = _mixed_timeline(caption_text=_CAP, shot_spans=spans)
    rows = [_uniform_row(timeline.scenes[0].id, _SRC)]
    cues = derive_caption_cues(timeline, rows)
    assert cues[0].text == _CAP
    ass = serialize_ass(cues, _STYLE)
    # Feature A wraps the highlighted word in override tags, so the raw
    # phrase is never a substring of the event line. Strip tags: every
    # dialogue line must still carry the unmangled Hinglish.
    dialogue = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    stripped = [_TAG_PATTERN.sub("", line) for line in dialogue]
    assert stripped
    assert all(_CAP in line for line in stripped)
    # Braces/backslashes still escaped if they appear in a display word.
    braced = _mixed_timeline(
        caption_text=_CAP.replace("guru", "gur{u}"),
        shot_spans=spans,
    )
    braced_ass = serialize_ass(derive_caption_cues(braced, rows), _STYLE)
    assert "gur\\{u\\}" in braced_ass
    assert "gur{u}" not in braced_ass


# ---------------------------------------------------------------------------
# Text cards are a different overlay and must not move
# ---------------------------------------------------------------------------


def test_text_card_cues_are_unchanged_by_caption_romanization():
    shots = [
        Shot(
            id="sh_01",
            order=0,
            intent=ShotIntent.INTRODUCE,
            duration_s=3.0,
            text_card="90 ROLLS-ROYCE",
        )
    ]
    scene = Scene(
        id="sc_01",
        order=0,
        title="s",
        duration_s=3.0,
        narration_text=_SRC,
        caption_text=_CAP,
        shots=shots,
    )
    romanized = Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )
    plain = romanized.model_copy(
        update={"scenes": [scene.model_copy(update={"caption_text": None})]}
    )
    assert derive_text_card_cues(romanized) == derive_text_card_cues(plain)
    assert derive_text_card_cues(romanized)[0].text == "90 ROLLS-ROYCE"


# ---------------------------------------------------------------------------
# §10 N->1 word grouping: bridge, straddle fallback, back-compat, fingerprint
# ---------------------------------------------------------------------------

_YEAR_WORDS = ["उन्नीस", "सौ", "इकतीस", "में", "उनका", "India", "में", "जन्म", "हुआ."]
_YEAR_SRC = " ".join(_YEAR_WORDS)
_YEAR_CAP_WORDS = ["1931", "mein", "unka", "India", "mein", "janm", "hua."]
_YEAR_CAP = " ".join(_YEAR_CAP_WORDS)
_YEAR_GROUPS = [3, 1, 1, 1, 1, 1, 1]
# Same word count as `_YEAR_SRC` (9), all `covers: 1` - the unmerged
# comparison point for the back-compat pair below.
_YEAR_UNMERGED_WORDS = ["unnis", "sau", "ikatees", "mein", "unka", "India", "mein", "janm", "hua."]
_YEAR_UNMERGED_CAP = " ".join(_YEAR_UNMERGED_WORDS)


def _word_boundaries(text: str) -> list[tuple[int, int]]:
    """(start, end_exclusive) for each whitespace-delimited word, in
    `str.split()` order - used here only to compute expected char
    offsets for assertions, never as a second tokeniser inside the
    production bridge (RV-R4)."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, ch in enumerate(text):
        if ch.isspace():
            if start is not None:
                spans.append((start, i))
                start = None
        elif start is None:
            start = i
    if start is not None:
        spans.append((start, len(text)))
    return spans


def test_group_of_three_narration_words_becomes_one_caption_word():
    timeline = _mixed_timeline(
        caption_text=_YEAR_CAP,
        shot_spans=[(0, len(_YEAR_SRC))],
        narration_text=_YEAR_SRC,
        caption_word_groups=_YEAR_GROUPS,
    )
    rows = [_uniform_row(timeline.scenes[0].id, _YEAR_SRC)]
    cues = derive_caption_cues(timeline, rows)

    assert len(cues) == 1
    words = cues[0].words
    # 9 narration words, 7 groups -> 7 CaptionWords, first one merged.
    assert [w.text for w in words] == _YEAR_CAP_WORDS
    assert cues[0].text == _YEAR_CAP


def test_merged_words_start_and_end_span_the_whole_source_group():
    timeline = _mixed_timeline(
        caption_text=_YEAR_CAP,
        shot_spans=[(0, len(_YEAR_SRC))],
        narration_text=_YEAR_SRC,
        caption_word_groups=_YEAR_GROUPS,
    )
    rows = [_uniform_row(timeline.scenes[0].id, _YEAR_SRC)]
    cues = derive_caption_cues(timeline, rows)

    boundaries = _word_boundaries(_YEAR_SRC)
    # `_uniform_row` times every character at exactly 0.1s: char i starts
    # at i*0.1 and ends at (i+1)*0.1, so a word spanning
    # [start, end_exclusive) has start_s = start*0.1, end_s = end*0.1.
    expected_start = boundaries[0][0] * 0.1
    expected_end = boundaries[2][1] * 0.1
    merged = cues[0].words[0]
    assert merged.text == "1931"
    assert merged.start_s == expected_start
    assert merged.end_s == expected_end
    # The next (unmerged) word starts exactly where narration word 3 does.
    assert cues[0].words[1].start_s == boundaries[3][0] * 0.1


def test_all_ones_groups_matches_omitted_groups():
    """§10.7 back-compat pair: `groups=[1,1,...]` must be identical to
    `caption_word_groups=None`, both applied to the SAME caption text."""
    spans = [(0, len(_YEAR_SRC))]
    no_groups = _mixed_timeline(
        caption_text=_YEAR_UNMERGED_CAP,
        shot_spans=spans,
        narration_text=_YEAR_SRC,
        caption_word_groups=None,
    )
    ones_groups = _mixed_timeline(
        caption_text=_YEAR_UNMERGED_CAP,
        shot_spans=spans,
        narration_text=_YEAR_SRC,
        caption_word_groups=[1] * len(_YEAR_WORDS),
    )
    rows = [_uniform_row(no_groups.scenes[0].id, _YEAR_SRC)]
    assert derive_caption_cues(no_groups, rows) == derive_caption_cues(ones_groups, rows)


def test_group_sum_mismatch_falls_back_like_a_word_count_mismatch():
    """A corrupt `caption_word_groups` (wrong total) must not desync
    Feature A highlighting any more than a corrupt `caption_text` does."""
    spans = [(0, len(_YEAR_SRC))]
    plain = _mixed_timeline(caption_text=None, shot_spans=spans, narration_text=_YEAR_SRC)
    bad = _mixed_timeline(
        caption_text=_YEAR_CAP,
        shot_spans=spans,
        narration_text=_YEAR_SRC,
        caption_word_groups=[2, 1, 1, 1, 1, 1, 1],  # sums to 8, not 9
    )
    rows = [_uniform_row(plain.scenes[0].id, _YEAR_SRC)]
    assert derive_caption_cues(plain, rows) == derive_caption_cues(bad, rows)


def test_merged_group_cue_hash_differs_from_unmerged():
    spans = [(0, len(_YEAR_SRC))]
    unmerged = _mixed_timeline(
        caption_text=_YEAR_UNMERGED_CAP,
        shot_spans=spans,
        narration_text=_YEAR_SRC,
        caption_word_groups=[1] * len(_YEAR_WORDS),
    )
    merged = _mixed_timeline(
        caption_text=_YEAR_CAP,
        shot_spans=spans,
        narration_text=_YEAR_SRC,
        caption_word_groups=_YEAR_GROUPS,
    )
    rows = [_uniform_row(unmerged.scenes[0].id, _YEAR_SRC)]
    h_unmerged = cue_list_content_hash(derive_caption_cues(unmerged, rows))
    h_merged = cue_list_content_hash(derive_caption_cues(merged, rows))
    assert h_unmerged != h_merged


def test_group_straddling_a_cue_split_falls_back_whole_scene(caplog):
    """§10.5: forcing `_split_if_too_long` to cut inside the merged
    year-group (verified directly: with `max_chars=10` the whole-scene
    segmentation of `_YEAR_SRC` splits at char 10, which lands strictly
    inside the group covering narration words 0..2) must fall the WHOLE
    scene back to `narration_text`, with a warning naming the scene -
    never a torn CaptionWord straddling two cues."""
    spans = [(0, len(_YEAR_SRC))]
    timeline = _mixed_timeline(
        caption_text=_YEAR_CAP,
        shot_spans=spans,
        narration_text=_YEAR_SRC,
        caption_word_groups=_YEAR_GROUPS,
    )
    plain = _mixed_timeline(caption_text=None, shot_spans=spans, narration_text=_YEAR_SRC)
    rows = [_uniform_row(timeline.scenes[0].id, _YEAR_SRC)]

    with caplog.at_level(logging.WARNING, logger="app.renderer.captions"):
        grouped_cues = derive_caption_cues(timeline, rows, max_chars=10)
    plain_cues = derive_caption_cues(plain, rows, max_chars=10)

    # The straddle is real: more than one cue was produced.
    assert len(grouped_cues) > 1
    assert grouped_cues == plain_cues
    assert not any("1931" in c.text for c in grouped_cues)
    warnings = [r for r in caplog.records if r.name == "app.renderer.captions"]
    assert any("group_straddles_cue" in r.getMessage() for r in warnings)
    assert any(getattr(r, "scene_id", None) == timeline.scenes[0].id for r in warnings)
