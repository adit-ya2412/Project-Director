"""`apply_narration_tempo` (2026-08-24): proves the ffmpeg `atempo` pass
actually changes a real, decodable MP3's real duration by the requested
factor, and that the rescaled alignment timestamps describe THAT new
duration - not the original's. A real, ffmpeg-synthesised sine-wave MP3
is used throughout, same reasoning as `test_narration_audio_concat.py`'s
own docstring: `FakeNarrationProvider` bytes are not decodable audio at
all, so they cannot stand in for what this function actually processes.
"""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.renderer.narration_tempo import apply_narration_tempo

_ORIGINAL_DURATION_S = 3.017  # deliberately not a round number


def _ffprobe_duration(path: Path) -> float:
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "stream=codec_type,duration",
        str(path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout)["streams"]
    for stream in streams:
        if stream["codec_type"] == "audio":
            return float(stream["duration"])
    raise AssertionError(f"no audio stream in {path}")


async def _make_sine_mp3(path: Path, duration_s: float) -> None:
    process = await asyncio.create_subprocess_exec(
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration_s}",
        "-ar",
        "44100",
        "-b:a",
        "128k",
        "-c:a",
        "libmp3lame",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace"))


def _fake_alignment(n_chars: int, duration_s: float) -> dict:
    rate = n_chars / duration_s
    return {
        "characters": ["x"] * n_chars,
        "character_start_times_seconds": [i / rate for i in range(n_chars)],
        "character_end_times_seconds": [(i + 1) / rate for i in range(n_chars)],
    }


async def test_factor_1_0_is_a_pure_passthrough(tmp_path: Path):
    src = tmp_path / "src.mp3"
    await _make_sine_mp3(src, _ORIGINAL_DURATION_S)
    content = src.read_bytes()
    alignment = _fake_alignment(50, _ORIGINAL_DURATION_S)

    new_content, new_alignment = await apply_narration_tempo(
        content, alignment, 1.0, ffmpeg_binary=settings.ffmpeg_binary
    )

    assert new_content is content
    assert new_alignment is alignment


@pytest.mark.parametrize("factor", [1.2, 0.7])
async def test_real_audio_duration_scales_by_factor(tmp_path: Path, factor: float):
    src = tmp_path / "src.mp3"
    await _make_sine_mp3(src, _ORIGINAL_DURATION_S)
    content = src.read_bytes()
    n_chars = 60
    alignment = _fake_alignment(n_chars, _ORIGINAL_DURATION_S)

    new_content, new_alignment = await apply_narration_tempo(
        content, alignment, factor, ffmpeg_binary=settings.ffmpeg_binary
    )

    out_path = tmp_path / "out.mp3"
    out_path.write_bytes(new_content)
    real_new_duration = _ffprobe_duration(out_path)
    expected_new_duration = _ORIGINAL_DURATION_S / factor

    # ffmpeg's atempo + MP3 frame rounding, not exact arithmetic - 5%
    # tolerance is generous against both.
    assert real_new_duration == pytest.approx(expected_new_duration, rel=0.05)

    # The rescaled alignment must describe THIS real output, not a
    # theoretical one: every timestamp divided by the same factor, and
    # the final one lands within the same tolerance of the real,
    # ffprobed duration - not just the arithmetic expectation.
    old_ends = alignment["character_end_times_seconds"]
    new_ends = new_alignment["character_end_times_seconds"]
    for old_t, new_t in zip(old_ends, new_ends, strict=True):
        assert new_t == pytest.approx(old_t / factor, rel=1e-6)
    assert new_ends[-1] == pytest.approx(real_new_duration, rel=0.05)
