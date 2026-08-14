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

from app.core.config import settings
from app.core.errors import PermanentError
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
    return total


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
