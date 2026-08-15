"""Explicit, weighted asset ranking (implementation guide, Phase M6
advice: "make ranking explicit and weighted, in one function... log the
component scores for the top 5 candidates. When someone asks 'why did it
pick that photo?', the answer must be in the logs.").

Ranking runs on already-fetched, already-deduped candidates (dedup by
content hash happens before this, in the resolve_assets step - the same
image arriving from two providers under different URLs must not be
ranked as two separate options), and on candidates that have already
passed the relevance hard gate (`app/assets/relevance.py`,
`passes_relevance_gate`) - a candidate below that threshold never reaches
this function at all, the same way a licence-rejected one never does. The
"relevance" component computed here is the same real term-overlap score,
kept as a graded input (not just a pass/fail) so that among several
candidates that all clear the gate, a stronger textual match still outranks
a weaker one.
"""

from dataclasses import dataclass

from app.assets.relevance import candidate_relevance
from app.core.config import settings
from app.core.logging import get_logger
from app.providers.base import AssetCandidate

logger = get_logger(__name__)

_LICENCE_SCORES = {
    "public_domain": 1.0,
    "cc0": 1.0,
    "cc_by": 0.7,
    "pexels_licence": 0.6,
}
_UNKNOWN_LICENCE_SCORE = 0.2

_W_RELEVANCE = 0.35
_W_QUALITY = 0.2
_W_PERIOD = 0.2
_W_LICENCE = 0.15
_W_REUSE_PENALTY = 0.4


@dataclass(frozen=True)
class RankedCandidate:
    candidate: AssetCandidate
    content_hash: str
    score: float
    components: dict[str, float]


def _quality_score(candidate: AssetCandidate) -> float:
    if candidate.width is None or candidate.height is None:
        return 0.5
    target_area = settings.render_width * settings.render_height
    return min(1.0, (candidate.width * candidate.height) / target_area)


def _period_match_score(candidate: AssetCandidate, historical_period: str) -> float:
    if not historical_period:
        return 0.5
    period_tokens = {tok for tok in historical_period.lower().replace("-", " ").split() if tok}
    title_tokens = set(candidate.title.lower().split())
    return 1.0 if period_tokens & title_tokens else 0.4


def _licence_score(candidate: AssetCandidate) -> float:
    return _LICENCE_SCORES.get(candidate.licence, _UNKNOWN_LICENCE_SCORE)


def rank_candidates(
    candidates_with_hash: list[tuple[AssetCandidate, str]],
    *,
    search_terms: list[str] | None = None,
    historical_period: str = "",
    already_used_hashes: frozenset[str] = frozenset(),
    shot_id: str = "",
) -> list[RankedCandidate]:
    """Highest score first. `candidates_with_hash` must already be
    deduped by content hash - this function does not dedupe - and already
    past the relevance hard gate; `search_terms` here only re-derives the
    graded score for ordering among survivors, it does not re-admit anyone
    the gate rejected."""
    search_terms = search_terms or []
    ranked = []
    for candidate, content_hash in candidates_with_hash:
        components = {
            "relevance": candidate_relevance(search_terms, candidate),
            "quality": _quality_score(candidate),
            "period_match": _period_match_score(candidate, historical_period),
            "licence": _licence_score(candidate),
            "reuse_penalty": 1.0 if content_hash in already_used_hashes else 0.0,
        }
        score = (
            _W_RELEVANCE * components["relevance"]
            + _W_QUALITY * components["quality"]
            + _W_PERIOD * components["period_match"]
            + _W_LICENCE * components["licence"]
            - _W_REUSE_PENALTY * components["reuse_penalty"]
        )
        ranked.append(
            RankedCandidate(
                candidate=candidate, content_hash=content_hash, score=score, components=components
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    for rank in ranked[:5]:
        logger.info(
            "asset.ranking.candidate",
            extra={
                "shot_id": shot_id,
                "source_id": rank.candidate.source_id,
                "content_hash": rank.content_hash,
                "score": round(rank.score, 3),
                **{f"component_{k}": round(v, 3) for k, v in rank.components.items()},
            },
        )
    return ranked
