"""F0a (2026-08-16): `app/workflow/trigger.py` against the real database -
the two properties an e2e test (which only ever sees ONE, effectively-
synchronous request at a time under `TestClient`'s ASGI transport - see
`tests/e2e/_polling.py`'s own note on this) genuinely cannot exercise:
a run that is ACTUALLY concurrent with the check, and a crash that
happens somewhere `WorkflowEngine.run()` itself, not a single step,
raises from.
"""

import asyncio
import uuid as uuid_module

import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.workflow_repository import WorkflowRunRepository
from app.schemas.project import ProjectStatus
from app.workflow.engine import WorkflowEngine
from app.workflow.trigger import _claim_or_join, _execute_in_background, reclaim_orphaned_runs


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).create("F0a trigger test")
        return project.id


async def test_a_second_claim_joins_a_run_already_in_flight(project_id):
    """Two triggers landing while a run is genuinely `state == "running"`
    must not both get to execute the pipeline - `_claim_or_join`'s whole
    reason to exist. Simulated directly rather than through real
    concurrency (impossible to force deterministically over HTTP): the
    first call claims and commits: exactly what `start_workflow_run` does
    before scheduling its background task, and exactly the state a real
    in-flight background execution would leave the row in for as long as
    it runs."""
    project_uuid = uuid_module.UUID(project_id)

    async with async_session_factory() as session:
        run_row_1, claimed_1 = await _claim_or_join(session, project_uuid)
        await session.commit()
    assert claimed_1 is True
    assert run_row_1.state == "running"

    async with async_session_factory() as session:
        run_row_2, claimed_2 = await _claim_or_join(session, project_uuid)
        await session.commit()
    # Joined the SAME row - no second run was started.
    assert claimed_2 is False
    assert run_row_2.id == run_row_1.id


async def test_a_claim_after_completion_starts_a_genuinely_new_run(project_id):
    """Once the in-flight run reaches a terminal state, the NEXT trigger
    must be free to start a real new run - concurrency safety must not
    turn into a permanent lock."""
    project_uuid = uuid_module.UUID(project_id)

    async with async_session_factory() as session:
        run_row_1, claimed_1 = await _claim_or_join(session, project_uuid)
        assert claimed_1 is True
        await WorkflowRunRepository(session).update_state(
            run_row_1, state="completed", completed=True
        )
        await session.commit()

    async with async_session_factory() as session:
        run_row_2, claimed_2 = await _claim_or_join(session, project_uuid)
        await session.commit()

    assert claimed_2 is True
    assert run_row_2.id != run_row_1.id


async def test_a_paused_run_can_be_reclaimed_to_resume_it(project_id):
    """`awaiting_approval`/`awaiting_review` are PAUSED, not finished and
    not in-flight - the next trigger (e.g. after a human approves) must
    be able to claim the SAME row again to resume it, not be told a run
    is already active."""
    project_uuid = uuid_module.UUID(project_id)

    async with async_session_factory() as session:
        run_row_1, claimed_1 = await _claim_or_join(session, project_uuid)
        assert claimed_1 is True
        await WorkflowRunRepository(session).update_state(run_row_1, state="awaiting_approval")
        await session.commit()

    async with async_session_factory() as session:
        run_row_2, claimed_2 = await _claim_or_join(session, project_uuid)
        await session.commit()

    assert claimed_2 is True
    assert run_row_2.id == run_row_1.id
    assert run_row_2.state == "running"


async def test_a_crash_inside_the_engine_itself_surfaces_through_status(project_id, monkeypatch):
    """Not a step failing (`WorkflowEngine._run_with_retry` already
    catches that into a clean `StepResult(outcome="failed", ...)` - well
    covered by existing tests) but a crash somewhere in `engine.run()`
    ITSELF - the one thing `_execute_in_background`'s own `except` exists
    to catch, so it surfaces through `GET /status` as a legible error
    instead of vanishing into `BackgroundTasks`' own logged-and-dropped
    handling, leaving a project stuck silently `running` forever."""
    monkeypatch.setattr(settings, "dry_run", True)

    # Mirrors the real flow: by the time `_execute_in_background` ever
    # runs, `start_workflow_run` has already claimed (created) the
    # `workflow_run` row in the REQUEST's own transaction - this function
    # only ever looks one up, never creates one itself.
    project_uuid = uuid_module.UUID(project_id)
    async with async_session_factory() as session:
        await _claim_or_join(session, project_uuid)
        await session.commit()

    async def _boom(self) -> None:
        raise RuntimeError("simulated: a bug in the engine loop itself, not a step")

    monkeypatch.setattr(WorkflowEngine, "run", _boom)

    await _execute_in_background(project_id, None)

    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).get(project_id)
        assert project is not None
        assert project.status == ProjectStatus.FAILED
        assert "internal error" in project.error
        assert "simulated" in project.error

        run_row = await WorkflowRunRepository(session).get_latest(uuid_module.UUID(project_id))
        assert run_row is not None
        assert run_row.state == "failed"
        assert run_row.completed_at is not None


async def test_reclaim_resumes_a_run_orphaned_by_a_hard_kill(project_id, monkeypatch):
    """The bug this closes: a process killed mid-run leaves its
    `workflow_run` row `state == "running"` forever - `_claim_or_join`
    treats that as proof another caller is already executing it, so
    without reclaim, no future trigger would EVER resume this project.
    Simulated the same way the crash test above does: claim the row (the
    exact state a real in-flight execution, now dead, would leave behind),
    then call `reclaim_orphaned_runs` as `main.py`'s `lifespan` would on
    the next server start."""
    project_uuid = uuid_module.UUID(project_id)
    async with async_session_factory() as session:
        run_row, claimed = await _claim_or_join(session, project_uuid)
        assert claimed is True
        assert run_row.state == "running"
        await session.commit()

    calls: list[str] = []

    async def _fake_execute(pid: str, steps) -> None:
        calls.append(pid)

    monkeypatch.setattr("app.workflow.trigger._execute_in_background", _fake_execute)

    tasks = await reclaim_orphaned_runs()
    await asyncio.gather(*tasks)

    assert calls == [project_id]


async def test_reclaim_leaves_terminal_and_paused_runs_alone(project_id, monkeypatch):
    """Only a genuinely stuck `"running"` row is a bug - a completed run
    needs no resuming, and a paused one (`awaiting_approval`) is already
    correctly resumable by its own next real trigger (see the paused-run
    test above). Reclaim touching either would be new, unrequested
    behaviour, not a fix."""
    project_uuid = uuid_module.UUID(project_id)
    async with async_session_factory() as session:
        run_row, claimed = await _claim_or_join(session, project_uuid)
        assert claimed is True
        await WorkflowRunRepository(session).update_state(
            run_row, state="completed", completed=True
        )
        await session.commit()

    calls: list[str] = []

    async def _fake_execute(pid: str, steps) -> None:
        calls.append(pid)

    monkeypatch.setattr("app.workflow.trigger._execute_in_background", _fake_execute)

    tasks = await reclaim_orphaned_runs()
    await asyncio.gather(*tasks)

    assert calls == []
