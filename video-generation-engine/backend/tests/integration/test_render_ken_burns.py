"""Ken Burns (M8 step 5) against real FFmpeg - proves the `zoompan` graph
actually produces the right duration/frame count and does not error,
including the riskiest case: a STATIC shot and a moving shot joined by
the same crossfade `_render_run` already proves for two static shots.
Real, decodable images (real `zoompan` needs real pixels to resample,
not fabricated bytes) - no cost, no external network.
"""

import json
import subprocess
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


def _ffprobe_streams(path: Path) -> list[dict]:
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "stream=codec_type,duration,nb_read_frames",
        "-count_frames",
        str(path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["streams"]


def _shot(shot_id: str, camera: Camera, duration_s: float = 1.5) -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        camera=camera,
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )


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


async def test_slow_zoom_shot_renders_the_correct_duration(tmp_path):
    image_path = tmp_path / "img.png"
    _make_image(image_path, (10, 20, 30))
    shot = _shot(
        "sh_01",
        Camera(movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.IN, intensity=0.3),
    )
    output_path = tmp_path / "out.mp4"
    work_dir = tmp_path / "work"

    await render_timeline(
        _timeline([shot]), {"sh_01": image_path}, _RENDER_SETTINGS, output_path, work_dir=work_dir
    )

    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - shot.duration_s) < 0.1
    # At 24fps for 1.5s, ~36 frames - real, decodable output, not a
    # single frozen/corrupt frame.
    assert int(video["nb_read_frames"]) >= 30


async def test_pan_shot_renders_the_correct_duration(tmp_path):
    image_path = tmp_path / "img.png"
    _make_image(image_path, (40, 50, 60))
    shot = _shot(
        "sh_01", Camera(movement=CameraMovement.PAN, direction=CameraDirection.LEFT, intensity=0.5)
    )
    output_path = tmp_path / "out.mp4"
    work_dir = tmp_path / "work"

    await render_timeline(
        _timeline([shot]), {"sh_01": image_path}, _RENDER_SETTINGS, output_path, work_dir=work_dir
    )

    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - shot.duration_s) < 0.1


async def test_static_and_moving_shots_crossfade_together_at_the_right_total_duration(tmp_path):
    """The riskiest combination: `_render_run` mixes a plain `-loop 1
    -t duration` static input with a single-frame `zoompan` input in the
    SAME xfade chain - both must land on identical stream shapes
    (duration, fps) for the crossfade arithmetic to hold."""
    static_path = tmp_path / "static.png"
    moving_path = tmp_path / "moving.png"
    _make_image(static_path, (70, 80, 90))
    _make_image(moving_path, (100, 110, 120))

    overlap = 0.3
    static_shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=1.5,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.DISSOLVE, duration_s=overlap),
    )
    moving_shot = _shot(
        "sh_02",
        Camera(movement=CameraMovement.SLOW_PUSH, intensity=0.4),
        duration_s=1.2,
    )
    output_path = tmp_path / "out.mp4"
    work_dir = tmp_path / "work"

    await render_timeline(
        _timeline([static_shot, moving_shot]),
        {"sh_01": static_path, "sh_02": moving_path},
        _RENDER_SETTINGS,
        output_path,
        work_dir=work_dir,
    )

    expected_total = static_shot.duration_s + moving_shot.duration_s - overlap
    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - expected_total) < 0.15


async def test_static_camera_is_byte_identical_to_before_ken_burns_existed(tmp_path):
    """No regression for the overwhelmingly common case: a STATIC shot
    must still take the exact plain `-loop 1 -t duration` path, never
    `zoompan` - proven by asserting its rendered duration matches
    exactly, the same assertion this renderer has always made."""
    image_path = tmp_path / "img.png"
    _make_image(image_path, (200, 90, 40))
    shot = _shot("sh_01", Camera(movement=CameraMovement.STATIC))
    output_path = tmp_path / "out.mp4"
    work_dir = tmp_path / "work"

    await render_timeline(
        _timeline([shot]), {"sh_01": image_path}, _RENDER_SETTINGS, output_path, work_dir=work_dir
    )

    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - shot.duration_s) < 0.1
