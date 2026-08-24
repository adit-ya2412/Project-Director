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

import pytest

from app.assets.music_ranking import (
    compute_duration_floor_s,
    music_candidate_relevance,
    pick_seeded_top,
    rank_music_candidates,
    target_bpm_for_mean_shot_duration,
)
from app.providers.base import TrackCandidate


def _track(
    source_id: str,
    title: str,
    tags: str = "",
    duration_s: float | None = None,
    bpm: int | None = None,
) -> TrackCandidate:
    return TrackCandidate(
        source_id=source_id,
        source_url=f"http://example.test/{source_id}",
        title=title,
        licence="cc0",
        tags=tags,
        duration_s=duration_s,
        bpm=bpm,
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


def test_target_bpm_is_four_beats_per_mean_shot():
    """Plan §5.3: 1.75s shots ≈ 137 BPM on a 4-beat bar."""
    assert target_bpm_for_mean_shot_duration(1.75) == 240.0 / 1.75
    assert target_bpm_for_mean_shot_duration(0.0) is None


def test_tempo_fit_prefers_a_published_in_band_bpm_over_a_mismatch():
    """Equal relevance, equal duration: the 140 BPM industrial bed fits
    a 1.75s (137 BPM) cut; the 60 BPM funeral bed does not."""
    fit = _track("fit", "industrial ambient", duration_s=45.0, bpm=140)
    mismatch = _track("mismatch", "industrial ambient", duration_s=45.0, bpm=60)
    ranked = rank_music_candidates(
        [mismatch, fit],
        query_terms=["industrial"],
        video_duration_s=60.0,
        mean_shot_duration_s=1.75,
    )
    assert [c.source_id for c in ranked] == ["fit", "mismatch"]


def test_unknown_bpm_ranks_between_a_fit_and_a_known_mismatch():
    """A drone with no published tempo must not lose to a 180 BPM march
    just because the march published a number, and must still lose to a
    published-fit bed."""
    fit = _track("fit", "industrial ambient", duration_s=45.0, bpm=140)
    unknown = _track("drone", "industrial ambient", duration_s=45.0, bpm=None)
    mismatch = _track("march", "industrial ambient", duration_s=45.0, bpm=180)
    ranked = rank_music_candidates(
        [mismatch, unknown, fit],
        query_terms=["industrial"],
        video_duration_s=60.0,
        mean_shot_duration_s=1.75,
    )
    assert [c.source_id for c in ranked] == ["fit", "drone", "march"]


# -- M10 / analysis.md C2.2: the project-seeded near-tie pick ----------------

_QUERY = ["documentary", "strings"]


def _seeded_pool() -> list[TrackCandidate]:
    """Identical title+tags => identical relevance => the whole pool is a
    near-tie band the seed may choose from (the B2 scenario: every
    documentary-ish brief produces several near-equivalent candidates and
    plain source_id ordering always crowned the same one)."""
    return [
        _track(
            "doc_strings",
            "Documentary Music Strings",
            tags="documentary strings",
            duration_s=60.0,
        ),
        _track(
            "war_underscore",
            "Documentary Music Strings",
            tags="documentary strings",
            duration_s=60.0,
        ),
        _track(
            "archive_bed",
            "Documentary Music Strings",
            tags="documentary strings",
            duration_s=60.0,
        ),
    ]


def test_seeded_pick_is_deterministic_per_project():
    """I5: same project + same pool -> same pick, every time."""
    first = pick_seeded_top(_seeded_pool(), query_terms=_QUERY, seed="project-1")
    second = pick_seeded_top(_seeded_pool(), query_terms=_QUERY, seed="project-1")
    assert first.source_id == second.source_id


def test_different_projects_pick_different_tracks():
    """The actual B2 defect: same brief, different projects must not all
    land on the one source_id-sorted winner."""
    picks = {
        pick_seeded_top(_seeded_pool(), query_terms=_QUERY, seed=f"project-{i}").source_id
        for i in range(8)
    }
    assert len(picks) >= 2


def test_seed_cannot_promote_a_candidate_below_the_duration_floor():
    short = _track(
        "air_horn",
        "Documentary Music Strings",
        tags="documentary strings",
        duration_s=10.0,
    )
    proper = _track(
        "proper_bed",
        "Documentary Music Strings",
        tags="documentary strings",
        duration_s=60.0,
    )
    ranked = rank_music_candidates([short, proper], query_terms=_QUERY, video_duration_s=90.0)
    for seed in ("a", "b", "c", "d"):
        chosen = pick_seeded_top(ranked, query_terms=_QUERY, video_duration_s=90.0, seed=seed)
        assert chosen.source_id == "proper_bed"


def test_seed_cannot_promote_a_clearly_worse_match():
    """Outside the epsilon band the seed has no power at all - quality
    still owns the decision; variety only breaks ties."""
    strong = _track("exact_match", "wartime documentary underscore strings", duration_s=60.0)
    weak = _track("party_mix", "upbeat party dance celebration", duration_s=60.0)
    terms = ["wartime documentary underscore"]
    ranked = rank_music_candidates([weak, strong], query_terms=terms)
    for seed in ("a", "b", "c"):
        chosen = pick_seeded_top(ranked, query_terms=terms, seed=seed)
        assert chosen.source_id == "exact_match"


def test_single_candidate_returns_it_for_any_seed():
    solo = _track("only_choice", "Documentary Music Strings", tags="documentary strings")
    assert pick_seeded_top([solo], query_terms=_QUERY, seed="whatever").source_id == "only_choice"


def test_empty_pool_raises():
    with pytest.raises(ValueError):
        pick_seeded_top([], query_terms=_QUERY, seed="whatever")


def test_duration_floor_still_outranks_tempo_fit():
    """Lexicographic: a 2.5s one-shot at the perfect BPM still loses to
    a qualifying loop outside the band."""
    perfect_but_short = _track("short", "industrial ambient", duration_s=2.5, bpm=137)
    long_mismatch = _track("long", "industrial ambient", duration_s=45.0, bpm=60)
    ranked = rank_music_candidates(
        [perfect_but_short, long_mismatch],
        query_terms=["industrial"],
        video_duration_s=60.0,
        mean_shot_duration_s=1.75,
    )
    assert [c.source_id for c in ranked] == ["long", "short"]


def test_term_overlap_outranks_tempo_fit():
    """R14: a zero-relevance in-band track must not beat a matching
    brief that happens to sit outside the BPM band."""
    matching = _track("dark", "solemn memorial strings mourning", duration_s=45.0, bpm=48)
    catchy = _track("edm", "unrelated dance pop", duration_s=45.0, bpm=140)
    ranked = rank_music_candidates(
        [catchy, matching],
        query_terms=["solemn", "memorial", "strings", "mourning"],
        video_duration_s=60.0,
        mean_shot_duration_s=1.75,
    )
    assert ranked[0].source_id == "dark"


def test_tempo_key_is_inert_when_mean_shot_duration_is_unknown():
    """Callers that omit mean_shot_duration_s keep pre-§5.3 order."""
    mismatch = _track("a", "industrial ambient", duration_s=45.0, bpm=180)
    fit = _track("b", "industrial ambient", duration_s=45.0, bpm=140)
    ranked = rank_music_candidates(
        [mismatch, fit], query_terms=["industrial"], video_duration_s=60.0
    )
    assert [c.source_id for c in ranked] == ["a", "b"]  # source_id, equal relevance
