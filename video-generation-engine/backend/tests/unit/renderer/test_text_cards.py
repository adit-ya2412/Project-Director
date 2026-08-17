"""`app/renderer/text_cards.py` (motion_new_styles_and_long_form_videos.md
§2.6, Tier 2) - pure string/arithmetic, no ffmpeg needed. The real
`subtitles=` filter this produces is verified separately: a real ASS
file burned onto a real archival photo, frames extracted at fade-in,
hold, and fade-out and visually inspected (2026-08-17) - centered
two-line text, a genuine partial-opacity fade at t=0.2s, full opacity
during the hold.
"""

from datetime import UTC, datetime

from app.renderer.text_cards import (
    TextCardStyle,
    derive_text_card_cues,
    serialize_text_card_ass,
    text_card_content_hash,
)
from app.schemas.timeline import ProducedBy, Scene, Shot, ShotIntent, Timeline, TimelineStatus


def _timeline(shots: list[Shot]) -> Timeline:
    scene = Scene(
        id="sc_01",
        order=0,
        title="Scene",
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
    )
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


def test_no_cues_when_no_shot_has_a_text_card():
    shots = [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)]
    assert derive_text_card_cues(_timeline(shots)) == []


def test_blank_text_card_is_treated_as_no_card():
    """Whitespace-only text is the same as `None` - a planner or human
    clearing a card by blanking it must not burn an empty, invisible
    cue."""
    shots = [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, text_card="   ")]
    assert derive_text_card_cues(_timeline(shots)) == []


def test_cue_spans_exactly_the_shots_own_rendered_window():
    """Uses the RENDERED-timeline clock (`compute_shot_start_times`, D5
    overlap-aware), not narration timing - a text card is tied to which
    shot is on screen, verified here against a non-trivial two-shot,
    hard-cut case."""
    shots = [
        Shot(
            id="sh_01", order=0, intent=ShotIntent.INTRODUCE, duration_s=3.0, text_card="Part One"
        ),
        Shot(id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=2.0),
    ]
    cues = derive_text_card_cues(_timeline(shots))
    assert len(cues) == 1
    assert cues[0].start_s == 0.0
    assert cues[0].end_s == 3.0
    assert cues[0].text == "Part One"


def test_cue_order_follows_shot_order_across_multiple_cards():
    shots = [
        Shot(id="sh_01", order=0, intent=ShotIntent.INTRODUCE, duration_s=2.0, text_card="One"),
        Shot(id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=2.0),
        Shot(id="sh_03", order=2, intent=ShotIntent.REVEAL, duration_s=2.0, text_card="Two"),
    ]
    cues = derive_text_card_cues(_timeline(shots))
    assert [c.text for c in cues] == ["One", "Two"]
    assert cues[1].start_s == 4.0  # after two 2.0s shots, no overlap (default transition is CUT)


def test_content_hash_is_deterministic_and_sensitive_to_text():
    shots_a = [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, text_card="A")]
    shots_b = [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, text_card="B")]
    hash_a1 = text_card_content_hash(derive_text_card_cues(_timeline(shots_a)))
    hash_a2 = text_card_content_hash(derive_text_card_cues(_timeline(shots_a)))
    hash_b = text_card_content_hash(derive_text_card_cues(_timeline(shots_b)))
    assert hash_a1 == hash_a2
    assert hash_a1 != hash_b


def test_ass_style_line_field_count_matches_its_own_format_line():
    """A real, easy-to-reintroduce ASS bug: adding/removing a Style field
    without updating the Format header (or vice versa) silently
    misaligns every value after the edit point. Checked directly against
    the actual serialized output, not just eyeballed once."""
    shots = [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, text_card="X")]
    ass = serialize_text_card_ass(
        derive_text_card_cues(_timeline(shots)),
        TextCardStyle(resolution=(720, 1280), font_family="Noto Sans Devanagari"),
    )
    lines = ass.splitlines()
    format_line = next(line for line in lines if line.startswith("Format: Name, Fontname"))
    style_line = next(line for line in lines if line.startswith("Style: TextCard"))
    assert len(format_line.split(",")) == len(style_line.split(","))


def test_alignment_is_centered_not_bottom():
    """Alignment=5 (middle-center), distinct from captions' Alignment=2
    (bottom-center, clearing the platform UI band) - a title card and a
    caption must not compete for the same screen region."""
    shots = [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, text_card="X")]
    ass = serialize_text_card_ass(
        derive_text_card_cues(_timeline(shots)),
        TextCardStyle(resolution=(720, 1280), font_family="Noto Sans Devanagari"),
    )
    style_line = next(line for line in ass.splitlines() if line.startswith("Style: TextCard"))
    alignment = style_line.split(",")[18]  # 0-indexed: Name=0 ... Alignment=18
    assert alignment == "5"


def test_line_breaks_are_preserved_as_ass_hard_breaks():
    """Deliberately different from captions' own escaping (which
    collapses newlines to a space) - a two-line title card is a normal,
    deliberate authoring choice."""
    shots = [
        Shot(
            id="sh_01",
            order=0,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            text_card="Fischer-Tropsch\nSasol, South Africa",
        )
    ]
    ass = serialize_text_card_ass(
        derive_text_card_cues(_timeline(shots)),
        TextCardStyle(resolution=(720, 1280), font_family="Noto Sans Devanagari"),
    )
    dialogue = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    assert "\\N" in dialogue
    assert "\n" not in dialogue.split(",", 9)[-1]  # the Text field itself has no raw newline


def test_fade_tag_is_present_and_clamped_for_a_very_short_shot():
    """A shot shorter than the fixed 0.5s+0.5s fade budget must still get
    a graceful, clamped fade rather than an invalid or backwards-timed
    one."""
    shots = [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=0.4, text_card="X")]
    ass = serialize_text_card_ass(
        derive_text_card_cues(_timeline(shots)),
        TextCardStyle(resolution=(720, 1280), font_family="Noto Sans Devanagari"),
    )
    dialogue = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    assert "\\fad(200,200)" in dialogue  # clamped to half of 400ms each way
