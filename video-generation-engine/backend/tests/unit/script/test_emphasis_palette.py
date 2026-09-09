"""K5: resolve_emphasis_palette precedence and band fallback."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.colour import hex_luma
from app.schemas.timeline import (
    PIVOT_GROUND_MAX_LUMA,
    EmphasisPalette,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineMetadata,
    TimelineStatus,
)
from app.script.styles import (
    EMPHASIS_SPIKE_ACCENT,
    EMPHASIS_SPIKE_PIVOT_GROUND,
    resolve_emphasis_palette,
)

_SPIKE = EmphasisPalette(
    accent=EMPHASIS_SPIKE_ACCENT, pivot_ground=EMPHASIS_SPIKE_PIVOT_GROUND
)
_CYAN = EmphasisPalette(accent="#00C8FF", pivot_ground="#5A00A8")
_GREEN = EmphasisPalette(accent="#00FF88", pivot_ground="#113300")


def _timeline(
    *,
    render_style: str | None = "retention_fast",
    palette: EmphasisPalette | None = None,
    override: EmphasisPalette | None = None,
) -> Timeline:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=2.0)
    scene = Scene(id="sc_01", order=0, title="t", duration_s=2.0, shots=[shot])
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata=TimelineMetadata(
            render_style=render_style,
            emphasis_palette=palette,
            emphasis_palette_override=override,
        ),
        scenes=[scene],
    )


def test_unset_retention_fast_falls_back_to_the_spike_pair():
    resolved = resolve_emphasis_palette(_timeline())
    assert resolved.accent == "#FFC300"
    assert resolved.pivot_ground == "#FF2E2E"
    assert (resolved.accent, resolved.pivot_ground) == (
        _SPIKE.accent,
        _SPIKE.pivot_ground,
    )


def test_override_beats_planner_beats_channel_beats_band():
    timeline = _timeline(palette=_CYAN, override=_GREEN)
    assert resolve_emphasis_palette(
        timeline, channel_accent="#111111", channel_pivot_ground="#222222"
    ) == _GREEN

    no_override = _timeline(palette=_CYAN)
    assert resolve_emphasis_palette(
        no_override, channel_accent="#111111", channel_pivot_ground="#222222"
    ) == _CYAN

    channel_only = _timeline()
    channel = resolve_emphasis_palette(
        channel_only, channel_accent="#00AAFF", channel_pivot_ground="#440088"
    )
    assert channel.accent == "#00AAFF"
    assert channel.pivot_ground == "#440088"

    band = resolve_emphasis_palette(_timeline())
    assert band.accent == "#FFC300"
    assert band.pivot_ground == "#FF2E2E"


def test_channel_may_mix_with_the_band_when_only_one_role_is_set():
    mixed = resolve_emphasis_palette(
        _timeline(), channel_accent="#00C8FF", channel_pivot_ground=None
    )
    assert mixed.accent == "#00C8FF"
    assert mixed.pivot_ground == "#FF2E2E"


def test_non_retention_style_returns_the_spike_pair_not_a_second_system():
    """Last-last fallback is the spike pair so the compositor never
    invents hexes. Same pair retention_fast records."""
    archival = resolve_emphasis_palette(_timeline(render_style="documentary_archival"))
    assert archival.accent == EMPHASIS_SPIKE_ACCENT
    assert archival.pivot_ground == EMPHASIS_SPIKE_PIVOT_GROUND
    unknown = resolve_emphasis_palette(_timeline(render_style="no_such_style"))
    assert unknown.accent == EMPHASIS_SPIKE_ACCENT
    assert unknown.pivot_ground == EMPHASIS_SPIKE_PIVOT_GROUND


def test_garbage_channel_hex_raises():
    with pytest.raises(ValueError, match="#RRGGBB"):
        resolve_emphasis_palette(_timeline(), channel_accent="amber")
    with pytest.raises(ValueError, match="#RRGGBB"):
        resolve_emphasis_palette(_timeline(), channel_accent="")


def test_every_resolved_ground_clears_the_pivot_ground_ceiling():
    """The resolver builds an `EmphasisPalette`, so the schema's
    `pivot_ground` ceiling (K5 review finding) guards the channel default
    and the style band too — not just a planner-authored pair.

    This is the regression that matters: change
    `StylePacingBand.emphasis_pivot_ground` or
    `settings.emphasis_pivot_ground` to something white type vanishes
    into and the resolver stops resolving instead of shipping an
    invisible pivot.
    """
    resolved = resolve_emphasis_palette(_timeline())
    assert resolved.pivot_ground == EMPHASIS_SPIKE_PIVOT_GROUND
    assert hex_luma(resolved.pivot_ground) <= PIVOT_GROUND_MAX_LUMA

    with pytest.raises(ValidationError):
        resolve_emphasis_palette(_timeline(), channel_pivot_ground="#FAFAFA")

