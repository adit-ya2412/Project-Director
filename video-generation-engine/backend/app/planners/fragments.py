"""Deterministic narration fragmentation (M5 hardening, 2026-08-15;
shared with the Scene Planner as of S2, 2026-08-16).

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

## Shared with the Scene Planner (S2, 2026-08-16)

The Scene Planner had the SAME defect, one level up: it was asked to
retype the user's script verbatim into per-scene `narration_text`, and
`app/planners/scene/planner.py` validated that concatenating those
scenes reproduced the script's word content exactly - the identical
"ask a model to reproduce deterministic text losslessly" mistake as the
Shot Planner's character offsets, and it failed the same way (two
back-to-back validation failures on a real run, burning a full planning
call). The fix is the same fix: the Scene Planner is now handed the
SCRIPT pre-split into these same numbered fragments and chooses a
contiguous fragment-index range per SCENE, never retyping narration
text. This module moved here (out of `app/planners/shot/`) because it
is no longer shot-specific - it is the one deterministic splitter both
planners that ever faced this problem now share. See the
Implementation Guide's S2 section for the full reasoning, including why
a scene boundary chosen this way is always also a valid shot-fragment
boundary once the Shot Planner re-splits that scene's `narration_text`
on its own turn.

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
so a repair round is the rare exception, not the common path. The same
reasoning applies one level up: a script cannot have more scenes than
it has fragments, for the identical arithmetic reason.

## Lossless reconstruction

Every fragment's span is `[start, end)` where `end` is the NEXT
fragment's own `start` (or `len(text)` for the last fragment) - never a
separately-tracked "gap". This guarantees, by construction rather than
by a separate check, that concatenating every fragment's own span
exactly reproduces the source text character for character, including
all whitespace - which is what both the Scene Planner's and the Shot
Planner's own tiling invariants ultimately depend on staying true.

## Whitespace-only fragments are merged, never emitted standalone (2026-08-16)

A live run surfaced a second-order defect: the user's script has blank
lines between stanzas, and the Scene Planner's own (then verbatim)
check meant that whitespace had to live SOMEWHERE - it landed at the
front of whichever scene came next. The splitter above would then emit
that leading blank run (`"\n\n"`) as its OWN fragment, and the Shot
Planner - correctly following its own instructions to assign every
fragment to some shot - gave it one: a shot whose entire narration is
blank lines, still charged a slice of the video's duration and its own
Ken Burns move for a beat of silence.

**The fix: after splitting, any fragment whose content is entirely
whitespace is merged into an ADJACENT fragment** (forward into the
fragment that follows, since that is where the blank run's own
sentence-final newline was already pointing; backward into the one
before it only if the whitespace-only fragment is the LAST one and has
no successor) **rather than ever being emitted as its own,
independently-assignable fragment.** Merging is exact-span-preserving
(removing the boundary BETWEEN two fragments, not discarding either
one's characters), so tiling and lossless reconstruction both still
hold without any special-casing - the merged fragment simply carries
the blank run's characters as a leading (or trailing) part of its own
span, the same way a fragment can already contain incidental whitespace
around its own trimmed `text`.

**In practice, only the very first fragment (the one starting at
position 0) can ever be whitespace-only.** Every OTHER split point
`_find_split_points` produces is, by construction, the position of a
non-whitespace character - the first one found after skipping past the
whitespace that followed whatever triggered the split - so a fragment
starting at any such point already contains real content and can never
be entirely blank. A blank run that follows a sentence (rather than
opening the text) is therefore already trailing content of the
PRECEDING fragment before this merge pass ever runs, not a standalone
fragment for it to fold forward - confirmed by fuzzing this splitter
across ~200k random combinations of sentence/clause/newline tokens
(2026-08-16): not one produced an interior whitespace-only fragment.
The forward/backward merge above exists for the one case that DOES
reach it (leading whitespace, when the text itself opens with a blank
run) and the whole-text-is-whitespace degenerate case below - not for
an "interior" case that cannot arise through the primary or secondary
split passes at all.

Fragments are renumbered 1..N after merging, since removing a fragment
always changes how many exist.

**The degenerate case - a scene whose ENTIRE narration is whitespace -
is left as a single whitespace-only fragment, on purpose.** There is
nothing else in the scene to merge it into. This module's job is to
never emit a whitespace-only fragment ALONGSIDE real content; a scene
with no real content at all is a planning-level defect (the Scene
Planner should never hand a shot-less scene nothing to narrate), not
something the fragmenter can conjure real words out of. Treated as an
accepted, out-of-scope input here - not silently patched over by
inventing content, and not crashing either.
"""

from dataclasses import dataclass

_SENTENCE_END_CHARS = frozenset(".!?…।")  # "।" = Devanagari danda (full stop)
_CLAUSE_SPLIT_CHARS = frozenset(",;:—")  # NOT "-" (hyphen) - see module docstring
_LONG_FRAGMENT_THRESHOLD_CHARS = 80


@dataclass(frozen=True)
class NarrationFragment:
    """One deterministically-split piece of narration text (a scene's
    `narration_text`, for the Shot Planner, or the whole script, for the
    Scene Planner). `index` is 1-based (matching how both planners'
    prompts number fragments for the model - "fragment 3", never
    "fragment[2]"). `start`/`end` are the exact, lossless, 0-indexed
    half-open character span into the source text - `text` is the SAME
    span, stripped, for display in the prompt only; span arithmetic
    always uses `start`/`end`, never `text`, so trimming never loses a
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


def _merge_whitespace_only_spans(text: str, starts: list[int]) -> list[int]:
    """Removes fragment-start boundaries that would otherwise produce a
    whitespace-only fragment, merging it into an adjacent one instead -
    see the module docstring's own "Whitespace-only fragments" section
    for why and the exact rule (forward, backward only if last).
    Degenerate case (the WHOLE text is whitespace, `len(starts) <= 1`):
    returned unchanged - there is nothing to merge a single fragment
    into."""
    if len(starts) <= 1:
        return starts

    starts = list(starts)
    i = 0
    while i < len(starts):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        if text[start:end].strip() != "":
            i += 1
            continue
        # This fragment is whitespace-only - merge it away by dropping
        # whichever boundary combines it with its neighbour. Forward
        # (drop the boundary that starts the NEXT fragment) is the
        # default; if this is the LAST fragment, there is no next one,
        # so merge backward instead (drop the boundary that starts THIS
        # fragment, folding it into the one before it). `i` is not
        # advanced after a merge - the fragment now occupying position
        # `i` is different (and itself possibly still whitespace-only,
        # e.g. two consecutive blank-line runs) and must be re-checked.
        if i + 1 < len(starts):
            del starts[i + 1]
        else:
            del starts[i]
            i -= 1
    return starts


def split_narration_fragments(text: str) -> list[NarrationFragment]:
    """The whole fragmentation pass: primary split on sentence-enders
    and newlines, then a secondary split - applied only within whichever
    primary fragments are still longer than
    `_LONG_FRAGMENT_THRESHOLD_CHARS` - on clause punctuation, then a
    merge pass that folds any whitespace-only fragment into an adjacent
    one (see the module docstring's own section on why). See the module
    docstring for why each threshold and character set was chosen.
    Always returns at least one fragment (text with no sentence-ending
    punctuation and no newlines is one whole fragment - the "one
    fragment, several shots/scenes" case each caller's own validator
    handles, not this function)."""
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

    starts = _merge_whitespace_only_spans(text, sorted(all_starts))
    spans = zip(starts, starts[1:] + [len(text)], strict=True)
    return [
        # Renumbered 1..N here unconditionally (`enumerate(..., start=1)`)
        # - merging always changes how many fragments exist, so the
        # index can never simply carry over from the pre-merge count.
        NarrationFragment(index=i, start=start, end=end, text=text[start:end].strip())
        for i, (start, end) in enumerate(spans, start=1)
    ]
