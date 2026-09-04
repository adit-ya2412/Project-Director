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
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from PIL import Image

from app.schemas.timeline import LayerRole, ShotLayer

# Matches parallax_probe.py's own measured constants exactly (§1.4/§1.5).
_KEY_SIMILARITY = 0.16  # covers the +-10/channel grain spread §1.5 measured
_KEY_BLEND = 0.05  # flat art has hard edges; a narrow blend keeps them crisp
_BASE_COLOR = "0x101418"

# §4.5's guard band. Zero (matched nothing) and anything above the max
# (ate the subject) are both failures `check_keyed_fraction` raises on;
# so is anything below the min that isn't exactly zero (matched too
# little to be a real cut-out).
_KEYED_FRACTION_MIN = 0.15
_KEYED_FRACTION_MAX = 0.85


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
) -> str:
    """Scale one ffmpeg input to its oversized working size, then
    chroma-key it if it is a cut-out plane. Ported from
    `parallax_probe.py::_layer_in`."""
    chain = f"[{index}:v]scale={width}:{height},setsar=1"
    if keyed:
        if key is None:
            raise ValueError("keyed=True requires a sampled key colour")
        chain += f",colorkey={key}:{similarity}:{blend}"
    return f"{chain},format=rgba[{name}]"


@dataclass(frozen=True)
class ParallaxLayerInput:
    """One layer's renderer-side inputs: which ffmpeg input index carries
    its still, and (for anything but the background) the key colour
    SAMPLED from that still's own bytes (§1.5). `scale`/`drift_x`/
    `drift_y` come straight off the Timeline's own `ShotLayer` -
    planner-authored, canon 3.1 - via `from_shot_layer` below."""

    role: LayerRole
    index: int
    scale: float
    drift_x: float
    drift_y: float
    key: str | None = None

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
    """
    if background.role is not LayerRole.BACKGROUND:
        raise ValueError(f"expected a BACKGROUND layer first, got {background.role.value}")
    if subject.role is not LayerRole.SUBJECT:
        raise ValueError(f"expected a SUBJECT layer second, got {subject.role.value}")
    if subject.key is None:
        raise ValueError("a SUBJECT layer must carry a sampled key colour")

    bg_w, bg_h = oversized_size(canvas_w, canvas_h, background.scale)
    bg_x0, bg_y0 = base_offset(canvas_w, canvas_h, bg_w, bg_h)
    bg_x, bg_y = drift_expressions(bg_x0, bg_y0, background.drift_x, background.drift_y, duration_s)

    sub_w, sub_h = oversized_size(canvas_w, canvas_h, subject.scale)
    sub_x0, sub_y0 = base_offset(canvas_w, canvas_h, sub_w, sub_h)
    sub_x, sub_y = drift_expressions(sub_x0, sub_y0, subject.drift_x, subject.drift_y, duration_s)

    parts = [
        base_canvas_filter(
            width=canvas_w, height=canvas_h, fps=fps, duration_s=duration_s, color=background_color
        ),
        layer_input_chain(background.index, "pxbg", width=bg_w, height=bg_h, keyed=False),
        layer_input_chain(
            subject.index, "pxsub", width=sub_w, height=sub_h, keyed=True, key=subject.key
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
