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
from app.renderer.placeholder import render_placeholder
from app.renderer.slideshow import RenderSettings, render_timeline
from app.renderer.still import ensure_still_image
from app.repositories.narration_repository import NarrationRepository
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

        project_uuid = uuid_module.UUID(ctx.project_id)
        binding_repo = ShotBindingRepository(ctx.session)
        bindings_by_shot = {
            b.shot_id: b
            for b in await binding_repo.list_for_version(project_uuid, timeline.version)
        }

        project_dir = settings.storage_root / ctx.project_id
        work_dir = project_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)

        render_settings = RenderSettings(
            width=settings.render_width,
            height=settings.render_height,
            fps=settings.render_fps,
            pixel_format=settings.render_pixel_format,
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
        )

        shot_images: dict[str, Path] = {}
        for shot in timeline.all_shots():
            binding = bindings_by_shot.get(shot.id)
            path = await self._resolved_path(ctx.session, binding)
            if path is None:
                path = work_dir / f"{shot.id}_placeholder.png"
                path.write_bytes(
                    render_placeholder(shot.id, settings.render_width, settings.render_height)
                )
            else:
                # An animated asset (Commons serves plenty of GIF maps and
                # diagrams) cannot be `-loop`ed as a still, and ffmpeg
                # aborts the ENTIRE render over one such input rather than
                # failing just that shot - see app/renderer/still.py.
                path = await ensure_still_image(
                    path, shot_id=shot.id, work_dir=work_dir, settings=render_settings
                )
            shot_images[shot.id] = path
        output_path = project_dir / "renders" / "final.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # The silent video always lands in the work dir first, never at
        # `output_path` directly - `_resolve_narration_audio` decides below
        # whether that silent file simply BECOMES the final output, or gets
        # narration muxed onto it in a second pass (M8 step 3). Either way
        # `render_timeline`'s own graph (crossfades, hard cuts) is exactly
        # what it was before this step existed.
        silent_path = work_dir / "silent.mp4"
        try:
            await render_timeline(
                timeline, shot_images, render_settings, silent_path, work_dir=work_dir
            )
            narration_paths = await self._resolve_narration_audio(ctx.session, timeline)
            if narration_paths is None:
                silent_path.replace(output_path)
            else:
                await mux_narration(silent_path, narration_paths, output_path, render_settings)
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

    @staticmethod
    async def _resolve_narration_audio(
        session: AsyncSession, timeline: Timeline
    ) -> list[Path] | None:
        """Ordered per-scene narration audio paths for the active timeline,
        or `None` when this project has no real narration to mux - the
        render then stays exactly the silent video it already was.

        Two deliberately distinct "no narration" cases collapse to that
        same silent-render behaviour, and neither is a fallback for a
        missing feature - both are the correct, decided output for what
        they describe:

        - `settings.dry_run`: `NarrationStep` still runs and still writes
          `narration` rows (DRY_RUN exercises the reconciliation
          arithmetic end to end via `FakeNarrationProvider` - implementation
          guide 4.1, fakes are kept forever), but its "audio" is a literal
          fake byte string, not decodable media - muxing it would not
          degrade gracefully, it would crash the render with an ffmpeg
          decode error. DRY_RUN's whole contract is "zero spend, always
          produces something runnable"; a silent .mp4 satisfies that, a
          crash does not.
        - `timeline.produced_by != NARRATION`: covers both an older
          project whose active version predates this step's existence and
          any pipeline that runs `RenderStep` with `NarrationStep` excluded
          (see `tests/integration/test_narration_pipeline_ordering.py`).
          In neither case has anything reconciled this timeline's shot
          durations against real spoken timings, so there is no audio
          whose timing is actually known to agree with the picture -
          silence is the honest output here, not a best-effort guess.

        Past both of those checks, this project's narration IS supposed to
        exist (this exact scene's row is what its shots' `duration_s` were
        reconciled against in `NarrationStep`) - a missing row from here on
        is a genuine data-integrity failure, not a case to quietly degrade
        for, so it raises `PermanentError` rather than silently falling
        back to a silent render that would contradict the timeline's own
        `produced_by` field (same refuse-to-guess philosophy as
        `app/timeline/narration_fit.py`).
        """
        if settings.dry_run:
            return None
        if timeline.produced_by != ProducedBy.NARRATION:
            return None

        # Mirrors NarrationStep's own voice resolution exactly (same
        # fallback order) - it must, since the content hash below is only
        # a cache hit if computed identically to how NarrationStep computed
        # it when the row was written. Both steps run within the same
        # workflow run's process, so `settings` cannot have changed between
        # them.
        voice_id = timeline.metadata.voice_id or settings.elevenlabs_voice_id
        if not voice_id:
            raise PermanentError(
                "timeline is produced_by=narration but no voice_id can be resolved - "
                "narration cannot have run without one"
            )

        narration_repo = NarrationRepository(session)
        paths: list[Path] = []
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
            paths.append(Path(row.local_path))
        return paths

    @staticmethod
    async def _resolved_path(session, binding) -> Path | None:
        if binding is None:
            return None
        if binding.asset_id is not None:
            asset = await session.get(AssetModel, binding.asset_id)
            return Path(asset.local_path) if asset and asset.local_path else None
        if binding.clip_id is not None:
            clip = await session.get(GeneratedClipModel, binding.clip_id)
            return Path(clip.local_path) if clip and clip.local_path else None
        return None
