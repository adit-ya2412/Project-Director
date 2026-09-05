"""Two-layer parallax compositing (illustrated_faceless.md §2.2/F2), beside
`ken_burns.py` and `split_screen.py`. Pure filter-graph / arithmetic
functions only, exactly like both of those modules - no ffmpeg subprocess
call lives here, and this module is not wired into `app/renderer/
slideshow.py`'s dispatch yet (that seam, and `app/workflow/steps/render.py`'s
media resolution it would need, is left for the task that actually turns
this on - F2's own brief forbids touching `render.py`).

## What this ports from `backend/scripts/parallax_probe.py`

The probe already measured that flat illustration keys cleanly (§1.4) and
that the key colour must be SAMPLED, never assumed (§1.5 - a hardcoded
`#FF00FF` matched nothing against a real delivered image and the "cut-out"
silently composited as an opaque rectangle, exit code 0). Everything below
is that probe's arithmetic and filter shape, generalised to take a Shot's
own `ShotLayer` values (role, prompt, asset_plan, drift, scale - all
planner-authored, canon 3.1) instead of the probe's hardcoded constants,
and to operate on already-loaded image BYTES rather than a path (I5: the
key must be derived from the bytes actually delivered, which are already
hashed via `shot_media` - re-opening a file would be an unrelated,
redundant read of the same content).

## The keyed-fraction guard (§4.5)

§1.5's failure was silent: exit code 0, an opaque rectangle where a
cut-out should be, nothing in the logs. `check_keyed_fraction` is the
guard that failure mode earns - it measures what share of a layer's frame
the sampled key would remove and raises if that share is not inside a
sane band (~15-85%). Zero means the key matched nothing (§1.5's own bug);
near-100% means the key ate the subject along with its background.

## P-IF-F2c (2026-09-05) - tolerance, alpha cleanup, and a distribution guard

The first real layered render (project `93c6cbde-a3c6-41d4-a2f0-8459b677a938`,
frame `tmp/jiho-parallax/p_2.1.jpg`) surfaced three defects the probe's own
clean test art never exercised:

1. **The chroma key was eating the subject in small pieces.** `_KEY_SIMILARITY`
   at its old value of 0.16 was tuned on the probe's smoother art; measured
   against this project's own real layer images (`backend/storage/93c6cbde-.../
   work/run_000_s000_sub.jpg`), it let through hundreds to thousands of
   isolated false-positive pixels inside the subject's own silhouette - see
   `keyed_scatter_fraction` below for the measurement. Lowered to 0.06 (still
   0% background leak on that same image; see the P-IF-F2c log entry in
   illustrated_faceless.md §7 for the full sweep across both a photoreal and a
   true-risograph-grain subject plate).
2. **A cleanup pass on the extracted alpha channel.** `layer_input_chain`'s
   keyed branch now runs the scaled+keyed RGBA through `split` +
   `alphaextract` + `median` (radius 2) + `alphamerge` before handing the
   frame back - a median filter on a mask is exactly a despeckle: an isolated
   transparent pixel surrounded by opaque neighbours (a hole eaten out of the
   subject) or an isolated opaque speck surrounded by transparent neighbours
   (background grain the key missed) both get overwritten by their
   neighbourhood's majority value, while a real, many-pixel-wide silhouette
   edge is untouched. Verified pixel-identical RGB channels before/after (the
   filter touches only alpha).
3. **`check_keyed_fraction` cannot tell WHERE the keyed pixels are.**
   `keyed_scatter_fraction`/`check_keyed_distribution` below are the
   distribution-aware companion §4.5 itself calls for: a real cut-out is one
   or two large contiguous keyed regions (the background, split by the
   subject's own silhouette); grain being eaten out of the subject is dozens
   of small, isolated ones. Same shape as the existing guard - measure, then
   raise `ParallaxKeyGuardError` (already caught and degraded by
   `slideshow.py`'s existing per-shot handler, so this needed no new wiring
   there beyond one more call).

## F4 (2026-09-05) - a layer can ENTER partway through a shot

`ShotLayer.enter_offset_s` (already resolved to seconds - see `app/timeline/
narration_fit.py::resolve_layer_entry_offsets`; this module never reads the
planner-authored `enter_on_fragment` itself) drives an ffmpeg `fade=t=in:
...:alpha=1` appended to the SUBJECT layer's own chain, after the §4.5/P-IF-
F2c despeckle pass rather than before it (a fade's own partially-transparent
frames would otherwise read as more small alpha holes to the median filter
to smooth away). A `background` layer may never carry one -
`build_two_layer_parallax_filter_complex` rejects a non-zero
`background.enter_offset_s` outright, matching `Shot`'s own domain-level
validator - it is the ground the shot stands on, and fading it in would
mean fading in from nothing. `_LAYER_ENTRY_FADE_S` is the one new module
constant, alongside the measured ones above; unlike them it is a REASONED
default, not a measured one (no real render with a timed entry exists yet).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from PIL import Image

from app.schemas.timeline import LayerRole, ShotLayer

# _KEY_SIMILARITY was 0.16 (parallax_probe.py's own measured value, tuned on
# its smoother test art - §1.4/§1.5). P-IF-F2c re-measured it against a real
# generated layer image (project 93c6cbde-a3c6-41d4-a2f0-8459b677a938's own
# `run_000_s000_sub.jpg`) using the connected-component method
# `keyed_scatter_fraction` below implements: at 0.16, 4.73% of the subject's
# own (ground-truth, cleanly-keyed) silhouette area fell inside the key
# tolerance and was wrongly cut out - the "riddled with pinholes" defect.
# Lowered to 0.06: 0.12% of the same silhouette (a ~38x reduction), while a
# true risograph-grain subject plate (`tmp/f1a-f2b-microtest/subject.png`)
# still has its background fully keyed at 0.06 (0% leak sampled at the same
# stride). Going lower still trades one failure for the other - at 0.04 that
# same risograph plate starts leaving visible unkeyed grain flecks in the
# background (0.37% leak, up from 0.04% at 0.06) - so 0.06 is a measured
# balance point between the two failure directions, not a floor.
_KEY_SIMILARITY = 0.06
_KEY_BLEND = 0.05  # flat art has hard edges; a narrow blend keeps them crisp
_BASE_COLOR = "0x101418"

# P-IF-F2c: a median filter over the keyed layer's extracted alpha channel,
# radius in pixels at the layer's OVERSIZED working resolution (not the final
# canvas). Despeckles small isolated errors in EITHER direction - a hole eaten
# into the subject, or a fleck of background grain the key missed - without
# touching a real, many-pixel-wide silhouette edge. Measured on the same two
# real images above: radius 2 fully removed the residual background-grain
# leak the risograph plate still showed at 0.06 (0.04% -> 0%), and left the
# photoreal subject's own silhouette edge (checked at its backpack-strap
# detail, the plate's finest feature) pixel-identical in shape at this scale.
# Set to 0 to disable (kept in the signature, not just the module constant,
# so a test can compare with/without it directly).
_ALPHA_CLEANUP_RADIUS = 2

# One `erosion` pass on the cleaned alpha, pulling the silhouette edge in by
# roughly a pixel. Measured 2026-09-05 on the microtest's own composited
# frames, which showed a distinct magenta rim tracing the subject's hair and
# shoulders: pixels at the boundary are a BLEND of subject and key field, so
# they sit too far from the key colour for `colorkey` to remove and still
# carry enough of it to read as a coloured halo. Neither a tighter
# `_KEY_SIMILARITY` nor the median pass touches them - the median preserves a
# real edge by design, which is exactly what this rim is part of.
#
# Sweep over the same pair, counting pixels in the finished composite still
# close to the sampled key colour:
#
#   erosion passes   magenta residue   frame area changed vs 0
#   0                0.019%            -
#   1                0.000%            0.297%
#   2                0.000%            0.523%
#   3                0.000%            0.747%
#
# One pass removes all of it; further passes remove nothing more and only eat
# further into the figure. 0.297% of frame area is a sub-pixel band around
# the silhouette, invisible at this scale - and losing a hair's width of
# subject is the right trade against a coloured outline around every figure.
# ffmpeg's `erosion` shrinks the bright region of a single plane, which on an
# extracted alpha mask means the opaque (subject) region. Set to 0 to disable.
_ALPHA_ERODE_PASSES = 1

# §4.5's guard band. Zero (matched nothing) and anything above the max
# (ate the subject) are both failures `check_keyed_fraction` raises on;
# so is anything below the min that isn't exactly zero (matched too
# little to be a real cut-out).
_KEYED_FRACTION_MIN = 0.15
# Raised 0.85 -> 0.95 with P-IF-F2c's subject-scale fix, because the two
# changes are in direct tension and the old number would now reject good
# frames. 0.85 was set when a subject layer was a FULL-FRAME portrait, so
# anything keying more than ~85% really did mean the subject itself had
# been eaten. F2c then told the subject layer to draw the figure small -
# "roughly the lower third to half of the frame's height, with generous
# solid magenta surrounding it on every side" - which makes a CORRECT
# plate key 80%+ by design. Measured immediately after that change, on a
# real regenerated plate that composites correctly: 0.818, i.e. inside
# the old band by 0.03 and one slightly smaller figure away from tripping
# a guard meant to catch the opposite failure.
#
# A genuine "ate the subject" is not 86%, it is near-total: the key
# matched the figure as well as the field and essentially nothing is
# left. 0.95 keeps that catchable while giving a deliberately small
# subject the room the prompt now asks it to take. The scatter guard
# (`check_keyed_distribution`) is the one that catches a subject being
# eaten a pinhole at a time, which is the failure this ceiling was
# reaching for and never actually measured.
_KEYED_FRACTION_MAX = 0.95

# P-IF-F2c's DEFECT 3: `check_keyed_fraction` above measures how MUCH of the
# frame keys away, not WHERE - a subject riddled with hundreds of small holes
# and a real, single-region cut-out can report the same healthy-looking
# fraction. `_SCATTER_FRACTION_MAX` bounds what share of the (strided) frame
# grid may belong to SMALL keyed connected components
# (`_SCATTER_MAX_COMPONENT_CELLS` grid cells or fewer - grain being eaten,
# never a real cut-out region) rather than the few large ones a real cut-out
# produces. Measured on the same
# two real images `_KEY_SIMILARITY` above was calibrated against, using
# `keyed_scatter_fraction`'s own stride-4 grid: the shipped defect (project
# 93c6cbde's `run_000_s000_sub.jpg` at the OLD similarity 0.16) scored 0.00118;
# the same image at the NEW similarity 0.06 scores 0.00050; a true
# risograph-grain subject plate (`tmp/f1a-f2b-microtest/subject.png`, always a
# clean cut-out at either similarity) scores 0.00021 (sim 0.16) / 0.00012 (sim
# 0.06). 0.0007 sits between the shipped defect and every measured clean case,
# so it catches the regression this guard exists for while passing both real
# subject plates at the new default tolerance. Calibrated on two real images
# only (four data points) - honestly flagged as a small sample, same epistemic
# status as `_DEAD_STOP_CEILING_MULTIPLIER`, not a large-scale statistical fit.
_SCATTER_MAX_COMPONENT_CELLS = 4
_SCATTER_FRACTION_MAX = 0.0007

# F4 (illustrated_faceless.md §2/F4, 2026-09-05): how long a layer's alpha
# ramp takes once it ENTERS partway through a shot (`ShotLayer.
# enter_offset_s`, resolved from a planner-authored fragment index - see
# `app/timeline/narration_fit.py::resolve_layer_entry_offsets`). No real
# render with a timed entry has been watched yet (F4's own human pass, "do
# the reveals land on the words?", is still outstanding) - reasoned from
# `app/renderer/text_cards.py::_FADE_IN_S` (0.5s), the only other place
# this codebase fades a whole visual element onto a video frame, rather
# than invented fresh. "A short fade rather than a hard pop": long enough
# to read as a deliberate reveal, short enough that the layer does not
# look like it is still arriving after the narration has already moved
# past the words that cued it.
_LAYER_ENTRY_FADE_S = 0.5


# ---------------------------------------------------------------------------
# Oversize / travel arithmetic (ported from parallax_probe.py's module-level
# constants and `_drift`, generalised from fixed numbers to a layer's own
# `scale`/`drift_x`/`drift_y`).
# ---------------------------------------------------------------------------


def oversized_size(canvas_w: int, canvas_h: int, scale: float) -> tuple[int, int]:
    """A layer's working size at `scale`x the render canvas - large enough
    that it has real picture to drift across without exposing an edge.
    `parallax_probe.py`'s own measured rule ("scale must COVER the
    output", `_OVER = 1.2`), the same reasoning `long_form_direction.md`
    §4.7 states for PAN applied to a new axis: pinning one dimension to
    the canvas is a crash risk the moment that axis drifts, so both
    dimensions are scaled, never just one."""
    if scale <= 1.0:
        raise ValueError(f"layer scale must be > 1.0 to leave room to drift, got {scale}")
    return int(canvas_w * scale), int(canvas_h * scale)


def base_offset(canvas_w: int, canvas_h: int, layer_w: int, layer_h: int) -> tuple[int, int]:
    """Top-left offset that centres the oversized layer over the canvas
    before any drift is applied. Negative in both axes, since the layer
    is larger than the canvas. Ported from `parallax_probe.py`'s
    `_X0, _Y0`."""
    return -(layer_w - canvas_w) // 2, -(layer_h - canvas_h) // 2


def drift_expressions(
    x0: int, y0: int, drift_x: float, drift_y: float, duration_s: float
) -> tuple[str, str]:
    """Linear travel over the shot's full duration, written for ffmpeg
    `overlay`'s per-frame `x`/`y`. Deterministic in ffmpeg's own `t`
    only - no RNG, no wall-clock (I5). Ported verbatim from
    `parallax_probe.py::_drift`."""
    x = f"{x0}-({drift_x}*t/{duration_s})"
    y = f"{y0}-({drift_y}*t/{duration_s})"
    return x, y


# ---------------------------------------------------------------------------
# The key colour, SAMPLED from delivered bytes, never assumed (§1.5).
# ---------------------------------------------------------------------------


def sample_key_colour(image_bytes: bytes) -> str:
    """Median colour of the top border strip, as an ffmpeg `colorkey`
    literal (`"0xRRGGBB"`). Ported from `parallax_probe.py::_sample_key`,
    generalised to take image BYTES rather than a path.

    Top strip only: a keyed layer's subject touches the BOTTOM edge by
    convention (the four faceless framings §1.3 measured all crop at the
    waist or lower), so a corner-average would sample the subject rather
    than the background the key needs. Median, not mean, so a single
    stray subject pixel at the strip's edge cannot pull the sampled key
    toward the subject's own colour.

    §1.5, measured: a HARDCODED key (`#FF00FF`) matched nothing against a
    real delivered image - the model returned `#B43E7E`, harmonising the
    requested magenta into its own limited palette and laying grain over
    it, so the plate varied +-10/channel across the field. The composite
    still built, with exit code 0, and the "cut-out" rendered as an
    opaque rectangle. This function exists so that failure mode cannot
    recur: the key always matches what was actually delivered, not what
    was asked for.
    """
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        if width == 0 or height == 0:
            raise ValueError("image has zero width or height; cannot sample a key colour")
        # `parallax_probe.py` samples a fixed 24px-tall strip (its probe
        # images are always >= 24px tall); clamped to the real height here
        # so this also works on the small synthetic images unit tests use.
        strip_h = min(24, height)
        pixels = [rgb.getpixel((x, y)) for x in range(0, width, 5) for y in range(0, strip_h, 4)]
    r, g, b = (sorted(p[i] for p in pixels)[len(pixels) // 2] for i in range(3))
    return f"0x{r:02X}{g:02X}{b:02X}"


def _key_to_rgb(key: str) -> tuple[int, int, int]:
    text = key.removeprefix("0x").removeprefix("0X")
    if len(text) != 6:
        raise ValueError(f"expected a 6-hex-digit colour like '0xRRGGBB', got {key!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


# ---------------------------------------------------------------------------
# Filter-graph construction (ported from parallax_probe.py::_layer_in,
# _base, and _clip_a).
# ---------------------------------------------------------------------------


def base_canvas_filter(
    *, width: int, height: int, fps: int, duration_s: float, color: str = _BASE_COLOR
) -> str:
    """The solid backdrop every parallax composite overlays onto - ported
    from `parallax_probe.py::_base`. Only visible at a layer's own
    oversize margin if drift ever exposes one; the working canvas is
    sized to make that not happen in practice."""
    return f"color=c={color}:s={width}x{height}:r={fps}:d={duration_s}[base]"


def layer_input_chain(
    index: int,
    name: str,
    *,
    width: int,
    height: int,
    keyed: bool,
    key: str | None = None,
    similarity: float = _KEY_SIMILARITY,
    blend: float = _KEY_BLEND,
    alpha_cleanup_radius: int = _ALPHA_CLEANUP_RADIUS,
    alpha_erode_passes: int = _ALPHA_ERODE_PASSES,
    entry_offset_s: float = 0.0,
    entry_fade_s: float = _LAYER_ENTRY_FADE_S,
) -> str:
    """Scale one ffmpeg input to its oversized working size, then
    chroma-key it if it is a cut-out plane. Ported from
    `parallax_probe.py::_layer_in`.

    P-IF-F2c: a keyed layer also gets an alpha-channel cleanup pass
    (`alpha_cleanup_radius` > 0, the default) - `median` on the extracted
    alpha, isolated from colour, then merged back via `alphamerge`. This
    despeckles the small isolated errors §4.5's own guard cannot see the
    SHAPE of (a hole eaten into the subject, or a fleck of background grain
    the key missed), without touching a real silhouette edge. `ffmpeg
    -filters` (this project's installed 9.0 build) was checked before
    reaching for this shape: no purpose-built "fill small alpha holes"
    filter exists, but `median`/`alphaextract`/`alphamerge` all do, and
    together are exactly a despeckle. The unkeyed background layer never
    needs this - it was never selectively made transparent, so it has no
    alpha-channel holes to clean.

    F4: `entry_offset_s > 0.0` appends an ffmpeg `fade=t=in:...:alpha=1`
    onto the FINAL rgba stream - after the despeckle pass, never before
    it, since the despeckle is a median filter over the alpha channel and
    would read a fade's own partially-transparent frames as more small
    holes to smooth away. `entry_offset_s <= 0.0` (the default, and every
    call site that predates F4) appends nothing at all - byte-identical
    to this function's own pre-F4 output, which is what keeps every
    existing parallax shot's filter-graph untouched (§3.1)."""
    chain = f"[{index}:v]scale={width}:{height},setsar=1"
    fade = (
        f",fade=t=in:st={entry_offset_s}:d={entry_fade_s}:alpha=1" if entry_offset_s > 0.0 else ""
    )
    if not keyed:
        return f"{chain},format=rgba{fade}[{name}]"
    if key is None:
        raise ValueError("keyed=True requires a sampled key colour")
    chain += f",colorkey={key}:{similarity}:{blend},format=rgba"
    if alpha_cleanup_radius <= 0:
        return f"{chain}{fade}[{name}]"
    erode = ",".join("erosion" for _ in range(max(0, alpha_erode_passes)))
    erode = f",{erode}" if erode else ""
    return (
        f"{chain},split[{name}_rgba1][{name}_rgba2];"
        f"[{name}_rgba1]alphaextract,median=radius={alpha_cleanup_radius}{erode}[{name}_a];"
        f"[{name}_rgba2][{name}_a]alphamerge,format=rgba{fade}[{name}]"
    )


@dataclass(frozen=True)
class ParallaxLayerInput:
    """One layer's renderer-side inputs: which ffmpeg input index carries
    its still, and (for anything but the background) the key colour
    SAMPLED from that still's own bytes (§1.5). `scale`/`drift_x`/
    `drift_y`/`enter_offset_s` come straight off the Timeline's own
    `ShotLayer` - planner/resolver-authored, canon 3.1 - via
    `from_shot_layer` below; this module only ever EXECUTES them."""

    role: LayerRole
    index: int
    scale: float
    drift_x: float
    drift_y: float
    key: str | None = None
    # F4: the RESOLVED (seconds) half of `ShotLayer.enter_on_fragment` -
    # `app/timeline/narration_fit.py::resolve_layer_entry_offsets` already
    # did the fragment-to-seconds arithmetic and the clamp; this module
    # never reads `enter_on_fragment` itself; it only ever consumes
    # already-resolved seconds. `0.0` (the default, and every layer that
    # predates F4) means "present from the start".
    enter_offset_s: float = 0.0

    @classmethod
    def from_shot_layer(
        cls, layer: ShotLayer, *, index: int, key: str | None = None
    ) -> ParallaxLayerInput:
        return cls(
            role=layer.role,
            index=index,
            scale=layer.scale,
            drift_x=layer.drift_x,
            drift_y=layer.drift_y,
            key=key,
            enter_offset_s=layer.enter_offset_s,
        )


def validate_two_layer_shot(layers: list[ShotLayer]) -> None:
    """F2 requires exactly `[background, subject]`, in that order - not
    enforced by the `Shot`/`ShotLayer` schema itself (F3 legitimately
    adds a third), but required by `build_two_layer_parallax_filter_
    complex` below. Raises `ValueError` naming exactly what's wrong
    rather than letting a malformed list reach the filter builder."""
    if len(layers) != 2:
        raise ValueError(f"F2 parallax needs exactly 2 layers, got {len(layers)}")
    if layers[0].role is not LayerRole.BACKGROUND:
        raise ValueError(f"first layer must be background, got {layers[0].role.value}")
    if layers[1].role is not LayerRole.SUBJECT:
        raise ValueError(f"second layer must be subject, got {layers[1].role.value}")


def build_two_layer_parallax_filter_complex(
    background: ParallaxLayerInput,
    subject: ParallaxLayerInput,
    *,
    canvas_w: int,
    canvas_h: int,
    fps: int,
    duration_s: float,
    label: str = "out",
    background_color: str = _BASE_COLOR,
    entry_fade_s: float = _LAYER_ENTRY_FADE_S,
) -> str:
    """F2's two-layer parallax `filter_complex`: an un-keyed background
    plane and one keyed subject plane, each drifting at its own rate over
    one shot. Ported from `parallax_probe.py::_clip_a` - same shape, same
    arithmetic, generalised to a Shot's own `ShotLayer` values via
    `ParallaxLayerInput` instead of the probe's hardcoded constants.

    F2 is two layers only (§2.2); a third (near-foreground) plane is F3.
    This function deliberately rejects anything but `(BACKGROUND,
    SUBJECT)` in that order rather than silently building a two-layer
    graph out of the wrong roles.

    F4: only the SUBJECT plane may fade in (`subject.enter_offset_s`) -
    `background.enter_offset_s` is REJECTED outright if non-zero, never
    silently ignored, matching this function's own existing practice of
    raising rather than degrading on a malformed role (`Shot`'s own
    `_background_layer_never_carries_an_entry` validator should already
    make this unreachable in practice; this is the belt to that
    suspenders). The fade duration is clamped to whatever of the shot
    remains after `enter_offset_s` so a late entry on a short shot cannot
    ask for a fade longer than the shot itself.
    """
    if background.role is not LayerRole.BACKGROUND:
        raise ValueError(f"expected a BACKGROUND layer first, got {background.role.value}")
    if subject.role is not LayerRole.SUBJECT:
        raise ValueError(f"expected a SUBJECT layer second, got {subject.role.value}")
    if subject.key is None:
        raise ValueError("a SUBJECT layer must carry a sampled key colour")
    if background.enter_offset_s:
        raise ValueError(
            "a BACKGROUND layer must never carry an entry offset "
            "(illustrated_faceless.md F4): it is the ground the shot stands "
            "on, and fading it in would mean fading in from nothing"
        )

    bg_w, bg_h = oversized_size(canvas_w, canvas_h, background.scale)
    bg_x0, bg_y0 = base_offset(canvas_w, canvas_h, bg_w, bg_h)
    bg_x, bg_y = drift_expressions(bg_x0, bg_y0, background.drift_x, background.drift_y, duration_s)

    sub_w, sub_h = oversized_size(canvas_w, canvas_h, subject.scale)
    sub_x0, sub_y0 = base_offset(canvas_w, canvas_h, sub_w, sub_h)
    sub_x, sub_y = drift_expressions(sub_x0, sub_y0, subject.drift_x, subject.drift_y, duration_s)

    # F4: never let the fade outlast what remains of the shot once the
    # entry has happened - the same `min(fade, remaining/2-or-less)` guard
    # `text_cards.py`'s own `clamped_in`/`clamped_out` apply for a short
    # shot, one level simpler here since only ONE fade (in) is ever built.
    effective_fade_s = min(entry_fade_s, max(0.0, duration_s - subject.enter_offset_s))

    parts = [
        base_canvas_filter(
            width=canvas_w, height=canvas_h, fps=fps, duration_s=duration_s, color=background_color
        ),
        layer_input_chain(background.index, "pxbg", width=bg_w, height=bg_h, keyed=False),
        layer_input_chain(
            subject.index,
            "pxsub",
            width=sub_w,
            height=sub_h,
            keyed=True,
            key=subject.key,
            entry_offset_s=subject.enter_offset_s,
            entry_fade_s=effective_fade_s,
        ),
        f"[base][pxbg]overlay=x='{bg_x}':y='{bg_y}':shortest=1[pxb1]",
        f"[pxb1][pxsub]overlay=x='{sub_x}':y='{sub_y}'[{label}]",
    ]
    return ";".join(parts)


# ---------------------------------------------------------------------------
# The keyed-fraction guard (§4.5).
# ---------------------------------------------------------------------------


class ParallaxKeyGuardError(ValueError):
    """§4.5's guard tripped. Both failure directions are silent
    everywhere else in the pipeline - exit code 0, nothing in the logs
    (§1.5) - which is exactly why this must raise rather than log."""


def _pixel_distance(pixel: tuple[int, int, int], key_rgb: tuple[int, int, int]) -> float:
    """Normalised (0..1) Euclidean distance in RGB space. Not a claim of
    bit-exact parity with ffmpeg's own internal `colorkey` implementation
    - this is a sanity check on the KEYED FRACTION (§4.5), not a
    reimplementation of the filter, and this measure is a reasonable,
    documented approximation of "how close is this pixel to the key"."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(pixel, key_rgb, strict=True))) / (
        255.0 * math.sqrt(3)
    )


def keyed_fraction(
    image_bytes: bytes, key: str, *, similarity: float = _KEY_SIMILARITY, stride: int = 4
) -> float:
    """Fraction (0..1) of `image_bytes` within `similarity` of `key`
    (`"0xRRGGBB"`) - approximately what ffmpeg's `colorkey` filter would
    key transparent at that similarity. A representative strided sample
    (every `stride`th pixel on each axis, the same sampling discipline
    `sample_key_colour` above uses), not a full-resolution scan, so this
    is cheap enough to run as a guard on every generated layer.

    §4.5's guard reads this value: near 0 means the key matched nothing
    (§1.5's opaque-rectangle bug); near 1 means the key ate the subject
    along with the background it was meant to remove."""
    key_rgb = _key_to_rgb(key)
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        pixels = [
            rgb.getpixel((x, y)) for x in range(0, width, stride) for y in range(0, height, stride)
        ]
    if not pixels:
        return 0.0
    keyed = sum(1 for p in pixels if _pixel_distance(p, key_rgb) <= similarity)
    return keyed / len(pixels)


def check_keyed_fraction(
    fraction: float,
    *,
    min_fraction: float = _KEYED_FRACTION_MIN,
    max_fraction: float = _KEYED_FRACTION_MAX,
    shot_id: str = "",
    layer_role: str = "",
) -> None:
    """§4.5's guard: raise `ParallaxKeyGuardError` unless `fraction` (as
    returned by `keyed_fraction` above) falls inside `[min_fraction,
    max_fraction]` (default ~15-85%). Zero and near-100% are both
    distinguished in the message, because they are different bugs with
    different fixes - zero means re-sample the key (§1.5); near-100%
    means the key colour or similarity is too loose and is eating real
    picture."""
    label = f" ({shot_id}/{layer_role})" if shot_id or layer_role else ""
    if fraction <= 0.0:
        raise ParallaxKeyGuardError(
            f"keyed fraction is 0.0{label}: the colour key matched nothing "
            "(the opaque-rectangle bug - illustrated_faceless.md §1.5/§4.5; "
            "exit code 0, no other symptom - the 'cut-out' composites as a "
            "solid rectangle instead)."
        )
    if fraction > max_fraction:
        raise ParallaxKeyGuardError(
            f"keyed fraction {fraction:.3f}{label} exceeds {max_fraction} "
            "(illustrated_faceless.md §4.5): the key likely ate the subject "
            "along with the background."
        )
    if fraction < min_fraction:
        raise ParallaxKeyGuardError(
            f"keyed fraction {fraction:.3f}{label} is below {min_fraction} "
            "(illustrated_faceless.md §4.5): the key matched too little of "
            "the frame to be a real cut-out."
        )


# ---------------------------------------------------------------------------
# The distribution guard (P-IF-F2c, DEFECT 3). `check_keyed_fraction` above
# measures how MUCH of the frame keys away and passed comfortably on the real
# defect this module was built to catch - thousands of tiny holes sum to a
# perfectly normal-looking fraction. `keyed_scatter_fraction` measures WHERE
# the keyed pixels are: a real cut-out is one or two large contiguous regions
# (the background, split by the subject's own silhouette); grain being eaten
# out of the subject is dozens of small, isolated ones.
# ---------------------------------------------------------------------------


def keyed_scatter_fraction(
    image_bytes: bytes,
    key: str,
    *,
    similarity: float = _KEY_SIMILARITY,
    stride: int = 4,
    max_component_cells: int = _SCATTER_MAX_COMPONENT_CELLS,
) -> float:
    """Share (0..1) of the sampled frame grid occupied by SMALL keyed
    connected components (`max_component_cells` grid cells or fewer) -
    distribution-aware companion to `keyed_fraction` above, cheap and
    deterministic (I5): one strided pass to build a boolean grid (the same
    sampling discipline `keyed_fraction`/`sample_key_colour` already use),
    then a plain 4-connected flood fill over that grid - no external
    dependency, no image library beyond the `Image.getpixel` calls already
    used elsewhere in this module.

    A real cut-out's background is one connected region (occasionally two
    or three, where the subject's silhouette splits it at the frame edges);
    grain being eaten out of the subject shows up as many components at or
    below `max_component_cells`. This function returns only the aggregate
    SIZE those small components occupy, as a fraction of the whole sampled
    grid - resolution-independent, so it means the same thing on a 9:16 and
    a 16:9 canvas (§4.2). `check_keyed_distribution` below is the guard that
    reads this value."""
    key_rgb = _key_to_rgb(key)
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        cols = list(range(0, width, stride))
        rows = list(range(0, height, stride))
        grid = [
            [_pixel_distance(rgb.getpixel((x, y)), key_rgb) <= similarity for x in cols]
            for y in rows
        ]
    n_rows, n_cols = len(grid), len(grid[0]) if grid else 0
    total_cells = n_rows * n_cols
    if total_cells == 0:
        return 0.0
    visited = [[False] * n_cols for _ in range(n_rows)]
    small_component_cells = 0
    for start_j in range(n_rows):
        for start_i in range(n_cols):
            if not grid[start_j][start_i] or visited[start_j][start_i]:
                continue
            stack = [(start_j, start_i)]
            visited[start_j][start_i] = True
            size = 0
            while stack:
                cj, ci = stack.pop()
                size += 1
                for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nj, ni = cj + dj, ci + di
                    if (
                        0 <= nj < n_rows
                        and 0 <= ni < n_cols
                        and grid[nj][ni]
                        and not visited[nj][ni]
                    ):
                        visited[nj][ni] = True
                        stack.append((nj, ni))
            if size <= max_component_cells:
                small_component_cells += size
    return small_component_cells / total_cells


def check_keyed_distribution(
    scatter_fraction: float,
    *,
    max_scatter_fraction: float = _SCATTER_FRACTION_MAX,
    shot_id: str = "",
    layer_role: str = "",
) -> None:
    """P-IF-F2c's guard: raise `ParallaxKeyGuardError` (the SAME exception
    `check_keyed_fraction` raises, so `slideshow.py`'s existing per-shot
    degrade handler catches this with no new wiring) when `scatter_fraction`
    (from `keyed_scatter_fraction` above) exceeds `max_scatter_fraction`.
    Distinct message from `check_keyed_fraction`'s three, because it is a
    different bug with a different fix: not "too much or too little got
    keyed" but "the keyed pixels are scattered rather than forming a real
    cut-out" - illustrated_faceless.md §7's P-IF-F2c log entry has the
    measurement `_SCATTER_FRACTION_MAX` was calibrated against."""
    label = f" ({shot_id}/{layer_role})" if shot_id or layer_role else ""
    if scatter_fraction > max_scatter_fraction:
        raise ParallaxKeyGuardError(
            f"keyed scatter fraction {scatter_fraction:.5f}{label} exceeds "
            f"{max_scatter_fraction} (illustrated_faceless.md §7 P-IF-F2c): "
            "the keyed pixels are scattered across many small isolated "
            "regions rather than forming a real cut-out - grain or detail is "
            "being eaten out of the subject rather than the background being "
            "removed."
        )


# Role-derived drift, resolved at PLANNING time (illustrated_faceless.md,
# 2026-09-05). `ShotLayerOutput`'s docstring correctly keeps `drift_x`/
# `drift_y` off the Shot Planner's structured output - a pixel travel is
# craft, not a creative judgement, the same way `ken_burns.py` derives a
# zoompan expression from movement+intensity rather than asking a planner
# for pixel coordinates. But nothing then SET them, so every layer of the
# first real parallax timeline came back at the schema default of 0.0 -
# two planes drifting at the same zero rate, which composites as a static
# image and is not parallax at all. Measured on a real plan
# (`5587a407-aa9d-4581-8c95-d00f21e1768c`, 5 parallax shots, every layer
# 0.0/0.0) before a cent was spent generating them.
#
# The values are `parallax_probe.py`'s own two-layer clip, the one that
# was eye-signed in §1.4: background 24px, subject 110px over the shot,
# at scale 1.2. The RATIO is what reads as depth - a subject travelling
# ~4.5x the background - not the absolute numbers.
#
# Resolved here rather than in the renderer on purpose: R2/§4.1 requires
# every value that changes render bytes to be in the fingerprint, and the
# fingerprint reads `ShotLayer`'s own fields. A renderer-side override
# would leave the Timeline recording 0.0 while the picture moved, so the
# cache could not tell two different drifts apart.
_ROLE_DRIFT_X: dict[LayerRole, float] = {
    LayerRole.BACKGROUND: 24.0,
    LayerRole.SUBJECT: 110.0,
    LayerRole.FOREGROUND: 230.0,
}


def default_drift_for_role(role: LayerRole) -> tuple[float, float]:
    """Horizontal-only by default: a vertical component on a 9:16 canvas
    eats the scale headroom far faster (the same "scale must COVER the
    output" arithmetic §4.7 of long_form_direction.md spells out for
    PAN), and no vertical drift has been eye-signed. Returns
    `(drift_x, drift_y)` so a future vertical variant needs no call-site
    change."""
    return _ROLE_DRIFT_X.get(role, 0.0), 0.0
