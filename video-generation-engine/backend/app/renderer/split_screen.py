"""Split-screen composite (plan §2.6). Two panels, top and bottom (or
left and right on a landscape canvas) — either or both may be a still
image or a real motion clip.

9:16 makes a vertical stack the usable layout; 16:9 inverts that to
side-by-side (`hstack`). Ken Burns correctly still returns `None` for
`SPLIT_FRAME` — this is a second input, not a `zoompan` expression.

Missing second panel degrades to the single-image/motion static path.
Never a fake split of one asset.

Panel fit (human verdict 2026-08-20, padded-panel bake-off): crop-to-
fill. Letterbox kept the whole still (the Gorki map legend survives)
but left ~25% pad on 3:2 archival photos. Fill covers each half of the
9:16 frame; edges are discarded — the same crop Ken Burns already
takes on a static shot.

## MOTION panels (2026-09-15 fix)

Originally this module only composited STILL+STILL: a MOTION panel on
either side silently degraded the whole shot to the single-image path,
showing one panel full-frame and dropping the other with no error (the
degrade `should_composite_split` was built to produce on a genuinely
missing secondary, firing instead on a merely-unsupported panel kind).

STILL+STILL stays byte-identical to the original shape: each panel
decodes to exactly one frame (`-framerate {fps} -i` with no `-loop`),
`vstack`/`hstack` combines the two 1-frame panels into one stacked
frame, and the single shared `tpad` after the stack clones it for the
shot's whole duration — the same "one decode, generate duration
internally" trick the STATIC path uses.

A MOTION panel instead carries its own real, multi-frame duration, so
it needs its own duration-fit (`app/renderer/motion.py::
build_duration_fit_fragment`, the same arithmetic
`slideshow.py::_motion_filter` already uses for a lone motion shot)
fitted to the shot's `duration_s` *before* the stack — trimming a too-
long clip or holding the last frame of a too-short one. A STILL panel
sharing the stack with a MOTION sibling gets the same "how long does
this panel need to run before the stack" treatment applied explicitly
(its own `tpad` hold to the shot's full frame count) rather than
leaning on `hstack`/`vstack`'s own end-of-stream behaviour, so the
result does not depend on undocumented stack-filter defaults.
"""

from pathlib import Path

from app.renderer.motion import MediaKind, build_duration_fit_fragment
from app.schemas.timeline import CameraMovement

# Hashed into every render/run/shot-stream fingerprint so a later
# letterbox revert cannot cache-HIT these filled frames (§7 / R2).
SPLIT_PANEL_FIT = "fill"


def panel_heights(frame_height: int) -> tuple[int, int]:
    """Top and bottom panel heights that sum to `frame_height` even when
    the frame is odd."""
    top = frame_height // 2
    return top, frame_height - top


def panel_widths(frame_width: int) -> tuple[int, int]:
    """Left and right panel widths that sum to `frame_width` even when
    the frame is odd."""
    left = frame_width // 2
    return left, frame_width - left


def should_composite_split(
    movement: CameraMovement,
    *,
    secondary_path: Path | None,
    top_kind: MediaKind,
    bot_kind: MediaKind | None,
) -> bool:
    """STILL+STILL, STILL+MOTION, MOTION+STILL and MOTION+MOTION all
    composite — only a genuinely missing secondary panel (or a movement
    other than `SPLIT_FRAME`) degrades to the single-panel path now.
    `top_kind` has no bearing on the result; it stays a required
    parameter so every call site keeps naming both panels explicitly."""
    del top_kind
    return movement == CameraMovement.SPLIT_FRAME and secondary_path is not None and bot_kind is not None


def build_split_filter(
    top_index: int,
    bot_index: int,
    *,
    width: int,
    height: int,
    fps: int,
    pixel_format: str,
    label: str,
    hold_s: float,
    top_kind: MediaKind = MediaKind.STILL,
    bot_kind: MediaKind = MediaKind.STILL,
    top_duration_s: float | None = None,
    bot_duration_s: float | None = None,
    target_duration_s: float | None = None,
) -> str:
    """Scale each panel to cover half the frame (crop-to-fill).

    Portrait (`height >= width`): `vstack` (top/bottom). Landscape:
    `hstack` (left/right). Layout is derived from the canvas so the
    render fingerprint already covers it via width/height (§19.3).

    STILL+STILL (`top_kind`/`bot_kind` both default to `MediaKind.STILL`)
    emits EXACTLY the original filter string: each panel is one decoded
    frame, and the single shared `tpad` after the stack holds the
    stacked frame for the shot's whole duration. This branch must never
    change shape — it is the shipped, proven path.

    Any other combination fits each panel to `target_duration_s`
    independently before the stack: a MOTION panel via
    `build_duration_fit_fragment` (trim a too-long clip, hold the last
    frame of a too-short one — `top_duration_s`/`bot_duration_s` must be
    that panel's real probed duration), a STILL panel sharing the stack
    with a MOTION sibling via its own `tpad` hold to the shot's full
    frame count (`hold_s`, the same value STILL+STILL's shared tail
    uses). Both panels therefore already span the full duration before
    `vstack`/`hstack` ever runs, so the shared tail collapses to a
    single `fps=`/`format=` normalisation — no second duration-fit is
    layered on top.
    """
    both_still = top_kind is MediaKind.STILL and bot_kind is MediaKind.STILL

    def _cover(index: int, panel_w: int, panel_h: int, name: str, kind: MediaKind, duration_s: float | None) -> str:
        base = (
            f"[{index}:v]scale={panel_w}:{panel_h}:force_original_aspect_ratio=increase,"
            f"crop={panel_w}:{panel_h},setsar=1"
        )
        if both_still:
            return f"{base}[{name}]"
        if kind is MediaKind.MOTION:
            assert duration_s is not None, "a MOTION panel needs its probed duration"
            assert target_duration_s is not None, "a MOTION panel needs the shot's target duration"
            fit_fragment = build_duration_fit_fragment(
                actual_duration_s=duration_s, target_duration_s=target_duration_s
            )
            fit_stage = f"{fit_fragment}," if fit_fragment else ""
            return f"{base},fps={fps},{fit_stage}fps={fps}[{name}]"
        # A STILL panel paired with a MOTION sibling: reach the shot's
        # full frame count on its own (identical arithmetic to
        # STILL+STILL's shared post-stack tpad), so the stack sees two
        # already-full-length inputs.
        return f"{base},tpad=stop_mode=clone:stop_duration={hold_s:.6f}[{name}]"

    if width > height:
        left_w, right_w = panel_widths(width)
        stack = (
            f"{_cover(top_index, left_w, height, 'spl', top_kind, top_duration_s)};"
            f"{_cover(bot_index, right_w, height, 'spr', bot_kind, bot_duration_s)};"
            f"[spl][spr]hstack=inputs=2,"
        )
    else:
        top_h, bot_h = panel_heights(height)
        stack = (
            f"{_cover(top_index, width, top_h, 'spt', top_kind, top_duration_s)};"
            f"{_cover(bot_index, width, bot_h, 'spb', bot_kind, bot_duration_s)};"
            f"[spt][spb]vstack=inputs=2,"
        )
    if both_still:
        tail = (
            f"fps={fps},"
            f"tpad=stop_mode=clone:stop_duration={hold_s:.6f},"
            f"fps={fps},"
            f"format={pixel_format}"
        )
    else:
        tail = f"fps={fps},format={pixel_format}"
    return f"{stack}{tail}[{label}]"
