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
"""

from dataclasses import dataclass

from app.planners.fragments import (
    LONG_FRAGMENT_THRESHOLD_CHARS,
    SENTENCE_END_CHARS,
    NarrationFragment,
    find_split_points,
    split_narration_fragments,
)
from app.script.preflight import FragmentEstimate, _chars_per_second
from app.script.styles import get_pacing_band


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


def suggest_breaks(script: str, style: str, *, max_suggestions: int = 10) -> list[BreakSuggestion]:
    """One suggestion per fragment whose ESTIMATED duration exceeds the
    style's own target shot duration (plan §3.2 level 2) - not only the
    single longest fragment (§2.5.1's "dead stop" check), since several
    fragments can each individually run slower than the style wants
    without any one of them being the absolute longest.

    Returns `[]` for a style with no pacing floor (`target_shot_duration_s
    is None` - `documentary_archival`, `stillness`) - there is nothing to
    suggest breaking for a style that has no feasibility floor to begin
    with (plan §3.1's asymmetry, same reasoning as `check_feasibility`).
    """
    band = get_pacing_band(style)
    if band.target_shot_duration_s is None:
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
    for estimate in over_target[:max_suggestions]:
        suggestion = _suggest_for_fragment(script, estimate.fragment)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions
