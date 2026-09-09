"""K5: EmphasisPalette on TimelineMetadata — isolation, hex validation."""

import pytest
from pydantic import ValidationError

from app.schemas.timeline import EmphasisPalette, TimelineMetadata


def test_palette_fields_default_to_none():
    meta = TimelineMetadata()
    assert meta.emphasis_palette is None
    assert meta.emphasis_palette_override is None


def test_stored_timeline_without_palette_keys_loads_as_unset():
    """Additive default None: a document that predates the keys must
    load, not raise, and both fields must be None so the resolver takes
    the band fallback."""
    loaded = TimelineMetadata.model_validate({"render_style": "retention_fast"})
    assert loaded.emphasis_palette is None
    assert loaded.emphasis_palette_override is None
    dumped = TimelineMetadata(render_style="retention_fast").model_dump(mode="json")
    dumped.pop("emphasis_palette")
    dumped.pop("emphasis_palette_override")
    again = TimelineMetadata.model_validate(dumped)
    assert again.emphasis_palette is None
    assert again.emphasis_palette_override is None


def test_hex_validation_rejects_garbage_and_empty_string():
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="", pivot_ground="#FF2E2E")
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#FFC300", pivot_ground="")
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="FFC300", pivot_ground="#FF2E2E")
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#FFC30", pivot_ground="#FF2E2E")
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#FFC3000", pivot_ground="#FF2E2E")
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="amber", pivot_ground="#FF2E2E")
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#GGGGGG", pivot_ground="#FF2E2E")


def test_hex_is_normalised_to_uppercase():
    pair = EmphasisPalette(accent="#ffc300", pivot_ground="#ff2e2e")
    assert pair.accent == "#FFC300"
    assert pair.pivot_ground == "#FF2E2E"


def test_palette_round_trips_on_metadata():
    pair = EmphasisPalette(accent="#00C8FF", pivot_ground="#5A00A8")
    meta = TimelineMetadata(
        render_style="retention_fast",
        emphasis_palette=pair,
        emphasis_palette_override=None,
    )
    loaded = TimelineMetadata.model_validate(meta.model_dump(mode="json"))
    assert loaded.emphasis_palette is not None
    assert loaded.emphasis_palette.accent == "#00C8FF"
    assert loaded.emphasis_palette.pivot_ground == "#5A00A8"
    assert loaded.emphasis_palette_override is None
