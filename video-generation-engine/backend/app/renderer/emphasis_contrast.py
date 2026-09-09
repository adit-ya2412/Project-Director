"""K4 contrast adaptation: measure the plate, choose light / dark / slab.

Treatment is code, from the measured plate — never a planner field
(retention_fast_kinetic_text.md architecture table; precedent
`sample_substrate_colour` — "never assumed"). Hue is K5; this module
does not invent hexes.

Runs at RENDER time. The approval gate requires every shot filled
before approval, so pictures do not exist when EmphasisPassStep runs
and they all do when RenderStep runs.

**Where the box comes from (review finding 3, 2026-09-09).** This module
used to carry its own copy of the pivot band's layout constants, mirrored
by hand from `compositor/src/Pivot.tsx`. Nothing tied the two copies
together, so moving the band in the TSX left this module measuring the
old rectangle and returning a treatment for a place the text is not —
silently, with no exception and no failing test. The band is now resolved
once by `pivot_band` in `app.renderer.compositor`, carried on
`OverlayCue.band`, shipped to the TSX through the props and measured from
that same object here. The rectangle measured and the rectangle drawn are
one value, not two derivations of it. See `PivotBand.as_props` for the
one place they are still allowed to differ (line-height overshoot) and
why that is deliberate.

**Why the measurement is kept even when the policy discards it (review
finding 1, 2026-09-09).** `retention_fast` sets
`emphasis_slab_default=True`, so `choose_treatment` returns `slab` for
every cue and the measured luma changes nothing about the frame. The
decode is NOT skipped, and it must not be "optimised away" later:

- The cost is nothing that matters. One PIL decode of one still is a few
  milliseconds against a render measured in minutes, and there is one
  cue per reel today.
- The numbers are the point. The slab policy is a conservative guess
  made after a 190px white `2025` washed out on a plate this module now
  measures at 236.9. Relaxing that policy — letting a `stamp` earn bare
  type on this style — needs evidence about what real plates under real
  cue boxes actually look like. `apply_emphasis_treatments` logs every
  measurement with the treatment the thresholds ALONE would have picked
  and whether the policy overrode it, so that evidence accumulates on
  every render at zero cost. Finding 2's threshold move from 90 to 105
  is exactly the kind of decision this data supports; skipping the
  decode would have left it a guess.

So a discarded value here is deliberate, and it is the cheapest
calibration data this feature will ever get.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Literal

from PIL import Image, ImageStat, UnidentifiedImageError

from app.core.logging import get_logger
from app.renderer.compositor import OverlayCue, PivotBand, pivot_band

logger = get_logger(__name__)

Treatment = Literal["light", "dark", "slab"]

# Rec. 601. Same coefficients every call; range 0–255.
_LUMA_R = 0.299
_LUMA_G = 0.587
_LUMA_B = 0.114

# SUV hook t=3.0s / the washed-out `2025`. Named so the number appears
# in the regression test, not as a magic 216 in an assert. Historical:
# it is the figure the 2026-09-08 spike session recorded for that beat.
# Re-measured 2026-09-09 through the band box on
# `tmp/suv_test/plate_nocaptions.mp4` the same frame reads 236.9 (frame
# mean 231.7), and the archived `tmp/suv_test/fail_2025.png` reads 228.8.
# The constant stays 216 because it is the number the plan, the commit
# history and the regression test all speak in, and every one of those
# values is far above `DARK_MIN_LUMA` — the classification is identical.
SUV_T3_MEAN_LUMA = 216.0

# Bare type must earn contrast; slabs do not need to. White on luma 216
# has only 39 units to 255 and failed. Light is legal only on a DARK
# plate; dark only on a BRIGHT plate; the mid band stays slab.
#
# LIGHT_MAX_LUMA was 90.0 and is 105.0 as of the 2026-09-09 review
# (finding 2). The number is otherwise arbitrary, so here is the
# measurement behind it. Six plates, taken at the six moments the
# hand-built spike put type on screen (t = 1.30, 2.20, 3.00, 4.30, 5.20,
# 5.90 on `tmp/suv_test/plate_nocaptions.mp4`, 720x1280), each measured
# through the pivot band box (0, 380, 720, 548):
#
#     98.3   108.6   236.9   190.1   159.8   132.2
#
# - At box luma **98.3** bare white type was rendered, inspected, and it
#   READ WELL. That is a measured good case, and the old 90.0 threshold
#   excluded it.
# - At box luma **236.9** bare white type WASHED OUT. That is the failure
#   this whole feature exists to prevent; 105.0 still classifies it
#   `dark`, with 132 units of clearance.
# - The next plate above the good case is **108.6**, and bare type there
#   was never tested — the spike drew a dark slab at that moment. So
#   105.0 admits the one proven-good case with ~7 units of margin and
#   stops below the nearest unproven one.
#
# Worth stating because it changes how much the old number was worth: at
# 90.0, `light` never fired on ANY plate in the reference reel. The
# branch had zero coverage in real data — only in synthetic test
# fixtures — so the threshold was never a measured floor, just a
# cautious one.
#
# DARK_MIN_LUMA stays at 180.0: 190.1 is the only reference plate above
# it, dark type there was never inspected either, and unlike the light
# side there is no measured good case asking for the boundary to move.
#
# Still conservative on purpose. Better to pick slab too often than to
# ship another washed-out year stamp.
LIGHT_MAX_LUMA = 105.0
DARK_MIN_LUMA = 180.0


def pivot_band_box(
    image_width: int,
    image_height: int,
    *,
    band: PivotBand | None = None,
) -> tuple[int, int, int, int] | None:
    """The rectangle to measure on an image `image_width`x`image_height`.

    Pass the cue's own `band` — that is the production path, and it is
    what makes the measured region the drawn region. With `band=None`
    the image is treated as its own canvas, which is the diagnostic path
    (a bare frame extracted with ffmpeg, or a unit-test fixture) and the
    only reason this argument is optional.
    """
    resolved = band if band is not None else pivot_band(image_width, image_height)
    if resolved is None:
        return None
    return resolved.box_on(image_width, image_height)


def _mean_luma_of_image(
    image: Image.Image, box: tuple[int, int, int, int] | None
) -> float:
    """Rec. 601 mean luma of an ALREADY-DECODED image, in 0–255.

    Split out for review finding 4: `measure_plate_luma` used to open and
    convert the bytes to learn the image's size and then call
    `mean_luma`, which opened and converted the very same bytes again —
    two full decodes of every plate on every render. Both callers now
    decode once and hand the open image here. Behaviour is byte-for-byte
    the same, including which conditions raise.
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width == 0 or height == 0:
        raise ValueError("image has zero width or height; cannot measure luma")
    region = rgb
    if box is not None:
        x0, y0, x1, y1 = box
        x0 = max(0, min(width, int(x0)))
        y0 = max(0, min(height, int(y0)))
        x1 = max(0, min(width, int(x1)))
        y1 = max(0, min(height, int(y1)))
        if x1 > x0 and y1 > y0:
            region = rgb.crop((x0, y0, x1, y1))
    cropped_w, cropped_h = region.size
    if cropped_w == 0 or cropped_h == 0:
        raise ValueError("image region has zero width or height; cannot measure luma")
    channels = ImageStat.Stat(region).mean
    r, g, b = channels[0], channels[1], channels[2]
    return _LUMA_R * r + _LUMA_G * g + _LUMA_B * b


def mean_luma(
    image_bytes: bytes, box: tuple[int, int, int, int] | None = None
) -> float:
    """Rec. 601 mean luma in 0–255. `box` is (x0, y0, x1, y1) pixel coords.

    Empty / zero-size image raises — a guessed number would become
    `light` the same way an unmeasured 2025 plate did. An unusable box
    falls back to the frame mean (the plan's v1 rule).
    """
    if not image_bytes:
        raise ValueError("image bytes are empty; cannot measure luma")
    with Image.open(io.BytesIO(image_bytes)) as image:
        return _mean_luma_of_image(image, box)


def choose_treatment(
    luma: float | None,
    *,
    slab_default: bool,
    light_max_luma: float = LIGHT_MAX_LUMA,
    dark_min_luma: float = DARK_MIN_LUMA,
) -> Treatment:
    """Pick light / dark / slab from measured luma.

    Unmeasured (`None`) is always slab — never light. `slab_default=True`
    (retention_fast) is always slab even when dark/light would be legal:
    this style's plates swung 93→236 in one hook and bare type is the
    exception. With the policy off, light still requires a dark plate
    and dark a bright one; luma 216 cannot be light.

    The `slab_default` short-circuit means `luma` is measured and then
    unused for every cue this style currently emits. That is on purpose
    and it is not a candidate for optimisation — see the module
    docstring's finding-1 note. The measured value is not thrown away
    either: `apply_emphasis_treatments` logs it, alongside the treatment
    this function would have returned with the policy off, precisely so
    that relaxing the policy later is an argument from data rather than
    another guess.

    Kept a pure function of its arguments (no logging in here) so the
    thresholds stay trivially testable at any luma, including the
    boundary values the tests pin.
    """
    if luma is None:
        return "slab"
    if slab_default:
        return "slab"
    if luma <= light_max_luma:
        return "light"
    if luma >= dark_min_luma:
        return "dark"
    return "slab"


def measure_plate_luma(
    image_bytes: bytes | None,
    *,
    device: str,
    band: PivotBand | None = None,
) -> float | None:
    """Mean luma under the cue's box, or None if the plate cannot be read.

    Video / garbage bytes must not crash: unmeasured → slab at the
    chooser. A silent skip that then picks `light` is the 2025 bug in
    another costume, so the two failure shapes are kept distinct on
    purpose and both are preserved exactly as they were:

    - empty bytes / `None` → `None` here, WITHOUT raising, because
      "there is no plate" is a normal render-time state (an unfilled
      shot, a placeholder);
    - unreadable or non-image bytes → `None` and one log line, again
      without raising, because a motion clip in `shot_images` must not
      fail a render;
    - `mean_luma` itself still RAISES on empty bytes, for callers that
      have asserted they hold a real image and want to hear about it.

    Do not "simplify" any of those three into each other. `None` becomes
    `slab`, which is always safe; an exception fails a render that had
    nothing wrong with it; and a default number is how bare white type
    ends up on a white frame.

    Decodes exactly once (review finding 4). Pass the cue's own `band`;
    with `band=None` the plate is treated as its own canvas, which is
    only right for diagnostics.
    """
    if not image_bytes:
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
            if width == 0 or height == 0:
                return None
            box = (
                pivot_band_box(width, height, band=band)
                if device == "pivot"
                else None
            )
            return _mean_luma_of_image(image, box)
    except (UnidentifiedImageError, OSError, ValueError):
        logger.info(
            "emphasis_contrast.unmeasured",
            extra={"device": device, "reason": "not_a_still"},
        )
        return None


def apply_emphasis_treatments(
    cues: list[OverlayCue],
    shot_images: Mapping[str, Path],
    *,
    slab_default: bool,
    light_max_luma: float = LIGHT_MAX_LUMA,
    dark_min_luma: float = DARK_MIN_LUMA,
) -> list[OverlayCue]:
    """Resolve `treatment` on each cue from its covering shot's plate.

    One pass, one list — the caller (RenderStep) hands this same list to
    the fingerprint and the compositor (RV2). Missing / unreadable /
    non-still plates are unmeasured → slab.

    Emits one `emphasis_contrast.treatment` line per cue (review finding
    1). It records the device, the measured luma or that there was none,
    the treatment chosen, the treatment the thresholds ALONE would have
    chosen, and whether the style's slab policy overrode the second into
    the first. That last field is the whole point: it turns every render
    into a data point about how often the policy is actually doing work,
    which is what a human needs before relaxing it. The measurement is
    taken whether or not the policy will use it, deliberately — see the
    module docstring.
    """
    resolved: list[OverlayCue] = []
    for cue in cues:
        path = shot_images.get(cue.shot_id) if cue.shot_id else None
        luma = _luma_from_path(path, device=cue.device, band=cue.band)
        # Computed even when `slab_default` is on, and never used to
        # decide anything — it is the "what would we have picked?"
        # column of the calibration log below.
        threshold_treatment = choose_treatment(
            luma,
            slab_default=False,
            light_max_luma=light_max_luma,
            dark_min_luma=dark_min_luma,
        )
        treatment = choose_treatment(
            luma,
            slab_default=slab_default,
            light_max_luma=light_max_luma,
            dark_min_luma=dark_min_luma,
        )
        logger.info(
            "emphasis_contrast.treatment",
            extra={
                "device": cue.device,
                "shot_id": cue.shot_id,
                "measured": luma is not None,
                # Two decimals: enough to compare plates against the
                # thresholds, not enough to pretend the crop is exact.
                "luma": round(luma, 2) if luma is not None else None,
                "treatment": treatment,
                "threshold_treatment": threshold_treatment,
                "slab_default": slab_default,
                "policy_override": treatment != threshold_treatment,
                "light_max_luma": light_max_luma,
                "dark_min_luma": dark_min_luma,
                "band_box": (
                    cue.band.box_on(cue.band.canvas_width, cue.band.canvas_height)
                    if cue.band is not None
                    else None
                ),
            },
        )
        resolved.append(replace(cue, treatment=treatment))
    return resolved


def _luma_from_path(
    path: Path | None, *, device: str, band: PivotBand | None = None
) -> float | None:
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        logger.info(
            "emphasis_contrast.unmeasured",
            extra={"path": str(path), "reason": "unreadable"},
        )
        return None
    return measure_plate_luma(data, device=device, band=band)
