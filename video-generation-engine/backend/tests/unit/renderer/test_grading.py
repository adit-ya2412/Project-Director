"""`app/renderer/grading.py` (motion_new_styles_and_long_form_videos.md
§2.4, Tier 1) - pure string composition, no ffmpeg needed. The real
`eq` filter graph this produces is verified separately: applied directly
to a real archival photo and visually inspected (2026-08-17), confirming
`retention_fast` reads visibly punchier and `stillness` visibly more
muted than the unmodified original.
"""

from app.core.config import settings
from app.renderer.fingerprint import _TIMELINE_BOOKKEEPING_FIELDS
from app.renderer.grading import STYLE_GRADES, grade_filter_fragment


def test_no_style_resolves_to_the_default_styles_real_grade():
    """R6 fix (§13.6, 2026-08-18, user-confirmed): `render_style=None`
    now resolves through `settings.default_render_style`
    ("documentary_archival") exactly like `resolve_constraint_bundle`
    already does - one sentinel, one meaning, everywhere. A style-less
    project now gets `documentary_archival`'s real grade rather than no
    grade at all; this is a deliberate output-bytes change, not a
    regression."""
    assert grade_filter_fragment(None, "0:v", "graded") == grade_filter_fragment(
        settings.default_render_style, "0:v", "graded"
    )
    assert grade_filter_fragment(None, "0:v", "graded") is not None


def test_an_unrecognised_style_falls_back_to_the_default_the_same_way():
    """Falls back the same way `resolve_constraint_bundle` does - this
    runs deep in the render pipeline, past every place a style name is
    validated at the API boundary."""
    assert grade_filter_fragment("not_a_real_style", "0:v", "graded") == grade_filter_fragment(
        settings.default_render_style, "0:v", "graded"
    )


def test_every_registered_style_produces_a_distinct_fragment():
    fragments = {style: grade_filter_fragment(style, "0:v", "graded") for style in STYLE_GRADES}
    assert all(f is not None for f in fragments.values())
    assert len(set(fragments.values())) == len(fragments)  # no two styles produce the same eq


def test_fragment_labels_are_wired_correctly():
    fragment = grade_filter_fragment("retention_fast", "0:v", "graded")
    assert fragment is not None
    assert fragment.startswith("[0:v]")
    assert fragment.endswith("[graded]")
    assert "eq=" in fragment


def test_retention_fast_is_punchier_than_documentary_archival():
    """Directional sanity check matching the plan's own stated intent
    (§2.4) - retention_fast should read punchier (more contrast, more
    saturated) than the calmer documentary_archival, not merely
    different."""
    fast = STYLE_GRADES["retention_fast"]
    archival = STYLE_GRADES["documentary_archival"]
    assert fast.contrast > archival.contrast
    assert fast.saturation > archival.saturation


def test_stillness_is_more_muted_than_documentary_archival():
    still = STYLE_GRADES["stillness"]
    archival = STYLE_GRADES["documentary_archival"]
    assert still.contrast < archival.contrast
    assert still.saturation < archival.saturation


def test_render_style_field_is_not_excluded_from_the_fingerprint():
    """The whole reason `grading.py` needs no new fingerprint parameter
    (see its own module docstring): `metadata` (which holds
    `render_style`) must not be in the bookkeeping-exclusion set, or a
    style change would silently serve a stale cached render at the old
    look. Checked directly against the real constant, not assumed."""
    assert "metadata" not in _TIMELINE_BOOKKEEPING_FIELDS
