"""Remotion as a layer producer (retention_fast_kinetic_text.md K7/K11).

One parameterized composition driven by `--props`. Cache by INPUT hash
(never output bytes) so headless Chromium's non-determinism cannot
break I5 at the assembly level. Missing Node/compositor is a
PermanentError — silently skipping would ship a reel with no kinetic
text and nothing would error.

This slice composites `pivot`, `stamp`, and `counter`. Other devices
(meter, comparison, correction, question) are ignored until they have
a renderer — collecting them here with nothing to draw would be the
silent-drop failure K11 exists to prevent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.schemas.timeline import EmphasisDevice, EmphasisPalette, Timeline
from app.timeline.duration import compute_shot_start_times, compute_timeline_duration

logger = get_logger(__name__)

# Per-device hold, pinned from the SUV spike windows (K11 work log).
# Each is still clamped to remaining shot and remaining film at collect.
# pivot  Beat 5  4.94 → 5.85  = 0.91s
# stamp  Beat 3  2.69 → 3.55  = 0.86s  (the year)
# counter Beat 4  3.60 → 4.90  = 1.30s
PIVOT_HOLD_S = 0.91
STAMP_HOLD_S = 0.86
COUNTER_HOLD_S = 1.30

COMPOSITOR_ROOT = Path(__file__).resolve().parents[3] / "compositor"
EMPHASIS_FONT_PATH = Path(__file__).resolve().parents[2] / "vendor" / "fonts" / "NotoSansDevanagari-Regular.ttf"
COMPOSITION_ID = "Emphasis"


# --------------------------------------------------------------------------
# Band geometry — ONE definition, and Python owns it.
#
# Review finding 3 (2026-09-09). These five numbers used to exist TWICE:
# as `_SPIKE_*` in `emphasis_contrast.pivot_spike_box`, which decided
# where to MEASURE the plate, and again as `SPIKE_*` inside
# `compositor/src/Pivot.tsx`, which decided where to DRAW the band.
# Nothing guarded that mirror. Move the band in the TSX and Python keeps
# measuring the old rectangle: it picks a treatment for a place the text
# is not, with no exception, no ffmpeg error and no failing test. It is
# the only failure mode in K4 that is completely silent, which is why it
# was fixed first.
#
# The fix is structural rather than a guard or a test: the band is
# resolved HERE, in canvas pixels, carried on the cue
# (`OverlayCue.band`), measured through `PivotBand.box_on` and shipped to
# the TSX through `_overlay_props` as `cue.band`. `Pivot.tsx` positions
# itself from that prop. The measured rectangle and the drawn rectangle
# are now the same numbers rather than two copies of the same arithmetic,
# so drift is impossible by construction. `Pivot.tsx` keeps the spike
# constants ONLY as a fallback for the standalone spike compositions
# (`SuvRetention.tsx`), which pass no band; that fallback is labelled as
# such in the TSX and production never reaches it.
#
# Spike origin (do not "improve" the look): `SuvRetention.tsx` Beat 5 on
# a 720x1280 canvas — font 132, top 380, vertical padding 18, full width.
# Font scales with WIDTH, top and padding with HEIGHT, exactly as the
# spike did; on the reference canvas the band is (0, 380, 720, 548).
_PIVOT_REF_WIDTH = 720
_PIVOT_REF_HEIGHT = 1280
_PIVOT_REF_FONT = 132
_PIVOT_REF_TOP = 380
_PIVOT_REF_PAD = 18


@dataclass(frozen=True)
class PivotBand:
    """Where the pivot band sits, in the pixels of the canvas it was cut for.

    Both halves of K4 read this object and nothing else: `box_on()` gives
    the rectangle to measure, `as_props()` gives the rectangle to draw.
    `canvas_width`/`canvas_height` are carried because `box_on` needs to
    know what the band's pixels are a fraction OF.
    """

    canvas_width: int
    canvas_height: int
    left: int
    top: int
    width: int
    height: int
    font_size: int
    pad: int

    def as_props(self) -> dict[str, int]:
        """The props contract consumed by `Pivot.tsx`.

        camelCase to match every other key in `_overlay_props`; the TSX
        reads these verbatim and computes no layout of its own.

        `height` is deliberately NOT in here, and that is the one place
        this contract is not literally one number. The band's drawn
        height comes out of `fontSize`, `pad` and the CSS line-height
        (1.1, for Devanagari matras above the shirorekha), so it is
        ~13px taller on the reference canvas than the nominal
        `font + 2*pad` this class reports as `height`. Two reasons the
        nominal number stays the measured one rather than being
        reconciled:

        1. It is the box the six reference-reel luma measurements were
           taken through, and `LIGHT_MAX_LUMA = 105` is justified by
           two of them (98.3 good, 108.6 untested). Widening the box to
           the drawn height moves those to 100.6 and 103.3, which would
           put the threshold ABOVE the untested plate and silently undo
           the rationale in `emphasis_contrast`.
        2. Forcing the drawn band down to 168px means an explicit
           height and re-centred type — a change to a look the plan
           says twice not to change.

        So: `top`/`left`/`width`/`fontSize`/`pad` are the single source
        of truth and cannot drift. The residual ~8% height difference is
        known, bounded, and on the safe side (the measured slice sits
        inside the drawn band).
        """
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "fontSize": self.font_size,
            "pad": self.pad,
        }

    def hash_payload(self) -> dict[str, int]:
        """What the fingerprint and the overlay cache hash.

        The canvas is already hashed separately, but the band is not a
        pure function of it forever: the five module constants above are
        CODE, and moving the band by editing them must invalidate both
        the overlay `.mov` and the cached `final.mp4`. Without this the
        plan's own fingerprint warning applies — the render step would
        serve a cached video whose band sits in the old place and
        nothing would error.
        """
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "font_size": self.font_size,
            "pad": self.pad,
        }

    def box_on(self, width: int, height: int) -> tuple[int, int, int, int] | None:
        """`(x0, y0, x1, y1)` for this band projected onto a `width`x`height` image.

        K4 measures `shot_images`, which holds the RAW resolved asset —
        frequently 1920x1080 — not a canvas-sized frame; the crop into
        720x1280 happens later inside ffmpeg. So the band is mapped by
        its fraction of the canvas rather than recomputed from the
        asset's own dimensions. Recomputing was subtly wrong on any
        asset whose aspect differs from the canvas: font (and therefore
        band height) scales with WIDTH while top scales with HEIGHT, so
        on a 1920x1080 asset the old code measured a band 0.35 of the
        picture tall where the drawn one covers 0.13.

        Still an approximation, and deliberately left as one: a
        ken-burns crop decides which of the asset's pixels actually land
        under the band, and knowing that exactly means extracting the
        rendered frame. That is a bigger change than this review, and
        the fractional map is strictly closer than what it replaces.
        """
        if width <= 0 or height <= 0:
            return None
        if self.canvas_width <= 0 or self.canvas_height <= 0:
            return None
        scale_x = width / self.canvas_width
        scale_y = height / self.canvas_height
        x0 = max(0, min(width, round(self.left * scale_x)))
        x1 = max(0, min(width, round((self.left + self.width) * scale_x)))
        y0 = max(0, min(height, round(self.top * scale_y)))
        y1 = max(0, min(height, round((self.top + self.height) * scale_y)))
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1, y1)


def pivot_band(canvas_width: int, canvas_height: int) -> PivotBand | None:
    """Resolve the pivot band for a canvas, or None if it cannot be formed.

    The single source of truth described in the block comment above. On
    the 720x1280 reference canvas this is top 380, height 168
    (font 132 + 2*pad 18), full width — i.e. the box (0, 380, 720, 548)
    that K4's regression tests pin.
    """
    if canvas_width <= 0 or canvas_height <= 0:
        return None
    font_size = round(_PIVOT_REF_FONT * (canvas_width / _PIVOT_REF_WIDTH))
    top = round(_PIVOT_REF_TOP * (canvas_height / _PIVOT_REF_HEIGHT))
    pad = round(_PIVOT_REF_PAD * (canvas_height / _PIVOT_REF_HEIGHT))
    band_height = font_size + pad * 2
    y0 = max(0, min(canvas_height, top))
    y1 = max(0, min(canvas_height, top + band_height))
    if y1 <= y0:
        return None
    return PivotBand(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        left=0,
        top=y0,
        width=canvas_width,
        height=y1 - y0,
        font_size=font_size,
        pad=pad,
    )


# Stamp geometry — SUV spike Beat 3 (Year) on 720x1280: top 320, font 190,
# full width. Same scale rules as pivot (font with width, top/pad with
# height). Pad is the slab inset; the spike Year was bare type, but
# retention_fast's slab default needs a rectangle to draw and K4 needs
# the same rectangle to measure. Finding 3: this is the only copy.
_STAMP_REF_WIDTH = 720
_STAMP_REF_HEIGHT = 1280
_STAMP_REF_FONT = 190
_STAMP_REF_TOP = 320
_STAMP_REF_PAD = 14


def stamp_band(canvas_width: int, canvas_height: int) -> PivotBand | None:
    """Resolve the stamp box for a canvas, or None if it cannot be formed.

    Reference: (0, 320, 720, 538) on 720x1280 — font 190 + 2*pad 14.
    Full width so K4 measures the vertical strip the type actually sits
    in; the TSX may shrink the ink slab to the word.
    """
    if canvas_width <= 0 or canvas_height <= 0:
        return None
    font_size = round(_STAMP_REF_FONT * (canvas_width / _STAMP_REF_WIDTH))
    top = round(_STAMP_REF_TOP * (canvas_height / _STAMP_REF_HEIGHT))
    pad = round(_STAMP_REF_PAD * (canvas_height / _STAMP_REF_HEIGHT))
    band_height = font_size + pad * 2
    y0 = max(0, min(canvas_height, top))
    y1 = max(0, min(canvas_height, top + band_height))
    if y1 <= y0:
        return None
    return PivotBand(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        left=0,
        top=y0,
        width=canvas_width,
        height=y1 - y0,
        font_size=font_size,
        pad=pad,
    )


# Counter geometry — SUV spike Beat 4 on 720x1280: top 300, font 116,
# meter 420 wide (not full-bleed). A band here is a precision choice:
# without one, K4 falls back to the frame mean, and on the SUV reel
# that mean and the cue box diverged by 54 luma units. Same scale
# rules as pivot. Finding 3: this is the only copy.
#
# The 420 is now a FLOOR, not the width. As shipped in f19370b it was
# the width, and the counter's own type overflowed it — measured on a
# real render by sampling pixels, not by eye: the band declared
# x 150..570, the slab was drawn there correctly ((34,36,36) at
# x=155..560, bare plate (226,241,244) from x=575), and the amber ran to
# x=629. `1,72,814` at font 116 plus a `+` unit is ~480px of type in a
# 420px band, so the unit and part of the last digit sat on the bare
# plate with no slab under them. That is the exact inversion of why the
# band exists: `Emphasis.tsx` says the band means "the treatment can no
# longer describe a region the type does not cover", and a hardcoded
# width describes a region the type EXCEEDS. So the width is derived
# from the content the counter will actually draw (see
# `_counter_content_width`) and the spike 420 survives only as the
# minimum, which keeps the spike look for every value that fits it.
_COUNTER_REF_WIDTH = 720
_COUNTER_REF_HEIGHT = 1280
_COUNTER_REF_FONT = 116
_COUNTER_REF_TOP = 300
_COUNTER_REF_PAD = 16
_COUNTER_MIN_BAND_WIDTH = 420

# Glyph-advance estimates, in em, for the counter content width.
#
# Python cannot do real text metrics here — the faces are chosen by
# Chromium out of a CSS stack (`Segoe UI Black` / `Arial Black` /
# Impact) and no Latin file is vendored, so there is nothing to load.
# These are therefore ESTIMATES, and they are deliberately biased WIDE:
# erring wide leaves slab the type does not use, erring narrow
# reproduces the bug above.
#
# Basis (measured 2026-09-09, `hmtx` advances read off the host faces
# the stack actually resolves to, normalised by unitsPerEm):
#   tabular digits    Segoe UI Black .599 (.483-.621 proportional)
#                     Arial Black    .667      Impact .381-.542
#   group separator   Arial Black    .333      Segoe UI Black .320
#                     Impact         .168
#   widest glyph      Segoe UI Black W 1.053, % .898
#                     Arial Black    W 1.000, % 1.000
# So 0.70 clears the widest digit in the stack by 5%, 0.40 clears the
# widest separator by 20%, and 1.10 clears the widest glyph of any kind
# by 4%. The digit headroom also absorbs the value spring overshoot:
# `Counter.tsx` scales the number by `interpolate(s, [0,1], [0.7,1])`
# with damping 13 / mass 0.5 / stiffness 150, whose peak is s=1.028,
# i.e. scale 1.0085 — 0.85%, well inside the 5%.
#
# If the stack ever gains a wider face (or a vendored Latin Black lands),
# RE-MEASURE these three numbers rather than nudging them.
_COUNTER_DIGIT_ADVANCE_EM = 0.70
_COUNTER_SEPARATOR_ADVANCE_EM = 0.40
_COUNTER_GLYPH_ADVANCE_EM = 1.10

# Mirrored from `Counter.tsx`, and the direction of the mirror is what
# makes it safe: these only decide how much EXTRA width the band asks
# for, so if the TSX changes one the band ends up a few px looser or
# tighter around type that still fits — not review finding 3, where two
# copies decided different things and only one of them drew anything.
_COUNTER_UNIT_FONT_SCALE = 0.5  # `fontSize * 0.5` on the unit span
_COUNTER_UNIT_MARGIN_PX = 10  # `marginLeft: 10` on the unit span
_COUNTER_KICKER_FONT_SCALE = 44 / 116  # `fontSize * (44/116)`
_COUNTER_KICKER_TRACKING_PX = 9  # `letterSpacing: 9` (Latin; `hi` is 0)


def format_counter_value(value: int) -> str:
    """Indian digit grouping — the same string `Counter.tsx` draws.

    `Intl.NumberFormat("en-IN")` is deterministic: last three digits,
    then groups of two (200000 -> "2,00,000", 1728140 -> "17,28,140").
    Reimplemented rather than approximated because the band width is
    counted in GLYPHS and the separators ARE glyphs — grouping in threes
    would undercount `2,00,000` by one comma, and undercounting is the
    failure being fixed.
    """
    sign = "-" if value < 0 else ""
    digits = str(abs(int(value)))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    groups.append(tail)
    return sign + ",".join(groups)


def _counter_content_width(
    *,
    font_size: int,
    pad: int,
    values: tuple[OverlayValue, ...],
    kicker: str,
) -> int:
    """Minimum band width that contains everything the counter draws.

    Two lines can be the widest and both are measured:

    1. The value line — `format_counter_value(target)` plus the optional
       unit span at half size with its 10px left margin.
    2. The kicker — the longest single WORD of `text`, because the kicker
       wraps at spaces inside the band but an unbreakable word cannot.
       On the reference case ("SOLD IN A YEAR") this never binds; a long
       compound word in either register would, and that is the same
       overflow bug one font size down.

    **The value line is sized to the FINAL value, not the current one.**
    `Counter.tsx` draws `Intl.NumberFormat("en-IN").format(round(t *
    target))` with no padding, so the string gains a glyph at a time and
    re-centres, and the count only goes UP — the final value is the
    widest string the cue ever shows. Both alternatives fail: a band
    sized to the current value would be a different rectangle every
    frame, which this design cannot express (the band is ONE value, that
    K4 measures once on the plate and both hashes key on), and
    right-padding the digits to hold the final width would change a
    watched look to buy nothing the band does not already give. The cost
    is a slab slightly wider than the digits early in the count; it is
    centred, so that reads as margin, and margin is the harmless
    direction.

    `+ 2 * pad` because `Counter.tsx` draws the slab as a padded box, so
    the type is laid out in `width - 2*pad`. That is why the overflow on
    the real render started at x=166 (band left 150 + pad 16) and not at
    the band edge.
    """
    unit_font = max(1, round(font_size * _COUNTER_UNIT_FONT_SCALE))
    kicker_font = max(1, round(font_size * _COUNTER_KICKER_FONT_SCALE))
    value_line = 0.0
    for item in values[:1]:  # `Counter.tsx` draws values[0] and no more
        rendered = format_counter_value(item.value)
        separators = rendered.count(",")
        glyphs = len(rendered) - separators
        value_line = glyphs * _COUNTER_DIGIT_ADVANCE_EM * font_size
        value_line += separators * _COUNTER_SEPARATOR_ADVANCE_EM * font_size
        if item.unit:
            value_line += len(item.unit) * _COUNTER_GLYPH_ADVANCE_EM * unit_font
            value_line += _COUNTER_UNIT_MARGIN_PX
    kicker_line = 0.0
    for word in kicker.split():
        # Tracking is charged per glyph and Latin-always: `hi` sets 0, so
        # assuming 9 is the wide side of the two registers.
        kicker_line = max(
            kicker_line,
            len(word) * (_COUNTER_GLYPH_ADVANCE_EM * kicker_font + _COUNTER_KICKER_TRACKING_PX),
        )
    return math.ceil(max(value_line, kicker_line)) + 2 * pad


def counter_band(
    canvas_width: int,
    canvas_height: int,
    *,
    values: tuple[OverlayValue, ...] = (),
    kicker: str = "",
) -> PivotBand | None:
    """Resolve the counter box for a canvas, or None if it cannot be formed.

    With no content: (150, 300, 570, 448) on 720x1280 — the spike
    420-wide meter, centred, font 116 + 2*pad 16. With content the width
    is `max(420-scaled, _counter_content_width(...))`, so the box grows
    to hold `2,00,000` + unit and never shrinks below the spike look.
    The slab/scrim draws this rectangle, K4 measures it, and both hashes
    key on it — one value, three readers, so widening it here moves the
    measured region and misses both caches with no extra wiring.

    `values`/`kicker` default to empty for callers that want geometry
    only (tests, degenerate-canvas checks). Production always passes
    them — see `_band_for_device`.
    """
    if canvas_width <= 0 or canvas_height <= 0:
        return None
    font_size = round(_COUNTER_REF_FONT * (canvas_width / _COUNTER_REF_WIDTH))
    top = round(_COUNTER_REF_TOP * (canvas_height / _COUNTER_REF_HEIGHT))
    pad = round(_COUNTER_REF_PAD * (canvas_height / _COUNTER_REF_HEIGHT))
    min_width = round(_COUNTER_MIN_BAND_WIDTH * (canvas_width / _COUNTER_REF_WIDTH))
    content_width = _counter_content_width(
        font_size=font_size, pad=pad, values=values, kicker=kicker
    )
    band_width = max(1, min_width, content_width)
    if band_width > canvas_width:
        # The canvas is now the binding constraint, so the band goes
        # full-bleed and the type may still overflow it — no rectangle
        # inside the canvas can cover type wider than the canvas. Logged
        # rather than clamped in silence, because clamping in silence is
        # how the 420 shipped. `estimated_width` is named as an estimate
        # on purpose: it is biased wide (see the em ratios above), so
        # this line can fire slightly before real overflow does — e.g.
        # `17,28,140+` at font 116 measures ~687px against a 688px
        # content box and is still rounded up to full-bleed. Treat it as
        # "this counter is at the canvas limit", and if it fires for a
        # value that plainly fits, the ratios are what to re-measure.
        logger.warning(
            "compositor.counter_band_exceeds_canvas",
            extra={
                "canvas_width": canvas_width,
                "estimated_width": band_width,
                "font_size": font_size,
            },
        )
        band_width = canvas_width
    left = max(0, (canvas_width - band_width) // 2)
    band_height = font_size + pad * 2
    y0 = max(0, min(canvas_height, top))
    y1 = max(0, min(canvas_height, top + band_height))
    if y1 <= y0:
        return None
    return PivotBand(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        left=left,
        top=y0,
        width=band_width,
        height=y1 - y0,
        font_size=font_size,
        pad=pad,
    )


def _band_for_device(
    device: EmphasisDevice,
    canvas_width: int,
    canvas_height: int,
    *,
    values: tuple[OverlayValue, ...] = (),
    text: str = "",
) -> PivotBand | None:
    if device is EmphasisDevice.PIVOT:
        return pivot_band(canvas_width, canvas_height)
    if device is EmphasisDevice.STAMP:
        return stamp_band(canvas_width, canvas_height)
    if device is EmphasisDevice.COUNTER:
        # The one device whose band cannot be a function of the canvas
        # alone: the width has to hold the digits of THIS cue target.
        # `text` is the kicker, drawn inside the same box.
        return counter_band(canvas_width, canvas_height, values=values, kicker=text)
    return None


@dataclass(frozen=True)
class OverlayValue:
    """One plotted number on a data device, mirrored from `EmphasisValue`.

    `cited_fragment` is not drawn — it is hashed so changing which
    fragment a number is cited from misses the overlay cache and the
    render fingerprint (honesty / K8 later).
    """

    value: int
    unit: str | None
    cited_fragment: int

    def as_props(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "citedFragment": self.cited_fragment,
        }

    def hash_payload(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "cited_fragment": self.cited_fragment,
        }


_COMPOSITED_DEVICES = frozenset(
    {EmphasisDevice.PIVOT, EmphasisDevice.STAMP, EmphasisDevice.COUNTER}
)

_DEVICE_HOLD_S = {
    EmphasisDevice.PIVOT: PIVOT_HOLD_S,
    EmphasisDevice.STAMP: STAMP_HOLD_S,
    EmphasisDevice.COUNTER: COUNTER_HOLD_S,
}


@dataclass(frozen=True)
class OverlayCue:
    """One cue as handed to the compositor AND hashed into the render
    fingerprint (RV2: one value gates derivation and cache).

    `treatment` is K4, resolved at render from the covering plate —
    never a planner field. Default `slab` is the safe unmeasured value
    (light-on-transparent is the 2025 failure). `shot_id` is how the
    chooser finds that plate; it is not a compositor input.

    `band` is the cue's resolved geometry (review finding 3). It is on
    the cue rather than passed around separately so that the rectangle
    K4 measures, the rectangle the fingerprint hashes and the rectangle
    the device TSX draws are one value read three times. `None` means
    the canvas could not produce a band (degenerate dimensions). Pivot,
    stamp, and counter each have their own resolver; a missing band on
    those devices is a degenerate-canvas case, not "this device has no
    geometry yet".

    `values` is the counter's target (and any later data device). Empty
    for pivot/stamp. A counter collected with no values is dropped
    upstream rather than drawn as 0→0.
    """

    device: str
    text: str
    text_register: str
    offset_s: float
    start_frame: int
    end_frame: int
    shot_id: str | None = None
    treatment: str = "slab"
    band: PivotBand | None = None
    values: tuple[OverlayValue, ...] = ()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def emphasis_font_content_hash() -> str:
    """Hash the vendored file's bytes, not its path — swapping Regular
    for Bold (K6) must miss every overlay cache and every render
    fingerprint."""
    if not EMPHASIS_FONT_PATH.exists():
        raise PermanentError(f"vendored emphasis font missing on disk: {EMPHASIS_FONT_PATH}")
    return hashlib.sha256(EMPHASIS_FONT_PATH.read_bytes()).hexdigest()


def collect_emphasis_overlay_cues(
    timeline: Timeline, *, fps: int, width: int, height: int
) -> list[OverlayCue]:
    """Film-absolute frames from each shot's resolved `offset_s`.

    Hold is per-device (`PIVOT_HOLD_S` 0.91s / `STAMP_HOLD_S` 0.86s /
    `COUNTER_HOLD_S` 1.30s), clamped so the cue cannot outlive the
    remaining shot or the remaining film.

    This slice composites `pivot`, `stamp`, and `counter`. Other devices
    (meter, comparison, correction, question) are ignored — they have no
    renderer yet, and collecting them would be a silent drop. A
    `counter` with empty `values` is skipped and logged: a counter with
    no target is a planner bug, and drawing 0→0 is worse than dropping it.

    `width`/`height` are the CANVAS, and they are required rather than
    defaulted because they resolve the cue's `band` (review finding 3).
    This is the resolver that already turns creative decisions into
    render-time numbers — frames from fragment offsets — so geometry
    belongs here too, and a defaulted 720x1280 would be exactly the kind
    of unguarded assumption finding 3 removed.
    """
    shots = timeline.all_shots()
    if not shots:
        return []
    starts = compute_shot_start_times(shots)
    total_s = compute_timeline_duration(shots)
    duration_frames = max(1, round(total_s * fps))
    cues: list[OverlayCue] = []
    for shot in shots:
        cue = shot.emphasis_cue
        if cue is None or cue.device not in _COMPOSITED_DEVICES:
            continue
        if cue.device is EmphasisDevice.COUNTER and not cue.values:
            logger.info(
                "compositor.counter_skipped_empty_values",
                extra={"shot_id": shot.id},
            )
            continue
        shot_start_s = starts.get(shot.id, 0.0)
        start_s = shot_start_s + cue.offset_s
        remaining_shot_s = max(0.0, shot.duration_s - cue.offset_s)
        remaining_film_s = max(0.0, total_s - start_s)
        hold_s = min(_DEVICE_HOLD_S[cue.device], remaining_shot_s, remaining_film_s)
        if hold_s <= 0:
            continue
        start_frame = max(0, round(start_s * fps))
        end_frame = min(duration_frames, start_frame + max(1, round(hold_s * fps)))
        if end_frame <= start_frame:
            continue
        values = tuple(
            OverlayValue(
                value=item.value,
                unit=item.unit,
                cited_fragment=item.cited_fragment,
            )
            for item in cue.values
        )
        cues.append(
            OverlayCue(
                device=cue.device.value,
                text=cue.text,
                text_register=cue.text_register.value,
                offset_s=cue.offset_s,
                start_frame=start_frame,
                end_frame=end_frame,
                shot_id=shot.id,
                # `values`/`text` reach the band because the counter box
                # is content-derived: its width has to hold the digits of
                # this cue target (f19370b shipped a hardcoded 420 that
                # the type overran by 59px). Pivot and stamp ignore them.
                band=_band_for_device(
                    cue.device, width, height, values=values, text=cue.text
                ),
                values=values,
            )
        )
    return cues


def emphasis_cue_content_hash(cues: list[OverlayCue]) -> str | None:
    """Fingerprint input: RESOLVED cues (device, text, offset_s,
    text_register, treatment, band, values). Not the untimed planner
    output. Treatment is hashed because a plate-driven flip must miss
    the render cache (retention_fast_kinetic_text.md fingerprint
    warning). `band` is hashed for the same reason one level down: the
    band's constants live in code, so editing them moves the drawn
    band, and a `final.mp4` keyed on an unchanged cue list would be
    served with the band still in its old place — the plan's own
    "serves the cached video and nothing errors" trap. `values` is
    hashed because editing a counter's target number (or its
    `cited_fragment`) must miss the same way. None when there are no
    cues so a no-cue timeline hashes with the key present and the
    value null.

    Adding `values` changes every historical value of this hash, so
    the first render of each existing project after K11 re-renders.
    That is correct: the props contract it fingerprints did change.
    """
    if not cues:
        return None
    payload = [
        {
            "device": cue.device,
            "text": cue.text,
            "offset_s": cue.offset_s,
            "text_register": cue.text_register,
            "treatment": cue.treatment,
            "band": cue.band.hash_payload() if cue.band is not None else None,
            "values": [item.hash_payload() for item in cue.values],
        }
        for cue in cues
    ]
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def emphasis_palette_as_props(palette: EmphasisPalette) -> dict[str, str]:
    """The props contract consumed by `Emphasis.tsx` (`palette`)."""
    return {"accent": palette.accent, "pivotGround": palette.pivot_ground}


def emphasis_palette_hash(palette: EmphasisPalette | None) -> str | None:
    """Fingerprint input: the RESOLVED pair actually passed to the compositor.

    None when this render has no overlay. Unset metadata and an explicit
    band pair hash identically because both resolve to the same colours
    — hashing the raw metadata field as null would let the first authoring
    of the spike pair wrongly HIT the unset cache.
    """
    if palette is None:
        return None
    return hashlib.sha256(
        _canonical_json(emphasis_palette_as_props(palette)).encode("utf-8")
    ).hexdigest()


def overlay_input_hash(
    *,
    cues: list[OverlayCue],
    width: int,
    height: int,
    fps: int,
    duration_in_frames: int,
    font_hash: str,
    palette: EmphasisPalette,
) -> str:
    """Cache key for the rendered `.mov`. Every pixel input, nothing else.

    `band` joined this payload with review finding 3. The canvas is
    already here and the band is derived from it today, but the
    derivation lives in code (`_PIVOT_REF_*` / `_STAMP_REF_*` /
    `_COUNTER_REF_*`), so the band is hashed explicitly: editing those
    constants must miss this cache instead of reusing a `.mov` with the
    band in the old position. `values` joined with K11 for the same
    reason one level down: editing a counter's target (or which
    fragment it is cited from) must miss this cache instead of serving
    a `.mov` that still counts to the old figure. `palette` joined with
    K5: changing accent or pivot_ground must miss instead of serving a
    `.mov` with the old colours (the plan's own fingerprint trap).
    Consequence, expected and correct: every overlay cached before this
    change misses once and re-renders.
    """
    payload = {
        "cues": [
            {
                "device": cue.device,
                "text": cue.text,
                "textRegister": cue.text_register,
                "startFrame": cue.start_frame,
                "endFrame": cue.end_frame,
                "treatment": cue.treatment,
                "band": cue.band.as_props() if cue.band is not None else None,
                "values": [item.as_props() for item in cue.values],
            }
            for cue in cues
        ],
        "canvas": {"width": width, "height": height},
        "fps": fps,
        "duration_in_frames": duration_in_frames,
        "font_hash": font_hash,
        "palette": emphasis_palette_as_props(palette),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def emphasis_overlay_filter_fragment(
    input_label: str, output_label: str, overlay_input_index: int
) -> str:
    return (
        f"[{input_label}][{overlay_input_index}:v]overlay=0:0:format=auto[{output_label}]"
    )


def _overlay_props(
    cues: list[OverlayCue],
    *,
    width: int,
    height: int,
    fps: int,
    duration_in_frames: int,
    palette: EmphasisPalette,
) -> dict:
    """The props contract handed to the `Emphasis` composition.

    `cue.band` is the finding-3 half of it: Python resolves the band and
    the device TSX positions itself from these numbers instead of holding
    its own copy of the layout. `values` is the counter's target (K11).
    `palette` is the K5 pair (accent + pivot ground), resolved in Python
    and never re-derived inside the compositor. Keys are camelCase
    because that is what the TSX types declare; the Python-side names
    are snake_case and the translation happens only here.
    """
    return {
        "canvas": {"width": width, "height": height},
        "fps": fps,
        "durationInFrames": duration_in_frames,
        "palette": emphasis_palette_as_props(palette),
        "cues": [
            {
                "device": cue.device,
                "text": cue.text,
                "textRegister": cue.text_register,
                "startFrame": cue.start_frame,
                "endFrame": cue.end_frame,
                "treatment": cue.treatment,
                "band": cue.band.as_props() if cue.band is not None else None,
                "values": [item.as_props() for item in cue.values],
            }
            for cue in cues
        ],
    }


def _ensure_compositor_toolchain() -> str:
    if not (COMPOSITOR_ROOT / "package.json").exists():
        raise PermanentError(
            f"compositor package missing at {COMPOSITOR_ROOT} — "
            "kinetic-text overlay cannot be rendered. Refusing to skip."
        )
    if not (COMPOSITOR_ROOT / "node_modules" / "remotion").exists():
        raise PermanentError(
            f"compositor dependencies missing under {COMPOSITOR_ROOT} — "
            "run `npm install` in compositor/. Refusing to skip."
        )
    npx = shutil.which("npx")
    if npx is None:
        raise PermanentError(
            "npx not found on PATH — the compositor requires Node 18+ "
            "(retention_fast_kinetic_text.md K7). Refusing to skip: a "
            "missing overlay would ship a reel with no kinetic text and "
            "nothing would error."
        )
    return npx


async def _invoke_remotion(props_path: Path, output_path: Path) -> None:
    npx = _ensure_compositor_toolchain()
    public_font = COMPOSITOR_ROOT / "public" / EMPHASIS_FONT_PATH.name
    if not public_font.exists():
        public_font.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EMPHASIS_FONT_PATH, public_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # ABSOLUTE paths, because this subprocess runs with cwd=COMPOSITOR_ROOT
    # while both paths are built from `settings.storage_root`, which is
    # relative ("./storage") and resolves against the BACKEND's cwd. Passed
    # through relative, the CLI cannot find the props file (it reports
    # "neither valid JSON nor a file path to a valid JSON file") and would
    # write the .mov into compositor/storage/... even if it could. Found
    # 2026-09-09 the first time `_invoke_remotion` was ever really called:
    # every unit test injects a fake `invoke`, so this line had never run.
    props_arg = props_path.resolve()
    output_arg = output_path.resolve()
    process = await asyncio.create_subprocess_exec(
        npx,
        "remotion",
        "render",
        COMPOSITION_ID,
        str(output_arg),
        f"--props={props_arg}",
        "--codec=prores",
        "--prores-profile=4444",
        "--pixel-format=yuva444p10le",
        "--image-format=png",
        cwd=str(COMPOSITOR_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise PermanentError(
            "compositor render failed "
            f"(exit {process.returncode}): {stderr.decode(errors='replace')[-4000:]}"
        )
    if not output_path.exists():
        raise PermanentError(
            f"compositor reported success but wrote no file at {output_path}; "
            f"stdout={stdout.decode(errors='replace')[-1000:]}"
        )


async def render_or_reuse_emphasis_overlay(
    *,
    project_id: str,
    cues: list[OverlayCue],
    width: int,
    height: int,
    fps: int,
    duration_in_frames: int,
    palette: EmphasisPalette,
    storage_root: Path | None = None,
    invoke=_invoke_remotion,
) -> Path:
    """Return `{storage_root}/{project_id}/overlays/{input_hash}.mov`.

    Cache HIT skips Chromium. Cache is keyed on the INPUT hash, never
    on output bytes. `palette` is the resolved pair (K5) — the same
    object the fingerprint hashed — so a colour change cannot reuse a
    `.mov` with the old hexes.
    """
    if not cues:
        raise PermanentError("render_or_reuse_emphasis_overlay called with no cues")
    font_hash = emphasis_font_content_hash()
    input_hash = overlay_input_hash(
        cues=cues,
        width=width,
        height=height,
        fps=fps,
        duration_in_frames=duration_in_frames,
        font_hash=font_hash,
        palette=palette,
    )
    root = storage_root if storage_root is not None else settings.storage_root
    overlays_dir = root / project_id / "overlays"
    cache_path = overlays_dir / f"{input_hash}.mov"
    if cache_path.exists():
        logger.info(
            "compositor.overlay_cache_hit",
            extra={"project_id": project_id, "input_hash": input_hash},
        )
        return cache_path

    overlays_dir.mkdir(parents=True, exist_ok=True)
    props_path = overlays_dir / f"{input_hash}.json"
    # Must still END in .mov: the Remotion CLI validates the output
    # extension against the codec ("prores ... must end in one of: mov,
    # mkv, mxf") before it renders anything, so a ".mov.tmp" suffix is
    # rejected outright. Leading dot keeps it out of the way and
    # `os.replace` below keeps the swap atomic. Found 2026-09-09 on the
    # first real invocation.
    tmp_path = overlays_dir / f".{input_hash}.partial.mov"
    props_path.write_text(
        json.dumps(
            _overlay_props(
                cues,
                width=width,
                height=height,
                fps=fps,
                duration_in_frames=duration_in_frames,
                palette=palette,
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        if tmp_path.exists():
            tmp_path.unlink()
        await invoke(props_path, tmp_path)
        os.replace(tmp_path, cache_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    logger.info(
        "compositor.overlay_cache_miss",
        extra={"project_id": project_id, "input_hash": input_hash},
    )
    return cache_path
