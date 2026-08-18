"""F0a (2026-08-16): every "run/resume the workflow engine" HTTP call
used to `await engine.run()` directly inside the request handler - and a
full pipeline run legitimately takes 5-15 minutes of planning, or, as
measured in live testing, more than 600 seconds for the paid
asset-resolution pass alone, backgrounded from the tooling because no
browser waits that long. This phase's own Advice already said so ("long
operations return 202 with a run ID... never block an HTTP request on
planning, generation, or rendering") - this module is the seam that
makes it true: every trigger in `app/api/projects.py` now calls
`start_workflow_run` instead of `engine.run()` directly, and returns
immediately.

## Why FastAPI `BackgroundTasks`, not a queue

Redis sits in docker-compose.yml, used by nothing in `app/` - a real
temptation to reach for Celery/arq here, and explicitly asked not to.
Rejected on its own merits, not just the instruction: this process
already holds a live asyncio event loop and a DB connection pool; a
`BackgroundTasks` callback scheduled on it runs on that SAME loop, needs
no broker, no second worker process, and no serialisation boundary for
`RunContext` (which holds a live `AsyncSession` - not something you can
hand to a different process without redesigning the whole per-step
contract). A queue earns its keep when work must survive THIS PROCESS
dying, or must be spread across machines; this codebase is single-
instance, and `WorkflowRunModel`/`WorkflowStepAttemptModel` already give
crash recovery for free (a step-attempt row is written before the step
starts - M4 Advice - so a killed process resumes correctly on the next
trigger, whether that trigger is a human retry or, now, this same
background mechanism). Reaching for Celery here would be exactly the
"speculative framework" this codebase's own conventions warn against.

## Concurrency: one run per project, enforced through `workflow_run`

Two triggers landing close together (a UI double-click, a client retry)
must not start the pipeline twice for the same project - `WorkflowEngine
.run()` itself has no guard against being entered twice concurrently: it
reads the latest `workflow_run` row, flips it to "running", and starts
executing steps, and two concurrent callers doing that at the same
moment would both start running (and both start PAYING for)
`ResolveAssetsStep`/generation. `_claim_or_join` below makes that
transition atomic across processes with a Postgres advisory lock scoped
to the request's own transaction (`pg_advisory_xact_lock` - released
automatically at commit/rollback, nothing to remember to unlock) around
the read-or-create of the latest `workflow_run` row: a second, truly
concurrent caller blocks on that same lock until the first commits, then
sees the row already `state="running"` and joins rather than starting a
second execution. A plain `SELECT ... FOR UPDATE` on the row would not
have been enough for a project's very FIRST trigger, where no row exists
yet to lock against - exactly the case an advisory lock (keyed on the
project id, not a row) still closes.

The claim itself - "read the latest run, create one or flip it to
running" - is deliberately the SAME logic `WorkflowEngine.run()` already
does at its own top; nothing here duplicates that decision, it is just
performed once, lock-guarded, and committed BEFORE the background task
is scheduled, rather than racily inside it. The background task's own
call into `engine.run()` re-derives the same row and finds it already
"running" - a harmless no-op re-flip, not a second claim.

## Orphan reclaim (2026-08-18, motion_new_styles_and_long_form_videos.md §11)

`_claim_or_join`'s `state == "running"` check has a blind spot it cannot
close from inside a single request: it assumes "running" always means
some OTHER caller is currently executing the pipeline, which is true
right up until that caller's process is hard-killed (Ctrl-C, a reboot,
an OOM kill). After that, the row is stuck `"running"` forever - every
future trigger sees it as busy and joins rather than resumes, and only
editing Postgres by hand recovers the project. `WorkflowEngine.run()`
itself has no trouble resuming a `"running"` row (it re-derives progress
from `is_satisfied()`, not from anything stored); the gap is purely that
nothing ever calls it again. `reclaim_orphaned_runs`, called once from
`main.py`'s `lifespan` before the app accepts requests, closes this: under
this codebase's single-instance assumption, any row still `"running"` at
process startup cannot belong to a live execution - the process that
would be running it is the one just starting - so it is provably
orphaned, no heartbeat column or timeout threshold needed.
"""

import asyncio
import uuid as uuid_module

from fastapi import BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.workflow import WorkflowRunModel
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.workflow_repository import WorkflowRunRepository
from app.schemas.project import ProjectStatus
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.engine import TERMINAL_RUN_STATES, WorkflowEngine
from app.workflow.step import WorkflowStep

logger = get_logger(__name__)


class WorkflowTriggerResult(BaseModel):
    """What every backgrounded trigger returns instead of the full
    `Project` it used to return synchronously - a run identifier to poll
    against (`GET /status`, `GET /progress`), never the outcome itself,
    since the outcome isn't known yet."""

    project_id: str
    workflow_run_id: str
    state: str
    # True when this call found a run already in flight and did NOT
    # schedule a second execution - the concurrency guarantee made
    # observable to the caller, rather than a silent, invisible no-op.
    joined_existing_run: bool


def _advisory_lock_key(project_id: uuid_module.UUID) -> int:
    """Folds a UUID down to a signed 64-bit int for `pg_advisory_xact_lock`'s
    single-bigint overload. A collision only ever serialises two
    DIFFERENT projects' claims behind one lock for the length of one
    transaction - never incorrect behaviour, at worst a slightly slower
    claim under a one-in-billions coincidence - so a plain truncation is
    enough; there is no need for a cryptographic hash here."""
    return project_id.int & 0x7FFFFFFFFFFFFFFF


async def _claim_or_join(
    session: AsyncSession, project_id: uuid_module.UUID
) -> tuple[WorkflowRunModel, bool]:
    """Returns `(run_row, claimed)`. `claimed=True` means THIS caller is
    now responsible for executing the pipeline - the row is freshly
    created or transitioned to "running", and the caller commits and
    schedules the background task. `claimed=False` means a run is
    already `state == "running"` right now; the caller reports on it and
    schedules nothing."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _advisory_lock_key(project_id)}
    )

    workflow_repo = WorkflowRunRepository(session)
    run_row = await workflow_repo.get_latest(project_id)

    if run_row is not None and run_row.state == "running":
        return run_row, False

    if run_row is None or run_row.state in TERMINAL_RUN_STATES:
        run_row = WorkflowRunModel(project_id=project_id, state="running", progress=0.0)
        session.add(run_row)
    else:
        # Paused at a human gate (awaiting_approval/awaiting_review) -
        # resuming it is exactly what this trigger is for.
        run_row.state = "running"
    await session.flush()
    return run_row, True


async def _execute_in_background(project_id: str, steps: list[WorkflowStep] | None) -> None:
    """The actual pipeline run, on its OWN session - `BackgroundTasks`
    callbacks run after the response has been handed back (Starlette's
    own contract), by which point the request's session is closed, so
    reusing it here would mean running queries on a dead connection.

    A step's own failure is already caught and recorded by
    `WorkflowEngine._run_with_retry` (never raises - it converts any
    exception into `StepResult(outcome="failed", ...)`), so the `except`
    below is deliberately for what is LEFT once that contract holds: a
    bug in the engine loop itself, or a DB/connectivity fault at a point
    the per-step try/except doesn't cover. Without this, such a crash
    would vanish into `BackgroundTasks`' own "logged and dropped"
    handling and a human would be left staring at a project stuck
    "running" forever with no explanation - the exact failure mode this
    function exists to close off."""
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        timeline_service = TimelineService(session)
        ctx = RunContext(
            project_id=project_id, session=session, repo=repo, timeline_service=timeline_service
        )
        engine = WorkflowEngine(ctx, steps=steps)
        try:
            await engine.run()
        except Exception as exc:  # noqa: BLE001 - the last backstop; see docstring above
            logger.exception("workflow.background_task_crashed", extra={"project_id": project_id})
            await session.rollback()
            project = await repo.get(project_id)
            if project is not None:
                project.status = ProjectStatus.FAILED
                project.error = f"internal error while running the workflow: {exc}"
                await repo.update(project)
            workflow_repo = WorkflowRunRepository(session)
            run_row = await workflow_repo.get_latest(uuid_module.UUID(project_id))
            if run_row is not None:
                await workflow_repo.update_state(run_row, state="failed", completed=True)
            await session.commit()


# Strong references to reclaim's own background tasks - `asyncio.create_task`
# does not keep a task alive on its own (nothing else holds it once
# `reclaim_orphaned_runs` returns), so a task could be garbage-collected
# mid-run without this, exactly the kind of silent loss this module exists
# to prevent.
_reclaim_tasks: set[asyncio.Task] = set()


async def reclaim_orphaned_runs() -> list[asyncio.Task]:
    """Finds every `workflow_run` row left `state == "running"` by a
    process that died before it could finish, and resumes each one the
    same way a normal trigger would - scheduling `_execute_in_background`
    directly, since we already know (see this module's own docstring)
    that nothing else is currently executing them. Returns the scheduled
    tasks so a caller (namely tests) can await them; production code
    (`main.py`'s `lifespan`) does not need to."""
    async with async_session_factory() as session:
        orphaned = await WorkflowRunRepository(session).list_running()
        project_ids = [str(run.project_id) for run in orphaned]

    tasks: list[asyncio.Task] = []
    for project_id in project_ids:
        logger.warning("workflow.reclaiming_orphaned_run", extra={"project_id": project_id})
        task = asyncio.create_task(_execute_in_background(project_id, None))
        _reclaim_tasks.add(task)
        task.add_done_callback(_reclaim_tasks.discard)
        tasks.append(task)
    return tasks


async def start_workflow_run(
    project_id: str,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    steps: list[WorkflowStep] | None = None,
) -> WorkflowTriggerResult:
    """Claims (or joins) this project's run, using the REQUEST's own
    session for the fast, atomic claim, then schedules the slow part -
    `engine.run()` itself - on a fresh session via `BackgroundTasks`.
    Callers commit nothing themselves before this: the claim's own
    `session.commit()` below is what releases the advisory lock and
    makes the "running" state visible to the next concurrent request."""
    project_uuid = uuid_module.UUID(project_id)
    run_row, claimed = await _claim_or_join(session, project_uuid)
    await session.commit()

    if claimed:
        background_tasks.add_task(_execute_in_background, project_id, steps)

    return WorkflowTriggerResult(
        project_id=project_id,
        workflow_run_id=str(run_row.id),
        state=run_row.state,
        joined_existing_run=not claimed,
    )
