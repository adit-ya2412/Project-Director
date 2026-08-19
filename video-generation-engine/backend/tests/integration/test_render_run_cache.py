"""Per-run fingerprint cache (Track C C3 remainder §12 step 9b).

A two-run (hard-cut) timeline re-rendered in the same work dir must not
call `_render_run` again for a run whose shots and media did not change.
Editing one run's camera re-encodes only that run.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.renderer import slideshow as slideshow_mod
from app.renderer.slideshow import RenderSettings, _render_run, render_timeline
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
    Transition,
    TransitionType,
)

_RENDER_SETTINGS = RenderSettings(
    width=320,
    height=240,
    fps=24,
    pixel_format="yuv420p",
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)


def _png(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (640, 480), color=color).save(path, format="PNG")


def _cut_shot(shot_id: str, order: int, *, camera: Camera | None = None) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=0.8,
        camera=camera or Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )


def _two_run_timeline(shot_a: Shot, shot_b: Shot) -> Timeline:
    scene = Scene(
        id="sc_01",
        order=0,
        title="Scene",
        duration_s=shot_a.duration_s + shot_b.duration_s,
        shots=[shot_a, shot_b],
    )
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime.now(UTC),
        scenes=[scene],
    )


@pytest.fixture
def _count_render_run(monkeypatch):
    calls: list[str] = []
    original = _render_run

    async def _counting(run, *args, **kwargs):
        calls.append(run[0].id)
        return await original(run, *args, **kwargs)

    monkeypatch.setattr(slideshow_mod, "_render_run", _counting)
    return calls


async def test_unchanged_run_is_served_from_cache_on_second_render(tmp_path, _count_render_run):
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    _png(img_a, (10, 20, 30))
    _png(img_b, (40, 50, 60))
    work = tmp_path / "work"
    timeline = _two_run_timeline(_cut_shot("sh_a", 0), _cut_shot("sh_b", 1))
    images = {"sh_a": img_a, "sh_b": img_b}

    await render_timeline(timeline, images, _RENDER_SETTINGS, tmp_path / "1.mp4", work_dir=work)
    assert set(_count_render_run) == {"sh_a", "sh_b"}

    _count_render_run.clear()
    await render_timeline(timeline, images, _RENDER_SETTINGS, tmp_path / "2.mp4", work_dir=work)
    assert _count_render_run == []


async def test_editing_one_run_reencodes_only_that_run(tmp_path, _count_render_run):
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    _png(img_a, (10, 20, 30))
    _png(img_b, (40, 50, 60))
    work = tmp_path / "work"
    images = {"sh_a": img_a, "sh_b": img_b}
    first = _two_run_timeline(_cut_shot("sh_a", 0), _cut_shot("sh_b", 1))
    await render_timeline(first, images, _RENDER_SETTINGS, tmp_path / "1.mp4", work_dir=work)
    _count_render_run.clear()

    zoomed = _cut_shot("sh_a", 0, camera=Camera(movement=CameraMovement.SLOW_ZOOM))
    edited = _two_run_timeline(zoomed, _cut_shot("sh_b", 1))
    await render_timeline(edited, images, _RENDER_SETTINGS, tmp_path / "2.mp4", work_dir=work)
    assert _count_render_run == ["sh_a"]


async def test_parallel_run_encodes_respect_the_cpu_cap(tmp_path, monkeypatch):
    """§4.3 / R-C2: two hard-cut runs encode concurrently, each still
    `-threads 1`, staging names stay run-unique."""
    import asyncio

    monkeypatch.setattr(slideshow_mod, "ffmpeg_run_concurrency", lambda: 2)
    in_flight = 0
    max_seen = 0
    original = slideshow_mod._render_run

    async def _gated(run, *args, **kwargs):
        nonlocal in_flight, max_seen
        in_flight += 1
        max_seen = max(max_seen, in_flight)
        try:
            await asyncio.sleep(0.05)
            return await original(run, *args, **kwargs)
        finally:
            in_flight -= 1

    monkeypatch.setattr(slideshow_mod, "_render_run", _gated)

    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    _png(img_a, (10, 20, 30))
    _png(img_b, (200, 10, 10))
    timeline = _two_run_timeline(_cut_shot("sh_a", 0), _cut_shot("sh_b", 1))
    await render_timeline(
        timeline,
        {"sh_a": img_a, "sh_b": img_b},
        _RENDER_SETTINGS,
        tmp_path / "out.mp4",
        work_dir=tmp_path / "work",
    )
    assert max_seen == 2
