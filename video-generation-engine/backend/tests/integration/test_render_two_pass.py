"""C3 (d) two-pass: per-shot cached streams, then xfade re-chain.

A dissolve-only run is one `group_into_runs` entry, so the per-run cache
cannot help an edit. Shot-stream cache can: change a dissolve duration
and every shot file is reused; change one camera and only that shot
re-encodes.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.renderer import slideshow as slideshow_mod
from app.renderer.slideshow import RenderSettings, probe_duration_seconds, render_timeline
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
from app.timeline.duration import compute_timeline_duration

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


def _dissolve_shot(
    shot_id: str, order: int, *, overlap: float = 0.3, camera: Camera | None = None
) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=0.8,
        camera=camera or Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.DISSOLVE, duration_s=overlap),
    )


def _cut_shot(shot_id: str, order: int) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=0.8,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )


def _timeline(shots: list[Shot]) -> Timeline:
    scene = Scene(
        id="sc_01",
        order=0,
        title="Scene",
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
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


async def test_changing_dissolve_duration_does_not_reencode_shot_streams(tmp_path, monkeypatch):
    encodes: list[str] = []
    original = slideshow_mod._encode_or_reuse_shot_stream

    async def _counting(**kwargs):
        cache_dir = kwargs["work_dir"] / "shot_cache"
        before = {p.name for p in cache_dir.glob("*.mp4")} if cache_dir.exists() else set()
        result = await original(**kwargs)
        after = {p.name for p in cache_dir.glob("*.mp4")}
        if after - before:
            encodes.append(kwargs["shot"].id)
        return result

    monkeypatch.setattr(slideshow_mod, "_encode_or_reuse_shot_stream", _counting)

    imgs = {}
    for i, color in enumerate([(10, 20, 30), (40, 50, 60), (70, 80, 90)]):
        path = tmp_path / f"{i}.png"
        _png(path, color)
        imgs[f"sh_{i}"] = path

    shots = [
        _dissolve_shot("sh_0", 0, overlap=0.3),
        _dissolve_shot("sh_1", 1, overlap=0.3),
        _cut_shot("sh_2", 2),
    ]
    work = tmp_path / "work"
    await render_timeline(
        _timeline(shots), imgs, _RENDER_SETTINGS, tmp_path / "1.mp4", work_dir=work
    )
    assert set(encodes) == {"sh_0", "sh_1", "sh_2"}
    encodes.clear()

    edited = [
        _dissolve_shot("sh_0", 0, overlap=0.5),
        _dissolve_shot("sh_1", 1, overlap=0.3),
        _cut_shot("sh_2", 2),
    ]
    await render_timeline(
        _timeline(edited), imgs, _RENDER_SETTINGS, tmp_path / "2.mp4", work_dir=work
    )
    assert encodes == []


async def test_changing_one_camera_reencodes_only_that_shot_stream(tmp_path, monkeypatch):
    encodes: list[str] = []
    original = slideshow_mod._encode_or_reuse_shot_stream

    async def _counting(**kwargs):
        cache_dir = kwargs["work_dir"] / "shot_cache"
        before = {p.name for p in cache_dir.glob("*.mp4")} if cache_dir.exists() else set()
        result = await original(**kwargs)
        after = {p.name for p in cache_dir.glob("*.mp4")}
        if after - before:
            encodes.append(kwargs["shot"].id)
        return result

    monkeypatch.setattr(slideshow_mod, "_encode_or_reuse_shot_stream", _counting)

    imgs = {}
    for i, color in enumerate([(10, 20, 30), (40, 50, 60), (70, 80, 90)]):
        path = tmp_path / f"{i}.png"
        _png(path, color)
        imgs[f"sh_{i}"] = path

    shots = [
        _dissolve_shot("sh_0", 0),
        _dissolve_shot("sh_1", 1),
        _cut_shot("sh_2", 2),
    ]
    work = tmp_path / "work"
    await render_timeline(
        _timeline(shots), imgs, _RENDER_SETTINGS, tmp_path / "1.mp4", work_dir=work
    )
    encodes.clear()

    edited = [
        _dissolve_shot("sh_0", 0),
        _dissolve_shot("sh_1", 1, camera=Camera(movement=CameraMovement.SLOW_ZOOM)),
        _cut_shot("sh_2", 2),
    ]
    await render_timeline(
        _timeline(edited), imgs, _RENDER_SETTINGS, tmp_path / "2.mp4", work_dir=work
    )
    assert encodes == ["sh_1"]


@pytest.mark.parametrize(
    "movement, n_shots",
    [
        (CameraMovement.STATIC, 3),
        (CameraMovement.SLOW_ZOOM, 3),
        (CameraMovement.STATIC, 6),
        (CameraMovement.SLOW_ZOOM, 6),
    ],
)
async def test_two_pass_dissolve_duration_matches_d5(tmp_path, movement, n_shots):
    """N2 / R-C5: multi-shot dissolve through two-pass is frame-exact
    against `compute_timeline_duration`, not the mux abs=0.10 slack."""
    overlap = 0.5
    duration_s = 3.0
    shots = []
    imgs = {}
    for i in range(n_shots):
        sid = f"sh_{i}"
        path = tmp_path / f"{i}.png"
        _png(path, (10 + i * 20, 20, 30))
        imgs[sid] = path
        is_last = i == n_shots - 1
        shots.append(
            Shot(
                id=sid,
                order=i,
                intent=ShotIntent.EXPLAIN,
                duration_s=duration_s,
                camera=Camera(movement=movement),
                transition_out=Transition(
                    type=TransitionType.CUT if is_last else TransitionType.DISSOLVE,
                    duration_s=0.0 if is_last else overlap,
                ),
            )
        )
    out = tmp_path / "out.mp4"
    await render_timeline(_timeline(shots), imgs, _RENDER_SETTINGS, out, work_dir=tmp_path / "work")
    expected = compute_timeline_duration(shots)
    actual = await probe_duration_seconds(out, _RENDER_SETTINGS.ffprobe_binary)
    # R-C9: 1/fps is exactly one frame, so this would pass with the
    # R-C1 +1-frame bug present. Measured spread here is 0.0000; use
    # the audio band (5 ms) so a one-frame regression fails.
    assert actual == pytest.approx(expected, abs=0.005)
