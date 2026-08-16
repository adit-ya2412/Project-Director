"""Step 2: the human approval gate (ADR-008, Invariant I6 - nothing
expensive runs before approval).

This is a state, not a blocked coroutine: `run()` never waits. If the
active timeline isn't approved yet, it returns immediately with
`outcome="awaiting_approval"` and the engine ends the run cleanly. A
later `POST /projects/{id}/timeline/approve` approves the timeline and
starts a *new* engine run that resumes at the next step.

## `produced_by == NARRATION` is NOT treated as approval-equivalent

This gate used to also accept `produced_by == ProducedBy.NARRATION` as
proof of approval, under the OLD pipeline order (`AwaitApproval` then
`NarrationStep`): narration ran strictly AFTER this gate and self-
approved its own reconciled version in a second commit, so seeing
NARRATION on the active version was itself transitive proof a human had
already approved a prior version, and the bypass just closed the crash
window between `append_version` and `approve`.

**2026-08-16: `NarrationStep` moved to run BEFORE this gate instead** (see
`app/workflow/engine.DEFAULT_PIPELINE`'s own module docstring for why -
the one-gate redesign needs the human to review REAL, narration-measured
durations, not a planner's pre-audio guess). That inverts the old
reasoning entirely: under the new order, `produced_by == NARRATION` on
the active version is routinely the ORDINARY, unapproved DRAFT state a
human is looking at right now while deciding whether to approve - it is
no longer evidence approval already happened. Keeping the old bypass
here would have made this gate a silent no-op: the instant `NarrationStep`
finished, `is_satisfied` would already read True and the engine would
sail through with nobody having clicked anything. So this is now checked
the same, simple way for every producer, always: `status ==
TimelineStatus.APPROVED`, nothing else. (`NarrationStep` still has its
own narrower self-approval for the N1 "redo with a different voice" case,
which runs well after a project's first approval - see that step's own
docstring.)
"""

from app.schemas.timeline import TimelineStatus
from app.workflow.context import RunContext
from app.workflow.step import StepResult


def _is_approved(active) -> bool:
    return active is not None and active.status == TimelineStatus.APPROVED


class AwaitApprovalStep:
    name = "await_approval"
    retryable = False
    max_attempts = 1

    async def is_satisfied(self, ctx: RunContext) -> bool:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        return _is_approved(active)

    async def run(self, ctx: RunContext) -> StepResult:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        if _is_approved(active):
            return StepResult(outcome="ok")
        return StepResult(outcome="awaiting_approval")
