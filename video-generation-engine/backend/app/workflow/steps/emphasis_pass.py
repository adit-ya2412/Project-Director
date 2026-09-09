"""K10 stub of the emphasis pass (retention_fast_kinetic_text.md).

This slice only runs lexical pivot detection. The LLM pass (K9) is a
later task. Position in DEFAULT_PIPELINE is load-bearing: AFTER
`RomanizeCaptionsStep` (shots + fragments exist) and BEFORE
`NarrationStep` - and so before `AwaitApprovalStep`, which the
one-gate redesign (2026-08-16) moved to sit immediately AFTER
narration.

The reason is the APPROVAL GATE. This step appends a version and never
self-approves it, so what it lands is a DRAFT - and `AwaitApprovalStep`
is now checked "the same, simple way for every producer, always"
(`status == TimelineStatus.APPROVED`, nothing else - see that step's own
docstring for why its old `produced_by == NARRATION` bypass had to go).
Appending a DRAFT after the gate has been passed therefore RE-OPENS it:
`is_satisfied` reads False again, the engine ends the run with
`outcome="awaiting_approval"`, and the pipeline stalls waiting on a
second human click for a creative decision no human made. This step has
no equivalent of `NarrationStep`'s narrow "narrated FROM an
already-approved version" self-approval (see that module's "Approval, and
why this step does NOT always self-approve"), and inventing one here
would be the mirror failure - a step that silently re-approves on the
human's behalf. Attaching the pivot BEFORE narration sidesteps both: the
version the human reviews at the gate is already the one carrying the
cue.

It is NOT about muxing. `render.py::_resolve_narration_rows` gates audio
on `timeline.metadata.narration_locked`, not on `produced_by` - the
long_form_direction.md A8 (2026-09-01) fix, made precisely because
`produced_by` "describes only the version that JUST landed", so any later
version fell out of the old check and wrongly silenced the render.
`narration_locked` persists across later versions, so appending a version
after `NarrationStep` would NOT drop audio. An earlier version of this
docstring said it would; that described pre-A8 behaviour and is false.

`is_satisfied` never keys off `produced_by` — Narration overwrites it.
A pivot cue already on a shot, nothing attachable, a prior attempt
stamp, a non-`retention_fast` style, or an already-narrated project
(`narration_locked`, the romanize landmine) all report satisfied.

Dry-run ATTACHES. Unlike romanize there is no LLM and no stamp that
would lock a later real run out of work it still needed; fake timelines
should still carry the pivot so the rest of the pipeline can be tested.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.schemas.timeline import EmphasisDevice, ProducedBy, Timeline
from app.timeline.pivot import attach_pivot_cue, detect_pivot
from app.workflow.context import RunContext
from app.workflow.step import StepResult

logger = get_logger(__name__)

_STYLE = "retention_fast"
_OWNS = frozenset({"scenes", "metadata.emphasis_pass_attempted"})


def _is_retention_fast(timeline: Timeline) -> bool:
    return timeline.metadata.render_style == _STYLE


def _has_pivot_cue(timeline: Timeline) -> bool:
    return any(
        shot.emphasis_cue is not None and shot.emphasis_cue.device is EmphasisDevice.PIVOT
        for shot in timeline.all_shots()
    )


class EmphasisPassStep:
    name = "emphasis_pass"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return True
        if not _is_retention_fast(timeline):
            return True
        if _has_pivot_cue(timeline):
            return True
        if timeline.metadata.emphasis_pass_attempted:
            return True
        if detect_pivot(timeline) is None:
            return True
        # Predating this step, already through NarrationStep: do not
        # append on a DEFAULT_PIPELINE resume. Appending would land a
        # fresh DRAFT past the approval gate, which re-opens it (see the
        # module docstring) - audio is not at risk, `narration_locked`
        # survives later versions. Fresh pipelines attach before
        # narration; already-narrated projects get no pivot at all.
        return bool(timeline.metadata.narration_locked)

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to attach a pivot cue to")
        if not _is_retention_fast(timeline):
            return StepResult(outcome="ok")
        if timeline.metadata.narration_locked:
            logger.info(
                "emphasis_pass.skipped_narration_locked",
                extra={"project_id": ctx.project_id},
            )
            return StepResult(outcome="ok")

        def _record(base: Timeline) -> Timeline:
            updated = attach_pivot_cue(base)
            updated.metadata.emphasis_pass_attempted = True
            return updated

        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.EMPHASIS_PASS,
            transform=_record,
            owns=_OWNS,
        )
        return StepResult(outcome="ok")
