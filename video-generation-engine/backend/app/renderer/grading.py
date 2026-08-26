"""Per-style colour grade (motion_new_styles_and_long_form_videos.md
§2.4 Tier 1 - "the grade costs no extra encode... highest visual-impact-
per-day item in the document").

Joins the SAME video-filter pass captions and the watermark already share
(`app/workflow/steps/render.py`) - one more `filter_complex` fragment on
the one re-encode neither of those can avoid, never a second pass.
Ordered FIRST in that chain (grade, then captions, then watermark): text
and the logo should sit crisp on top of the graded image, not be graded
themselves.

## Fingerprint (I5) - deliberately NOT a new parameter, and here is why

R2 (2026-08-16, `fingerprint.py`'s own docstring) is the standing lesson:
a render input read from live config at render time, but never hashed,
serves a stale cached render with no error. This module does not repeat
that mistake, but it also does not need a new fingerprint parameter to
avoid it: `STYLE_GRADES` below is a FIXED code-level lookup, not a
`Settings` value - the grade for a given style can only change if the
code itself changes (which invalidates test fixtures anyway) or if
`Timeline.metadata.render_style` itself changes, and that field is
ALREADY part of `compute_render_fingerprint`'s payload (via the whole
timeline document dump, `render_style` is not in `_TIMELINE_BOOKKEEPING_
FIELDS`) - verified directly, not assumed, before this module was
written. **If grade parameters ever become independently tunable via
`Settings`** (the way `music_bed_gain_db` is), THAT would need adding to
the fingerprint explicitly, exactly like R2's own fix - this module
would stop being safe by construction the moment that happens.
"""

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class StyleGrade:
    """ffmpeg `eq` filter parameters. `1.0`/`1.0`/`0.0` (contrast/
    saturation/brightness) is the identity - a style with exactly these
    values is treated as "no grade" (see `grade_filter_fragment`) so a
    style added later with a deliberately neutral look never pays for a
    no-op filter in the chain."""

    contrast: float
    saturation: float
    brightness: float


# Contrast/saturation/brightness only (no gamma, no tint) - the smallest
# set of `eq` parameters that reads as a distinct look, chosen for this
# first slice over `colorbalance`/gamma/vignette/grain (plan §2.4 groups
# all of those under one Tier-1 item) to keep this change reviewable as
# one coherent piece; the rest are a natural follow-up on the SAME
# fragment-composition point, not a redesign. Keyed by the same style
# names `STYLE_PACING_BANDS` (`app/script/styles.py`) uses - one
# vocabulary, not two.
STYLE_GRADES: dict[str, StyleGrade] = {
    "documentary_archival": StyleGrade(contrast=1.05, saturation=0.85, brightness=0.0),
    "retention_fast": StyleGrade(contrast=1.15, saturation=1.25, brightness=0.02),
    "stillness": StyleGrade(contrast=0.95, saturation=0.75, brightness=-0.02),
    # Feature B (style_extensions.md §4.3): archival-montage look -
    # punchier than documentary_archival's muted grade (harder cutting
    # wants images that pop between fast cuts) but well short of
    # retention_fast's saturated social-pop; the footage stays archival
    # in character. Starting point, not measured - revisit after a real
    # viewing pass, exactly like the pacing numbers in styles.py.
    "archival_montage": StyleGrade(contrast=1.10, saturation=1.05, brightness=0.01),
}


def grade_filter_fragment(
    render_style: str | None, input_label: str, output_label: str
) -> str | None:
    """`None` means "skip this fragment entirely" - now only one case
    reaches it (see the R6 fix below), plus the identity-grade case:

    - A style whose grade is exactly the identity (`contrast=1.0,
      saturation=1.0, brightness=0.0`) - not currently true of any
      registered style, but kept as an explicit check so a future
      deliberately-neutral style never pays for a no-op `eq` filter.

    **Fixed 2026-08-18 (motion_new_styles_and_long_form_videos.md
    §13.6, "R6"):** `render_style is None` used to mean "no grade at
    all" here while meaning "resolve via `settings.default_render_style`"
    in `resolve_constraint_bundle` (`app/script/styles.py`) - so a
    style-less project and an explicit `documentary_archival` one
    produced IDENTICAL planning constraints but DIFFERENT pixels, once
    `documentary_archival` gained a real grade. One sentinel now has one
    meaning: `None` and an unrecognised style name both resolve through
    `settings.default_render_style` here too, exactly like
    `resolve_constraint_bundle` already does. This is a deliberate,
    user-confirmed decision that `documentary_archival` IS the real
    default look, not merely a named absence of one - it changes the
    output bytes of every existing style-less project, correctly
    detected as a re-render by the fingerprint (I5), since
    `render_style` is already part of `compute_render_fingerprint`'s
    payload."""
    grade = STYLE_GRADES.get(render_style or settings.default_render_style)
    if grade is None:
        grade = STYLE_GRADES.get(settings.default_render_style)
    if grade is None:
        return None
    if grade.contrast == 1.0 and grade.saturation == 1.0 and grade.brightness == 0.0:
        return None
    return (
        f"[{input_label}]eq=contrast={grade.contrast}:saturation={grade.saturation}:"
        f"brightness={grade.brightness}[{output_label}]"
    )
