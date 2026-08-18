"""WorkflowRun / WorkflowStepAttempt persistence.

A WorkflowStepAttempt row is written *before* the attempt starts, not
after — otherwise a hard crash leaves no trace of what was in flight
(implementation guide, Phase M4 advice).
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.workflow import WorkflowRunModel, WorkflowStepAttemptModel


class WorkflowRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(self, project_id: uuid.UUID) -> WorkflowRunModel | None:
        result = await self._session.execute(
            select(WorkflowRunModel)
            .where(WorkflowRunModel.project_id == project_id)
            .order_by(WorkflowRunModel.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_running(self) -> list[WorkflowRunModel]:
        """Every row still `state == "running"` right now. Under this
        codebase's single-instance assumption, the only legitimate caller
        is startup-time orphan reclaim (`app/workflow/trigger.py`) - a row
        in this state while nothing has run a single step yet in the
        current process can only be left over from a process that died
        mid-run."""
        result = await self._session.execute(
            select(WorkflowRunModel).where(WorkflowRunModel.state == "running")
        )
        return list(result.scalars().all())

    async def create(self, project_id: uuid.UUID) -> WorkflowRunModel:
        run = WorkflowRunModel(project_id=project_id, state="running", progress=0.0)
        self._session.add(run)
        await self._session.flush()
        return run

    async def begin_attempt(
        self, workflow_run_id: uuid.UUID, step_name: str, attempt_number: int
    ) -> WorkflowStepAttemptModel:
        """Written before the step runs — the durable trace of "this was
        in flight" if the process dies mid-attempt."""
        attempt = WorkflowStepAttemptModel(
            workflow_run_id=workflow_run_id,
            step_name=step_name,
            attempt_number=attempt_number,
            status="running",
        )
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def finish_attempt(
        self,
        attempt: WorkflowStepAttemptModel,
        *,
        status: str,
        error: str | None,
        completed_at: datetime,
    ) -> None:
        attempt.status = status
        attempt.error = error
        attempt.completed_at = completed_at

    async def update_state(
        self,
        run: WorkflowRunModel,
        *,
        state: str | None = None,
        current_step: str | None = None,
        completed: bool = False,
    ) -> None:
        if state is not None:
            run.state = state
        if current_step is not None:
            run.current_step = current_step
        if completed:
            run.completed_at = utcnow()
