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

Entity-curated candidates (`AssetCandidate.entity_curated`, M6.5 A1/A2) go
through this same relevance gate as everything else - an earlier version
of this pipeline exempted them on the theory that human curation implies
relevance; measured against the live API, that premise is false (a
Wikipedia article legitimately embeds off-topic images alongside the one
that matches a given shot - see `app/providers/wikimedia.py`). Here,
`entity_curated` is folded into the weighted score as a small, modest
component (`_W_ENTITY_CURATED`) rather than an overriding priority tier: a
measured run showed the tier version letting a poorly-matched
entity-curated candidate (e.g. a stray photo pulled in under a loosely
related article) beat an already-correct free-text hit outright. A modest
weight breaks a near-tie in favour of curated provenance without being
able to override a genuinely stronger free-text match on relevance/
quality/period.

**Reuse is a window, not a set (Track C C4).** A candidate used 8 minutes
ago is a callback; one used 8 seconds ago is a stutter. `reuse_penalty`
is 1.0 at a 0 s gap and decays linearly to 0 at `asset_reuse_window_s`
(60 s default; 20 s for `retention_fast`). The weight is 0.7, larger
than the old flat 0.4, because far reuse is no longer paying that 0.4
for free.

**`quality` measures adequacy for the render, not raw pixel count** - a
correction made after a live measurement traced a real wrong pick
(a Polish coal elevator photo beating two genuine Bundesarchiv Leuna-Werke
archival photos for a Leuna-Werke shot) to `_quality_score`, not to
relevance or to entity retrieval: the old formula was `min(1.0,
source_area / target_area)`, raw pixel count against the render target.
Since archival material is close to a century old and modern stock/
incidental photography is not, that formula systematically rewards a
candidate for being modern and penalises one for being archival - in a
tool whose entire visual language is archival documentary, that is
exactly backwards. See `_quality_score` for the corrected formula and the
threshold rationale.
"""

import math
from collections.abc import Mapping, Sequence
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
# Track C C4: near-reuse is punished harder than the old flat 0.4,
# because far reuse (a callback 8 minutes later) is no longer paying
# that 0.4 for free. Component is 1.0 at a 0 s gap, 0.0 at the window.
_W_REUSE_PENALTY = 0.7
# Deliberately the smallest weight in the formula - smaller than every
# other single component (the next-smallest, licence, is 0.15) - so
# entity-curated provenance can only break a close tie among otherwise
# similar candidates, never override a candidate that is genuinely more
# relevant, higher quality, or a better period match (M6.5, A2: measured
# against the live API, an unconditional priority tier let a poorly
# matched entity-curated candidate beat an already-correct free-text hit -
# see this module's docstring).
_W_ENTITY_CURATED = 0.08

# `quality` thresholds, expressed as the LINEAR upscale factor a source
# image would need to fill the render frame (`sqrt(target_area /
# source_area)`, not the raw area ratio the old formula used) - linear
# scale is what actually determines visible softness, since resampling
# error grows with the per-axis stretch, not with pixel-count ratio.
#
# - Up to ~1.5x linear upscale is full score: a 1.2-1.4x enlargement is
#   not perceptible at typical render/viewing sizes, and 1.5x is a
#   deliberately generous cutoff so a real archival scan a bit under the
#   render's native resolution isn't quietly marked down for being
#   archival - the exact defect this replaces (see module docstring).
# - Beyond that it degrades linearly, reaching the floor at a 4x linear
#   upscale, the rough point a stretch stops reading as "a bit soft" and
#   starts reading as visibly mushy/blocky.
# - The floor is 0.1, not 0.0: a small, low-resolution source is still
#   worse than nothing scoreable, but it may genuinely be the only real
#   photograph of its subject that exists, and 0.2 (the unknown-licence
#   floor) sets the precedent that "worst case" isn't zero either.
#
# Symmetrically, and just as deliberately: a source far ABOVE the render
# target (a 12MP modern photo against a 720x1280 target) gets no bonus for
# it - `min(..., 1.0)` already capped that before this fix, and still
# does. More pixels than the render needs are worth nothing; that half of
# the principle was already right. What was wrong was punishing not having
# more pixels than a modern camera produces.
_QUALITY_FULL_SCORE_UPSCALE = 1.5
_QUALITY_FLOOR_UPSCALE = 4.0
_QUALITY_FLOOR_SCORE = 0.1


@dataclass(frozen=True)
class RankedCandidate:
    candidate: AssetCandidate
    content_hash: str
    score: float
    components: dict[str, float]


def _quality_score(
    candidate: AssetCandidate, *, target_width: int, target_height: int
) -> float:
    """Adequacy for the render, not raw resolution (see module docstring
    for the defect this fixes: raw pixel count systematically penalises
    archival material for predating modern cameras)."""
    if not candidate.width or not candidate.height:
        return 0.5
    source_area = candidate.width * candidate.height
    target_area = target_width * target_height
    linear_upscale_needed = math.sqrt(target_area / source_area)

    if linear_upscale_needed <= _QUALITY_FULL_SCORE_UPSCALE:
        return 1.0
    if linear_upscale_needed >= _QUALITY_FLOOR_UPSCALE:
        return _QUALITY_FLOOR_SCORE

    span = _QUALITY_FLOOR_UPSCALE - _QUALITY_FULL_SCORE_UPSCALE
    fraction_degraded = (linear_upscale_needed - _QUALITY_FULL_SCORE_UPSCALE) / span
    return 1.0 - fraction_degraded * (1.0 - _QUALITY_FLOOR_SCORE)


def _period_match_score(candidate: AssetCandidate, historical_period: str) -> float:
    if not historical_period:
        return 0.5
    period_tokens = {tok for tok in historical_period.lower().replace("-", " ").split() if tok}
    title_tokens = set(candidate.title.lower().split())
    return 1.0 if period_tokens & title_tokens else 0.4


def _licence_score(candidate: AssetCandidate) -> float:
    return _LICENCE_SCORES.get(candidate.licence, _UNKNOWN_LICENCE_SCORE)


def reuse_window_s(style: str | None) -> float:
    """Seconds of rendered time inside which a reuse still costs. Never
    less than 1 s (a 0-window would make the penalty a no-op)."""
    resolved = style or settings.default_render_style
    raw = (
        settings.asset_reuse_window_s_fast
        if resolved == "retention_fast"
        else settings.asset_reuse_window_s
    )
    return max(1.0, raw)


def reuse_gaps_s(used_at_s: Mapping[str, Sequence[float]], shot_start_s: float) -> dict[str, float]:
    """`content_hash -> seconds since the most recent *earlier* use`.

    Uses strictly before this shot (D5 start times). A later-in-the-video
    binding must not penalise an earlier shot on resume.
    """
    gaps: dict[str, float] = {}
    for content_hash, times in used_at_s.items():
        prior = [t for t in times if t < shot_start_s]
        if prior:
            gaps[content_hash] = shot_start_s - max(prior)
    return gaps


def _reuse_penalty_component(gap_s: float, window_s: float) -> float:
    """1.0 at a 0 s gap, linear decay to 0 at `window_s` and beyond."""
    if window_s <= 0 or gap_s >= window_s:
        return 0.0
    if gap_s <= 0:
        return 1.0
    return 1.0 - (gap_s / window_s)


def _orientation_score(
    candidate: AssetCandidate, *, target_width: int, target_height: int
) -> float:
    """1.0 when source and frame share landscape/portrait, else 0.
    Unknown dimensions sit in the middle. Reordering only — never a
    hard filter (§19.8)."""
    if not candidate.width or not candidate.height:
        return 0.5
    source_landscape = candidate.width > candidate.height
    target_landscape = target_width > target_height
    return 1.0 if source_landscape == target_landscape else 0.0


def rank_candidates(
    candidates_with_hash: list[tuple[AssetCandidate, str]],
    *,
    search_terms: list[str] | None = None,
    historical_period: str = "",
    already_used_hashes: frozenset[str] = frozenset(),
    reuse_gap_s: Mapping[str, float] | None = None,
    window_s: float | None = None,
    shot_id: str = "",
    target_width: int | None = None,
    target_height: int | None = None,
) -> list[RankedCandidate]:
    """Highest score first. `candidates_with_hash` must already be
    deduped by content hash - this function does not dedupe - and already
    past the relevance hard gate; `search_terms` here only re-derives the
    graded score for ordering among survivors, it does not re-admit anyone
    the gate rejected.

    Track C C4: reuse is a gap in rendered seconds, not a global set.
    `reuse_gap_s` maps content_hash -> seconds since the most recent
    earlier use. Omit it and `already_used_hashes` still means "used
    just now" (gap 0, full penalty) so existing callers keep working.
    """
    search_terms = search_terms or []
    gaps = reuse_gap_s if reuse_gap_s is not None else {h: 0.0 for h in already_used_hashes}
    window = window_s if window_s is not None else settings.asset_reuse_window_s
    tw = target_width if target_width is not None else settings.render_width
    th = target_height if target_height is not None else settings.render_height
    ranked = []
    for candidate, content_hash in candidates_with_hash:
        gap = gaps.get(content_hash)
        components = {
            "relevance": candidate_relevance(search_terms, candidate),
            "quality": _quality_score(candidate, target_width=tw, target_height=th),
            "period_match": _period_match_score(candidate, historical_period),
            "licence": _licence_score(candidate),
            "reuse_penalty": (_reuse_penalty_component(gap, window) if gap is not None else 0.0),
            "entity_curated": 1.0 if candidate.entity_curated else 0.0,
            "orientation": _orientation_score(candidate, target_width=tw, target_height=th),
        }
        score = (
            _W_RELEVANCE * components["relevance"]
            + _W_QUALITY * components["quality"]
            + _W_PERIOD * components["period_match"]
            + _W_LICENCE * components["licence"]
            + _W_ENTITY_CURATED * components["entity_curated"]
            - _W_REUSE_PENALTY * components["reuse_penalty"]
        )
        ranked.append(
            RankedCandidate(
                candidate=candidate, content_hash=content_hash, score=score, components=components
            )
        )

    # §19.8: matching orientation breaks ties. It is not in the weighted
    # score so it cannot override relevance or reuse (R14). Equal-score
    # pairs (same title, same area) are the case it is built for.
    ranked.sort(
        key=lambda r: (-r.score, -r.components["orientation"], r.content_hash)
    )
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
