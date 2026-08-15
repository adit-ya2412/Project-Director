"""Runs (or resumes) the pipeline for one project.

Every call to `run()` is a fresh invocation: it asks each step
`is_satisfied()` before running it, so a process that crashed mid-run -
or a request that stopped at AWAITING_APPROVAL - picks back up exactly
where observable state says it left off. There is no stored "current
step index" anywhere to trust or distrust (implementation guide, Phase
M4 advice).
"""

import uuid as uuid_module

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.models.workflow import WorkflowRunModel
from app.repositories.domain_event_repository import DomainEventRepository
from app.repositories.workflow_repository import WorkflowRunRepository
from app.schemas.project import Project, ProjectStatus
from app.workflow.context import RunContext
from app.workflow.retry import backoff_sleep
from app.workflow.step import StepResult, WorkflowStep
from app.workflow.steps.await_approval import AwaitApprovalStep
from app.workflow.steps.await_review import AwaitReviewStep
from app.workflow.steps.complete import CompleteStep
from app.workflow.steps.generate_timeline import GenerateTimelineStep
from app.workflow.steps.narration import NarrationStep
from app.workflow.steps.render import RenderStep
from app.workflow.steps.resolve_assets import GENERATION_RUNGS, SEARCH_RUNGS, ResolveAssetsStep
from app.workflow.steps.select_music import SelectMusicStep

logger = get_logger(__name__)

# M6.5, A5/A6/A7/A21: `ResolveAssetsStep` runs TWICE, once for each half
# of the asset ladder (canon 3.1) - never as a single pass, and never as
# two separate classes (see that module's own docstring for why one
# parameterised class, not two).
#
# `resolve_assets_search` (rungs 1-4, free) runs BEFORE the approval gate
# - I6 only forbids EXPENSIVE work pre-approval, and search costs nothing,
# so this is what makes the risky acquisition step supervised at the
# moment fixing it is still free (A5). A shot it cannot resolve is left
# `awaiting_generation`, not failed - the paid pass still owns it.
#
# `resolve_assets_generate` (rungs 5-6, paid) runs AFTER NarrationStep,
# not directly after approval (A6/A7): narration is cheap (~9c) and is
# what validates the real, spoken duration - a script that blows the 90s
# cap must fail there, before dollars of generation are spent on a video
# that can never ship. NarrationStep appends a NEW Timeline version
# (reconciled durations, M8); ShotBinding rows are keyed by (project_id,
# timeline_version, shot_id), so that version bump would orphan every
# binding `resolve_assets_search` and a human just approved, forcing a
# full, silent re-resolve (and re-pay for generation) of every shot - A11
# is the hard prerequisite this depends on: `TimelineService` carries a
# shot's binding forward across that exact version bump whenever the
# shot's acquisition-relevant fields (`prompt`, `asset_plan`) are
# unchanged (A20), which is true for every shot narration ever touches
# (it only changes durations). See `app/timeline/service.py` for where
# that carry-forward actually happens and why.
# A15/A26/A28 (M6.5): `AwaitReviewStep` runs after the generation pass and
# BEFORE `RenderStep` - a shot that ended `failed` there must never reach
# the renderer, not even as a placeholder. This is a different gate from
# `AwaitApprovalStep` above (a different project status, A28), with a
# different, single exit: a human overrides the failed shot
# (`POST /projects/{id}/shots/{shot_id}/override`, A9/A24), never
# "proceed anyway" (A26) - see that step's own docstring.
#
# `SelectMusicStep` (M8 step 4, D6/21.2) runs right after the free search
# pass and before the approval gate, for the identical reason
# `resolve_assets_search` does: Pixabay search is free, so I6 permits it,
# and a human approving a video should hear what it will sound like
# before approving - see that step's own docstring for the rest.
DEFAULT_PIPELINE: list[WorkflowStep] = [
    GenerateTimelineStep(),
    ResolveAssetsStep(name="resolve_assets_search", permitted_strategies=SEARCH_RUNGS),
    SelectMusicStep(),
    AwaitApprovalStep(),
    NarrationStep(),
    ResolveAssetsStep(name="resolve_assets_generate", permitted_strategies=GENERATION_RUNGS),
    AwaitReviewStep(),
    RenderStep(),
    CompleteStep(),
]

_TERMINAL_RUN_STATES = frozenset({"completed", "failed"})


class WorkflowEngine:
    def __init__(
        self,
        ctx: RunContext,
        *,
        steps: list[WorkflowStep] | None = None,
        base_delay_s: float = 1.0,
    ) -> None:
        self._ctx = ctx
        self._steps = steps if steps is not None else DEFAULT_PIPELINE
        self._base_delay_s = base_delay_s
        self._workflow_repo = WorkflowRunRepository(ctx.session)
        self._events = DomainEventRepository(ctx.session)

    async def run(self) -> Project:
        project_uuid = uuid_module.UUID(self._ctx.project_id)

        run_row = await self._workflow_repo.get_latest(project_uuid)
        if run_row is None or run_row.state in _TERMINAL_RUN_STATES:
            run_row = await self._workflow_repo.create(project_uuid)
            await self._events.emit(
                project_uuid, "WorkflowStarted", {"workflow_run_id": str(run_row.id)}
            )
        else:
            run_row.state = "running"
        await self._ctx.session.commit()

        for step in self._steps:
            if await step.is_satisfied(self._ctx):
                continue

            await self._workflow_repo.update_state(run_row, current_step=step.name)
            await self._ctx.session.commit()

            result = await self._run_with_retry(run_row, step)

            if result.outcome == "awaiting_approval":
                await self._workflow_repo.update_state(run_row, state="awaiting_approval")
                project = await self._reload_project()
                # Clear any stale FAILED status/error from an earlier run of
                # this same project: without this, a project that failed
                # once and then successfully retried past the failure point
                # would keep reporting status="failed" with the old error
                # forever, even though workflow_state (the source of truth
                # in /progress) correctly shows awaiting_approval - anyone
                # polling /status alone would be misled into thinking the
                # retry never worked.
                project.status = ProjectStatus.AWAITING_APPROVAL
                project.error = None
                await self._ctx.repo.update(project)
                await self._events.emit(
                    project_uuid, "TimelineAwaitingApproval", {"step": step.name}
                )
                await self._ctx.session.commit()
                logger.info(
                    "workflow.awaiting_approval",
                    extra={"project_id": self._ctx.project_id, "step": step.name},
                )
                return await self._reload_project()

            if result.outcome == "awaiting_review":
                # A26/A28: no acknowledgement to store here - the ONLY
                # exit is a human override that resolves the failed
                # shot(s), so a later run re-checks the same observable
                # condition (`AwaitReviewStep.is_satisfied`) rather than
                # trusting a flag that could go stale.
                await self._workflow_repo.update_state(run_row, state="awaiting_review")
                project = await self._reload_project()
                project.status = ProjectStatus.AWAITING_REVIEW
                project.error = None
                await self._ctx.repo.update(project)
                await self._events.emit(project_uuid, "ShotsAwaitingReview", {"step": step.name})
                await self._ctx.session.commit()
                logger.info(
                    "workflow.awaiting_review",
                    extra={"project_id": self._ctx.project_id, "step": step.name},
                )
                return await self._reload_project()

            if result.outcome == "failed":
                await self._workflow_repo.update_state(run_row, state="failed", completed=True)
                project = await self._reload_project()
                project.status = ProjectStatus.FAILED
                project.error = result.error
                await self._ctx.repo.update(project)
                await self._events.emit(
                    project_uuid, "WorkflowFailed", {"step": step.name, "error": result.error}
                )
                await self._ctx.session.commit()
                logger.error(
                    "workflow.failed",
                    extra={
                        "project_id": self._ctx.project_id,
                        "step": step.name,
                        "error": result.error,
                    },
                )
                return await self._reload_project()

            # outcome == "ok"
            await self._events.emit(project_uuid, "WorkflowStepCompleted", {"step": step.name})
            await self._ctx.session.commit()

        await self._workflow_repo.update_state(
            run_row, state="completed", current_step=None, completed=True
        )
        await self._events.emit(project_uuid, "WorkflowCompleted", {})
        await self._ctx.session.commit()
        logger.info("workflow.completed", extra={"project_id": self._ctx.project_id})
        return await self._reload_project()

    async def _run_with_retry(self, run_row: WorkflowRunModel, step: WorkflowStep) -> StepResult:
        attempt_number = 0
        while True:
            attempt_number += 1
            attempt_row = await self._workflow_repo.begin_attempt(
                run_row.id, step.name, attempt_number
            )
            await self._ctx.session.commit()

            try:
                result = await step.run(self._ctx)
            except Exception as exc:  # noqa: BLE001 - a step must never crash the engine
                result = StepResult(outcome="failed", error=str(exc))

            await self._workflow_repo.finish_attempt(
                attempt_row, status=result.outcome, error=result.error, completed_at=utcnow()
            )
            await self._ctx.session.commit()

            if result.outcome != "retry":
                return result
            if not step.retryable or attempt_number >= step.max_attempts:
                return StepResult(
                    outcome="failed", error=result.error or f"{step.name} exhausted retries"
                )

            logger.info(
                "workflow.step_retry",
                extra={
                    "project_id": self._ctx.project_id,
                    "step": step.name,
                    "attempt": attempt_number,
                },
            )
            await backoff_sleep(attempt_number, base_delay_s=self._base_delay_s)

    async def _reload_project(self) -> Project:
        project = await self._ctx.repo.get(self._ctx.project_id)
        if project is None:
            raise RuntimeError(f"project {self._ctx.project_id} vanished mid-run")
        return project
