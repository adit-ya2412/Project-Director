"""Step 2: the human approval gate (ADR-008, Invariant I6 - nothing
expensive runs before approval).

This is a state, not a blocked coroutine: `run()` never waits. If the
active timeline isn't approved yet, it returns immediately with
`outcome="awaiting_approval"` and the engine ends the run cleanly. A
later `POST /projects/{id}/timeline/approve` approves the timeline and
starts a *new* engine run that resumes at the next step.

`produced_by == NARRATION` also satisfies this gate (M8), not just
`status == APPROVED`: `NarrationStep` (which runs after this one) appends
its reconciled version and approves it in two separate commits, and a
crash between them would otherwise resume here demanding a second human
approval for a version a human already approved - narration reconciles
durations, it doesn't reopen the creative plan for review (M8 open
decision: "approval is of the creative plan, not of millisecond
timings"). Seeing `produced_by == NARRATION` is itself proof approval
already happened, transitively: that version can only exist because
`NarrationStep` ran, and `NarrationStep` only ever runs after THIS step
already let a prior, human-approved version through.
"""

from app.schemas.timeline import ProducedBy, TimelineStatus
from app.workflow.context import RunContext
from app.workflow.step import StepResult


def _is_approved_or_narration_produced(active) -> bool:
    return active is not None and (
        active.status == TimelineStatus.APPROVED or active.produced_by == ProducedBy.NARRATION
    )


class AwaitApprovalStep:
    name = "await_approval"
    retryable = False
    max_attempts = 1

    async def is_satisfied(self, ctx: RunContext) -> bool:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        return _is_approved_or_narration_produced(active)

    async def run(self, ctx: RunContext) -> StepResult:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        if _is_approved_or_narration_produced(active):
            return StepResult(outcome="ok")
        return StepResult(outcome="awaiting_approval")
