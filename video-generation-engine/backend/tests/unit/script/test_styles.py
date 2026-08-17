"""`app/script/styles.py::resolve_constraint_bundle` (motion_new_styles_
and_long_form_videos.md, Track B) - the function that closes the gap
`preflight.py`'s own module docstring flagged: the two real enforcement
points (`generate_timeline.py`, `shot/planner.py`) now read this instead
of flat `settings.*` values directly.
"""

from app.core.config import settings
from app.script.styles import STYLE_PACING_BANDS, resolve_constraint_bundle


def test_none_resolves_byte_identical_to_flat_settings():
    """Every Timeline predating this field has `render_style=None` -
    this must be indistinguishable from the flat settings reads it
    replaced, not merely similar."""
    expected = (
        settings.min_shot_duration_s,
        settings.max_shot_duration_s,
        settings.max_shots_per_project,
    )
    assert resolve_constraint_bundle(None) == expected


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
