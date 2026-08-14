"""Pre-approval cost estimation and the budget cap - pure functions, no
DB, no network."""

import pytest

from app.assets.cost import check_budget, estimate_project_cost_cents
from app.core.config import settings
from app.core.errors import PermanentError
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    PreferredMediaType,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
)


def _timeline_with_shots(shots: list[Shot]) -> Timeline:
    from app.core.clock import utcnow
    from app.schemas.timeline import ProducedBy

    scene = Scene(
        id="sc_01", order=0, title="t", duration_s=sum(s.duration_s for s in shots), shots=shots
    )
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        created_at=utcnow(),
        scenes=[scene],
    )


def _shot(shot_id: str, strategy: AssetStrategy) -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        asset_plan=AssetPlan(
            strategy=strategy,
            preferred_type=PreferredMediaType.IMAGE,
            fallback_chain=[strategy],
        ),
    )


def test_search_primary_shots_cost_nothing():
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.HISTORICAL_SEARCH)])
    assert estimate_project_cost_cents(timeline) == 0


def test_generate_image_shot_costs_the_image_estimate():
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.GENERATE_IMAGE)])
    assert estimate_project_cost_cents(timeline) == settings.fal_image_cost_cents_estimate


def test_generate_video_shot_costs_image_plus_video_estimate():
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.GENERATE_VIDEO)])
    expected = settings.fal_image_cost_cents_estimate + settings.fal_video_cost_cents_estimate
    assert estimate_project_cost_cents(timeline) == expected


def test_shot_with_no_asset_plan_defaults_to_image_generation_cost():
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    timeline = _timeline_with_shots([shot])
    assert estimate_project_cost_cents(timeline) == settings.fal_image_cost_cents_estimate


def test_mixed_shots_sum_correctly():
    timeline = _timeline_with_shots(
        [
            _shot("sh_01", AssetStrategy.HISTORICAL_SEARCH),
            _shot("sh_02", AssetStrategy.GENERATE_IMAGE),
            _shot("sh_03", AssetStrategy.GENERATE_VIDEO),
        ]
    )
    expected = settings.fal_image_cost_cents_estimate + (
        settings.fal_image_cost_cents_estimate + settings.fal_video_cost_cents_estimate
    )
    assert estimate_project_cost_cents(timeline) == expected


def test_check_budget_passes_when_under_cap(monkeypatch):
    monkeypatch.setattr(settings, "project_budget_cap_cents", 1000)
    check_budget(already_spent_cents=500, additional_cents=100)  # must not raise


def test_check_budget_raises_when_exceeding_cap(monkeypatch):
    monkeypatch.setattr(settings, "project_budget_cap_cents", 1000)
    with pytest.raises(PermanentError, match="budget cap"):
        check_budget(already_spent_cents=950, additional_cents=100)


def test_check_budget_boundary_is_inclusive(monkeypatch):
    monkeypatch.setattr(settings, "project_budget_cap_cents", 1000)
    check_budget(already_spent_cents=900, additional_cents=100)  # exactly at cap, must not raise
