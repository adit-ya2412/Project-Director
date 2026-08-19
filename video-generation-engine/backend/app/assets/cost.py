"""Pre-approval cost estimation and the hard per-project budget cap
(implementation guide, Phase M7 advice: "estimate cost before the
approval gate and show it"; "enforce a hard per-project budget cap...
exceeding it raises PermanentError and halts").

## Task 5 (2026-08-16): counting what will actually be generated

The estimate USED TO only count shots whose PRIMARY `asset_plan.strategy`
was already a generation rung - correct only back when a shot's asset
plan and its eventual acquisition rung were the same thing. After M6.5
split acquisition into a free search pass followed by a paid generation
pass (canon 3.1's ladder), that stopped being true: a shot whose primary
strategy is `historical_search` routinely falls through every search
rung and ends up generated anyway - after M6.5 this is the NORMAL route,
not an edge case - and the old estimate silently reported `0` for every
one of those shots. Measured on a real run: 10 of 14 shots were queued to
generate and this function still returned `0` (backlogged as a known
defect, `docs/13_Implementation_Guide.md`'s F3 section). With per-click
spending now possible at the one-gate design's approval gate
(`POST /shots/{id}/generate`), an estimate a human might actually decide
against is worse than useless if it is wrong in the direction of "this
looks free."

The fix needs `ShotBinding` state, not just the Timeline (the whole
reason `estimate_project_cost_cents` gained a second parameter): only the
search pass's own verdict - `ShotBinding.state == "awaiting_generation"` -
actually knows a shot fell through every free rung and WILL be
generated, regardless of what its `asset_plan.strategy` happens to say.
A shot with no binding yet (the search pass hasn't reached it - a fresh
project, or a total provider outage per A22) falls back to the OLD
primary-strategy guess, exactly as before - there is still no reliable
way to predict a search hit rate before it has actually run once, and
that half of the original limitation is honestly unchanged. A shot
already `"resolved"` (found for free, OR a human's own override/upload -
which never costs anything and must not be counted as if it will still
be generated) or `"generated"` (already paid for - and already reflected
in `spent_cost_cents`, so counting it here too would double it) is
excluded outright.
"""

import uuid

from app.core.config import settings
from app.core.errors import PermanentError
from app.planners.fragments import split_narration_fragments
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import AssetStrategy, PreferredMediaType, Timeline
from app.script.styles import resolve_constraint_bundle

# Binding states that mean "this shot already has media, of some kind" -
# nothing left to estimate a generation cost for, whichever way it got
# there (free search, a human's own override/upload, or a generation
# already paid for and counted in `spent_cost_cents`).
_ALREADY_HAS_MEDIA_STATES = frozenset({"resolved", "generated"})


def estimate_project_cost_cents(
    timeline: Timeline, binding_states: dict[str, str] | None = None
) -> int:
    """`binding_states` maps `shot_id -> ShotBinding.state` at the active
    version - optional (and ignored if omitted) so every existing caller
    that only has a `Timeline` in hand keeps working, at the OLD,
    documented-limited accuracy. `GET /progress` (the one real caller)
    already loads every binding for the active version for its own `shots`
    array, so passing them here costs it nothing extra - see that
    endpoint for where the dict is built."""
    binding_states = binding_states or {}
    total = 0
    for shot in timeline.all_shots():
        state = binding_states.get(shot.id)
        if state in _ALREADY_HAS_MEDIA_STATES:
            continue

        if state == "awaiting_generation":
            # The search pass's own verdict: every rung it was permitted
            # to use came up empty, so this shot WILL reach the
            # generation pass regardless of what its `asset_plan`'s
            # PRIMARY strategy happens to say - this is exactly the
            # normal-after-M6.5 case the old, plan-only estimate missed.
            preferred_type = (
                shot.asset_plan.preferred_type if shot.asset_plan else PreferredMediaType.IMAGE
            )
            total += settings.fal_image_cost_cents_estimate
            if preferred_type == PreferredMediaType.VIDEO:
                total += settings.fal_video_cost_cents_estimate
            continue

        # No binding yet (search hasn't reached this shot - a fresh
        # project, or a total provider outage, A22) or a non-terminal
        # state (`"pending"`/`"failed"`) - fall back to the shot's OWN
        # plan, same as the original estimate: there is still no reliable
        # way to predict whether a search rung will hit before it runs.
        strategy = shot.asset_plan.strategy if shot.asset_plan else AssetStrategy.GENERATE_IMAGE
        if strategy == AssetStrategy.GENERATE_VIDEO:
            # A video generation chains through an image keyframe first.
            total += settings.fal_image_cost_cents_estimate
            total += settings.fal_video_cost_cents_estimate
        elif strategy == AssetStrategy.GENERATE_IMAGE:
            total += settings.fal_image_cost_cents_estimate
    # M8 step 4: folded in for the same reason the generation estimate is
    # shown pre-approval at all - 0 by default (Pixabay search is free),
    # but a project whose music_plan exists is always shown the true
    # estimate for whatever provider is actually configured, never a
    # number that quietly excludes an entire acquisition category.
    if timeline.music_plan is not None:
        total += settings.music_cost_cents_estimate
    return total


async def total_project_spend_cents(
    *,
    clip_repo: GeneratedClipRepository,
    narration_repo: NarrationRepository,
    project_id: uuid.UUID,
) -> int:
    """Every cent already committed against the shared per-project cap,
    across every paid rung that counts against it: generated media
    (`GeneratedClip.cost_cents`, rungs 5-6) and TTS narration
    (`Narration.cost_cents`, M8's `NarrationStep`). `check_budget` itself
    stays a pure function - this is the ONE place the two DB-backed totals
    are added together, so a caller can never accidentally check the cap
    against only one of them (M8 open decision "does TTS count against the
    budget cap?" - yes; before this, `check_budget`'s callers only ever
    summed `generated_clip.cost_cents`, so a long, expensive script's TTS
    spend was invisible to the same cap that blocks a fourth generated
    clip).

    Music selection (M8 step 4) deliberately adds no third total here:
    unlike generated media and narration, a chosen track has no
    persisted `cost_cents` row anywhere - the Timeline records only its
    provenance (`MusicTrackSelection`, D6/I1/I2), because Pixabay search
    is genuinely free and there is nothing to bill. `SelectMusicStep`
    still calls `check_budget` against this same total before every
    fetch attempt (`settings.music_cost_cents_estimate`, 0 by default) -
    the structural guarantee holds even though, today, music itself
    never has anything real to add to it."""
    clip_total = await clip_repo.total_cost_cents_for_project(project_id)
    narration_total = await narration_repo.total_cost_cents_for_project(project_id)
    return clip_total + narration_total


def budget_cap_cents_for(timeline: Timeline) -> int:
    """Length-aware project cap (Track C C6). 90 s and `n_fragments=None`
    resolve to `settings.project_budget_cap_cents` (1000). One resolver
    with the rest of the bounds — do not read the flat setting at a
    check site (R1)."""
    text = "".join(s.narration_text for s in timeline.scenes)
    n = len(split_narration_fragments(text)) if text else None
    return resolve_constraint_bundle(timeline.metadata.render_style, n_fragments=n).budget_cap_cents


def check_budget(
    *,
    already_spent_cents: int,
    additional_cents: int,
    cap_cents: int | None = None,
) -> None:
    """Raises PermanentError (never retryable - a retry storm against a
    paid API is the single most expensive failure mode this system has)
    if spending `additional_cents` more would exceed the project's hard
    cap.

    `cap_cents` is the length-aware C6 cap. Omit it and the 90 s default
    (`settings.project_budget_cap_cents`) is used — that default is the
    *safe* direction (halts too early on a long-form project), not an
    overspend.
    """
    cap = settings.project_budget_cap_cents if cap_cents is None else cap_cents
    projected = already_spent_cents + additional_cents
    if projected > cap:
        raise PermanentError(
            f"generation would bring project spend to {projected} cents, exceeding the "
            f"{cap} cent budget cap - halting further generation"
        )
