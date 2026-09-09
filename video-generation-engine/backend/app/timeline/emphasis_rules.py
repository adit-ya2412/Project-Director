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
   `2.5 lakh`), or spelled out in Devanagari Hindi (`दो लाख`, `पाँच`),
   in ROMANISED Hindi (`do lakh`, `das lakh`, `paanch`) or in English
   (`two lakh`, `five stars`). One failure drops the whole cue (a
   chart with no citable anchor is dropped). Empty `values` (a pivot,
   a stamp) is not a citation failure.

   What a `values_citation` drop DOES and does NOT prove, because the
   log line gets read as an accusation: a kept cue proves only that
   the number is FINDABLE in the cited fragment under the readings
   this module implements — not that the fragment is about it, and
   not that the number is true. A drop proves only that THIS matcher
   could not find it. It is not evidence the model invented a number.
   The matcher is deliberately lenient and still incomplete. READ:
   Devanagari multi-word numerals (`दो हजार छब्बीस` == 2026, by
   `caption_romanizer.numerals`), and romanised units alone or as the
   coefficient of the `lakh`/`crore` tier. NOT READ, each for a
   reason: English compounds (`twenty five lakh`); ordinals,
   fractions, ranges and percentages-of; romanised `sau`/`hazaar`
   (`do hazaar chhabbis`, `unnis sau ikatees` — Hindi puts the
   remainder after those tiers, so a two-token read states 2000 or
   1900, a number the narration did NOT say); a romanised spelling
   that collides with an ordinary English word unless a scale word
   sits next to it (`do lakh` is 200000, `I do think` is nothing);
   `so` for `सौ` at all, since "do so" is ordinary English and 200
   would be a FORGED citation; and a bare scale word carrying no
   coefficient (`lakh` on its own). Everything withheld here is
   withheld because reading it could invent a number rather than
   miss one. So real narration can state a value in a form that
   still drops. Widen the matcher when that is measured — and never
   in a way that can forge; do not read the rule as a hallucination
   detector.
4. At most one cue per shot — structural (`Shot.emphasis_cue` is
   optional, not a list). Nothing to enforce here.
5. `min_gap` — density. A cue fewer than `min_shot_gap` shots after
   the last KEPT cue is dropped, where the distance is the film-order
   INDEX difference: at gap 3, cues on shots 0 and 3 both survive and
   cues on shots 0 and 2 do not. The pivot is guaranteed: never drop a
   `device=pivot` cue to satisfy density; a non-pivot already kept
   yields to a later pivot inside the gap (same shape as chapter cards
   outranking ordinary text cards). A lone pivot is always kept.

   K14.1: when `hook_s` is set, a shot whose start time (via
   `compute_shot_start_times`, start < hook_s) is inside the hook
   uses `hook_min_shot_gap` instead (1 on retention_fast so
   consecutive hook shots may both keep a cue). Body shots still use
   `min_shot_gap`. Gap 0 would skip the rule under `if gap > 0`;
   gap 1 is the value that lets consecutive indices survive.
6. `rate_cap` — optional extra cap in cues/minute. When over, drop
   non-pivot first, film order, reserving a slot for every pivot.
   Never drop a pivot to satisfy the cap.

   K14.2: when `hook_s` is set, the cap is computed over the BODY
   only (duration after hook_s; cues whose shots start >= hook_s).
   Hook cues are extra and never dropped by this rule. Do not raise
   the whole-reel ceiling instead — that would let the body pack at
   the higher average too.

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
from typing import NamedTuple

from app.core.logging import get_logger
from app.planners.caption_romanizer import numerals
from app.planners.fragments import split_narration_fragments
from app.schemas.timeline import EmphasisCue, EmphasisDevice, Scene, Shot, Timeline
from app.timeline.duration import compute_shot_start_times, compute_timeline_duration

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

# Romanised Hindi number words, as SPELLINGS ONLY. Reviewed
# 2026-09-09 (one transliteration layer under the first review): this
# pipeline's narration is Hinglish written in LATIN script — the live
# K9 script says `2025 mein 2 lakh models bikhe` and `Safety rating
# mein paanch stars` — so a romanised numeral is the most likely of
# the three forms, and it was the one form the matcher could not read.
# `do lakh` / `das lakh` / `paanch stars` all dropped with
# `rule=values_citation` while their Devanagari and English twins were
# cited.
#
# No romanised numeral table existed anywhere in the backend to reuse:
# `caption_romanizer.numerals` is Devanagari-keyed, and the Latin side
# of that pass is produced per-scene by the LLM (plain 1:1
# transliteration, prompt `caption_romanizer/v1.md`) and never stored
# as a table. So the spellings below are new — but the VALUES are not
# retyped: each entry maps a Latin spelling to the Devanagari word it
# transliterates, and the integer (and whether the word is a scale)
# comes from `numerals.word_value` / `numerals.is_multiplier`. That
# module stays the single source of truth for what a Hindi number word
# means; a spelling here that does not resolve raises at import rather
# than silently reading as nothing (see `_roman_tables`).
#
# Coverage is what a 30-45s reel actually says: 1-10, the round-ish
# larger units a counter cites (20, 25, 30, 40, 50) and the four
# scales. Transliteration has no standard, so plausible variants sit
# side by side (`paanch`/`paach`, `hazaar`/`hajaar`/`hazar`).
_ROMAN_TO_DEVANAGARI: dict[str, str] = {
    "ek": "एक",
    "do": "दो",
    "doh": "दो",
    "teen": "तीन",
    "tin": "तीन",
    "chaar": "चार",
    "char": "चार",
    "paanch": "पाँच",
    "paach": "पाँच",
    "panch": "पांच",
    "chhah": "छह",
    "chhe": "छह",
    "chheh": "छह",
    "che": "छह",
    "chah": "छह",
    "saat": "सात",
    "sat": "सात",
    "sath": "सात",
    "aath": "आठ",
    "ath": "आठ",
    "nau": "नौ",
    "nao": "नौ",
    "das": "दस",
    "dus": "दस",
    "bees": "बीस",
    "bis": "बीस",
    "pachees": "पच्चीस",
    "pachchees": "पच्चीस",
    "pacchis": "पच्चीस",
    "tees": "तीस",
    "tis": "तीस",
    "chalees": "चालीस",
    "chalis": "चालीस",
    "pachaas": "पचास",
    "pachas": "पचास",
    "karod": "करोड़",
    "karor": "करोड़",
    "karore": "करोड़",
    # `lakh`/`lac`/`crore` are already read as scale words on the
    # English side above; they are the same Latin token either way.
    #
    # `sau` (सौ) and `hazaar` (हजार) are DELIBERATELY ABSENT, and this
    # was measured, not assumed. Hindi puts a numeral's remainder AFTER
    # those two tiers — `do hazaar chhabbis` is 2026, `unnis sau
    # ikatees` is 1931, and reels say years constantly — so a
    # coefficient+scale pair reads the wrong number off them (2000,
    # 1900) unless the remainder word is also in the table. Devanagari
    # is safe there only because §11's run parser consumes a whole run
    # and refuses a partial merge; a Latin table cannot be closed the
    # same way (`chhabbis`/`chhabis`/`chabbis` are all plausible), so
    # ANY missing spelling would silently forge a number the narration
    # did not state. The first draft of this table included both tiers
    # and the probe caught exactly that: `do hazaar chhabbis` cited
    # 2000. `lakh`/`crore` do not carry this risk in practice — a reel
    # says "do lakh", not "do lakh pachaas hazaar" — and their pair
    # reading is the same lenience the English side has shipped since
    # the first review. So `das hazaar` and `unnis sau ikatees` stay
    # UNCOVERED (they drop), which is the fail-safe direction.
}

# The defence against the thing that would make this fix WORSE than
# the gap it closes. Several natural transliterations are also ordinary
# words: `do` and `so` are English, `char` is English, `tin`/`teen`/
# `bees`/`tees`/`sat` are English, `sath` is Hindi साथ ("with"), `chah`
# is चाह ("desire"), `che`/`nao` are ordinary words elsewhere. Reading
# "I do think" as the number 2 would CREATE a citation the narration
# never made — silently certifying a number, which is strictly worse
# than the drop this change removes, because honesty is the entire
# point of the rule.
#
# The guard: a colliding spelling is read ONLY as the coefficient of an
# immediately following scale word. `do lakh` is 200000; `do` alone,
# next to any ordinary word, states nothing. This costs nothing that
# works today (every romanised reading dropped before this change) and
# it is the case that actually occurs — a reel says "do lakh", not a
# bare "do" as a counter. `sau` is safe unguarded, but `so` for सौ is
# NOT IN THE TABLE AT ALL and must not be added: the guard above is a
# preceding/following-coefficient rule, and "I do so" would satisfy it
# and forge 200. A number small enough to say bare is spelled
# unambiguously anyway (`paanch`, `chaar`, `das`).
_ROMAN_NEEDS_SCALE: frozenset[str] = frozenset(
    {
        "do",
        "doh",
        "teen",
        "tin",
        "char",
        "panch",
        "che",
        "chah",
        "sat",
        "sath",
        "ath",
        "nao",
        "bees",
        "bis",
        "tees",
        "tis",
    }
)


def _roman_tables() -> tuple[dict[str, int], dict[str, int]]:
    """Split `_ROMAN_TO_DEVANAGARI` into unit words and scale words.

    Values are looked up, never declared here. A spelling whose
    Devanagari side is not in `numerals.TABLE` (a typo, or a respelling
    on that side) raises at import: the failure is deterministic, so it
    cannot ship past one test run, whereas a silent skip would quietly
    narrow the matcher again.
    """
    words: dict[str, int] = {}
    scales: dict[str, int] = {}
    for roman, devanagari in _ROMAN_TO_DEVANAGARI.items():
        value = numerals.word_value(devanagari)
        if value is None:
            raise RuntimeError(
                f"emphasis_rules: {roman!r} maps to {devanagari!r}, which is not "
                "a word in caption_romanizer.numerals.TABLE"
            )
        if numerals.is_multiplier(devanagari):
            scales[roman] = value
        else:
            words[roman] = value
    return words, scales


_ROMAN_NUMBER_WORDS, _ROMAN_SCALE_WORDS = _roman_tables()

# Punctuation on either end of an already-Latin token (`Do`, `lakh.`,
# `"paanch`). Stripped before the romanised lookup only — the number
# readers below keep using `_TOKEN_SPLIT_RE`.
_LATIN_EDGE_PUNCT_RE = re.compile(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$")

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
    hook_s: float | None = None,
    hook_min_shot_gap: int | None = None,
) -> Timeline:
    """Return a copy with offending cues cleared. Never mutates `timeline`.

    `hook_s` / `hook_min_shot_gap` are K14 additives. Defaults keep
    pre-K14 call sites (whole-reel gap and rate cap) unchanged.
    """
    copy = timeline.model_copy(deep=True)
    film = _film_order(copy)
    starts = compute_shot_start_times([shot for _scene, shot in film])

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

    if _gap_rule_active(min_shot_gap, hook_s, hook_min_shot_gap):
        _apply_min_gap(
            film,
            starts,
            min_shot_gap=min_shot_gap,
            hook_s=hook_s,
            hook_min_shot_gap=hook_min_shot_gap,
        )

    if max_cues_per_minute is not None:
        _apply_rate_cap(
            film,
            starts,
            max_cues_per_minute,
            hook_s=hook_s,
        )

    return copy


def _gap_rule_active(
    min_shot_gap: int | None,
    hook_s: float | None,
    hook_min_shot_gap: int | None,
) -> bool:
    if min_shot_gap is not None and min_shot_gap > 0:
        return True
    return (
        hook_s is not None
        and hook_s > 0
        and hook_min_shot_gap is not None
        and hook_min_shot_gap > 0
    )


def _shot_in_hook(
    shot_id: str,
    starts: dict[str, float],
    hook_s: float | None,
) -> bool:
    """Hook membership is by start time: start < hook_s.

    A long first shot that overlaps the whole window is in the hook
    because it starts at 0; a shot that begins at exactly hook_s is
    body. Not shot index, not overlap of [0, hook_s).
    """
    if hook_s is None or hook_s <= 0:
        return False
    return starts[shot_id] < hook_s


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
    decimals and number words in Devanagari Hindi, romanised Hindi or
    English, alone or as the coefficient of a scale word. See the module
    docstring for what a False here does and does not prove, and for the
    readings that are deliberately withheld so that this function can
    never certify a number the fragment did not state.
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


class _Reading(NamedTuple):
    """How one token may be read as a number.

    `is_scale` — the token IS a multiplier (`lakh`, `सौ`), so on its own
    it states nothing; it needs a coefficient.
    `needs_scale` — the token is a romanised spelling that collides with
    an ordinary word (`do`, `char`), so it is read only when a scale
    word follows it. See `_ROMAN_NEEDS_SCALE`.
    """

    value: float
    is_scale: bool
    needs_scale: bool


def _token_reading(token: str) -> _Reading | None:
    """A numeral (`2`, `2.5`) or a spelled-out number word, or None."""
    if _NUMERIC_RE.fullmatch(token):
        return _Reading(float(token), is_scale=False, needs_scale=False)
    lowered = token.lower()
    if lowered in _EN_NUMBER_WORDS:
        return _Reading(float(_EN_NUMBER_WORDS[lowered]), is_scale=False, needs_scale=False)
    if lowered in _EN_SCALE_WORDS:
        return _Reading(float(_EN_SCALE_WORDS[lowered]), is_scale=True, needs_scale=False)
    stripped = _LATIN_EDGE_PUNCT_RE.sub("", lowered)
    if stripped in _ROMAN_SCALE_WORDS:
        return _Reading(float(_ROMAN_SCALE_WORDS[stripped]), is_scale=True, needs_scale=False)
    if stripped in _ROMAN_NUMBER_WORDS:
        return _Reading(
            float(_ROMAN_NUMBER_WORDS[stripped]),
            is_scale=False,
            needs_scale=stripped in _ROMAN_NEEDS_SCALE,
        )
    hindi = numerals.word_value(token)
    if hindi is None:
        return None
    return _Reading(float(hindi), is_scale=numerals.is_multiplier(token), needs_scale=False)


def _scale_value(token: str) -> int | None:
    """The multiplier a token names (`lakh`, `लाख`, `hazaar`), or None."""
    lowered = token.lower()
    if lowered in _EN_SCALE_WORDS:
        return _EN_SCALE_WORDS[lowered]
    stripped = _LATIN_EDGE_PUNCT_RE.sub("", lowered)
    if stripped in _ROMAN_SCALE_WORDS:
        return _ROMAN_SCALE_WORDS[stripped]
    if numerals.is_multiplier(token):
        return numerals.word_value(token)
    return None


def _stated_numbers(text: str) -> set[int]:
    """Every integer `text` states, reading left to right.

    A number word or numeral immediately followed by a scale word is
    read as one value and the pair is CONSUMED: `दो लाख` and `do lakh`
    yield 200000 only — not 2 and not 100000, so citing the coefficient
    or the scale alone still drops. A scale word with no coefficient at
    all (`lakh` on its own) states nothing either, for the same reason:
    the rule certifies the number a fragment SAYS, and a bare unit is
    not that number. Non-integral products (`2.5 thousand` -> 2500 is
    fine, `1.5 hundred` -> 150 is fine, a fraction that does not land on
    an integer is not) are ignored rather than rounded.
    """
    # Multi-word Hindi numerals (`दो हजार छब्बीस` == 2026) are parsed by
    # the module that owns that grammar — §11's fixed accumulate, which
    # refuses an ambiguous run rather than guessing — not re-derived
    # here. Its words are then WITHHELD from the pair reader below, so
    # `दो हजार छब्बीस` states 2026 and not also 2000 or 26.
    #
    # There is no romanised equivalent of this run parser and there
    # deliberately is not one: it works because its table is CLOSED,
    # and Latin spellings are not (see `_ROMAN_TO_DEVANAGARI` on why
    # `sau`/`hazaar` are absent). Romanised text is read one token at a
    # time by the pair reader below.
    words = text.split()
    runs = numerals.find_numeral_runs(words)
    stated: set[int] = {run.value for run in runs}
    consumed = {i for run in runs for i in range(run.start, run.end + 1)}
    tokens = _number_tokens(" ".join(w for i, w in enumerate(words) if i not in consumed))
    i = 0
    while i < len(tokens):
        reading = _token_reading(tokens[i])
        if reading is None:
            i += 1
            continue
        scale = _scale_value(tokens[i + 1]) if i + 1 < len(tokens) else None
        if scale is not None:
            product = reading.value * scale
            if product.is_integer():
                stated.add(int(product))
            i += 2
            continue
        if not reading.is_scale and not reading.needs_scale and reading.value.is_integer():
            stated.add(int(reading.value))
        i += 1
    return stated


def _gap_for_shot(
    shot: Shot,
    starts: dict[str, float],
    *,
    min_shot_gap: int | None,
    hook_s: float | None,
    hook_min_shot_gap: int | None,
) -> int | None:
    """Gap that applies to a NEW cue on this shot (hook vs body)."""
    if _shot_in_hook(shot.id, starts, hook_s):
        if hook_min_shot_gap is not None:
            return hook_min_shot_gap
    return min_shot_gap


def _apply_min_gap(
    film: list[tuple[Scene, Shot]],
    starts: dict[str, float],
    *,
    min_shot_gap: int | None,
    hook_s: float | None,
    hook_min_shot_gap: int | None,
) -> None:
    """Walk film order. Pivot is never dropped; a non-pivot yields to it.

    The gap is an INDEX DISTANCE in film order: a cue at film index `i`
    is inside the gap when `i - last_kept_index < gap`, so a cue exactly
    `gap` shots after the last kept one is KEPT (gap 3: shots 0 and 3
    both survive; shots 0 and 2 do not). Reviewed 2026-09-09: the first
    implementation counted "shots seen since the keeper", which read a
    distance of `d` as `d - 1` and made the effective gap 4.

    K14.1: the gap for the incoming cue is hook_min_shot_gap when that
    cue's shot starts inside the hook, else min_shot_gap. Gap 1 inside
    the hook lets consecutive indices survive (`i - last < 1` is never
    true for two different shots).

    Mirrors `_cap_text_cards`: chapter cards there, pivot cues here.
    Two pivots inside the gap are both kept — never drop a pivot.
    """
    last_kept_index: int | None = None
    last_kept_is_pivot = False

    for i, (_scene, shot) in enumerate(film):
        cue = shot.emphasis_cue
        if cue is None:
            continue

        gap = _gap_for_shot(
            shot,
            starts,
            min_shot_gap=min_shot_gap,
            hook_s=hook_s,
            hook_min_shot_gap=hook_min_shot_gap,
        )
        if gap is None or gap <= 0:
            last_kept_index = i
            last_kept_is_pivot = cue.device is EmphasisDevice.PIVOT
            continue

        inside_gap = last_kept_index is not None and i - last_kept_index < gap
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
    starts: dict[str, float],
    max_cues_per_minute: float,
    *,
    hook_s: float | None,
) -> None:
    """Drop non-pivots in film order until under the cap; never drop a pivot.

    Slots are reserved for every remaining pivot so a late pivot cannot
    push the reel back over the cap after earlier stamps were kept.
    A lone pivot is kept even when the hypothetical rate is already
    exhausted.

    K14.2 choice: when `hook_s` is set, compute the ceiling over the
    BODY only (duration_s - hook_s; cues whose shots start >= hook_s).
    Hook cues are never dropped by this rule and do not consume body
    slots. Leaving 12.0 on the whole reel would strip a dense hook;
    raising the whole-reel cap to ~16 would let the body pack 16/min.
    """
    shots = [shot for _scene, shot in film]
    duration_s = compute_timeline_duration(shots)
    if duration_s <= 0:
        return

    if hook_s is not None and hook_s > 0:
        body_duration_s = max(0.0, duration_s - hook_s)
        if body_duration_s <= 0:
            return
        allowed = max_cues_per_minute * (body_duration_s / 60.0)
        body_shots = [shot for shot in shots if not _shot_in_hook(shot.id, starts, hook_s)]
    else:
        allowed = max_cues_per_minute * (duration_s / 60.0)
        body_shots = shots

    n_pivots = sum(
        1
        for shot in body_shots
        if shot.emphasis_cue is not None and shot.emphasis_cue.device is EmphasisDevice.PIVOT
    )
    remaining_pivots = n_pivots
    kept = 0
    for shot in body_shots:
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
