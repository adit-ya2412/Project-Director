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


def test_still_plus_still_is_byte_identical_to_the_shipped_filter():
    """The regression that matters most: adding MOTION support must not
    change a single character of the STILL+STILL output. The expected
    strings below are written out independently of `build_split_filter`
    (the original, pre-MOTION algorithm), not derived from it, so this
    test actually anchors the shape rather than restating the code."""
    vstack_expected = (
        "[0:v]scale=240:160:force_original_aspect_ratio=increase,crop=240:160,setsar=1[spt];"
        "[1:v]scale=240:160:force_original_aspect_ratio=increase,crop=240:160,setsar=1[spb];"
        "[spt][spb]vstack=inputs=2,"
        "fps=24,"
        "tpad=stop_mode=clone:stop_duration=1.458333,"
        "fps=24,"
        "format=yuv420p[vout]"
    )
    assert (
        build_split_filter(
            0,
            1,
            width=240,
            height=320,
            fps=24,
            pixel_format="yuv420p",
            label="vout",
            hold_s=1.458333,
        )
        == vstack_expected
    )
    # Explicit STILL/STILL kwargs (what the real call site now always
    # passes) must produce the exact same string as the all-defaults call
    # above and the exact same string as before MOTION support existed.
    assert (
        build_split_filter(
            0,
            1,
            width=240,
            height=320,
            fps=24,
            pixel_format="yuv420p",
            label="vout",
            hold_s=1.458333,
            top_kind=MediaKind.STILL,
            bot_kind=MediaKind.STILL,
            top_duration_s=None,
            bot_duration_s=None,
            target_duration_s=1.5,
        )
        == vstack_expected
    )

    hstack_expected = (
        "[0:v]scale=160:240:force_original_aspect_ratio=increase,crop=160:240,setsar=1[spl];"
        "[1:v]scale=160:240:force_original_aspect_ratio=increase,crop=160:240,setsar=1[spr];"
        "[spl][spr]hstack=inputs=2,"
        "fps=24,"
        "tpad=stop_mode=clone:stop_duration=1.000000,"
        "fps=24,"
        "format=yuv420p[vout]"
    )
    assert (
        build_split_filter(
            0,
            1,
            width=320,
            height=240,
            fps=24,
            pixel_format="yuv420p",
            label="vout",
            hold_s=1.0,
        )
        == hstack_expected
    )


def test_motion_plus_motion_fits_each_panel_independently_before_the_stack():
    fragment = build_split_filter(
        0,
        1,
        width=240,
        height=320,
        fps=24,
        pixel_format="yuv420p",
        label="vout",
        hold_s=1.458333,
        top_kind=MediaKind.MOTION,
        bot_kind=MediaKind.MOTION,
        top_duration_s=3.0,  # longer than target -> trim
        bot_duration_s=1.0,  # shorter than target -> hold
        target_duration_s=1.5,
    )
    assert "vstack=inputs=2" in fragment
    # Top (too long) is trimmed to the target duration.
    assert "trim=duration=1.500,setpts=PTS-STARTPTS" in fragment
    # Bottom (too short) holds its last frame for the gap.
    assert "tpad=stop_mode=clone:stop_duration=0.500" in fragment
    # Duration-fit happens per panel, BEFORE the stack - no second
    # duration-fit stage (tpad) is layered on after it.
    _, after_stack = fragment.split("vstack=inputs=2,", 1)
    assert "tpad" not in after_stack
    assert after_stack == "fps=24,format=yuv420p[vout]"
    # Each motion panel gets its own fps-normalise/fit/fps-normalise
    # envelope (mirrors `slideshow.py::_motion_filter`) - 2 `fps=` per
    # panel (4 total) plus 1 in the shared tail.
    assert fragment.count("fps=24") == 5


def test_still_plus_motion_extends_the_still_to_the_full_duration_itself():
    fragment = build_split_filter(
        0,
        1,
        width=240,
        height=320,
        fps=24,
        pixel_format="yuv420p",
        label="vout",
        hold_s=1.458333,
        top_kind=MediaKind.STILL,
        bot_kind=MediaKind.MOTION,
        top_duration_s=None,
        bot_duration_s=1.5,  # exactly the target -> no fit fragment needed
        target_duration_s=1.5,
    )
    assert "vstack=inputs=2" in fragment
    top_panel, rest = fragment.split(";", 1)
    # Top (STILL) reaches the full duration on its own, with the SAME
    # hold_s the STILL+STILL shared tail uses - not by relying on
    # vstack/hstack's own end-of-stream behaviour.
    assert top_panel == (
        "[0:v]scale=240:160:force_original_aspect_ratio=increase,crop=240:160,"
        "setsar=1,tpad=stop_mode=clone:stop_duration=1.458333[spt]"
    )
    # Bottom (MOTION) is already at the target duration - no fit fragment.
    assert "trim=" not in rest
    assert "tpad=stop_mode=clone" not in rest.split("vstack=inputs=2,", 1)[1]
    assert rest.endswith("fps=24,format=yuv420p[vout]")


def test_motion_plus_still_extends_the_still_to_the_full_duration_itself():
    fragment = build_split_filter(
        0,
        1,
        width=320,
        height=240,
        fps=24,
        pixel_format="yuv420p",
        label="vout",
        hold_s=1.0,
        top_kind=MediaKind.MOTION,
        bot_kind=MediaKind.STILL,
        top_duration_s=2.0,  # longer than target -> trim
        bot_duration_s=None,
        target_duration_s=1.0,
    )
    assert "hstack=inputs=2" in fragment
    assert "trim=duration=1.000,setpts=PTS-STARTPTS" in fragment
    # Bottom (STILL) panel carries its own hold, matching hold_s.
    assert "tpad=stop_mode=clone:stop_duration=1.000000[spr]" in fragment
    after_stack = fragment.split("hstack=inputs=2,", 1)[1]
    assert after_stack == "fps=24,format=yuv420p[vout]"


def test_should_composite_now_accepts_motion_on_either_or_both_panels():
    path = Path("bot.mp4")
    for top_kind, bot_kind in (
        (MediaKind.STILL, MediaKind.STILL),
        (MediaKind.STILL, MediaKind.MOTION),
        (MediaKind.MOTION, MediaKind.STILL),
        (MediaKind.MOTION, MediaKind.MOTION),
    ):
        assert should_composite_split(
            CameraMovement.SPLIT_FRAME,
            secondary_path=path,
            top_kind=top_kind,
            bot_kind=bot_kind,
        )
    # Still degrades: wrong movement, or a genuinely missing secondary.
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
        bot_kind=None,
    )
