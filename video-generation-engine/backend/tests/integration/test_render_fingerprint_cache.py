"""The fingerprint CACHE-HIT path (M8 step 6, I5), proven end to end
through the real database - not just the pure `compute_render_fingerprint`
unit tests (`tests/unit/renderer/test_fingerprint.py`), which never touch
`RenderRepository` or `render_video`'s own copy-instead-of-reencode branch.

Two DIFFERENT projects, built independently, that happen to have
byte-identical Timeline scene content and byte-identical bound image
content: the second project's render must be a byte-for-byte copy of the
first's, and `render_timeline` (the real, slow ffmpeg encode) must be
invoked exactly ONCE across both - proving the second render was actually
served from the cache, not just "also happened to produce the same
bytes" by re-encoding twice.
"""

import hashlib
import uuid as uuid_module

import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.asset import AssetModel
from app.models.render import RenderModel
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
from app.workflow.steps import render as render_module
from app.workflow.steps.render import render_video

_RENDER_SETTINGS = RenderSettings(
    width=320,
    height=240,
    fps=24,
    pixel_format="yuv420p",
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


async def _make_project() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("fingerprint-cache-test")
        return project.id


async def _seed_single_shot_timeline(project_id: str, *, image_bytes: bytes) -> int:
    """One static shot, no narration, no music - the simplest possible
    render, bound to a real image asset whose CONTENT (not path) is
    `image_bytes`. Returns the approved timeline's version."""
    image_dir = settings.storage_root / project_id / "assets"
    image_dir.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(image_bytes).hexdigest()
    # Deliberately a project-specific path (never shared across projects,
    # matching how `_resolved_path_and_hash`/`compute_render_fingerprint`
    # are documented to work: content identity is the hash, never the
    # path) - the point of this test is that two DIFFERENT files with the
    # SAME bytes still cache-hit.
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
            # Deliberately NOT narration - keeps `_resolve_narration_audio`
            # returning `None` with no narration rows to seed, so this
            # test's only variable is the fingerprint cache itself.
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

        binding = ShotBindingModel(
            project_id=uuid_module.UUID(project_id),
            timeline_version=appended.version,
            shot_id="sh_00",
            state="resolved",
            asset_id=asset.id,
        )
        session.add(binding)
        await session.commit()

    return appended.version


@pytest_asyncio.fixture
async def two_projects_same_content() -> tuple[str, str]:
    """Two independently-created projects whose Timeline scene content and
    bound image bytes are identical, but whose ids/paths are not - the
    only way a fingerprint cache hit can be told apart from "would have
    produced the same output anyway"."""
    image_bytes = _png_bytes((15, 25, 35))
    project_a = await _make_project()
    project_b = await _make_project()
    await _seed_single_shot_timeline(project_a, image_bytes=image_bytes)
    await _seed_single_shot_timeline(project_b, image_bytes=image_bytes)
    return project_a, project_b


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color=color).save(buf, format="PNG")
    return buf.getvalue()


async def test_second_project_reuses_the_first_render_byte_for_byte(
    two_projects_same_content, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)
    project_a, project_b = two_projects_same_content

    call_count = 0
    real_render_timeline = render_module.render_timeline

    async def _counting_render_timeline(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await real_render_timeline(*args, **kwargs)

    monkeypatch.setattr(render_module, "render_timeline", _counting_render_timeline)

    async with async_session_factory() as session:
        timeline_a = await TimelineService(session).get_active(project_a)
        output_a = await render_video(
            _make_ctx(project_a, session), timeline_a, _RENDER_SETTINGS, output_filename="final.mp4"
        )
        await session.commit()

    assert call_count == 1  # the real encode happened, for real, exactly once so far

    async with async_session_factory() as session:
        timeline_b = await TimelineService(session).get_active(project_b)
        output_b = await render_video(
            _make_ctx(project_b, session), timeline_b, _RENDER_SETTINGS, output_filename="final.mp4"
        )
        await session.commit()

    # The core proof: project B's render never re-invoked the real encoder
    # at all - it was served entirely from project A's completed `render`
    # row, copied into project B's own path.
    assert call_count == 1

    assert output_a != output_b  # each project keeps its own independent file...
    assert output_a.read_bytes() == output_b.read_bytes()  # ...but byte-identical content
    assert output_a.exists() and output_b.exists()  # never a live cross-project reference

    async with async_session_factory() as session:
        # Both projects recorded their OWN completed `render` row (the
        # cache hit still inserts a row for project B, pointing at its own
        # copied file - see `render_video`'s docstring on why
        # `insert_completed` runs unconditionally after either branch) and
        # the two rows share one fingerprint, proving the reuse above
        # wasn't a coincidence of two independent encodes landing on
        # identical bytes.
        result = await session.execute(select(RenderModel))
        rows = list(result.scalars().all())

    assert len(rows) == 2
    fingerprints = {row.fingerprint for row in rows}
    assert len(fingerprints) == 1  # one shared fingerprint across both projects' rows
    output_paths = {row.output_path for row in rows}
    assert output_paths == {str(output_a), str(output_b)}
