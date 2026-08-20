"""R17: a split shot is not done while its bottom panel has no outcome."""

from types import SimpleNamespace

from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    Camera,
    CameraMovement,
    Shot,
    ShotIntent,
)
from app.workflow.steps.resolve_assets import secondary_panel_done

_DONE = frozenset({"resolved", "generated", "failed", "skipped"})
_SEARCH_DONE = _DONE | {"awaiting_generation"}


def _split_shot() -> Shot:
    return Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=2.0,
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
        prompt="top",
        secondary_prompt="bottom",
        secondary_asset_plan=AssetPlan(strategy=AssetStrategy.HISTORICAL_SEARCH),
    )


def test_a_non_split_shot_is_done():
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=2.0)
    binding = SimpleNamespace(secondary_asset_id=None, secondary_clip_id=None, secondary_state=None)
    assert secondary_panel_done(shot, binding, done_states=_DONE)


def test_missing_secondary_is_not_done():
    binding = SimpleNamespace(secondary_asset_id=None, secondary_clip_id=None, secondary_state=None)
    assert not secondary_panel_done(_split_shot(), binding, done_states=_DONE)


def test_resolved_secondary_ids_are_done():
    binding = SimpleNamespace(
        secondary_asset_id="asset", secondary_clip_id=None, secondary_state="resolved"
    )
    assert secondary_panel_done(_split_shot(), binding, done_states=_DONE)


def test_failed_secondary_is_done_so_it_is_not_retried_forever():
    binding = SimpleNamespace(
        secondary_asset_id=None, secondary_clip_id=None, secondary_state="failed"
    )
    assert secondary_panel_done(_split_shot(), binding, done_states=_DONE)


def test_awaiting_generation_is_done_for_search_and_not_for_generation():
    binding = SimpleNamespace(
        secondary_asset_id=None, secondary_clip_id=None, secondary_state="awaiting_generation"
    )
    assert secondary_panel_done(_split_shot(), binding, done_states=_SEARCH_DONE)
    assert not secondary_panel_done(_split_shot(), binding, done_states=_DONE)
