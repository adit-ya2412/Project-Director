"""K4 contrast adaptation. Pure — no DB, no ffmpeg, no Chromium."""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.renderer.compositor import OverlayCue, counter_band, pivot_band, stamp_band
from app.renderer.emphasis_contrast import (
    DARK_MIN_LUMA,
    LIGHT_MAX_LUMA,
    SUV_T3_MEAN_LUMA,
    apply_emphasis_treatments,
    choose_treatment,
    mean_luma,
    measure_plate_luma,
    pivot_band_box,
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
        band=pivot_band(720, 1280),
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
    # K16.7: 128 sits under LIGHT_MAX_LUMA 175 → light (was slab at 105).
    assert choose_treatment(128.0, slab_default=False) == "light"
    assert choose_treatment(LIGHT_MAX_LUMA, slab_default=False) == "light"
    assert choose_treatment(DARK_MIN_LUMA, slab_default=False) == "dark"
    # Just inside the mid band (176 until DARK_MIN 180): still slab.
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
    box = pivot_band_box(width, height)
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
    x0, y0, x1, y1 = pivot_band_box(width, height)
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


# --------------------------------------------------------------------------
# Review finding 2 (2026-09-09): LIGHT_MAX_LUMA 90.0 -> 105.0.
# K16.7 (2026-09-10): LIGHT_MAX_LUMA 105.0 -> 175.0 (outline first).
#
# The six numbers below are the measured box luma of the six moments the
# hand-built spike put type on screen, taken through the pivot band box
# on `tmp/suv_test/plate_nocaptions.mp4` (720x1280) at t = 1.30, 2.20,
# 3.00, 4.30, 5.20, 5.90. They are asserted as literals rather than
# recomputed from the video so this stays a CI test with no `tmp/`
# fixture; `test_reference_reel_plate_luma_when_present` below checks the
# literals against the real file whenever it happens to be there.
REFERENCE_REEL_BOX_LUMA = [98.3, 108.6, 236.9, 190.1, 159.8, 132.2]

# nexon-reel4-test plate lumas from the K16.7 table (still-slabbed under
# the old 105 floor; now light under 175 with the caption outline).
REEL4_BARE_LIGHT_LUMA = (174.98, 157.49, 139.62, 116.69, 166.16, 88.48)


def test_new_light_threshold_admits_the_proven_plate_and_no_further():
    good = 98.3
    # 98.3 is the plate where bare white type was rendered, inspected,
    # and read well. The old 90.0 threshold called it slab.
    assert choose_treatment(good, slab_default=False) == "light"
    assert choose_treatment(good, slab_default=False, light_max_luma=90.0) == "slab"
    # K16.7: 108.6 is now light under 175 (was slab at 105). The outline
    # is the reason the wider floor is safe — captions already survive
    # the measured luma-175 showroom plate.
    assert choose_treatment(108.6, slab_default=False) == "light"
    assert choose_treatment(108.6, slab_default=False, light_max_luma=105.0) == "slab"
    assert LIGHT_MAX_LUMA == 175.0
    assert choose_treatment(174.98, slab_default=False) == "light"
    assert choose_treatment(LIGHT_MAX_LUMA + 1, slab_default=False) == "slab"
    # The failure the whole feature exists to prevent is still nowhere
    # near the light branch.
    assert choose_treatment(236.9, slab_default=False) == "dark"
    assert choose_treatment(216.0, slab_default=False) == "dark"
    assert choose_treatment(SUV_T3_MEAN_LUMA, slab_default=False) == "dark"
    assert DARK_MIN_LUMA == 180.0


def test_reel4_showroom_and_mid_plates_are_light_under_k16_7():
    """K16.7 table: every still-slabbed stamp/counter row under 105 is
    light once the floor is 175. Unmeasured stays slab; 216 stays dark."""
    for luma in REEL4_BARE_LIGHT_LUMA:
        assert choose_treatment(luma, slab_default=False) == "light"
    assert choose_treatment(None, slab_default=False) == "slab"
    assert choose_treatment(SUV_T3_MEAN_LUMA, slab_default=False) == "dark"
    assert choose_treatment(SUV_T3_MEAN_LUMA, slab_default=False) != "light"


def test_light_had_zero_coverage_on_real_plates_at_the_old_threshold():
    """Worth pinning because it is the argument for moving the number:
    at 90.0 not one plate in the reference reel could ever be `light`.
    At 105.0 exactly one did; at 175.0 four of the six do (the two
    washout plates stay dark)."""
    at_90 = [
        choose_treatment(v, slab_default=False, light_max_luma=90.0)
        for v in REFERENCE_REEL_BOX_LUMA
    ]
    at_105 = [
        choose_treatment(v, slab_default=False, light_max_luma=105.0)
        for v in REFERENCE_REEL_BOX_LUMA
    ]
    at_175 = [choose_treatment(v, slab_default=False) for v in REFERENCE_REEL_BOX_LUMA]
    assert at_90.count("light") == 0
    assert at_105.count("light") == 1
    assert at_175.count("light") == 4
    assert at_175.count("dark") == 2
    assert LIGHT_MAX_LUMA == 175.0


def test_reference_reel_plate_luma_when_present():
    """Local-only. Re-measures the six literals above off the real plate
    frames when they exist, so the threshold rationale cannot quietly
    stop matching the picture it was derived from."""
    frames = (
        Path(__file__).resolve().parents[4] / "tmp" / "suv_test" / "_f2review"
    )
    stamps = ["1.30", "2.20", "3.00", "4.30", "5.20", "5.90"]
    paths = [frames / f"p_{t}.png" for t in stamps]
    if not all(p.exists() for p in paths):
        pytest.skip("tmp/suv_test/_f2review frames are local-only")
    band = pivot_band(720, 1280)
    for path, expected in zip(paths, REFERENCE_REEL_BOX_LUMA, strict=True):
        measured = measure_plate_luma(path.read_bytes(), device="pivot", band=band)
        assert measured == pytest.approx(expected, abs=0.05)


# --------------------------------------------------------------------------
# Review finding 1 (2026-09-09): the measurement is kept under the slab
# policy and LOGGED, rather than skipped. The log line is the calibration
# data that lets a human relax the policy with evidence.


def test_policy_override_is_measured_and_logged(tmp_path: Path, caplog):
    """retention_fast discards the luma, so the only way the measurement
    earns its keep is by being recorded. One line per cue, carrying the
    device, the luma, the treatment, and what the thresholds alone would
    have picked."""
    width, height = 720, 1280
    x0, y0, x1, y1 = pivot_band_box(width, height)
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(40, 40, 40))
    plate = tmp_path / "sh_01.png"
    image.save(plate, format="PNG")

    with caplog.at_level("INFO"):
        out = apply_emphasis_treatments(
            [_overlay()], {"sh_01": plate}, slab_default=True
        )
    assert out[0].treatment == "slab"
    records = [r for r in caplog.records if r.message == "emphasis_contrast.treatment"]
    assert len(records) == 1
    record = records[0]
    assert record.device == "pivot"
    assert record.measured is True
    assert record.luma == pytest.approx(40.0, abs=1.0)
    assert record.treatment == "slab"
    # The whole point: the thresholds would have said `light`, and the
    # style policy is what turned it into a slab. That is now visible.
    assert record.threshold_treatment == "light"
    assert record.policy_override is True
    assert record.slab_default is True
    assert record.band_box == (0, 380, 720, 548)


def test_unmeasured_cue_is_logged_as_unmeasured_not_as_a_number(caplog):
    with caplog.at_level("INFO"):
        out = apply_emphasis_treatments([_overlay()], {}, slab_default=False)
    assert out[0].treatment == "slab"
    record = next(
        r for r in caplog.records if r.message == "emphasis_contrast.treatment"
    )
    assert record.measured is False
    assert record.luma is None
    assert record.treatment == "slab"
    # No policy in play — an unmeasured plate is slab on the thresholds
    # alone, so this is not an override and must not be logged as one.
    assert record.threshold_treatment == "slab"
    assert record.policy_override is False


def test_no_policy_means_no_override_flag(tmp_path: Path, caplog):
    grey = 200
    plate = tmp_path / "bright.png"
    plate.write_bytes(_png(720, 1280, (grey, grey, grey)))
    with caplog.at_level("INFO"):
        out = apply_emphasis_treatments(
            [_overlay()], {"sh_01": plate}, slab_default=False
        )
    assert out[0].treatment == "dark"
    record = next(
        r for r in caplog.records if r.message == "emphasis_contrast.treatment"
    )
    assert record.treatment == "dark"
    assert record.threshold_treatment == "dark"
    assert record.policy_override is False


def test_plate_is_decoded_once_per_measurement(monkeypatch):
    """Review finding 4. `measure_plate_luma` used to open and convert
    the bytes to learn the size, then call `mean_luma`, which opened and
    converted the identical bytes again."""
    opens: list[int] = []
    real_open = Image.open

    def counting_open(*args, **kwargs):
        opens.append(1)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(Image, "open", counting_open)
    data = _png(720, 1280, (40, 40, 40))
    assert measure_plate_luma(
        data, device="pivot", band=pivot_band(720, 1280)
    ) == pytest.approx(40.0, abs=1.0)
    assert len(opens) == 1


def test_unreadable_plate_still_returns_none_and_does_not_raise():
    """Error behaviour is unchanged by the single-decode restructure:
    empty bytes raise out of `mean_luma`, garbage bytes return None from
    `measure_plate_luma` (-> slab), and nothing becomes `light`."""
    with pytest.raises(ValueError, match="empty"):
        mean_luma(b"")
    assert measure_plate_luma(b"", device="pivot") is None
    assert measure_plate_luma(None, device="pivot") is None
    assert measure_plate_luma(b"\x00\x01\x02not-an-image", device="pivot") is None
    assert choose_treatment(
        measure_plate_luma(b"garbage", device="pivot"), slab_default=False
    ) == "slab"


def test_stamp_band_uses_local_box_not_frame_mean(tmp_path: Path):
    """K11: stamp with a band is measured through THAT box, not the
    pivot band and not the frame mean. Reuses the local-vs-frame-mean
    fixture shape against the stamp rectangle."""
    width, height = 720, 1280
    band = stamp_band(width, height)
    assert band is not None
    box = band.box_on(width, height)
    assert box == (0, 320, 720, 538)
    x0, y0, x1, y1 = box

    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(40, 40, 40))
    plate = tmp_path / "sh_stamp.png"
    image.save(plate, format="PNG")

    cue = OverlayCue(
        device="stamp",
        text="2025",
        text_register="en",
        offset_s=0.0,
        start_frame=0,
        end_frame=26,
        shot_id="sh_01",
        treatment="slab",
        band=band,
    )
    earned = apply_emphasis_treatments([cue], {"sh_01": plate}, slab_default=False)
    assert earned[0].treatment == "light"
    retained = apply_emphasis_treatments([cue], {"sh_01": plate}, slab_default=True)
    assert retained[0].treatment == "slab"

    data = plate.read_bytes()
    box_luma = mean_luma(data, box=box)
    frame_luma = mean_luma(data)
    assert frame_luma > 200
    assert abs(box_luma - 40) <= 1
    assert measure_plate_luma(data, device="stamp", band=band) == pytest.approx(box_luma)


def test_counter_without_a_band_uses_frame_mean():
    """No band → frame mean, a measured 54-luma loss of precision.
    Production always passes a band; this pins the fallback so it cannot
    silently start measuring the pivot box instead."""
    width, height = 720, 1280
    pivot_box = pivot_band_box(width, height)
    assert pivot_box is not None
    x0, y0, x1, y1 = pivot_box
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(40, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()

    frame_luma = mean_luma(data)
    assert frame_luma > 200
    assert measure_plate_luma(data, device="counter") == pytest.approx(frame_luma)
    assert measure_plate_luma(data, device="stamp") == pytest.approx(frame_luma)
    # Pivot without a band still uses the diagnostic pivot box.
    assert measure_plate_luma(data, device="pivot") == pytest.approx(
        mean_luma(data, box=pivot_box)
    )


def test_counter_band_uses_its_own_box_not_the_pivot_box(tmp_path: Path):
    width, height = 720, 1280
    band = counter_band(width, height)
    assert band is not None
    box = band.box_on(width, height)
    assert box == (150, 300, 570, 448)
    x0, y0, x1, y1 = box

    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(40, 40, 40))
    plate = tmp_path / "sh_counter.png"
    image.save(plate, format="PNG")

    cue = OverlayCue(
        device="counter",
        text="lakh",
        text_register="en",
        offset_s=0.0,
        start_frame=0,
        end_frame=39,
        shot_id="sh_01",
        treatment="slab",
        band=band,
    )
    earned = apply_emphasis_treatments([cue], {"sh_01": plate}, slab_default=False)
    assert earned[0].treatment == "light"
    data = plate.read_bytes()
    assert measure_plate_luma(data, device="counter", band=band) == pytest.approx(
        mean_luma(data, box=box), abs=1.0
    )


def test_hex_luma_and_plate_luma_are_one_implementation():
    """K5 review finding: the `pivot_ground` guard measures a single
    authored hex and this module measures a decoded plate. Both go
    through `app.core.colour.rec601_luma`, so a flat image of a colour
    must read exactly that colour's `hex_luma`. Two Rec.601 formulas
    that can disagree is the mirrored-band-geometry bug (finding 3) in
    another costume."""
    from app.core.colour import hex_luma

    for hex_colour, rgb in (
        ("#FF2E2E", (0xFF, 0x2E, 0x2E)),
        ("#5A00A8", (0x5A, 0x00, 0xA8)),
        ("#8C8C8C", (0x8C, 0x8C, 0x8C)),
    ):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), rgb).save(buf, "PNG")
        assert mean_luma(buf.getvalue()) == pytest.approx(hex_luma(hex_colour))

