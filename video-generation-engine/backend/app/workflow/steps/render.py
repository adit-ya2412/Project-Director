"""Step 4: Timeline + resolved media -> MP4.

Any shot whose binding never resolved (missing, pending, or failed) gets
a placeholder frame rather than blocking the render - the same
per-task failure isolation `ResolveAssetsStep` applies (Principle 10).
"""

import uuid as uuid_module
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.core.errors import EngineError, TransientError
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
from app.renderer.placeholder import render_placeholder
from app.renderer.slideshow import RenderSettings, render_timeline
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.project import ProjectStatus
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

        shot_images: dict[str, Path] = {}
        for shot in timeline.all_shots():
            binding = bindings_by_shot.get(shot.id)
            path = await self._resolved_path(ctx.session, binding)
            if path is None:
                path = work_dir / f"{shot.id}_placeholder.png"
                path.write_bytes(
                    render_placeholder(shot.id, settings.render_width, settings.render_height)
                )
            shot_images[shot.id] = path

        render_settings = RenderSettings(
            width=settings.render_width,
            height=settings.render_height,
            fps=settings.render_fps,
            pixel_format=settings.render_pixel_format,
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
        )
        output_path = project_dir / "renders" / "final.mp4"
        try:
            await render_timeline(
                timeline, shot_images, render_settings, output_path, work_dir=work_dir
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
