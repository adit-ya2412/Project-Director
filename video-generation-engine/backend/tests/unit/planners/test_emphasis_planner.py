"""K9 emphasis planner: strict-mode schema, mapper, FakePlanningProvider."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.planners.emphasis.planner import (
    _HOOK_MIN_CUES,
    _TARGET_CUES_PER_MINUTE,
    EmphasisPlanner,
    _build_user_content,
    _hook_capacity,
    apply_emphasis_plan,
    derive_text_register,
)
from app.planners.emphasis.schemas import (
    EmphasisCuePlanOutput,
    EmphasisPlannerOutput,
    EmphasisValuePlanOutput,
)
from app.planners.fragments import split_narration_fragments
from app.schemas.timeline import (
    EmphasisDevice,
    EmphasisRegister,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.timeline.emphasis_rules import enforce_emphasis_rules

from .helpers import FakePlanningProvider

NARRATION = (
    "Hyundai Creta dikhti hai har gali mein. "
    "2025 mein 2 lakh models bikhe. "
    "Lekin kya yeh safest hai? "
    "Brochures kehte hain 9 lakh. "
    "Comment karo abhi."
)


class _StubLlm:
    async def insert(self, **kwargs):
        return None


def _cue(
    shot_id: str,
    device: str,
    *,
    anchor_fragment: int,
    text: str,
    values: list[EmphasisValuePlanOutput] | None = None,
    replaced_text: str = "",
) -> EmphasisCuePlanOutput:
    return EmphasisCuePlanOutput(
        shot_id=shot_id,
        device=device,
        anchor_fragment=anchor_fragment,
        text=text,
        values=values or [],
        replaced_text=replaced_text,
    )


def _value(value: int, cited_fragment: int, unit: str = "") -> EmphasisValuePlanOutput:
    return EmphasisValuePlanOutput(value=value, unit=unit, cited_fragment=cited_fragment)


def _output(cues: list[EmphasisCuePlanOutput], **palette) -> EmphasisPlannerOutput:
    return EmphasisPlannerOutput(
        cues=cues,
        accent=palette.get("accent", "#00C8FF"),
        pivot_ground=palette.get("pivot_ground", "#5A00A8"),
    )


def _timeline() -> Timeline:
    fragments = split_narration_fragments(NARRATION)
    shots = [
        Shot(
            id=f"sc_01_sh_{fragment.index:02d}",
            order=fragment.index - 1,
            intent=ShotIntent.EXPLAIN,
            duration_s=2.0,
            narration_span=(fragment.start, fragment.end),
            prompt=f"plate {fragment.index}",
        )
        for fragment in fragments
    ]
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[
            Scene(
                id="sc_01",
                order=0,
                title="hook",
                narration_text=NARRATION,
                duration_s=sum(shot.duration_s for shot in shots),
                shots=shots,
            )
        ],
    )


def _canned_stamp_counter_pivot() -> list[EmphasisCuePlanOutput]:
    return [
        _cue("sc_01_sh_01", "stamp", anchor_fragment=1, text="Hyundai"),
        _cue(
            "sc_01_sh_02",
            "counter",
            anchor_fragment=2,
            text="SOLD IN A YEAR",
            values=[_value(200000, 2, unit="+")],
        ),
        _cue("sc_01_sh_03", "pivot", anchor_fragment=3, text="lekin"),
    ]


def test_narration_splits_into_five_fragments():
    assert [f.text for f in split_narration_fragments(NARRATION)] == [
        "Hyundai Creta dikhti hai har gali mein.",
        "2025 mein 2 lakh models bikhe.",
        "Lekin kya yeh safest hai?",
        "Brochures kehte hain 9 lakh.",
        "Comment karo abhi.",
    ]


def test_build_user_content_names_the_hook_and_uses_12_multiplier():
    """K14.3 / K14.4: Target cue count must name the hook and use 12.0."""
    timeline = _timeline()
    timeline.metadata.render_style = "retention_fast"
    # 5 shots × 2.0s = 10s → round(10/60 * 12) = 2; hook_min clipped to 2.
    content = _build_user_content(timeline)
    assert _TARGET_CUES_PER_MINUTE == 12.0
    assert "first 5.0s hook" in content
    assert "front-load" in content
    assert "~1.5s" in content
    assert "consecutive shots may both carry a cue" in content
    assert "gap 3" in content
    assert "multiplier 12.0/min" in content
    assert "Target cue count: 2 = at least 2 in the first 5.0s hook + 0 in the body" in content


def test_hook_request_never_exceeds_hook_capacity():
    """Review finding 1: the hook floor is clipped by shot geometry.

    The watched reel's shape — 12 shots, 24.68s, openers of 2.82s and
    2.72s — puts shot 2 at 5.54s, outside the 5.0s hook, so only TWO
    shots start inside the window. One cue per shot is structural, so a
    floor of 3 asked for a hook cue enforcement could never keep. The
    request is now `min(_HOOK_MIN_CUES, capacity, total)` = 2, the body
    gets the remaining 3, and the line says what the window can hold.
    """
    durations = [2.82, 2.72, 1.61, 1.69, 1.81, 2.10, 2.41, 1.93, 2.04, 1.96, 1.83, 1.76]
    shots = [
        Shot(
            id=f"sc_01_sh_{i:02d}",
            order=i,
            intent=ShotIntent.EXPLAIN,
            duration_s=duration,
            narration_span=(0, 1),
            prompt=f"plate {i}",
        )
        for i, duration in enumerate(durations)
    ]
    timeline = _timeline()
    timeline.metadata.render_style = "retention_fast"
    timeline.scenes[0].shots = shots
    timeline.scenes[0].duration_s = sum(durations)

    assert _hook_capacity(timeline, 5.0) == 2
    assert _HOOK_MIN_CUES == 3  # the ceiling on the floor, not the floor
    content = _build_user_content(timeline)
    # round(24.68 / 60 * 12.0) = 5 total.
    assert "Target cue count: 5 = at least 2 in the first 5.0s hook + 3 in the body" in content
    assert "only 2 shot(s) start inside the hook window" in content


def test_hook_request_keeps_the_floor_when_the_hook_holds_enough_shots():
    """Same window, faster cutting: five 1.0s openers put three shot
    starts inside the 5.0s hook, so the floor of 3 stands."""
    timeline = _timeline()
    timeline.metadata.render_style = "retention_fast"
    for shot in timeline.scenes[0].shots:
        shot.duration_s = 1.6
    timeline.scenes[0].duration_s = sum(s.duration_s for s in timeline.scenes[0].shots)
    # starts 0 / 1.6 / 3.2 / 4.8 / 6.4 → four inside a 5.0s hook.
    assert _hook_capacity(timeline, 5.0) == 4
    content = _build_user_content(timeline)
    # round(8.0 / 60 * 12.0) = 2 total, so the floor clips to the total.
    assert "at least 2 in the first 5.0s hook" in content
    assert "only 4 shot(s) start inside the hook window" in content


def test_build_user_content_without_hook_keeps_uniform_band_line():
    timeline = _timeline()
    timeline.metadata.render_style = "documentary_archival"
    content = _build_user_content(timeline)
    assert "first 5.0s hook" not in content
    assert "band 8-12 per minute" in content


def test_emphasis_planner_schema_has_no_defaults():
    """OpenAI structured-output strict mode: a pydantic default drops
    the field from `required`, and the model is then never asked."""
    for model in (EmphasisValuePlanOutput, EmphasisCuePlanOutput, EmphasisPlannerOutput):
        schema = model.model_json_schema()
        for field in model.model_fields:
            assert field in schema["required"], field
            prop = schema["properties"][field]
            assert "default" not in prop, field


def test_emphasis_planner_output_rejects_a_missing_field():
    payload = _output(_canned_stamp_counter_pivot()).model_dump()
    payload.pop("accent")
    with pytest.raises(ValidationError, match="accent"):
        EmphasisPlannerOutput.model_validate(payload)
    cue = payload["cues"][0]
    cue.pop("replaced_text")
    with pytest.raises(ValidationError, match="replaced_text"):
        EmphasisCuePlanOutput.model_validate(cue)


def test_derive_text_register_follows_decision_4():
    assert derive_text_register("pivot", "lekin") is EmphasisRegister.HI
    assert derive_text_register("counter", "SOLD IN A YEAR") is EmphasisRegister.EN
    assert derive_text_register("stamp", "Hyundai") is EmphasisRegister.EN
    assert derive_text_register("stamp", "झूठ") is EmphasisRegister.HI


def test_mapper_lands_stamp_counter_pivot_with_derived_registers():
    timeline = apply_emphasis_plan(_timeline(), _output(_canned_stamp_counter_pivot()))
    shots = {shot.id: shot for shot in timeline.all_shots()}

    stamp = shots["sc_01_sh_01"].emphasis_cue
    assert stamp is not None
    assert stamp.device is EmphasisDevice.STAMP
    assert stamp.text == "Hyundai"
    assert stamp.text_register is EmphasisRegister.EN
    assert stamp.anchor_fragment == 1
    assert stamp.offset_s == 0.0
    assert stamp.values == []

    counter = shots["sc_01_sh_02"].emphasis_cue
    assert counter is not None
    assert counter.device is EmphasisDevice.COUNTER
    assert counter.text == "SOLD IN A YEAR"
    assert counter.text_register is EmphasisRegister.EN
    assert counter.values[0].value == 200000
    assert counter.values[0].unit == "+"
    assert counter.values[0].cited_fragment == 2

    pivot = shots["sc_01_sh_03"].emphasis_cue
    assert pivot is not None
    assert pivot.device is EmphasisDevice.PIVOT
    assert pivot.text == "लेकिन"
    assert pivot.text_register is EmphasisRegister.HI

    assert timeline.metadata.emphasis_palette is not None
    assert timeline.metadata.emphasis_palette.accent == "#00C8FF"
    assert timeline.metadata.emphasis_palette.pivot_ground == "#5A00A8"


def test_mapper_drops_correction_and_unknown_shot():
    cues = [
        *_canned_stamp_counter_pivot(),
        _cue("sc_01_sh_04", "correction", anchor_fragment=4, text="myth", replaced_text="truth"),
        _cue("sc_99_sh_01", "stamp", anchor_fragment=1, text="ghost"),
        _cue("sc_01_sh_05", "meter", anchor_fragment=5, text="bar"),
    ]
    timeline = apply_emphasis_plan(_timeline(), _output(cues))
    shots = {shot.id: shot for shot in timeline.all_shots()}
    assert shots["sc_01_sh_01"].emphasis_cue.device is EmphasisDevice.STAMP
    assert shots["sc_01_sh_04"].emphasis_cue is None
    assert shots["sc_01_sh_05"].emphasis_cue is None


def test_mapper_skips_blocked_shot_and_empty_counter():
    timeline = _timeline()
    timeline.all_shots()[0].text_card = "THE MYTH"
    timeline.all_shots()[3].picture_is_graphic = True
    cues = [
        _cue("sc_01_sh_01", "stamp", anchor_fragment=1, text="Hyundai"),
        _cue("sc_01_sh_04", "stamp", anchor_fragment=4, text="Brochures"),
        _cue("sc_01_sh_02", "counter", anchor_fragment=2, text="NO VALUES"),
        _cue("sc_01_sh_03", "pivot", anchor_fragment=3, text="लेकिन"),
    ]
    mapped = apply_emphasis_plan(timeline, _output(cues))
    shots = {shot.id: shot for shot in mapped.all_shots()}
    assert shots["sc_01_sh_01"].emphasis_cue is None
    assert shots["sc_01_sh_04"].emphasis_cue is None
    assert shots["sc_01_sh_02"].emphasis_cue is None
    assert shots["sc_01_sh_03"].emphasis_cue.device is EmphasisDevice.PIVOT


def test_missing_pivot_is_filled_by_lexical_backstop():
    cues = [
        _cue("sc_01_sh_01", "stamp", anchor_fragment=1, text="Hyundai"),
        _cue(
            "sc_01_sh_02",
            "counter",
            anchor_fragment=2,
            text="SOLD IN A YEAR",
            values=[_value(200000, 2)],
        ),
    ]
    timeline = apply_emphasis_plan(_timeline(), _output(cues))
    pivot = timeline.all_shots()[2].emphasis_cue
    assert pivot is not None
    assert pivot.device is EmphasisDevice.PIVOT
    assert pivot.text == "लेकिन"
    assert pivot.text_register is EmphasisRegister.HI


def test_uncitable_counter_survives_the_mapper_and_k3_drops_it():
    cues = [
        *_canned_stamp_counter_pivot(),
        _cue(
            "sc_01_sh_05",
            "counter",
            anchor_fragment=5,
            text="FAKE",
            values=[_value(999999, 5)],
        ),
    ]
    mapped = apply_emphasis_plan(_timeline(), _output(cues))
    assert mapped.all_shots()[4].emphasis_cue is not None
    # Isolate the citation rule: density knobs off so a nearby pivot
    # cannot be the reason the fake counter disappears.
    enforced = enforce_emphasis_rules(mapped, min_shot_gap=None, max_cues_per_minute=None)
    assert enforced.all_shots()[4].emphasis_cue is None
    assert enforced.all_shots()[0].emphasis_cue.device is EmphasisDevice.STAMP
    assert enforced.all_shots()[1].emphasis_cue.device is EmphasisDevice.COUNTER
    assert enforced.all_shots()[2].emphasis_cue.device is EmphasisDevice.PIVOT


def test_empty_unit_and_replaced_text_normalise_to_none():
    cues = [
        _cue(
            "sc_01_sh_02",
            "counter",
            anchor_fragment=2,
            text="SOLD",
            values=[_value(200000, 2, unit="")],
            replaced_text="",
        )
    ]
    timeline = apply_emphasis_plan(_timeline(), _output(cues))
    cue = timeline.all_shots()[1].emphasis_cue
    assert cue is not None
    assert cue.values[0].unit is None
    assert cue.replaced_text is None


def test_invalid_palette_is_left_unset():
    mapped = apply_emphasis_plan(
        _timeline(),
        _output(_canned_stamp_counter_pivot(), accent="red", pivot_ground="#FFFFFF"),
    )
    assert mapped.metadata.emphasis_palette is None


def test_near_white_pivot_ground_is_left_unset():
    mapped = apply_emphasis_plan(
        _timeline(),
        _output(_canned_stamp_counter_pivot(), accent="#00C8FF", pivot_ground="#FAFAFA"),
    )
    assert mapped.metadata.emphasis_palette is None


async def test_plan_threads_canned_output_through_fake_provider():
    provider = FakePlanningProvider(responses=[_output(_canned_stamp_counter_pivot())])
    planner = EmphasisPlanner(provider, _StubLlm())  # type: ignore[arg-type]
    planned = await planner.plan(project_id=str(uuid.uuid4()), timeline=_timeline())
    shots = {shot.id: shot for shot in planned.all_shots()}
    assert shots["sc_01_sh_01"].emphasis_cue.device is EmphasisDevice.STAMP
    assert shots["sc_01_sh_02"].emphasis_cue.text_register is EmphasisRegister.EN
    assert shots["sc_01_sh_03"].emphasis_cue.text == "लेकिन"
    assert len(provider.calls) == 1
    user = provider.calls[0]["user_content"]
    assert "sc_01_sh_01" in user
    assert "1. Hyundai Creta dikhti hai har gali mein." in user
    assert "Lexical turn: shot sc_01_sh_03" in user
    assert "Never emit seconds" in provider.calls[0]["system_prompt"]
