"""Golden-file test for the Shot Planner: verifies narration-span
coverage, per-scene looping, and the running max_shots_per_project cap.

Also covers the narration-boundary snap (the ShotPlanner's first shot's
`narration_start` and last shot's `narration_end` are structural facts,
not creative decisions - see `app/planners/shot/planner.py`'s own
docstrings): a model output that is a few characters short at the very
end must still succeed, one with a genuine INTERNAL gap must still fail,
and a large end-boundary miss must still succeed but log a warning."""

import logging

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


def _shot(
    *,
    shot_id: str,
    order: int,
    narration_start: int,
    narration_end: int,
    duration_s: float,
) -> ShotPlanOutput:
    return ShotPlanOutput(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        intent_text="text",
        narration_start=narration_start,
        narration_end=narration_end,
        duration_s=duration_s,
        framing=Framing.WIDE,
        camera=ShotCameraOutput(
            movement=CameraMovement.STATIC, direction=CameraDirection.NONE, intensity=0.0
        ),
        transition_out=ShotTransitionOutput(type=TransitionType.CUT, duration_s=0.0),
        prompt="archival photograph",
    )


def _output_with_end_short_by(scene: Scene, drift: int) -> ShotPlannerOutput:
    """Two shots tiling the scene correctly except the last shot's
    `narration_end` is `drift` characters short of the true scene length -
    exactly the shape of the real bug report (144 vs 140)."""
    mid = len(scene.narration_text) // 2
    return ShotPlannerOutput(
        shots=[
            _shot(shot_id="sh_01", order=0, narration_start=0, narration_end=mid, duration_s=1.5),
            _shot(
                shot_id="sh_02",
                order=1,
                narration_start=mid,
                narration_end=len(scene.narration_text) - drift,
                duration_s=1.5,
            ),
        ]
    )


def _output_with_internal_gap(scene: Scene) -> ShotPlannerOutput:
    """Three shots whose outer boundaries are exactly right (0 and the
    full scene length) but whose middle shot leaves a real gap before it -
    the class of error the snap must NOT paper over."""
    quarter = len(scene.narration_text) // 4
    return ShotPlannerOutput(
        shots=[
            _shot(
                shot_id="sh_01", order=0, narration_start=0, narration_end=quarter, duration_s=1.5
            ),
            _shot(
                shot_id="sh_02",
                order=1,
                # A real gap: skips several characters instead of picking
                # up exactly where shot 1 left off.
                narration_start=quarter + 5,
                narration_end=2 * quarter,
                duration_s=1.5,
            ),
            _shot(
                shot_id="sh_03",
                order=2,
                narration_start=2 * quarter,
                narration_end=len(scene.narration_text),
                duration_s=1.5,
            ),
        ]
    )


async def test_shot_plan_snaps_a_narration_end_short_by_a_few_characters(project_id):
    """The real bug: the model's last shot ended 4 characters short of the
    scene's true length (a trailing space before the final full stop).
    That must no longer fail the whole scene - it must snap and succeed
    on the FIRST attempt (no repair round needed)."""
    scene = _scene()
    drift = 4
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(scene, drift)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
        )

    assert len(provider.calls) == 1  # no repair round needed
    shots = planned[0].shots
    assert shots[0].narration_span[0] == 0
    assert shots[-1].narration_span[1] == len(scene.narration_text)


async def test_shot_plan_still_fails_on_a_genuine_internal_gap(project_id, monkeypatch):
    """The snap only ever touches the two OUTER boundaries. A gap between
    two INTERNAL shots is a real structural error and must still fail
    loudly, even though both outer boundaries are correct in this output."""
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    async with async_session_factory() as session:
        # Two identical bad responses: the repair round doesn't fix a
        # canned fake's output, so this proves the failure survives past
        # the repair attempt rather than being a fluke of only trying once.
        provider = FakePlanningProvider(
            responses=[_output_with_internal_gap(scene), _output_with_internal_gap(scene)]
        )
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="must equal"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert len(provider.calls) == 2  # original attempt + one repair, both rejected


async def test_shot_plan_snaps_a_large_narration_end_drift_but_logs_a_warning(project_id, caplog):
    """A 4-character miss is the model being imprecise about a trailing
    space; a large miss means it likely misunderstood the scene boundary
    entirely. Both must still snap and succeed - the render still needs a
    video - but the large one must be visible in the logs so a human can
    notice a planner regression instead of it silently sliding by."""
    scene = _scene()
    drift = 15  # comfortably past _LARGE_SNAP_THRESHOLD_CHARS (10)
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(scene, drift)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with caplog.at_level(logging.WARNING, logger="app.planners.shot.planner"):
            planned = await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert len(provider.calls) == 1
    assert planned[0].shots[-1].narration_span[1] == len(scene.narration_text)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].message == "shot_planner.snapped_narration_end"
    assert warnings[0].drift_chars == drift


async def test_shot_plan_snaps_a_small_narration_end_drift_without_a_warning(project_id, caplog):
    """The real bug's own scale (4 characters) must stay a quiet, routine
    correction - not something that spams the logs on every ordinary,
    slightly-imprecise model output."""
    scene = _scene()
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(scene, 4)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with caplog.at_level(logging.INFO, logger="app.planners.shot.planner"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert not any(r.levelno == logging.WARNING for r in caplog.records)
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert info_records[0].drift_chars == 4


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
