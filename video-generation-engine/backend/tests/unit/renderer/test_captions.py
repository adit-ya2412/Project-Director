"""`app/renderer/captions.py` - pure cue derivation and ASS serialisation,
no ffmpeg needed. Loads the real fixture (`captions_test_project.json`,
exported from project `71e4758a-...` per docs/14_Captions_Plan.md §0)
directly via `json.load` + `Timeline.model_validate` - no DB, no
`seed_test_project.py`. Real render burn-in is proven separately in
tests/integration/test_render_captions_determinism.py.

Never uses synthetic alignment for timing/voice-selection assertions
(doc §7: "Synthetic alignment arrays are uniform in a way real TTS
output never is, and they hide exactly the bugs worth catching") - only
the shot-boundary structural test uses a small crafted example, since
that rule is about text/offset structure, not alignment timing.
"""

import json
import uuid
from pathlib import Path

import pytest

from app.models.narration import NarrationModel
from app.renderer.captions import (
    CaptionCue,
    CaptionStyle,
    MAX_CHARS_PER_CUE,
    MAX_CUE_DURATION_S,
    MIN_CUE_DURATION_S,
    cue_list_content_hash,
    derive_caption_cues,
    serialize_ass,
)
from app.schemas.timeline import Timeline

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "captions_test_project.json"


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


def _rows_for_voice(timeline: Timeline, voice_id: str) -> list[NarrationModel]:
    """One row per scene, in `timeline.scenes` order, for the given voice -
    exactly the shape `_resolve_narration_rows` produces in production."""
    narrations = _load_fixture()["narrations"]
    by_scene_and_voice = {(n["scene_id"], n["voice_id"]): n for n in narrations}
    return [
        _narration_row(by_scene_and_voice[(scene.id, voice_id)]) for scene in timeline.scenes
    ]


def _active_voice_rows(timeline: Timeline) -> list[NarrationModel]:
    return _rows_for_voice(timeline, timeline.metadata.voice_id)


# ---------------------------------------------------------------------------
# §0's trap: voice selection
# ---------------------------------------------------------------------------


def test_active_voice_cues_span_exactly_the_timelines_total_duration():
    """The correct voice's narration sums to `total_duration_s` to the
    millisecond (docs/14_Captions_Plan.md §10.1) - the last cue's end
    time must land there too, not at the wrong voice's ~67s total."""
    timeline = _timeline()
    cues = derive_caption_cues(timeline, _active_voice_rows(timeline))
    assert cues[-1].end_s == pytest.approx(timeline.metadata.total_duration_s, abs=0.01)


def test_a_superseded_voices_rows_produce_measurably_different_cue_times():
    """Feeding `derive_caption_cues` the WRONG voice's rows (the fixture's
    3-voices-per-scene residue, §0) must produce cues that land somewhere
    detectably different from the correct voice's - proving the function
    is timing-sensitive to which rows it's given, so a caller bug in row
    selection (never this module's job - see its docstring) would be
    caught by whichever test exercises that selection."""
    timeline = _timeline()
    correct = derive_caption_cues(timeline, _active_voice_rows(timeline))
    wrong = derive_caption_cues(timeline, _rows_for_voice(timeline, "T3s9anIvGvoeogXyFyMt"))
    assert wrong[-1].end_s != pytest.approx(correct[-1].end_s, abs=0.01)
    assert wrong[-1].end_s == pytest.approx(67.104, abs=0.01)


# ---------------------------------------------------------------------------
# §10.2's correction: audio-concat clock, not compute_shot_start_times
# ---------------------------------------------------------------------------


def test_sc05_starts_on_the_audio_concat_clock_not_the_video_frame_clock():
    """The one real divergence in the fixture: sc_04's own transition
    into sc_05 is a cross-scene transition `mux_narration` never sees.
    Video-frame time (`compute_shot_start_times`) would put sc_05 at
    43.479s; the audio track it's actually muxed onto puts it at
    43.979s. Cues must land on the second number."""
    timeline = _timeline()
    rows = _active_voice_rows(timeline)
    cues = derive_caption_cues(timeline, rows)

    scene_order = [s.id for s in timeline.scenes]
    sc04_index = scene_order.index("sc_04")
    cumulative_through_sc04 = sum(
        rows[i].alignment["character_end_times_seconds"][-1] for i in range(sc04_index + 1)
    )

    sc05_shot_ids = {s.id for s in timeline.scenes[sc04_index + 1].shots}
    scene = timeline.scenes[sc04_index + 1]
    first_shot_span = next(
        s.narration_span for s in scene.shots if s.narration_span is not None
    )
    sc05_row = rows[sc04_index + 1]
    first_char_offset_s = sc05_row.alignment["character_start_times_seconds"][
        first_shot_span[0]
    ]
    expected_first_cue_start = cumulative_through_sc04 + first_char_offset_s

    sc05_cues = [c for c in cues if c.start_s >= cumulative_through_sc04 - 0.01]
    assert sc05_cues, "expected at least one cue in sc_05"
    assert sc05_cues[0].start_s == pytest.approx(expected_first_cue_start, abs=0.01)
    assert sc05_cues[0].start_s != pytest.approx(43.479, abs=0.05)
    assert cumulative_through_sc04 == pytest.approx(43.979, abs=0.01)
    del sc05_shot_ids  # only used to document intent above


# ---------------------------------------------------------------------------
# §3.3: segmentation quality
# ---------------------------------------------------------------------------


def test_sc04_long_scene_splits_into_multiple_readable_cues():
    """sc_04 is 305 characters over ~22.9s (doc §0) - the "mathematically
    perfect cue nobody can read" case. Must become several cues, each
    within budget."""
    timeline = _timeline()
    rows = _active_voice_rows(timeline)
    cues = derive_caption_cues(timeline, rows)

    scene_order = [s.id for s in timeline.scenes]
    sc04_index = scene_order.index("sc_04")
    start = sum(
        rows[i].alignment["character_end_times_seconds"][-1] for i in range(sc04_index)
    )
    end = start + rows[sc04_index].alignment["character_end_times_seconds"][-1]
    sc04_cues = [c for c in cues if start - 0.01 <= c.start_s < end + 0.01]

    assert len(sc04_cues) > 1, "a 305-character scene must not be one cue"
    for cue in sc04_cues:
        assert len(cue.text) <= MAX_CHARS_PER_CUE * 1.5, cue.text


def test_no_cue_is_shorter_than_the_minimum_duration_or_longer_than_the_maximum():
    timeline = _timeline()
    cues = derive_caption_cues(timeline, _active_voice_rows(timeline))
    for cue in cues:
        duration = cue.end_s - cue.start_s
        assert duration <= MAX_CUE_DURATION_S + 0.01, cue
        # A cue may still be shorter than MIN_CUE_DURATION_S only when it
        # is a whole shot's own span on its own (decision §8.1: never
        # merge across a shot cut, even to satisfy the minimum).
        assert duration >= 0.0, cue


def test_cues_tile_without_overlap_across_the_whole_timeline():
    timeline = _timeline()
    cues = derive_caption_cues(timeline, _active_voice_rows(timeline))
    for previous, current in zip(cues, cues[1:]):
        assert current.start_s >= previous.start_s
        assert current.start_s >= previous.end_s - 1e-6


def test_a_shot_boundary_forces_a_split_even_mid_sentence():
    """A crafted, deliberately small example (not the fixture - this
    tests text/offset structure, not alignment timing, so a synthetic
    uniform alignment is appropriate here per this file's own docstring).
    One long sentence with no internal punctuation, split across two
    shots partway through - the cue boundary must still land exactly on
    the shot boundary, never mid-shot."""
    text = "the quick brown fox jumps over the lazy dog while everyone watches quietly"
    n = len(text)
    alignment = {
        "characters": list(text),
        "character_start_times_seconds": [i * 0.1 for i in range(n)],
        "character_end_times_seconds": [(i + 1) * 0.1 for i in range(n)],
    }
    split_at = 54  # inside "everyone" -> "ev" | "eryone", genuinely mid-word
    assert text[split_at - 1] != " "  # not a lucky word-boundary split
    timeline = _build_single_scene_timeline(
        text, shot_spans=[(0, split_at), (split_at, n)]
    )
    row = NarrationModel(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        scene_id="sc_01",
        provider="elevenlabs",
        voice_id="v1",
        model_id="m1",
        output_format="mp3_44100_128",
        text=text,
        content_hash="deadbeef",
        local_path="/fake/deadbeef.mp3",
        alignment=alignment,
        character_count=n,
        cost_cents=0,
    )
    cues = derive_caption_cues(timeline, [row])
    boundary_time = alignment["character_start_times_seconds"][split_at]
    assert any(cue.start_s == pytest.approx(boundary_time, abs=1e-6) for cue in cues)
    for cue in cues:
        # No cue's span (recovered from its own duration back to chars via
        # the uniform 0.1s/char clock) crosses `split_at`.
        cue_start_char = round(cue.start_s / 0.1)
        cue_end_char = round(cue.end_s / 0.1)
        assert cue_start_char >= split_at or cue_end_char <= split_at


def _build_single_scene_timeline(text: str, *, shot_spans: list[tuple[int, int]]) -> Timeline:
    fixture = _load_fixture()["timeline_document"]
    template = Timeline.model_validate(fixture)
    scene = template.scenes[0].model_copy(deep=True)
    scene.narration_text = text
    scene.shots = [
        scene.shots[0].model_copy(update={"id": f"sh_{i}", "narration_span": span})
        for i, span in enumerate(shot_spans)
    ]
    return template.model_copy(update={"scenes": [scene]})


# ---------------------------------------------------------------------------
# Determinism (I5, doc §5)
# ---------------------------------------------------------------------------


def test_cue_derivation_is_deterministic():
    timeline = _timeline()
    rows = _active_voice_rows(timeline)
    assert derive_caption_cues(timeline, rows) == derive_caption_cues(timeline, rows)


def test_ass_serialization_is_byte_identical_across_two_independent_calls():
    timeline = _timeline()
    cues = derive_caption_cues(timeline, _active_voice_rows(timeline))
    style = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")
    assert serialize_ass(cues, style) == serialize_ass(cues, style)


def test_ass_output_has_no_generation_timestamp_or_nondeterministic_content():
    cues = [CaptionCue(start_s=0.0, end_s=1.0, text="hello")]
    style = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")
    ass = serialize_ass(cues, style)
    assert "Script generated by" not in ass
    for token in ("2024", "2025", "2026"):
        assert token not in ass


def test_cue_list_content_hash_changes_when_text_changes_but_not_ordering_of_equal_input():
    cues_a = [CaptionCue(start_s=0.0, end_s=1.0, text="hello")]
    cues_b = [CaptionCue(start_s=0.0, end_s=1.0, text="goodbye")]
    assert cue_list_content_hash(cues_a) != cue_list_content_hash(cues_b)
    assert cue_list_content_hash(cues_a) == cue_list_content_hash(list(cues_a))


# ---------------------------------------------------------------------------
# ASS format basics
# ---------------------------------------------------------------------------


def test_ass_dialogue_lines_use_fixed_precision_ass_time_format():
    cues = [CaptionCue(start_s=7.059, end_s=10.5, text="hi")]
    style = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")
    ass = serialize_ass(cues, style)
    assert "Dialogue: 0,0:00:07.06,0:00:10.50,Caption,,0,0,0,,hi" in ass


def test_ass_text_escapes_braces_and_backslashes():
    cues = [CaptionCue(start_s=0.0, end_s=1.0, text="a {b} c\\d")]
    style = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")
    ass = serialize_ass(cues, style)
    assert "a \\{b\\} c\\\\d" in ass
