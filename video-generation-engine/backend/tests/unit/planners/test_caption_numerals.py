"""Deterministic Hindi-numeral merging (caption_romanization.md §11).

Pure functions, no fixtures, no LLM, no DB — this is the most testable
part of the whole feature. `--noconftest` on this explicitly named file
is still the required invocation (§4, §11.7), even though nothing here
touches a database.
"""

from app.planners.caption_romanizer.numerals import (
    NumeralRun,
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
