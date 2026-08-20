"""SFX candidate ranking (parent plan §5.5). Inverse of the music
duration floor: a 3-minute bed is a defect here. Prefer clips that fit
`settings.sfx_max_clip_s` intact (R15 — same number the mix trims to)."""

from app.assets.relevance import term_overlap_relevance
from app.core.config import settings
from app.providers.base import TrackCandidate

_TAGS_HEAD_CHARS = 300


def sfx_candidate_relevance(query_terms: list[str], candidate: TrackCandidate) -> float:
    query_text = " ".join(query_terms)
    candidate_text = f"{candidate.title} {candidate.tags[:_TAGS_HEAD_CHARS]}"
    return term_overlap_relevance(query_text, candidate_text)


def _short_enough(candidate: TrackCandidate) -> bool:
    # R15: same ceiling the mix uses (`atrim=0:{sfx_max_clip_s}`), so
    # ranking cannot prefer a clip the mix will cut in half.
    ceiling = settings.sfx_max_clip_s
    return candidate.duration_s is not None and 0.05 <= candidate.duration_s <= ceiling


def rank_sfx_candidates(
    candidates: list[TrackCandidate], *, query_terms: list[str]
) -> list[TrackCandidate]:
    """Clips that fit the mix intact first, then shorter among those
    that do not (less truncation), then term-overlap, then source_id."""

    def _key(candidate: TrackCandidate) -> tuple[int, float, float, str]:
        fits = _short_enough(candidate)
        over = 0.0 if fits else (candidate.duration_s or 1e9)
        return (
            0 if fits else 1,
            over,
            -sfx_candidate_relevance(query_terms, candidate),
            candidate.source_id,
        )

    return sorted(candidates, key=_key)
