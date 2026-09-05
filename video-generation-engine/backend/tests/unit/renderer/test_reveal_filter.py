"""`_reveal_filter`/`_REVEAL_TRANSITIONS`/`_per_shot_filter`'s F5 dispatch
(illustrated_faceless.md §2/F5) - pure filter-graph string construction,
no ffmpeg needed, mirroring `test_slideshow_argv.py`'s/`test_parallax.py`'s
own shape.

The mechanism (a progressive reveal of a shot's own PRIMARY static
picture, never a `ShotLayer`): a solid substrate-colour canvas and the
shot's own normalised picture, both held for the shot's own full
`frames`/`fps` duration, combined with one `xfade` wipe transition and
trimmed back to the shot's own exact duration. `xfade`'s two wipe
directions were measured directly (a synthetic red/green clip pair, this
ffmpeg build, illustrated_faceless.md §7's P-IF-F5 log entry has the exact
readout) to confirm which `RevealDirection` maps to which transition name
- this file pins the mapping, not the ffmpeg behaviour itself (that is
what the plan's own log records as measured).
"""

import pytest

from app.renderer.ken_burns import build_zoompan_expression
from app.renderer.motion import MediaKind, MediaProbe
from app.renderer.slideshow import (
    _REVEAL_TRANSITIONS,
    RenderSettings,
    _effective_reveal_window,
    _normalize_filter,
    _per_shot_filter,
    _reveal_filter,
)
from app.schemas.timeline import Camera, CameraMovement, RevealDirection, Shot, ShotIntent
from app.timeline.narration_fit import _clamp_reveal_window


def _settings() -> RenderSettings:
    return RenderSettings(width=320, height=240, fps=24, pixel_format="yuv420p")


def _reveal_shot(
    shot_id: str,
    *,
    direction: RevealDirection,
    start_offset_s: float,
    duration_s: float,
    shot_duration_s: float = 3.0,
) -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=shot_duration_s,
        camera=Camera(movement=CameraMovement.STATIC),
        reveal_direction=direction,
        reveal_start_fragment=1,
        reveal_end_fragment=1,
        reveal_start_offset_s=start_offset_s,
        reveal_duration_s=duration_s,
    )


# ---------------------------------------------------------------------------
# The direction -> xfade transition mapping (measured, see this file's own
# docstring and the plan's P-IF-F5 log entry).
# ---------------------------------------------------------------------------


def test_reveal_transitions_cover_every_direction_except_none():
    assert set(_REVEAL_TRANSITIONS) == {
        RevealDirection.BOTTOM_TO_TOP,
        RevealDirection.LEFT_TO_RIGHT,
    }


def test_bottom_to_top_maps_to_wipeup():
    """Measured: `wipeup` reveals the SECOND input starting at the BOTTOM
    of the frame, sweeping the boundary upward - a bar climbing from its
    own baseline."""
    assert _REVEAL_TRANSITIONS[RevealDirection.BOTTOM_TO_TOP] == "wipeup"


def test_left_to_right_maps_to_wiperight():
    """Measured: `wiperight` reveals the SECOND input starting at the
    LEFT, sweeping rightward - an arrow or line drawing itself."""
    assert _REVEAL_TRANSITIONS[RevealDirection.LEFT_TO_RIGHT] == "wiperight"


# ---------------------------------------------------------------------------
# `_reveal_filter` - the filter-graph shape.
# ---------------------------------------------------------------------------


def test_reveal_filter_shape_has_base_full_xfade_and_trim_stages():
    settings = _settings()
    fragment = _reveal_filter(
        0,
        settings,
        "n0",
        direction=RevealDirection.BOTTOM_TO_TOP,
        start_offset_s=1.0,
        duration_s=0.5,
        frames=72,  # 3.0s at 24fps
        substrate_color="0xEADECD",
    )
    stages = fragment.split(";")
    assert len(stages) == 4
    base, full, xfade, trim = stages

    # Substrate canvas: same colour literal, this shot's own full
    # duration (frames/fps = 3.0s), namespaced off "n0".
    assert base == "color=c=0xEADECD:s=320x240:r=24:d=3.0[n0_rvbase]"

    # The picture chain is `_normalize_filter` itself, reused verbatim -
    # not re-derived - just relabelled.
    expected_full = _normalize_filter(0, settings, "n0_rvfull", hold_s=(72 - 1) / 24)
    assert full == expected_full

    # The wipe: bottom_to_top -> wipeup, at the resolved offset/duration.
    assert xfade == (
        "[n0_rvbase][n0_rvfull]xfade=transition=wipeup:" "duration=0.500000:offset=1.000000[n0_rvx]"
    )

    # Trimmed back to the shot's own exact duration and re-labelled to
    # the caller's own output label.
    assert trim == "[n0_rvx]trim=0:3.000000,setpts=PTS-STARTPTS,format=yuv420p[n0]"


def test_reveal_filter_left_to_right_uses_wiperight():
    fragment = _reveal_filter(
        0,
        _settings(),
        "n0",
        direction=RevealDirection.LEFT_TO_RIGHT,
        start_offset_s=0.2,
        duration_s=1.0,
        frames=48,
        substrate_color="0x101418",
    )
    assert "xfade=transition=wiperight:duration=1.000000:offset=0.200000" in fragment


def test_reveal_filter_labels_are_namespaced_per_shot():
    """Two reveal shots in the SAME multi-shot filter graph must never
    collide - each stage's own intermediate label carries the caller's
    `label`, mirroring `_glitch_transition_filter`'s own `f"g{out_label}"`
    discipline."""
    frag_a = _reveal_filter(
        0,
        _settings(),
        "n0",
        direction=RevealDirection.BOTTOM_TO_TOP,
        start_offset_s=0.5,
        duration_s=0.5,
        frames=24,
        substrate_color="0xAAAAAA",
    )
    frag_b = _reveal_filter(
        1,
        _settings(),
        "n1",
        direction=RevealDirection.BOTTOM_TO_TOP,
        start_offset_s=0.5,
        duration_s=0.5,
        frames=24,
        substrate_color="0xAAAAAA",
    )
    labels_a = {"n0_rvbase", "n0_rvfull", "n0_rvx"}
    labels_b = {"n1_rvbase", "n1_rvfull", "n1_rvx"}
    for label in labels_a:
        assert label in frag_a and label not in frag_b
    for label in labels_b:
        assert label in frag_b and label not in frag_a


# ---------------------------------------------------------------------------
# `_per_shot_filter`'s F5 dispatch - checked BEFORE Ken Burns, never
# alongside it (a reveal shot is always camera.movement=static, per
# `Shot._reveal_requires_static_camera`, so Ken Burns would return no
# expression anyway - this proves the dispatch is deliberate).
# ---------------------------------------------------------------------------


def test_per_shot_filter_dispatches_to_reveal_when_set():
    settings = _settings()
    shot = _reveal_shot(
        "sh1", direction=RevealDirection.BOTTOM_TO_TOP, start_offset_s=1.0, duration_s=0.5
    )
    probe = MediaProbe(kind=MediaKind.STILL, width=320, height=240)
    fragment = _per_shot_filter(0, shot, probe, settings, "n0", substrate_color="0xEADECD")
    assert "xfade=transition=wipeup" in fragment
    assert "zoompan" not in fragment


def test_per_shot_filter_without_a_reveal_takes_the_plain_static_path():
    settings = _settings()
    shot = Shot(
        id="sh1",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        camera=Camera(movement=CameraMovement.STATIC),
    )
    probe = MediaProbe(kind=MediaKind.STILL, width=320, height=240)
    fragment = _per_shot_filter(0, shot, probe, settings, "n0")
    assert "xfade" not in fragment
    assert "tpad=stop_mode=clone" in fragment


def test_per_shot_filter_reveal_shot_never_reaches_ken_burns_arithmetic():
    """Sanity check on the test fixtures themselves: a reveal shot's own
    camera (STATIC) really does make `build_zoompan_expression` return no
    expression, confirming `_per_shot_filter`'s reveal branch is reached
    via `expr is None` territory rather than racing Ken Burns for it."""
    shot = _reveal_shot(
        "sh1", direction=RevealDirection.LEFT_TO_RIGHT, start_offset_s=0.0, duration_s=1.0
    )
    assert (
        build_zoompan_expression(
            shot.camera, frames=72, focal=None, canvas_w=320, canvas_h=240, duration_s=3.0
        )
        is None
    )


# ---------------------------------------------------------------------------
# The fps/xfade-length invariant (review finding, 2026-09-05) - see
# illustrated_faceless.md's own §8.8 for the full account, including the
# TWO corrections a from-scratch measurement made to the original review:
#
# 1. The review hypothesised a `render_fps >= 30` dependency, derived from
#    modelling the tpad-cloned picture stream's effective length (as far as
#    `xfade`'s own `first + second - transition` rule is concerned) as
#    `hold_s`. Measured (real ffmpeg + exact `nb_read_frames` counts, see
#    the plan): the picture stream's real length is `total_s = frames/fps`
#    (one decoded frame + `hold_s` of clones), not `hold_s` alone - `hold_s`
#    is only the ADDED clone duration. `render_fps=30` was never actually
#    at risk under the review's own formula error.
# 2. The corrected arithmetic (worst-case rounding gap `0.5/fps` against
#    `_REVEAL_MIN_TAIL_S`'s 0.05s margin) puts the REAL threshold at
#    fps >= 10, a factor of 3 more forgiving than the review's fps >= 30 -
#    confirmed by a fine per-fps sweep (fps=9's worst margin: -0.00555s;
#    fps=10 and above: exactly 0.0). This sweep still checks down to fps=5
#    to exercise that real (if currently harmless-in-production) edge.
#
# The FIX (`_effective_reveal_window`, `app/renderer/slideshow.py`) removes
# the threshold entirely rather than padding it - a renderer-side re-clamp
# against the RENDERER's own `total_s`, mirroring `build_two_layer_
# parallax_filter_complex`'s existing `effective_fade_s` shape - so this
# sweep asserts the invariant holds at every fps below 10 too, not merely
# that today's real threshold is safely below the shipped default.
# ---------------------------------------------------------------------------

_FPS_SWEEP = (5, 6, 7, 8, 9, 10, 12, 24, 25, 30, 60)
_DURATION_SWEEP = tuple(round(0.5 + 0.05 * i, 4) for i in range(int((12.0 - 0.5) / 0.05) + 1))


def _xfade_would_run_short(fps: int, duration_s: float, *, mid_shot: bool) -> tuple[bool, dict]:
    """One (fps, duration_s) point: builds the widest reveal window the
    REAL resolver would ever emit for that shot (start=0 for the
    start-to-end case; a third of the way in for the mid-shot case,
    mirroring `resolve_element_reveals`'s own onset-relative arithmetic),
    applies the SAME renderer-side re-clamp `_reveal_filter` itself now
    applies (`_effective_reveal_window` - the fix under test, not a
    second copy of its logic), and checks whether the resulting
    base/full/xfade/trim graph would come out short of `total_s`.
    Returns `(is_short, detail)` so a failing assertion carries the
    exact numbers, not just a bare boolean."""
    frames = max(round(duration_s * fps), 1)
    total_s = frames / fps
    raw_start = duration_s / 3 if mid_shot else 0.0
    start, finish = _clamp_reveal_window(raw_start, duration_s, duration_s=duration_s, shot_id="x")
    reveal_duration = finish - start
    effective_start, effective_duration = _effective_reveal_window(
        start, reveal_duration, total_s=total_s
    )
    xfade_output_s = total_s + total_s - effective_duration  # base + full - transition
    detail = {
        "fps": fps,
        "duration_s": duration_s,
        "frames": frames,
        "total_s": total_s,
        "unclamped_reveal_duration_s": reveal_duration,
        "effective_start_s": effective_start,
        "effective_duration_s": effective_duration,
        "xfade_output_s": xfade_output_s,
        "short_by": total_s - xfade_output_s,
    }
    return xfade_output_s < total_s - 1e-9, detail


def test_xfade_output_never_runs_short_of_the_trim_target_start_to_end_window():
    failures = []
    for fps in _FPS_SWEEP:
        for duration_s in _DURATION_SWEEP:
            is_short, detail = _xfade_would_run_short(fps, duration_s, mid_shot=False)
            if is_short:
                failures.append(detail)
    assert (
        not failures
    ), f"{len(failures)} (fps, duration) points would render short: {failures[:5]}"


def test_xfade_output_never_runs_short_of_the_trim_target_mid_shot_window():
    """The same sweep, but the reveal window starts a THIRD of the way
    into the shot rather than at its very first fragment - a shape the
    start-to-end sweep above cannot exercise, since a mid-shot start
    changes both `reveal_start_s` and how much room is left for
    `reveal_duration_s` before the ceiling."""
    failures = []
    for fps in _FPS_SWEEP:
        for duration_s in _DURATION_SWEEP:
            is_short, detail = _xfade_would_run_short(fps, duration_s, mid_shot=True)
            if is_short:
                failures.append(detail)
    assert (
        not failures
    ), f"{len(failures)} (fps, duration) points would render short: {failures[:5]}"


def test_the_original_review_hypothesis_specifically_fps_24_and_25_never_ran_short():
    """Pins the exact two fps values the ORIGINAL review's own (since-
    corrected) arithmetic flagged as broken. Measurement showed these
    never actually failed even before the fix (the review's formula, not
    the shipped code, was wrong) - kept as its own standing regression
    guard, distinct from the broader sweep above, specifically for the
    values the review named."""
    for fps in (24, 25):
        for duration_s in _DURATION_SWEEP:
            is_short, detail = _xfade_would_run_short(fps, duration_s, mid_shot=False)
            assert not is_short, detail
            is_short, detail = _xfade_would_run_short(fps, duration_s, mid_shot=True)
            assert not is_short, detail


def test_the_corrected_threshold_fps_9_would_have_failed_without_the_fix():
    """Proves the sweep tests above are not vacuous: WITHOUT `_effective_
    reveal_window`'s re-clamp, fps=9 (the real, corrected worst case -
    see this section's own docstring) genuinely runs short. Recomputes
    the UNCLAMPED xfade arithmetic directly, deliberately bypassing the
    fix, so this test would have failed loudly before it existed."""
    fps = 9
    duration_s = 2.6111027756939236  # the measured worst point for fps=9
    frames = max(round(duration_s * fps), 1)
    total_s = frames / fps
    start, finish = _clamp_reveal_window(0.0, duration_s, duration_s=duration_s, shot_id="x")
    reveal_duration = finish - start
    unclamped_xfade_output_s = total_s + total_s - reveal_duration
    assert unclamped_xfade_output_s < total_s, (
        "fps=9's worst point should genuinely run short without the "
        "renderer-side re-clamp - if this assertion fails, the fixture "
        "above no longer reproduces the pre-fix defect"
    )
    # And WITH the fix applied, it no longer does.
    effective_start, effective_duration = _effective_reveal_window(
        start, reveal_duration, total_s=total_s
    )
    fixed_xfade_output_s = total_s + total_s - effective_duration
    assert fixed_xfade_output_s >= total_s - 1e-9


# -- `_effective_reveal_window` in isolation -----------------------------


def test_effective_reveal_window_passes_a_window_already_in_range_unchanged():
    start, duration = _effective_reveal_window(1.0, 2.0, total_s=5.0)
    assert start == 1.0
    assert duration == 2.0


def test_effective_reveal_window_shrinks_a_duration_that_would_outlast_total_s():
    start, duration = _effective_reveal_window(0.0, 0.45, total_s=0.4)
    assert start == 0.0
    assert duration == 0.4


def test_effective_reveal_window_shrinks_duration_to_what_remains_after_a_late_start():
    start, duration = _effective_reveal_window(0.3, 0.3, total_s=0.4)
    assert start == 0.3
    assert duration == pytest.approx(0.1)


def test_effective_reveal_window_clamps_a_start_beyond_total_s_and_leaves_no_duration():
    start, duration = _effective_reveal_window(5.0, 1.0, total_s=2.0)
    assert start == 2.0
    assert duration == 0.0


def test_effective_reveal_window_never_goes_negative():
    start, duration = _effective_reveal_window(-1.0, -1.0, total_s=2.0)
    assert start == 0.0
    assert duration == 0.0


def test_effective_reveal_window_start_plus_duration_never_exceeds_total_s():
    """The property that actually matters - checked directly rather than
    only inferred from the specific cases above, across a small grid of
    inputs that may or may not need clamping."""
    total_s = 3.0
    for raw_start in (-1.0, 0.0, 0.5, 1.5, 2.9, 3.0, 4.0):
        for raw_duration in (-1.0, 0.0, 0.1, 1.0, 2.9, 3.0, 4.0):
            start, duration = _effective_reveal_window(raw_start, raw_duration, total_s=total_s)
            assert start + duration <= total_s + 1e-9
            assert start >= 0.0
            assert duration >= 0.0
