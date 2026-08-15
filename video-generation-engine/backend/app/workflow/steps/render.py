"""Step 4: Timeline + resolved media -> MP4.

Any shot whose binding never resolved (missing, pending, or failed) gets
a placeholder frame rather than blocking the render - the same
per-task failure isolation `ResolveAssetsStep` applies (Principle 10).

## Narration (M8 step 3)

The silent visual path (`render_timeline`, unchanged) always runs first,
to a work-directory file rather than straight to `final.mp4`. Whether
that silent file becomes the final output as-is, or gets narration muxed
onto it, is decided by `_resolve_narration_audio` - see its docstring for
exactly which projects get audio and which stay silent, and why both are
correct rather than one being a fallback for the other. The renderer
itself (`app/renderer/audio.py`) stays a pure function: this step reads
narration from paths resolved here and passed in, the same contract
`RenderStep` already has with `shot_images` - it never queries the
database from inside `app/renderer/`.

## Music (M8 step 4)

A third, final pass: whatever the narration stage produced (narrated or
silent) gets music mixed in - or doesn't - decided by
`_resolve_music_track`, mirroring `_resolve_narration_audio`'s own
DRY_RUN/no-op reasoning exactly. `app/renderer/music.py` stays a pure
function too: it reads a video path, a music path, and (optionally) the
same ordered narration paths this step already resolved - never the
database.

## The fingerprint (M8 step 6, I5)

Before doing any of the above, `render_video` computes a fingerprint of
every real input to the output bytes (`app/renderer/fingerprint.py`) and
checks `render` (`RenderRepository`) for an existing COMPLETED render
with that exact fingerprint. A hit means this exact content, at this
exact quality, has provably already been produced - its bytes are copied
into this project's own output path (never a live cross-project file
reference: if the source project's storage is ever cleaned up, this
project's own copy must still exist) and the entire render/mux pipeline
below is skipped. A miss renders for real, then records a new `render`
row so a later, identical request - this project's own resumed run, or a
different project that happens to reproduce byte-identical content - can
reuse it.

## Draft mode (M8 step 6)

`render_video` is parameterised by `RenderSettings` and an output
filename specifically so the SAME function serves both the automated
final render (`RenderStep`, `settings.render_width/height`,
`final.mp4`) and an on-demand low-res preview
(`POST /projects/{id}/render/draft`, `settings.draft_width/height`,
`draft.mp4`) - "always render a fast draft first" (M8 Advice). Draft and
final can never collide on one fingerprint/cache entry: width/height are
themselves part of the fingerprint, so the two modes are provably
different renders even of the identical Timeline content.
"""

import uuid as uuid_module
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import EngineError, PermanentError, TransientError
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
from app.providers.elevenlabs import compute_narration_content_hash
from app.renderer.audio import mux_narration
from app.renderer.fingerprint import compute_render_fingerprint, get_ffmpeg_version
from app.renderer.music import mux_music
from app.renderer.placeholder import render_placeholder
from app.renderer.slideshow import RenderSettings, probe_duration_seconds, render_timeline
from app.renderer.still import ensure_still_image
from app.repositories.narration_repository import NarrationRepository
from app.repositories.render_repository import RenderRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.project import ProjectStatus
from app.schemas.timeline import ProducedBy, Timeline
from app.workflow.context import RunContext
from app.workflow.step import StepResult


class RenderStep:
    name = "render"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        project = await ctx.repo.get(ctx.project_id)
        if project is None or not project.video_path:
            return False
        video_path = Path(project.video_path)
        if not video_path.exists():
            return False

        # A video file existing isn't enough: if resolve_assets re-resolved
        # any shot (e.g. a fixed provider bug turned a placeholder into a
        # real photo) after this file was rendered, the file is stale and
        # must be redone - otherwise a retry silently ships the OLD render
        # forever, even though every upstream shot binding improved.
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return False
        binding_repo = ShotBindingRepository(ctx.session)
        bindings = await binding_repo.list_for_version(
            uuid_module.UUID(ctx.project_id), timeline.version
        )
        if not bindings:
            return True
        latest_binding_update = max(b.updated_at for b in bindings)
        video_mtime = datetime.fromtimestamp(video_path.stat().st_mtime, tz=UTC)
        return video_mtime >= latest_binding_update

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to render")

        render_settings = RenderSettings(
            width=settings.render_width,
            height=settings.render_height,
            fps=settings.render_fps,
            pixel_format=settings.render_pixel_format,
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
        )
        try:
            output_path = await render_video(
                ctx, timeline, render_settings, output_filename="final.mp4"
            )
        except TransientError as exc:
            return StepResult(outcome="retry", error=str(exc))
        except EngineError as exc:
            return StepResult(outcome="failed", error=str(exc))

        project = await ctx.repo.get(ctx.project_id)
        if project is None:
            return StepResult(outcome="failed", error="project vanished mid-render")
        project.video_path = str(output_path)
        project.status = ProjectStatus.RENDERING
        await ctx.repo.update(project)
        return StepResult(outcome="ok")


async def render_video(
    ctx: RunContext,
    timeline: Timeline,
    render_settings: RenderSettings,
    *,
    output_filename: str,
) -> Path:
    """The whole render/mux pipeline, parameterised so `RenderStep` (the
    automated `final.mp4`) and the on-demand draft endpoint (`draft.mp4`,
    M8 step 6) are the same code path, never two - see this module's own
    docstring for why. Checks the fingerprint (I5) BEFORE doing any real
    work; a hit copies an existing render's bytes into this project's own
    output path and returns immediately, a miss renders for real and then
    records one."""
    project_uuid = uuid_module.UUID(ctx.project_id)
    binding_repo = ShotBindingRepository(ctx.session)
    bindings_by_shot = {
        b.shot_id: b for b in await binding_repo.list_for_version(project_uuid, timeline.version)
    }

    project_dir = settings.storage_root / ctx.project_id
    work_dir = project_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path = project_dir / "renders" / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    media_content_hashes: list[str] = []
    shot_images: dict[str, Path] = {}
    for shot in timeline.all_shots():
        binding = bindings_by_shot.get(shot.id)
        path, content_hash = await _resolved_path_and_hash(ctx.session, binding)
        if content_hash is not None:
            media_content_hashes.append(content_hash)
        if path is None:
            path = work_dir / f"{shot.id}_placeholder.png"
            path.write_bytes(
                render_placeholder(shot.id, render_settings.width, render_settings.height)
            )
        else:
            # An animated asset (Commons serves plenty of GIF maps and
            # diagrams) cannot be `-loop`ed as a still, and ffmpeg aborts
            # the ENTIRE render over one such input rather than failing
            # just that shot - see app/renderer/still.py.
            path = await ensure_still_image(
                path, shot_id=shot.id, work_dir=work_dir, settings=render_settings
            )
        shot_images[shot.id] = path

    narration_pairs = await _resolve_narration_audio(ctx.session, timeline)
    narration_paths = [p for p, _ in narration_pairs] if narration_pairs else None
    narration_content_hashes = [h for _, h in narration_pairs] if narration_pairs else []
    music_path = _resolve_music_track(timeline, ctx.project_id)
    music_content_hash = (
        timeline.music_plan.selected_track.content_hash
        if music_path is not None and timeline.music_plan and timeline.music_plan.selected_track
        else None
    )

    ffmpeg_version = await get_ffmpeg_version(render_settings.ffmpeg_binary)
    fingerprint = compute_render_fingerprint(
        timeline=timeline,
        asset_content_hashes=media_content_hashes,
        narration_content_hashes=narration_content_hashes,
        music_content_hash=music_content_hash,
        render_settings=render_settings,
        ffmpeg_version=ffmpeg_version,
    )

    render_repo = RenderRepository(ctx.session)
    cached = await render_repo.get_completed_by_fingerprint(fingerprint)
    if cached is not None and cached.output_path and Path(cached.output_path).exists():
        # Same fingerprint == provably the same output bytes (I5) - copy
        # rather than reference the other render's path directly, so this
        # project's own file survives independently of whatever happens
        # to the source project's storage later.
        output_path.write_bytes(Path(cached.output_path).read_bytes())
    else:
        # The silent video always lands in the work dir first, never at
        # `output_path` directly - `narration_pairs`/`music_path` above
        # decide whether that silent file simply BECOMES the final
        # output, or gets narration/music muxed onto it in further passes
        # (M8 steps 3-4). Either way `render_timeline`'s own graph
        # (crossfades, hard cuts, Ken Burns) is exactly what it always was.
        silent_path = work_dir / f"silent_{output_path.stem}.mp4"
        narrated_path = work_dir / f"narrated_{output_path.stem}.mp4"
        await render_timeline(
            timeline, shot_images, render_settings, silent_path, work_dir=work_dir
        )
        if narration_paths is None:
            silent_path.replace(narrated_path)
        else:
            await mux_narration(silent_path, narration_paths, narrated_path, render_settings)

        if music_path is None:
            narrated_path.replace(output_path)
        else:
            await mux_music(
                narrated_path,
                music_path,
                narration_paths,
                output_path,
                render_settings,
                bed_gain_db=settings.music_bed_gain_db,
                duck_gain_db=settings.music_duck_gain_db,
            )

    duration_s = await probe_duration_seconds(output_path, render_settings.ffprobe_binary)
    await render_repo.insert_completed(
        project_id=project_uuid,
        output_path=str(output_path),
        fingerprint=fingerprint,
        settings={
            "width": render_settings.width,
            "height": render_settings.height,
            "fps": render_settings.fps,
            "pixel_format": render_settings.pixel_format,
        },
        width=render_settings.width,
        height=render_settings.height,
        fps=render_settings.fps,
        duration_s=duration_s,
    )
    return output_path


async def _resolve_narration_audio(
    session: AsyncSession, timeline: Timeline
) -> list[tuple[Path, str]] | None:
    """Ordered per-scene `(narration audio path, content_hash)` pairs for
    the active timeline, or `None` when this project has no real
    narration to mux - the render then stays exactly the silent video it
    already was.

    Two deliberately distinct "no narration" cases collapse to that same
    silent-render behaviour, and neither is a fallback for a missing
    feature - both are the correct, decided output for what they
    describe:

    - `settings.dry_run`: `NarrationStep` still runs and still writes
      `narration` rows (DRY_RUN exercises the reconciliation arithmetic
      end to end via `FakeNarrationProvider` - implementation guide 4.1,
      fakes are kept forever), but its "audio" is a literal fake byte
      string, not decodable media - muxing it would not degrade
      gracefully, it would crash the render with an ffmpeg decode error.
      DRY_RUN's whole contract is "zero spend, always produces something
      runnable"; a silent .mp4 satisfies that, a crash does not.
    - `timeline.produced_by != NARRATION`: covers both an older project
      whose active version predates this step's existence and any
      pipeline that runs `RenderStep` with `NarrationStep` excluded (see
      `tests/integration/test_narration_pipeline_ordering.py`). In
      neither case has anything reconciled this timeline's shot
      durations against real spoken timings, so there is no audio whose
      timing is actually known to agree with the picture - silence is
      the honest output here, not a best-effort guess.

    Past both of those checks, this project's narration IS supposed to
    exist (this exact scene's row is what its shots' `duration_s` were
    reconciled against in `NarrationStep`) - a missing row from here on
    is a genuine data-integrity failure, not a case to quietly degrade
    for, so it raises `PermanentError` rather than silently falling back
    to a silent render that would contradict the timeline's own
    `produced_by` field (same refuse-to-guess philosophy as
    `app/timeline/narration_fit.py`).
    """
    if settings.dry_run:
        return None
    if timeline.produced_by != ProducedBy.NARRATION:
        return None

    # Mirrors NarrationStep's own voice resolution exactly (same fallback
    # order) - it must, since the content hash below is only a cache hit
    # if computed identically to how NarrationStep computed it when the
    # row was written. Both steps run within the same workflow run's
    # process, so `settings` cannot have changed between them.
    voice_id = timeline.metadata.voice_id or settings.elevenlabs_voice_id
    if not voice_id:
        raise PermanentError(
            "timeline is produced_by=narration but no voice_id can be resolved - "
            "narration cannot have run without one"
        )

    narration_repo = NarrationRepository(session)
    pairs: list[tuple[Path, str]] = []
    for scene in timeline.scenes:
        content_hash = compute_narration_content_hash(
            text=scene.narration_text,
            voice_id=voice_id,
            model=settings.elevenlabs_model,
            output_format=settings.elevenlabs_output_format,
        )
        row = await narration_repo.get_by_content_hash(content_hash)
        if row is None:
            raise PermanentError(
                f"timeline is produced_by=narration but no narration row exists for "
                f"scene {scene.id} (content_hash {content_hash}) - cannot mux audio "
                "that was never persisted"
            )
        pairs.append((Path(row.local_path), content_hash))
    return pairs


def _resolve_music_track(timeline: Timeline, project_id: str) -> Path | None:
    """The chosen track's audio file, or `None` when there is nothing to
    mux - mirrors `_resolve_narration_audio`'s own DRY_RUN/no-op
    reasoning exactly (see that function's docstring for the general
    shape of this argument).

    - `settings.dry_run`: `SelectMusicStep` still runs and still records
      a selection (`FakeMusicProvider` always "finds" a canned track,
      exercising the real selection logic end to end), but deliberately
      never writes its fake, undecodable bytes to disk (same idiom as
      `FakeNarrationProvider`) - muxing it would try to read a file that
      was never written, not degrade gracefully. DRY_RUN's contract is
      "zero spend, always produces something runnable"; skipping the mux
      satisfies that, trying to read a missing file would not.
    - `music_plan` absent, or present but `selected_track is None`: a
      genuine, decided "no suitable track" (or no plan at all) - not a
      fallback, the correct output for this step's own scope.

    Past both of those checks, a selected track is supposed to have a
    real file on disk (`SelectMusicStep` only ever records a selection
    after successfully validating and writing it) - a missing file here
    is a genuine data-integrity failure, not a case to quietly degrade
    for, so it raises `PermanentError` rather than silently rendering
    without music."""
    if settings.dry_run:
        return None
    if timeline.music_plan is None or timeline.music_plan.selected_track is None:
        return None

    content_hash = timeline.music_plan.selected_track.content_hash
    path = settings.storage_root / project_id / "music" / f"{content_hash}.mp3"
    if not path.exists():
        raise PermanentError(
            f"timeline has a selected music track (content_hash {content_hash}) but its "
            "audio file is missing on disk - cannot mux music that was never persisted"
        )
    return path


async def _resolved_path_and_hash(session, binding) -> tuple[Path | None, str | None]:
    """The shot's resolved media path, and a content-identifying hash of
    it for the render fingerprint (M8 step 6) - `Asset.content_hash` for
    a searched/uploaded image, `GeneratedClip.prompt_hash` for a
    generated one (there is no separate output-content hash for
    generated media; `prompt_hash` already uniquely determines what was
    generated, via the same cache this pipeline already trusts for
    reuse - see `ResolveAssetsStep`)."""
    if binding is None:
        return None, None
    if binding.asset_id is not None:
        asset = await session.get(AssetModel, binding.asset_id)
        if asset is None or not asset.local_path:
            return None, None
        return Path(asset.local_path), asset.content_hash
    if binding.clip_id is not None:
        clip = await session.get(GeneratedClipModel, binding.clip_id)
        if clip is None or not clip.local_path:
            return None, None
        return Path(clip.local_path), clip.prompt_hash
    return None, None
