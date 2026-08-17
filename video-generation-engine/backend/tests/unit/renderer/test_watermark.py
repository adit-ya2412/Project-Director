"""`app/renderer/watermark.py` - pure filter-string construction and
hashing, no ffmpeg needed. Real overlay rendering is proven against a
real ffmpeg invocation in
tests/integration/test_render_watermark_determinism.py.
"""

import pytest

from app.renderer.watermark import (
    LOGO_PATH,
    watermark_content_hash,
    watermark_filter_fragment,
    watermark_params_hash,
)

_KWARGS = dict(
    frame_width=1080, position="top_right", width_fraction=0.10, margin_fraction=0.03, opacity=0.65
)


def test_logo_is_vendored_on_disk():
    """A missing vendored asset should fail loudly at hash time, not
    produce a silently-empty watermark."""
    assert LOGO_PATH.exists()


def test_watermark_content_hash_matches_the_vendored_files_actual_bytes():
    import hashlib

    assert watermark_content_hash() == hashlib.sha256(LOGO_PATH.read_bytes()).hexdigest()


def test_top_right_places_the_overlay_away_from_both_edges_using_overlay_dimensions():
    fragment = watermark_filter_fragment("0:v", "out", 1, **_KWARGS)
    assert "x=main_w-overlay_w-32" in fragment
    assert "y=32" in fragment
    assert "y=main_h" not in fragment


def test_bottom_left_places_the_overlay_at_the_opposite_corner():
    kwargs = {**_KWARGS, "position": "bottom_left"}
    fragment = watermark_filter_fragment("0:v", "out", 1, **kwargs)
    assert "x=32" in fragment
    assert "x=main_w" not in fragment
    assert "y=main_h-overlay_h-32" in fragment


def test_all_four_corners_produce_distinct_fragments():
    fragments = {
        position: watermark_filter_fragment("0:v", "out", 1, **{**_KWARGS, "position": position})
        for position in ("top_left", "top_right", "bottom_left", "bottom_right")
    }
    assert len(set(fragments.values())) == 4


def test_unknown_position_raises_rather_than_silently_defaulting():
    with pytest.raises(ValueError):
        watermark_filter_fragment("0:v", "out", 1, **{**_KWARGS, "position": "center"})


def test_width_fraction_is_resolved_against_the_actual_frame_width():
    narrow = watermark_filter_fragment("0:v", "out", 1, **{**_KWARGS, "frame_width": 500})
    wide = watermark_filter_fragment("0:v", "out", 1, **{**_KWARGS, "frame_width": 2000})
    assert "scale=50:-1" in narrow  # 500 * 0.10
    assert "scale=200:-1" in wide  # 2000 * 0.10


def test_opacity_is_applied_via_alpha_multiply_not_replacing_the_pngs_own_alpha():
    fragment = watermark_filter_fragment("0:v", "out", 1, **_KWARGS)
    assert "colorchannelmixer=aa=0.65" in fragment


def test_logo_input_index_is_referenced_correctly_when_not_the_first_extra_input():
    fragment = watermark_filter_fragment("captioned", "out", 2, **_KWARGS)
    assert fragment.startswith("[2:v]")
    assert "[captioned][wm_out]overlay" in fragment


def test_params_hash_changes_when_any_single_parameter_changes():
    base = watermark_params_hash(position="top_right", width_fraction=0.1, margin_fraction=0.03, opacity=0.65)
    assert base != watermark_params_hash(
        position="bottom_left", width_fraction=0.1, margin_fraction=0.03, opacity=0.65
    )
    assert base != watermark_params_hash(
        position="top_right", width_fraction=0.2, margin_fraction=0.03, opacity=0.65
    )
    assert base != watermark_params_hash(
        position="top_right", width_fraction=0.1, margin_fraction=0.05, opacity=0.65
    )
    assert base != watermark_params_hash(
        position="top_right", width_fraction=0.1, margin_fraction=0.03, opacity=0.9
    )


def test_params_hash_is_deterministic():
    kwargs = dict(position="top_right", width_fraction=0.1, margin_fraction=0.03, opacity=0.65)
    assert watermark_params_hash(**kwargs) == watermark_params_hash(**kwargs)
