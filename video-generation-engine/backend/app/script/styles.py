"""Style pacing bands (motion_new_styles_and_long_form_videos.md §3.5.2,
decided 2026-08-17): a small, standalone registry the feasibility check
(`preflight.py`) reads. Track B (2026-08-17) extends this same registry
- `Timeline.metadata.render_style` and the real enforcement points
(`app/workflow/steps/generate_timeline.py`, `app/planners/shot/
planner.py`) now read `resolve_constraint_bundle` below - rather than
duplicating a second copy of these numbers.

Only three styles ship in v1 (plan §2.8: "three presets, not eight" -
every style is a behaviour four planners can regress against).
"""

from dataclasses import dataclass

from app.core.config import settings

# A fast style's dead-stop ceiling is expressed as a multiple of its own
# target shot duration, not a flat constant - a style with a slower
# target should tolerate a proportionally longer outlier fragment before
# it reads as a dead stop. 2x is a starting point, not a measured
# constant (unlike the chars/sec figures in Settings, no real long
# fragment has been rendered against this ceiling yet - see the plan's
# Q5, "target pacing bands per style... blocked on calibration data").
_DEAD_STOP_CEILING_MULTIPLIER = 2.0


@dataclass(frozen=True)
class StylePacingBand:
    """One style's feasibility inputs (plan §3.1, §3.5.2).

    `target_shot_duration_s=None` means this style has no pacing FLOOR
    to check at all - true of every style slower than the fastest
    physically reachable pace (plan §3.1's asymmetry: a script can always
    be cut SLOWER by merging fragments, never faster than one fragment
    per shot, so only fast styles can genuinely be infeasible).
    `max_fragment_duration_s=None` follows the same reasoning for the
    per-shot "dead stop" ceiling (plan §2.5.1) - both are computed from
    `target_shot_duration_s` when it is set, never supplied separately,
    so the two numbers can never drift apart for one style.
    `max_shots_override=None` means "use `settings.max_shots_per_project`
    directly" - only a style whose target pace needs materially more
    shots at the standard duration cap (`retention_fast`) overrides it.
    `min_shot_duration_s_override` follows the same "None = use the flat
    setting" shape, for the planning-time floor a fast style needs
    lowered (plan §2.5 Route 2, §4.2 - `narration_locked` already exempts
    MEASURED durations from this bound regardless, so lowering it only
    affects the Shot Planner's pre-narration estimate, never real,
    reconciled shot lengths).

    `max_shot_duration_s_override` is the Shot Planner's real validation
    bound - a SEPARATE number from `max_fragment_duration_s` below, fixed
    2026-08-18 (motion_new_styles_and_long_form_videos.md §13.7, "R7").
    Before this field existed, `resolve_constraint_bundle` read
    `max_fragment_duration_s` for this purpose - but that property is a
    pre-flight DIAGNOSTIC (the §2.5.1 dead-stop ceiling for a single
    narration FRAGMENT, derived from `_DEAD_STOP_CEILING_MULTIPLIER`,
    which is explicitly uncalibrated - see that constant's own comment),
    not a planning bound. Sharing one number meant Q5's still-open
    calibration of the diagnostic would have silently retuned a real
    planning constraint the moment someone adjusted the multiplier. The
    two numbers happen to be equal for `retention_fast` today (3.5), but
    are now two independent fields that merely agree, not one field
    serving two purposes.
    """

    name: str
    target_shot_duration_s: float | None
    max_shots_override: int | None
    min_shot_duration_s_override: float | None = None
    max_shot_duration_s_override: float | None = None

    @property
    def max_fragment_duration_s(self) -> float | None:
        """Pre-flight ceiling ONLY (plan §2.5.1) - the ceiling a single
        narration fragment must not exceed before it reads as a dead
        stop, used by `preflight.py::check_feasibility`. NOT the Shot
        Planner's validation bound - see `max_shot_duration_s_override`'s
        own docstring for why those stopped being the same field (R7)."""
        if self.target_shot_duration_s is None:
            return None
        return self.target_shot_duration_s * _DEAD_STOP_CEILING_MULTIPLIER


# Registry, keyed by the style name `Timeline.metadata.render_style` also
# uses (plan §2.3) - one vocabulary, not two.
STYLE_PACING_BANDS: dict[str, StylePacingBand] = {
    "documentary_archival": StylePacingBand(
        name="documentary_archival",
        target_shot_duration_s=None,
        max_shots_override=None,
    ),
    "retention_fast": StylePacingBand(
        # 90s / 1.75s/shot =~ 51 shots; budgeted to ~58 for headroom
        # (plan §4.2's "budget ~55-60"). Floor lowered to 0.8s (§2.5
        # Route 2) - a planning-time estimate only, per the docstring
        # above. `max_shot_duration_s_override=3.5` matches
        # `max_fragment_duration_s`'s current value (1.75 * 2.0) - same
        # number today, independent field since R7 (see StylePacingBand's
        # own docstring for why sharing one was the bug).
        name="retention_fast",
        target_shot_duration_s=1.75,
        max_shots_override=58,
        min_shot_duration_s_override=0.8,
        max_shot_duration_s_override=3.5,
    ),
    "stillness": StylePacingBand(
        name="stillness",
        target_shot_duration_s=None,
        max_shots_override=None,
    ),
}


def get_pacing_band(style: str) -> StylePacingBand:
    """Raises `KeyError` on an unknown style name - deliberately, not a
    silent fallback to some default band. An endpoint calling this
    translates the KeyError into a 400 naming the valid styles; guessing
    a band for a typo'd style name would produce a feasibility verdict
    that looks real but checks the wrong thing."""
    return STYLE_PACING_BANDS[style]


def resolve_constraint_bundle(style: str | None) -> tuple[float, float, int]:
    """`(min_shot_duration_s, max_shot_duration_s, max_shots_per_project)`
    for the two REAL enforcement points (`generate_timeline.py`'s
    `_is_fully_planned`, `shot/planner.py`'s `plan()`), style-aware where
    a style overrides a bound and falling back to the flat `settings.*`
    value everywhere it does not.

    `style=None` (a Timeline predating this field, or an explicit
    "no style set yet") resolves via `settings.default_render_style`
    (`"documentary_archival"`, which itself has no overrides at all) -
    so every existing project and fixture gets EXACTLY the bundle it
    always did, byte-for-byte, not a new default that happens to look
    similar. An unrecognised style name (should not happen - the create-
    project endpoint validates against `STYLE_PACING_BANDS` before it
    ever reaches here) falls back the same way rather than raising, since
    this function runs deep inside planning where a raised `KeyError`
    would surface as a confusing crash far from the actual mistake.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        band = STYLE_PACING_BANDS[settings.default_render_style]
    # `if ... is not None else`, not `x or y` (R7, §13.7): an `or` here
    # would fall through to the flat setting for an override of `0`/`0.0`
    # - unreachable with today's three styles, but a live trap for a
    # future one (`stillness` is exactly the style that might legitimately
    # want a `0.0` bound one day).
    min_shot_duration_s = (
        band.min_shot_duration_s_override
        if band.min_shot_duration_s_override is not None
        else settings.min_shot_duration_s
    )
    max_shot_duration_s = (
        band.max_shot_duration_s_override
        if band.max_shot_duration_s_override is not None
        else settings.max_shot_duration_s
    )
    max_shots_per_project = (
        band.max_shots_override
        if band.max_shots_override is not None
        else settings.max_shots_per_project
    )
    return min_shot_duration_s, max_shot_duration_s, max_shots_per_project
