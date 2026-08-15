"""`app/assets/music_ranking.py` (M8, D6/21.2) - pure, fast, no network.
Reuses `app/assets/relevance.py`'s exact term-overlap function; these
tests are about the MUSIC-specific adaptation (title+tags instead of
title+description) and the ranking/tie-break behaviour, not re-proving
term-overlap scoring itself (see tests/unit/assets/test_relevance.py for
that).

The duration-floor tests below (M8 hardening, 2026-08-15) cover the
lexicographic preference added in `rank_music_candidates`/
`compute_duration_floor_s` - see that module's own docstring for why a
floor that REORDERS rather than DISCARDS was chosen over both a hard
gate (risks selecting nothing on a thin pool) and a pure weighted/soft
score (risks a short clip still winning on relevance alone)."""

from app.assets.music_ranking import (
    compute_duration_floor_s,
    music_candidate_relevance,
    rank_music_candidates,
)
from app.providers.base import TrackCandidate


def _track(
    source_id: str, title: str, tags: str = "", duration_s: float | None = None
) -> TrackCandidate:
    return TrackCandidate(
        source_id=source_id,
        source_url=f"http://example.test/{source_id}",
        title=title,
        licence="cc0",
        tags=tags,
        duration_s=duration_s,
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


def test_compute_duration_floor_scales_with_video_length_but_caps_at_the_absolute_ceiling():
    # A short video: half its own length, well under the 20s cap.
    assert compute_duration_floor_s(10.0) == 5.0
    # A long (documentary-length) video: capped at 20s, not half of 90s.
    assert compute_duration_floor_s(90.0) == 20.0
    # No known video length yet - no meaningful floor to apply.
    assert compute_duration_floor_s(0.0) == 0.0
    assert compute_duration_floor_s(-1.0) == 0.0


def test_a_one_shot_effect_never_beats_a_genuine_loop_when_one_exists():
    """The exact measured failure mode this floor exists to prevent: a
    2.5s air horn scoring the SAME relevance as a real ambient loop must
    still lose to it."""
    air_horn = _track("horn", "industrial air horn", tags="industrial, effect", duration_s=2.5)
    real_loop = _track(
        "loop", "industrial ambient loop", tags="industrial, ambient", duration_s=45.0
    )
    ranked = rank_music_candidates(
        [air_horn, real_loop], query_terms=["industrial"], video_duration_s=60.0
    )
    assert [c.source_id for c in ranked] == ["loop", "horn"]


def test_a_short_clip_with_far_better_relevance_still_loses_to_a_qualifying_one():
    """The floor is lexicographic, not a weighted blend (see module
    docstring on why) - a floor-passing candidate wins even when a
    floor-failing one matches the query terms far better."""
    perfect_but_short = _track("short", "documentary industrial ambient tension", duration_s=3.0)
    qualifies_but_weaker_match = _track("long", "instrumental", duration_s=45.0)
    ranked = rank_music_candidates(
        [perfect_but_short, qualifies_but_weaker_match],
        query_terms=["documentary", "industrial", "ambient", "tension"],
        video_duration_s=60.0,
    )
    assert [c.source_id for c in ranked] == ["long", "short"]


def test_when_nothing_meets_the_floor_the_best_relevance_match_still_wins_not_nothing():
    """The other half of "reorder, never discard": with no qualifying
    candidate at all, ranking still returns the best-matching short one
    rather than an empty result - the failure mode a hard gate risks."""
    better_match_short = _track("a", "industrial ambient", duration_s=2.0)
    worse_match_short = _track("b", "unrelated jingle", duration_s=3.0)
    ranked = rank_music_candidates(
        [worse_match_short, better_match_short],
        query_terms=["industrial", "ambient"],
        video_duration_s=60.0,
    )
    assert ranked[0].source_id == "a"  # still the best match, not discarded


def test_a_candidate_with_no_reported_duration_does_not_meet_the_floor():
    """Unverified is not the same as long enough (module docstring) -
    Openverse does not guarantee every result reports a duration."""
    unknown_duration = _track("unknown", "industrial ambient", duration_s=None)
    confirmed_long = _track("confirmed", "industrial ambient", duration_s=45.0)
    ranked = rank_music_candidates(
        [unknown_duration, confirmed_long],
        query_terms=["industrial", "ambient"],
        video_duration_s=60.0,
    )
    assert [c.source_id for c in ranked] == ["confirmed", "unknown"]


def test_duration_floor_is_a_no_op_when_video_duration_is_unknown():
    """`video_duration_s=0.0` (the default) - callers that don't yet know
    the video's planned length get the pre-M2 behaviour exactly: pure
    relevance ranking, no duration preference at all."""
    short = _track("short", "documentary underscore", duration_s=1.0)
    long_ = _track("long", "unrelated", duration_s=99.0)
    ranked = rank_music_candidates([short, long_], query_terms=["documentary underscore"])
    assert ranked[0].source_id == "short"  # relevance alone still decides
