"""K5: EmphasisPalette on TimelineMetadata — isolation, hex validation."""

import pytest
from pydantic import ValidationError

from app.core.colour import hex_luma
from app.schemas.timeline import (
    PIVOT_GROUND_MAX_LUMA,
    EmphasisPalette,
    TimelineMetadata,
)


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


# ---------------------------------------------------------------------------
# `pivot_ground` legibility ceiling (K5 review finding, 2026-09-09).
# `Pivot.tsx` draws the pivot's type #FFFFFF unconditionally because the band
# IS its ground, so K4 never measures this fill and cannot rescue it. The
# measurement behind 140.0 is recorded at the constant.
# ---------------------------------------------------------------------------


def test_both_known_good_pivot_grounds_still_construct():
    """The two grounds that have actually been looked at must stay valid.

    A threshold that rejects either of these is wrong by definition:
    `#FF2E2E` is what every reel renders today (the style band default)
    and `#5A00A8` is the reviewed authored case from the K5 slice.
    """
    shipped = EmphasisPalette(accent="#FFC300", pivot_ground="#FF2E2E")
    assert shipped.pivot_ground == "#FF2E2E"
    assert hex_luma("#FF2E2E") == pytest.approx(108.5, abs=0.1)

    authored = EmphasisPalette(accent="#00C8FF", pivot_ground="#5A00A8")
    assert authored.pivot_ground == "#5A00A8"
    assert hex_luma("#5A00A8") == pytest.approx(46.1, abs=0.1)


def test_near_white_pivot_ground_raises_and_says_why():
    """The failure the guard exists for: measured 250.0, rendered white-on-white
    (tmp/k5_pivot_luma/pivot_invisible_250.png, sampled contrast 1.04:1)."""
    with pytest.raises(ValidationError) as excinfo:
        EmphasisPalette(accent="#FFC300", pivot_ground="#FAFAFA")
    message = str(excinfo.value)
    # Names the actual problem, not "invalid colour".
    assert "illegible" in message
    assert "#FFFFFF" in message
    # Carries the measurement and the limit.
    assert "250.0" in message
    assert "140.0" in message


def test_pure_white_pivot_ground_raises():
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#FFC300", pivot_ground="#FFFFFF")
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#FFC300", pivot_ground="#FFF8F0")


def test_the_boundary_is_where_the_constant_says_it_is():
    """Either side of 140.0, in both hue families that were rendered.

    `#8C8C8C` is neutral grey at luma exactly 140.0 and is the last
    accepted ground; `#8D8D8D` is 141.0 and is rejected. `#FF5D5D` is
    the shipped default's own hue family at 141.4 and is also rejected —
    that ramp is the pessimistic one, measured at 3.01:1 in the render.
    """
    assert hex_luma("#8C8C8C") == pytest.approx(PIVOT_GROUND_MAX_LUMA, abs=0.05)
    inside = EmphasisPalette(accent="#FFC300", pivot_ground="#8C8C8C")
    assert inside.pivot_ground == "#8C8C8C"

    assert hex_luma("#8D8D8D") > PIVOT_GROUND_MAX_LUMA
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#FFC300", pivot_ground="#8D8D8D")

    assert hex_luma("#FF5D5D") > PIVOT_GROUND_MAX_LUMA
    with pytest.raises(ValidationError):
        EmphasisPalette(accent="#FFC300", pivot_ground="#FF5D5D")


def test_accent_is_not_subject_to_the_pivot_ground_ceiling():
    """Accent type sits on a plate K4 measures, or on a slab.

    A light accent is `apply_emphasis_treatments`' problem, not this
    validator's — capping it here would be a second contrast system
    fighting K4's, which is precisely what K5 must not become. So a
    white accent, and the accent that is brighter than the pivot limit
    (`#FFC300`, luma 190.7), both construct.
    """
    assert hex_luma("#FFC300") > PIVOT_GROUND_MAX_LUMA
    assert EmphasisPalette(accent="#FFC300", pivot_ground="#FF2E2E").accent == "#FFC300"
    assert EmphasisPalette(accent="#FFFFFF", pivot_ground="#FF2E2E").accent == "#FFFFFF"
    assert EmphasisPalette(accent="#FAFAFA", pivot_ground="#5A00A8").accent == "#FAFAFA"


def test_the_ceiling_guards_both_metadata_fields_and_the_load_path():
    """Planner-authored, human override, and a stored document.

    The validator is on the schema rather than in the resolver so that
    an illegible pair cannot be CONSTRUCTED by any of these paths.

    What is NOT covered, and is not covered for the hex check either:
    `EmphasisPalette.model_construct` skips validation by design, and
    pydantic does not re-validate an already-built model instance
    assigned to `TimelineMetadata`. That is an explicit bypass, used
    only in `tmp/k5_pivot_luma/verify_pivot_luma.py` to render the
    rejected side of the boundary. Nothing in `app/` constructs a
    palette that way.
    """
    with pytest.raises(ValidationError):
        TimelineMetadata(
            render_style="retention_fast",
            emphasis_palette={"accent": "#FFC300", "pivot_ground": "#FAFAFA"},
        )
    with pytest.raises(ValidationError):
        TimelineMetadata.model_validate(
            {
                "render_style": "retention_fast",
                "emphasis_palette": {"accent": "#FFC300", "pivot_ground": "#FAFAFA"},
            }
        )
    with pytest.raises(ValidationError):
        TimelineMetadata.model_validate(
            {
                "render_style": "retention_fast",
                "emphasis_palette_override": {
                    "accent": "#FFC300",
                    "pivot_ground": "#FFFFFF",
                },
            }
        )

