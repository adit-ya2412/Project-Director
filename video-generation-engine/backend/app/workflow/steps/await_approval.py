"""Step 2: the human approval gate (ADR-008, Invariant I6 - nothing
expensive runs before approval).

This is a state, not a blocked coroutine: `run()` never waits. If the
active timeline isn't approved yet, it returns immediately with
`outcome="awaiting_approval"` and the engine ends the run cleanly. A
later `POST /projects/{id}/timeline/approve` approves the timeline and
starts a *new* engine run that resumes at the next step.
"""

from app.schemas.timeline import TimelineStatus
from app.workflow.context import RunContext
from app.workflow.step import StepResult


class AwaitApprovalStep:
    name = "await_approval"
    retryable = False
    max_attempts = 1

    async def is_satisfied(self, ctx: RunContext) -> bool:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        return active is not None and active.status == TimelineStatus.APPROVED

    async def run(self, ctx: RunContext) -> StepResult:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        if active is not None and active.status == TimelineStatus.APPROVED:
            return StepResult(outcome="ok")
        return StepResult(outcome="awaiting_approval")
