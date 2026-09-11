"""Deterministic Hindi-numeral merging (caption_romanization.md §11).

Pure functions, no fixtures, no LLM, no DB — this is the most testable
part of the whole feature. `--noconftest` on this explicitly named file
is still the required invocation (§4, §11.7), even though nothing here
touches a database.
"""

import pytest

from app.planners.caption_romanizer.numerals import (
    NumeralRun,
    _parse_run,
    apply_numeral_merging,
    find_numeral_runs,
    trailing_punctuation,
    word_value,
)

# ---- parser: the two pinned literals (§11.7) -------------------------------


def test_1931_pinned():
    words = "उन्नीस सौ इकतीस में उनका India में जन्म हुआ।".split()
    runs = find_numeral_runs(words)
    assert runs == [NumeralRun(start=0, end=2, value=1931)]


def test_2026_pinned():
    """A real run produced `2006` under §10's LLM-side merging — that
    is the bug this whole section exists to make impossible."""
    words = "दो हजार छब्बीस।".split()
    runs = find_numeral_runs(words)
    assert runs == [NumeralRun(start=0, end=2, value=2026)]
    assert runs[0].value != 2006


# ---- nukta / non-nukta spellings -------------------------------------------


def test_nukta_and_non_nukta_hazaar_parse_identically():
    assert word_value("हज़ार") == word_value("हजार") == 1000


# ---- rule 1: a run must contain a multiplier -------------------------------


def test_rule1_no_multiplier_is_not_merged():
    # "एक दो" ("a couple") would parse to 3 without this rule — a real
    # sentence turned into nonsense.
    assert find_numeral_runs("एक दो".split()) == []


def test_rule1_multiplier_present_is_merged():
    assert find_numeral_runs("तीन सौ".split()) == [NumeralRun(start=0, end=1, value=300)]


# ---- rule 2: a run must be two or more words -------------------------------


def test_rule2_lone_number_word_is_not_merged():
    assert find_numeral_runs(["पचास"]) == []


def test_rule2_lone_multiplier_word_is_not_merged():
    assert find_numeral_runs(["हजार"]) == []


# ---- rule 3: a run must parse completely, or be left alone -----------------


def test_rule3_repeated_multiplier_tier_is_left_alone():
    # "हजार ... हजार" is not a real Hindi numeral phrase — refuse to
    # guess rather than produce an arbitrary value.
    words = "दो हजार तीन हजार".split()
    assert find_numeral_runs(words) == []


# ---- defect A: digits already in the narration never enter a run ----------


def test_defect_a_bare_digits_are_never_merged():
    words = "90 percent whey".split()
    assert find_numeral_runs(words) == []


def test_defect_a_digit_adjacent_to_number_words_does_not_join_the_run():
    # "1990 mein 58 ki age" — digits break the run; "58" and "1990" are
    # not table entries at all, so they cannot be swallowed into a
    # neighbouring run the way §10's LLM-side merge did.
    words = "1990 में 58 की age में".split()
    assert find_numeral_runs(words) == []


# ---- punctuation -----------------------------------------------------------


def test_trailing_punctuation_extracted_from_latin_token():
    assert trailing_punctuation("chhabbis.") == "."
    assert trailing_punctuation("1990") == ""
    assert trailing_punctuation("theen।") == "।"


def test_apply_numeral_merging_takes_punctuation_from_llm_token_for_last_word():
    narration_words = "दो हजार छब्बीस।".split()
    display_words = "do hazaar chhabbis.".split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert caption_text == "2026."
    assert groups == [3]


# ---- apply_numeral_merging: groups and regression --------------------------


def test_apply_numeral_merging_1931_full_sentence():
    narration_words = "उन्नीस सौ इकतीस में उनका India में जन्म हुआ।".split()
    display_words = "unnis sau ikatees mein unka India mein janm hua.".split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert caption_text == "1931 mein unka India mein janm hua."
    assert groups == [3, 1, 1, 1, 1, 1, 1]
    assert sum(groups) == len(narration_words)
    assert len(groups) == len(caption_text.split())


def test_apply_numeral_merging_no_number_words_is_all_ones():
    narration_words = "वह बहुत प्रसिद्ध हो गए और चले गए।".split()
    display_words = "woh bahut prasiddh ho gaye aur chale gaye.".split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert caption_text == " ".join(display_words)
    assert groups == [1] * len(narration_words)


def test_apply_numeral_merging_defect_a_narration_is_unchanged():
    narration_words = "90 percent whey".split()
    display_words = "90 percent whey".split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert caption_text == "90 percent whey"
    assert groups == [1, 1, 1]


def test_apply_numeral_merging_groups_sum_to_narration_word_count():
    narration_words = "1990 में 58 की age में Osho की मौत हो गई।".split()
    display_words = "1990 mein 58 ki age mein Osho ki maut ho gayi.".split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert sum(groups) == len(narration_words)
    assert caption_text == " ".join(display_words)
    assert groups == [1] * len(narration_words)


# ---- K19 / K19.1: magnitude-ordered tiers; multiplier-only runs refuse ----
# K19: 13 verified cases. K19.1 replaces current-vs-total with
# magnitude-ordered tiers (22/22). Three flips vs shipped K19 for the
# pending-units-then-bigger-tier shape.


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        # K19 (must not regress)
        ("दो हज़ार छब्बीस", 2026),
        ("ग्यारह हज़ार", 11000),
        ("पचास लाख", 5000000),
        ("सौ करोड़", 1000000000),
        ("पांच सौ", 500),
        ("दो सौ पचास", 250),
        ("तीन करोड़", 30000000),
        ("एक लाख बीस हज़ार", 120000),
        ("दो हज़ार", 2000),
        ("ग्यारह हज़ार करोड़", 110000000000),
        ("दो लाख करोड़", 2000000000000),
        ("हज़ार करोड़", None),
        ("लाख करोड़", None),
        # reviewer extras
        ("दो सौ करोड़", 2000000000),
        ("करोड़ हज़ार", None),
        ("पचास हज़ार करोड़", 500000000000),
        ("एक करोड़ बीस लाख", 12000000),
        ("दो हज़ार पांच सौ", 2500),
        # K19.1 flips (pending units then bigger tier)
        ("दो हज़ार छब्बीस करोड़", 20260000000),
        ("एक हज़ार पांच सौ करोड़", 15000000000),
        ("दस हज़ार पचास करोड़", 100500000000),
        # control: units consumed by smaller हज़ार before करोड़
        ("एक लाख बीस हज़ार करोड़", 1200000000000),
    ],
)
def test_k19_parse_run_thirteen_verified_cases(run: str, expected: int | None):
    assert _parse_run(run.split()) == expected


def test_k19_compound_gayarah_hazaar_crore_finds_correct_run():
    words = "ग्यारह हज़ार करोड़".split()
    assert find_numeral_runs(words) == [
        NumeralRun(start=0, end=2, value=110000000000)
    ]


def test_k19_compound_do_lakh_crore_finds_correct_run():
    words = "दो लाख करोड़".split()
    assert find_numeral_runs(words) == [
        NumeralRun(start=0, end=2, value=2000000000000)
    ]


def test_k19_multiplier_only_hazaar_crore_is_refused():
    assert find_numeral_runs("हज़ार करोड़".split()) == []


def test_k19_multiplier_only_lakh_crore_is_refused():
    assert find_numeral_runs("लाख करोड़".split()) == []


def test_k19_apply_refused_multiplier_only_leaves_display_unmerged():
    narration_words = "हज़ार करोड़".split()
    display_words = "hazaar crore".split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert caption_text == "hazaar crore"
    assert groups == [1, 1]


def test_k19_apply_compound_emits_raw_integer_no_commas():
    # Look decision still open: raw int, not "11,000 crore". Pin current
    # emission so a readability ceiling cannot land silently.
    narration_words = "ग्यारह हज़ार करोड़".split()
    display_words = "gyaarah hazaar crore".split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert caption_text == "110000000000"
    assert groups == [3]


def test_k19_fy25_bare_digit_then_hazaar_crore_does_not_merge_to_10001000():
    # Live garble on 833dfd54: digit 11 stays out of TABLE; हज़ार करोड़
    # is refused; caption must not become "... 11 10001000 ...".
    narration_words = "FY25 में 11 हज़ार करोड़ से ज़्यादा कमाए।".split()
    display_words = "FY25 mein 11 hazaar crore se zyada kamaaye.".split()
    assert find_numeral_runs(narration_words) == []
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert "10001000" not in caption_text
    assert caption_text == "FY25 mein 11 hazaar crore se zyada kamaaye."
    assert groups == [1] * len(narration_words)


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        ("दो हज़ार छब्बीस करोड़", 20260000000),
        ("एक हज़ार पांच सौ करोड़", 15000000000),
        ("दस हज़ार पचास करोड़", 100500000000),
    ],
)
def test_k19_1_pending_units_then_bigger_tier_finds_correct_run(
    run: str, expected: int
):
    words = run.split()
    assert find_numeral_runs(words) == [
        NumeralRun(start=0, end=len(words) - 1, value=expected)
    ]


@pytest.mark.parametrize(
    ("narration", "display", "expected"),
    [
        (
            "दो हज़ार छब्बीस करोड़",
            "do hazaar chhabbis crore",
            "20260000000",
        ),
        (
            "एक हज़ार पांच सौ करोड़",
            "ek hazaar paanch sau crore",
            "15000000000",
        ),
        (
            "दस हज़ार पचास करोड़",
            "das hazaar pachaas crore",
            "100500000000",
        ),
    ],
)
def test_k19_1_apply_emits_raw_integer_no_commas(
    narration: str, display: str, expected: str
):
    # Ceiling still not done: correct values are bigger and still raw.
    narration_words = narration.split()
    display_words = display.split()
    caption_text, groups = apply_numeral_merging(narration_words, display_words)
    assert caption_text == expected
    assert groups == [len(narration_words)]
