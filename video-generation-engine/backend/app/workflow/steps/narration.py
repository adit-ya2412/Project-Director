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
*active* timeline version. `ResolveAssetsStep` now runs TWICE (M6.5, A5/
A21) - a free search-only pass BEFORE this step, and a paid
generation-only pass after `AwaitApprovalStep`. This step's own `append_version`
call (reconciled durations) bumps the version between the search pass and
the approval gate, which would silently orphan every binding the search
pass found if `TimelineService` didn't carry them forward (A11/A20 - see
`app/timeline/service.py` for where that actually happens: every shot
narration reconciles keeps its `prompt`/`asset_plan` byte-identical,
since it only ever changes `duration_s`, so every binding carries).

**This step runs BEFORE `AwaitApprovalStep` (decision, 2026-08-16 - see
`app/workflow/engine.DEFAULT_PIPELINE`'s own module docstring for the
full reasoning), a deliberate, narrow I6 exception**: narration costs
real money (~10 cents) and now runs pre-approval, because the one-gate
redesign needs the human to see REAL, measured shot durations at the
gate, not the planner's pre-audio guess - a busy image that's fine on
screen for 4.6s and wrong for 1.5s is not a judgement a human can make
against an estimate. Narration is also the cheapest, earliest thing that
can fail (~10c vs. tens of cents of generation, script-wide), so a script
that can never ship is caught before a human's review time is spent on
it. This step still runs BEFORE the generation-only `ResolveAssetsStep`
pass, so that pass (and `RenderStep`) always bind against the FINAL,
narration-corrected version.

## Approval, and why this step does NOT always self-approve

Narration reconciles durations; it does not re-open the creative plan for
review (M8 open decision: "approval is of the creative plan, not of
millisecond timings"). Under the OLD pipeline order (approve, then
narrate) that meant the version this step appended was always
immediately marked approved too - a human had already approved a prior
version, and narration was never meant to demand a second click for a
mere duration reconciliation.

Under the NEW order, that is no longer universally true: the FIRST time
this step ever runs for a project, it runs BEFORE the human has approved
anything at all - the version it appends IS what `AwaitApprovalStep`
(which runs immediately after this step now) is waiting for a human to
approve. Self-approving unconditionally here would make that gate a
silent no-op - the pipeline would sail straight through it the instant
narration finished, with nobody having clicked anything.

So this step only self-approves when the version it narrated FROM was
ALREADY approved (`timeline.status == TimelineStatus.APPROVED`, checked
at the top of `run()` before anything is appended) - which is exactly
the N1 "redo narration with a different voice" path
(`POST /narration/retry`): that endpoint's own `_resume_after_human_correction`
re-approves its `produced_by=HUMAN` voice-change version before resuming
the engine (since the project was already past its first approval by
then), so when `NarrationStep` re-runs against it, the pre-narration
timeline IS approved, and the freshly re-synthesized version is
self-approved too - preserving N1's "resume, no second click" contract
without reopening the FIRST-approval gate this step now sits in front of.

## Resumability (load-bearing - see the M4/M5 notes on this exact mistake)

`is_satisfied` checks the ACTIVE timeline's `produced_by` field, not a
stored flag and not "do some narration rows exist" (narration rows are a
GLOBAL content-hash cache shared across projects - their existence proves
nothing about whether THIS project's active timeline has been reconciled).
A timeline version can only ever get `produced_by == NARRATION` from this
step's own `append_version` call below, so observing it on the active
version is proof this step already finished for it. A retry mid-run simply
redoes the unique-by-hash gather; each hash's own cache lookup (DB row,
then this project's mp3 + alignment sidecar) makes that safe - no hash is
ever synthesised, and no project is ever billed, twice.

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

import asyncio
import json
import uuid as uuid_module
from dataclasses import dataclass
from pathlib import Path

from app.assets.cost import check_budget, total_project_spend_cents
from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.planners.fragments import split_narration_fragments
from app.providers.base import NarrationProvider, NarrationRequest
from app.providers.elevenlabs import ElevenLabsNarrationProvider, compute_narration_content_hash
from app.providers.fakes.narration import FakeNarrationProvider
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import ProducedBy, Scene, Timeline, TimelineStatus
from app.script.styles import resolve_constraint_bundle
from app.timeline.duration import compute_timeline_duration
from app.timeline.narration_fit import SceneAlignment, reconcile_timeline_durations
from app.utils.bounded_gather import narration_concurrency, reserve_then_gather
from app.workflow.context import RunContext
from app.workflow.step import StepResult

# Only ever used when DRY_RUN=true and no voice is configured - see run().
_DRY_RUN_VOICE_ID = "dry-run-voice"

# Track C §3.3: alignment lives in the DB row. After pytest truncates
# `narration` the mp3 is still on disk but unusable without this sidecar
# (mp3-only legacy files still re-synthesise). Written next to the mp3.
_ALIGNMENT_SIDECAR_SUFFIX = ".alignment.json"
_ALIGNMENT_KEYS = frozenset(
    {"characters", "character_start_times_seconds", "character_end_times_seconds"}
)


@dataclass(frozen=True)
class _SynthJob:
    """One unique content-hash that still needs a paid TTS call."""

    content_hash: str
    scene_id: str
    text: str
    estimated_cents: int


def _alignment_sidecar_path(mp3_path: Path) -> Path:
    return mp3_path.with_name(mp3_path.stem + _ALIGNMENT_SIDECAR_SUFFIX)


def _write_alignment_sidecar(mp3_path: Path, alignment: dict) -> None:
    _alignment_sidecar_path(mp3_path).write_text(
        json.dumps(alignment, ensure_ascii=False), encoding="utf-8"
    )


def _read_alignment_sidecar(mp3_path: Path) -> dict | None:
    sidecar = _alignment_sidecar_path(mp3_path)
    if not sidecar.is_file() or sidecar.stat().st_size == 0:
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.keys() >= _ALIGNMENT_KEYS:
        return None
    return data


def _ensure_alignment_sidecar(mp3_path: Path, alignment: dict) -> None:
    """Back-fill the sidecar next to an existing mp3 so a later DB wipe
    can restore without re-paying. No-op if the mp3 is gone (another
    project's path after a cache hit, or a deleted file)."""
    if not mp3_path.is_file():
        return
    sidecar = _alignment_sidecar_path(mp3_path)
    if not sidecar.is_file():
        _write_alignment_sidecar(mp3_path, alignment)


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
        # Captured BEFORE anything is appended (see this module's own
        # docstring, "Approval, and why this step does NOT always
        # self-approve"): whether to self-approve the version this run
        # produces depends on whether the version it narrated FROM was
        # already approved, not on anything about the NEW version itself.
        already_approved = timeline.status == TimelineStatus.APPROVED

        try:
            alignments = await self._synthesize_scene_alignments(ctx, timeline, voice_id=voice_id)
            new_timeline = await self._reconcile_and_append(ctx, timeline, alignments)
        except TransientError as exc:
            return StepResult(outcome="retry", error=str(exc))
        except PermanentError as exc:
            return StepResult(outcome="failed", error=str(exc))

        if already_approved:
            # N1 (narration redo, e.g. a different voice): the project was
            # already past its first approval, so this reconciliation is
            # not reopening the creative plan for review - self-approve,
            # same as the old unconditional behaviour. The FIRST pass on a
            # fresh, unapproved project (narration now runs before
            # `AwaitApprovalStep` - 2026-08-16) deliberately does NOT hit
            # this branch: that version is exactly what the gate is
            # waiting for a human to look at.
            await ctx.timeline_service.approve(ctx.project_id, new_timeline.version)
        return StepResult(outcome="ok")

    async def _synthesize_scene_alignments(
        self, ctx: RunContext, timeline: Timeline, *, voice_id: str
    ) -> dict[str, SceneAlignment]:
        """One TTS request per unique content hash (D1: per-scene text,
        settled), reusing the global content-hash cache. A hash already
        synthesised by ANY project is never paid for twice; a hash whose
        DB row was wiped but whose mp3 + alignment sidecar still sit in
        this project's narration dir is restored rather than re-paid
        (Track C §3.3). Paid calls go through `reserve_then_gather` at
        ElevenLabs' concurrent-request cap of 3 (Q4 / Q5)."""
        project_uuid = uuid_module.UUID(ctx.project_id)
        narration_repo = NarrationRepository(ctx.session)
        clip_repo = GeneratedClipRepository(ctx.session)
        provider: NarrationProvider = (
            FakeNarrationProvider() if settings.dry_run else ElevenLabsNarrationProvider()
        )
        project_dir = settings.storage_root / ctx.project_id / "narration"
        project_dir.mkdir(parents=True, exist_ok=True)

        alignments: dict[str, SceneAlignment] = {}
        jobs: list[_SynthJob] = []
        queued_hashes: set[str] = set()
        hash_to_scene_ids: dict[str, list[str]] = {}

        for scene in timeline.scenes:
            content_hash = compute_narration_content_hash(
                text=scene.narration_text,
                voice_id=voice_id,
                model=settings.elevenlabs_model,
                output_format=settings.elevenlabs_output_format,
            )
            hash_to_scene_ids.setdefault(content_hash, []).append(scene.id)

            row = await narration_repo.get_by_content_hash(content_hash)
            if row is not None:
                _ensure_alignment_sidecar(Path(row.local_path), row.alignment)
                alignments[scene.id] = SceneAlignment.from_raw(row.alignment)
                continue

            restored = await self._restore_row_from_disk(
                narration_repo,
                project_uuid=project_uuid,
                scene=scene,
                content_hash=content_hash,
                voice_id=voice_id,
                provider_name=provider.name,
                project_dir=project_dir,
            )
            if restored is not None:
                alignments[scene.id] = SceneAlignment.from_raw(restored.alignment)
                continue

            if content_hash not in queued_hashes:
                queued_hashes.add(content_hash)
                jobs.append(
                    _SynthJob(
                        content_hash=content_hash,
                        scene_id=scene.id,
                        text=scene.narration_text,
                        estimated_cents=round(
                            len(scene.narration_text) * settings.elevenlabs_cost_cents_per_character
                        ),
                    )
                )

        if jobs:
            db_lock = asyncio.Lock()
            reserved_cents = 0

            async def reserve(job: _SynthJob) -> None:
                nonlocal reserved_cents
                reserved_cents += job.estimated_cents

            async def check() -> None:
                already_spent = await total_project_spend_cents(
                    clip_repo=clip_repo,
                    narration_repo=narration_repo,
                    project_id=project_uuid,
                )
                check_budget(already_spent_cents=already_spent, additional_cents=reserved_cents)

            async def release(job: _SynthJob) -> None:
                nonlocal reserved_cents
                reserved_cents -= job.estimated_cents

            async def submit(job: _SynthJob) -> dict:
                result = await provider.synthesize(
                    NarrationRequest(
                        text=job.text,
                        voice_id=voice_id,
                        model=settings.elevenlabs_model,
                        output_format=settings.elevenlabs_output_format,
                        scene_id=job.scene_id,
                    )
                )
                path = project_dir / f"{job.content_hash}.mp3"
                path.write_bytes(result.content)
                _write_alignment_sidecar(path, result.alignment)
                async with db_lock:
                    await narration_repo.insert(
                        project_id=project_uuid,
                        scene_id=job.scene_id,
                        provider=provider.name,
                        voice_id=voice_id,
                        model_id=settings.elevenlabs_model,
                        output_format=settings.elevenlabs_output_format,
                        text=job.text,
                        content_hash=job.content_hash,
                        local_path=str(path),
                        alignment=result.alignment,
                        character_count=result.character_count,
                        cost_cents=job.estimated_cents,
                    )
                return result.alignment

            results = await reserve_then_gather(
                jobs,
                reserve=reserve,
                check=check,
                submit=submit,
                release=release,
                concurrency=narration_concurrency(),
            )
            # Narration has no placeholder: any hash that failed fails
            # the whole step. Siblings already finished (and are cached)
            # so a retry only re-pays the failed hash.
            for job, result in zip(jobs, results, strict=True):
                if isinstance(result, Exception):
                    raise result
                for scene_id in hash_to_scene_ids[job.content_hash]:
                    alignments[scene_id] = SceneAlignment.from_raw(result)

        return alignments

    async def _restore_row_from_disk(
        self,
        narration_repo: NarrationRepository,
        *,
        project_uuid: uuid_module.UUID,
        scene: Scene,
        content_hash: str,
        voice_id: str,
        provider_name: str,
        project_dir: Path,
    ):
        """Re-insert a wiped DB row from this project's mp3 + sidecar.

        Both files must exist and be non-empty. An mp3 without a sidecar
        (every file written before C2) is not enough to rebuild
        `alignment`, so those still re-synthesise."""
        mp3_path = project_dir / f"{content_hash}.mp3"
        if not mp3_path.is_file() or mp3_path.stat().st_size == 0:
            return None
        alignment = _read_alignment_sidecar(mp3_path)
        if alignment is None:
            return None
        return await narration_repo.insert(
            project_id=project_uuid,
            scene_id=scene.id,
            provider=provider_name,
            voice_id=voice_id,
            model_id=settings.elevenlabs_model,
            output_format=settings.elevenlabs_output_format,
            text=scene.narration_text,
            content_hash=content_hash,
            local_path=str(mp3_path),
            alignment=alignment,
            character_count=len(scene.narration_text),
            cost_cents=round(
                len(scene.narration_text) * settings.elevenlabs_cost_cents_per_character
            ),
        )

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
        # Same resolver GenerateTimelineStep / preflight use (R1). The
        # flat 90 s cap would reject every long-form narration even
        # after C1 authorised the length at plan time.
        script_text = "".join(s.narration_text for s in timeline.scenes)
        n_fragments = len(split_narration_fragments(script_text)) if script_text else None
        duration_cap = resolve_constraint_bundle(
            timeline.metadata.render_style, n_fragments=n_fragments
        ).max_video_duration_s
        if new_total > duration_cap:
            raise PermanentError(
                f"narration-reconciled duration is {new_total:.2f}s, exceeding "
                f"max_video_duration_s ({duration_cap}s) - shorten the "
                "script; narration is never trimmed to fit"
            )

        def _apply_durations(base: Timeline) -> Timeline:
            for scene in base.scenes:
                for shot in scene.shots:
                    shot.duration_s = reconciled[shot.id]
            # Recomputed via the one function that owns this arithmetic
            # (D5) - never by hand.
            base.metadata.total_duration_s = compute_timeline_duration(base.all_shots())
            # Permanent, from here on (M8 hardening, 2026-08-16): every
            # shot's duration_s is now a measured fact, not a planning
            # estimate, and `Timeline.validate_constraints` reads this
            # flag to stop re-applying min/max_shot_duration_s to it -
            # forever, across every later version, not just this one.
            base.metadata.narration_locked = True
            return base

        return await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.NARRATION,
            transform=_apply_durations,
            owns=frozenset({"scenes", "metadata"}),
        )
