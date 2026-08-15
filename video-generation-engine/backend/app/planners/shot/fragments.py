"""Deterministic narration fragmentation (M5 hardening, 2026-08-15).

## Why this exists

Three times now, this project asked a language model to do character
arithmetic, and three times the model got it wrong: cross-scene shot-id
collisions (reproducing an example id verbatim rather than counting
scenes), the outer narration boundary off by four characters (a live run
killed by it), and internal shot boundaries landing mid-word
("Leuna-Werke" -> "L" + "euna-Werke") or mid-grapheme-cluster in
Devanagari ("दिन" -> "द" + "िन", separating a dependent vowel sign from
its consonant - not merely truncated text, malformed text). Snapping the
outer edges fixed the second case; snapping internal boundaries to the
nearest word boundary would have been a fourth patch on the same wrong
interface. **Models cannot count characters reliably - that is not a
prompt-quality problem, and it is not a post-processing problem. It is
the wrong thing to ask for.**

The fix: stop asking the Shot Planner for character offsets at all.
This module splits a scene's `narration_text` into an ordered list of
`NarrationFragment`s, deterministically, in code, BEFORE the model ever
sees the scene. The Shot Planner is then asked to assign each shot a
contiguous RANGE OF FRAGMENT INDICES (a far more natural judgement -
"shots 1 covers fragments 1-2" - than counting to 144), never a
character offset. `app/planners/shot/planner.py` converts fragment
ranges back into the exact character spans `Shot.narration_span` has
always used - nothing downstream (`narration_fit.py`, the renderer, the
master clock) changes at all, because `narration_span` itself is still
exactly what it always was.

A mid-word or mid-grapheme boundary becomes STRUCTURALLY IMPOSSIBLE,
rather than something to detect and correct after the fact: every
fragment boundary this module produces is, by construction, at a
sentence end or a line break (or, for a long fragment, a clause break) -
never inside a word, and never inside a grapheme cluster, because
Devanagari combining marks never immediately follow whitespace or
sentence-ending punctuation. Devanagari needs no special-case handling
anywhere in this module, which is itself evidence this is the right
fix rather than another patch.

## Fragment granularity - argued, not assumed

**Primary split points: sentence-ending punctuation (`.`, `!`, `?`, the
Devanagari danda `।`, the ellipsis `…`) and newlines.** The user's
scripts are written as short lines (observed directly in the Hinglish
fixtures), so a newline is already a strong, natural, human-authored
fragment boundary - this is cheap and matches how the material was
actually written, not an arbitrary rule invented for this fix.

**Secondary split points, applied ONLY within a fragment that is still
"too long" after the primary pass: `,` `;` `:` and the em dash `—`.**
This is deliberately NOT the default - splitting on every comma would
put fragment granularity right back to "arbitrary boundaries", the same
failure this fix exists to avoid, just one level coarser than character
offsets. It exists only to solve the opposite, equally real risk: one
very long run-on sentence that would otherwise be a single
un-subdividable fragment, forcing every shot that touches it to include
the ENTIRE sentence regardless of how long that makes the shot.
`_LONG_FRAGMENT_THRESHOLD_CHARS = 80` is the line between those two
risks - long enough that an ordinary short line or sentence (the common
case, per the user's own writing style) is never touched by it, short
enough that a genuinely long sentence gets a chance to subdivide. It is
a judgement call, not a derived constant, and is recorded here as one.

The plain hyphen `-` (U+002D) is deliberately NOT a split character at
either pass - it is what let "Leuna-Werke" get split in the first place,
and a compound/hyphenated name must stay whole. The em dash `—`
(U+2014) is a different character entirely and IS treated as a
legitimate secondary break.

## The "one fragment, several shots" case

A shot's fragment range must be non-empty, and two shots can never
share a fragment (a fragment is the finest unit a shot may own) -
therefore **a scene cannot have more shots than it has fragments.** This
is not a special rule bolted on: it falls out for free from the same
"fragment ranges tile 1..N with no gap or overlap" invariant every
other structural check in this module already needs, because it is
arithmetically impossible for more non-empty disjoint ranges to exist
than there are items to distribute them over. A model that proposes
more shots than a scene has fragments therefore fails the SAME
validation every other tiling violation already fails, and is repaired
the same way (fed back and asked again) - not a new failure mode
requiring new machinery. In practice this means: a short, single-
sentence scene realistically gets ONE shot, and the Shot Planner prompt
says so explicitly (it is told the fragment count before it plans),
so a repair round is the rare exception, not the common path.

## Lossless reconstruction

Every fragment's span is `[start, end)` where `end` is the NEXT
fragment's own `start` (or `len(text)` for the last fragment) - never a
separately-tracked "gap". This guarantees, by construction rather than
by a separate check, that concatenating every fragment's own span
exactly reproduces the scene's `narration_text` character for character,
including all whitespace - which is what the Scene Planner's own
verbatim-script check ultimately depends on staying true.
"""

from dataclasses import dataclass

_SENTENCE_END_CHARS = frozenset(".!?…।")  # "।" = Devanagari danda (full stop)
_CLAUSE_SPLIT_CHARS = frozenset(",;:—")  # NOT "-" (hyphen) - see module docstring
_LONG_FRAGMENT_THRESHOLD_CHARS = 80


@dataclass(frozen=True)
class NarrationFragment:
    """One deterministically-split piece of a scene's `narration_text`.
    `index` is 1-based (matching how the Shot Planner prompt numbers
    fragments for the model - "fragment 3", never "fragment[2]").
    `start`/`end` are the exact, lossless, 0-indexed half-open character
    span into the scene's `narration_text` - `text` is the SAME span,
    stripped, for display in the prompt only; span arithmetic always
    uses `start`/`end`, never `text`, so trimming never loses a
    character that matters for reconstruction."""

    index: int
    start: int
    end: int
    text: str


def _find_split_points(text: str, *, split_chars: frozenset[str]) -> list[int]:
    """Character offsets where a new fragment should start: immediately
    after any of `split_chars` or a newline, skipping the whitespace run
    that follows (if any) so a fragment never carries leading whitespace
    it would otherwise have to. Always includes 0. Never includes
    `len(text)` (a split character at the very end of the text starts no
    new fragment - there is nothing left to put in one)."""
    points = {0}
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n" or ch in split_chars:
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n:
                points.add(j)
            i = j
        else:
            i += 1
    return sorted(points)


def split_narration_fragments(text: str) -> list[NarrationFragment]:
    """The whole fragmentation pass: primary split on sentence-enders
    and newlines, then a secondary split - applied only within whichever
    primary fragments are still longer than
    `_LONG_FRAGMENT_THRESHOLD_CHARS` - on clause punctuation. See the
    module docstring for why each threshold and character set was
    chosen. Always returns at least one fragment (a scene with no
    sentence-ending punctuation and no newlines is one whole fragment -
    the "one fragment, several shots" case the Shot Planner's own
    validator handles, not this function)."""
    if not text:
        return [NarrationFragment(index=1, start=0, end=0, text="")]

    primary_starts = _find_split_points(text, split_chars=_SENTENCE_END_CHARS)
    primary_spans = list(zip(primary_starts, primary_starts[1:] + [len(text)], strict=True))

    all_starts = set(primary_starts)
    for start, end in primary_spans:
        if end - start > _LONG_FRAGMENT_THRESHOLD_CHARS:
            sub_points = _find_split_points(text[start:end], split_chars=_CLAUSE_SPLIT_CHARS)
            # sub_points are relative to text[start:end]; 0 is always
            # included (== start itself, already known) - only the
            # genuinely new interior ones are worth adding.
            all_starts.update(start + p for p in sub_points if p > 0)

    starts = sorted(all_starts)
    spans = zip(starts, starts[1:] + [len(text)], strict=True)
    return [
        NarrationFragment(index=i, start=start, end=end, text=text[start:end].strip())
        for i, (start, end) in enumerate(spans, start=1)
    ]
