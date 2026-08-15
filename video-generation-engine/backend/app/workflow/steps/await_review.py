"""Step: the A15/A26/A28 conditional review gate (M6.5).

Fires after the generation pass, and only when at least one shot ended
`failed` there - never unconditionally (A15). Unlike `AwaitApprovalStep`,
this gate has exactly ONE exit: resolve every failed shot. There is no
"proceed anyway" (A26, decided by the user, 2026-08-15: "you should not
be able to finish a video if we can't fix it") - a project cannot reach
`completed` while any shot is `failed`. This step therefore stores no
acknowledgement flag anywhere; its condition is purely observable -
"are there failed bindings at the active version, right now" - so a run
that halts here and is resumed later (after a human overrides the failed
shot via `POST /projects/{id}/shots/{shot_id}/override`, A9/A24) simply
finds the condition no longer true and walks straight through. There is
nothing to acknowledge, only something to fix.

Not a deadlock: the remedy is always available; a per-shot override
bypasses every gate (relevance, licence, this one) and always resolves.
This intentionally overrides M7's "a 59-shot video with one gap is more
useful than no video" AT THE PROJECT LEVEL ONLY - per-shot isolation
during a pass is untouched (one shot failing during resolve_assets never
aborts the others), and the renderer still degrades gracefully; what
changes is that the *project* is never marked complete while a gap
remains. A28: this is a distinct project status
(`ProjectStatus.AWAITING_REVIEW`) from the plan-approval gate, and this
step runs BEFORE `RenderStep` - a failed shot must never reach the
renderer, not even as a placeholder.
"""

import uuid as uuid_module

from app.repositories.shot_binding_repository import ShotBindingRepository
from app.workflow.context import RunContext
from app.workflow.step import StepResult


class AwaitReviewStep:
    name = "await_review"
    retryable = False
    max_attempts = 1

    async def is_satisfied(self, ctx: RunContext) -> bool:
        return not await self._has_failed_shots(ctx)

    async def run(self, ctx: RunContext) -> StepResult:
        if await self._has_failed_shots(ctx):
            return StepResult(outcome="awaiting_review")
        return StepResult(outcome="ok")

    async def _has_failed_shots(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return False
        binding_repo = ShotBindingRepository(ctx.session)
        bindings = await binding_repo.list_for_version(
            uuid_module.UUID(ctx.project_id), timeline.version
        )
        return any(b.state == "failed" for b in bindings)
