"""WorkflowEngine — resumability, retry/backoff, and per-step failure
isolation. Needs real Postgres (docs/12_Testing_Strategy.md: integration
tests, unlike unit tests, are allowed to hit the database) since the
engine's own resumability proof requires observable, persisted state
across genuinely separate sessions - the same thing a real process
restart would see.
"""

import uuid as uuid_module

import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.workflow_repository import WorkflowRunRepository
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.engine import WorkflowEngine
from app.workflow.step import StepResult
from app.workflow.steps.generate_timeline import GenerateTimelineStep


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("workflow-engine-test")
        return project.id


class _FlakyStep:
    """Returns outcome="retry" `fail_times` times, then succeeds."""

    name = "flaky"
    retryable = True
    max_attempts = 5

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def is_satisfied(self, ctx) -> bool:
        return False

    async def run(self, ctx) -> StepResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            return StepResult(outcome="retry", error=f"transient failure #{self.calls}")
        return StepResult(outcome="ok")


class _DoomedStep:
    name = "doomed"
    retryable = False
    max_attempts = 1

    async def is_satisfied(self, ctx) -> bool:
        return False

    async def run(self, ctx) -> StepResult:
        return StepResult(outcome="failed", error="this step can never succeed")


async def test_retryable_step_succeeds_after_transient_failures(project_id):
    step = _FlakyStep(fail_times=2)
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        engine = WorkflowEngine(ctx, steps=[step], base_delay_s=0.01)
        project = await engine.run()

    assert step.calls == 3  # two failures, then success
    assert project.status.value != "failed"


async def test_retryable_step_exhausts_attempts_and_fails(project_id):
    # Never returns "ok" - retries up to max_attempts, then the engine
    # converts the last "retry" into a "failed" outcome.
    step = _FlakyStep(fail_times=999)
    step.max_attempts = 3
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        engine = WorkflowEngine(ctx, steps=[step], base_delay_s=0.01)
        project = await engine.run()

    assert step.calls == 3
    assert project.status.value == "failed"
    assert "transient failure #3" in project.error


async def test_permanent_failure_stops_with_clear_error_and_is_inspectable(project_id):
    step = _DoomedStep()
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        engine = WorkflowEngine(ctx, steps=[step], base_delay_s=0.01)
        project = await engine.run()

    assert project.status.value == "failed"
    assert project.error == "this step can never succeed"

    # State is inspectable afterward via a completely fresh read, not
    # just the value the engine happened to return inline.
    async with async_session_factory() as session:
        refetched = await PostgresProjectRepository(session).get(project_id)
    assert refetched.status.value == "failed"
    assert refetched.error == "this step can never succeed"


async def test_resume_after_simulated_crash_does_not_redo_completed_steps(project_id, monkeypatch):
    """Simulates killing the process right after generate_timeline commits:
    a brand-new WorkflowEngine (fresh session, standing in for a fresh
    process) must skip it via is_satisfied(), not re-run it - re-running
    would call append_version again and bump the timeline to v3.

    Pinned to the fake planner path regardless of the ambient .env's
    DRY_RUN value - this test is about engine-level resumability, not
    about which planner chain fills the timeline, and must not silently
    make real, paid OpenAI calls just because a developer's local .env
    has DRY_RUN=false for a live manual test.
    """
    monkeypatch.setattr(settings, "dry_run", True)
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.get(project_id)
        project.script = "a script for the resumability test"
        await repo.update(project)

    # "Process 1": runs only generate_timeline, then stops (as if killed).
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        await WorkflowEngine(ctx, steps=[GenerateTimelineStep()]).run()

    async with async_session_factory() as session:
        after_first_process = await TimelineService(session).get_active(project_id)
    assert after_first_process is not None
    assert after_first_process.version == 2  # v1 create_initial, v2 append_version
    assert len(after_first_process.scenes) > 0

    # "Process 2": a completely fresh engine, full default pipeline. It
    # must land at the approval gate without touching generate_timeline
    # again.
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        result = await WorkflowEngine(ctx).run()

    assert result.timeline.version == 2  # unchanged - generate_timeline was skipped

    async with async_session_factory() as session:
        run_row = await WorkflowRunRepository(session).get_latest(uuid_module.UUID(project_id))
    assert run_row.state == "awaiting_approval"
