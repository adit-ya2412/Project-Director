"""The M0 walking-skeleton pipeline: script -> Timeline -> images -> MP4.

Deliberately linear and synchronous. M4 replaces this with the real
Workflow Engine (explicit steps, retries, resumability, the human-approval
gate) — every step here becomes one `WorkflowStep` there. Until then this
function is the whole "workflow": it proves the shape of the IR and the
renderer before either planners or a state machine exist.

Every provider used here is a fake (Invariant: providers/ firewall). No
network calls, no API keys, no spend.
"""

from pathlib import Path

from app.core.config import settings
from app.core.errors import EngineError
from app.core.logging import get_logger
from app.providers.base import AssetQuery, ImageRequest
from app.providers.fakes.asset import FakeAssetProvider
from app.providers.fakes.image import FakeImageProvider
from app.providers.fakes.llm import FakeTimelinePlanner
from app.renderer.slideshow import RenderSettings, render_timeline
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import Project, ProjectStatus
from app.schemas.timeline import AssetStrategy, Shot

logger = get_logger(__name__)

_SEARCH_STRATEGIES = {
    AssetStrategy.PROJECT_ASSETS,
    AssetStrategy.HISTORICAL_SEARCH,
    AssetStrategy.PUBLIC_DOMAIN,
    AssetStrategy.STOCK_SEARCH,
}


async def _resolve_shot_image(
    shot: Shot,
    *,
    image_provider: FakeImageProvider,
    asset_provider: FakeAssetProvider,
) -> bytes:
    """Reuse-before-generate (Creative Philosophy Principle 8), even in
    fake form: search strategies go through the asset provider; only
    generate_image/generate_video strategies (or no asset_plan at all)
    fall through to image generation."""
    strategy = shot.asset_plan.strategy if shot.asset_plan else AssetStrategy.GENERATE_IMAGE

    if strategy in _SEARCH_STRATEGIES:
        query = AssetQuery(
            search_terms=shot.asset_plan.search_queries if shot.asset_plan else [],
            preferred_type=(shot.asset_plan.preferred_type.value if shot.asset_plan else "image"),
            shot_id=shot.id,
        )
        candidates = await asset_provider.search(query)
        if candidates:
            best = max(candidates, key=lambda c: c.score)
            fetched = await asset_provider.fetch(best)
            return fetched.content
        # Fell through the search rung with nothing found — generate.

    result = await image_provider.generate(
        ImageRequest(
            prompt=shot.prompt,
            width=settings.render_width,
            height=settings.render_height,
            shot_id=shot.id,
        )
    )
    return result.content


async def run_pipeline(project: Project, repo: ProjectRepository) -> Project:
    """Run script -> Timeline -> images -> MP4 for one project, updating
    its status as it goes. Never raises — failures are recorded on the
    Project and returned (Principle 10, fail gracefully)."""
    logger.info("pipeline.start", extra={"project_id": project.id})

    project.status = ProjectStatus.RENDERING
    project.error = None
    await repo.update(project)

    try:
        if not project.script:
            raise EngineError("project has no script uploaded")

        timeline = await FakeTimelinePlanner().plan(project_id=project.id, script=project.script)

        violations = timeline.validate_constraints(
            max_video_duration_s=settings.max_video_duration_s,
            max_shots_per_project=settings.max_shots_per_project,
            min_shot_duration_s=settings.min_shot_duration_s,
            max_shot_duration_s=settings.max_shot_duration_s,
            max_scenes=settings.max_scenes,
        )
        if violations:
            raise EngineError(f"timeline violates creative constraints: {violations}")

        project.timeline = timeline
        await repo.update(project)

        project_dir = settings.storage_root / project.id
        work_dir = project_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)

        image_provider = FakeImageProvider()
        asset_provider = FakeAssetProvider()

        shot_images: dict[str, Path] = {}
        for shot in timeline.all_shots():
            content = await _resolve_shot_image(
                shot, image_provider=image_provider, asset_provider=asset_provider
            )
            image_path = work_dir / f"{shot.id}.png"
            image_path.write_bytes(content)
            shot_images[shot.id] = image_path

        render_settings = RenderSettings(
            width=settings.render_width,
            height=settings.render_height,
            fps=settings.render_fps,
            pixel_format=settings.render_pixel_format,
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
        )
        output_path = project_dir / "renders" / "final.mp4"
        await render_timeline(
            timeline, shot_images, render_settings, output_path, work_dir=work_dir
        )

        project.video_path = str(output_path)
        project.status = ProjectStatus.COMPLETED
        logger.info("pipeline.completed", extra={"project_id": project.id})

    except Exception as exc:  # noqa: BLE001 - top-level pipeline boundary
        project.status = ProjectStatus.FAILED
        project.error = str(exc)
        logger.error("pipeline.failed", extra={"project_id": project.id, "error": str(exc)})

    await repo.update(project)
    return project
