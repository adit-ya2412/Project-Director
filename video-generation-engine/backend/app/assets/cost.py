"""Pre-approval cost estimation and the hard per-project budget cap
(implementation guide, Phase M7 advice: "estimate cost before the
approval gate and show it"; "enforce a hard per-project budget cap...
exceeding it raises PermanentError and halts").

The estimate only counts shots whose primary `asset_plan.strategy` is
already a generation rung - a shot planned to resolve via search costs
nothing if the search succeeds, and there is no reliable way to predict
search hit-rate before actually running it. This under-estimates total
spend whenever search misses and a shot falls through to generation; that
is an honest, documented limitation, not a bug - claiming otherwise would
need real usage data this system doesn't have yet.
"""

import uuid

from app.core.config import settings
from app.core.errors import PermanentError
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import AssetStrategy, Timeline


def estimate_project_cost_cents(timeline: Timeline) -> int:
    total = 0
    for shot in timeline.all_shots():
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


def check_budget(*, already_spent_cents: int, additional_cents: int) -> None:
    """Raises PermanentError (never retryable - a retry storm against a
    paid API is the single most expensive failure mode this system has)
    if spending `additional_cents` more would exceed the project's hard
    cap."""
    projected = already_spent_cents + additional_cents
    if projected > settings.project_budget_cap_cents:
        raise PermanentError(
            f"generation would bring project spend to {projected} cents, exceeding the "
            f"{settings.project_budget_cap_cents} cent budget cap - halting further generation"
        )
