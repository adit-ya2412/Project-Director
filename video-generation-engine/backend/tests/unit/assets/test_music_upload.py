"""C1 BGM upload (analysis.md, decisions 6a/6b/7): pure warning math +
real-ffmpeg validation of `validate_and_identify_audio`. No DB anywhere -
safe to run with `--noconftest` (see the RV3 conftest gate)."""

import shutil
from pathlib import Path

import pytest

from app.assets.music_upload import music_upload_warnings
from app.assets.validation import validate_and_identify_audio
from app.core.config import settings
from app.core.errors import PermanentError

_FFMPEG = shutil.which(settings.ffmpeg_binary) or shutil.which("ffmpeg")


def _make_audio(tmp_path: Path, fmt: str) -> bytes:
    """A half-second 440 Hz tone, encoded for real by this machine's
    ffmpeg - the same "isolated volume measurement" discipline the ducking
    proof uses. Skips the whole module's ffmpeg cases if none is found."""
    out = tmp_path / f"tone.{fmt}"
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=0.5",
        str(out),
    ]
    import subprocess

    subprocess.run(args, check=True, capture_output=True)
    return out.read_bytes()


# -- music_upload_warnings (pure, decision 6a/6b) ---------------------------


def test_no_warning_without_a_video_duration():
    assert music_upload_warnings(30.0, None) == []
    assert music_upload_warnings(30.0, 0.0) == []


def test_no_warning_when_track_matches_video():
    assert music_upload_warnings(90.4, 90.0) == []


def test_short_track_warns_about_looping():
    (warning,) = music_upload_warnings(20.0, 95.0)
    assert "loop" in warning
    assert "5 times" in warning  # ceil(95/20)


def test_long_track_warns_about_first_n_seconds():
    (warning,) = music_upload_warnings(228.0, 95.0)
    assert "first 1:35" in warning
    assert "3:48" in warning


def test_zero_or_negative_track_is_not_warned_about():
    assert music_upload_warnings(0.0, 90.0) == []


# -- validate_and_identify_audio (real ffprobe) -----------------------------


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
async def test_wav_upload_round_trips_with_duration_and_extension(tmp_path):
    content = _make_audio(tmp_path, "wav")
    ext, duration_s = await validate_and_identify_audio(content)
    assert ext == "wav"
    assert 0.4 < duration_s < 1.0


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
async def test_mp3_upload_round_trips_with_duration_and_extension(tmp_path):
    content = _make_audio(tmp_path, "mp3")
    ext, duration_s = await validate_and_identify_audio(content)
    assert ext == "mp3"
    assert 0.4 < duration_s < 1.5


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
async def test_garbage_bytes_are_rejected_at_the_endpoint_not_in_ffmpeg():
    """A27: an HTML error page saved as .mp3 must fail validation here."""
    with pytest.raises(PermanentError):
        await validate_and_identify_audio(b"<html>not audio</html>")


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
async def test_oversized_upload_rejected_before_any_probing(monkeypatch):
    monkeypatch.setattr(settings, "max_download_bytes", 8)
    with pytest.raises(PermanentError, match="byte cap"):
        await validate_and_identify_audio(b"123456789")


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
async def test_video_only_bytes_are_rejected(tmp_path):
    """No audio stream -> rejected, even though ffprobe itself succeeds."""
    out = tmp_path / "silent.mp4"
    import subprocess

    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=64x64:duration=0.2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(PermanentError, match="no audio stream"):
        await validate_and_identify_audio(out.read_bytes())
