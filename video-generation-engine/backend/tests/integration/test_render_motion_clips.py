"""`render_timeline` against a real motion-clip shot (motion_new_styles_
and_long_form_videos.md, Track A, A1/A2) - real ffmpeg, a real decodable
clip standing in for a downloaded Kling result (no network, no spend),
mirroring `test_render_ken_burns.py`'s own discipline exactly.
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.renderer.slideshow import RenderSettings, render_timeline
from app.schemas.timeline import (
    Camera,
    CameraDirection,
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


def _make_clip(path: Path, duration_s: float) -> None:
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration_s}:size=320x240:rate=24",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(args, capture_output=True, check=True)


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


def _timeline(shots: list[Shot]) -> Timeline:
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


async def test_a_too_long_clip_is_trimmed_to_the_shot_duration(tmp_path):
    clip_path = tmp_path / "clip.mp4"
    _make_clip(clip_path, duration_s=4.0)
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=2.0)
    output_path = tmp_path / "out.mp4"

    await render_timeline(
        _timeline([shot]),
        {"sh_01": clip_path},
        _RENDER_SETTINGS,
        output_path,
        work_dir=tmp_path / "work",
    )

    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - shot.duration_s) < 0.1


async def test_a_too_short_clip_holds_its_last_frame_to_the_shot_duration(tmp_path):
    """DECIDED 2026-08-18 (Q4): the clip's own last frame is held, not
    looped and not slowed - proven here by the total output duration
    matching the LONGER shot duration exactly, not the clip's own
    shorter, real length."""
    clip_path = tmp_path / "clip.mp4"
    _make_clip(clip_path, duration_s=1.5)
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    output_path = tmp_path / "out.mp4"

    await render_timeline(
        _timeline([shot]),
        {"sh_01": clip_path},
        _RENDER_SETTINGS,
        output_path,
        work_dir=tmp_path / "work",
    )

    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - shot.duration_s) < 0.1


async def test_ken_burns_never_runs_on_a_motion_clip_even_if_the_shot_requests_it(tmp_path):
    """A1's pitfall, checked directly: a shot whose `camera.movement` is
    a real Ken-Burns value must still render as plain motion, never
    `zoompan`, when its resolved media is a clip - proven by the output
    still landing on exactly the shot's duration (a `zoompan` mismatch
    would be a visible artifact, not silently wrong duration, so this
    also doubles as a "did it even run without erroring" check for the
    combination)."""
    clip_path = tmp_path / "clip.mp4"
    _make_clip(clip_path, duration_s=2.0)
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(
            movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.IN, intensity=0.5
        ),
    )
    output_path = tmp_path / "out.mp4"

    await render_timeline(
        _timeline([shot]),
        {"sh_01": clip_path},
        _RENDER_SETTINGS,
        output_path,
        work_dir=tmp_path / "work",
    )

    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - shot.duration_s) < 0.1


async def test_a_motion_clip_and_a_still_crossfade_together_at_the_right_total_duration(tmp_path):
    """The riskiest combination for A1: `_render_run` mixes a real
    decoded clip with a static `tpad` still in the SAME xfade chain -
    both must land on identical stream shapes for the crossfade
    arithmetic to hold, exactly the property
    `test_render_ken_burns.py` already proves for a still/Ken-Burns mix."""
    clip_path = tmp_path / "clip.mp4"
    still_path = tmp_path / "still.png"
    _make_clip(clip_path, duration_s=2.5)
    _make_image(still_path, (70, 80, 90))

    overlap = 0.3
    motion_shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        transition_out=Transition(type=TransitionType.DISSOLVE, duration_s=overlap),
    )
    still_shot = Shot(id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=1.5)
    output_path = tmp_path / "out.mp4"

    await render_timeline(
        _timeline([motion_shot, still_shot]),
        {"sh_01": clip_path, "sh_02": still_path},
        _RENDER_SETTINGS,
        output_path,
        work_dir=tmp_path / "work",
    )

    expected_total = motion_shot.duration_s + still_shot.duration_s - overlap
    streams = _ffprobe_streams(output_path)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert abs(float(video["duration"]) - expected_total) < 0.15
