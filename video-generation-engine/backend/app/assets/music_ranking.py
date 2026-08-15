"""Music-candidate ranking (M8, D6/21.2). Reuses the exact term-overlap
relevance function visual assets already use
(`app/assets/relevance.term_overlap_relevance`), scored against a track's
own title + tags instead of a photo's title + description - the same
lesson from M6.5 applies here: a stock-music API's own result ordering is
not evidence that a track's mood/subject genuinely fits `music_plan`, any
more than a search provider's rank position was evidence a photo depicted
the right subject.

## The duration floor (M8, hardening 2026-08-15)

The render mix loops the chosen track to cover the video and trims to
length either way (`app/renderer/music.py`) - which is exactly why a
BONA FIDE short loop (a 20s ambient bed designed to repeat seamlessly)
is a perfectly legitimate pick even for a 90s video, and why this is
deliberately NOT "prefer the longest track" or "require duration >=
video length". The real defect this closes is different and narrower:
once the Director's search terms return a plentiful, thinly-curated pool
(M1), the single top hit for a query like `industrial` can be a
2.5-second air horn, or `tension` a 15-second stab - a one-shot sound
effect, not a composition meant to loop, which the render would then
repeat 10-30+ times back to back under a documentary.

**Chosen: a floor that reorders, never discards.** Candidates that meet
`compute_duration_floor_s` sort strictly ahead of ones that don't,
regardless of relevance score, but a track short of the floor is never
removed from the pool - only ranked behind every floor-passing
candidate. This was picked deliberately over the two more obvious
options, each of which reintroduces the failure mode the other one
fixes:

- **A hard gate** (discard anything under the floor) risks producing
  `selected_track=None` on a thin, honestly-filtered pool - literally
  how this defect was first noticed, and the coordinator's own explicit
  worry: "how we got here."
- **A pure weighted/soft preference** (duration folded into one blended
  score) risks the exact failure this floor exists to prevent: a
  short clip with strong term overlap can still outscore a long,
  weakly-matching one if the weights are not tuned exactly right, and
  there is no live corpus large enough to tune them against with
  confidence.

A **lexicographic** preference gets both guarantees at once: whenever
ANY floor-passing candidate exists, it always wins over a short one, no
matter the relevance gap (unlike a soft blend); and when NONE do, the
best-matching short candidate is still selected rather than nothing
(unlike a hard gate) - selecting a short loop that renders a little
repetitively is a strictly better outcome than silence, and is the
outcome this pool already produced before this fix existed (it is not a
regression, only no longer the risk-free case's default).

`compute_duration_floor_s` scales with the video's own length rather
than using one fixed constant: `min(_ABSOLUTE_FLOOR_S, 0.5 *
video_duration_s)`. `_ABSOLUTE_FLOOR_S = 20.0` is picked to sit above
the measured one-shot-effect cases (2.5s, 15s) and comfortably within
range of a genuine short ambient loop, without demanding a track cover
anywhere near a full 60-90s documentary - the render's own looping
already covers that gap. The `0.5 *` term keeps the floor from being
absurdly high relative to a short video (a 10s piece should not demand
a 20s track before preferring it). A candidate with no reported
duration (Openverse does not guarantee the field) is treated as NOT
meeting the floor - unverified is not the same as long enough, and
silently trusting a missing value would defeat the point of the floor.
"""

from app.assets.relevance import term_overlap_relevance
from app.providers.base import TrackCandidate

_TAGS_HEAD_CHARS = 300
_ABSOLUTE_FLOOR_S = 20.0


def music_candidate_relevance(query_terms: list[str], candidate: TrackCandidate) -> float:
    query_text = " ".join(query_terms)
    candidate_text = f"{candidate.title} {candidate.tags[:_TAGS_HEAD_CHARS]}"
    return term_overlap_relevance(query_text, candidate_text)


def compute_duration_floor_s(video_duration_s: float) -> float:
    """See this module's own docstring for the derivation. `0.0` (nothing
    is preferred over anything else on duration) for a non-positive
    `video_duration_s` - a project that doesn't yet know its own planned
    length has no meaningful video-relative floor to compute."""
    if video_duration_s <= 0.0:
        return 0.0
    return min(_ABSOLUTE_FLOOR_S, 0.5 * video_duration_s)


def _meets_duration_floor(candidate: TrackCandidate, *, floor_s: float) -> bool:
    if floor_s <= 0.0:
        return True
    return candidate.duration_s is not None and candidate.duration_s >= floor_s


def rank_music_candidates(
    candidates: list[TrackCandidate],
    *,
    query_terms: list[str],
    video_duration_s: float = 0.0,
) -> list[TrackCandidate]:
    """Candidates that meet the duration floor first (see module
    docstring - a lexicographic preference, never a hard filter), highest
    term-overlap relevance second, `source_id` last for determinism (I5)
    - never dict/set iteration order, which is not guaranteed stable
    across processes."""
    floor_s = compute_duration_floor_s(video_duration_s)

    def _key(candidate: TrackCandidate) -> tuple[int, float, str]:
        meets_floor = _meets_duration_floor(candidate, floor_s=floor_s)
        return (
            0 if meets_floor else 1,
            -music_candidate_relevance(query_terms, candidate),
            candidate.source_id,
        )

    return sorted(candidates, key=_key)
