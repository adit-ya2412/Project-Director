"""K4 contrast adaptation. Pure — no DB, no ffmpeg, no Chromium."""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.renderer.compositor import OverlayCue
from app.renderer.emphasis_contrast import (
    DARK_MIN_LUMA,
    LIGHT_MAX_LUMA,
    SUV_T3_MEAN_LUMA,
    apply_emphasis_treatments,
    choose_treatment,
    mean_luma,
    measure_plate_luma,
    pivot_spike_box,
)


def _png(width: int, height: int, colour=(10, 20, 30)) -> bytes:
    image = Image.new("RGB", (width, height), color=colour)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _overlay(*, shot_id: str = "sh_01", treatment: str = "slab") -> OverlayCue:
    return OverlayCue(
        device="pivot",
        text="लेकिन",
        text_register="hi",
        offset_s=0.4,
        start_frame=12,
        end_frame=39,
        shot_id=shot_id,
        treatment=treatment,
    )


def test_suv_t3_luma_216_is_never_light():
    """The 2025 / t=3.0s regression: mean luma 216 must not pick
    light-on-transparent. That exact frame is the named failure."""
    grey = int(SUV_T3_MEAN_LUMA)
    data = _png(64, 64, (grey, grey, grey))
    luma = mean_luma(data)
    assert abs(luma - SUV_T3_MEAN_LUMA) <= 1
    assert choose_treatment(luma, slab_default=False) != "light"
    assert choose_treatment(SUV_T3_MEAN_LUMA, slab_default=False) != "light"
    assert choose_treatment(SUV_T3_MEAN_LUMA, slab_default=False) == "dark"
    assert choose_treatment(SUV_T3_MEAN_LUMA, slab_default=True) == "slab"


def test_slab_default_and_floors_on_dark_bright_mid():
    assert choose_treatment(40.0, slab_default=False) == "light"
    assert choose_treatment(40.0, slab_default=True) == "slab"
    assert choose_treatment(255.0, slab_default=False) == "dark"
    assert choose_treatment(128.0, slab_default=False) == "slab"
    assert choose_treatment(LIGHT_MAX_LUMA, slab_default=False) == "light"
    assert choose_treatment(DARK_MIN_LUMA, slab_default=False) == "dark"
    # Just inside the mid band: neither bare type has earned contrast.
    assert choose_treatment(LIGHT_MAX_LUMA + 1, slab_default=False) == "slab"
    assert choose_treatment(DARK_MIN_LUMA - 1, slab_default=False) == "slab"


def test_unmeasured_is_slab_never_light():
    assert choose_treatment(None, slab_default=False) == "slab"
    assert choose_treatment(None, slab_default=True) == "slab"
    assert measure_plate_luma(None, device="pivot") is None
    assert measure_plate_luma(b"", device="pivot") is None
    assert measure_plate_luma(b"not-an-image", device="pivot") is None


def test_empty_image_raises_rather_than_guessing():
    """A guessed luma on empty input is how unmeasured became `light`."""
    with pytest.raises(ValueError, match="empty"):
        mean_luma(b"")


def test_local_box_not_frame_mean():
    """The 2025 type sat on the bright centre; the bottom of that same
    frame is a dark infographic. Treatment must follow the cue box."""
    width, height = 720, 1280
    box = pivot_spike_box(width, height)
    assert box == (0, 380, 720, 548)
    x0, y0, x1, y1 = box

    bright_frame_dark_box = Image.new("RGB", (width, height), color=(255, 255, 255))
    ImageDraw.Draw(bright_frame_dark_box).rectangle(
        (x0, y0, x1 - 1, y1 - 1), fill=(40, 40, 40)
    )
    buffer = io.BytesIO()
    bright_frame_dark_box.save(buffer, format="PNG")
    dark_box_bytes = buffer.getvalue()

    frame_luma = mean_luma(dark_box_bytes)
    box_luma = mean_luma(dark_box_bytes, box=box)
    assert frame_luma > 200
    assert abs(box_luma - 40) <= 1
    assert choose_treatment(frame_luma, slab_default=False) == "dark"
    assert choose_treatment(box_luma, slab_default=False) == "light"
    assert measure_plate_luma(dark_box_bytes, device="pivot") == pytest.approx(box_luma)

    dark_frame_bright_box = Image.new("RGB", (width, height), color=(40, 40, 40))
    ImageDraw.Draw(dark_frame_bright_box).rectangle(
        (x0, y0, x1 - 1, y1 - 1), fill=(216, 216, 216)
    )
    buffer = io.BytesIO()
    dark_frame_bright_box.save(buffer, format="PNG")
    bright_box_bytes = buffer.getvalue()
    box_luma_bright = mean_luma(bright_box_bytes, box=box)
    assert abs(box_luma_bright - SUV_T3_MEAN_LUMA) <= 1
    assert choose_treatment(box_luma_bright, slab_default=False) != "light"
    assert choose_treatment(mean_luma(bright_box_bytes), slab_default=False) == "light"


def test_apply_follows_the_box_and_defaults_missing_plates_to_slab(tmp_path: Path):
    width, height = 720, 1280
    x0, y0, x1, y1 = pivot_spike_box(width, height)
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(40, 40, 40))
    plate = tmp_path / "sh_01.png"
    image.save(plate, format="PNG")

    cues = [_overlay(shot_id="sh_01", treatment="slab")]
    earned = apply_emphasis_treatments(cues, {"sh_01": plate}, slab_default=False)
    assert earned[0].treatment == "light"
    retained = apply_emphasis_treatments(cues, {"sh_01": plate}, slab_default=True)
    assert retained[0].treatment == "slab"

    missing = apply_emphasis_treatments(cues, {}, slab_default=False)
    assert missing[0].treatment == "slab"

    video = tmp_path / "sh_01.mp4"
    video.write_bytes(b"not-a-still")
    unreadable = apply_emphasis_treatments(cues, {"sh_01": video}, slab_default=False)
    assert unreadable[0].treatment == "slab"


def test_uniform_216_plate_via_apply_is_not_light(tmp_path: Path):
    grey = int(SUV_T3_MEAN_LUMA)
    plate = tmp_path / "t3.png"
    plate.write_bytes(_png(720, 1280, (grey, grey, grey)))
    cues = [_overlay()]
    out = apply_emphasis_treatments(cues, {"sh_01": plate}, slab_default=False)
    assert out[0].treatment != "light"
    slaby = apply_emphasis_treatments(cues, {"sh_01": plate}, slab_default=True)
    assert slaby[0].treatment == "slab"


def test_mean_luma_and_treatment_are_deterministic():
    data = _png(32, 32, (216, 216, 216))
    assert mean_luma(data) == mean_luma(data)
    luma = mean_luma(data)
    assert choose_treatment(luma, slab_default=False) == choose_treatment(
        luma, slab_default=False
    )


def test_suv_fail_2025_png_is_never_light_when_present():
    """Local-only regression file. CI must not need tmp/."""
    path = (
        Path(__file__).resolve().parents[4] / "tmp" / "suv_test" / "fail_2025.png"
    )
    if not path.exists():
        pytest.skip("tmp/suv_test/fail_2025.png is local-only")
    luma = mean_luma(path.read_bytes())
    assert choose_treatment(luma, slab_default=False) != "light"
    assert choose_treatment(luma, slab_default=True) == "slab"
