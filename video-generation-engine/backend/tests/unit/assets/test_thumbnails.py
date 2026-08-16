"""`app/assets/thumbnails.py`'s pure logic - no ffmpeg, no Pillow, no disk.
The parts that actually shell out or touch files (`cached_video_frame`,
`cached_resized_image`, and the mtime-keyed cache itself) are proven
against real files in `tests/integration/test_thumbnails.py`.
"""

from pathlib import Path

from app.assets.thumbnails import _frame_timestamp, is_video_file


def test_is_video_file_recognises_the_suffixes_the_pipeline_actually_writes():
    """`.mp4` is what both `RenderStep`/the draft endpoint and a video-
    generation clip (rung 5) actually write - see
    `app/workflow/steps/resolve_assets.py`'s own `.mp4` path."""
    assert is_video_file(Path("final.mp4")) is True
    assert is_video_file(Path("draft.mp4")) is True
    assert is_video_file(Path("clip.MP4")) is True  # case-insensitive


def test_is_video_file_rejects_still_image_suffixes():
    assert is_video_file(Path("photo.jpg")) is False
    assert is_video_file(Path("photo.png")) is False
    assert is_video_file(Path("photo.gif")) is False  # animated GIF is still not "video" here


def test_frame_timestamp_is_roughly_ten_percent_in_for_an_ordinary_clip():
    assert _frame_timestamp(20.0) == 2.0


def test_frame_timestamp_floors_at_half_a_second_for_a_short_clip():
    """F1: 10% of a 3s clip is 0.3s - too close to a fade-in/dark frame,
    so the floor kicks in instead."""
    assert _frame_timestamp(3.0) == 0.5


def test_frame_timestamp_ceilings_at_three_seconds_for_a_long_clip():
    assert _frame_timestamp(90.0) == 3.0


def test_frame_timestamp_never_exceeds_a_clip_shorter_than_the_floor():
    """The [0.5s, 3s] clamp alone would seek PAST the end of a clip
    shorter than half a second (a real case: a single-shot generated
    clip, not just a full render) - the extra end-of-clip guard is what
    keeps this from ever asking ffmpeg to seek past EOF."""
    timestamp = _frame_timestamp(0.3)
    assert timestamp < 0.3
    assert timestamp == 0.25  # max(0.3 - 0.05, 0) - safely inside the clip
