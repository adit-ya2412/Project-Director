"""Act Planner tiling — same invariant as the Scene Planner, coarser."""

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.planners.act.planner import ActPlanner
from app.planners.act.schemas import ActPlannerOutput, ActPlanOutput
from app.planners.fragments import split_narration_fragments
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import CreativeContext

from .helpers import FakePlanningProvider

MULTI_SCRIPT = (
    "Germany possessed abundant coal. It powered every factory. "
    "But oil remained scarce. Ships waited empty at port. "
    "That gap would shape the war."
)


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("act-planner-test")
        return project.id


async def test_act_plan_tiles_and_slices_the_script(project_id):
    assert len(split_narration_fragments(MULTI_SCRIPT)) == 5
    output = ActPlannerOutput(
        acts=[
            ActPlanOutput(id="act_01", order=0, title="Coal", fragment_start=1, fragment_end=2),
            ActPlanOutput(id="act_02", order=1, title="Oil", fragment_start=3, fragment_end=5),
        ]
    )
    async with async_session_factory() as session:
        planner = ActPlanner(FakePlanningProvider([output]), LlmCallRepository(session))
        acts = await planner.plan(
            project_id=project_id,
            script=MULTI_SCRIPT,
            creative_context=CreativeContext(),
            min_acts=2,
            max_acts=5,
        )
    assert [a.id for a in acts] == ["act_01", "act_02"]
    assert "".join(a.script_slice for a in acts) == MULTI_SCRIPT
    assert len(split_narration_fragments(acts[0].script_slice)) == 2
    assert len(split_narration_fragments(acts[1].script_slice)) == 3


async def test_act_plan_rejects_too_few_acts(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    output = ActPlannerOutput(
        acts=[
            ActPlanOutput(id="act_01", order=0, title="All", fragment_start=1, fragment_end=5),
        ]
    )
    async with async_session_factory() as session:
        planner = ActPlanner(
            FakePlanningProvider([output, output]), LlmCallRepository(session)
        )
        with pytest.raises(PermanentError, match="outside the allowed range"):
            await planner.plan(
                project_id=project_id,
                script=MULTI_SCRIPT,
                creative_context=CreativeContext(),
                min_acts=3,
                max_acts=7,
            )
