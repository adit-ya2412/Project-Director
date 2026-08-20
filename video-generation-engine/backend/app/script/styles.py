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

import math
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

    `narration_speed` is the ElevenLabs speaking-rate multiplier for
    this style (parent plan §2.1 / R8). Default 1.0 is the API default
    and keeps the pre-R8 four-value narration cache key. Only
    `retention_fast` overrides it (~1.2×) — speed is a voice lever that
    matches delivery to cutting, not a pacing lever that changes the
    voice. Hashed into `compute_narration_content_hash`.

    `music_bed_gain_db` / `music_duck_gain_db` are None to mean "use
    `settings.*`" (parent plan §5.2 / leftover item 5). Archival keeps
    the measured mix. Fast-cut and stillness override. `0.0` is a
    legitimate value — resolve with `is not None`, never `or`.

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
    narration_speed: float = 1.0
    music_bed_gain_db: float | None = None
    music_duck_gain_db: float | None = None

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
        narration_speed=1.2,
        # §5.2: driving, barely ducked. Offsets from the measured
        # archival mix (-14 / -20), not a new listening pass.
        music_bed_gain_db=-10.0,
        music_duck_gain_db=-14.0,
    ),
    "stillness": StylePacingBand(
        name="stillness",
        target_shot_duration_s=None,
        max_shots_override=None,
        # §5.2: near-absent. 8 dB quieter bed than the measured mix.
        music_bed_gain_db=-22.0,
        music_duck_gain_db=-28.0,
    ),
}


def resolve_narration_speed(style: str | None) -> float:
    """Style-owned speaking rate (parent plan §2.1 / R8).

    Unknown / unset styles resolve to 1.0 — the ElevenLabs default and
    the pre-R8 cache key — the same fallback `resolve_constraint_bundle`
    uses for an unrecognised name.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        return 1.0
    return band.narration_speed


@dataclass(frozen=True)
class MusicGains:
    """Resolved bed/duck mix for one style (parent plan §5.2)."""

    bed_gain_db: float
    duck_gain_db: float


def resolve_music_gains(style: str | None) -> MusicGains:
    """Style-owned music mix. None / unknown / archival fall through
    to `settings.music_*_gain_db` (the measured mix, leftover item 5).
    `0.0` is a real override — `is not None`, never `or`.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    bed = settings.music_bed_gain_db
    duck = settings.music_duck_gain_db
    if band is not None:
        if band.music_bed_gain_db is not None:
            bed = band.music_bed_gain_db
        if band.music_duck_gain_db is not None:
            duck = band.music_duck_gain_db
    return MusicGains(bed_gain_db=bed, duck_gain_db=duck)


def get_pacing_band(style: str) -> StylePacingBand:
    """Raises `KeyError` on an unknown style name - deliberately, not a
    silent fallback to some default band. An endpoint calling this
    translates the KeyError into a 400 naming the valid styles; guessing
    a band for a typo'd style name would produce a feasibility verdict
    that looks real but checks the wrong thing."""
    return STYLE_PACING_BANDS[style]


# Track C C1 §2.3: projected from the five short fixtures (plan §0).
# ~3.2 fragments/scene, ~0.9 shots/fragment. 31 fragments ≈ today's 90 s.
_FRAGS_PER_SCENE = 3.2
_SHOTS_PER_FRAG = 0.9
_N_AT_SHORT_CAP = 31.0
_SCENE_HEADROOM = 5
_SHOT_SCALE = 1.18  # 206 * 0.9 * 1.18 ≈ 220 at 10 min


@dataclass(frozen=True)
class ConstraintBundle:
    """The one resolved set of planning bounds (Track C C1, R1).

    Unpackable as the historical 3-tuple
    `(min_shot_duration_s, max_shot_duration_s, max_shots_per_project)`
    so existing call sites keep working. `max_scenes` and
    `max_video_duration_s` used to be read from flat settings beside
    this function — that is the R1 shape; they live here now.
    Track C C6 adds `budget_cap_cents` and `max_video_shots_per_project`
    the same way: length-aware, and `n_fragments=None` is today's 1000¢
    / 5 video shots.
    """

    min_shot_duration_s: float
    max_shot_duration_s: float
    max_shots_per_project: int
    max_scenes: int
    max_video_duration_s: float
    budget_cap_cents: int
    max_video_shots_per_project: int

    def __iter__(self):
        yield self.min_shot_duration_s
        yield self.max_shot_duration_s
        yield self.max_shots_per_project


def resolve_constraint_bundle(
    style: str | None, *, n_fragments: int | None = None
) -> ConstraintBundle:
    """Length-aware, style-aware bounds for the real enforcement points.

    `style=None` and `n_fragments=None` (every Timeline predating both
    fields, and every caller that has not yet split the script) resolve
    to EXACTLY the numbers those flat `settings.*` reads always
    produced. Length sets the base (`max(today's cap, f(N))`); style
    multiplies the shot cap (retention_fast 58/40). Not "whichever is
    larger" — that silently drops one of the two (Track C §2.3).
    C6: budget scales linearly with the duration cap (90 s → 1000¢);
    the motion-shot cap scales with `sqrt(duration / 90 s)` so a
    10-minute video cannot spend the whole cap on ~130 motion shots.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        band = STYLE_PACING_BANDS[settings.default_render_style]
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

    if n_fragments:
        max_scenes = max(
            settings.max_scenes, math.ceil(n_fragments / _FRAGS_PER_SCENE) + _SCENE_HEADROOM
        )
        shots_base = max(
            settings.max_shots_per_project,
            math.ceil(n_fragments * _SHOTS_PER_FRAG * _SHOT_SCALE),
        )
        implied_duration = (n_fragments / _N_AT_SHORT_CAP) * settings.max_video_duration_s
        max_video_duration_s = min(
            settings.max_long_form_duration_s,
            max(settings.max_video_duration_s, implied_duration),
        )
    else:
        max_scenes = settings.max_scenes
        shots_base = settings.max_shots_per_project
        max_video_duration_s = settings.max_video_duration_s

    # Length sets the base; style multiplies. retention_fast's 58 is
    # 58/40 of the 90 s cap; at 10 min that same ratio applies to the
    # length-scaled base, not "max(220, 58)".
    if band.max_shots_override is not None:
        style_mult = band.max_shots_override / settings.max_shots_per_project
        max_shots_per_project = math.ceil(shots_base * style_mult)
    else:
        max_shots_per_project = shots_base

    # C6: 90 s → project_budget_cap_cents (1000). 10 min → ~6667¢ (~$67).
    # ceil so a fractional second never silently drops a cent of room.
    budget_cap_cents = math.ceil(
        max_video_duration_s * settings.project_budget_cap_cents / settings.max_video_duration_s
    )
    # Sub-linear in length (D4): sqrt(6.67) × 5 ≈ 13 motion shots at
    # 10 min, not 5 × 6.67 ≈ 33, and nowhere near 130.
    duration_ratio = max_video_duration_s / settings.max_video_duration_s
    max_video_shots_per_project = max(
        settings.max_video_shots_per_project,
        math.ceil(settings.max_video_shots_per_project * math.sqrt(duration_ratio)),
    )

    return ConstraintBundle(
        min_shot_duration_s=min_shot_duration_s,
        max_shot_duration_s=max_shot_duration_s,
        max_shots_per_project=max_shots_per_project,
        max_scenes=max_scenes,
        max_video_duration_s=max_video_duration_s,
        budget_cap_cents=budget_cap_cents,
        max_video_shots_per_project=max_video_shots_per_project,
    )
