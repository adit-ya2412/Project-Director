"""`app/assets/music_ranking.py` (M8, D6/21.2) - pure, fast, no network.
Reuses `app/assets/relevance.py`'s exact term-overlap function; these
tests are about the MUSIC-specific adaptation (title+tags instead of
title+description) and the ranking/tie-break behaviour, not re-proving
term-overlap scoring itself (see tests/unit/assets/test_relevance.py for
that)."""

from app.assets.music_ranking import music_candidate_relevance, rank_music_candidates
from app.providers.base import TrackCandidate


def _track(source_id: str, title: str, tags: str = "") -> TrackCandidate:
    return TrackCandidate(
        source_id=source_id,
        source_url=f"http://example.test/{source_id}",
        title=title,
        licence="cc0",
        tags=tags,
    )


def test_relevance_scores_a_genuine_term_match_higher_than_no_overlap():
    matching = _track("a", "sombre documentary underscore", tags="wartime, sparse strings")
    unrelated = _track("b", "upbeat pop dance track", tags="party, celebration")
    query_terms = ["documentary underscore", "sparse strings", "wartime"]

    assert music_candidate_relevance(query_terms, matching) > music_candidate_relevance(
        query_terms, unrelated
    )


def test_rank_orders_by_relevance_descending():
    matching = _track("a", "documentary underscore, wartime")
    unrelated = _track("b", "birthday party dance beat")
    ranked = rank_music_candidates([unrelated, matching], query_terms=["documentary underscore"])
    assert [c.source_id for c in ranked] == ["a", "b"]


def test_rank_ties_broken_deterministically_by_source_id():
    """No real signal either way (both tracks equally (ir)relevant) -
    ties must still resolve to a fixed order (I5), never dict/set
    iteration order."""
    same_a = _track("zzz", "")
    same_b = _track("aaa", "")
    ranked_1 = rank_music_candidates([same_a, same_b], query_terms=["anything"])
    ranked_2 = rank_music_candidates([same_b, same_a], query_terms=["anything"])
    assert [c.source_id for c in ranked_1] == [c.source_id for c in ranked_2] == ["aaa", "zzz"]


def test_rank_handles_an_empty_candidate_list():
    assert rank_music_candidates([], query_terms=["anything"]) == []
