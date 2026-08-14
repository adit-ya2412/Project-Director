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
from app.schemas.timeline import AssetStrategy, PreferredMediaType, Scene, Shot, ShotIntent

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
                strategy=AssetStrategy.PUBLIC_DOMAIN,
                search_queries=["1930s Europe map"],
                preferred_type=PreferredMediaType.IMAGE,
                fallback_chain=[AssetStrategy.PUBLIC_DOMAIN, AssetStrategy.GENERATE_IMAGE],
                licence_requirements=["public_domain"],
            ),
        ]
    )


async def test_asset_plan_attaches_to_correct_shots(project_id):
    scene = _scene_with_shots()
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        planner = AssetPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(project_id=project_id, scenes=[scene])

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
            await planner.plan(project_id=project_id, scenes=[scene])


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
            await planner.plan(project_id=project_id, scenes=[scene])


async def test_asset_plan_rejects_missing_licence_requirements(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene_with_shots()
    bad = _valid_output()
    bad.asset_plans[0].licence_requirements = []

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[bad, bad])
        planner = AssetPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="licence_requirements"):
            await planner.plan(project_id=project_id, scenes=[scene])
