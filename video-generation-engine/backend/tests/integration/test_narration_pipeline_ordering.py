"""Proves NarrationStep's placement in `DEFAULT_PIPELINE`: it must run
AFTER `AwaitApprovalStep` (I6 - TTS costs money) and BEFORE
`ResolveAssetsStep`. Getting the order wrong would have `ResolveAssetsStep`
bind against the pre-narration timeline version - orphaning every
`ShotBinding` row the moment narration appends its own version - or, if
narration ran first, would fail I6 entirely.

Exercises the real DRY_RUN pipeline (fake planner + fake asset/image
providers, real Postgres) through `ResolveAssetsStep` - `RenderStep` needs
a real FFmpeg binary and is out of scope here (see tests/e2e, which is
skipped in this environment for the same reason).
"""

import uuid as uuid_module

import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.engine import DEFAULT_PIPELINE, WorkflowEngine
from app.workflow.steps.await_approval import AwaitApprovalStep
from app.workflow.steps.generate_timeline import GenerateTimelineStep
from app.workflow.steps.narration import NarrationStep
from app.workflow.steps.resolve_assets import ResolveAssetsStep

_SCRIPT = (
    "Germany possessed abundant coal, fueling its factories and its "
    "ambitions. But it lacked one vital resource: oil, and that "
    "dependency would shape the war to come. That single gap in "
    "resources would drive strategic decisions with consequences the "
    "world still remembers."
)


def test_default_pipeline_runs_narration_between_approval_and_resolve_assets():
    names = [step.name for step in DEFAULT_PIPELINE]
    assert names.index("await_approval") < names.index("narration") < names.index("resolve_assets")


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("narration-pipeline-order-test")
        project.script = _SCRIPT
        await repo.update(project)
        return project.id


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


async def test_resolve_assets_binds_against_the_post_narration_version(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_x")
    steps = [GenerateTimelineStep(), AwaitApprovalStep(), NarrationStep(), ResolveAssetsStep()]

    # Run 1: generate_timeline fills v2 from the fixture, then the engine
    # stops cleanly at the (still unapproved) approval gate - narration
    # must not have run yet (I6: nothing expensive before approval).
    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    async with async_session_factory() as session:
        pre_narration = await TimelineService(session).get_active(project_id)
    assert pre_narration.status.value == "draft"
    assert pre_narration.produced_by.value != "narration"

    # A human approves the pre-narration plan, exactly like the API does.
    async with async_session_factory() as session:
        await TimelineService(session).approve(project_id, pre_narration.version)

    # Run 2: resumes past generate_timeline and await_approval, runs
    # narration (appends + self-approves a new version), then
    # resolve_assets - which must bind against THAT new version.
    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    async with async_session_factory() as session:
        final_timeline = await TimelineService(session).get_active(project_id)
        bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), final_timeline.version
        )
        stale_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), pre_narration.version
        )

    assert final_timeline.produced_by.value == "narration"
    assert final_timeline.version == pre_narration.version + 1
    # Every shot got a binding against the NEW version...
    assert len(bindings) == len(final_timeline.all_shots()) > 0
    assert all(b.state in {"resolved", "generated"} for b in bindings)
    # ...and none against the stale, pre-narration one - proving
    # resolve_assets never bound to the orphaned version.
    assert stale_bindings == []
