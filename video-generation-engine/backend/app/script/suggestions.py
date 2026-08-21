"""Level 2 of the script pre-flight (plan §3.2, §3.5.1): propose
PUNCTUATION insertion points that would let the real splitter
(`app/planners/fragments.py::split_narration_fragments`) produce more,
shorter fragments - never a reworded script. The user's own words never
change; only where a mark of punctuation could go.

## Why the punctuation TYPE matters (§3.5.1 - verified against the real
splitter, not assumed)

`split_narration_fragments`'s clause pass (`,;:—`) only runs INSIDE a
primary (sentence) span already longer than `LONG_FRAGMENT_THRESHOLD_
CHARS` (80 characters) - a comma in a short sentence is inert, and only
a PERIOD (or other sentence-ending punctuation) always creates a new
fragment, regardless of length. So a correct suggestion has to know
which rule applies to the SENTENCE a long fragment belongs to, not just
propose "add a comma" as if it always worked - that was this plan's own
initial mistake (§3.5.1), corrected here in the implementation that
would have reproduced it.

R2 (2026-08-20): one call returns the transitive set — apply, re-split,
keep proposing until the style's band is met. Offsets stay in the
original script. The user still ticks them one by one.

R21 (2026-08-20): the cap is derived from `D / target_shot_duration_s`,
not a length-blind 40. A 196 s `retention_fast` script needs ~120 marks;
40 would have restored R2's original "accept everything, still refused"
loop at long-form size.

R23 / R24 (2026-08-20): `further_available` only answers "are there more
marks?". `would_pass` answers "will these marks make pre-flight pass?".
If the remaining violation is the hard duration ceiling, punctuation is
the wrong tool and the loop stops rather than reporting success.
"""

import math
from dataclasses import dataclass, field

from app.core.config import settings
from app.planners.fragments import (
    LONG_FRAGMENT_THRESHOLD_CHARS,
    SENTENCE_END_CHARS,
    NarrationFragment,
    find_split_points,
    split_narration_fragments,
)
from app.script.preflight import (
    FragmentEstimate,
    _chars_per_second,
    check_feasibility,
    estimate_duration_s,
)
from app.script.styles import get_pacing_band

# Floor so a short script is never capped below the original default.
# Not the limiter at long-form size — `suggestion_cap` is.
_SHORT_FORM_SUGGESTION_FLOOR = 40
# Backstop against a pathological non-converging script. The real
# exits are: feasible, cap reached, no new marks. Do not tune this
# thinking it is the limiter (R21).
_MAX_SUGGESTION_ROUNDS = 20


@dataclass(frozen=True)
class BreakSuggestion:
    """One proposed punctuation insertion, at an ABSOLUTE character
    offset into the ORIGINAL script (never a rewritten copy - plan
    §3.2's whole point is that the user's words are never touched, only
    where a mark could go). `mark` is a single character - `.` (always
    effective, any length) or `,` (effective only when the surrounding
    sentence would then exceed the 80-char clause-split threshold, see
    module docstring); `preview_before`/`preview_after` are display-only
    slices around the offset, never used for the actual insertion."""

    offset: int
    mark: str
    preview_before: str
    preview_after: str
    reason: str


@dataclass(frozen=True)
class BreakSuggestionResult:
    """R2: the full set, not one round.

    `further_available` is True only when we hit `max_suggestions` while
    the script is still infeasible and another round still found a legal
    break — the cap, not a stuck splitter.

    `would_pass` is the third state R23 asked for: True iff applying
    every returned mark makes `check_feasibility` pass. False together
    with `further_available=False` means we exhausted punctuation (or
    it is the wrong tool) and the script is still infeasible.

    `unfixable` is why, in that last case — duration against the hard
    ceiling, or no legal break left. Empty when `would_pass` is True
    or when the cap is the limiter (`further_available=True`).
    """

    suggestions: list[BreakSuggestion] = field(default_factory=list)
    further_available: bool = False
    would_pass: bool = False
    unfixable: list[str] = field(default_factory=list)


def apply_break_suggestions(script: str, suggestions: list[BreakSuggestion]) -> str:
    """Insert each mark at its ORIGINAL-script offset. Apply from the
    right so earlier offsets do not shift later ones."""
    modified = script
    for suggestion in sorted(suggestions, key=lambda item: item.offset, reverse=True):
        modified = (
            modified[: suggestion.offset] + suggestion.mark + modified[suggestion.offset :]
        )
    return modified


def working_offset_to_original(working_offset: int, original_offsets: list[int]) -> int:
    """Map an offset in `apply_break_suggestions(script, …)` back to the
    original script. Each original offset already applied is one extra
    character sitting at `original + n_insertions_before` in the working
    copy."""
    inserted_before = 0
    for original in sorted(original_offsets):
        working_pos = original + inserted_before
        if working_pos < working_offset:
            inserted_before += 1
        else:
            break
    return working_offset - inserted_before


def _sentence_span(script: str, offset: int) -> tuple[int, int]:
    """The [start, end) character span of the sentence containing
    `offset`, using the SAME primary split points the real splitter
    computes - so "is this sentence over 80 chars" is answered with
    exactly the boundaries `split_narration_fragments` would use, not an
    approximation."""
    primary_starts = find_split_points(script, split_chars=SENTENCE_END_CHARS)
    spans = list(zip(primary_starts, primary_starts[1:] + [len(script)], strict=True))
    for start, end in spans:
        if start <= offset < end or (offset == end and end == len(script)):
            return start, end
    return 0, len(script)


def _nearest_word_boundary(text: str, target_offset: int) -> int:
    """The nearest whitespace run at or after `target_offset` within
    `text` - so a suggested mark never lands mid-word. Falls back to
    `target_offset` itself if the fragment has no interior whitespace at
    all (a single very long word - rare, and inserting mid-word there is
    no worse than any other choice)."""
    for i in range(target_offset, len(text)):
        if text[i].isspace():
            return i
    for i in range(target_offset, -1, -1):
        if text[i].isspace():
            return i
    return target_offset


def _suggest_for_fragment(script: str, fragment: NarrationFragment) -> BreakSuggestion | None:
    """One suggestion for one over-long fragment, or `None` if the
    fragment is too short to usefully split (a single word, or already
    at the edge of the script)."""
    span_len = fragment.end - fragment.start
    if span_len < 20:
        return None

    sentence_start, sentence_end = _sentence_span(script, fragment.start)
    sentence_len = sentence_end - sentence_start
    midpoint = fragment.start + span_len // 2
    insert_at = _nearest_word_boundary(script, midpoint)
    if insert_at <= fragment.start or insert_at >= fragment.end:
        return None

    # The rule this module exists to get right (§3.5.1): a comma only
    # does anything if the SENTENCE (not just this fragment) is already,
    # or would become, longer than the clause-split threshold. Below it,
    # only a sentence-ending mark works, regardless of this fragment's
    # own length.
    if sentence_len > LONG_FRAGMENT_THRESHOLD_CHARS:
        mark = ","
        reason = (
            f"this sentence is {sentence_len} characters - a comma here will split it, "
            "since clause punctuation only takes effect past "
            f"{LONG_FRAGMENT_THRESHOLD_CHARS} characters"
        )
    else:
        mark = "."
        reason = (
            f"this sentence is only {sentence_len} characters - a comma would be ignored "
            "below the clause-split threshold, so a full stop is needed to split it here"
        )

    return BreakSuggestion(
        offset=insert_at,
        mark=mark,
        preview_before=script[max(0, insert_at - 30) : insert_at],
        preview_after=script[insert_at : min(len(script), insert_at + 30)],
        reason=reason,
    )


def _cut_words_reason(duration_s: float, ceiling_s: float) -> str:
    """Already over the hard ceiling. Do not reuse for the projected
    branch — 591 s under 600 s with that sentence reads as a fit (§18.6)."""
    return (
        f"this script is ~{duration_s:.0f}s; the maximum is {ceiling_s:.0f}s, "
        "and punctuation cannot shorten it — cut words instead"
    )


def _projected_cut_words_reason(
    duration_s: float, min_marks: int, projected_s: float, ceiling_s: float
) -> str:
    return (
        f"this script is ~{duration_s:.0f}s and would need ~{min_marks} more "
        f"marks to reach this style's pace, which pushes it to "
        f"~{projected_s:.0f}s against a {ceiling_s:.0f}s maximum; cut words instead"
    )


def _unfixable_by_punctuation(script: str, style: str) -> list[str]:
    """Violations punctuation cannot clear (R23 / R24).

    Length-aware `bundle.max_video_duration_s` below the 10-minute
    ceiling is NOT in this list: more fragments raise that cap, which
    is why the 196 s R21 script starts over 116 s and still passes
    after suggestions. `settings.max_long_form_duration_s` does not
    move, and inserting marks makes the estimate longer.

    Inserted marks currently count as full characters of speech —
    `estimate_duration_s` is `len(script) / chars_per_second`, and
    `apply_break_suggestions` inserts real characters. A comma is a
    pause, not a syllable. That is a modelling choice; changing it
    would make this loop's exit test disagree with `check_feasibility`
    on the applied script, which is the number that matters.
    """
    ceiling = settings.max_long_form_duration_s
    duration = estimate_duration_s(script, style)
    if duration > ceiling:
        return [_cut_words_reason(duration, ceiling)]

    band = get_pacing_band(style)
    if band.target_shot_duration_s is None or band.target_shot_duration_s <= 0:
        return []
    n_fragments = len(split_narration_fragments(script))
    needed_shots = math.ceil(duration / band.target_shot_duration_s)
    min_marks = max(needed_shots - n_fragments, 0)
    projected = (len(script) + min_marks) / _chars_per_second(style)
    if projected > ceiling:
        return [_projected_cut_words_reason(duration, min_marks, projected, ceiling)]
    return []


def suggestion_cap(script: str, style: str) -> int:
    """How many marks one pre-flight response may return (R21).

    `ceil(D / target) - N` is the number of extra fragments the average
    pace needs. Midpoint splits overshoot that (a 196 s / 1.75 s script
    needed 120 marks for a 72-fragment gap), so the gap is doubled.
    Floor 40 keeps short scripts at the original default.
    """
    band = get_pacing_band(style)
    if band.target_shot_duration_s is None or band.target_shot_duration_s <= 0:
        return 0
    n_fragments = len(split_narration_fragments(script))
    needed_shots = math.ceil(estimate_duration_s(script, style) / band.target_shot_duration_s)
    gap = max(needed_shots - n_fragments, 0)
    return max(_SHORT_FORM_SUGGESTION_FLOOR, gap * 2)


def _suggest_breaks_one_round(
    script: str, style: str, *, limit: int
) -> list[BreakSuggestion]:
    """One pass over the current script's over-target fragments."""
    band = get_pacing_band(style)
    if band.target_shot_duration_s is None or limit <= 0:
        return []

    chars_per_second = _chars_per_second(style)
    fragments = split_narration_fragments(script)
    over_target = [
        FragmentEstimate(fragment=f, estimated_duration_s=(f.end - f.start) / chars_per_second)
        for f in fragments
        if (f.end - f.start) / chars_per_second > band.target_shot_duration_s
    ]
    over_target.sort(key=lambda e: e.estimated_duration_s, reverse=True)

    suggestions: list[BreakSuggestion] = []
    for estimate in over_target[:limit]:
        suggestion = _suggest_for_fragment(script, estimate.fragment)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def suggest_breaks(
    script: str, style: str, *, max_suggestions: int | None = None
) -> BreakSuggestionResult:
    """Punctuation insertions that would let this script reach the
    style's pacing band (plan §3.2 level 2 / R2).

    Transitive: apply each round, re-split, keep proposing until
    `check_feasibility` passes, no legal break remains, or the cap.
    Offsets are always into the ORIGINAL script so the user still
    accept/rejects per mark. Returns `suggestions=[]` for a style with
    no pacing floor (`documentary_archival`, `stillness`).
    """
    band = get_pacing_band(style)
    if band.target_shot_duration_s is None:
        return BreakSuggestionResult()

    cap = suggestion_cap(script, style) if max_suggestions is None else max_suggestions
    accumulated: list[BreakSuggestion] = []
    seen_offsets: set[int] = set()

    start_unfixable = _unfixable_by_punctuation(script, style)
    if start_unfixable:
        return BreakSuggestionResult(unfixable=start_unfixable)

    for _ in range(_MAX_SUGGESTION_ROUNDS):
        working = apply_break_suggestions(script, accumulated)
        if check_feasibility(working, style).passed:
            return BreakSuggestionResult(
                suggestions=accumulated, further_available=False, would_pass=True
            )

        working_unfixable = _unfixable_by_punctuation(working, style)
        if working_unfixable:
            return BreakSuggestionResult(
                suggestions=accumulated, unfixable=working_unfixable
            )

        remaining = cap - len(accumulated)
        if remaining <= 0:
            further_available = bool(_suggest_breaks_one_round(working, style, limit=1))
            return BreakSuggestionResult(
                suggestions=accumulated, further_available=further_available
            )

        round_hits = _suggest_breaks_one_round(working, style, limit=remaining)
        # Map through THIS working copy, which only contains marks from
        # earlier rounds. Do not fold this round's originals into the
        # map — they are not in `working` yet.
        base_offsets = list(seen_offsets)
        round_suggestions: list[BreakSuggestion] = []
        for hit in round_hits:
            original_offset = working_offset_to_original(hit.offset, base_offsets)
            if original_offset in seen_offsets:
                continue
            if original_offset < 0 or original_offset > len(script):
                continue
            round_suggestions.append(
                BreakSuggestion(
                    offset=original_offset,
                    mark=hit.mark,
                    preview_before=script[max(0, original_offset - 30) : original_offset],
                    preview_after=script[original_offset : min(len(script), original_offset + 30)],
                    reason=hit.reason,
                )
            )
        if not round_suggestions:
            return BreakSuggestionResult(
                suggestions=accumulated,
                unfixable=[
                    "no more legal punctuation breaks remain, and this script "
                    "is still not feasible for this style"
                ],
            )

        tentative = accumulated + round_suggestions
        tentative_script = apply_break_suggestions(script, tentative)
        tentative_unfixable = _unfixable_by_punctuation(tentative_script, style)
        if tentative_unfixable:
            # This round would push estimated duration over the hard
            # ceiling. Keep the marks that still fit; do not hand the
            # user a set that cannot pass (R24).
            return BreakSuggestionResult(
                suggestions=accumulated, unfixable=tentative_unfixable
            )

        accumulated = tentative
        seen_offsets.update(s.offset for s in round_suggestions)

    working = apply_break_suggestions(script, accumulated)
    if check_feasibility(working, style).passed:
        return BreakSuggestionResult(
            suggestions=accumulated, further_available=False, would_pass=True
        )
    further_available = bool(_suggest_breaks_one_round(working, style, limit=1))
    unfixable = _unfixable_by_punctuation(working, style)
    return BreakSuggestionResult(
        suggestions=accumulated,
        further_available=further_available,
        unfixable=unfixable,
    )
