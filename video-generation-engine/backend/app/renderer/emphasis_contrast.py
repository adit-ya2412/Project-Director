"""K4 contrast adaptation: measure the plate, choose light / dark / slab.

Treatment is code, from the measured plate — never a planner field
(retention_fast_kinetic_text.md architecture table; precedent
`sample_substrate_colour` — "never assumed"). Hue is K5; this module
does not invent hexes.

Runs at RENDER time. The approval gate requires every shot filled
before approval, so pictures do not exist when EmphasisPassStep runs
and they all do when RenderStep runs.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Literal

from PIL import Image, ImageStat, UnidentifiedImageError

from app.core.logging import get_logger
from app.renderer.compositor import OverlayCue

logger = get_logger(__name__)

Treatment = Literal["light", "dark", "slab"]

# Rec. 601. Same coefficients every call; range 0–255.
_LUMA_R = 0.299
_LUMA_G = 0.587
_LUMA_B = 0.114

# SUV hook t=3.0s / the washed-out `2025`. Named so the number appears
# in the regression test, not as a magic 216 in an assert.
SUV_T3_MEAN_LUMA = 216.0

# Bare type must earn contrast; slabs do not need to. White on luma 216
# has only 39 units to 255 and failed. Light is legal only on a DARK
# plate; dark only on a BRIGHT plate; the mid band stays slab.
# Conservative on purpose: better to pick slab too often than to ship
# another washed-out year stamp.
LIGHT_MAX_LUMA = 90.0
DARK_MIN_LUMA = 180.0

# Pivot.tsx spike layout on a 720×1280 canvas. Band is full width;
# height ≈ font + 2*pad. Scale the same way the TSX does.
_SPIKE_WIDTH = 720
_SPIKE_HEIGHT = 1280
_SPIKE_FONT = 132
_SPIKE_TOP = 380
_SPIKE_PAD = 18


def pivot_spike_box(width: int, height: int) -> tuple[int, int, int, int] | None:
    """Pixel box under the pivot band, or None if it cannot be formed.

    Mirrors compositor/src/Pivot.tsx: top and pad scale with height/1280,
    font with width/720. On the spike canvas this is (0, 380, 720, 548).
    """
    if width <= 0 or height <= 0:
        return None
    font_size = round(_SPIKE_FONT * (width / _SPIKE_WIDTH))
    top = round(_SPIKE_TOP * (height / _SPIKE_HEIGHT))
    pad = round(_SPIKE_PAD * (height / _SPIKE_HEIGHT))
    band_height = font_size + pad * 2
    y0 = max(0, min(height, top))
    y1 = max(0, min(height, top + band_height))
    if y1 <= y0:
        return None
    return (0, y0, width, y1)


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
    this style's plates swung 93→216 in one hook and bare type is the
    exception. With the policy off, light still requires a dark plate
    and dark a bright one; luma 216 cannot be light.
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


def measure_plate_luma(image_bytes: bytes | None, *, device: str) -> float | None:
    """Mean luma under the cue's box, or None if the plate cannot be read.

    Video / garbage bytes must not crash: unmeasured → slab at the chooser.
    Silent skip that then picks `light` is the 2025 bug in another costume.
    """
    if not image_bytes:
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            if width == 0 or height == 0:
                return None
            box = pivot_spike_box(width, height) if device == "pivot" else None
            return mean_luma(image_bytes, box=box)
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
    """
    resolved: list[OverlayCue] = []
    for cue in cues:
        path = shot_images.get(cue.shot_id) if cue.shot_id else None
        luma = _luma_from_path(path, device=cue.device)
        treatment = choose_treatment(
            luma,
            slab_default=slab_default,
            light_max_luma=light_max_luma,
            dark_min_luma=dark_min_luma,
        )
        resolved.append(replace(cue, treatment=treatment))
    return resolved


def _luma_from_path(path: Path | None, *, device: str) -> float | None:
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
    return measure_plate_luma(data, device=device)
