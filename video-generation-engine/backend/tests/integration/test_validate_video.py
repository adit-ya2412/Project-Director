"""`app/assets/validation.py::validate_and_identify_video` (A7,
motion_new_styles_and_long_form_videos.md, 2026-08-18) against real
ffprobe and a real, genuine h264 clip - the video counterpart to
`test_validate_and_identify_image`'s real-Pillow proofs, needed because
Pillow cannot open a video container at all.
"""

import subprocess

import pytest

from app.assets.validation import validate_and_identify_video
from app.core.config import settings
from app.core.errors import PermanentError


def _real_clip_bytes(duration_s: float = 2.0, size: str = "640x360") -> bytes:
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration_s}:size={size}:rate=24",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "mp4",
        "-movflags",
        "frag_keyframe+empty_moov",
        "-",
    ]
    result = subprocess.run(args, capture_output=True, check=True)
    return result.stdout


async def test_a_real_clip_returns_mp4_extension_and_real_dimensions():
    content = _real_clip_bytes(duration_s=2.0, size="640x360")
    ext, width, height = await validate_and_identify_video(
        content, ffprobe_binary=settings.ffprobe_binary
    )
    assert ext == "mp4"
    assert (width, height) == (640, 360)


async def test_garbage_bytes_are_rejected():
    with pytest.raises(PermanentError, match="not a valid video"):
        await validate_and_identify_video(
            b"this is not a video, it is an HTML error page",
            ffprobe_binary=settings.ffprobe_binary,
        )


async def test_oversized_content_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "max_download_bytes", 10)
    content = _real_clip_bytes()
    with pytest.raises(PermanentError, match="byte cap"):
        await validate_and_identify_video(content, ffprobe_binary=settings.ffprobe_binary)


async def test_audio_only_content_is_rejected():
    """No video stream at all (e.g. a provider that somehow served audio)
    must be rejected, not silently accepted with garbage dimensions."""
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-f",
        "mp4",
        "-movflags",
        "frag_keyframe+empty_moov",
        "-",
    ]
    result = subprocess.run(args, capture_output=True, check=True)
    with pytest.raises(PermanentError, match="no video stream"):
        await validate_and_identify_video(result.stdout, ffprobe_binary=settings.ffprobe_binary)
