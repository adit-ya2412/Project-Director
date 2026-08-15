"""Unit tests for the real term-overlap relevance gate
(`app/assets/relevance.py`) - pure, no DB, no network.

The regression cases below are the real observed (query -> selected file)
pairs from an actual Hindi documentary run that resolved 11 shots from
Wikimedia Commons: only 2 of 11 assets actually matched what the shot
asked for. Every WRONG pair must fail `passes_relevance_gate`; both
CORRECT pairs must pass it. These are not invented examples - they are the
evidence the gate exists to fix.
"""

import pytest

from app.assets.relevance import passes_relevance_gate, term_overlap_relevance
from app.core.config import settings

# (query, selected filename/title, verdict) - verbatim from the real run.
_REGRESSION_CASES = [
    ("Germany coalfields map", "Train_wreck_at_Montparnasse_1895.jpg", False),
    ("German tanks rail yard", "Bf_Livraçao,_aus_Richtung_Amarante.jpg", False),
    ("Germany oil map 1942", "Cristo_crucificado.jpg", False),
    ("Ruhr coal mine 1940", "BNR_bogie_coal_hopper_wagon_1921.jpg", False),
    (
        "Leuna Werke 1943",
        "Bundesarchiv_B_145_Bild-F089027-0001,_Leuna,_Industrieanlagen.jpg",
        True,
    ),
    ("Bergius process diagram", "No.103_class_landing_ship.jpg", False),
    ("Sasol Secunda 1980", "Sasol_CTL,_Secunda.jpg", True),
    (
        "South Africa oil embargo",
        "Non-Native_American_Nations_Control_over_South_America_1700_and_on.gif",
        False,
    ),
    ("Ruhr rail yard 1940", "BNR_coal_wagon_17209.jpg", False),
    ("German oil depot 1940", "Schepen_in_een_sterke_wind_op_zee.jpg", False),
    ("Leuna Werke 1943", "Holzvergaser_Güssing.jpg", False),
]


@pytest.mark.parametrize("query, selected_title, should_pass", _REGRESSION_CASES)
def test_regression_corpus_from_real_hindi_documentary_run(query, selected_title, should_pass):
    score = term_overlap_relevance(query, selected_title)
    assert passes_relevance_gate(score) is should_pass, (
        f"query={query!r} candidate={selected_title!r} scored {score:.3f} "
        f"(threshold={settings.asset_relevance_threshold}) - expected "
        f"pass={should_pass}"
    )


def test_wrong_matches_score_below_correct_matches_with_a_clear_margin():
    """The gate threshold must sit strictly between the worst real WRONG
    score and the worst (lowest) real CORRECT score - proves the threshold
    isn't just accidentally tuned to pass/fail these exact cases."""
    wrong_scores = [
        term_overlap_relevance(q, t) for q, t, verdict in _REGRESSION_CASES if not verdict
    ]
    correct_scores = [
        term_overlap_relevance(q, t) for q, t, verdict in _REGRESSION_CASES if verdict
    ]
    assert max(wrong_scores) < min(correct_scores)


def test_south_alone_cannot_carry_a_match_against_a_different_place():
    # "South Africa" vs "South America" - only the generic direction word
    # "South" overlaps; that must not be enough.
    score = term_overlap_relevance("South Africa oil embargo", "South America map 1700")
    assert not passes_relevance_gate(score)


def test_coal_alone_cannot_carry_a_match_against_a_different_subject():
    # A coal *mine* is not a coal *wagon* - only the generic noun "coal"
    # overlaps; that must not be enough.
    score = term_overlap_relevance("Ruhr coal mine 1940", "British coal hopper wagon 1921")
    assert not passes_relevance_gate(score)


def test_a_single_distinctive_shared_term_is_enough():
    # Real proper nouns/rare words carry a match on their own - this is
    # exactly why the two real CORRECT matches worked.
    score = term_overlap_relevance("Leuna Werke 1943", "Leuna industrial plant")
    assert passes_relevance_gate(score)


def test_no_overlap_at_all_scores_zero():
    assert term_overlap_relevance("Leuna Werke 1943", "Cristo crucificado painting") == 0.0


def test_matching_candidate_description_counts_same_as_title():
    from app.providers.base import AssetCandidate

    candidate = AssetCandidate(
        source_id="1",
        source_url="http://example.test/1",
        title="IMG_0001.jpg",  # uninformative filename
        licence="cc0",
        description="Leuna Werke, synthetic fuel plant, 1943",
    )
    from app.assets.relevance import candidate_relevance

    assert passes_relevance_gate(candidate_relevance(["Leuna Werke 1943"], candidate))


def test_a_long_unrelated_description_does_not_win_on_coincidental_word_overlap():
    """Regression from the live check against the real Wikimedia API (not
    the original defect table - a second, independently-discovered failure
    mode). A real Commons item - a bronze statue of the Portuguese writer
    Eca de Queiros - carries a ~22,000-character auto-scraped biography as
    its `ImageDescription`. That biography happens to mention, in two
    unrelated passing sentences deep in the text, both "Germany" (an aside
    about literary influences) and "coalfields" (a detail of the writer's
    time in Newcastle) - enough for the query "Germany coalfields map" to
    score a perfect 1.0 before this was fixed, a worse false positive than
    any single-generic-word collision in the main regression table. Only
    the front of a description is trusted, because the real caption is
    always there and the coincidental-overlap risk grows with text volume."""
    from app.providers.base import AssetCandidate

    long_unrelated_bio = (
        ("Eca de Queiros Sculpture - Portuguese Writer. " + ("filler text. " * 200))
        + "his diplomatic duties concerned the coalfields of Northumberland, "
        + ("more filler text. " * 200)
        + "ideas, aesthetic systems, and Germany by way of France."
    )
    candidate = AssetCandidate(
        source_id="1",
        source_url="http://example.test/1",
        title="The Truth (unveiled 1903) - Teixeira Lopes.jpg",
        licence="cc0",
        description=long_unrelated_bio,
    )
    from app.assets.relevance import candidate_relevance

    assert not passes_relevance_gate(candidate_relevance(["Germany coalfields map"], candidate))


def test_empty_query_scores_zero_rather_than_dividing_by_zero():
    assert term_overlap_relevance("", "some title") == 0.0


def test_diacritics_and_case_are_normalised():
    # "Güssing" and "GUSSING" must tokenise identically for matching
    # purposes - a real title in the regression corpus carries a diacritic.
    assert term_overlap_relevance("Güssing", "GUSSING festival") == pytest.approx(1.0)
