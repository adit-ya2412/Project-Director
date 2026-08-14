"""Golden-file test for the Shot Planner: verifies narration-span
coverage, per-scene looping, and the running max_shots_per_project cap."""

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
    Scene,
    ShotIntent,
    TransitionType,
)

from .helpers import FakePlanningProvider

NARRATION = "Germany possessed abundant coal."


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("shot-planner-test")
        return project.id


def _scene(scene_id: str = "sc_01", duration_s: float = 4.0) -> Scene:
    return Scene(
        id=scene_id, order=0, title="Coal wealth", narration_text=NARRATION, duration_s=duration_s
    )


def _valid_output_for(scene: Scene) -> ShotPlannerOutput:
    # Raw ids deliberately do NOT encode the scene - this mirrors what the
    # real model does (reuses the same simple pattern for every scene,
    # since each call only ever sees one scene). Global uniqueness comes
    # from ShotPlanner namespacing by scene_id, not from this id.
    mid = len(scene.narration_text) // 2
    half = scene.duration_s / 2
    return ShotPlannerOutput(
        shots=[
            ShotPlanOutput(
                id="sh_01",
                order=0,
                intent=ShotIntent.EXPLAIN,
                intent_text="Show the scale of coal extraction",
                narration_start=0,
                narration_end=mid,
                duration_s=half,
                framing=Framing.WIDE,
                camera=ShotCameraOutput(
                    movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.IN, intensity=0.15
                ),
                transition_out=ShotTransitionOutput(type=TransitionType.DISSOLVE, duration_s=0.4),
                prompt="1930s coal mine, archival photograph",
            ),
            ShotPlanOutput(
                id="sh_02",
                order=1,
                intent=ShotIntent.EXPLAIN,
                intent_text="Connect coal to industry",
                narration_start=mid,
                narration_end=len(scene.narration_text),
                duration_s=half,
                framing=Framing.MEDIUM,
                camera=ShotCameraOutput(
                    movement=CameraMovement.STATIC, direction=CameraDirection.NONE, intensity=0.1
                ),
                transition_out=ShotTransitionOutput(type=TransitionType.CUT, duration_s=0.0),
                prompt="1930s steel factory, archival photograph",
            ),
        ]
    )


async def test_shot_plan_fills_shots_covering_the_full_narration(project_id):
    scene = _scene()
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output_for(scene)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.5,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
        )

    shots = planned[0].shots
    assert [s.id for s in shots] == ["sc_01_sh_01", "sc_01_sh_02"]
    assert shots[0].narration_span == (0, len(scene.narration_text) // 2)
    assert shots[-1].narration_span[1] == len(scene.narration_text)
    assert all(s.asset_plan is None for s in shots)


async def test_shot_plan_loops_once_per_scene(project_id):
    scene_a = _scene("sc_01")
    scene_b = _scene("sc_02")
    async with async_session_factory() as session:
        provider = FakePlanningProvider(
            responses=[_valid_output_for(scene_a), _valid_output_for(scene_b)]
        )
        planner = ShotPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene_a, scene_b],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.5,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
        )

    assert len(provider.calls) == 2
    # Both scenes' fake responses reuse the same raw ids ("sh_01", "sh_02")
    # - exactly what the real model does, since each call is blind to the
    # other scenes. Namespacing by scene_id must still keep them globally
    # unique across scenes.
    assert [s.id for s in planned[0].shots] == ["sc_01_sh_01", "sc_01_sh_02"]
    assert [s.id for s in planned[1].shots] == ["sc_02_sh_01", "sc_02_sh_02"]
    all_ids = [s.id for scene in planned for s in scene.shots]
    assert len(all_ids) == len(set(all_ids))


async def test_shot_plan_enforces_project_wide_shot_cap(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output_for(scene)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="max_shots_per_project"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.5,
                max_shot_duration_s=8.0,
                max_shots_per_project=1,  # the fixture produces 2 shots
            )
