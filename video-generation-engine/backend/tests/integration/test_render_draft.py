"""Draft mode (M8 step 6): `render_video` parameterised at
`settings.draft_width`/`draft_height` instead of the final render's own
dimensions - proving draft and final of the SAME timeline content produce
two independent files, at two different resolutions, without colliding on
one fingerprint/cache entry (the collision guard is already proven at the
pure-fingerprint level in tests/unit/renderer/test_fingerprint.py; this
proves it holds through the real `render_video` pipeline too, with a real
ffmpeg encode measured back out via ffprobe).
"""

import asyncio
import hashlib
import json
import uuid as uuid_module

import pytest_asyncio
from PIL import Image

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.asset import AssetModel
from app.models.shot_binding import ShotBindingModel
from app.renderer.slideshow import RenderSettings
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps.render import render_video

_FINAL_SETTINGS = RenderSettings(
    width=settings.render_width,
    height=settings.render_height,
    fps=settings.render_fps,
    pixel_format=settings.render_pixel_format,
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)
_DRAFT_SETTINGS = RenderSettings(
    width=settings.draft_width,
    height=settings.draft_height,
    fps=settings.render_fps,
    pixel_format=settings.render_pixel_format,
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color=color).save(buf, format="PNG")
    return buf.getvalue()


async def _ffprobe_dimensions(path) -> tuple[int, int]:
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    stream = json.loads(stdout.decode())["streams"][0]
    return stream["width"], stream["height"]


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


@pytest_asyncio.fixture
async def project_with_shot() -> str:
    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).create("draft-render-test")
        project_id = project.id

    image_bytes = _png_bytes((40, 50, 60))
    image_dir = settings.storage_root / project_id / "assets"
    image_dir.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(image_bytes).hexdigest()
    image_path = image_dir / f"{content_hash}.png"
    image_path.write_bytes(image_bytes)

    shot = Shot(
        id="sh_00",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=1.0,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    scene = Scene(id="sc_00", order=0, title="Scene", duration_s=1.0, shots=[shot])

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base):
            base.scenes = [scene]
            base.metadata.total_duration_s = 1.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        await service.approve(project_id, appended.version)

        asset = AssetModel(
            project_id=uuid_module.UUID(project_id),
            provider="test-fixture",
            type="image",
            local_path=str(image_path),
            licence="cc0",
            content_hash=content_hash,
            confidence=1.0,
        )
        session.add(asset)
        await session.flush()
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=appended.version,
                shot_id="sh_00",
                state="resolved",
                asset_id=asset.id,
            )
        )
        await session.commit()

    return project_id


async def test_draft_and_final_render_at_their_own_distinct_resolutions(
    project_with_shot, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_with_shot)
        draft_path = await render_video(
            _make_ctx(project_with_shot, session),
            timeline,
            _DRAFT_SETTINGS,
            output_filename="draft.mp4",
        )
        await session.commit()

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_with_shot)
        final_path = await render_video(
            _make_ctx(project_with_shot, session),
            timeline,
            _FINAL_SETTINGS,
            output_filename="final.mp4",
        )
        await session.commit()

    assert draft_path != final_path
    assert draft_path.read_bytes() != final_path.read_bytes()  # not a cache collision

    draft_dims = await _ffprobe_dimensions(draft_path)
    final_dims = await _ffprobe_dimensions(final_path)
    assert draft_dims == (settings.draft_width, settings.draft_height)
    assert final_dims == (settings.render_width, settings.render_height)
    assert draft_dims != final_dims
