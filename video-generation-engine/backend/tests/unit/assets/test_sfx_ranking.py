"""SFX ranking prefers short overlay clips over long beds."""

from app.assets.sfx_ranking import rank_sfx_candidates
from app.providers.base import TrackCandidate


def _track(source_id: str, title: str, duration_s: float | None) -> TrackCandidate:
    return TrackCandidate(
        source_id=source_id,
        source_url=f"http://example.test/{source_id}",
        title=title,
        licence="cc0",
        duration_s=duration_s,
        tags="whoosh",
    )


def test_a_short_whoosh_beats_a_long_bed_of_the_same_terms():
    long_bed = _track("long", "whoosh drone bed", 180.0)
    whoosh = _track("short", "whoosh", 0.5)
    ranked = rank_sfx_candidates([long_bed, whoosh], query_terms=["whoosh"])
    assert [c.source_id for c in ranked] == ["short", "long"]


def test_a_clip_that_fits_the_mix_beats_one_the_mix_would_truncate():
    """R15: ceiling is sfx_max_clip_s (1.5), not a separate 4.0."""
    truncated = _track("creepy", "stinger", 4.0)
    intact = _track("whoosh_ok", "stinger", 0.5)
    ranked = rank_sfx_candidates([truncated, intact], query_terms=["stinger"])
    assert ranked[0].source_id == "whoosh_ok"


def test_among_over_length_clips_the_shorter_one_wins():
    """Less truncation when nothing fits intact."""
    four = _track("creepy", "stinger", 4.0)
    two = _track("stinger3", "stinger", 1.995)
    ranked = rank_sfx_candidates([four, two], query_terms=["stinger"])
    assert ranked[0].source_id == "stinger3"
