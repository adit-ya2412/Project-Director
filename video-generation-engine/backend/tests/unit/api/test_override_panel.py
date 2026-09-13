"""Split-screen bottom-panel override writes secondary_* and leaves the
primary binding alone."""

from types import SimpleNamespace

import pytest

from app.api.projects import apply_override_to_binding


def test_primary_override_does_not_clear_the_bottom_panel():
    binding = SimpleNamespace(
        asset_id="old-primary",
        clip_id="old-clip",
        state="generated",
        rung="generate_image",
        last_error="x",
        secondary_asset_id="old-bottom",
        secondary_clip_id=None,
        secondary_state="resolved",
        secondary_last_error=None,
    )
    asset = SimpleNamespace(id="new-primary")
    apply_override_to_binding(binding, asset, panel="primary")
    assert binding.asset_id == "new-primary"
    assert binding.clip_id is None
    assert binding.state == "resolved"
    assert binding.secondary_asset_id == "old-bottom"


def test_secondary_override_does_not_clear_the_top_panel():
    binding = SimpleNamespace(
        asset_id="top",
        clip_id=None,
        state="resolved",
        rung="historical_search",
        last_error=None,
        secondary_asset_id="old-bottom",
        secondary_clip_id="old-bottom-clip",
        secondary_state="generated",
        secondary_last_error="x",
    )
    asset = SimpleNamespace(id="new-bottom")
    apply_override_to_binding(binding, asset, panel="secondary")
    assert binding.asset_id == "top"
    assert binding.state == "resolved"
    assert binding.secondary_asset_id == "new-bottom"
    assert binding.secondary_clip_id is None
    assert binding.secondary_state == "resolved"
    assert binding.secondary_last_error is None


def test_layer_panel_does_not_fall_through_to_primary():
    """P1: no per-layer binding column. Falling through would rebind the
    primary still and leave the plane unwritten."""
    binding = SimpleNamespace(asset_id="top", clip_id=None, state="resolved")
    asset = SimpleNamespace(id="must-not-apply")
    with pytest.raises(ValueError, match="layer planes persist via GeneratedClip"):
        apply_override_to_binding(binding, asset, panel="layer:1")
    assert binding.asset_id == "top"
