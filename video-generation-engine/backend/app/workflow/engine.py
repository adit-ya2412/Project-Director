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
# `resolve_assets_generate` (rungs 5-6, paid) runs AFTER `AwaitApprovalStep`
# (A6) - it costs real money, and I6 forbids that before a human approves.
#
# ## Decision (2026-08-16): `NarrationStep` moved BEFORE `AwaitApprovalStep`
#
# The pipeline used to be `... -> AwaitApproval -> Narration ->
# ResolveAssets(generate) -> ...` (A7's original reading: "post-approval
# order is narrate -> generate -> render"). This reorders it to `...
# -> Narration -> AwaitApproval -> ResolveAssets(generate) -> ...` -
# narration now runs BEFORE the one gate, not after it. This is a
# DELIBERATE, narrow exception to I6 ("nothing expensive runs before
# approval"): narration costs real money (~10 cents via ElevenLabs), and
# it now runs pre-approval. Recorded here, not left to read as drift:
#
# - **The one-gate redesign needs REAL durations to review, not
#   planning estimates.** Under the one-gate design (superseding M6.5's
#   two-gate plan and F4/F5's frontend split - see
#   docs/13_Implementation_Guide.md), a human at the single approval gate
#   is shown every shot's image alongside how long it stays on screen, so
#   they can judge whether a busy, detailed picture works for its actual
#   duration. Before narration runs, `duration_s` is only the Shot
#   Planner's pre-audio guess - a number that routinely differs from the
#   real, ElevenLabs-measured spoken time by seconds (D1: narration is the
#   master clock). Gating approval on a guess and reconciling the real
#   number afterward would mean the human approves a video whose timing
#   they never actually saw.
# - **Narration is the cheapest, earliest thing that can fail.** ~10 cents
#   against image generation's ~4 cents PER SHOT across a whole script
#   (commonly 60+ cents), and it fails FIRST: a narration-span that covers
#   only whitespace, or a reconciled duration that blows
#   `max_video_duration_s`, is now caught before a human spends review
#   time on a gate full of pictures for a script that can never ship.
#   Under the old order those same scripts reached generation (or even
#   the human) before failing.
# - **Narration's own result never changes under anything a human does at
#   the gate.** A29 guarantees an override never changes `duration_s` - it
#   only swaps which picture a shot uses - so nothing decided at approval
#   can invalidate what narration already measured. Moving it earlier
#   loses nothing that later human input could have informed.
#
# Consequence, not swept under the rug: `NarrationStep` and
# `AwaitApprovalStep` themselves had to stop treating "the active version
# is `produced_by == NARRATION`" as proof of approval (a shortcut that
# was correct under the OLD order, where narration ran strictly after the
# gate and could only ever exist on an already-approved lineage - see
# each step's own docstring for why keeping it now would have made the
# gate a silent no-op instead). `NarrationStep` now only self-approves
# the version it appends when the version it narrated FROM was already
# approved (the N1 "redo narration with a different voice" path, which
# runs well after the project's first approval) - never on the very
# first pass, which is exactly the DRAFT state a human is now looking at
# while deciding whether to approve.
#
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
    NarrationStep(),
    AwaitApprovalStep(),
    ResolveAssetsStep(name="resolve_assets_generate", permitted_strategies=GENERATION_RUNGS),
    AwaitReviewStep(),
    RenderStep(),
    CompleteStep(),
]

# Not underscore-prefixed (unlike most module-private constants in this
# codebase): F0a's `app/workflow/trigger.py` needs the identical set to
# decide whether a `workflow_run` row represents a run still in flight -
# one source of truth for "terminal", shared rather than duplicated.
TERMINAL_RUN_STATES = frozenset({"completed", "failed"})


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
        if run_row is None or run_row.state in TERMINAL_RUN_STATES:
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
