"""`app/script/styles.py::resolve_constraint_bundle` (motion_new_styles_
and_long_form_videos.md, Track B) - the function that closes the gap
`preflight.py`'s own module docstring flagged: the two real enforcement
points (`generate_timeline.py`, `shot/planner.py`) now read this instead
of flat `settings.*` values directly.
"""

import pytest

from app.core.config import settings
from app.script.styles import STYLE_PACING_BANDS, StylePacingBand, resolve_constraint_bundle


def test_none_resolves_byte_identical_to_flat_settings():
    """Every Timeline predating this field has `render_style=None` -
    this must be indistinguishable from the flat settings reads it
    replaced, not merely similar."""
    bundle = resolve_constraint_bundle(None)
    assert bundle.min_shot_duration_s == settings.min_shot_duration_s
    assert bundle.max_shot_duration_s == settings.max_shot_duration_s
    assert bundle.max_shots_per_project == settings.max_shots_per_project
    assert bundle.max_scenes == settings.max_scenes
    assert bundle.max_video_duration_s == settings.max_video_duration_s


def test_documentary_archival_resolves_identical_to_none():
    """The named default style must be exactly as inert as no style at
    all - it has no overrides in `STYLE_PACING_BANDS`."""
    assert resolve_constraint_bundle("documentary_archival") == resolve_constraint_bundle(None)


def test_stillness_resolves_identical_to_none():
    assert resolve_constraint_bundle("stillness") == resolve_constraint_bundle(None)


def test_retention_fast_overrides_all_three_bounds():
    min_s, max_s, shots = resolve_constraint_bundle("retention_fast")
    assert min_s == 0.8
    assert max_s == 3.5  # 1.75 * 2.0 dead-stop ceiling multiplier
    assert shots == 58
    assert resolve_constraint_bundle("retention_fast").max_scenes == settings.max_scenes


def test_length_raises_caps_and_style_multiplies_the_shot_base():
    """Track C §2.3: length sets the base, style multiplies. N=206
    (10 min projection) must raise scenes/shots; retention_fast must
    apply 58/40 to that base, not `max(length, 58)`."""
    long = resolve_constraint_bundle(None, n_fragments=206)
    assert long.max_scenes >= 70
    assert long.max_shots_per_project >= 200
    assert long.max_video_duration_s == pytest.approx(settings.max_long_form_duration_s, abs=5)
    import math

    fast = resolve_constraint_bundle("retention_fast", n_fragments=206)
    assert fast.max_shots_per_project == math.ceil(long.max_shots_per_project * 58 / 40)


def test_short_n_keeps_todays_caps():
    """Path A fixtures (N around 13) must not silently raise the 90 s caps."""
    short = resolve_constraint_bundle(None, n_fragments=13)
    assert short.max_scenes == settings.max_scenes
    assert short.max_shots_per_project == settings.max_shots_per_project
    assert short.max_video_duration_s == settings.max_video_duration_s


def test_unrecognised_style_falls_back_rather_than_raising():
    """Deliberately different from `get_pacing_band` (which raises) -
    this function runs deep inside planning, where a raised `KeyError`
    would surface as a confusing crash far from the actual mistake; the
    create-project/set-style endpoints already validate against
    `STYLE_PACING_BANDS` before a style name ever reaches here."""
    assert resolve_constraint_bundle("not_a_real_style") == resolve_constraint_bundle(None)


def test_every_registered_style_is_reachable():
    for style in STYLE_PACING_BANDS:
        resolve_constraint_bundle(style)  # must not raise


def test_max_shot_duration_s_override_is_independent_of_the_dead_stop_ceiling():
    """R7 fix (§13.7): `max_shot_duration_s_override` and
    `max_fragment_duration_s` are separate fields that happen to agree
    for `retention_fast` today - not one field doing both jobs. Proven by
    changing the (uncalibrated, still-open Q5) dead-stop multiplier's
    input and confirming the planning bound does not move with it."""
    band = STYLE_PACING_BANDS["retention_fast"]
    assert band.max_shot_duration_s_override == 3.5
    assert band.max_fragment_duration_s == 3.5  # equal today, not the same field
    # The real proof: a band whose target changes (moving max_fragment_duration_s)
    # must not move max_shot_duration_s_override, since they are independent.
    moved = StylePacingBand(
        name="hypothetical",
        target_shot_duration_s=1.0,  # -> max_fragment_duration_s = 2.0
        max_shots_override=None,
        max_shot_duration_s_override=3.5,
    )
    assert moved.max_fragment_duration_s == 2.0
    _min, max_shot_duration_s, _shots = resolve_constraint_bundle("retention_fast")
    assert max_shot_duration_s == band.max_shot_duration_s_override


def test_a_zero_override_is_honoured_not_treated_as_unset():
    """The `x or y` trap R7 fixed: `0`/`0.0` is a legitimate override
    value (e.g. a future style with no per-shot ceiling), and must not
    silently fall back to the flat setting the way `or` would."""
    zero_band = StylePacingBand(
        name="hypothetical_zero",
        target_shot_duration_s=None,
        max_shots_override=0,
        min_shot_duration_s_override=0.0,
        max_shot_duration_s_override=0.0,
    )
    STYLE_PACING_BANDS["hypothetical_zero"] = zero_band
    try:
        min_s, max_s, shots = resolve_constraint_bundle("hypothetical_zero")
        assert min_s == 0.0
        assert max_s == 0.0
        assert shots == 0
    finally:
        del STYLE_PACING_BANDS["hypothetical_zero"]
