"""Emphasis pass (retention_fast_kinetic_text.md K9 / K10 / K3).

K9: one whole-film LLM call authors `stamp` / `counter` / `pivot` cues
plus the per-project palette pair. K3 (`enforce_emphasis_rules`) runs
afterwards as the density / citation / blocker backstop. Lexical
`attach_pivot_cue` (K10) is a further backstop if the model misses the
turn.

Position in DEFAULT_PIPELINE is load-bearing: AFTER
`RomanizeCaptionsStep` (shots + fragments exist) and BEFORE
`NarrationStep` — and so before `AwaitApprovalStep`, which the
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
human's behalf. Authoring BEFORE narration sidesteps both: the version
the human reviews at the gate is already the one carrying the cues.

It is NOT about muxing. `render.py::_resolve_narration_rows` gates audio
on `timeline.metadata.narration_locked`, not on `produced_by` - the
long_form_direction.md A8 (2026-09-01) fix, made precisely because
`produced_by` "describes only the version that JUST landed", so any later
version fell out of the old check and wrongly silenced the render.
`narration_locked` persists across later versions, so appending a version
after `NarrationStep` would NOT drop audio.

`is_satisfied` never keys off `produced_by` — Narration overwrites it.
It also does NOT treat "no pivot word" as done (that skipped stamps and
counters) and does NOT treat "already has a pivot cue" as done (the
K10 stub's shortcut; K9 must still author the rest on a fresh run).
`emphasis_pass_attempted` is the "already ran" bit, with
`narration_locked` as the already-narrated landmine (same as romanize:
appending a DRAFT past the gate re-opens it).

Dry-run ATTACHES the lexical pivot only — no LLM — and still stamps
`emphasis_pass_attempted` so the step cannot loop. That stamp will
lock a later real run out of the LLM pass on the same project, the
romanize RV-R3 shape. Documented and accepted here: dry-run timelines
are fixtures, not projects that flip `DRY_RUN` off. A real run on a
fresh project takes the LLM path.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.errors import TransientError
from app.core.logging import get_logger
from app.planners.emphasis.planner import EmphasisPlanner
from app.providers.openai_provider import OpenAIPlanningProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import ProducedBy, Timeline
from app.script.styles import (
    resolve_emphasis_max_cues_per_minute,
    resolve_emphasis_min_shot_gap,
)
from app.timeline.emphasis_rules import enforce_emphasis_rules
from app.timeline.pivot import attach_pivot_cue
from app.workflow.context import RunContext
from app.workflow.step import StepResult

logger = get_logger(__name__)

_STYLE = "retention_fast"
_OWNS = frozenset(
    {"scenes", "metadata.emphasis_pass_attempted", "metadata.emphasis_palette"}
)


def _is_retention_fast(timeline: Timeline) -> bool:
    return timeline.metadata.render_style == _STYLE


def _enforce(timeline: Timeline) -> Timeline:
    style = timeline.metadata.render_style
    return enforce_emphasis_rules(
        timeline,
        min_shot_gap=resolve_emphasis_min_shot_gap(style),
        max_cues_per_minute=resolve_emphasis_max_cues_per_minute(style),
    )


class EmphasisPassStep:
    name = "emphasis_pass"
    retryable = True
    max_attempts = 3

    def __init__(self, planner: EmphasisPlanner | None = None) -> None:
        self._planner = planner

    async def is_satisfied(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return True
        if not _is_retention_fast(timeline):
            return True
        if timeline.metadata.emphasis_pass_attempted:
            return True
        # Predating this step, already through NarrationStep: do not
        # append on a DEFAULT_PIPELINE resume. Appending would land a
        # fresh DRAFT past the approval gate, which re-opens it (see the
        # module docstring) - audio is not at risk, `narration_locked`
        # survives later versions. Fresh pipelines author before
        # narration; already-narrated projects get no K9 pass at all.
        return bool(timeline.metadata.narration_locked)

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(
                outcome="failed", error="no active timeline to attach emphasis cues to"
            )
        if not _is_retention_fast(timeline):
            return StepResult(outcome="ok")
        if timeline.metadata.narration_locked:
            logger.info(
                "emphasis_pass.skipped_narration_locked",
                extra={"project_id": ctx.project_id},
            )
            return StepResult(outcome="ok")

        if settings.dry_run:
            planned = attach_pivot_cue(timeline)
        else:
            planner = self._planner or EmphasisPlanner(
                OpenAIPlanningProvider(),
                LlmCallRepository(ctx.session),
            )
            try:
                planned = await planner.plan(project_id=ctx.project_id, timeline=timeline)
            except TransientError as exc:
                return StepResult(outcome="retry", error=str(exc))
            except Exception as exc:  # noqa: BLE001 - provider call boundary
                return StepResult(outcome="failed", error=str(exc))

        def _record(base: Timeline) -> Timeline:
            # `planned` is already a copy (planner / attach_pivot_cue).
            # Re-apply the authored scenes/palette onto `base` so the
            # additive-merge owns set stays honest, then K3, then stamp.
            updated = base.model_copy(deep=True)
            updated.scenes = planned.scenes
            updated.metadata.emphasis_palette = planned.metadata.emphasis_palette
            updated = _enforce(updated)
            updated.metadata.emphasis_pass_attempted = True
            return updated

        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.EMPHASIS_PASS,
            transform=_record,
            owns=_OWNS,
        )
        return StepResult(outcome="ok")
