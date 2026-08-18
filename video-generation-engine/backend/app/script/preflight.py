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

**Formerly a known gap, closed 2026-08-18 (motion_new_styles_and_
long_form_videos.md §13.1, "R1"):** this check compares a script against
a style's own `max_shots_override`, and for a while the real enforcement
point (`app/workflow/steps/generate_timeline.py::GenerateTimelineStep
.run()`) disagreed with it - it read the flat, non-style-aware
`settings.max_shots_per_project` directly instead of the same
`resolve_constraint_bundle` result `_is_fully_planned` (in that same
file) already used, so a script this check certified as "feasible for
retention_fast" could still hard-fail during real planning. Both call
sites in `generate_timeline.py` now go through one shared function
(`_validate_against_style`), so they cannot diverge again - see that
function's own docstring for the full history. Recorded here as closed,
not deleted outright, because the R1 review section (§13.1) that found
it explicitly asked that this paragraph survive until the fix landed.
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
      settings.max_shots_per_project` (matches what `generate_timeline
      .py::_validate_against_style` actually enforces, since R1 - see
      this module's own top docstring)

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
        # ⚠ KNOWN RESIDUAL GAP, documented rather than closed (found
        # 2026-08-18 while reviewing the R1 fix, sharpened the same day
        # by a second reviewer - motion_new_styles_and_long_form_videos.md
        # §13 addendum): `margin` widens THIS check (an estimate) but the
        # real enforcement point (`generate_timeline.py::
        # _validate_against_style`, via `resolve_constraint_bundle`)
        # checks the SAME `max_fragment_duration_s`/
        # `max_shot_duration_s_override` value with NO margin. For
        # `retention_fast` (3.5s exact bound) that leaves a 0.7s band
        # (3.5s-4.2s) where this function says "feasible" and real
        # planning still fails on an ESTIMATE that lands there - the
        # same shape of promise-the-enforcement-doesn't-honour bug R1
        # fixed, just far narrower (a band, not an 18-shot gap).
        #
        # **The mechanism is sharper than "only an estimate is at risk"
        # - a fragment landing in this band is ATOMIC** (`fragments.py`:
        # "a fragment is the finest unit a shot may own" - the Shot
        # Planner cannot split it into two shots or merge it away). The
        # repair loop DOES see this bound (`shot/planner.py::
        # _make_validator` checks `max_shot_duration_s` on every retry),
        # but the model has no LEGAL move that actually shortens an
        # atomic shot - only two things can happen when one lands in
        # 3.5-4.2s:
        #   1. the model UNDER-estimates `duration_s` (reports <=3.5s for
        #      a fragment that will really take ~3.6s to narrate) -
        #      passes planning, and `NarrationStep`'s real measurement
        #      later corrects it under `narration_locked`'s exemption -
        #      no harm to the FINISHED video, but only because the
        #      wrong estimate was never true to begin with.
        #   2. the model reports HONESTLY (~3.6s) - the repair loop
        #      retries against a bound it cannot satisfy (the fragment
        #      does not get shorter on retry), exhausts its attempts,
        #      and the run dies - `PermanentError`, after the Director,
        #      Scene Planner, and every prior Shot Planner call have
        #      already been paid for. Exactly R1's own failure mode,
        #      reached a different way.
        # Which branch actually happens depends on the model CHOOSING to
        # mis-estimate on that one shot, which is not a property this
        # code controls or can rely on. Deliberately not closed by
        # symmetrising the two checks: narrowing this margin would
        # reintroduce false pre-flight rejections for estimates that are
        # merely pessimistic (the margin's whole purpose); widening the
        # real planning bound to match would weaken an actual creative
        # ceiling for a reason unrelated to the style's own intent.
        assert band.max_fragment_duration_s is not None  # set whenever target is (styles.py)
        if longest.estimated_duration_s > band.max_fragment_duration_s * margin:
            violations.append(
                f'one span of the script ("{longest.fragment.text[:60]}") is '
                f"~{longest.estimated_duration_s:.1f}s on its own - past '{style}''s "
                f"~{band.max_fragment_duration_s:.1f}s ceiling for a single shot, which would "
                "read as a dead stop regardless of how the rest of the script is cut"
            )

    # `if ... is not None else`, not `or` (same R7 trap as `styles.py`'s
    # own `resolve_constraint_bundle`, found as a second copy 2026-08-18
    # while reviewing that fix - this one was never touched by it since
    # it lives in a different file): a future style setting
    # `max_shots_override = 0` as a deliberate sentinel would otherwise
    # silently fall through to the flat default here.
    shot_cap = (
        band.max_shots_override
        if band.max_shots_override is not None
        else settings.max_shots_per_project
    )
    if fragment_count > shot_cap:
        # R9 fix (§13.9, 2026-08-18): this used to say planning "would
        # have to merge fragments, producing a slower cut... or fail
        # outright" - §3.4 (corrected twice) established that the merge
        # half of that sentence does not exist: `max_shots_per_project`
        # is checked directly after `run_structured_with_repair` returns
        # and raises `PermanentError` outright, with no repair-loop path
        # that would ever ask the model to merge shots. This message now
        # says what actually happens, not the retracted claim.
        violations.append(
            f"this script's {fragment_count} punctuation-based fragments exceed "
            f"'{style}''s shot cap of {shot_cap}. Planning would fail partway through, "
            "after the Director and Scene Planner have already run. Add fewer breaks, "
            "or choose a slower style."
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
