"""Unit tests for the explicit weighted asset ranking function - pure,
no DB, no network (implementation guide, Phase M6 advice: "make ranking
explicit and weighted... log the component scores")."""

from app.assets.ranking import rank_candidates
from app.providers.base import AssetCandidate


def _candidate(**overrides) -> AssetCandidate:
    defaults = dict(
        source_id="c1",
        source_url="http://example.test/c1",
        title="a 1930s coal mine photograph",
        licence="cc0",
        relevance=0.5,
        width=1080,
        height=1920,
    )
    defaults.update(overrides)
    return AssetCandidate(**defaults)


def test_higher_relevance_wins_all_else_equal():
    low = _candidate(source_id="low", relevance=0.2)
    high = _candidate(source_id="high", relevance=0.9)
    ranked = rank_candidates([(low, "hash-low"), (high, "hash-high")])
    assert ranked[0].candidate.source_id == "high"


def test_higher_resolution_scores_higher_on_quality():
    small = _candidate(source_id="small", width=200, height=300, relevance=0.5)
    large = _candidate(source_id="large", width=1080, height=1920, relevance=0.5)
    ranked = rank_candidates([(small, "hash-small"), (large, "hash-large")])
    assert ranked[0].candidate.source_id == "large"


def test_unknown_dimensions_get_a_neutral_quality_score():
    unknown = _candidate(source_id="unknown", width=None, height=None)
    ranked = rank_candidates([(unknown, "hash-unknown")])
    assert ranked[0].components["quality"] == 0.5


def test_public_domain_outranks_unknown_licence_all_else_equal():
    pd = _candidate(source_id="pd", licence="public_domain", relevance=0.5)
    unknown = _candidate(source_id="unknown", licence="some_weird_licence", relevance=0.5)
    ranked = rank_candidates([(pd, "hash-pd"), (unknown, "hash-unknown")])
    assert ranked[0].candidate.source_id == "pd"


def test_title_matching_historical_period_scores_higher_on_period_match():
    matching = _candidate(source_id="matching", title="1936 Ruhr coal mine", relevance=0.5)
    unrelated = _candidate(source_id="unrelated", title="a modern skyline", relevance=0.5)
    ranked = rank_candidates(
        [(matching, "hash-matching"), (unrelated, "hash-unrelated")],
        historical_period="1936-1945",
    )
    assert ranked[0].candidate.source_id == "matching"


def test_no_historical_period_gives_neutral_period_match():
    candidate = _candidate()
    ranked = rank_candidates([(candidate, "hash-1")], historical_period="")
    assert ranked[0].components["period_match"] == 0.5


def test_reuse_penalty_can_flip_the_ranking_despite_lower_relevance():
    reused = _candidate(source_id="reused", relevance=1.0)
    fresh = _candidate(source_id="fresh", relevance=0.5)
    ranked = rank_candidates(
        [(reused, "hash-reused"), (fresh, "hash-fresh")],
        already_used_hashes=frozenset({"hash-reused"}),
    )
    assert ranked[0].candidate.source_id == "fresh"
    reused_result = next(r for r in ranked if r.candidate.source_id == "reused")
    assert reused_result.components["reuse_penalty"] == 1.0


def test_results_are_sorted_descending_by_score():
    candidates = [_candidate(source_id=f"c{i}", relevance=i / 10) for i in range(5)]
    ranked = rank_candidates([(c, f"hash-{c.source_id}") for c in candidates])
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)
