"""K3 enforcement pass (retention_fast_kinetic_text.md).

Fixed rules applied AFTER a planner (or `attach_pivot_cue`) returns,
same contract as `_cap_text_cards`: silently correct + log, never fail
the run. The model was structurally denied the information needed to
get density / collisions right (per-scene calls, no plate at authoring
time), so raising would punish our architecture.

Pure: no DB, no LLM. Input is a `Timeline`; output is a COPY with
offending `emphasis_cue`s cleared. Never mutates in place.

Rule order (logged as `rule` on each drop):

1. `text_card` — a title card and a kinetic cue on the same shot were
   measured unreadable. The schema validator already refuses to
   *construct* both; this pass still exists so K9 can emit a batch and
   we correct before/as we write, and so `detect_pivot` can ask the
   same question without inlining it.
2. `graphic` — never over an asset that is already a graphic. The
   signal is planner-authored `Shot.picture_is_graphic` (option 1 in
   the plan), not a prompt grep and not vision. Missing/False does not
   drop a cue.
3. `values_citation` — every `values[]` entry must cite a fragment
   whose narration text states that number, written as digits
   (`200000`, `2,00,000`), as digits plus a scale word (`2 lakh`,
   `2.5 lakh`), or spelled out in Hindi or English (`दो लाख`,
   `two lakh`, `पाँच`). One failure drops the whole cue (a chart with
   no citable anchor is dropped). Empty `values` (a pivot, a stamp) is
   not a citation failure.

   What a `values_citation` drop DOES and does NOT prove, because the
   log line gets read as an accusation: a kept cue proves only that
   the number is FINDABLE in the cited fragment under the readings
   this module implements — not that the fragment is about it, and
   not that the number is true. A drop proves only that THIS matcher
   could not find it. It is not evidence the model invented a number.
   The matcher is deliberately lenient and still incomplete: Hindi
   multi-word numerals are read (`दो हजार छब्बीस` == 2026, by
   `caption_romanizer.numerals`), but English compounds are not
   (`twenty five lakh`), and neither are ordinals, fractions, ranges
   or percentages-of — so real narration can state a value in a form
   that still drops. Widen the matcher when that is measured; do not
   read the rule as a hallucination detector.
4. At most one cue per shot — structural (`Shot.emphasis_cue` is
   optional, not a list). Nothing to enforce here.
5. `min_gap` — density. A cue fewer than `min_shot_gap` shots after
   the last KEPT cue is dropped, where the distance is the film-order
   INDEX difference: at gap 3, cues on shots 0 and 3 both survive and
   cues on shots 0 and 2 do not. The pivot is guaranteed: never drop a
   `device=pivot` cue to satisfy density; a non-pivot already kept
   yields to a later pivot inside the gap (same shape as chapter cards
   outranking ordinary text cards). A lone pivot is always kept.
6. `rate_cap` — optional extra cap in cues/minute. When over, drop
   non-pivot first, film order, reserving a slot for every pivot.
   Never drop a pivot to satisfy the cap.

Band knobs are resolved by the caller (EmphasisPassStep), not here —
RV2 / R1, same as whoosh and slab_default.

Per-shot safe-zone geometry is deliberately NOT in this module.
Pictures do not exist at EmphasisPassStep (approval requires every
shot filled before approval), so authoring cannot see the plate. The
Python-authoritative `band` already places type; a second layout
system would drift. Safe zones are render-time / K4-adjacent.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.planners.caption_romanizer import numerals
from app.planners.fragments import split_narration_fragments
from app.schemas.timeline import EmphasisCue, EmphasisDevice, Scene, Shot, Timeline
from app.timeline.duration import compute_timeline_duration

logger = get_logger(__name__)

# Indian / Western grouping commas and spaces may sit between the
# digits of a cited value (`200000`, `2,00,000`, `200,000`).
_DIGIT_SEP = r"[\s,]*"

# Scale words that reconstruct an integer the digits themselves do not
# spell. `2 lakh` == 200000; without this, the honesty rule would drop
# the SUV reel's actual anchor. English side only — the Hindi
# multipliers (`सौ`/`हजार`/`लाख`/`करोड़`, nukta variants included) are
# owned by `caption_romanizer.numerals`, which is also where the Hindi
# unit words 0-99 come from. That module exists because §11 needed a
# value COMPUTED from a closed table rather than guessed; the same
# table is exactly what this rule needs, so it is reused rather than
# retyped here.
_EN_SCALE_WORDS: dict[str, int] = {
    "hundred": 100,
    "hundreds": 100,
    "thousand": 1_000,
    "thousands": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
}

# English number words. Reviewed 2026-09-09: the matcher read digits
# only, so the user's own test line ("Safety rating में पाँच stars, और
# price भी दस लाख से कम") dropped both counters with `rule=
# values_citation` — which reads in the log as "the model invented a
# number" when the narration said it plainly. One through twenty plus
# the round tens; compounds (`twenty five`) are deliberately not read
# (see the module docstring on what a drop does not prove).
_EN_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

# Token boundaries for number reading. A NEGATIVE class on purpose:
# `\w` and `[^\W\d_]` both exclude Devanagari matras and the nukta
# (categories Mc / Mn), so a positive class shreds `पाँच` into `प` +
# `च` and never matches the table. `.` is not a separator (it carries
# `2.5`); it is stripped off the ends of a token instead.
_TOKEN_SPLIT_RE = re.compile(r"[\s,;:!?()\[\]{}<>\"'/|*+=&%@#$^~\-]+|—|–|…|।")

# A leading numeral glued to its scale word (`2लाख`, `2lakh`). The
# regex this replaced allowed zero space between the two, so the token
# reader has to as well.
_LEADING_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)(.*)", re.DOTALL)
_NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?")


def shot_blocks_emphasis_cue(shot: Shot) -> str | None:
    """Shot-level reason this shot cannot carry a cue, or None.

    Used by `detect_pivot` / `attach_pivot_cue` so they do not try to
    write an illegal Shot, and by the full pass as rules 1–2. Values
    citation needs the owning scene and is not asked here.
    """
    if shot.text_card:
        return "text_card"
    if shot.picture_is_graphic:
        return "graphic"
    return None


def enforce_emphasis_rules(
    timeline: Timeline,
    *,
    min_shot_gap: int | None,
    max_cues_per_minute: float | None,
) -> Timeline:
    """Return a copy with offending cues cleared. Never mutates `timeline`."""
    copy = timeline.model_copy(deep=True)
    film = _film_order(copy)

    for scene, shot in film:
        cue = shot.emphasis_cue
        if cue is None:
            continue
        reason = shot_blocks_emphasis_cue(shot)
        if reason is not None:
            _drop(shot, reason)
            continue
        if not _values_are_cited(scene, cue):
            _drop(shot, "values_citation")

    if min_shot_gap is not None and min_shot_gap > 0:
        _apply_min_gap(film, min_shot_gap)

    if max_cues_per_minute is not None:
        _apply_rate_cap(film, max_cues_per_minute)

    return copy


def _film_order(timeline: Timeline) -> list[tuple[Scene, Shot]]:
    pairs: list[tuple[Scene, Shot]] = []
    for scene in sorted(timeline.scenes, key=lambda s: s.order):
        for shot in sorted(scene.shots, key=lambda s: s.order):
            pairs.append((scene, shot))
    return pairs


def _drop(shot: Shot, rule: str) -> None:
    cue = shot.emphasis_cue
    if cue is None:
        return
    logger.info(
        "emphasis_rules.dropped",
        extra={
            "shot_id": shot.id,
            "device": cue.device.value,
            "rule": rule,
        },
    )
    shot.emphasis_cue = None


def _values_are_cited(scene: Scene, cue: EmphasisCue) -> bool:
    """Empty values are fine (pivot/stamp). Any one miss drops the cue."""
    if not cue.values:
        return True
    fragments = {
        fragment.index: fragment
        for fragment in split_narration_fragments(scene.narration_text or "")
    }
    for entry in cue.values:
        fragment = fragments.get(entry.cited_fragment)
        if fragment is None:
            return False
        if not _fragment_contains_value(fragment.text, entry.value):
            return False
    return True


def _fragment_contains_value(text: str, value: int) -> bool:
    """True when `text` states `value` — as digits or spelled out.

    Two readings, in order: the digits of `value` (allowing Indian /
    Western grouping), then every number the text spells out — digits,
    decimals and number words in Hindi or English, alone or as the
    coefficient of a scale word. See the module docstring for what a
    False here does and does not prove.
    """
    target = abs(value)
    digits = str(target)
    pattern = r"(?<!\d)" + _DIGIT_SEP.join(re.escape(d) for d in digits) + r"(?!\d)"
    if re.search(pattern, text):
        return True
    return target in _stated_numbers(text)


def _number_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_SPLIT_RE.split(text):
        token = raw.strip(".")
        if not token:
            continue
        match = _LEADING_NUMBER_RE.fullmatch(token)
        if match is not None and match.group(2):
            tokens.append(match.group(1))
            tokens.append(match.group(2))
        else:
            tokens.append(token)
    return tokens


def _token_number(token: str) -> float | None:
    """A numeral (`2`, `2.5`) or a spelled-out number word, or None."""
    if _NUMERIC_RE.fullmatch(token):
        return float(token)
    lowered = token.lower()
    if lowered in _EN_NUMBER_WORDS:
        return float(_EN_NUMBER_WORDS[lowered])
    if lowered in _EN_SCALE_WORDS:
        return float(_EN_SCALE_WORDS[lowered])
    hindi = numerals.word_value(token)
    return None if hindi is None else float(hindi)


def _scale_value(token: str) -> int | None:
    """The multiplier a token names (`lakh`, `लाख`, `crore`), or None."""
    lowered = token.lower()
    if lowered in _EN_SCALE_WORDS:
        return _EN_SCALE_WORDS[lowered]
    if numerals.is_multiplier(token):
        return numerals.word_value(token)
    return None


def _stated_numbers(text: str) -> set[int]:
    """Every integer `text` states, reading left to right.

    A number word or numeral immediately followed by a scale word is
    read as one value and the pair is CONSUMED: `दो लाख` yields 200000
    only — not 2 and not 100000, so citing the coefficient or the scale
    alone still drops. Non-integral products (`2.5 thousand` -> 2500 is
    fine, `1.5 hundred` -> 150 is fine, a fraction that does not land on
    an integer is not) are ignored rather than rounded.
    """
    # Multi-word Hindi numerals (`दो हजार छब्बीस` == 2026) are parsed by
    # the module that owns that grammar — §11's fixed accumulate, which
    # refuses an ambiguous run rather than guessing — not re-derived
    # here. Its words are then WITHHELD from the pair reader below, so
    # `दो हजार छब्बीस` states 2026 and not also 2000 or 26.
    words = text.split()
    runs = numerals.find_numeral_runs(words)
    stated: set[int] = {run.value for run in runs}
    consumed = {i for run in runs for i in range(run.start, run.end + 1)}
    tokens = _number_tokens(" ".join(w for i, w in enumerate(words) if i not in consumed))
    i = 0
    while i < len(tokens):
        coefficient = _token_number(tokens[i])
        if coefficient is None:
            i += 1
            continue
        scale = _scale_value(tokens[i + 1]) if i + 1 < len(tokens) else None
        if scale is not None:
            product = coefficient * scale
            if product.is_integer():
                stated.add(int(product))
            i += 2
            continue
        if coefficient.is_integer():
            stated.add(int(coefficient))
        i += 1
    return stated


def _apply_min_gap(film: list[tuple[Scene, Shot]], min_shot_gap: int) -> None:
    """Walk film order. Pivot is never dropped; a non-pivot yields to it.

    The gap is an INDEX DISTANCE in film order: a cue at film index `i`
    is inside the gap when `i - last_kept_index < min_shot_gap`, so a
    cue exactly `min_shot_gap` shots after the last kept one is KEPT
    (gap 3: shots 0 and 3 both survive; shots 0 and 2 do not; adjacent
    shots never do). Reviewed 2026-09-09: the first implementation
    counted "shots seen since the keeper", which read a distance of `d`
    as `d - 1` and made the effective gap 4 — the docstring's rule and
    the band comment's `1.75 x 3 = 5.25s` arithmetic both describe this
    index reading, and at gap 3 it is what puts a fully-authored reel on
    the 12.0/min cap instead of 8.57/min.

    Mirrors `_cap_text_cards`: chapter cards there, pivot cues here.
    Two pivots inside the gap are both kept — never drop a pivot.
    """
    last_kept_index: int | None = None
    last_kept_is_pivot = False

    for i, (_scene, shot) in enumerate(film):
        cue = shot.emphasis_cue
        if cue is None:
            continue

        inside_gap = last_kept_index is not None and i - last_kept_index < min_shot_gap
        if cue.device is EmphasisDevice.PIVOT:
            if inside_gap and not last_kept_is_pivot and last_kept_index is not None:
                _drop(film[last_kept_index][1], "min_gap")
            last_kept_index = i
            last_kept_is_pivot = True
        elif not inside_gap:
            last_kept_index = i
            last_kept_is_pivot = False
        else:
            # A dropped cue is not a keeper: the gap still runs from the
            # last KEPT index, so three colliding cues do not ratchet.
            _drop(shot, "min_gap")


def _apply_rate_cap(
    film: list[tuple[Scene, Shot]],
    max_cues_per_minute: float,
) -> None:
    """Drop non-pivots in film order until under the cap; never drop a pivot.

    Slots are reserved for every remaining pivot so a late pivot cannot
    push the reel back over the cap after earlier stamps were kept.
    A lone pivot is kept even when the hypothetical rate is already
    exhausted.
    """
    shots = [shot for _scene, shot in film]
    duration_s = compute_timeline_duration(shots)
    if duration_s <= 0:
        return
    allowed = max_cues_per_minute * (duration_s / 60.0)
    n_pivots = sum(
        1
        for shot in shots
        if shot.emphasis_cue is not None and shot.emphasis_cue.device is EmphasisDevice.PIVOT
    )
    remaining_pivots = n_pivots
    kept = 0
    for shot in shots:
        cue = shot.emphasis_cue
        if cue is None:
            continue
        if cue.device is EmphasisDevice.PIVOT:
            remaining_pivots -= 1
            kept += 1
            continue
        # Keep this non-pivot only when it plus the pivots still ahead
        # still fit. `kept` already counts earlier keepers (pivot or not).
        if kept + remaining_pivots + 1 <= allowed:
            kept += 1
        else:
            _drop(shot, "rate_cap")
