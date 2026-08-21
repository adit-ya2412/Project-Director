"""Golden-file test for the Director agent: a canned structured response
in, a CreativeContext/MusicPlan out, no network call. Also proves the
one-repair-then-fail discipline (implementation guide, Phase M5 advice)."""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.models.llm_call import LlmCallModel
from app.planners.director.planner import DirectorPlanner
from app.planners.director.schemas import DirectorCreativeContext, DirectorMusicPlan, DirectorOutput
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import EnergyArc

from .helpers import FakePlanningProvider


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("director-planner-test")
        return project.id


def _valid_output() -> DirectorOutput:
    return DirectorOutput(
        creative_context=DirectorCreativeContext(
            tone="sober documentary",
            visual_style="1940s archival, desaturated",
            historical_period="1936-1945",
            audience="general",
            camera_language="static and slow push; no whip pans",
            constraints=["no swastika imagery"],
        ),
        music_plan=DirectorMusicPlan(
            mood="sombre, restrained",
            tempo="slow",
            energy_arc=EnergyArc.BUILD,
            search_terms=["documentary underscore", "sparse strings"],
            licence_requirements=["cc0"],
        ),
    )


async def test_director_plan_produces_creative_context_and_music_plan(project_id):
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        planner = DirectorPlanner(provider, LlmCallRepository(session))

        creative_context, music_plan = await planner.plan(
            project_id=project_id, script="Germany possessed abundant coal."
        )

    assert creative_context.tone == "sober documentary"
    assert creative_context.historical_period == "1936-1945"
    assert creative_context.colour_palette == []
    assert music_plan.energy_arc == EnergyArc.BUILD
    assert len(provider.calls) == 1


async def test_director_plan_repairs_once_then_succeeds(project_id):
    invalid = _valid_output()
    invalid.creative_context.tone = ""  # triggers a validation violation
    valid = _valid_output()

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[invalid, valid])
        planner = DirectorPlanner(provider, LlmCallRepository(session))

        creative_context, _ = await planner.plan(
            project_id=project_id, script="Germany possessed abundant coal."
        )

    assert creative_context.tone == "sober documentary"
    assert len(provider.calls) == 2
    # The repaired prompt must carry the violation back to the model.
    assert "tone must not be empty" in provider.calls[1]["user_content"]


async def test_director_plan_fails_permanently_after_one_repair(project_id, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    invalid = _valid_output()
    invalid.creative_context.tone = ""
    still_invalid = _valid_output()
    still_invalid.creative_context.tone = ""

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[invalid, still_invalid])
        planner = DirectorPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError):
            await planner.plan(project_id=project_id, script="a script")

    assert len(provider.calls) == 2


async def test_every_attempt_is_recorded_as_an_llm_call(project_id):
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        planner = DirectorPlanner(provider, LlmCallRepository(session))
        await planner.plan(project_id=project_id, script="a script")
        await session.commit()

    async with async_session_factory() as session:
        rows = (
            (await session.execute(select(LlmCallModel).where(LlmCallModel.agent == "director")))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].prompt_version == "v1"
