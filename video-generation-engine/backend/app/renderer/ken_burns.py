"""Ken Burns: `camera.movement`/`direction`/`intensity` -> ffmpeg
`zoompan` expressions (M8 step 5, canon 3.1 - a renderer concern only, no
planner changes). A slow push or pan across a real archival photograph is
most of what makes generated/searched stills read as documentary footage
rather than a slideshow.

## The well-known zoompan jitter, and why this avoids it

`zoompan`'s `zoom` variable is the PREVIOUS output frame's zoom level -
it only accumulates correctly across `d` frames generated from a SINGLE
input frame. Feed it a `-loop 1 -t duration` input (many decoded copies
of the same still, which is how every OTHER shot in this renderer plays
a static image for its duration) and zoompan sees a "new" input frame
on every step, resetting `zoom` to 1 each time - the visible stutter
this module's whole job is to avoid. The fix (`app/renderer/slideshow.py`
callers of `zoompan_filter_graph`) is to hand zoompan EXACTLY one decoded
frame and let its own `d`/`fps` parameters generate the whole shot's
duration internally, rather than pre-looping the input at all.

## Scope

- `STATIC` and `SPLIT_FRAME` never touch `zoompan` - `STATIC` because
  there is nothing to animate, `SPLIT_FRAME` because a real split-screen
  composite needs a SECOND source image to split with, which this
  renderer's one-image-per-shot contract doesn't have; building that is
  a materially different pipeline change, not a `zoompan` expression, so
  it renders as a plain static frame instead of pretending to split
  (a known, documented gap, not silently mis-implemented).
- `SLOW_PUSH` always zooms in and `PULL_BACK` always zooms out -
  `camera.direction` is not consulted for either (the movement name
  already says which way), only for `SLOW_ZOOM` (which needs `direction`
  to know which way) and `PAN`.
- `intensity` (0-1) scales how much motion happens; `intensity=0`
  degrades gracefully to no visible motion at all (zoom/pan range
  collapses to zero), never a crash or a jarring full-range default.
"""

from dataclasses import dataclass

from app.schemas.timeline import Camera, CameraDirection, CameraMovement

# At intensity=1.0, a zoom shot travels from 1.0x to this multiplier over
# its whole duration - subtle by design (Principle 7, cinematic
# continuity: this must read as documentary motion, not a music-video
# zoom). At the Camera default (intensity=0.15) that is a gentle ~7.5%
# zoom across a shot, matching the module docstring's own "slow push".
_MAX_ZOOM_DELTA = 0.5
# A pan needs SOME zoom headroom to have anywhere to pan within a fixed-
# size output frame; at intensity=1.0 this is a generous 30% zoomed-in
# working canvas to pan across.
_MAX_PAN_ZOOM_DELTA = 0.3
# The oversized working canvas every Ken Burns shot is scaled to before
# zoompan runs, so zooming/panning resamples real extra pixels rather
# than upscaling an already-target-resolution frame. Large enough to
# cover both the zoom delta and the pan delta above with margin.
WORKING_CANVAS_SCALE = 1.6


@dataclass(frozen=True)
class ZoompanExpression:
    """One shot's complete `zoompan` filter parameters - everything
    `app/renderer/slideshow.py` needs to build the filter string, kept
    separate from ffmpeg string-building so the arithmetic itself is
    unit-testable without shelling out."""

    zoom_expr: str
    x_expr: str
    y_expr: str


def build_zoompan_expression(camera: Camera, *, frames: int) -> ZoompanExpression | None:
    """`None` means "no motion" (STATIC, SPLIT_FRAME, or an intensity of
    0) - the caller renders a plain static frame, byte-for-byte the same
    path every shot used before this module existed. `frames` is the
    shot's total OUTPUT frame count (`round(duration_s * fps)`, already
    computed by the caller, which also owns that arithmetic - D5's own
    "compute it in exactly one place" discipline applies here too)."""
    if camera.movement in (CameraMovement.STATIC, CameraMovement.SPLIT_FRAME):
        return None
    frames = max(frames, 1)
    last_frame = max(frames - 1, 1)

    if camera.movement in (
        CameraMovement.SLOW_ZOOM,
        CameraMovement.SLOW_PUSH,
        CameraMovement.PULL_BACK,
    ):
        zooming_out = camera.movement == CameraMovement.PULL_BACK or (
            camera.movement == CameraMovement.SLOW_ZOOM and camera.direction == CameraDirection.OUT
        )
        max_zoom = 1.0 + camera.intensity * _MAX_ZOOM_DELTA
        if max_zoom <= 1.0:
            return None  # intensity 0 - no motion, not a divide-by-zero
        step = (max_zoom - 1.0) / last_frame
        zoom_expr = (
            f"if(eq(on,0),{max_zoom:.6f},max(zoom-{step:.8f},1.0))"
            if zooming_out
            else f"min(zoom+{step:.8f},{max_zoom:.6f})"
        )
        return ZoompanExpression(
            zoom_expr=zoom_expr,
            x_expr="iw/2-(iw/zoom/2)",
            y_expr="ih/2-(ih/zoom/2)",
        )

    if camera.movement == CameraMovement.PAN:
        pan_zoom = 1.0 + camera.intensity * _MAX_PAN_ZOOM_DELTA
        if pan_zoom <= 1.0:
            return None
        # LEFT means the camera reveals the frame moving leftward (pans
        # from the right side of the image toward the left); anything
        # else (RIGHT, or an undirected/IN/OUT pan, which is not a
        # meaningful combination but must never crash) defaults to a
        # left-to-right pan.
        left_to_right = camera.direction != CameraDirection.LEFT
        progress = f"(on/{last_frame})" if left_to_right else f"(1-on/{last_frame})"
        x_expr = f"(iw-iw/{pan_zoom:.6f})*{progress}"
        return ZoompanExpression(
            zoom_expr=f"{pan_zoom:.6f}",
            x_expr=x_expr,
            y_expr=f"ih/2-(ih/{pan_zoom:.6f}/2)",
        )

    return None
