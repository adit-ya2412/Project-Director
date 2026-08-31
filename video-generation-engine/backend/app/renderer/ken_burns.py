"""Ken Burns: `camera.movement`/`direction`/`intensity` -> ffmpeg
`zoompan` expressions (M8 step 5, canon 3.1 - a renderer concern only, no
planner changes). A slow push or pan across a real archival photograph is
most of what makes generated/searched stills read as documentary footage
rather than a slideshow.

## The well-known zoompan jitter, and why this avoids it

`zoompan`'s `zoom` variable is the PREVIOUS output frame's zoom level -
it only accumulates correctly across `d` frames generated from a SINGLE
input frame. Feed it a looping multi-frame input and zoompan sees a
"new" input frame on every step, resetting `zoom` to 1 each time -
the visible stutter this module's whole job is to avoid. STATIC
stills used to be that looping input (`-loop 1 -t`); they are not
any more (Track C §4.1b, `tpad` in the graph). Every still is now a
single decoded frame. The fix for zoompan itself is unchanged: hand
it EXACTLY one decoded frame and let its own `d`/`fps` parameters
generate the whole shot's duration internally.

## Scope

- `STATIC` and `SPLIT_FRAME` never touch `zoompan` - `STATIC` because
  there is nothing to animate, `SPLIT_FRAME` because the composite is
  a second ffmpeg input (`app/renderer/split_screen.py`), not a
  `zoompan` expression. This function still returns `None` for it;
  `slideshow.py` dispatches on the same `None` plus a second still.
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
- `PAN` (A2, 2026-08-31, long_form_direction.md §3) is NOT a `zoompan`
  expression at all any more - the old mechanism zoomed into a fixed
  1.6x working canvas and panned across the small margin that left,
  which measured out to ~4% of the source image regardless of intensity.
  `PAN` now returns a `MovingCropExpression`: a time-varying `crop` over
  the FULL scaled image, so travel is real picture, not a pre-cropped
  fraction of it. See that dataclass and the PAN branch in
  `build_zoompan_expression` for the mechanism and the travel cap
  (`_MAX_PAN_PX_PER_SEC`); `slideshow.py` dispatches on the RETURN TYPE
  (`ZoompanExpression` vs `MovingCropExpression`), not on
  `camera.movement`, to build the right filter chain.
- `PAN`'s vertical axis (A5, 2026-08-31, long_form_direction.md §3) is
  the SAME mechanism mirrored onto `y` - same intensity-times-range
  arithmetic, same `_MAX_PAN_PX_PER_SEC` cap, only the axis and the
  ffmpeg runtime variable (`iw`->`ih`) change. Selected by
  `camera.direction in (UP, DOWN)`; legal only on a landscape canvas,
  enforced by the Shot Planner's validator (`app/planners/shot/
  planner.py::_make_validator`), not here - this module stays a pure
  renderer concern (canon 3.1) and still degrades sanely if a Timeline
  somehow carries the illegal combination anyway.
"""

from dataclasses import dataclass

from app.schemas.timeline import Camera, CameraDirection, CameraMovement

# At intensity=1.0, a zoom shot travels from 1.0x to this multiplier over
# its whole duration - subtle by design (Principle 7, cinematic
# continuity: this must read as documentary motion, not a music-video
# zoom). At the Camera default (intensity=0.15) that is a gentle ~7.5%
# zoom across a shot, matching the module docstring's own "slow push".
_MAX_ZOOM_DELTA = 0.5
# PAN's travel ceiling (A2, long_form_direction.md §3 - moving-crop
# mechanism replacing the old zoompan-over-a-1.6x-canvas approach, which
# is why `_MAX_PAN_ZOOM_DELTA` is gone: there is no zoom headroom left to
# bound). Shared by A5's vertical mirror unchanged - "the SAME
# intensity-times-range and px/second-cap arithmetic", not a second
# travel policy for the new axis. Measured against a real archival photo
# (horizontal axis): full image-relative
# travel reads as "a camera" at 5.00s (311 px/s) and a whip pan below 3s
# (691 px/s at 2.25s, 889 px/s - 123% of frame width per second - at
# 1.75s). `retention_fast`/`archival_montage` carry the most pans on the
# shortest shots, so travel is capped to this many pixels per second of
# shot duration, on top of (not instead of) `camera.intensity` scaling
# the uncapped travel - a short shot travels LESS, never faster. Picked
# just above the 5.00s figure so a full-length shot is untouched by the
# cap and only shorter shots give something up; UNMEASURED below 5s - a
# starting point awaiting the viewing pass called for in the plan, not a
# validated number.
_MAX_PAN_PX_PER_SEC = 320.0
# The oversized working canvas every non-PAN Ken Burns shot is scaled to
# before zoompan runs, so zooming resamples real extra pixels rather than
# upscaling an already-target-resolution frame. Large enough to cover the
# zoom delta above with margin. PAN (A2) no longer uses this - it scales
# to the full image instead, so it can traverse real picture rather than
# a pre-cropped fraction of it.
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


@dataclass(frozen=True)
class MovingCropExpression:
    """PAN's mechanism (A2 horizontal, A5 vertical, long_form_direction.md
    §3) - a time-varying `crop` over the FULL scaled image, not a
    `zoompan` region shrunk into a 1.6x-oversized working canvas.
    Deliberately its own shape, not a `ZoompanExpression`: there is no
    `zoom` here (the crop window never resizes, only translates), so a
    fake `zoom_expr="1.0"` would invite `slideshow.py` to wrap it in the
    wrong filter chain (`zoompan` cannot see a `frames`-long stream from
    one decoded frame - `crop` needs an already-materialised per-frame
    stream instead, e.g. `tpad`).

    Exactly one axis travels per shot - `slideshow.py`'s
    `_ken_burns_pan_filter` dispatches on which:

    - Horizontal (A2, LEFT/RIGHT/undirected): `x_expr` is the moving
      expression, `y_expr` is `None` - the filter hard-codes a literal
      `0` for `y` (no quoting), exactly as it did before A5 existed, so
      this path is byte-identical.
    - Vertical (A5, UP/DOWN): `y_expr` is the moving expression and
      `x_expr` is the literal string `"0"` (the "centred literal" the
      plan asks for - after A5's `scale={out_w}:-2`, the scaled width
      already equals the output width, so `0` is the only valid, and
      therefore centred, crop offset - the exact mirror of horizontal's
      own literal-`0` `y`).

    Both `x_expr`/`y_expr` are written in ffmpeg's OWN runtime variables
    (`iw`/`ih` - the scaled frame's real width/height, `n` - the output
    frame number) rather than a Python-computed pixel count, so the same
    expression is correct for any source image without this module
    needing the probed dimensions (mirrors how the plan's own mechanism
    note writes it)."""

    x_expr: str
    y_expr: str | None = None


# Geometric centre — today's behaviour, and the OQ-2 fallback when no
# subject focal is known. Byte-identical strings so existing tests and
# cached expressions stay stable when focal is None or (0.5, 0.5).
_CENTRE_X_EXPR = "iw/2-(iw/zoom/2)"
_CENTRE_Y_EXPR = "ih/2-(ih/zoom/2)"


@dataclass(frozen=True)
class AimedCrop:
    """Pre-zoompan crop of the `force_original_aspect_ratio=increase`
    canvas, aimed at an original-image focal (RV-Q1).

    `crop_x`/`crop_y` are the top-left of the canvas-sized window in the
    scaled frame. `residual_fx`/`residual_fy` are the subject's location
    *inside that crop* (0..1) — the value zoompan must consume, not the
    original-image focal.
    """

    scaled_w: int
    scaled_h: int
    crop_x: int
    crop_y: int
    residual_fx: float
    residual_fy: float


def scale_increase_size(
    orig_w: int, orig_h: int, canvas_w: int, canvas_h: int
) -> tuple[int, int]:
    """Match ffmpeg `scale=cw:ch:force_original_aspect_ratio=increase`.

    Measured on ffmpeg 9.0: 600×800 → scale=2048:1152:increase yields
    2048×2731 (`round(2048 * 800 / 600)`).
    """
    tmp_w = canvas_h * orig_w / orig_h
    tmp_h = canvas_w * orig_h / orig_w
    if tmp_w >= canvas_w:
        return int(round(tmp_w)), canvas_h
    return canvas_w, int(round(tmp_h))


def compute_aimed_crop(
    orig_w: int,
    orig_h: int,
    canvas_w: int,
    canvas_h: int,
    fx: float,
    fy: float,
) -> AimedCrop:
    """Aim a canvas-sized crop at (fx, fy) in original-image space.

    Clamps the crop inside the scaled frame, then reports where the
    subject landed *inside the crop* so zoompan can finish the aim
    instead of being fed original-space coordinates (RV-Q1).
    """
    scaled_w, scaled_h = scale_increase_size(orig_w, orig_h, canvas_w, canvas_h)
    desired_x = fx * scaled_w - canvas_w / 2.0
    desired_y = fy * scaled_h - canvas_h / 2.0
    crop_x = int(round(max(0.0, min(float(scaled_w - canvas_w), desired_x))))
    crop_y = int(round(max(0.0, min(float(scaled_h - canvas_h), desired_y))))
    residual_fx = max(0.0, min(1.0, (fx * scaled_w - crop_x) / canvas_w))
    residual_fy = max(0.0, min(1.0, (fy * scaled_h - crop_y) / canvas_h))
    return AimedCrop(
        scaled_w=scaled_w,
        scaled_h=scaled_h,
        crop_x=crop_x,
        crop_y=crop_y,
        residual_fx=residual_fx,
        residual_fy=residual_fy,
    )


def ken_burns_crop_and_zoompan_focal(
    orig_w: int,
    orig_h: int,
    canvas_w: int,
    canvas_h: int,
    focal: tuple[float, float] | None,
) -> tuple[int | None, int | None, tuple[float, float] | None]:
    """Return `(crop_x, crop_y, residual_focal)` for `_ken_burns_filter`.

    None/centre focal → `(None, None, None)` so the filter string stays
    today's centred `crop=w:h` and centre zoompan expressions.
    """
    if focal is None or focal == (0.5, 0.5):
        return None, None, None
    aimed = compute_aimed_crop(orig_w, orig_h, canvas_w, canvas_h, focal[0], focal[1])
    residual: tuple[float, float] | None = (aimed.residual_fx, aimed.residual_fy)
    if abs(aimed.residual_fx - 0.5) < 1e-4 and abs(aimed.residual_fy - 0.5) < 1e-4:
        residual = None
    return aimed.crop_x, aimed.crop_y, residual


def _focal_xy_exprs(focal: tuple[float, float] | None) -> tuple[str, str]:
    """Crop window aimed at `focal` (normalised 0..1), clamped inside the
    frame. None / (0.5, 0.5) keep the historical centre strings exactly.
    Used by SLOW_ZOOM / SLOW_PUSH / PULL_BACK / PUNCH_IN only — PAN keeps
    its own directional x (OQ-2)."""
    if focal is None or focal == (0.5, 0.5):
        return _CENTRE_X_EXPR, _CENTRE_Y_EXPR
    fx, fy = focal
    # clamp(fx*iw - iw/zoom/2, 0, iw - iw/zoom) via portable min/max.
    x_expr = f"min(max({fx:.6f}*iw-iw/zoom/2,0),iw-iw/zoom)"
    y_expr = f"min(max({fy:.6f}*ih-ih/zoom/2,0),ih-ih/zoom)"
    return x_expr, y_expr


def build_zoompan_expression(
    camera: Camera,
    *,
    frames: int,
    focal: tuple[float, float] | None = None,
    canvas_w: int | None = None,
    canvas_h: int | None = None,
    duration_s: float | None = None,
) -> ZoompanExpression | MovingCropExpression | None:
    """`None` means "no motion" (STATIC, SPLIT_FRAME, or an intensity of
    0). STATIC is a plain tpad still; SPLIT_FRAME is a two-input
    composite in `split_screen.py` when a second still exists, else the
    same tpad path. `frames` is the shot's total OUTPUT frame count
    (`round(duration_s * fps)`, already computed by the caller - D5's
    "compute it in exactly one place" discipline).

    `focal` (OQ-2) is an optional normalised subject point in image
    space. When set, zoom/push/punch aim the crop at it (clamped). PAN
    does not retarget its x (unchanged by A2 - see `MovingCropExpression`
    and the PAN branch below); STATIC/SPLIT_FRAME stay out.

    `canvas_w`/`canvas_h`/`duration_s` are PAN-only (A2/A5's moving-crop
    travel cap needs the real output width/height and the shot's real
    duration in seconds - none is derivable from `frames`/`focal` alone).
    `canvas_h` is only actually consulted for a vertical (UP/DOWN) pan;
    every other movement, and a horizontal pan, ignores it. Every other
    movement ignores all three; passing them unconditionally from both
    call sites in `slideshow.py` is harmless and simpler than gating the
    call on `camera.movement`."""
    if camera.movement in (CameraMovement.STATIC, CameraMovement.SPLIT_FRAME):
        return None
    frames = max(frames, 1)
    last_frame = max(frames - 1, 1)

    if camera.movement == CameraMovement.PUNCH_IN:
        return build_punch_in_expression(camera, frames=frames, focal=focal)

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
        x_expr, y_expr = _focal_xy_exprs(focal)
        return ZoompanExpression(
            zoom_expr=zoom_expr,
            x_expr=x_expr,
            y_expr=y_expr,
        )

    if camera.movement == CameraMovement.PAN:
        if camera.intensity <= 0:
            return None  # intensity 0 - no motion, not a divide-by-zero
        if canvas_w is None or duration_s is None:
            # A caller bug, not a data/intensity case - both real call
            # sites in slideshow.py always supply these. Loud on purpose
            # rather than silently degrading to no motion, which would
            # hide a wiring mistake behind what looks like a valid render.
            raise ValueError(
                "PAN (A2 moving-crop) requires canvas_w and duration_s"
            )
        # Same travel policy on both axes (A5 mirrors A2, not a second
        # policy): intensity's share of the full scaled image, capped in
        # absolute pixels so a short shot travels LESS rather than FASTER
        # (the plan's own instruction: "let a short shot simply travel
        # less"). Computed once here and reused by whichever axis moves.
        cap_px = _MAX_PAN_PX_PER_SEC * duration_s

        if camera.direction in (CameraDirection.UP, CameraDirection.DOWN):
            # Vertical (A5) - gated to landscape canvases by the Shot
            # Planner's validator (`_make_validator`), not here: this is a
            # renderer concern only (canon 3.1), and it must still render
            # SOMETHING sane if a Timeline somehow carries an illegal
            # combination (e.g. an old/hand-built Timeline predating the
            # validator).
            if canvas_h is None:
                raise ValueError(
                    "PAN (A5 vertical moving-crop) requires canvas_h for "
                    "an UP/DOWN direction"
                )
            # DOWN means the camera reveals the frame moving downward
            # (pans from the top of the image toward the bottom); UP
            # reverses it (pans from the bottom toward the top) - the
            # exact mirror of LEFT/RIGHT below, and DOWN is picked as the
            # sensible undirected default for the same "reading order"
            # reasoning RIGHT is the horizontal default. Focal deliberately
            # does NOT retarget PAN y, mirroring x below: a pan does not
            # retarget on its own axis of travel.
            top_to_bottom = camera.direction != CameraDirection.UP
            progress = f"(n/{last_frame})" if top_to_bottom else f"(1-n/{last_frame})"
            # `ih` - the moving-crop's scaled input height at ffmpeg eval
            # time, mirroring `iw` below. The outer max(...,0) only
            # clamps a negative OFFSET (a source shorter than the output
            # after PAN's width-only scale) - it does NOT make `crop`
            # itself succeed when the scaled height is smaller than
            # `canvas_h`: `crop`'s own target size is the literal
            # `canvas_h`, independent of this expression, so ffmpeg still
            # refuses to configure the filter in that case (confirmed by
            # a real render, A5's verification pass - a portrait source
            # this task calls "tall" (height/width >= 1.5) scaled via a
            # horizontal PAN's `scale=-2:{h}` is ALWAYS narrower than a
            # 1280-wide canvas, and the mirror is equally possible here
            # for an extremely wide, short source on PAN's `scale=
            # {w}:-2`). Not newly introduced by A5 - `_ken_burns_pan_filter`
            # inherits it from A2's own horizontal branch below - and
            # already correctly out of scope per that branch's own
            # comment ("a mismatched aspect ratio, not this slice's
            # concern"); recorded here precisely rather than repeating
            # A2's slightly optimistic "guards ... so that case degrades
            # to no travel" claim, which undersold what the guard does.
            y_expr = (
                f"max(min({camera.intensity:.6f}*(ih-{canvas_h}),{cap_px:.6f}),0)"
                f"*{progress}"
            )
            return MovingCropExpression(x_expr="0", y_expr=y_expr)

        # Horizontal (A2, unchanged) - LEFT means the camera reveals the
        # frame moving leftward (pans from the right side of the image
        # toward the left); anything else (RIGHT, or an undirected/IN/OUT
        # pan, which is not a meaningful combination but must never crash)
        # defaults to a left-to-right pan. Focal deliberately does NOT
        # retarget PAN x (OQ-2, restated for A2's mechanism): a pan does
        # not retarget on its own axis of travel - the directional pan IS
        # the motion.
        left_to_right = camera.direction != CameraDirection.LEFT
        progress = f"(n/{last_frame})" if left_to_right else f"(1-n/{last_frame})"
        # Travel is intensity's share of the FULL scaled image width
        # (`iw` - the moving-crop's input width at ffmpeg eval time; the
        # working canvas IS the whole picture now, A2's whole point). The
        # outer max(...,0) only clamps a negative OFFSET; it does NOT
        # make `crop` succeed when the scaled width is smaller than
        # `canvas_w` (`crop`'s own target size is the literal `canvas_w`)
        # - confirmed by a real render in A5's verification pass, where a
        # portrait source scaled via THIS branch's `scale=-2:{h}` came out
        # narrower than a 1280-wide canvas and ffmpeg refused to configure
        # the filter. A mismatched-aspect-ratio source is out of scope
        # for A2 (this is exactly what A5's vertical axis is for), but
        # the guard's actual coverage is corrected here rather than
        # repeating A2's original "degrades to no travel" claim, which
        # overstated it - see the y_expr branch above for the mirror.
        x_expr = (
            f"max(min({camera.intensity:.6f}*(iw-{canvas_w}),{cap_px:.6f}),0)"
            f"*{progress}"
        )
        return MovingCropExpression(x_expr=x_expr)

    return None


# Punch-in reaches noticeably further than a slow-drift Ken Burns shot in
# the SAME duration (motion_new_styles_and_long_form_videos.md, Track B
# Tier 1 "fast-cut / retention") - it needs to read as a deliberate snap
# within a second or two, not a gentle push across 3-8s. A separate,
# larger ceiling than `_MAX_ZOOM_DELTA` on purpose: reusing the slow-drift
# constant would produce a step too small to register as a "punch" at
# typical fast-cut shot durations.
_MAX_PUNCH_ZOOM_DELTA = 0.9


def punch_in_frame_offsets(
    camera: Camera, *, frames: int, num_punches: int = 2
) -> list[int] | None:
    """Frame indices where a punch snaps, or None when the shot has no
    punch (same guards as `build_punch_in_expression`). Shared with
    `app/renderer/sfx.py` so a whoosh lands on the same frame the zoom
    steps, not a reconstructed guess."""
    if camera.intensity <= 0:
        return None
    frames = max(frames, 1)
    last_frame = max(frames - 1, 1)
    if num_punches < 1 or frames < num_punches * 2:
        return None
    max_zoom = 1.0 + camera.intensity * _MAX_PUNCH_ZOOM_DELTA
    if max_zoom <= 1.0:
        return None
    return [round(last_frame * (i + 1) / (num_punches + 1)) for i in range(num_punches)]


def build_punch_in_expression(
    camera: Camera,
    *,
    frames: int,
    num_punches: int = 2,
    focal: tuple[float, float] | None = None,
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
    punch_frames = punch_in_frame_offsets(camera, frames=frames, num_punches=num_punches)
    if not punch_frames:
        return None
    frames = max(frames, 1)
    max_zoom = 1.0 + camera.intensity * _MAX_PUNCH_ZOOM_DELTA
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

    x_expr, y_expr = _focal_xy_exprs(focal)
    return ZoompanExpression(
        zoom_expr=zoom_expr,
        x_expr=x_expr,
        y_expr=y_expr,
    )
