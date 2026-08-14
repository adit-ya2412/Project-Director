"""Golden-file test for the Scene Planner: verifies the additive-ready
Scene objects it produces, and the two hardest validation rules -
verbatim script coverage and the max_scenes cap."""

import uuid

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.planners.repair import run_structured_with_repair
from app.planners.scene.planner import ScenePlanner
from app.planners.scene.schemas import ScenePlannerOutput, ScenePlanOutput
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import CreativeContext

from .helpers import FakePlanningProvider

SCRIPT = "Germany possessed abundant coal. But it lacked oil, and that would shape the war."


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("scene-planner-test")
        return project.id


def _valid_output() -> ScenePlannerOutput:
    return ScenePlannerOutput(
        scenes=[
            ScenePlanOutput(
                id="sc_01",
                order=0,
                title="Coal wealth",
                summary="Germany had coal.",
                emotion="curiosity",
                narrative_purpose="setup",
                narration_text="Germany possessed abundant coal.",
                duration_s=4.0,
            ),
            ScenePlanOutput(
                id="sc_02",
                order=1,
                title="Oil deficit",
                summary="Germany lacked oil.",
                emotion="tension",
                narrative_purpose="conflict",
                narration_text=" But it lacked oil, and that would shape the war.",
                duration_s=5.0,
            ),
        ]
    )


async def test_scene_plan_produces_ordered_scenes_with_empty_shots(project_id):
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        creative_context = CreativeContext(tone="sober", visual_style="archival")
        planner = ScenePlanner(provider, LlmCallRepository(session))

        scenes = await planner.plan(
            project_id=project_id,
            script=SCRIPT,
            creative_context=creative_context,
            max_scenes=12,
            max_video_duration_s=90.0,
        )

    assert [s.id for s in scenes] == ["sc_01", "sc_02"]
    assert all(s.shots == [] for s in scenes)
    assert scenes[0].duration_s == 4.0


async def test_scene_plan_rejects_script_coverage_mismatch(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    tampered = _valid_output()
    tampered.scenes[1].narration_text = " completely different words here"

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[tampered, tampered])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="reproduce the script"):
            await planner.plan(
                project_id=project_id,
                script=SCRIPT,
                creative_context=CreativeContext(),
                max_scenes=12,
                max_video_duration_s=90.0,
            )


async def test_scene_plan_rejects_too_many_scenes(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    too_many = _valid_output()

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[too_many, too_many])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="exceeds the maximum"):
            await planner.plan(
                project_id=project_id,
                script=SCRIPT,
                creative_context=CreativeContext(),
                max_scenes=1,
                max_video_duration_s=90.0,
            )


async def test_run_structured_with_repair_is_reused_correctly(project_id):
    # Sanity check that ScenePlanner is built on the shared repair helper,
    # not a bespoke loop - a regression here would desync the two.
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        result = await run_structured_with_repair(
            provider=provider,
            llm_call_repo=LlmCallRepository(session),
            project_id=uuid.UUID(project_id),
            agent="scene_planner",
            prompt_version="v1",
            system_prompt="sys",
            user_content="user",
            response_model=ScenePlannerOutput,
            validate=lambda _output: [],
        )
    assert isinstance(result, ScenePlannerOutput)
