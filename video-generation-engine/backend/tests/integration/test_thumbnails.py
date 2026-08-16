"""`app/assets/thumbnails.py` against real ffmpeg and real Pillow - both
the actual image bytes produced (a real, decodable JPEG at the expected
size) and the mtime-keyed cache itself: regenerated when the source is
newer than the cache, served untouched otherwise. `run_ffmpeg` calls are
counted (same technique as `tests/integration/test_render_fingerprint_cache
.py`) so "the cache was served" is proven by the ENCODER never running a
second time, not merely by the output bytes happening to match.
"""

import time
from pathlib import Path

from PIL import Image

from app.assets import thumbnails as thumbnails_module
from app.assets.thumbnails import cached_resized_image, cached_video_frame
from app.core.config import settings

from .test_narration_audio_concat import _make_silent_video


def _png_bytes(path: Path, size: tuple[int, int] = (800, 600)) -> None:
    Image.new("RGB", size, color=(20, 40, 60)).save(path, format="PNG")


async def test_cached_video_frame_produces_a_real_decodable_jpeg(tmp_path):
    video_path = tmp_path / "final.mp4"
    await _make_silent_video(video_path, 10.0)

    cache_path = tmp_path / "thumb.jpg"
    result = await cached_video_frame(
        video_path,
        cache_path,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )

    assert result == cache_path
    assert cache_path.exists()
    with Image.open(cache_path) as image:
        assert image.format == "JPEG"
        assert image.size == (320, 240)  # the source video's own dimensions


async def test_cached_video_frame_is_not_frame_zero(tmp_path, monkeypatch):
    """F1: never frame 0 - proven here by checking the extracted frame's
    OWN timestamp lands near the expected ~10% mark, not at t=0. A solid-
    colour test video can't show a visual difference, so this asserts the
    ACTUAL ffmpeg invocation's `-ss` argument instead - the real mechanism
    F1 depends on, not an incidental pixel comparison."""
    video_path = tmp_path / "final.mp4"
    await _make_silent_video(video_path, 20.0)  # 10% => 2.0s, inside [0.5, 3]

    seen_args: list[list[str]] = []
    real_run_ffmpeg = thumbnails_module.run_ffmpeg

    async def _capturing_run_ffmpeg(args):
        seen_args.append(args)
        return await real_run_ffmpeg(args)

    monkeypatch.setattr(thumbnails_module, "run_ffmpeg", _capturing_run_ffmpeg)
    await cached_video_frame(
        video_path,
        tmp_path / "thumb.jpg",
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )

    assert len(seen_args) == 1
    ss_index = seen_args[0].index("-ss")
    assert float(seen_args[0][ss_index + 1]) == 2.0


async def test_cached_video_frame_skips_regeneration_when_the_source_is_unchanged(
    tmp_path, monkeypatch
):
    video_path = tmp_path / "final.mp4"
    await _make_silent_video(video_path, 5.0)
    cache_path = tmp_path / "thumb.jpg"

    call_count = 0
    real_run_ffmpeg = thumbnails_module.run_ffmpeg

    async def _counting_run_ffmpeg(args):
        nonlocal call_count
        call_count += 1
        return await real_run_ffmpeg(args)

    monkeypatch.setattr(thumbnails_module, "run_ffmpeg", _counting_run_ffmpeg)
    await cached_video_frame(
        video_path,
        cache_path,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )
    assert call_count == 1

    # Same source, unchanged mtime - a second call must NOT re-invoke
    # ffmpeg at all.
    await cached_video_frame(
        video_path,
        cache_path,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )
    assert call_count == 1


async def test_cached_video_frame_regenerates_once_the_source_is_newer(tmp_path, monkeypatch):
    """The load-bearing mtime check (F0b): a re-render replaces
    `final.mp4` in place - without this, the project-list thumbnail would
    keep showing the OLD video's frame forever, reproducing the exact
    stale-cache bug `RenderStep.is_satisfied` already had to fix once
    (see that module's own docstring)."""
    video_path = tmp_path / "final.mp4"
    await _make_silent_video(video_path, 5.0)
    cache_path = tmp_path / "thumb.jpg"

    call_count = 0
    real_run_ffmpeg = thumbnails_module.run_ffmpeg

    async def _counting_run_ffmpeg(args):
        nonlocal call_count
        call_count += 1
        return await real_run_ffmpeg(args)

    monkeypatch.setattr(thumbnails_module, "run_ffmpeg", _counting_run_ffmpeg)
    await cached_video_frame(
        video_path,
        cache_path,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )
    assert call_count == 1

    # Re-render: a new file lands at the same path, strictly newer than
    # the cache (a real filesystem mtime bump, not simulated).
    time.sleep(0.05)
    await _make_silent_video(video_path, 5.0)

    await cached_video_frame(
        video_path,
        cache_path,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )
    assert call_count == 2


def test_cached_resized_image_downscales_and_never_upscales(tmp_path):
    source_path = tmp_path / "source.png"
    _png_bytes(source_path, size=(800, 600))
    cache_path = tmp_path / "thumb.jpg"

    result = cached_resized_image(source_path, cache_path)

    assert result == cache_path
    with Image.open(cache_path) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 640
        # Aspect ratio preserved (4:3 source -> 4:3 output).
        assert image.size[0] / image.size[1] == 800 / 600

    small_source = tmp_path / "small.png"
    _png_bytes(small_source, size=(100, 80))
    small_cache = tmp_path / "small_thumb.jpg"
    cached_resized_image(small_source, small_cache)
    with Image.open(small_cache) as image:
        assert image.size == (100, 80)  # never upscaled


def test_cached_resized_image_regenerates_once_the_source_changes(tmp_path):
    source_path = tmp_path / "source.png"
    _png_bytes(source_path, size=(800, 600))
    cache_path = tmp_path / "thumb.jpg"

    cached_resized_image(source_path, cache_path)
    first_bytes = cache_path.read_bytes()

    time.sleep(0.05)
    _png_bytes(source_path, size=(400, 300))  # a genuinely different source image
    cached_resized_image(source_path, cache_path)
    second_bytes = cache_path.read_bytes()

    assert first_bytes != second_bytes
    with Image.open(cache_path) as image:
        assert image.size == (400, 300)
