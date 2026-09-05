"""`ShotPlanOutput.reveal_direction`/`reveal_start_fragment`/
`reveal_end_fragment` (illustrated_faceless.md §2/F5) - the Shot
Planner's authoring path for a shot's own progressive reveal.

Same shape as `test_shot_planner_parallax_layers.py`: a movement/field
pair must agree both directions, enforced as a hard failure (the model
already had every fact it needed in this same call, unlike the
project-wide cap in `_cap_element_reveals`).
"""

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.planners.shot.planner import ShotPlanner
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
    ShotIntent,
)

from .helpers import FakePlanningProvider

NARRATION = "Germany possessed abundant coal. It fueled every furnace in the Ruhr."


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("shot-planner-test")
        return project.id


def _scene() -> Scene:
    return Scene(id="sc_01", order=0, title="Coal wealth", narration_text=NARRATION, duration_s=4.0)


def _shot_output(**overrides) -> ShotPlanOutput:
    fields = dict(
        id="sh_01",
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
        transition_out=ShotTransitionOutput(type="cut", duration_s=0.0),
        prompt="a risograph bar chart",
        secondary_prompt="",
        text_card="",
        sfx_cue="",
        layers=[],
        reveal_direction=RevealDirection.NONE,
        reveal_start_fragment=0,
        reveal_end_fragment=0,
    )
    fields.update(overrides)
    return ShotPlanOutput(**fields)


async def _plan(scene: Scene, output: ShotPlanOutput, project_id: str, *, attempts: int = 1):
    async with async_session_factory() as session:
        response = ShotPlannerOutput(shots=[output])
        provider = FakePlanningProvider(responses=[response] * attempts)
        planner = ShotPlanner(provider, LlmCallRepository(session))
        return await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
            max_parallax_layers_per_project=100,
        )


async def test_reveal_on_a_moving_camera_shot_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        camera=ShotCameraOutput(
            movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.NONE, intensity=0.15
        ),
        reveal_direction=RevealDirection.BOTTOM_TO_TOP,
        reveal_start_fragment=1,
        reveal_end_fragment=2,
    )
    with pytest.raises(PermanentError, match="needs camera.movement=static"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_reveal_with_start_fragment_zero_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        reveal_direction=RevealDirection.BOTTOM_TO_TOP,
        reveal_start_fragment=0,
        reveal_end_fragment=2,
    )
    with pytest.raises(PermanentError, match="both reveal_start_fragment and reveal_end_fragment"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_reveal_with_end_fragment_zero_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        reveal_direction=RevealDirection.BOTTOM_TO_TOP,
        reveal_start_fragment=1,
        reveal_end_fragment=0,
    )
    with pytest.raises(PermanentError, match="both reveal_start_fragment and reveal_end_fragment"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_reveal_end_before_start_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        reveal_direction=RevealDirection.BOTTOM_TO_TOP,
        reveal_start_fragment=2,
        reveal_end_fragment=1,
    )
    with pytest.raises(PermanentError, match="must be >= reveal_start_fragment"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_reveal_window_outside_the_shots_own_fragment_range_is_rejected(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    # This shot covers fragments 1-2 (see _shot_output's own defaults) -
    # fragment 5 is not one of the words this shot's narration covers.
    bad = _shot_output(
        reveal_direction=RevealDirection.BOTTOM_TO_TOP,
        reveal_start_fragment=1,
        reveal_end_fragment=5,
    )
    with pytest.raises(PermanentError, match="a reveal cannot track words the shot does not cover"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_reveal_fields_set_without_a_direction_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        reveal_direction=RevealDirection.NONE,
        reveal_start_fragment=1,
        reveal_end_fragment=2,
    )
    with pytest.raises(PermanentError, match="must be 0 when reveal_direction is none"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_a_valid_reveal_lands_on_the_domain_shot(project_id):
    scene = _scene()
    good = _shot_output(
        reveal_direction=RevealDirection.LEFT_TO_RIGHT,
        reveal_start_fragment=1,
        reveal_end_fragment=2,
    )
    planned = await _plan(scene, good, project_id)
    shot = planned[0].shots[0]
    assert shot.reveal_direction is RevealDirection.LEFT_TO_RIGHT
    assert shot.reveal_start_fragment == 1
    assert shot.reveal_end_fragment == 2
    # Resolved at the narration_fit seam, never here - see
    # tests/unit/timeline/test_narration_fit.py.
    assert shot.reveal_start_offset_s == 0.0
    assert shot.reveal_duration_s == 0.0


async def test_a_non_reveal_shot_keeps_reveal_fields_none(project_id):
    scene = _scene()
    good = _shot_output()
    planned = await _plan(scene, good, project_id)
    shot = planned[0].shots[0]
    assert shot.reveal_direction is None
    assert shot.reveal_start_fragment is None
    assert shot.reveal_end_fragment is None
