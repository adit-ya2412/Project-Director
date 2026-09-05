"""Two-layer parallax against real ffmpeg (illustrated_faceless.md
§2.2/F2a) - the composition-dispatch wiring `test_render_split_screen.py`
already proves for `split_frame`, mirrored for `parallax`.

Every shot below also carries its own resolved `shot_images[shot.id]`
(RED) distinct from both layer colours (BLUE background / GREEN
subject-on-magenta) so a test can tell, from the rendered frame alone,
whether the parallax path actually ran or whether the shot fell back to
the plain single-image path - the same "documented degrade, never a fake
composite" property `test_split_frame_without_a_second_still_is_a_static_
shot` already proves for split-screen.
"""

import json
import random
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.renderer.slideshow import RenderSettings, render_timeline
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    LayerRole,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
    Timeline,
    TimelineStatus,
    Transition,
    TransitionType,
)

_RENDER_SETTINGS = RenderSettings(
    width=240,
    height=320,
    fps=24,
    pixel_format="yuv420p",
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)

_RED = (255, 0, 0)
_BLUE = (0, 0, 255)
_GREEN = (0, 255, 0)
_MAGENTA = (255, 0, 255)


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


def _parallax_shot() -> Shot:
    return Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=1.5,
        camera=Camera(movement=CameraMovement.PARALLAX),
        prompt="a quiet room",
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
        layers=[
            ShotLayer(role=LayerRole.BACKGROUND, prompt="a quiet room"),
            ShotLayer(role=LayerRole.SUBJECT, prompt="a seated figure"),
        ],
    )


def _extract_frame(video: Path, dest: Path, *, at_s: float = 0.7) -> None:
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-ss",
            str(at_s),
            "-i",
            str(video),
            "-vframes",
            "1",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )


def _frame_has_colour(frame: Path, colour: tuple[int, int, int], *, tolerance: int = 40) -> bool:
    pixels = Image.open(frame).convert("RGB")
    width, height = pixels.size
    for x in range(0, width, 6):
        for y in range(0, height, 6):
            p = pixels.getpixel((x, y))
            if all(abs(p[i] - colour[i]) <= tolerance for i in range(3)):
                return True
    return False


def _subject_with_key_top_strip(*, key: tuple[int, int, int], subject_colour) -> Image.Image:
    """A subject plate whose TOP STRIP is `key` (so `sample_key_colour`
    samples exactly this colour, §1.5) and whose lower two-thirds is
    either `subject_colour` (a real cut-out) or also `key` (nothing to
    cut out - §4.5's "matched too much" failure)."""
    image = Image.new("RGB", (640, 480), color=key)
    if subject_colour is not None:
        for y in range(160, 420):
            for x in range(160, 480):
                image.putpixel((x, y), subject_colour)
    return image


async def test_parallax_composites_both_layers_over_the_shots_own_image(tmp_path: Path):
    background = tmp_path / "bg.png"
    subject = tmp_path / "sub.png"
    primary = tmp_path / "primary.png"
    Image.new("RGB", (640, 480), color=_BLUE).save(background, format="PNG")
    _subject_with_key_top_strip(key=_MAGENTA, subject_colour=_GREEN).save(subject, format="PNG")
    Image.new("RGB", (640, 480), color=_RED).save(primary, format="PNG")

    output = tmp_path / "out.mp4"
    await render_timeline(
        _timeline([_parallax_shot()]),
        {"sh_01": primary},
        _RENDER_SETTINGS,
        output,
        work_dir=tmp_path / "work",
        shot_layer_images={"sh_01": [background, subject]},
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

    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    # Both layers actually composited...
    assert _frame_has_colour(frame, _BLUE)
    assert _frame_has_colour(frame, _GREEN)
    # ...the key colour was removed (§4.5's own success case)...
    assert not _frame_has_colour(frame, _MAGENTA, tolerance=20)
    # ...and the shot's own single-image path was NOT what rendered.
    assert not _frame_has_colour(frame, _RED)


async def test_a_failed_key_guard_degrades_to_the_shots_own_image(tmp_path, caplog):
    """§4.5: a subject plate with nothing to cut out (the key colour
    covers the whole frame) trips `check_keyed_fraction`'s "ate the
    subject" branch. That must never kill the render - the same
    per-shot failure isolation `GenerateDiegeticSfxStep` already applies
    to one failed diegetic cue."""
    background = tmp_path / "bg.png"
    subject = tmp_path / "sub.png"
    primary = tmp_path / "primary.png"
    Image.new("RGB", (640, 480), color=_BLUE).save(background, format="PNG")
    _subject_with_key_top_strip(key=_MAGENTA, subject_colour=None).save(subject, format="PNG")
    Image.new("RGB", (640, 480), color=_RED).save(primary, format="PNG")

    output = tmp_path / "out.mp4"
    with caplog.at_level("WARNING"):
        await render_timeline(
            _timeline([_parallax_shot()]),
            {"sh_01": primary},
            _RENDER_SETTINGS,
            output,
            work_dir=tmp_path / "work",
            shot_layer_images={"sh_01": [background, subject]},
        )

    assert any(r.message == "render.parallax_guard_failed_degrading" for r in caplog.records)
    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    # Degraded to the shot's OWN single image - never a half-built
    # composite, never a killed render.
    assert _frame_has_colour(frame, _RED)
    assert not _frame_has_colour(frame, _BLUE)


def _real_looking_subject(*, width: int = 640, height: int = 480, seed: int = 7) -> Image.Image:
    """A densely-varied, photographic-style fixture - deliberately NOT a
    flat colour field, unlike every synthetic plate above. This is
    closer to what a REAL delivered illustration actually looks like
    (paper grain, halftone texture, §1.5) than a hand-picked flat colour
    is, so the §4.5 guard's ZERO-match direction (the opaque-rectangle
    bug - "the key matched nothing") is exercised here against something
    that actually resembles delivered media, per the F2b brief's own ask
    ("verify its degrade path with a real (fixture) image that keys to
    ~0%"). `random.Random(seed)` is deterministic - not a live provider
    call, no spending - so this stays a reproducible fixture, not a flaky
    one."""
    data = random.Random(seed).randbytes(width * height * 3)
    return Image.frombytes("RGB", (width, height), data)


async def test_a_zero_key_match_on_a_real_looking_image_degrades_to_the_shots_own_image(
    tmp_path, caplog
):
    """§4.5's OTHER failure direction (§1.5's own opaque-rectangle bug):
    a subject plate whose sampled top-strip key matches almost nothing
    else in the frame. Unlike the synthetic magenta plates above, this
    fixture is genuinely busy/textured - the first time this guard is
    exercised against something that looks like real delivered media
    rather than a flat colour a test author picked to key cleanly (or
    not) on purpose."""
    background = tmp_path / "bg.png"
    subject = tmp_path / "sub.png"
    primary = tmp_path / "primary.png"
    Image.new("RGB", (640, 480), color=_BLUE).save(background, format="PNG")
    _real_looking_subject().save(subject, format="PNG")
    Image.new("RGB", (640, 480), color=_RED).save(primary, format="PNG")

    output = tmp_path / "out.mp4"
    with caplog.at_level("WARNING"):
        await render_timeline(
            _timeline([_parallax_shot()]),
            {"sh_01": primary},
            _RENDER_SETTINGS,
            output,
            work_dir=tmp_path / "work",
            shot_layer_images={"sh_01": [background, subject]},
        )

    assert any(r.message == "render.parallax_guard_failed_degrading" for r in caplog.records)
    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    # Degraded to the shot's OWN single image - the busy fixture never
    # composited as a half-built parallax shot.
    assert _frame_has_colour(frame, _RED)
    assert not _frame_has_colour(frame, _BLUE)


async def test_parallax_without_resolved_layer_images_is_a_static_shot(tmp_path: Path):
    """Documented degrade, same shape as split-screen's own "without a
    second still" test: a `parallax` shot with nothing in
    `shot_layer_images` renders as its own plain single image."""
    primary = tmp_path / "primary.png"
    Image.new("RGB", (640, 480), color=_RED).save(primary, format="PNG")
    output = tmp_path / "out.mp4"
    await render_timeline(
        _timeline([_parallax_shot()]),
        {"sh_01": primary},
        _RENDER_SETTINGS,
        output,
        work_dir=tmp_path / "work",
    )
    frame = tmp_path / "frame.png"
    _extract_frame(output, frame)
    assert _frame_has_colour(frame, _RED)
