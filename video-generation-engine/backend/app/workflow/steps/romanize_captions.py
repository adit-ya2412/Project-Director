"""Caption romanization step (caption_romanization.md §3.2 / §3.5 / §10).

Fills `Scene.caption_text` — a Latin-script display string for captions
— and `Scene.caption_word_groups` (§10.3: how many consecutive narration
words each display token replaces) from `narration_text`. TTS never sees
the result. Failure is never fatal: a scene the validator cannot accept
stays mixed-script, the run continues.

## Position in DEFAULT_PIPELINE is load-bearing

Sits between `SelectSfxStep` and `NarrationStep`. Two constraints, not
one:

1. It must run AFTER any script rewrite (those change `narration_text`)
   and AFTER the Scene Planner has written that field. SelectSfx is the
   last pre-narration step that already exists, so this is the earliest
   inspectable slot with a final script.
2. It must run BEFORE `NarrationStep`, because this step appends a
   timeline version (`produced_by=CAPTION_ROMANIZATION`) and
   `render.py::_resolve_narration_rows` returns None — silent video —
   unless the *active* version is `produced_by=NARRATION`. Narration
   overwrites that stamp on the way to the approval gate. See the
   comment above `DEFAULT_PIPELINE`.

Under `settings.dry_run` this step does nothing at all - `is_satisfied`
reports True so the engine skips it, and `run` refuses to append even
if called directly. The check reads `settings` LIVE rather than storing
a `caption_romanization_attempted` stamp, so flipping DRY_RUN off makes
the same project romanize on its next real run. Stamping instead would
lock it out permanently, and leaving `is_satisfied` False would block
`render_precondition_gap` (and therefore `render_only`) forever. Both
were tried; see RV-R3 in the plan.

Already-narrated projects (`metadata.narration_locked`) are skipped
here on purpose: appending a version would reset `status` to DRAFT
(re-opening the approval gate) and, unless we re-stamped NARRATION,
drop audio. Those projects go through `backfill_caption_romanization`
instead, which re-stamps NARRATION and re-approves.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.planners.caption_romanizer.planner import CaptionRomanizer, needs_romanization
from app.providers.openai_provider import OpenAIPlanningProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import ProducedBy, Timeline, TimelineStatus
from app.workflow.context import RunContext
from app.workflow.step import StepResult

logger = get_logger(__name__)

_OWNS = frozenset({"scenes", "metadata.caption_romanization_attempted"})


def _nothing_to_romanize(timeline: Timeline) -> bool:
    return not any(needs_romanization(scene) for scene in timeline.scenes)


class RomanizeCaptionsStep:
    name = "romanize_captions"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        if settings.dry_run:
            # DRY_RUN: the pass is not applicable, so report satisfied
            # rather than "not done yet". This clause is what keeps the
            # step out of `render_precondition_gap`'s way - that helper
            # walks DEFAULT_PIPELINE and returns the FIRST step reporting
            # unsatisfied, which `render_only` turns into a 409. A step
            # that can never report satisfied under DRY_RUN would block
            # render-only forever for every dry-run Devanagari project.
            #
            # Deliberately read from `settings` live rather than from a
            # stored flag: flip DRY_RUN off and this re-evaluates to
            # False, so the project romanizes on its next real run. That
            # is exactly what stamping `caption_romanization_attempted`
            # in dry-run got wrong (RV-R3) - a stored stamp locked the
            # project out permanently.
            return True
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return True
        if timeline.metadata.caption_romanization_attempted:
            return True
        if _nothing_to_romanize(timeline):
            return True
        # Predating this step, already through NarrationStep: do not
        # mutate on a DEFAULT_PIPELINE resume. Backfill is explicit.
        return bool(timeline.metadata.narration_locked)

    async def run(self, ctx: RunContext) -> StepResult:
        if settings.dry_run:
            # Belt-and-braces: `is_satisfied` already returns True under
            # DRY_RUN, so the engine never reaches this. Kept so the step
            # is still correct if invoked directly (a test, a script, a
            # future pipeline that skips the satisfied check).
            #
            # DRY_RUN must leave no trace. Appending here would burn a
            # timeline version on a no-op AND stamp
            # `caption_romanization_attempted` - and that stamp, unlike
            # the `settings.dry_run` check above, would survive into a
            # later real run and permanently skip romanization (RV-R3).
            # (The DRY_RUN branch inside `_apply_romanization` stays:
            # it guards `backfill_caption_romanization`, which is an
            # explicit, manually-invoked path.)
            logger.warning(
                "romanize_captions.skipped_dry_run",
                extra={"project_id": ctx.project_id},
            )
            return StepResult(outcome="ok")
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to romanize captions for")
        await _apply_romanization(
            ctx,
            timeline,
            produced_by=ProducedBy.CAPTION_ROMANIZATION,
            reapprove=False,
        )
        return StepResult(outcome="ok")


async def backfill_caption_romanization(ctx: RunContext) -> StepResult:
    """§3.6: run the pass over an already-narrated timeline without
    re-planning, re-narrating, or re-acquiring assets.

    Re-stamps `produced_by=NARRATION` so render still muxes audio, and
    re-approves if the version we romanized FROM was already approved
    (append_version always writes DRAFT). The caller still has to force
    a re-render: `RenderStep.is_satisfied` watches shot-binding mtimes,
    not caption text (caption_romanization.md §5).
    """
    timeline = await ctx.timeline_service.get_active(ctx.project_id)
    if timeline is None:
        return StepResult(outcome="failed", error="no active timeline to romanize captions for")
    was_approved = timeline.status == TimelineStatus.APPROVED
    await _apply_romanization(
        ctx,
        timeline,
        produced_by=ProducedBy.NARRATION,
        reapprove=was_approved,
    )
    return StepResult(outcome="ok")


async def _apply_romanization(
    ctx: RunContext,
    timeline: Timeline,
    *,
    produced_by: ProducedBy,
    reapprove: bool,
) -> Timeline:
    """Plan (or no-op in DRY_RUN), append one version, optionally
    re-approve. Always stamps `caption_romanization_attempted` so the
    step cannot retry-fail a run over a cosmetic miss.

    `RomanizeCaptionsStep.run` returns before reaching this in DRY_RUN;
    the DRY_RUN branch below is what keeps the explicitly-invoked
    `backfill_caption_romanization` off the real provider."""

    if settings.dry_run:
        planned_by_id: dict[str, tuple[str | None, list[int] | None]] = {}
    else:
        provider = OpenAIPlanningProvider(model=settings.openai_planning_model_cheap)
        planner = CaptionRomanizer(provider, LlmCallRepository(ctx.session))
        planned = await planner.plan(project_id=ctx.project_id, scenes=timeline.scenes)
        planned_by_id = {
            scene.id: (scene.caption_text, scene.caption_word_groups) for scene in planned
        }

    def _record(base: Timeline) -> Timeline:
        new_scenes = []
        for scene in base.scenes:
            caption_text, caption_word_groups = planned_by_id.get(scene.id, (None, None))
            if caption_text:
                new_scenes.append(
                    scene.model_copy(
                        update={
                            "caption_text": caption_text,
                            # caption_romanization.md §10.3: carried through
                            # alongside caption_text — dropping it here would
                            # silently discard grouping and fall the scene
                            # back to the plain 1:1 bridge in captions.py.
                            "caption_word_groups": caption_word_groups,
                        }
                    )
                )
            else:
                new_scenes.append(scene)
        base.scenes = new_scenes
        base.metadata.caption_romanization_attempted = True
        return base

    new_timeline = await ctx.timeline_service.append_version(
        ctx.project_id,
        produced_by=produced_by,
        transform=_record,
        owns=_OWNS,
    )
    if reapprove:
        new_timeline = await ctx.timeline_service.approve(ctx.project_id, new_timeline.version)
    return new_timeline
