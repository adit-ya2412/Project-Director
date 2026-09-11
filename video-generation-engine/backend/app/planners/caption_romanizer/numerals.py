"""Deterministic Hindi-numeral merging (caption_romanization.md §11).

§10 let the LLM decide when to merge spelled-out Hindi number words into
a single digit token (`covers`). That produced two live defects on
`2deaef0d`: it over-merged numerals that were already digits (`90
percent whey` -> a nonsense merge), and it silently produced the WRONG
value once (`दो हजार छब्बीस` -> `2006` instead of `2026`) while passing
every structural check §10.3 had.

§11's fix is to stop asking the model to decide this at all. The LLM
goes back to plain 1:1 transliteration (`caption_romanizer/planner.py`);
this module is a pure, deterministic pass over the result that finds
runs of Hindi number words in `narration_text`, parses each run to an
integer with a fixed accumulate algorithm, and reports which narration
word indices collapse into one display token. No I/O, no LLM, nothing
non-deterministic — the whole point is that a value is *computed*, never
guessed.

Vocabulary is closed and small (~110 words: 0-99 plus four
multipliers), unlike general transliteration (§2.5) where the hard part
— Hindi schwa deletion — is a real, unsolved NLP problem. `छब्बीस` is 26
in every sentence; there is nothing here for an LLM to get right that a
table lookup does not already get right structurally. See §11.2.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The table. Hindi names 0-99 irregularly (not compositionally, the way
# English "twenty-three" = "twenty" + "three" is), so every one of them
# is a literal entry rather than a formula. Includes common nukta and
# non-nukta spelling variants — both occur in real narration scripts.
# ---------------------------------------------------------------------------

_UNITS: dict[str, int] = {
    "शून्य": 0,
    "एक": 1,
    "दो": 2,
    "तीन": 3,
    "चार": 4,
    "पांच": 5,
    "पाँच": 5,
    "छह": 6,
    "छः": 6,
    "सात": 7,
    "आठ": 8,
    "नौ": 9,
    "दस": 10,
    "ग्यारह": 11,
    "बारह": 12,
    "तेरह": 13,
    "चौदह": 14,
    "पंद्रह": 15,
    "पन्द्रह": 15,
    "सोलह": 16,
    "सत्रह": 17,
    "अठारह": 18,
    "उन्नीस": 19,
    "बीस": 20,
    "इक्कीस": 21,
    "बाईस": 22,
    "तेईस": 23,
    "चौबीस": 24,
    "पच्चीस": 25,
    "छब्बीस": 26,
    "सत्ताईस": 27,
    "अट्ठाईस": 28,
    "उनतीस": 29,
    "तीस": 30,
    "इकतीस": 31,
    "बत्तीस": 32,
    "तैंतीस": 33,
    "चौंतीस": 34,
    "पैंतीस": 35,
    "छत्तीस": 36,
    "सैंतीस": 37,
    "अड़तीस": 38,
    "उनतालीस": 39,
    "चालीस": 40,
    "इकतालीस": 41,
    "बयालीस": 42,
    "तैंतालीस": 43,
    "चवालीस": 44,
    "पैंतालीस": 45,
    "छियालीस": 46,
    "सैंतालीस": 47,
    "अड़तालीस": 48,
    "उनचास": 49,
    "पचास": 50,
    "इक्यावन": 51,
    "इक्यावन्न": 51,
    "बावन": 52,
    "तिरपन": 53,
    "तिरेपन": 53,
    "चौवन": 54,
    "चौवन्न": 54,
    "पचपन": 55,
    "छप्पन": 56,
    "सत्तावन": 57,
    "अट्ठावन": 58,
    "उनसठ": 59,
    "साठ": 60,
    "इकसठ": 61,
    "बासठ": 62,
    "तिरसठ": 63,
    "चौंसठ": 64,
    "पैंसठ": 65,
    "छियासठ": 66,
    "सड़सठ": 67,
    "अड़सठ": 68,
    "उनहत्तर": 69,
    "सत्तर": 70,
    "इकहत्तर": 71,
    "बहत्तर": 72,
    "तिहत्तर": 73,
    "चौहत्तर": 74,
    "पचहत्तर": 75,
    "छिहत्तर": 76,
    "सतहत्तर": 77,
    "अठहत्तर": 78,
    "उन्यासी": 79,
    "अस्सी": 80,
    "इक्यासी": 81,
    "बयासी": 82,
    "तिरासी": 83,
    "चौरासी": 84,
    "पचासी": 85,
    "छियासी": 86,
    "सत्तासी": 87,
    "अठासी": 88,
    "नवासी": 89,
    "उनानबे": 89,
    "उनानवे": 89,
    "नब्बे": 90,
    "इक्यानवे": 91,
    "बानवे": 92,
    "तिरानवे": 93,
    "चौरानवे": 94,
    "पंचानवे": 95,
    "पचानवे": 95,
    "छियानवे": 96,
    "सत्तानवे": 97,
    "अट्ठानवे": 98,
    "अठानवे": 98,
    "निन्यानवे": 99,
    "निन्यानबे": 99,
}

_MULTIPLIER_VALUES = frozenset({100, 1000, 100_000, 10_000_000})

_MULTIPLIERS: dict[str, int] = {
    "सौ": 100,
    "हजार": 1000,
    "हज़ार": 1000,
    "लाख": 100_000,
    "लाख़": 100_000,
    "करोड़": 10_000_000,
    "करोड": 10_000_000,
}

# The full lookup table: unit words 0-99 plus the four multipliers.
TABLE: dict[str, int] = {**_UNITS, **_MULTIPLIERS}

# Trailing punctuation a Devanagari number word can carry in narration
# (most commonly the danda `।`, but also plain sentence punctuation).
# Stripped before table lookup, never before merged-token reconstruction
# — the merged token's own punctuation comes from the LLM's transliterated
# token for the run's last word (§11.5), not from this stripping.
_TRAILING_PUNCT_RE = re.compile(r"[।.,!?:;)\]]+$")

# For extracting punctuation off an already-transliterated (Latin) token,
# e.g. "chhabbis." -> ".". Non-alphanumeric, non-hyphen trailing run.
_TRAILING_LATIN_PUNCT_RE = re.compile(r"[^0-9A-Za-z]+$")


def _strip_trailing_punct(word: str) -> str:
    return _TRAILING_PUNCT_RE.sub("", word)


def word_value(word: str) -> int | None:
    """Look up a single narration word (unit or multiplier), stripping
    common trailing punctuation first. None if it is not a Hindi number
    word — this is what keeps a bare digit like `90` or `1990` out of a
    run entirely: it is never a key in `TABLE`."""
    return TABLE.get(_strip_trailing_punct(word))


def is_multiplier(word: str) -> bool:
    value = word_value(word)
    return value is not None and value in _MULTIPLIER_VALUES


def trailing_punctuation(token: str) -> str:
    """The trailing run of non-alphanumeric characters on an already-
    transliterated Latin token, e.g. `chhabbis.` -> `.`, `1990` -> ``.
    Used to carry punctuation onto a merged numeral token (§11.5)."""
    match = _TRAILING_LATIN_PUNCT_RE.search(token)
    return match.group(0) if match else ""


def _parse_run(words: Sequence[str]) -> int | None:
    """The §11.4 accumulate algorithm, defensively guarded so a
    malformed or ambiguous run is refused rather than guessed at
    (§11.5 rule 3) — e.g. the same multiplier tier appearing twice in
    one run (`हजार ... हजार`) is not a real Hindi numeral and is left
    alone rather than assigned an arbitrary value.

    Non-`सौ` multipliers are magnitude-ordered: track the largest such
    tier applied so far. A new tier larger than every prior non-`सौ`
    tier (including "no tier yet") scales everything accumulated
    (`total = (total + current) * v`); otherwise it closes a chunk
    (`total += current * v`). Refuse when both `total` and `current`
    are 0 (no invented `1`). `सौ` still multiplies `current` in place
    and is not magnitude-tracked. Compound tiers like
    `ग्यारह हज़ार करोड़` and pending-units shapes like
    `दो हज़ार छब्बीस करोड़` are therefore products, not sums."""
    total = 0
    current = 0
    max_tier = 0
    seen_multiplier_values: set[int] = set()
    for word in words:
        value = word_value(word)
        if value is None:
            return None  # defensive; run construction should prevent this
        if value in _MULTIPLIER_VALUES:
            if value in seen_multiplier_values:
                return None
            seen_multiplier_values.add(value)
            if value == 100:
                current = (current or 1) * 100
            elif total == 0 and current == 0:
                return None
            elif max_tier == 0 or value > max_tier:
                total = (total + current) * value
                current = 0
                max_tier = value
            else:
                total += current * value
                current = 0
        else:
            current += value
    return total + current


@dataclass(frozen=True)
class NumeralRun:
    """A run of consecutive narration-word indices (`start`..`end`,
    both inclusive) that parses to a single numeral `value`. Only runs
    that satisfy all three §11.5 rules are ever returned by
    `find_numeral_runs` — a caller never has to re-check them."""

    start: int
    end: int
    value: int


def find_numeral_runs(words: Sequence[str]) -> list[NumeralRun]:
    """Scan `words` (narration text, already whitespace-split) for
    maximal runs of consecutive Hindi number words and return only the
    runs that qualify for merging under §11.5:

    1. the run contains at least one multiplier
       (`सौ`/`हजार`/`लाख`/`करोड़`) — otherwise `एक दो` ("a couple")
       would parse to `3` and render as a nonsense digit;
    2. the run is two or more words — a lone `पचास` stays `pachaas`;
    3. the run parses completely (see `_parse_run`) — a run that does
       not is left alone entirely, never partially merged or guessed.

    Runs are found greedily and are non-overlapping by construction:
    each maximal run of table words is considered exactly once.
    """
    runs: list[NumeralRun] = []
    i = 0
    n = len(words)
    while i < n:
        if word_value(words[i]) is None:
            i += 1
            continue
        j = i
        while j < n and word_value(words[j]) is not None:
            j += 1
        run_words = words[i:j]
        if len(run_words) >= 2 and any(is_multiplier(w) for w in run_words):
            value = _parse_run(run_words)
            if value is not None:
                runs.append(NumeralRun(start=i, end=j - 1, value=value))
        i = j
    return runs


def apply_numeral_merging(
    narration_words: Sequence[str], display_words: Sequence[str]
) -> tuple[str, list[int]]:
    """Collapse each qualifying numeral run's display words into one
    digit token and derive the `caption_word_groups` entry alongside it.

    `narration_words` and `display_words` must be the same length (the
    planner's validator already guarantees this — plain 1:1
    transliteration, no merging done by the LLM). The merged token's
    trailing punctuation is taken from the LLM's own display token for
    the run's LAST word (`छब्बीस।` transliterates to `chhabbis.`, so the
    merged token is `2026.`, not `2026`) — never invented here.

    A scene with no qualifying runs comes back with an all-ones group
    list, byte-identical in shape to the pre-§10 plain path.
    """
    assert len(narration_words) == len(display_words)
    runs_by_start = {run.start: run for run in find_numeral_runs(narration_words)}

    tokens: list[str] = []
    groups: list[int] = []
    i = 0
    n = len(narration_words)
    while i < n:
        run = runs_by_start.get(i)
        if run is not None:
            punct = trailing_punctuation(display_words[run.end])
            tokens.append(f"{run.value}{punct}")
            groups.append(run.end - run.start + 1)
            i = run.end + 1
        else:
            tokens.append(display_words[i])
            groups.append(1)
            i += 1
    return " ".join(tokens), groups
