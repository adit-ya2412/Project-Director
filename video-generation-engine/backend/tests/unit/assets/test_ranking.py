"""Unit tests for the explicit weighted asset ranking function - pure,
no DB, no network (implementation guide, Phase M6 advice: "make ranking
explicit and weighted... log the component scores").

`AssetCandidate.relevance` (the provider's rank-position field) is NOT what
these tests vary to drive the "relevance" component - `rank_candidates` no
longer reads it (see app/assets/relevance.py for why: it's the provider's
result position, not a measure of whether the image matches the query).
Tests that exercise the relevance component instead pass `search_terms` and
vary `title`/`description`, the same real inputs `ResolveAssetsStep` gives
it."""

from app.assets.ranking import rank_candidates
from app.providers.base import AssetCandidate


def _candidate(**overrides) -> AssetCandidate:
    defaults = dict(
        source_id="c1",
        source_url="http://example.test/c1",
        title="a 1930s coal mine photograph",
        licence="cc0",
        width=1080,
        height=1920,
    )
    defaults.update(overrides)
    return AssetCandidate(**defaults)


def test_higher_relevance_wins_all_else_equal():
    low = _candidate(source_id="low", title="a modern city skyline")
    high = _candidate(source_id="high", title="Leuna Werke synthetic fuel plant 1943")
    ranked = rank_candidates(
        [(low, "hash-low"), (high, "hash-high")], search_terms=["Leuna Werke 1943"]
    )
    assert ranked[0].candidate.source_id == "high"


def test_higher_resolution_scores_higher_on_quality():
    small = _candidate(source_id="small", width=200, height=300)
    large = _candidate(source_id="large", width=1080, height=1920)
    ranked = rank_candidates([(small, "hash-small"), (large, "hash-large")])
    assert ranked[0].candidate.source_id == "large"


def test_unknown_dimensions_get_a_neutral_quality_score():
    unknown = _candidate(source_id="unknown", width=None, height=None)
    ranked = rank_candidates([(unknown, "hash-unknown")])
    assert ranked[0].components["quality"] == 0.5


def test_public_domain_outranks_unknown_licence_all_else_equal():
    pd = _candidate(source_id="pd", licence="public_domain")
    unknown = _candidate(source_id="unknown", licence="some_weird_licence")
    ranked = rank_candidates([(pd, "hash-pd"), (unknown, "hash-unknown")])
    assert ranked[0].candidate.source_id == "pd"


def test_title_matching_historical_period_scores_higher_on_period_match():
    matching = _candidate(source_id="matching", title="1936 Ruhr coal mine")
    unrelated = _candidate(source_id="unrelated", title="a modern skyline")
    ranked = rank_candidates(
        [(matching, "hash-matching"), (unrelated, "hash-unrelated")],
        historical_period="1936-1945",
    )
    assert ranked[0].candidate.source_id == "matching"


def test_no_historical_period_gives_neutral_period_match():
    candidate = _candidate()
    ranked = rank_candidates([(candidate, "hash-1")], historical_period="")
    assert ranked[0].components["period_match"] == 0.5


def test_no_search_terms_gives_a_zero_relevance_component():
    """`rank_candidates` is called on already-gated survivors; without
    `search_terms` (e.g. a caller that never had a query) it must not
    invent a relevance score out of nothing."""
    candidate = _candidate()
    ranked = rank_candidates([(candidate, "hash-1")])
    assert ranked[0].components["relevance"] == 0.0


def test_reuse_penalty_can_flip_the_ranking_despite_higher_relevance():
    reused = _candidate(source_id="reused", title="Leuna Werke synthetic fuel plant 1943")
    fresh = _candidate(source_id="fresh", title="a Leuna factory building")
    ranked = rank_candidates(
        [(reused, "hash-reused"), (fresh, "hash-fresh")],
        search_terms=["Leuna Werke 1943"],
        already_used_hashes=frozenset({"hash-reused"}),
    )
    reused_result = next(r for r in ranked if r.candidate.source_id == "reused")
    fresh_result = next(r for r in ranked if r.candidate.source_id == "fresh")
    assert reused_result.components["relevance"] > fresh_result.components["relevance"]
    assert ranked[0].candidate.source_id == "fresh"
    assert reused_result.components["reuse_penalty"] == 1.0


def test_results_are_sorted_descending_by_score():
    # Four distinctive query tokens (none in the generic-term list), so each
    # title below matches strictly one more of them than the last - a clean
    # 0/4, 1/4, 2/4, 3/4, 4/4 ladder with no ties to make ordering ambiguous.
    titles = [
        "a modern city skyline",  # matches nothing
        "a Leuna factory building",  # leuna
        "Leuna Werke plant",  # leuna, werke
        "Leuna Werke Buna plant",  # leuna, werke, buna
        "Leuna Werke Buna plant, 1943",  # leuna, werke, buna, 1943
    ]
    candidates = [_candidate(source_id=f"c{i}", title=title) for i, title in enumerate(titles)]
    ranked = rank_candidates(
        [(c, f"hash-{c.source_id}") for c in candidates],
        search_terms=["Leuna Werke Buna 1943"],
    )
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    # Not just trivially sorted (`rank_candidates` always sorts) - the
    # order must actually track increasing title/query overlap.
    assert [r.candidate.source_id for r in ranked] == ["c4", "c3", "c2", "c1", "c0"]
