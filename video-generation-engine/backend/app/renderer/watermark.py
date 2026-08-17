"""Channel branding overlay (docs/plans/watermark_implementation_plan.md).
One vendored logo, composited onto the final render via ffmpeg's
`overlay=` filter - never a second re-encode pass; see
`app/renderer/video_filters.py`'s own docstring for why this and
`app/renderer/captions.py` each only build a `filter_complex` FRAGMENT
rather than running ffmpeg themselves.

Pure string-building here, no I/O beyond reading the vendored file's own
bytes for hashing - identical shape to `captions.py`'s font handling:
- `LOGO_PATH` resolved from this module's own location, not cwd or
  config (§8.1: one channel, one logo - no name->file lookup needed).
- `watermark_content_hash` hashes the FILE's bytes, not its path, so
  swapping the vendored logo changes the fingerprint (§4, the R2 lesson).
- `watermark_filter_fragment` is the pure filter-string builder.
- `watermark_params_hash` folds position/margin/width/opacity into one
  value, the same "one hash covers every tunable" shape
  `cue_list_content_hash` already established for captions.

Position/margin/width are fractions of frame dimensions (config, never
absolute pixels) resolved to concrete pixel values here using the
render's own known width/height - exactly how `captions.py::serialize_ass`
turns `CaptionStyle`'s fractions into concrete `Fontsize`/`MarginV`
values, not a live ffmpeg `main_w` expression, since the target
resolution is already known before ffmpeg ever runs. Positioning WITHIN
the frame (which corner) still uses ffmpeg's own `main_w`/`main_h`/
`overlay_w`/`overlay_h` expressions, because the scaled logo's own exact
height depends on its aspect ratio after ffmpeg applies `scale=W:-1` -
computing that in Python would mean re-deriving what ffmpeg already
knows, for a non-square logo that may not stay square if ever replaced.
"""

import hashlib
from pathlib import Path

LOGO_PATH = Path(__file__).resolve().parents[2] / "vendor" / "branding" / "logo.png"

_POSITIONS = frozenset({"top_left", "top_right", "bottom_left", "bottom_right"})


def watermark_content_hash() -> str:
    """The fingerprint's logo input (§4): hash the FILE's bytes, not its
    path, so swapping the vendored logo changes the fingerprint even
    though `LOGO_PATH` itself never changes."""
    if not LOGO_PATH.exists():
        raise ValueError(f"vendored logo missing on disk: {LOGO_PATH}")
    return hashlib.sha256(LOGO_PATH.read_bytes()).hexdigest()


def watermark_params_hash(
    *, position: str, width_fraction: float, margin_fraction: float, opacity: float
) -> str:
    """Folds every tunable that affects burned pixels into one value
    (§4) - a position/size/opacity change must invalidate the render
    cache exactly like a logo swap does."""
    digest_input = f"{position}|{width_fraction}|{margin_fraction}|{opacity}".encode()
    return hashlib.sha256(digest_input).hexdigest()


def _position_expressions(position: str, margin_px: int) -> tuple[str, str]:
    if position not in _POSITIONS:
        raise ValueError(f"unknown watermark position {position!r} - expected one of {sorted(_POSITIONS)}")
    x = "main_w-overlay_w-{m}" if "right" in position else "{m}"
    y = "main_h-overlay_h-{m}" if "bottom" in position else "{m}"
    return x.format(m=margin_px), y.format(m=margin_px)


def watermark_filter_fragment(
    input_label: str,
    output_label: str,
    logo_input_index: int,
    *,
    frame_width: int,
    position: str,
    width_fraction: float,
    margin_fraction: float,
    opacity: float,
) -> str:
    """One `filter_complex` fragment: scales the logo (input
    `logo_input_index`) to `width_fraction` of `frame_width`, applies
    `opacity` via alpha multiply (a PNG's own per-pixel alpha survives
    this unchanged - `colorchannelmixer=aa=` multiplies it, never
    replaces it), and overlays it onto whatever video is at
    `input_label`, emitting `output_label`."""
    logo_width_px = max(round(frame_width * width_fraction), 1)
    margin_px = max(round(frame_width * margin_fraction), 0)
    x_expr, y_expr = _position_expressions(position, margin_px)
    wm_label = f"wm_{output_label}"
    return (
        f"[{logo_input_index}:v]scale={logo_width_px}:-1,format=rgba,"
        f"colorchannelmixer=aa={opacity}[{wm_label}];"
        f"[{input_label}][{wm_label}]overlay=x={x_expr}:y={y_expr}[{output_label}]"
    )
