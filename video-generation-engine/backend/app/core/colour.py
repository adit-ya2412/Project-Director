"""Rec. 601 luma — ONE implementation, for every caller that needs it.

Split out of `app/renderer/emphasis_contrast.py` (2026-09-09, K5 review
finding) the moment a SECOND caller appeared. That module measures the
mean luma of a decoded plate; `EmphasisPalette` in
`app/schemas/timeline.py` needs the luma of a single authored hex. Both
are the same Rec. 601 weighted sum, and two copies of it that can
disagree is exactly the drift RV2 / R1 exist to stop — the K4 review's
finding 3 (the band geometry mirrored by hand in Python and in the TSX)
was the same failure in another costume.

Why here rather than in the renderer: `app/schemas/timeline.py` cannot
import `app.renderer.emphasis_contrast` at all. That module imports
`app.renderer.compositor`, which imports `app.schemas.timeline` — the
import cycle raises at load time, not subtly. `app/core` is the layer
schemas is already allowed to depend on (`app/schemas/project.py`
imports `app.core.clock` and `app.core.ids`), and nothing in `app/core`
imports schemas or the renderer.

Rec. 601 and not WCAG relative luminance: this is the vocabulary the
project already speaks — `LIGHT_MAX_LUMA`, `DARK_MIN_LUMA`,
`SUV_T3_MEAN_LUMA` and every logged `emphasis_contrast.treatment` line
are all in this 0–255 scale, and a threshold in a second scale would be
uncomparable to all of them. Where the two metrics disagree matters and
is recorded at the one threshold that was derived from WCAG — see
`PIVOT_GROUND_MAX_LUMA` in `app/schemas/timeline.py`.
"""

from __future__ import annotations

import re

# Rec. 601. Same coefficients every call; range 0–255.
LUMA_R = 0.299
LUMA_G = 0.587
LUMA_B = 0.114

_HEX_RRGGBB = re.compile(r"^#[0-9A-Fa-f]{6}$")


def rec601_luma(r: float, g: float, b: float) -> float:
    """Rec. 601 luma of one RGB triple, in 0–255.

    Floats accepted because `ImageStat.Stat(...).mean` hands per-channel
    MEANS, not integers. A single hex colour goes through `hex_luma`.
    """
    return LUMA_R * r + LUMA_G * g + LUMA_B * b


def hex_luma(value: str) -> float:
    """Rec. 601 luma of a `#RRGGBB` string, in 0–255.

    Raises on anything that is not `#RRGGBB`: a guessed number here
    would become "legible" the same way an unmeasured plate became
    `light` in the 2025 bug. Callers that have their own hex validation
    (`EmphasisPalette`) run it first, so this raise is a backstop.
    """
    if not _HEX_RRGGBB.fullmatch(value):
        raise ValueError(f"not a #RRGGBB hex colour: {value!r}")
    return rec601_luma(
        int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    )
