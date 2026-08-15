"""I5 ("rendering is a pure function") DEMONSTRATED, not asserted (M8
step 6): render the exact same Timeline + images twice, independently,
and prove the output bytes are IDENTICAL - not just "the same duration"
or "no error", the actual file hash.

This calls `render_timeline` directly (the silent video pass) rather
than through `render_video`'s fingerprint cache, deliberately - a cache
hit trivially returns the same bytes by copying a file, which would
prove nothing about whether the ENCODER itself is reproducible. This
test proves the thing the cache is trusting: two from-scratch encodes of
the same inputs are byte-for-byte the same file.
"""

import hashlib
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.renderer.slideshow import RenderSettings, render_timeline
from app.schemas.timeline import (
    Camera,
    CameraDirection,
    CameraMovement,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
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


def _make_image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (640, 480), color=color).save(path, format="PNG")


def _timeline(shots: list[Shot]) -> Timeline:
    from datetime import UTC, datetime

    from app.schemas.timeline import ProducedBy, TimelineStatus

    scene = Scene(
        id="sc_01", order=0, title="Scene", duration_s=sum(s.duration_s for s in shots), shots=shots
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_static_render_is_byte_identical_across_two_independent_runs(tmp_path):
    image_path = tmp_path / "img.png"
    _make_image(image_path, (10, 20, 30))
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=1.2,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    timeline = _timeline([shot])

    out_a = tmp_path / "a.mp4"
    out_b = tmp_path / "b.mp4"
    await render_timeline(
        timeline, {"sh_01": image_path}, _RENDER_SETTINGS, out_a, work_dir=tmp_path / "work_a"
    )
    await render_timeline(
        timeline, {"sh_01": image_path}, _RENDER_SETTINGS, out_b, work_dir=tmp_path / "work_b"
    )

    assert _sha256(out_a) == _sha256(out_b)


async def test_ken_burns_render_is_byte_identical_across_two_independent_runs(tmp_path):
    """The riskier case: `zoompan`'s own frame generation must be exactly
    reproducible too, not just the plain static path."""
    image_path = tmp_path / "img.png"
    _make_image(image_path, (50, 60, 70))
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=1.5,
        camera=Camera(
            movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.IN, intensity=0.3
        ),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    timeline = _timeline([shot])

    out_a = tmp_path / "a.mp4"
    out_b = tmp_path / "b.mp4"
    await render_timeline(
        timeline, {"sh_01": image_path}, _RENDER_SETTINGS, out_a, work_dir=tmp_path / "work_a"
    )
    await render_timeline(
        timeline, {"sh_01": image_path}, _RENDER_SETTINGS, out_b, work_dir=tmp_path / "work_b"
    )

    assert _sha256(out_a) == _sha256(out_b)


async def test_multi_shot_crossfade_render_is_byte_identical_across_two_independent_runs(tmp_path):
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    _make_image(image_a, (90, 100, 110))
    _make_image(image_b, (120, 130, 140))
    shots = [
        Shot(
            id="sh_01",
            order=0,
            intent=ShotIntent.EXPLAIN,
            duration_s=1.0,
            camera=Camera(movement=CameraMovement.STATIC),
            transition_out=Transition(type=TransitionType.DISSOLVE, duration_s=0.3),
        ),
        Shot(
            id="sh_02",
            order=1,
            intent=ShotIntent.EXPLAIN,
            duration_s=1.0,
            camera=Camera(movement=CameraMovement.STATIC),
            transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
        ),
    ]
    timeline = _timeline(shots)
    shot_images = {"sh_01": image_a, "sh_02": image_b}

    out_a = tmp_path / "a.mp4"
    out_b = tmp_path / "b.mp4"
    await render_timeline(
        timeline, shot_images, _RENDER_SETTINGS, out_a, work_dir=tmp_path / "work_a"
    )
    await render_timeline(
        timeline, shot_images, _RENDER_SETTINGS, out_b, work_dir=tmp_path / "work_b"
    )

    assert _sha256(out_a) == _sha256(out_b)
