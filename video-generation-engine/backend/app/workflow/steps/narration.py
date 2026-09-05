"""The master clock step (M8 step 2 - see docs/13_Implementation_Guide.md,
"Phase M8 — Renderer", build order item 2).

Runs TTS, then reconciles the real spoken durations into a NEW Timeline
version via `narration_fit.reconcile_timeline_durations` - the arithmetic
itself lives there and is proven by its own test suite; this step is the
plumbing around it (provider call, cache, budget, `append_version`).

Cache keys and `Shot.narration_span` stay per-scene (D1). RV-Q10 batches
contiguous uncached unique-hash scenes into one provider call so the
voice cannot change character at a scene join, then splits the returned
alignment and audio back into per-scene files. A cache hit is never
overwritten (the hash is the request, not the bytes), so an already-
synthesised scene in the middle of a timeline breaks the batch.

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

from app.assets.cost import budget_cap_cents_for, check_budget, total_project_spend_cents
from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.planners.fragments import split_narration_fragments
from app.providers.base import NarrationProvider, NarrationRequest
from app.providers.elevenlabs import (
    ElevenLabsNarrationProvider,
    canonical_narration_speed,
    compute_narration_content_hash,
    tts_request_character_limit,
)
from app.providers.fakes.narration import FakeNarrationProvider
from app.renderer.narration_slice import slice_wav
from app.renderer.narration_tempo import apply_narration_tempo
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import ProducedBy, Scene, Timeline, TimelineStatus
from app.script.styles import resolve_constraint_bundle, resolve_narration_speed
from app.timeline.duration import compute_timeline_duration
from app.timeline.narration_batch import (
    NarrationBatchMember,
    SceneNarrationSlice,
    join_batch_text,
    plan_tts_batches,
    split_batched_alignment,
)
from app.timeline.narration_fit import (
    SceneAlignment,
    reconcile_timeline_durations,
    resolve_element_reveals,
    resolve_layer_entry_offsets,
)
from app.utils.bounded_gather import narration_concurrency, reserve_then_gather
from app.workflow.context import RunContext
from app.workflow.step import StepResult

# Only ever used when DRY_RUN=true and no voice is configured - see run().
_DRY_RUN_VOICE_ID = "dry-run-voice"

# Track C §3.3: alignment lives in the DB row. After pytest truncates
# `narration` the audio file is still on disk but unusable without this
# sidecar (legacy audio-only files still re-synthesise). Written next to
# the audio file.
_ALIGNMENT_SIDECAR_SUFFIX = ".alignment.json"
_ALIGNMENT_KEYS = frozenset(
    {"characters", "character_start_times_seconds", "character_end_times_seconds"}
)


@dataclass(frozen=True)
class _SynthJob:
    """One paid TTS call: one scene, or several contiguous unique-hash scenes."""

    members: tuple[NarrationBatchMember, ...]
    estimated_cents: int

    @property
    def scene_id(self) -> str:
        return self.members[0].scene_id

    @property
    def text(self) -> str:
        return join_batch_text(self.members)


def _alignment_sidecar_path(audio_path: Path) -> Path:
    return audio_path.with_name(audio_path.stem + _ALIGNMENT_SIDECAR_SUFFIX)


def _write_alignment_sidecar(audio_path: Path, alignment: dict) -> None:
    _alignment_sidecar_path(audio_path).write_text(
        json.dumps(alignment, ensure_ascii=False), encoding="utf-8"
    )


def _read_alignment_sidecar(audio_path: Path) -> dict | None:
    sidecar = _alignment_sidecar_path(audio_path)
    if not sidecar.is_file() or sidecar.stat().st_size == 0:
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.keys() >= _ALIGNMENT_KEYS:
        return None
    return data


def _ensure_alignment_sidecar(audio_path: Path, alignment: dict) -> None:
    """Back-fill the sidecar next to an existing audio file so a later DB
    wipe can restore without re-paying. No-op if the audio file is gone
    (another project's path after a cache hit, or a deleted file)."""
    if not audio_path.is_file():
        return
    sidecar = _alignment_sidecar_path(audio_path)
    if not sidecar.is_file():
        _write_alignment_sidecar(audio_path, alignment)


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

        language_code = timeline.metadata.language_code or settings.elevenlabs_language_code

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
            alignments = await self._synthesize_scene_alignments(
                ctx, timeline, voice_id=voice_id, language_code=language_code
            )
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
        self, ctx: RunContext, timeline: Timeline, *, voice_id: str, language_code: str | None
    ) -> dict[str, SceneAlignment]:
        """TTS for uncached scenes, reusing the global content-hash cache.

        Unique-by-hash still holds: a hash already synthesised by ANY
        project is never paid for twice; a hash whose DB row was wiped
        but whose mp3 + alignment sidecar still sit in this project's
        narration dir is restored rather than re-paid (Track C §3.3).
        RV-Q10 packs contiguous remaining misses into one request (up to
        the model character cap) so the voice cannot change character at
        a scene join, then splits audio+alignment back into per-scene
        files. Paid calls go through `reserve_then_gather` at ElevenLabs'
        concurrent-request cap of 3 (Q4 / Q5)."""
        project_uuid = uuid_module.UUID(ctx.project_id)
        narration_repo = NarrationRepository(ctx.session)
        clip_repo = GeneratedClipRepository(ctx.session)
        provider: NarrationProvider = (
            FakeNarrationProvider() if settings.dry_run else ElevenLabsNarrationProvider()
        )
        project_dir = settings.storage_root / ctx.project_id / "narration"
        project_dir.mkdir(parents=True, exist_ok=True)

        alignments: dict[str, SceneAlignment] = {}
        hash_to_scene_ids: dict[str, list[str]] = {}
        cached_hashes: set[str] = set()
        ordered_members: list[NarrationBatchMember] = []
        speed = resolve_narration_speed(timeline.metadata.render_style)
        cents_per_char = settings.elevenlabs_cost_cents_per_character

        for scene in timeline.scenes:
            content_hash = compute_narration_content_hash(
                text=scene.narration_text,
                voice_id=voice_id,
                model=settings.elevenlabs_model,
                output_format=settings.elevenlabs_output_format,
                speed=speed,
                language_code=language_code,
            )
            hash_to_scene_ids.setdefault(content_hash, []).append(scene.id)
            ordered_members.append(
                NarrationBatchMember(
                    scene_id=scene.id,
                    content_hash=content_hash,
                    text=scene.narration_text,
                )
            )
            if content_hash in cached_hashes:
                first_id = hash_to_scene_ids[content_hash][0]
                alignments[scene.id] = alignments[first_id]
                continue

            row = await narration_repo.get_by_content_hash(content_hash)
            if row is not None:
                _ensure_alignment_sidecar(Path(row.local_path), row.alignment)
                cached_hashes.add(content_hash)
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
                cached_hashes.add(content_hash)
                alignments[scene.id] = SceneAlignment.from_raw(restored.alignment)
                continue

        jobs = [
            _SynthJob(
                members=tuple(batch),
                estimated_cents=round(len(join_batch_text(batch)) * cents_per_char),
            )
            for batch in plan_tts_batches(
                ordered_members,
                cached_hashes=cached_hashes,
                max_characters=tts_request_character_limit(settings.elevenlabs_model),
            )
        ]

        if jobs:
            db_lock = asyncio.Lock()
            reserved_cents = 0
            cap_cents = budget_cap_cents_for(timeline)

            async def reserve(job: _SynthJob) -> None:
                nonlocal reserved_cents
                reserved_cents += job.estimated_cents

            async def check() -> None:
                already_spent = await total_project_spend_cents(
                    clip_repo=clip_repo,
                    narration_repo=narration_repo,
                    project_id=project_uuid,
                )
                check_budget(
                    already_spent_cents=already_spent,
                    additional_cents=reserved_cents,
                    cap_cents=cap_cents,
                )

            async def release(job: _SynthJob) -> None:
                nonlocal reserved_cents
                reserved_cents -= job.estimated_cents

            async def _persist_slice(
                *,
                member: NarrationBatchMember,
                content: bytes,
                alignment: dict,
                character_count: int,
                cost_cents: int,
                extension: str,
            ) -> None:
                path = project_dir / f"{member.content_hash}{extension}"
                path.write_bytes(content)
                _write_alignment_sidecar(path, alignment)
                async with db_lock:
                    await narration_repo.insert(
                        project_id=project_uuid,
                        scene_id=member.scene_id,
                        provider=provider.name,
                        voice_id=voice_id,
                        model_id=settings.elevenlabs_model,
                        output_format=settings.elevenlabs_output_format,
                        text=member.text,
                        content_hash=member.content_hash,
                        local_path=str(path),
                        alignment=alignment,
                        character_count=character_count,
                        cost_cents=cost_cents,
                    )

            async def submit(job: _SynthJob) -> dict[str, dict]:
                result = await provider.synthesize(
                    NarrationRequest(
                        text=job.text,
                        voice_id=voice_id,
                        model=settings.elevenlabs_model,
                        output_format=settings.elevenlabs_output_format,
                        scene_id=job.scene_id,
                        speed=speed,
                        language_code=language_code,
                    )
                )
                content, alignment = result.content, result.alignment
                if not settings.dry_run:
                    # FakeNarrationProvider (DRY_RUN) already fabricates
                    # its alignment at the right rate itself and its
                    # `content` isn't real audio ffmpeg could process -
                    # this step is real-provider only (narration_tempo.py's
                    # own docstring covers why speed lives here now, not
                    # in the ElevenLabs request).
                    content, alignment = await apply_narration_tempo(
                        content,
                        alignment,
                        canonical_narration_speed(speed),
                        ffmpeg_binary=settings.ffmpeg_binary,
                    )
                if len(job.members) == 1:
                    # A genuine, single ElevenLabs response - real MP3
                    # bytes (or DRY_RUN's fake stand-in), never re-encoded.
                    member = job.members[0]
                    await _persist_slice(
                        member=member,
                        content=content,
                        alignment=alignment,
                        character_count=len(member.text),
                        cost_cents=round(len(member.text) * cents_per_char),
                        extension=".mp3",
                    )
                    return {member.content_hash: alignment}

                slices = split_batched_alignment(alignment, job.members)
                # Cut every slice before inserting any row. A mid-batch
                # ffmpeg failure must not cache the first scenes and
                # leave the join synthesised as two performances.
                pieces: list[tuple[SceneNarrationSlice, bytes]] = []
                for sl in slices:
                    if settings.dry_run:
                        piece = f"fake-narration-audio:{sl.scene_id}:{sl.text}".encode()
                    else:
                        # RV-Q11: PCM/WAV, not a second MP3 encode - see
                        # `slice_wav`'s docstring for the measured drift
                        # a lossy re-encode introduced here.
                        piece = await slice_wav(
                            content,
                            sl.audio_start_s,
                            sl.audio_end_s,
                            ffmpeg_binary=settings.ffmpeg_binary,
                        )
                    pieces.append((sl, piece))
                persisted: dict[str, dict] = {}
                for sl, piece in pieces:
                    await _persist_slice(
                        member=NarrationBatchMember(
                            scene_id=sl.scene_id,
                            content_hash=sl.content_hash,
                            text=sl.text,
                        ),
                        content=piece,
                        alignment=sl.alignment,
                        character_count=len(sl.text),
                        cost_cents=round(len(sl.text) * cents_per_char),
                        extension=".wav",
                    )
                    persisted[sl.content_hash] = sl.alignment
                return persisted

            results = await reserve_then_gather(
                jobs,
                reserve=reserve,
                check=check,
                submit=submit,
                release=release,
                concurrency=narration_concurrency(),
            )
            # Narration has no placeholder: any batch that failed fails
            # the whole step. Siblings already finished (and are cached)
            # so a retry only re-pays the failed batch.
            for job, result in zip(jobs, results, strict=True):
                if isinstance(result, Exception):
                    raise result
                for member in job.members:
                    scene_alignment = SceneAlignment.from_raw(result[member.content_hash])
                    for scene_id in hash_to_scene_ids[member.content_hash]:
                        alignments[scene_id] = scene_alignment

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
        """Re-insert a wiped DB row from this project's audio + sidecar.

        A hash produced by the solo synthesis path (`len(job.members) ==
        1`, above) is stored as `.mp3` - genuine, unre-encoded ElevenLabs
        bytes. A hash produced by the batched-slice path (RV-Q11) is
        stored as `.wav` - PCM, to stay sample-exact (see
        `app.renderer.narration_slice`'s module docstring). This function
        runs before batching is decided, so it does not know which path
        produced a given wiped row, and checks both extensions.

        Both the audio file and its sidecar must exist and be non-empty.
        Audio without a sidecar (every file written before C2) is not
        enough to rebuild `alignment`, so those still re-synthesise."""
        for suffix in (".mp3", ".wav"):
            audio_path = project_dir / f"{content_hash}{suffix}"
            if not audio_path.is_file() or audio_path.stat().st_size == 0:
                continue
            alignment = _read_alignment_sidecar(audio_path)
            if alignment is None:
                continue
            return await narration_repo.insert(
                project_id=project_uuid,
                scene_id=scene.id,
                provider=provider_name,
                voice_id=voice_id,
                model_id=settings.elevenlabs_model,
                output_format=settings.elevenlabs_output_format,
                text=scene.narration_text,
                content_hash=content_hash,
                local_path=str(audio_path),
                alignment=alignment,
                character_count=len(scene.narration_text),
                cost_cents=round(
                    len(scene.narration_text) * settings.elevenlabs_cost_cents_per_character
                ),
            )
        return None

    async def _reconcile_and_append(
        self, ctx: RunContext, timeline: Timeline, alignments: dict[str, SceneAlignment]
    ) -> Timeline:
        reconciled = reconcile_timeline_durations(timeline, alignments)
        # F4 (illustrated_faceless.md §2/F4): the same seam `duration_s`
        # itself is fitted to measured narration at - a layer's entry
        # (`ShotLayer.enter_on_fragment`) is resolved to real seconds here
        # too, never at render time (§4.1/R2). `reconciled` (this shot's
        # FINAL duration_s, post-transition-compensation) is what bounds
        # the clamp, since that is the shot's own on-screen length the
        # renderer's alpha fade actually runs against.
        layer_entry_offsets = resolve_layer_entry_offsets(timeline.scenes, alignments, reconciled)
        # F5 (illustrated_faceless.md §2/F5): same seam, same reasoning -
        # a shot's own element reveal is resolved to real seconds here
        # too, never at render time (§4.1/R2).
        element_reveals = resolve_element_reveals(timeline.scenes, alignments, reconciled)

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
                    # F4: absent from `layer_entry_offsets` means this shot
                    # has no layer with `enter_on_fragment` set - every
                    # `enter_offset_s` on it already sits at its schema
                    # default (0.0), so there is nothing to write back.
                    entries = layer_entry_offsets.get(shot.id)
                    if entries is not None:
                        for layer, offset in zip(shot.layers, entries, strict=True):
                            layer.enter_offset_s = offset
                    # F5: absent from `element_reveals` means this shot
                    # has no `reveal_direction` set - both resolved
                    # fields already sit at their schema defaults (0.0),
                    # so there is nothing to write back.
                    reveal = element_reveals.get(shot.id)
                    if reveal is not None:
                        shot.reveal_start_offset_s, shot.reveal_duration_s = reveal
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
