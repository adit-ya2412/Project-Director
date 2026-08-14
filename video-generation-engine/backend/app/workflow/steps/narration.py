"""The master clock step (M8 step 2 - see docs/13_Implementation_Guide.md,
"Phase M8 — Renderer", build order item 2).

Runs one TTS request per scene (D1, settled: per-scene, not per-video - the
cache key and `narration_span` offsets are both per-scene already), then
reconciles the real spoken durations into a NEW Timeline version via
`narration_fit.reconcile_timeline_durations` - the arithmetic itself lives
there and is proven by its own test suite; this step is the plumbing
around it (provider call, cache, budget, `append_version`).

## Where this sits in the pipeline, and why

`ShotBinding` rows are keyed by `(project_id, timeline_version, shot_id)`,
and both `ResolveAssetsStep` and `RenderStep` look up bindings by the
*active* timeline version. If narration ran AFTER `ResolveAssetsStep`, its
new `append_version` call would orphan every binding at the old version -
`ResolveAssetsStep` would re-resolve (and re-pay for) every shot, and
`RenderStep` would find no bindings at all. So this step must run BEFORE
`ResolveAssetsStep`. It must also run AFTER `AwaitApprovalStep` - TTS costs
money, and I6 forbids anything expensive before approval. See
`app/workflow/engine.DEFAULT_PIPELINE`.

## Approval, and the crash window around it

Narration reconciles durations; it does not re-open the creative plan for
review (M8 open decision: "approval is of the creative plan, not of
millisecond timings"). So the version this step appends is immediately
marked approved too, via the same `TimelineService.approve` the API uses -
`AwaitApprovalStep` never needs to know this step exists. Belt and braces
against the crash window between `append_version` and `approve` (both are
separate commits): `AwaitApprovalStep.is_satisfied`/`run` also treat
`produced_by == NARRATION` as approval-equivalent on their own, so a crash
in that exact window resumes by finishing the approval rather than making
the engine demand a second human click for a version a human already
approved.

## Resumability (load-bearing - see the M4/M5 notes on this exact mistake)

`is_satisfied` checks the ACTIVE timeline's `produced_by` field, not a
stored flag and not "do some narration rows exist" (narration rows are a
GLOBAL content-hash cache shared across projects - their existence proves
nothing about whether THIS project's active timeline has been reconciled).
A timeline version can only ever get `produced_by == NARRATION` from this
step's own `append_version` call below, so observing it on the active
version is proof this step already finished for it. A retry mid-run simply
redoes the per-scene loop; each scene's own cache lookup (keyed on content
hash, exactly like step 1) makes that safe - no scene is ever synthesised,
and no project is ever billed, twice.

## Failure isolation - deliberately NOT per-scene

`ResolveAssetsStep` isolates failures per shot because a missing image
asset degrades gracefully to a placeholder frame - still a watchable
video. A missing scene's narration has no equivalent placeholder: skipping
it would either leave that scene's shots with no real duration data (an
invented number - exactly what this module refuses to do) or silently
drop a chunk of the spoken script. So a single scene's synthesis failure
fails the WHOLE step: a transient provider error retries the step (safe,
thanks to the cache), and anything else stops the run and surfaces
clearly, rather than shipping a documentary with a silently missing
paragraph.
"""

import uuid as uuid_module

from app.assets.cost import check_budget, total_project_spend_cents
from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import NarrationProvider, NarrationRequest
from app.providers.elevenlabs import ElevenLabsNarrationProvider, compute_narration_content_hash
from app.providers.fakes.narration import FakeNarrationProvider
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import ProducedBy, Timeline
from app.timeline.duration import compute_timeline_duration
from app.timeline.narration_fit import SceneAlignment, reconcile_timeline_durations
from app.workflow.context import RunContext
from app.workflow.step import StepResult

# Only ever used when DRY_RUN=true and no voice is configured - see run().
_DRY_RUN_VOICE_ID = "dry-run-voice"


class NarrationStep:
    name = "narration"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        return timeline is not None and timeline.produced_by == ProducedBy.NARRATION

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to narrate")

        voice_id = timeline.metadata.voice_id or settings.elevenlabs_voice_id
        if not voice_id:
            if not settings.dry_run:
                return StepResult(
                    outcome="failed",
                    error="no narration voice configured - set ELEVENLABS_VOICE_ID or "
                    "Timeline.metadata.voice_id before narration can run",
                )
            # DRY_RUN must keep working with ZERO API keys configured - that
            # is the walking skeleton's whole contract (implementation guide
            # section 4.1, and the e2e test that enforces it). Requiring a
            # real voice id here would break `DRY_RUN=true` for anyone who
            # has never touched ElevenLabs, even though FakeNarrationProvider
            # ignores the voice entirely. A fixed placeholder keeps the
            # content hash deterministic, which is what the cache needs.
            voice_id = _DRY_RUN_VOICE_ID

        # Everything from here on can fail for reasons that map onto the
        # three step outcomes (mirrors GenerateTimelineStep.run): a
        # transient provider error is safe to retry (the cache means no
        # scene already synthesised gets re-paid for on the retry), and
        # anything else - budget exceeded, corrupted alignment data, the
        # reconciled video running too long - is a clean, loud `failed`
        # rather than a raw exception escaping the step.
        try:
            alignments = await self._synthesize_scene_alignments(ctx, timeline, voice_id=voice_id)
            new_timeline = await self._reconcile_and_append(ctx, timeline, alignments)
        except TransientError as exc:
            return StepResult(outcome="retry", error=str(exc))
        except PermanentError as exc:
            return StepResult(outcome="failed", error=str(exc))

        await ctx.timeline_service.approve(ctx.project_id, new_timeline.version)
        return StepResult(outcome="ok")

    async def _synthesize_scene_alignments(
        self, ctx: RunContext, timeline: Timeline, *, voice_id: str
    ) -> dict[str, SceneAlignment]:
        """One TTS request per scene (D1: per-scene, settled), reusing
        step 1's global content-hash cache - a scene already synthesised
        by ANY project is never paid for twice."""
        project_uuid = uuid_module.UUID(ctx.project_id)
        narration_repo = NarrationRepository(ctx.session)
        clip_repo = GeneratedClipRepository(ctx.session)
        provider: NarrationProvider = (
            FakeNarrationProvider() if settings.dry_run else ElevenLabsNarrationProvider()
        )
        project_dir = settings.storage_root / ctx.project_id / "narration"
        project_dir.mkdir(parents=True, exist_ok=True)

        alignments: dict[str, SceneAlignment] = {}
        for scene in timeline.scenes:
            content_hash = compute_narration_content_hash(
                text=scene.narration_text,
                voice_id=voice_id,
                model=settings.elevenlabs_model,
                output_format=settings.elevenlabs_output_format,
            )
            row = await narration_repo.get_by_content_hash(content_hash)
            if row is None:
                estimated_cents = round(
                    len(scene.narration_text) * settings.elevenlabs_cost_cents_per_character
                )
                already_spent = await total_project_spend_cents(
                    clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
                )
                check_budget(already_spent_cents=already_spent, additional_cents=estimated_cents)

                result = await provider.synthesize(
                    NarrationRequest(
                        text=scene.narration_text,
                        voice_id=voice_id,
                        model=settings.elevenlabs_model,
                        output_format=settings.elevenlabs_output_format,
                        scene_id=scene.id,
                    )
                )
                # D3: content-hash filename, under {project}/narration/.
                path = project_dir / f"{content_hash}.mp3"
                path.write_bytes(result.content)
                row = await narration_repo.insert(
                    project_id=project_uuid,
                    scene_id=scene.id,
                    provider=provider.name,
                    voice_id=voice_id,
                    model_id=settings.elevenlabs_model,
                    output_format=settings.elevenlabs_output_format,
                    text=scene.narration_text,
                    content_hash=content_hash,
                    local_path=str(path),
                    alignment=result.alignment,
                    character_count=result.character_count,
                    cost_cents=estimated_cents,
                )
            alignments[scene.id] = SceneAlignment.from_raw(row.alignment)
        return alignments

    async def _reconcile_and_append(
        self, ctx: RunContext, timeline: Timeline, alignments: dict[str, SceneAlignment]
    ) -> Timeline:
        reconciled = reconcile_timeline_durations(timeline, alignments)

        # D7 caps vs. reality (M8 settled decision): a shot may legitimately
        # exceed max_shot_duration_s once its real narration is in - the
        # cap is a planning heuristic, narration is real. But the whole
        # video exceeding max_video_duration_s is not tolerable, and audio
        # is never silently trimmed to fit - so check the real total
        # BEFORE persisting anything, and fail loudly rather than ship (or
        # silently cut) a video that runs long.
        updated_shots = [
            shot.model_copy(update={"duration_s": reconciled[shot.id]})
            for shot in timeline.all_shots()
        ]
        new_total = compute_timeline_duration(updated_shots)
        if new_total > settings.max_video_duration_s:
            raise PermanentError(
                f"narration-reconciled duration is {new_total:.2f}s, exceeding "
                f"max_video_duration_s ({settings.max_video_duration_s}s) - shorten the "
                "script; narration is never trimmed to fit"
            )

        def _apply_durations(base: Timeline) -> Timeline:
            for scene in base.scenes:
                for shot in scene.shots:
                    shot.duration_s = reconciled[shot.id]
            # Recomputed via the one function that owns this arithmetic
            # (D5) - never by hand.
            base.metadata.total_duration_s = compute_timeline_duration(base.all_shots())
            return base

        return await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.NARRATION,
            transform=_apply_durations,
            owns=frozenset({"scenes", "metadata"}),
        )
