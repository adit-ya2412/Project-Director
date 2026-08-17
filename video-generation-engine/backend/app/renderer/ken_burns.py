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
- `PUNCH_IN` (added 2026-08-17, motion_new_styles_and_long_form_videos.md
  step 0 -> Track B) is the one movement that is NOT a continuous ramp -
  a hard, stepped zoom-in, built by `build_punch_in_expression` and
  dispatched to it below exactly like any other movement. Verified
  pixel-correct against a real archival photo and watched by a human
  against real production output before being wired in as a real,
  planner-choosable value, not left as a renderer-only override - see
  that function's own docstring for why `camera.movement`/`direction`
  are deliberately NOT consulted for it, unlike every other branch here.
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

    if camera.movement == CameraMovement.PUNCH_IN:
        return build_punch_in_expression(camera, frames=frames)

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


# Punch-in reaches noticeably further than a slow-drift Ken Burns shot in
# the SAME duration (motion_new_styles_and_long_form_videos.md, Track B
# Tier 1 "fast-cut / retention") - it needs to read as a deliberate snap
# within a second or two, not a gentle push across 3-8s. A separate,
# larger ceiling than `_MAX_ZOOM_DELTA` on purpose: reusing the slow-drift
# constant would produce a step too small to register as a "punch" at
# typical fast-cut shot durations.
_MAX_PUNCH_ZOOM_DELTA = 0.9


def build_punch_in_expression(
    camera: Camera, *, frames: int, num_punches: int = 2
) -> ZoompanExpression | None:
    """A HARD, STEPPED zoom-in - held constant, then snapping to a higher
    level at evenly-spaced frame offsets - as opposed to
    `build_zoompan_expression`'s continuous ramp for every other
    movement. This is Route 1 for a fast-cut/retention style (plan §2.5):
    re-framing the SAME still to manufacture a cut where none exists, the
    technique's actual origin (talking-head footage with no real cuts to
    work with).

    **History, because the reasoning below only makes sense with it:**
    started as a visual spike (`build_zoompan_expression` deliberately
    did NOT dispatch to this, and `camera.movement`/`direction` were
    deliberately NOT consulted at all - a render-level override forcing
    every shot to punch, bypassing whatever camera the Timeline actually
    said) to answer one question before committing to any schema change:
    does this look right on archival stills? Verified pixel-correct
    (frame-by-frame symbolic evaluation, then a real render against
    `m8_test_project`'s real Wikimedia photos) and watched by a human
    against real production output - verdict "holds good". Promoted the
    same day to `CameraMovement.PUNCH_IN`, a real value the Shot Planner
    can choose per shot (canon 3.1/§2.2: camera decisions are written
    into the Timeline by the planner, never applied by the renderer from
    a style alone) - `build_zoompan_expression` now dispatches to this
    function exactly like any other movement.

    `camera.direction` is NOT consulted, for the SAME reason `SLOW_PUSH`/
    `PULL_BACK` above don't consult it either - the movement's own name
    already says which way (in). `camera.intensity` scales how far each
    punch reaches, consistent with every other movement in this module.

    Same `None`-means-no-motion contract as `build_zoompan_expression`:
    `intensity=0` or `frames` too short for `num_punches` distinct steps
    both degrade to no motion, never a crash or a cramped, unreadable
    zoom pattern.
    """
    if camera.intensity <= 0:
        return None
    frames = max(frames, 1)
    last_frame = max(frames - 1, 1)
    if num_punches < 1 or frames < num_punches * 2:
        # Too few frames to hold each punch level for a moment before the
        # next one - a shot this short should stay static rather than
        # render a smeared, unreadable zoom.
        return None

    max_zoom = 1.0 + camera.intensity * _MAX_PUNCH_ZOOM_DELTA
    if max_zoom <= 1.0:
        return None

    # Punch frame offsets: evenly spaced, none at frame 0 (the shot must
    # visibly HOLD before the first punch, or there is nothing to punch
    # FROM) and none past `last_frame` (the final level must still be
    # holding, not still stepping, when the shot ends).
    punch_frames = [round(last_frame * (i + 1) / (num_punches + 1)) for i in range(num_punches)]
    levels = [1.0 + (i + 1) * (max_zoom - 1.0) / num_punches for i in range(num_punches)]

    # Build the piecewise-constant zoom(on) expression from the LAST
    # threshold inward, e.g. for two punches (F0 < F1, levels L0 < L1):
    #   if(lt(on,F0), 1.0, if(lt(on,F1), L0, L1))
    # `levels[i-1]` (not `levels[i]`) at threshold `punch_frames[i]` is
    # deliberate: crossing threshold i means "advance from level i-1 to
    # level i", so the guard for NOT YET past threshold i must still
    # report the PRIOR level - using `levels[i]` here would make the
    # level at index 0 unreachable (any `on` failing the outermost check
    # falls straight past it into level 1's own branch).
    zoom_expr = f"{levels[-1]:.6f}"
    for i in range(num_punches - 1, 0, -1):
        zoom_expr = f"if(lt(on,{punch_frames[i]}),{levels[i - 1]:.6f},{zoom_expr})"
    zoom_expr = f"if(lt(on,{punch_frames[0]}),1.0,{zoom_expr})"

    return ZoompanExpression(
        zoom_expr=zoom_expr,
        x_expr="iw/2-(iw/zoom/2)",
        y_expr="ih/2-(ih/zoom/2)",
    )
