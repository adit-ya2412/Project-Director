"""K12 (retention_fast_kinetic_text.md): `ShotPlanOutput.picture_is_graphic`
threads onto `Shot.picture_is_graphic`.

K3 already owns enforcement of the flag; this file only pins the Shot
Planner wiring. A green suite here is not the slice's done-criterion —
that is a live re-plan recorded in the plan's K12 work log.
"""

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.db.session import async_session_factory
from app.planners.fragments import split_narration_fragments
from app.planners.shot.planner import ShotPlanner, _to_domain_shot
from app.planners.shot.schemas import (
    ShotCameraOutput,
    ShotPlannerOutput,
    ShotPlanOutput,
    ShotTransitionOutput,
)
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    CameraDirection,
    CameraMovement,
    CreativeContext,
    Framing,
    RevealDirection,
    Scene,
    Shot,
    ShotIntent,
    TransitionType,
)

from .helpers import FakePlanningProvider

_NARRATION = "Germany possessed abundant coal. It fueled every furnace in the Ruhr."


def _shot_output(*, picture_is_graphic: bool, shot_id: str = "sh_01", **overrides) -> ShotPlanOutput:
    fields = dict(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        intent_text="text",
        fragment_start=1,
        fragment_end=2,
        duration_s=4.0,
        framing=Framing.WIDE,
        camera=ShotCameraOutput(
            movement=CameraMovement.STATIC, direction=CameraDirection.NONE, intensity=0.0
        ),
        transition_out=ShotTransitionOutput(type=TransitionType.CUT, duration_s=0.0),
        prompt="archival photograph",
        secondary_prompt="",
        text_card="",
        sfx_cue="",
        picture_is_graphic=picture_is_graphic,
        layers=[],
        reveal_direction=RevealDirection.NONE,
        reveal_start_fragment=0,
        reveal_end_fragment=0,
    )
    fields.update(overrides)
    return ShotPlanOutput(**fields)


def _domain_shot(*, picture_is_graphic: bool) -> Shot:
    fragments = split_narration_fragments(_NARRATION)
    assert len(fragments) == 2
    return _to_domain_shot(
        _shot_output(picture_is_graphic=picture_is_graphic),
        scene_id="sc_01",
        fragments=fragments,
    )


def test_picture_is_graphic_true_threads_through_to_the_persisted_shot():
    assert _domain_shot(picture_is_graphic=True).picture_is_graphic is True


def test_picture_is_graphic_false_threads_through_to_the_persisted_shot():
    assert _domain_shot(picture_is_graphic=False).picture_is_graphic is False


def test_domain_shot_without_the_kwarg_is_still_false():
    """Isolation: constructing a Shot the way every pre-K12 caller does
    (no kwarg) must not start dropping cues. Same default K3 already
    pinned; this is the planner-wiring side of that contract."""
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    assert shot.picture_is_graphic is False


def test_stored_timeline_without_the_field_still_loads_as_false():
    """A Timeline persisted before K12 has no `picture_is_graphic` key;
    the domain default must keep those shots as non-graphics."""
    dumped = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0).model_dump(
        mode="json"
    )
    dumped.pop("picture_is_graphic")
    restored = Shot.model_validate(dumped)
    assert restored.picture_is_graphic is False


def test_picture_is_graphic_is_required_and_has_no_default():
    """OpenAI structured-output strict mode: a pydantic default drops
    the field from `required`, and the model is then never asked."""
    schema = ShotPlanOutput.model_json_schema()
    assert "picture_is_graphic" in schema["required"]
    prop = schema["properties"]["picture_is_graphic"]
    assert "default" not in prop
    assert prop["type"] == "boolean"
    payload = _shot_output(picture_is_graphic=True).model_dump()
    payload.pop("picture_is_graphic")
    with pytest.raises(ValidationError, match="picture_is_graphic"):
        ShotPlanOutput.model_validate(payload)


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("shot-planner-graphic-test")
        return project.id


async def test_plan_threads_true_and_false_after_namespacing(project_id):
    """FakePlanningProvider path through `ShotPlanner.plan`: a canned
    output with True on one shot and False on another lands on the
    domain shots after scene-id namespacing."""
    scene = Scene(
        id="sc_01", order=0, title="Coal wealth", narration_text=_NARRATION, duration_s=4.0
    )
    output = ShotPlannerOutput(
        shots=[
            _shot_output(
                picture_is_graphic=True,
                shot_id="sh_01",
                order=0,
                fragment_start=1,
                fragment_end=1,
                duration_s=2.0,
                prompt="bar chart of coal output, 1930s, infographic",
            ),
            _shot_output(
                picture_is_graphic=False,
                shot_id="sh_02",
                order=1,
                fragment_start=2,
                fragment_end=2,
                duration_s=2.0,
                prompt="workers at a Ruhr furnace, archival photograph",
            ),
        ]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[output])
        planner = ShotPlanner(provider, LlmCallRepository(session))
        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
            max_parallax_layers_per_project=100,
        )

    shots = planned[0].shots
    assert [s.id for s in shots] == ["sc_01_sh_01", "sc_01_sh_02"]
    assert shots[0].picture_is_graphic is True
    assert shots[1].picture_is_graphic is False

