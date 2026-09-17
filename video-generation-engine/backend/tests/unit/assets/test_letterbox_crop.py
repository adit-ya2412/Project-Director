"""`strip_baked_in_letterbox` (docs/plans/baked_in_letterbox.md §4/§7) -
one test per invariant, named for the invariant, following
`test_substrate_crop.py`'s conventions for its video sibling.

Real ffmpeg/ffprobe subprocesses throughout (no mocking of the detection
mechanism itself) - `tests/media_fixtures.py::make_real_clip` builds
genuine, small, fast-to-encode h264 clips with a known content box, the
same idiom `tests/integration/test_motion_classification.py` already uses
for real still/clip probing.
"""

from __future__ import annotations

import subprocess

from app.assets.letterbox_crop import _probe_dimensions, strip_baked_in_letterbox
from app.core.config import settings
from tests.media_fixtures import make_real_clip


async def _dimensions(video_bytes: bytes, tmp_path) -> tuple[int, int]:
    path = tmp_path / "probe.mp4"
    path.write_bytes(video_bytes)
    probe = await _probe_dimensions(path, settings.ffprobe_binary)
    assert probe is not None, "expected a decodable clip"
    width, height, _duration_s = probe
    return width, height


async def test_detects_and_crops_a_real_pillarbox(tmp_path):
    """The canonical real case (plan §1): a 608x1080-shaped picture baked
    into the centre of a 1920x1080 frame. Scaled down 1/10th here so the
    encode stays fast, but the SHAPE - true content centred inside a much
    wider frame - is the real one. Output dimensions must be exactly the
    true content box, not merely "smaller"."""
    path = tmp_path / "pillarboxed.mp4"
    make_real_clip(path, duration_s=2.0, width=192, height=192, pad_to=(608, 192, 208, 0))
    cropped = await strip_baked_in_letterbox(
        path.read_bytes(),
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )
    assert cropped != path.read_bytes()
    width, height = await _dimensions(cropped, tmp_path)
    assert (width, height) == (192, 192)


async def test_no_op_on_a_clip_with_no_border(tmp_path):
    """17 of 21 real assets (plan §1/§9) are clean and must never pay a
    re-encode - asserts the SAME BYTES return, not merely the same
    dimensions."""
    path = tmp_path / "clean.mp4"
    make_real_clip(path, duration_s=2.0, width=192, height=192)
    source = path.read_bytes()
    result = await strip_baked_in_letterbox(
        source, ffmpeg_binary=settings.ffmpeg_binary, ffprobe_binary=settings.ffprobe_binary
    )
    assert result == source


async def test_skips_a_trivial_border(tmp_path):
    """A sub-floor border (well under the 2% `_MIN_REMOVED_FRACTION`) is
    encoder edge noise, not a bar worth a re-encode - no-op."""
    path = tmp_path / "trivial_border.mp4"
    # 2px black margin on left+right of a 640-wide frame: 1 - 636/640 =
    # 0.625% removed, nowhere near the 2% floor.
    make_real_clip(path, duration_s=2.0, width=636, height=480, pad_to=(640, 480, 2, 0))
    source = path.read_bytes()
    result = await strip_baked_in_letterbox(
        source, ffmpeg_binary=settings.ffmpeg_binary, ffprobe_binary=settings.ffprobe_binary
    )
    assert result == source


def _make_moving_shadow_clip(path, *, segment_duration_s: float = 2.0) -> None:
    """A clip with a GENUINE fixed bar (top 50px, every frame) plus a
    second dark region that MOVES: left half of the remaining frame for
    the first half of the clip, right half for the second half - the false
    positive `_MAX_UNION_GROWTH_FRACTION` exists to catch (plan §4: "the
    dark region MOVED between samples ... that is content, not a bar").

    Per-segment content box is `(300, 50, 640, 480)` then `(0, 50, 340,
    480)` - each 340x430 = 146200px. Their UNION is `(0, 50, 640, 480)` =
    640x430 = 275200px, ~88% larger than either sample alone - far past
    the 10% growth ceiling - while still describing a plausible-looking
    crop (10.4% removed, 1.49 aspect), so this exercises the stability
    guard specifically rather than the area floor/ceiling.
    """
    size = "640x480"
    common_bar = "drawbox=x=0:y=0:w=640:h=50:color=black:t=fill"
    left_shadow = f"{common_bar},drawbox=x=0:y=50:w=300:h=430:color=black:t=fill"
    right_shadow = f"{common_bar},drawbox=x=340:y=50:w=300:h=430:color=black:t=fill"
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=size={size}:color=gray:duration={segment_duration_s}:rate=24",
        "-f",
        "lavfi",
        "-i",
        f"color=size={size}:color=gray:duration={segment_duration_s}:rate=24",
        "-filter_complex",
        f"[0:v]{left_shadow}[a];[1:v]{right_shadow}[b];[a][b]concat=n=2:v=1:a=0[out]",
        "-map",
        "[out]",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(args, capture_output=True, check=True)


async def test_skips_when_the_dark_region_moves_between_samples(tmp_path):
    """The false-positive case that matters most (plan §7): a dark region
    that moves is content (a shadow, a scene change), not a bar. Must
    remain a no-op even though each individual sample looks like a
    plausible partial-bar crop on its own."""
    path = tmp_path / "moving_shadow.mp4"
    _make_moving_shadow_clip(path, segment_duration_s=2.0)
    source = path.read_bytes()
    result = await strip_baked_in_letterbox(
        source, ffmpeg_binary=settings.ffmpeg_binary, ffprobe_binary=settings.ffprobe_binary
    )
    assert result == source


async def test_degrades_to_input_bytes_on_ffmpeg_failure():
    """Corrupt/unreadable input must never raise - a human's upload must
    never fail because cropdetect had a bad day (module docstring)."""
    garbage = b"not a real video file" * 100
    result = await strip_baked_in_letterbox(
        garbage, ffmpeg_binary=settings.ffmpeg_binary, ffprobe_binary=settings.ffprobe_binary
    )
    assert result == garbage


async def test_empty_bytes_is_a_no_op():
    result = await strip_baked_in_letterbox(b"", ffmpeg_binary=settings.ffmpeg_binary)
    assert result == b""


async def test_deterministic_same_bytes_same_output(tmp_path):
    """I5: given identical input bytes, the function reaches the identical
    decision AND the identical encoded output every time - no RNG, no
    wall-clock dependency in either the detection or the crop pass."""
    path = tmp_path / "pillarboxed.mp4"
    make_real_clip(path, duration_s=2.0, width=192, height=192, pad_to=(608, 192, 208, 0))
    source = path.read_bytes()
    kwargs = dict(ffmpeg_binary=settings.ffmpeg_binary, ffprobe_binary=settings.ffprobe_binary)
    first = await strip_baked_in_letterbox(source, **kwargs)
    second = await strip_baked_in_letterbox(source, **kwargs)
    assert first == second
    assert first != source  # confirms this exercised the crop path, not a no-op


async def test_sample_window_scales_down_for_a_short_clip():
    """Task 3 (review finding): a short real-shot-length clip must not use
    an overlapping window. `_SAMPLE_FRACTIONS` are 20% of duration apart;
    the window must never exceed that gap, and never drop below the floor
    that still lets cropdetect converge."""
    from app.assets.letterbox_crop import (
        _MIN_SAMPLE_WINDOW_S,
        _SAMPLE_WINDOW_S,
        _sample_window_s_for,
    )

    for duration_s in (1.0, 1.5, 2.0, 3.0, 8.0, 30.0):
        window_s = _sample_window_s_for(duration_s)
        assert _MIN_SAMPLE_WINDOW_S <= window_s <= _SAMPLE_WINDOW_S
        assert window_s <= duration_s / 10.0 + 1e-9 or window_s == _MIN_SAMPLE_WINDOW_S


def test_snap_even_box_never_retains_a_bar_pixel():
    """Task 2 (review finding): on an odd union edge, the box must shrink
    INTO the content on every edge, never keep a bar pixel by rounding an
    edge the wrong direction. An earlier version rounded x1/y1 down
    (keeping a left/top bar pixel) while still sizing w/h from the
    pre-round edge (dropping a real content pixel on the far edge
    instead) - the opposite of what its own docstring claimed."""
    from app.assets.letterbox_crop import _snap_even_box

    w, h, x, y = _snap_even_box(1, 1, 101, 101)
    # The snapped box must be a SUBSET of the odd content box (1, 1, 101, 101)
    # on every edge - shrinking inward, never including x<1 or y<1, and
    # never extending past x=101 or y=101.
    assert x >= 1 and y >= 1
    assert x + w <= 101 and y + h <= 101
    assert w % 2 == 0 and h % 2 == 0 and x % 2 == 0 and y % 2 == 0
