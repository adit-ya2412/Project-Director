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

R2 (2026-08-16) adds the mirror-image proof: the SAME project, rendered
twice with every real input held constant except `music_bed_gain_db`,
must NOT cache-hit the second time - see
`test_changing_only_the_bed_gain_forces_a_real_rerender` below.
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
    MusicPlan,
    MusicTrackSelection,
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

from .test_narration_audio_concat import _make_sine_mp3

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


async def _seed_single_shot_timeline_with_music(
    project_id: str, *, image_bytes: bytes, music_path
) -> int:
    """Same shape as `_seed_single_shot_timeline` above, plus a real,
    selected `music_plan` pointing at a real (locally-synthesised, see
    `_make_sine_mp3`) MP3 on disk at the exact path
    `RenderStep._resolve_music_track` expects
    (`storage/{project}/music/{content_hash}.mp3`, D3) - needed so a
    gain-only change actually reaches `mux_music` at all; the OTHER
    project-A/project-B tests in this file deliberately have no music, so
    they cannot exercise R2's fix even by accident."""
    content_hash = hashlib.sha256(music_path.read_bytes()).hexdigest()
    music_dir = settings.storage_root / project_id / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    (music_dir / f"{content_hash}.mp3").write_bytes(music_path.read_bytes())

    image_dir = settings.storage_root / project_id / "assets"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    image_path = image_dir / f"{image_hash}.png"
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
            base.music_plan = MusicPlan(
                selected_track=MusicTrackSelection(
                    provider="test-fixture",
                    track_id="t1",
                    source_url="https://example.com/t1",
                    licence="cc0",
                    content_hash=content_hash,
                ),
                selection_attempted=True,
            )
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata", "music_plan"}),
        )
        await service.approve(project_id, appended.version)

        asset = AssetModel(
            project_id=uuid_module.UUID(project_id),
            provider="test-fixture",
            type="image",
            local_path=str(image_path),
            licence="cc0",
            content_hash=image_hash,
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


async def test_changing_only_the_bed_gain_forces_a_real_rerender(monkeypatch, tmp_path):
    """R2: `music_bed_gain_db`/`music_duck_gain_db` are read from config
    at mux time, never from the Timeline - proven here against the real
    pipeline (not just the pure `compute_render_fingerprint` unit tests):
    one project, one timeline, one bound image, one music track, rendered
    TWICE with only `settings.music_bed_gain_db` differing between the
    two calls. Before this fix, the second call would have cache-HIT the
    first's fingerprint and silently returned the first (quieter) render;
    it must instead record a genuinely different fingerprint and
    genuinely re-invoke the real encoder."""
    monkeypatch.setattr(settings, "dry_run", False)

    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 2.0)

    project_id = await _make_project()
    await _seed_single_shot_timeline_with_music(
        project_id, image_bytes=_png_bytes((40, 50, 60)), music_path=music_path
    )

    call_count = 0
    real_render_timeline = render_module.render_timeline

    async def _counting_render_timeline(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await real_render_timeline(*args, **kwargs)

    monkeypatch.setattr(render_module, "render_timeline", _counting_render_timeline)

    monkeypatch.setattr(settings, "music_bed_gain_db", -14.0)
    monkeypatch.setattr(settings, "music_duck_gain_db", -20.0)
    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
        await render_video(
            _make_ctx(project_id, session), timeline, _RENDER_SETTINGS, output_filename="final.mp4"
        )
        await session.commit()

    assert call_count == 1

    # ONLY the bed gain changes - same project, same timeline version,
    # same image, same music track, same everything else.
    monkeypatch.setattr(settings, "music_bed_gain_db", -8.0)
    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
        await render_video(
            _make_ctx(project_id, session), timeline, _RENDER_SETTINGS, output_filename="final.mp4"
        )
        await session.commit()

    # The real proof: a second real encode happened - a cache HIT would
    # have left this at 1, having just copied the first render's bytes.
    assert call_count == 2

    async with async_session_factory() as session:
        result = await session.execute(
            select(RenderModel).where(RenderModel.project_id == uuid_module.UUID(project_id))
        )
        rows = list(result.scalars().all())

    assert len(rows) == 2
    fingerprints = {row.fingerprint for row in rows}
    assert len(fingerprints) == 2  # the gain-only change produced a genuinely different fingerprint
