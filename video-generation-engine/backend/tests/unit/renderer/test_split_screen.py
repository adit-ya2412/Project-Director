"""Split-screen filter arithmetic, no ffmpeg."""

from pathlib import Path

from app.renderer.motion import MediaKind
from app.renderer.split_screen import (
    build_split_filter,
    panel_heights,
    should_composite_split,
)
from app.schemas.timeline import CameraMovement


def test_panel_heights_sum_to_the_frame():
    assert panel_heights(1920) == (960, 960)
    assert sum(panel_heights(241)) == 241


def test_split_filter_vstacks_two_crop_filled_panels():
    fragment = build_split_filter(
        0,
        1,
        width=240,
        height=320,
        fps=24,
        pixel_format="yuv420p",
        label="vout",
        hold_s=1.458333,
    )
    assert "vstack=inputs=2" in fragment
    assert "hstack=" not in fragment
    assert "scale=240:160:force_original_aspect_ratio=increase" in fragment
    assert "crop=240:160" in fragment
    assert fragment.endswith("[vout]")


def test_split_filter_hstacks_on_a_landscape_canvas():
    fragment = build_split_filter(
        0,
        1,
        width=320,
        height=240,
        fps=24,
        pixel_format="yuv420p",
        label="vout",
        hold_s=1.0,
    )
    assert "hstack=inputs=2" in fragment
    assert "vstack=" not in fragment
    assert "scale=160:240:force_original_aspect_ratio=increase" in fragment
    assert "crop=160:240" in fragment


def test_should_composite_requires_two_stills_and_split_movement():
    path = Path("bot.png")
    assert should_composite_split(
        CameraMovement.SPLIT_FRAME,
        secondary_path=path,
        top_kind=MediaKind.STILL,
        bot_kind=MediaKind.STILL,
    )
    assert not should_composite_split(
        CameraMovement.STATIC,
        secondary_path=path,
        top_kind=MediaKind.STILL,
        bot_kind=MediaKind.STILL,
    )
    assert not should_composite_split(
        CameraMovement.SPLIT_FRAME,
        secondary_path=None,
        top_kind=MediaKind.STILL,
        bot_kind=MediaKind.STILL,
    )
    assert not should_composite_split(
        CameraMovement.SPLIT_FRAME,
        secondary_path=path,
        top_kind=MediaKind.STILL,
        bot_kind=MediaKind.MOTION,
    )
