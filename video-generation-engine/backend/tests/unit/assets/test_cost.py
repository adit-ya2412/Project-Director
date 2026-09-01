"""Pre-approval cost estimation and the budget cap - pure functions, no
DB, no network."""

import pytest

from app.assets.cost import budget_cap_cents_for, check_budget, estimate_project_cost_cents
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


# --- diegetic SFX (long_form_direction.md A8) -------------------------------


def _cue_shot(shot_id: str, cue: str | None) -> Shot:
    # A search-primary `asset_plan` (free) isolates the assertions below to
    # ONLY the diegetic SFX estimate - a `None` asset_plan would also carry
    # the pre-existing "no binding yet -> assume image generation" cost
    # (`test_shot_with_no_asset_plan_defaults_to_image_generation_cost`
    # above), which has nothing to do with this section.
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        sfx_cue=cue,
        asset_plan=AssetPlan(
            strategy=AssetStrategy.HISTORICAL_SEARCH,
            preferred_type=PreferredMediaType.IMAGE,
            fallback_chain=[AssetStrategy.HISTORICAL_SEARCH],
        ),
    )


def test_a_pending_cue_bearing_shot_adds_the_diegetic_estimate():
    timeline = _timeline_with_shots([_cue_shot("sh_01", "a Geiger counter clicking")])
    assert estimate_project_cost_cents(timeline) == settings.sfx_diegetic_cost_cents_estimate


def test_a_shot_with_no_cue_adds_nothing():
    timeline = _timeline_with_shots([_cue_shot("sh_01", None)])
    assert estimate_project_cost_cents(timeline) == 0


def test_a_cue_shot_with_an_already_settled_diegetic_clip_adds_nothing():
    from app.schemas.timeline import SfxClipSelection, SfxKind, SfxPlan

    timeline = _timeline_with_shots([_cue_shot("sh_01", "a Geiger counter clicking")])
    timeline.sfx_plan = SfxPlan(
        clips=[
            SfxClipSelection(
                kind=SfxKind.DIEGETIC,
                provider="elevenlabs",
                track_id="h1",
                source_url="",
                licence="generated",
                content_hash="hash1",
                shot_id="sh_01",
            )
        ]
    )
    assert estimate_project_cost_cents(timeline) == 0


def test_a_cue_shot_already_marked_permanently_failed_adds_nothing():
    from app.schemas.timeline import SfxPlan

    timeline = _timeline_with_shots([_cue_shot("sh_01", "a Geiger counter clicking")])
    timeline.sfx_plan = SfxPlan(diegetic_failed_shot_ids=["sh_01"])
    assert estimate_project_cost_cents(timeline) == 0


def test_multiple_pending_cue_shots_sum():
    timeline = _timeline_with_shots(
        [
            _cue_shot("sh_01", "a Geiger counter clicking"),
            _cue_shot("sh_02", "a distant explosion"),
            _cue_shot("sh_03", None),
        ]
    )
    assert estimate_project_cost_cents(timeline) == 2 * settings.sfx_diegetic_cost_cents_estimate


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


def test_awaiting_generation_costs_the_image_estimate_even_with_a_search_primary_plan():
    """Task 5 (2026-08-16): the real defect - a shot whose PLAN's primary
    strategy is a search rung, but whose `ShotBinding.state` (the search
    pass's own verdict) is `"awaiting_generation"`, must be counted as a
    generation cost. Measured on a real run: 10 of 14 shots were queued
    to generate this way and the old, plan-only estimate read 0 for every
    one of them."""
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.HISTORICAL_SEARCH)])
    assert (
        estimate_project_cost_cents(timeline, {"sh_01": "awaiting_generation"})
        == settings.fal_image_cost_cents_estimate
    )


def test_awaiting_generation_video_shot_costs_image_plus_video_estimate():
    shot = _shot("sh_01", AssetStrategy.HISTORICAL_SEARCH)
    shot.asset_plan.preferred_type = PreferredMediaType.VIDEO
    timeline = _timeline_with_shots([shot])
    expected = settings.fal_image_cost_cents_estimate + settings.fal_video_cost_cents_estimate
    assert estimate_project_cost_cents(timeline, {"sh_01": "awaiting_generation"}) == expected


def test_resolved_shot_costs_nothing_even_with_a_generation_primary_plan():
    """A locked, human-overridden shot keeps its ORIGINAL `asset_plan`
    (A25 - a re-plan may never change it), which can legitimately still
    say `generate_image` even though the shot is now `"resolved"` for
    free via the override. Counting it here would double-charge an
    estimate for a shot that will never actually reach generation."""
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.GENERATE_IMAGE)])
    assert estimate_project_cost_cents(timeline, {"sh_01": "resolved"}) == 0


def test_generated_shot_costs_nothing_new_already_spent_and_counted_elsewhere():
    """A shot already `"generated"` was paid for once - that cost is
    reflected in `spent_cost_cents` (a separate figure), not counted a
    second time here as still-to-be-spent."""
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.GENERATE_IMAGE)])
    assert estimate_project_cost_cents(timeline, {"sh_01": "generated"}) == 0


def test_no_binding_yet_falls_back_to_the_plans_primary_strategy():
    """Search hasn't reached this shot at all yet (a fresh project, or a
    total provider outage, A22) - there is still no reliable way to
    predict a search hit rate before it runs, so this falls back to the
    original, documented-limited behaviour."""
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.GENERATE_IMAGE)])
    assert (
        estimate_project_cost_cents(timeline, {})
        == estimate_project_cost_cents(timeline)
        == settings.fal_image_cost_cents_estimate
    )


def test_mixed_binding_states_sum_correctly():
    timeline = _timeline_with_shots(
        [
            _shot("sh_01", AssetStrategy.HISTORICAL_SEARCH),  # awaiting_generation -> costs
            _shot("sh_02", AssetStrategy.HISTORICAL_SEARCH),  # resolved -> free
            _shot("sh_03", AssetStrategy.GENERATE_IMAGE),  # generated -> already spent
            _shot("sh_04", AssetStrategy.GENERATE_IMAGE),  # no binding yet -> plan fallback
        ]
    )
    binding_states = {
        "sh_01": "awaiting_generation",
        "sh_02": "resolved",
        "sh_03": "generated",
    }
    expected = settings.fal_image_cost_cents_estimate * 2  # sh_01 and sh_04 only
    assert estimate_project_cost_cents(timeline, binding_states) == expected


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


def test_check_budget_honours_an_explicit_length_aware_cap():
    """C6: a 10-minute cap (~6667) must not halt a $20 spend that the
    flat 1000¢ setting would reject."""
    check_budget(already_spent_cents=2000, additional_cents=50, cap_cents=6667)
    with pytest.raises(PermanentError, match="6667"):
        check_budget(already_spent_cents=6640, additional_cents=50, cap_cents=6667)


def test_budget_cap_for_a_short_timeline_is_todays_1000():
    timeline = _timeline_with_shots([_shot("sh_01", AssetStrategy.GENERATE_IMAGE)])
    assert budget_cap_cents_for(timeline) == settings.project_budget_cap_cents
