"""Feasibility check (motion_new_styles_and_long_form_videos.md §3.1,
§3.5.1): deterministic, computed from the script's character count and
the real fragment splitter alone - no LLM call, no persistence, safe to
run on every keystroke (plan §3.5.3, §3.5.4).

The asymmetry this whole check rests on (plan §3.1): after S1, the Shot
Planner picks a CONTIGUOUS RANGE of fragment indices per shot, never a
character offset - so a shot is at minimum one fragment. A script can
always be cut SLOWER (merge adjacent fragments into one longer shot) but
never FASTER than one fragment per shot. So a script imposes a hard
FLOOR on pace, never a ceiling - only a FAST style's target can be
infeasible; a slow style is always reachable by merging.

**Known gap, not yet closed (see this module's own `check_feasibility`
docstring): this check compares a script against a style's OWN
`max_shots_override` (`app/script/styles.py`), but the actual
enforcement points that would reject a real planning run
(`app/workflow/steps/generate_timeline.py`,
`app/planners/shot/planner.py`) still read the flat,
non-style-aware `settings.max_shots_per_project` - they do not yet know
`retention_fast` wants a higher cap. Building that (threading
`metadata.render_style` into both real call sites) is Track B work.
Until it lands, this check can report "feasible for retention_fast" for
a script needing 41-58 shots that would still hard-fail for real during
planning at the global default of 40. This is flagged here so it is not
silently forgotten, not because the arithmetic below is wrong - it
already checks the right number, `settings.max_shots_per_project` just
is not that number yet everywhere it needs to be.**
"""

from dataclasses import dataclass, field

from app.core.config import settings
from app.planners.fragments import NarrationFragment, split_narration_fragments
from app.script.styles import StylePacingBand, get_pacing_band

# Above this fraction of non-ASCII characters, the script is treated as
# mixed/non-Latin-script content for calibration purposes (the Hindi/
# Hinglish chars-per-second constant applies) rather than English.
# Chosen from real measurement, not guessed: `hinglish_final_project`
# (mixed Devanagari/Latin) measures 39% non-ASCII; a pure-English script
# measures ~0%. 15% sits well clear of both, so a script needs a
# genuinely substantial non-Latin component to cross it, not an
# occasional loanword or a single non-ASCII punctuation mark.
_NON_ASCII_HINDI_THRESHOLD = 0.15


@dataclass(frozen=True)
class FragmentEstimate:
    """One fragment's identity plus its ESTIMATED spoken duration -
    proportional to character count against the script's selected
    chars/sec constant (Settings docstring: calibrated from one real
    measured project per language, not a robust sample). This is
    deliberately an approximation available before any real narration
    exists - `NarrationStep`'s own measured, per-scene TTS timing is the
    real number, once it exists; this estimate only has to be close
    enough to catch an UNAMBIGUOUS mismatch (plan §3.6)."""

    fragment: NarrationFragment
    estimated_duration_s: float


@dataclass(frozen=True)
class FeasibilityResult:
    """Everything the pre-flight endpoint needs to explain a verdict to
    a human, not just whether it passed - plan §3.2 level 1's whole
    point is a diagnosis, not a pass/fail flag."""

    style: str
    fragment_count: int
    estimated_total_duration_s: float
    estimated_average_shot_duration_s: float
    longest_fragment: FragmentEstimate
    fragment_estimates: list[FragmentEstimate] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations


def _chars_per_second(script: str) -> float:
    """Selects the calibration constant from the SCRIPT'S OWN character
    composition, not a `language` metadata field - deliberately.
    `hinglish_final_project`'s own `language` field reads `"en"` despite
    being ~39% Devanagari by character count (verified directly against
    the fixture, 2026-08-17) - that field describes the TTS voice
    selection, not a reliable claim about script content, so trusting it
    here would silently miscalibrate every mixed-script project."""
    if not script:
        return settings.script_chars_per_second_en
    non_ascii_fraction = sum(1 for c in script if ord(c) > 127) / len(script)
    if non_ascii_fraction > _NON_ASCII_HINDI_THRESHOLD:
        return settings.script_chars_per_second_hi
    return settings.script_chars_per_second_en


def estimate_duration_s(script: str) -> float:
    """The script's estimated total spoken duration - character count
    over the selected chars/sec constant. This is `D` throughout the
    plan's own notation (§0, §3.1)."""
    return len(script) / _chars_per_second(script)


def _estimate_fragments(script: str) -> list[FragmentEstimate]:
    chars_per_second = _chars_per_second(script)
    fragments = split_narration_fragments(script)
    return [
        FragmentEstimate(
            fragment=fragment,
            estimated_duration_s=(fragment.end - fragment.start) / chars_per_second,
        )
        for fragment in fragments
    ]


def check_feasibility(script: str, style: str) -> FeasibilityResult:
    """The BLOCKING half of the pre-flight (plan §3.1) - pure arithmetic,
    no LLM call, safe on every keystroke. Raises `KeyError` for an
    unknown `style` (see `get_pacing_band`'s own docstring for why that
    is deliberate, not swallowed into a default).

    Three checks, all against the SAME `band: StylePacingBand`:
    - average pace (`D/N`) vs `band.target_shot_duration_s`
    - the single longest fragment vs `band.max_fragment_duration_s` (the
      "dead stop" ceiling, plan §2.5.1 - the sharper of the two checks,
      since one long atomic fragment cannot be split by any later
      decision, only by adding punctuation to the script itself)
    - fragment count vs `band.max_shots_override or
      settings.max_shots_per_project` (see this module's own top
      docstring for the one gap in this specific check)

    A style with `target_shot_duration_s is None` (`documentary_archival`,
    `stillness`) skips the first two entirely - plan §3.1's own
    asymmetry: a slow style can always be reached by merging fragments,
    so there is nothing to block on pace for one.

    The total-duration check against `settings.max_video_duration_s` is
    NOT margin-widened (unlike the two style-pace checks below) - it
    mirrors `Timeline._validate_structural_invariants`, which is exact
    and applies regardless of style, so widening it here would let a
    script pass pre-flight that is guaranteed to fail real planning
    later.
    """
    band: StylePacingBand = get_pacing_band(style)
    fragment_estimates = _estimate_fragments(script)
    fragment_count = len(fragment_estimates)
    total_duration_s = sum(f.estimated_duration_s for f in fragment_estimates)
    average_shot_duration_s = total_duration_s / fragment_count if fragment_count else 0.0
    longest = max(fragment_estimates, key=lambda f: f.estimated_duration_s)

    violations: list[str] = []
    margin = 1.0 + settings.script_preflight_margin_fraction

    if total_duration_s > settings.max_video_duration_s:
        violations.append(
            f"estimated script duration ~{total_duration_s:.1f}s exceeds the "
            f"{settings.max_video_duration_s:.0f}s project maximum"
        )

    if band.target_shot_duration_s is not None:
        if average_shot_duration_s > band.target_shot_duration_s * margin:
            max_possible_shots = fragment_count
            violations.append(
                f"this script's punctuation produces at most {max_possible_shots} shots "
                f"over an estimated ~{total_duration_s:.1f}s (~{average_shot_duration_s:.2f}s/shot "
                f"average) - '{style}' wants ~{band.target_shot_duration_s:.2f}s/shot, which this "
                "script cannot reach without more punctuation (see suggested breaks)"
            )
        assert band.max_fragment_duration_s is not None  # set whenever target is (styles.py)
        if longest.estimated_duration_s > band.max_fragment_duration_s * margin:
            violations.append(
                f'one span of the script ("{longest.fragment.text[:60]}") is '
                f"~{longest.estimated_duration_s:.1f}s on its own - past '{style}''s "
                f"~{band.max_fragment_duration_s:.1f}s ceiling for a single shot, which would "
                "read as a dead stop regardless of how the rest of the script is cut"
            )

    shot_cap = band.max_shots_override or settings.max_shots_per_project
    if fragment_count > shot_cap:
        violations.append(
            f"this script's {fragment_count} punctuation-based fragments exceed "
            f"'{style}''s shot cap of {shot_cap} - planning would have to merge fragments, "
            "producing a slower cut than intended, or fail outright"
        )

    return FeasibilityResult(
        style=style,
        fragment_count=fragment_count,
        estimated_total_duration_s=total_duration_s,
        estimated_average_shot_duration_s=average_shot_duration_s,
        longest_fragment=longest,
        fragment_estimates=fragment_estimates,
        violations=violations,
    )
