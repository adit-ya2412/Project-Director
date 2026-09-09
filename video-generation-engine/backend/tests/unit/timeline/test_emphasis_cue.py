"""K1 — `EmphasisCue` on `Shot` (retention_fast_kinetic_text.md).

Schema isolation only: round-trip, required `anchor_fragment`, default
None, mutual exclusion with `text_card`. No DB, no LLM.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.timeline import (
    EmphasisCue,
    EmphasisDevice,
    EmphasisRegister,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)


def _shot(**overrides) -> Shot:
    fields = {"id": "sh_01", "order": 0, "intent": ShotIntent.EXPLAIN, "duration_s": 3.0}
    fields.update(overrides)
    return Shot(**fields)


def _cue(**overrides) -> EmphasisCue:
    fields = {
        "device": EmphasisDevice.PIVOT,
        "anchor_fragment": 1,
        "text": "लेकिन",
        "text_register": EmphasisRegister.HI,
    }
    fields.update(overrides)
    return EmphasisCue(**fields)


def test_emphasis_cue_defaults_to_none():
    assert _shot().emphasis_cue is None


def test_picture_is_graphic_defaults_to_false():
    """K3 isolation: constructing a shot the way every pre-K3 style does
    (no kwarg) must not start dropping cues."""
    assert _shot().picture_is_graphic is False
    assert _shot().model_dump(mode="json")["picture_is_graphic"] is False


def test_emphasis_cue_none_dumps_as_null_not_omitted():
    """Pydantic includes the default in `model_dump` — the same §3.4-
    shaped fingerprint leak `layers` already accepted. Pinning it so a
    future exclude-none change is a deliberate, reviewed decision."""
    assert _shot().model_dump(mode="json")["emphasis_cue"] is None


def test_cue_round_trips_dump_validate():
    shot = _shot(emphasis_cue=_cue(), narration_span=(0, 12))
    dumped = shot.model_dump(mode="json")
    restored = Shot.model_validate(dumped)
    assert restored.emphasis_cue is not None
    assert restored.emphasis_cue.device is EmphasisDevice.PIVOT
    assert restored.emphasis_cue.anchor_fragment == 1
    assert restored.emphasis_cue.text == "लेकिन"
    assert restored.emphasis_cue.text_register is EmphasisRegister.HI
    assert restored.emphasis_cue.values == []
    assert restored.emphasis_cue.replaced_text is None
    assert restored.emphasis_cue.offset_s == 0.0


def test_timeline_round_trips_a_cue_through_dump_validate():
    shot = _shot(emphasis_cue=_cue(), narration_span=(0, 12))
    scene = Scene(id="sc_01", order=0, title="t", duration_s=3.0, shots=[shot])
    timeline = Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )
    restored = Timeline.model_validate(timeline.model_dump(mode="json"))
    cue = restored.all_shots()[0].emphasis_cue
    assert cue is not None
    assert cue.device == "pivot"
    assert cue.text == "लेकिन"


def test_missing_anchor_fragment_is_rejected():
    with pytest.raises(ValidationError):
        EmphasisCue(device="pivot", text="लेकिन", text_register="hi")


def test_anchor_fragment_must_be_at_least_one():
    with pytest.raises(ValidationError):
        _cue(anchor_fragment=0)


def test_cannot_coexist_with_a_non_empty_text_card():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _shot(text_card="THE MYTH", emphasis_cue=_cue())


def test_empty_text_card_is_not_a_conflict():
    shot = _shot(text_card="", emphasis_cue=_cue())
    assert shot.emphasis_cue is not None
    assert shot.text_card == ""


def test_none_text_card_is_not_a_conflict():
    shot = _shot(text_card=None, emphasis_cue=_cue())
    assert shot.emphasis_cue is not None
