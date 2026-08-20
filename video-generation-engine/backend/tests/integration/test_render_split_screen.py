"""Split-screen against real ffmpeg: two stills become one stacked frame."""

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.renderer.slideshow import RenderSettings, render_timeline
from app.schemas.timeline import (
    Camera,
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

    if isinstance(shots, Shot):
        shots = [shots]
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


def _extract_frame(video: Path, dest: Path) -> None:
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(video),
            "-vframes",
            "1",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )


def _split_shot() -> Shot:
    return Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=1.5,
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
        prompt="top subject",
        secondary_prompt="bottom subject",
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )


async def test_split_frame_stacks_two_stills_top_and_bottom(tmp_path: Path):
    top = tmp_path / "top.png"
    bot = tmp_path / "bot.png"
    _make_image(top, (255, 0, 0))
    _make_image(bot, (0, 0, 255))
    shot = _split_shot()
    output = tmp_path / "out.mp4"
    await render_timeline(
        _timeline([shot]),
        {"sh_01": top},
        _RENDER_SETTINGS,
        output,
        work_dir=tmp_path / "work",
        shot_secondary_images={"sh_01": bot},
    )

    probe = subprocess.run(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "stream=width,height,duration",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["width"] == 320
    assert stream["height"] == 240
    assert abs(float(stream["duration"]) - 1.5) < 0.15

    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    pixels = Image.open(frame).convert("RGB")
    # Top panel is the top half; bottom panel the bottom half.
    assert pixels.getpixel((160, 40))[0] > 200  # red
    assert pixels.getpixel((160, 200))[2] > 200  # blue


async def test_split_frame_without_a_second_still_is_a_static_shot(tmp_path: Path):
    """Documented degrade: one photograph, never a fake split of it."""
    only = tmp_path / "only.png"
    _make_image(only, (0, 255, 0))
    shot = _split_shot()
    output = tmp_path / "out.mp4"
    await render_timeline(
        _timeline([shot]),
        {"sh_01": only},
        _RENDER_SETTINGS,
        output,
        work_dir=tmp_path / "work",
    )
    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    pixels = Image.open(frame).convert("RGB")
    assert pixels.getpixel((160, 40))[1] > 200
    assert pixels.getpixel((160, 200))[1] > 200


async def test_split_shot_crossfades_with_a_neighbour(tmp_path: Path):
    """§16.6: the two-pass + xfade path, not the dedicated single-shot
    encode. One stream per shot still has to hold."""
    top = tmp_path / "top.png"
    bot = tmp_path / "bot.png"
    neighbour = tmp_path / "neighbour.png"
    _make_image(top, (255, 0, 0))
    _make_image(bot, (0, 0, 255))
    _make_image(neighbour, (0, 255, 0))
    split = _split_shot()
    split.duration_s = 1.5
    split.transition_out = Transition(type=TransitionType.DISSOLVE, duration_s=0.3)
    follow = Shot(
        id="sh_02",
        order=1,
        intent=ShotIntent.EXPLAIN,
        duration_s=1.5,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    output = tmp_path / "out.mp4"
    await render_timeline(
        _timeline([split, follow]),
        {"sh_01": top, "sh_02": neighbour},
        _RENDER_SETTINGS,
        output,
        work_dir=tmp_path / "work",
        shot_secondary_images={"sh_01": bot},
    )
    probe = subprocess.run(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    assert duration == pytest.approx(2.7, abs=0.2)

    frame = tmp_path / "frame.png"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-ss",
            "0.2",
            "-i",
            str(output),
            "-vframes",
            "1",
            str(frame),
        ],
        check=True,
        capture_output=True,
    )
    pixels = Image.open(frame).convert("RGB")
    assert pixels.getpixel((160, 40))[0] > 200
    assert pixels.getpixel((160, 200))[2] > 200
