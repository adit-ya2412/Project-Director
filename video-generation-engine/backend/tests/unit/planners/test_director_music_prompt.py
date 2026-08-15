"""M1 (M8 hardening, 2026-08-15): the Director's music `search_terms`
guidance must ask for simple, literal, keyword-tagged-library vocabulary
- not production-music jargon. This is a regression guard on the PROMPT
TEXT itself, not the planner's code (there is no code-level validator for
term style - see the Director planner's own `validate()`, which only
checks `search_terms` is non-empty): the actual defect this fixes lives
entirely in prompt wording, so the test that would catch a silent
regression has to look at the prompt file directly.

Measured motivation (`0711551`, and re-verified live against the real
Openverse API this session): the five jargon terms below returned ONE
permissive result between them (birdsong); simple literal terms return
dozens to hundreds each. This test cannot re-run that live measurement
(no network in a unit test), but it can make sure nobody quietly puts
the jargon phrasing back.
"""

from app.prompts.loader import load_prompt

_MEASURED_JARGON_EXAMPLES = [
    "investigative historical underscore",
    "minimal mechanical pulse",
]
_MEASURED_SIMPLE_EXAMPLES = [
    "documentary music",
    "ambient",
    "orchestral",
    "cinematic",
]


def test_director_prompt_asks_for_simple_literal_music_terms():
    prompt = load_prompt("director", "v1")

    for term in _MEASURED_SIMPLE_EXAMPLES:
        assert term in prompt, f"expected the prompt to recommend the simple term {term!r}"

    # The old jargon phrasing must not still be presented as a POSITIVE
    # example (a template a model would imitate) - it is fine, even good,
    # for it to appear as a named NEGATIVE example (which is exactly how
    # the current prompt uses it - "measured against the live API" - so
    # this asserts on the surrounding guidance rather than mere absence.
    assert "simple, literal" in prompt or "simple, literal, one-or-two-word" in prompt
    assert "production-library jargon" in prompt or "production-music catalogue" in prompt
    for jargon in _MEASURED_JARGON_EXAMPLES:
        assert jargon in prompt  # present as the documented cautionary example...
    # ...but the recommendation to use plain terms must appear too, so a
    # model reading the prompt sees the contrast, not just the jargon.
    assert "Openverse" in prompt
