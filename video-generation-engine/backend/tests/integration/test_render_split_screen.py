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

_RED = (255, 0, 0)
_BLUE = (0, 0, 255)


def _make_clip(path: Path, color: tuple[int, int, int], *, duration_s: float, rate: int = 24) -> None:
    """A genuine, decodable, SOLID-colour h264 clip (no network, no paid
    API) - `tests/media_fixtures.py::make_real_clip`'s `testsrc` pattern
    is deliberately not solid, which makes per-pixel colour assertions
    unreliable; a plain `color=` lavfi source classifies as MOTION exactly
    the same way (ffprobe sees a real video stream with a positive
    duration) while staying as easy to sample as the STILL fixtures
    above."""
    r, g, b = color
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{r:02x}{g:02x}{b:02x}:s=640x480:d={duration_s}:r={rate}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )

_RENDER_SETTINGS = RenderSettings(
    width=240,
    height=320,
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
    assert stream["width"] == 240
    assert stream["height"] == 320
    assert abs(float(stream["duration"]) - 1.5) < 0.15

    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    pixels = Image.open(frame).convert("RGB")
    # Top panel is the top half; bottom panel the bottom half.
    assert pixels.getpixel((120, 40))[0] > 200  # red
    assert pixels.getpixel((120, 280))[2] > 200  # blue


async def test_split_panels_crop_to_fill_so_edges_are_content_not_pad(tmp_path: Path):
    """A square still into a 3:2 panel: letterbox would pad the sides;
    fill must put the photograph there instead."""
    top = tmp_path / "top.png"
    bot = tmp_path / "bot.png"
    Image.new("RGB", (200, 200), color=(255, 0, 0)).save(top, format="PNG")
    Image.new("RGB", (200, 200), color=(0, 0, 255)).save(bot, format="PNG")
    output = tmp_path / "out.mp4"
    await render_timeline(
        _timeline([_split_shot()]),
        {"sh_01": top},
        _RENDER_SETTINGS,
        output,
        work_dir=tmp_path / "work",
        shot_secondary_images={"sh_01": bot},
    )
    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    pixels = Image.open(frame).convert("RGB")
    # Left edge of each panel, well inside the half.
    assert pixels.getpixel((4, 40))[0] > 200
    assert pixels.getpixel((4, 280))[2] > 200
    assert pixels.getpixel((236, 40))[0] > 200
    assert pixels.getpixel((236, 280))[2] > 200


async def test_split_frame_without_a_second_still_is_a_static_shot(tmp_path: Path, caplog):
    """Documented degrade: one photograph, never a fake split of it. The
    degrade is no longer silent - it must log which condition failed."""
    only = tmp_path / "only.png"
    _make_image(only, (0, 255, 0))
    shot = _split_shot()
    output = tmp_path / "out.mp4"
    with caplog.at_level("WARNING"):
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
    # Static degrade letterboxes the 4:3 still into 240×320; sample the
    # fitted image, not the pad.
    assert pixels.getpixel((120, 160))[1] > 200
    warnings = [r for r in caplog.records if r.message == "render.split_frame_not_compositing"]
    assert len(warnings) == 1
    assert warnings[0].shot_id == "sh_01"
    assert warnings[0].reason == "missing_secondary_path"


async def test_split_frame_motion_plus_motion_composites_for_the_whole_duration(tmp_path: Path):
    """The actual reported bug: two VIDEO panels, both dropped to one
    full-frame panel with no error. Top is shorter than the shot (hold
    the last frame); bottom is longer (trim) - both fit-fragment branches
    exercised in one shot."""
    top = tmp_path / "top.mp4"
    bot = tmp_path / "bot.mp4"
    _make_clip(top, _RED, duration_s=1.0)
    _make_clip(bot, _BLUE, duration_s=2.5)
    shot = _split_shot()
    shot.duration_s = 1.5
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
            "format=duration",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    assert duration == pytest.approx(1.5, abs=0.15)

    for t in ("0.1", "1.3"):  # near the start, and near the end
        frame = tmp_path / f"frame_{t}.png"
        subprocess.run(
            [settings.ffmpeg_binary, "-y", "-ss", t, "-i", str(output), "-vframes", "1", str(frame)],
            check=True,
            capture_output=True,
        )
        pixels = Image.open(frame).convert("RGB")
        assert pixels.getpixel((120, 40))[0] > 200, f"top not red at t={t}"
        assert pixels.getpixel((120, 280))[2] > 200, f"bottom not blue at t={t}"


async def test_split_frame_still_plus_motion_composites(tmp_path: Path):
    """Top panel is a STILL, bottom is a real video clip."""
    top = tmp_path / "top.png"
    bot = tmp_path / "bot.mp4"
    _make_image(top, _RED)
    _make_clip(bot, _BLUE, duration_s=1.0)  # shorter than the shot -> holds
    shot = _split_shot()
    shot.duration_s = 1.5
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
            "format=duration",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(1.5, abs=0.15)

    for t in ("0.1", "1.3"):
        frame = tmp_path / f"frame_{t}.png"
        subprocess.run(
            [settings.ffmpeg_binary, "-y", "-ss", t, "-i", str(output), "-vframes", "1", str(frame)],
            check=True,
            capture_output=True,
        )
        pixels = Image.open(frame).convert("RGB")
        assert pixels.getpixel((120, 40))[0] > 200, f"top (still) not red at t={t}"
        assert pixels.getpixel((120, 280))[2] > 200, f"bottom (motion) not blue at t={t}"


async def test_split_frame_motion_plus_still_composites(tmp_path: Path):
    """Top panel is a real video clip, bottom is a STILL."""
    top = tmp_path / "top.mp4"
    bot = tmp_path / "bot.png"
    _make_clip(top, _RED, duration_s=2.5)  # longer than the shot -> trims
    _make_image(bot, _BLUE)
    shot = _split_shot()
    shot.duration_s = 1.5
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
            "format=duration",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(1.5, abs=0.15)

    for t in ("0.1", "1.3"):
        frame = tmp_path / f"frame_{t}.png"
        subprocess.run(
            [settings.ffmpeg_binary, "-y", "-ss", t, "-i", str(output), "-vframes", "1", str(frame)],
            check=True,
            capture_output=True,
        )
        pixels = Image.open(frame).convert("RGB")
        assert pixels.getpixel((120, 40))[0] > 200, f"top (motion) not red at t={t}"
        assert pixels.getpixel((120, 280))[2] > 200, f"bottom (still) not blue at t={t}"


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
    assert pixels.getpixel((120, 40))[0] > 200
    assert pixels.getpixel((120, 280))[2] > 200
