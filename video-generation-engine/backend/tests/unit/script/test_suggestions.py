"""`app/script/suggestions.py` (motion_new_styles_and_long_form_videos.md
§3.2 level 2, §3.5.1) - pure, no network, no model. Every suggestion is
verified by actually APPLYING it and re-running the real splitter, not
by trusting the suggestion's own claim about what it will do.
"""

import json
from pathlib import Path

from app.planners.fragments import split_narration_fragments
from app.script.suggestions import suggest_breaks

_FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "m8_test_project.json").read_text(
        encoding="utf-8"
    )
)
_SCRIPT = _FIXTURE["script"]


def _apply(script: str, suggestions) -> str:
    modified = script
    for s in sorted(suggestions, key=lambda s: s.offset, reverse=True):
        modified = modified[: s.offset] + s.mark + modified[s.offset :]
    return modified


def test_no_suggestions_for_a_style_with_no_pacing_floor():
    assert suggest_breaks(_SCRIPT, "documentary_archival") == []


def test_suggestions_genuinely_increase_fragment_count_when_applied():
    """The real proof this module works: apply every suggestion, re-run
    the REAL splitter, and confirm N actually goes up - not merely that
    the suggestion's own `reason` string claims it will. Measured
    directly, 2026-08-17: 13 -> 20 fragments on the real fixture."""
    before_n = len(split_narration_fragments(_SCRIPT))
    suggestions = suggest_breaks(_SCRIPT, "retention_fast")
    assert len(suggestions) > 0

    modified = _apply(_SCRIPT, suggestions)
    after_n = len(split_narration_fragments(modified))
    assert after_n > before_n


def test_every_suggestion_lands_on_a_word_boundary():
    """A suggested mark must never split a word in half - the same
    "never mid-word, never mid-grapheme" discipline S1 established for
    the Shot Planner's own fragment boundaries, applied here to where a
    NEW mark of punctuation may be inserted."""
    for s in suggest_breaks(_SCRIPT, "retention_fast"):
        assert s.offset == 0 or _SCRIPT[s.offset - 1].isspace() or _SCRIPT[s.offset].isspace()


def test_comma_only_suggested_when_the_sentence_exceeds_the_clause_threshold():
    """§3.5.1's whole point: a comma suggestion must never be made for a
    sentence the real splitter would ignore a comma in."""
    from app.planners.fragments import LONG_FRAGMENT_THRESHOLD_CHARS
    from app.script.suggestions import _sentence_span

    for s in suggest_breaks(_SCRIPT, "retention_fast"):
        sentence_start, sentence_end = _sentence_span(_SCRIPT, s.offset)
        sentence_len = sentence_end - sentence_start
        if s.mark == ",":
            assert sentence_len > LONG_FRAGMENT_THRESHOLD_CHARS
        else:
            assert s.mark == "."
