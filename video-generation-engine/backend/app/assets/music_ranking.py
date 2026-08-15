"""Music-candidate ranking (M8, D6/21.2). Reuses the exact term-overlap
relevance function visual assets already use
(`app/assets/relevance.term_overlap_relevance`), scored against a track's
own title + tags instead of a photo's title + description - the same
lesson from M6.5 applies here: a stock-music API's own result ordering is
not evidence that a track's mood/subject genuinely fits `music_plan`, any
more than a search provider's rank position was evidence a photo depicted
the right subject.

No duration-based preference in the ranking itself: the render mix loops
the chosen track to cover the video and trims to length either way (see
`app/renderer/music.py`), so a track's own reported length is not a
reason to prefer one candidate over another here.
"""

from app.assets.relevance import term_overlap_relevance
from app.providers.base import TrackCandidate

_TAGS_HEAD_CHARS = 300


def music_candidate_relevance(query_terms: list[str], candidate: TrackCandidate) -> float:
    query_text = " ".join(query_terms)
    candidate_text = f"{candidate.title} {candidate.tags[:_TAGS_HEAD_CHARS]}"
    return term_overlap_relevance(query_text, candidate_text)


def rank_music_candidates(
    candidates: list[TrackCandidate], *, query_terms: list[str]
) -> list[TrackCandidate]:
    """Highest term-overlap relevance first; ties broken by `source_id`
    for determinism (I5) - never by dict/set iteration order, which is
    not guaranteed stable across processes."""

    def _key(candidate: TrackCandidate) -> tuple[float, str]:
        return (-music_candidate_relevance(query_terms, candidate), candidate.source_id)

    return sorted(candidates, key=_key)
