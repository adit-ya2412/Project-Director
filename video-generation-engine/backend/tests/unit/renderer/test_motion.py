"""`app/renderer/motion.py::build_duration_fit_fragment` (A2) - pure
arithmetic, no ffmpeg needed. `probe_media` itself (the Pillow-then-
ffprobe classification) needs real files and a real ffprobe subprocess,
so it is proven against real media in
`tests/integration/test_motion_classification.py` instead.
"""

from app.renderer.motion import build_duration_fit_fragment


def test_negligible_gap_needs_no_filter_at_all():
    assert build_duration_fit_fragment(actual_duration_s=3.001, target_duration_s=3.0) is None


def test_too_long_clip_is_trimmed():
    fragment = build_duration_fit_fragment(actual_duration_s=5.0, target_duration_s=3.2)
    assert fragment == "trim=duration=3.200,setpts=PTS-STARTPTS"


def test_too_short_clip_holds_its_last_frame():
    """DECIDED 2026-08-18 (Q4): hold the last frame via `tpad`, not a
    loop or slow-motion - see the function's own docstring for why."""
    fragment = build_duration_fit_fragment(actual_duration_s=3.0, target_duration_s=3.5)
    assert fragment == "tpad=stop_mode=clone:stop_duration=0.500"


def test_worst_case_gap_from_the_real_fixture_is_handled():
    """The real, measured bound (A2): because `fal_video.py` requests
    `round(shot.duration_s)`, the gap this ever needs to cover is at most
    +-0.5s - proven here at that exact boundary, not merely below it."""
    fragment = build_duration_fit_fragment(actual_duration_s=3.5, target_duration_s=3.0)
    assert fragment == "trim=duration=3.000,setpts=PTS-STARTPTS"
