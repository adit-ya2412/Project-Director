"""`app/renderer/grading.py` (motion_new_styles_and_long_form_videos.md
§2.4, Tier 1) - pure string composition, no ffmpeg needed. The real
`eq` filter graph this produces is verified separately: applied directly
to a real archival photo and visually inspected (2026-08-17), confirming
`retention_fast` reads visibly punchier and `stillness` visibly more
muted than the unmodified original.
"""

from app.core.config import settings
from app.renderer.fingerprint import _TIMELINE_BOOKKEEPING_FIELDS
from app.renderer.grading import STYLE_GRADES, StyleGrade, grade_filter_fragment

# The four styles that existed before F1 (illustrated_faceless.md §2.1) -
# used below to scope the pre-existing "every style produces a distinct
# fragment" regression test around the new identity-grade style, which
# deliberately produces NO fragment (see
# test_illustrated_risograph_grade_is_exact_identity_and_costs_nothing).
_PRE_F1_STYLES = ("documentary_archival", "retention_fast", "stillness", "archival_montage")


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
    """Scoped to the four PRE-F1 styles (see `_PRE_F1_STYLES`'s own
    comment): F1 registered two more styles at the exact identity grade,
    which `grade_filter_fragment` deliberately treats as "no grade" (see
    `StyleGrade`'s own docstring) - so extending this loop to `STYLE_GRADES`
    unfiltered would now fail by design, not by regression. Those two are
    covered on their own terms by
    test_illustrated_risograph_grades_are_exact_identity_and_cost_nothing
    below."""
    fragments = {style: grade_filter_fragment(style, "0:v", "graded") for style in _PRE_F1_STYLES}
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


def test_archival_montage_is_punchier_than_archival_but_not_retention_hot():
    """Feature B (style_extensions.md §4.3): the montage look sits
    between documentary_archival's muted grade and retention_fast's
    saturated pop - harder cutting wants images that pop between cuts,
    but the footage stays archival in character. Distinctness from all
    other styles is already enforced by
    test_every_registered_style_produces_a_distinct_fragment above."""
    fragment = grade_filter_fragment("archival_montage", "0:v", "graded")
    assert fragment is not None
    assert fragment.startswith("[0:v]")
    assert fragment.endswith("[graded]")
    assert "eq=" in fragment
    montage = STYLE_GRADES["archival_montage"]
    archival = STYLE_GRADES["documentary_archival"]
    retention = STYLE_GRADES["retention_fast"]
    assert archival.contrast < montage.contrast < retention.contrast
    assert archival.saturation < montage.saturation < retention.saturation


def test_original_four_grades_are_byte_for_byte_unchanged():
    """F1 (illustrated_faceless.md §2.1) added two new `STYLE_GRADES`
    entries. This pins the exact, literal shipped value of the four
    pre-F1 styles so any accidental drift fails loudly here, not just in
    the narrower directional tests above."""
    assert STYLE_GRADES["documentary_archival"] == StyleGrade(
        contrast=1.05, saturation=0.85, brightness=0.0
    )
    assert STYLE_GRADES["retention_fast"] == StyleGrade(
        contrast=1.15, saturation=1.25, brightness=0.02
    )
    assert STYLE_GRADES["stillness"] == StyleGrade(contrast=0.95, saturation=0.75, brightness=-0.02)
    assert STYLE_GRADES["archival_montage"] == StyleGrade(
        contrast=1.10, saturation=1.05, brightness=0.01
    )


def test_illustrated_risograph_grade_is_exact_identity_and_costs_nothing():
    """F1: the risograph palette is baked into the GENERATION PROMPT
    (`shot_planner_styles/illustrated_risograph.md`), not this filter -
    an `eq` grade on top would double-grade already-graded pixels. The
    grade must be EXACTLY the identity (not merely close), because
    `grade_filter_fragment` treats an exact-identity grade as "no grade"
    and skips the filter entirely (`StyleGrade`'s own docstring) - which
    is what makes this cost nothing in the render's filter chain.
    Verified directly, not assumed: a near-but-not-exact identity would
    silently start paying for a no-op filter instead. One row now
    (collapsed from `_vertical`/`_horizontal`, 2026-09-04) - the identity
    value does not vary by canvas, so the collapse changes nothing about
    what either aspect actually renders."""
    grade = STYLE_GRADES["illustrated_risograph"]
    assert (grade.contrast, grade.saturation, grade.brightness) == (1.0, 1.0, 0.0)
    assert grade_filter_fragment("illustrated_risograph", "0:v", "graded") is None


def test_render_style_field_is_not_excluded_from_the_fingerprint():
    """The whole reason `grading.py` needs no new fingerprint parameter
    (see its own module docstring): `metadata` (which holds
    `render_style`) must not be in the bookkeeping-exclusion set, or a
    style change would silently serve a stale cached render at the old
    look. Checked directly against the real constant, not assumed."""
    assert "metadata" not in _TIMELINE_BOOKKEEPING_FIELDS
