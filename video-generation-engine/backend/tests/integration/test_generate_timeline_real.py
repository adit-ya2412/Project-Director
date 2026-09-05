"""GenerateTimelineStep with DRY_RUN=false: proves the real Director ->
Scene Planner -> Shot Planner -> Asset Planner chain drives four separate
`append_version` calls (v2..v5), each additive, ending in a Timeline that
passes `validate_constraints` - and that a crash mid-chain resumes at the
exact planner stage it left off at, never redoing an earlier one (the
same resumability property M4 proved for whole workflow steps, one level
deeper for planner sub-stages within `generate_timeline` itself).

No real OpenAI call: `OpenAIPlanningProvider` is monkeypatched to a queued
fake that serves canned, pre-validated structured responses in the exact
order the chain calls them.
"""

import uuid as uuid_module

import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.llm_call import LlmCallModel
from app.planners.asset.schemas import AssetPlannerOutput, AssetPlanShotOutput
from app.planners.director.schemas import DirectorCreativeContext, DirectorMusicPlan, DirectorOutput
from app.planners.scene.schemas import ScenePlannerOutput, ScenePlanOutput
from app.planners.shot.schemas import (
    ShotCameraOutput,
    ShotPlannerOutput,
    ShotPlanOutput,
    ShotTransitionOutput,
)
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    AssetStrategy,
    CameraDirection,
    CameraMovement,
    EnergyArc,
    Framing,
    PreferredMediaType,
    RevealDirection,
    ShotIntent,
    TransitionType,
)
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps import generate_timeline as generate_timeline_module
from app.workflow.steps.generate_timeline import GenerateTimelineStep
from tests.unit.planners.helpers import FakePlanningProvider

SCRIPT = "Germany possessed abundant coal. But it lacked oil, and that would shape the war."


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("generate-timeline-real-test")
        project.script = SCRIPT
        await repo.update(project)
        return project.id


def _director_output() -> DirectorOutput:
    return DirectorOutput(
        creative_context=DirectorCreativeContext(
            tone="sober documentary",
            visual_style="1940s archival, desaturated",
            historical_period="1936-1945",
            audience="general",
            camera_language="static and slow push",
            constraints=["no swastika imagery"],
        ),
        music_plan=DirectorMusicPlan(
            mood="sombre",
            tempo="slow",
            energy_arc=EnergyArc.BUILD,
            search_terms=["documentary underscore"],
            licence_requirements=["cc0"],
        ),
    )


def _scene_output() -> ScenePlannerOutput:
    # SCRIPT splits into exactly 2 fragments (verified directly against
    # the real splitter - see test_scene_planner.py's own SCRIPT fixture,
    # the identical text): "Germany possessed abundant coal. " and
    # "But it lacked oil, and that would shape the war." - one fragment
    # per scene (S2 hardening, 2026-08-16 - fragment_start/fragment_end
    # replacing the old retyped narration_text).
    return ScenePlannerOutput(
        scenes=[
            ScenePlanOutput(
                id="sc_01",
                order=0,
                title="Coal wealth",
                summary="Germany had coal.",
                emotion="curiosity",
                narrative_purpose="setup",
                fragment_start=1,
                fragment_end=1,
                duration_s=4.0,
            ),
            ScenePlanOutput(
                id="sc_02",
                order=1,
                title="Oil deficit",
                summary="Germany lacked oil.",
                emotion="tension",
                narrative_purpose="conflict",
                fragment_start=2,
                fragment_end=2,
                duration_s=5.0,
            ),
        ]
    )


def _shot_output(scene_id: str, duration_s: float) -> ShotPlannerOutput:
    # Raw id deliberately does NOT encode scene_id - this mirrors the
    # real model, which reuses the same simple pattern every scene since
    # each call only ever sees one scene. ShotPlanner namespaces by
    # scene_id afterwards, so the final persisted id is f"{scene_id}_sh_01"
    # - see _asset_output below, which must match that final id.
    #
    # Exactly ONE shot, covering the scene's single fragment (M5
    # hardening, 2026-08-15): each scene here is one plain sentence with
    # no internal sentence-ending punctuation until its own final full
    # stop, so `split_narration_fragments` produces exactly one fragment
    # for it - and a fragment can never be split between two shots (see
    # app/planners/fragments.py's own docstring). This test is
    # about the four-planner CHAIN's resumability, not shot count, so
    # one shot per scene exercises it identically to two.
    return ShotPlannerOutput(
        shots=[
            ShotPlanOutput(
                id="sh_01",
                order=0,
                intent=ShotIntent.EXPLAIN,
                intent_text="the whole scene",
                fragment_start=1,
                fragment_end=1,
                duration_s=duration_s,
                framing=Framing.WIDE,
                camera=ShotCameraOutput(
                    movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.IN, intensity=0.15
                ),
                transition_out=ShotTransitionOutput(type=TransitionType.CUT, duration_s=0.0),
                prompt="archival photograph",
                secondary_prompt="",
                text_card="",
                sfx_cue="",
                layers=[],
                reveal_direction=RevealDirection.NONE,
                reveal_start_fragment=0,
                reveal_end_fragment=0,
            ),
        ]
    )


def _asset_output(scene_id: str) -> AssetPlannerOutput:
    # Must match the shot id ShotPlanner actually persists: scene_id,
    # namespaced onto the raw "sh_01" id from _shot_output above.
    return AssetPlannerOutput(
        asset_plans=[
            AssetPlanShotOutput(
                shot_id=f"{scene_id}_sh_01",
                entity="",
                strategy=AssetStrategy.HISTORICAL_SEARCH,
                search_queries=["archival search term"],
                preferred_type=PreferredMediaType.IMAGE,
                fallback_chain=[AssetStrategy.HISTORICAL_SEARCH, AssetStrategy.GENERATE_IMAGE],
                licence_requirements=["public_domain"],
            ),
        ],
        secondary_asset_plans=[],
    )


def _full_response_queue() -> list:
    scenes = _scene_output().scenes
    return [
        _director_output(),
        _scene_output(),
        _shot_output(scenes[0].id, scenes[0].duration_s),
        _shot_output(scenes[1].id, scenes[1].duration_s),
        _asset_output(scenes[0].id),
        _asset_output(scenes[1].id),
    ]


async def _llm_call_count(project_id: str) -> int:
    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(LlmCallModel).where(
                        LlmCallModel.project_id == uuid_module.UUID(project_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        return len(rows)


async def test_real_chain_produces_a_fully_planned_timeline(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    provider = FakePlanningProvider(responses=_full_response_queue())
    monkeypatch.setattr(generate_timeline_module, "OpenAIPlanningProvider", lambda: provider)

    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        result = await GenerateTimelineStep().run(ctx)

    assert result.outcome == "ok"
    assert len(provider.calls) == 6

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)

    assert timeline.version == 5  # v1 create_initial, v2..v5 the four planners
    assert timeline.creative_context.tone == "sober documentary"
    assert timeline.music_plan.energy_arc == EnergyArc.BUILD
    assert len(timeline.scenes) == 2
    all_shots = timeline.all_shots()
    assert len(all_shots) == 2  # one shot per scene - each scene is a single fragment
    assert all(shot.asset_plan is not None for shot in all_shots)
    assert timeline.metadata.total_duration_s > 0

    violations = timeline.validate_constraints(
        max_video_duration_s=settings.max_video_duration_s,
        max_shots_per_project=settings.max_shots_per_project,
        min_shot_duration_s=settings.min_shot_duration_s,
        max_shot_duration_s=settings.max_shot_duration_s,
        max_scenes=settings.max_scenes,
    )
    assert violations == []

    step = GenerateTimelineStep()
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        assert await step.is_satisfied(ctx) is True


async def test_crash_mid_chain_resumes_at_the_next_planner_stage_only(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)

    # "Process 1": only enough responses for Director + Scene Planner.
    # The Shot Planner's call then pops from an empty queue and raises -
    # standing in for a crash right after Scene Planner's append_version
    # committed (v3) and before Shot Planner started.
    provider_holder = {
        "provider": FakePlanningProvider(responses=[_director_output(), _scene_output()])
    }
    monkeypatch.setattr(
        generate_timeline_module, "OpenAIPlanningProvider", lambda: provider_holder["provider"]
    )

    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        first_result = await GenerateTimelineStep().run(ctx)

    assert first_result.outcome == "failed"  # the simulated crash

    async with async_session_factory() as session:
        after_crash = await TimelineService(session).get_active(project_id)
    assert after_crash.version == 3  # v1 create_initial, v2 director, v3 scene
    assert after_crash.creative_context.tone == "sober documentary"
    assert all(not scene.shots for scene in after_crash.scenes)
    assert await _llm_call_count(project_id) == 2

    # "Process 2": a completely fresh provider seeded with only the
    # remaining stages. If the chain incorrectly re-ran Director or Scene
    # Planner it would immediately raise (empty queue / wrong schema).
    scenes = after_crash.scenes
    provider_holder["provider"] = FakePlanningProvider(
        responses=[
            _shot_output(scenes[0].id, scenes[0].duration_s),
            _shot_output(scenes[1].id, scenes[1].duration_s),
            _asset_output(scenes[0].id),
            _asset_output(scenes[1].id),
        ]
    )

    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        second_result = await GenerateTimelineStep().run(ctx)

    assert second_result.outcome == "ok"
    assert (
        len(provider_holder["provider"].calls) == 4
    )  # only shot + asset, not director/scene again

    async with async_session_factory() as session:
        final = await TimelineService(session).get_active(project_id)
    assert final.version == 5
    assert all(shot.asset_plan is not None for shot in final.all_shots())

    # Exactly 2 (process 1) + 4 (process 2) llm_call rows - proof Director
    # and Scene Planner were never invoked a second time.
    assert await _llm_call_count(project_id) == 6
