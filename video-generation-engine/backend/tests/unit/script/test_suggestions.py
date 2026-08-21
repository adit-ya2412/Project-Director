"""`app/script/suggestions.py` (motion_new_styles_and_long_form_videos.md
§3.2 level 2, §3.5.1) - pure, no network, no model. Every suggestion is
verified by actually APPLYING it and re-running the real splitter, not
by trusting the suggestion's own claim about what it will do.
"""

import json
from pathlib import Path

from app.planners.fragments import split_narration_fragments
from app.script.preflight import check_feasibility
from app.script.suggestions import (
    _suggest_breaks_one_round,
    apply_break_suggestions,
    suggest_breaks,
    suggestion_cap,
    working_offset_to_original,
)

_FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "m8_test_project.json").read_text(
        encoding="utf-8"
    )
)
_SCRIPT = _FIXTURE["script"]


def test_no_suggestions_for_a_style_with_no_pacing_floor():
    assert suggest_breaks(_SCRIPT, "documentary_archival").suggestions == []


def test_suggestions_genuinely_increase_fragment_count_when_applied():
    """The real proof this module works: apply every suggestion, re-run
    the REAL splitter, and confirm N actually goes up - not merely that
    the suggestion's own `reason` string claims it will."""
    before_n = len(split_narration_fragments(_SCRIPT))
    suggestions = suggest_breaks(_SCRIPT, "retention_fast").suggestions
    assert len(suggestions) > 0

    modified = apply_break_suggestions(_SCRIPT, suggestions)
    after_n = len(split_narration_fragments(modified))
    assert after_n > before_n


def test_every_suggestion_lands_on_a_word_boundary():
    """A suggested mark must never split a word in half - the same
    "never mid-word, never mid-grapheme" discipline S1 established for
    the Shot Planner's own fragment boundaries, applied here to where a
    NEW mark of punctuation may be inserted."""
    for s in suggest_breaks(_SCRIPT, "retention_fast").suggestions:
        assert s.offset == 0 or _SCRIPT[s.offset - 1].isspace() or _SCRIPT[s.offset].isspace()


def test_comma_only_suggested_when_the_sentence_exceeds_the_clause_threshold():
    """§3.5.1's whole point: a comma suggestion must never be made for a
    sentence the real splitter would ignore a comma in."""
    from app.planners.fragments import LONG_FRAGMENT_THRESHOLD_CHARS
    from app.script.suggestions import _sentence_span

    for s in suggest_breaks(_SCRIPT, "retention_fast").suggestions:
        sentence_start, sentence_end = _sentence_span(_SCRIPT, s.offset)
        sentence_len = sentence_end - sentence_start
        if s.mark == ",":
            assert sentence_len > LONG_FRAGMENT_THRESHOLD_CHARS
        else:
            assert s.mark == "."


def test_working_offset_maps_back_through_earlier_insertions():
    """Two original inserts at 3 and 7: working index 10 is original 8."""
    assert working_offset_to_original(10, [3, 7]) == 8
    assert working_offset_to_original(0, [3, 7]) == 0
    assert working_offset_to_original(4, [3]) == 3


def test_accepting_every_suggestion_makes_the_fixture_feasible_for_retention_fast():
    """R2: one response carries the transitive set. Accepting all of it
    must pass pre-flight, not leave the script still blocked."""
    assert not check_feasibility(_SCRIPT, "retention_fast").passed
    result = suggest_breaks(_SCRIPT, "retention_fast")
    assert result.suggestions
    modified = apply_break_suggestions(_SCRIPT, result.suggestions)
    after = check_feasibility(modified, "retention_fast")
    assert after.passed
    assert result.further_available is False
    assert result.would_pass is True
    assert result.unfixable == []


def test_a_second_round_is_included_when_one_split_is_not_enough():
    """R2's actual shape: midpoint-split once and the span is still
    over the band. The transitive call must keep going, not stop after
    the first round the way the pre-R2 API did."""
    sentence = ("word " * 40).strip() + ". "
    script = sentence * 3
    one_round = _suggest_breaks_one_round(script, "retention_fast", limit=40)
    result = suggest_breaks(script, "retention_fast")
    assert len(result.suggestions) > len(one_round)
    modified = apply_break_suggestions(script, result.suggestions)
    assert check_feasibility(modified, "retention_fast").passed
    assert result.further_available is False
    assert result.would_pass is True


def test_suggestion_cap_is_the_short_form_floor_on_the_fixture():
    assert suggestion_cap(_SCRIPT, "retention_fast") == 40
    assert suggestion_cap(_SCRIPT, "documentary_archival") == 0


def test_a_length_blind_cap_of_40_is_not_enough_for_long_form():
    """R21: ~196 s retention_fast needs more than 40 marks. The derived
    cap must still return the full set in one response."""
    sentence = ("word " * 16).strip() + ". "
    script = sentence * 40
    assert suggestion_cap(script, "retention_fast") > 40
    cramped = suggest_breaks(script, "retention_fast", max_suggestions=40)
    assert cramped.further_available is True
    assert cramped.would_pass is False
    result = suggest_breaks(script, "retention_fast")
    assert len(result.suggestions) > 40
    assert result.further_available is False
    assert result.would_pass is True
    modified = apply_break_suggestions(script, result.suggestions)
    assert check_feasibility(modified, "retention_fast").passed


def _script_with_n_sentences(*, n_sentences: int, chars: int) -> str:
    body = chars - 2 * n_sentences
    base, extra = divmod(body, n_sentences)
    parts: list[str] = []
    for i in range(n_sentences):
        n_chars = base + (1 if i < extra else 0)
        text = ("word " * (n_chars // 5 + 1))[:n_chars]
        parts.append(text + ". ")
    script = "".join(parts)
    assert len(script) == chars
    return script


def test_further_available_false_is_not_success_when_punctuation_cannot_pass():
    """R23: ran-out-of-breaks and now-feasible used to share one shape."""
    script = _script_with_n_sentences(n_sentences=120, chars=10209)
    result = suggest_breaks(script, "retention_fast")
    assert result.further_available is False
    assert result.would_pass is False
    assert result.unfixable
    assert "would need" in result.unfixable[0]
    assert "punctuation cannot shorten it" not in result.unfixable[0]
    modified = apply_break_suggestions(script, result.suggestions)
    assert not check_feasibility(modified, "retention_fast").passed


def test_a_script_over_the_hard_ceiling_is_not_padded_with_futile_marks():
    """R24: 1,188 s already exceeds 600 s. Punctuation cannot help."""
    from app.script.preflight import _chars_per_second

    chars = round(1188 * _chars_per_second("retention_fast"))
    script = _script_with_n_sentences(n_sentences=240, chars=chars)
    result = suggest_breaks(script, "retention_fast")
    assert result.suggestions == []
    assert result.further_available is False
    assert result.would_pass is False
    assert "600s" in result.unfixable[0]
    assert "cut words" in result.unfixable[0]
    assert "would need" not in result.unfixable[0]


def test_marks_that_would_push_over_the_ceiling_are_not_offered():
    """R24: 590.8 s is under 600 s, but enough marks to hit pace are not.

    Even the optimistic (needed − N) extra characters project over the
    hard ceiling, so the loop must not hand back 360 marks that fail.
    """
    script = _script_with_n_sentences(n_sentences=120, chars=10209)
    result = suggest_breaks(script, "retention_fast")
    assert result.would_pass is False
    assert result.further_available is False
    assert result.suggestions == []
    assert "cut words" in result.unfixable[0]
    assert "would need ~218 more marks" in result.unfixable[0]
    assert "~603s against a 600s maximum" in result.unfixable[0]
