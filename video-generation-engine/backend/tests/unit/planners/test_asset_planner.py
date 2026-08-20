"""Golden-file test for the Asset Planner: verifies the ladder-ordering
and licence-requirement validation rules, and that asset_plans attach to
the correct shot by id."""

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.planners.asset.planner import AssetPlanner
from app.planners.asset.schemas import AssetPlannerOutput, AssetPlanShotOutput
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    AssetStrategy,
    Camera,
    CameraMovement,
    PreferredMediaType,
    Scene,
    Shot,
    ShotIntent,
)

from .helpers import FakePlanningProvider


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("asset-planner-test")
        return project.id


def _scene_with_shots() -> Scene:
    shots = [
        Shot(
            id="sh_01",
            order=0,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            prompt="1930s coal mine, archival photograph",
        ),
        Shot(
            id="sh_02",
            order=1,
            intent=ShotIntent.REVEAL,
            duration_s=3.0,
            prompt="1930s map of Europe, archival cartography",
        ),
    ]
    return Scene(id="sc_01", order=0, title="Coal wealth", duration_s=6.0, shots=shots)


def _valid_output() -> AssetPlannerOutput:
    return AssetPlannerOutput(
        asset_plans=[
            AssetPlanShotOutput(
                shot_id="sh_01",
                entity="",
                strategy=AssetStrategy.HISTORICAL_SEARCH,
                search_queries=["Ruhr coal mine 1936"],
                preferred_type=PreferredMediaType.IMAGE,
                fallback_chain=[
                    AssetStrategy.HISTORICAL_SEARCH,
                    AssetStrategy.PUBLIC_DOMAIN,
                    AssetStrategy.GENERATE_IMAGE,
                ],
                licence_requirements=["public_domain", "cc0"],
            ),
            AssetPlanShotOutput(
                shot_id="sh_02",
                entity="",
                strategy=AssetStrategy.PUBLIC_DOMAIN,
                search_queries=["1930s Europe map"],
                preferred_type=PreferredMediaType.IMAGE,
                fallback_chain=[AssetStrategy.PUBLIC_DOMAIN, AssetStrategy.GENERATE_IMAGE],
                licence_requirements=["public_domain"],
            ),
        ],
        secondary_asset_plans=[],
    )


async def test_asset_planner_prompt_includes_each_shots_camera_movement(project_id):
    """A real, previously-verified gap (2026-08-18): the prompt's own
    `preferred_type` rule (app/prompts/asset_planner/v1.md) says to judge
    by "the shot's camera movement", but `_build_user_content` never
    actually sent that field - the model was asked to use a signal it
    could not see. Fixed by including it; proven here against the real
    text handed to the provider, not just by reading the diff."""
    shots = [
        Shot(
            id="sh_01",
            order=0,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            prompt="1930s coal mine, archival photograph",
            camera=Camera(movement=CameraMovement.SLOW_PUSH),
        ),
    ]
    scene = Scene(id="sc_01", order=0, title="Coal wealth", duration_s=3.0, shots=shots)
    output = AssetPlannerOutput(
        asset_plans=[
            AssetPlanShotOutput(
                shot_id="sh_01",
                entity="",
                strategy=AssetStrategy.HISTORICAL_SEARCH,
                search_queries=["Ruhr coal mine 1936"],
                preferred_type=PreferredMediaType.IMAGE,
                fallback_chain=[AssetStrategy.HISTORICAL_SEARCH, AssetStrategy.GENERATE_IMAGE],
                licence_requirements=["public_domain"],
            )
        ],
        secondary_asset_plans=[],
    )

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[output])
        planner = AssetPlanner(provider, LlmCallRepository(session))
        await planner.plan(
            project_id=project_id,
            scenes=[scene],
            max_video_shots_per_project=settings.max_video_shots_per_project,
        )

    assert "camera=slow_push" in provider.calls[0]["user_content"]


async def test_asset_plan_attaches_to_correct_shots(project_id):
    scene = _scene_with_shots()
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        planner = AssetPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            max_video_shots_per_project=settings.max_video_shots_per_project,
        )

    shots = planned[0].shots
    assert shots[0].asset_plan.strategy == AssetStrategy.HISTORICAL_SEARCH
    assert shots[1].asset_plan.strategy == AssetStrategy.PUBLIC_DOMAIN
    assert shots[0].asset_plan.fallback_chain[-1] == AssetStrategy.GENERATE_IMAGE


async def test_asset_plan_rejects_out_of_order_ladder(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene_with_shots()
    bad = _valid_output()
    # stock_search (rung 3) before historical_search (rung 1) - descending.
    bad.asset_plans[0].fallback_chain = [
        AssetStrategy.STOCK_SEARCH,
        AssetStrategy.HISTORICAL_SEARCH,
    ]
    bad.asset_plans[0].strategy = AssetStrategy.STOCK_SEARCH

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[bad, bad])
        planner = AssetPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="ladder order"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                max_video_shots_per_project=settings.max_video_shots_per_project,
            )


async def test_asset_plan_rejects_sentence_length_search_queries(project_id, monkeypatch):
    """A search_query written as a descriptive sentence rather than a
    short keyword phrase reliably returns zero results from real archive
    search APIs (verified empirically against the live Wikimedia Commons
    API) - this must be caught and repaired, not shipped."""
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene_with_shots()
    bad = _valid_output()
    bad.asset_plans[0].search_queries = [
        "Germany coal hydrogenation plant 1940 workers pipes pressure vessels"
    ]

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[bad, bad])
        planner = AssetPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="too long"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                max_video_shots_per_project=settings.max_video_shots_per_project,
            )


async def test_asset_plan_fails_loudly_once_the_video_shot_cap_is_exceeded(project_id):
    """A4 (motion_new_styles_and_long_form_videos.md, 2026-08-18): the
    cap is a running, cross-scene count checked and failed the moment
    it's exceeded - mirroring `ShotPlanner.plan()`'s own `max_shots_per_
    project` check exactly (same file, same "loud failure, never silent
    merging" reasoning, since the model is never asked to reduce its own
    video count)."""
    scene = _scene_with_shots()
    both_video = _valid_output()
    both_video.asset_plans[0].preferred_type = PreferredMediaType.VIDEO
    both_video.asset_plans[0].strategy = AssetStrategy.GENERATE_VIDEO
    both_video.asset_plans[0].fallback_chain = [
        AssetStrategy.GENERATE_VIDEO,
        AssetStrategy.GENERATE_IMAGE,
    ]
    both_video.asset_plans[1].preferred_type = PreferredMediaType.VIDEO
    both_video.asset_plans[1].strategy = AssetStrategy.GENERATE_VIDEO
    both_video.asset_plans[1].fallback_chain = [
        AssetStrategy.GENERATE_VIDEO,
        AssetStrategy.GENERATE_IMAGE,
    ]

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[both_video])
        planner = AssetPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="max_video_shots_per_project"):
            await planner.plan(project_id=project_id, scenes=[scene], max_video_shots_per_project=1)


async def test_asset_plan_rejects_missing_licence_requirements(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene_with_shots()
    bad = _valid_output()
    bad.asset_plans[0].licence_requirements = []

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[bad, bad])
        planner = AssetPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="licence_requirements"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                max_video_shots_per_project=settings.max_video_shots_per_project,
            )


def _split_plan() -> AssetPlanShotOutput:
    return AssetPlanShotOutput(
        shot_id="sh_01",
        entity="Leuna-Werke",
        strategy=AssetStrategy.HISTORICAL_SEARCH,
        search_queries=["Leuna Werke 1943"],
        preferred_type=PreferredMediaType.IMAGE,
        fallback_chain=[AssetStrategy.HISTORICAL_SEARCH, AssetStrategy.GENERATE_IMAGE],
        licence_requirements=["public_domain"],
    )


async def test_split_frame_requires_a_secondary_plan(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=3.0,
        prompt="Leuna plant",
        secondary_prompt="Sasol plant",
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
    )
    scene = Scene(id="sc_01", order=0, title="Compare", duration_s=3.0, shots=[shot])
    missing = AssetPlannerOutput(asset_plans=[_split_plan()], secondary_asset_plans=[])
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[missing, missing])
        planner = AssetPlanner(provider, LlmCallRepository(session))
        with pytest.raises(PermanentError, match="secondary_asset_plans"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                max_video_shots_per_project=settings.max_video_shots_per_project,
            )


async def test_split_frame_attaches_the_secondary_plan(project_id):
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=3.0,
        prompt="Leuna plant",
        secondary_prompt="Sasol plant",
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
    )
    scene = Scene(id="sc_01", order=0, title="Compare", duration_s=3.0, shots=[shot])
    bottom = _split_plan()
    bottom.search_queries = ["Sasol Secunda"]
    output = AssetPlannerOutput(asset_plans=[_split_plan()], secondary_asset_plans=[bottom])
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[output])
        planner = AssetPlanner(provider, LlmCallRepository(session))
        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            max_video_shots_per_project=settings.max_video_shots_per_project,
        )
    attached = planned[0].shots[0]
    assert attached.asset_plan is not None
    assert attached.secondary_asset_plan is not None
    assert attached.secondary_asset_plan.search_queries == ["Sasol Secunda"]
    assert "secondary_prompt=Sasol plant" in provider.calls[0]["user_content"]
