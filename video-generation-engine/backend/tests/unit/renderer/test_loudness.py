"""OQ-1a loudness target: parser unit tests + real-ffmpeg duration/LUFS proof.

Duration-preserving proof models tests/integration/test_narration_audio_concat.py
(ffprobe stream duration before/after). Real-ffmpeg tests skip if ffmpeg
is missing.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.renderer.loudness import (
    apply_loudness_target,
    parse_loudnorm_measurement,
    parse_loudnorm_normalization_type,
)
from app.renderer.metrics import parse_ebur128_summary
from app.renderer.slideshow import RenderSettings

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")

_LOUDNORM_STDERR_FIXTURE = """
[Parsed_loudnorm_0 @ 0x123] 
{
	"input_i" : "-27.61",
	"input_tp" : "-9.05",
	"input_lra" : "8.40",
	"input_thresh" : "-38.10",
	"output_i" : "-16.00",
	"output_tp" : "-1.50",
	"output_lra" : "11.00",
	"output_thresh" : "-27.12",
	"normalization_type" : "dynamic",
	"target_offset" : "0.49"
}
"""


def test_parse_loudnorm_measurement_from_fixture_stderr():
    parsed = parse_loudnorm_measurement(_LOUDNORM_STDERR_FIXTURE)
    assert parsed is not None
    assert parsed["measured_I"] == pytest.approx(-27.61)
    assert parsed["measured_TP"] == pytest.approx(-9.05)
    assert parsed["measured_LRA"] == pytest.approx(8.40)
    assert parsed["measured_thresh"] == pytest.approx(-38.10)
    assert parsed["offset"] == pytest.approx(0.49)


def test_parse_loudnorm_measurement_returns_none_when_missing():
    assert parse_loudnorm_measurement("no json here\nError: boom") is None


def test_parse_loudnorm_normalization_type_linear_and_dynamic():
    linear = _LOUDNORM_STDERR_FIXTURE.replace('"dynamic"', '"linear"')
    assert parse_loudnorm_normalization_type(linear) == "linear"
    assert parse_loudnorm_normalization_type(_LOUDNORM_STDERR_FIXTURE) == "dynamic"


def _render_settings() -> RenderSettings:
    assert _FFMPEG is not None and _FFPROBE is not None
    return RenderSettings(
        width=320,
        height=240,
        fps=30,
        pixel_format="yuv420p",
        ffmpeg_binary=_FFMPEG,
        ffprobe_binary=_FFPROBE,
    )


def _ffprobe(path: Path, *entries: str) -> dict:
    assert _FFPROBE is not None
    args = [
        _FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        ":".join(entries),
        str(path),
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return json.loads(result.stdout)


def _stream_duration(path: Path, codec_type: str) -> float:
    probe = _ffprobe(path, "stream=codec_type,duration")
    for stream in probe["streams"]:
        if stream["codec_type"] == codec_type:
            return float(stream["duration"])
    raise AssertionError(f"no {codec_type} stream in {path}")


async def _run(args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace")[-2000:])


def _measure_lufs(path: Path) -> float:
    assert _FFMPEG is not None
    args = [
        _FFMPEG,
        "-hide_banner",
        "-i",
        str(path),
        "-filter:a",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    parsed = parse_ebur128_summary(result.stderr or "")
    assert parsed is not None, result.stderr[-500:]
    return parsed["integrated_lufs"]


async def _make_loud_sine_video(path: Path, duration_s: float, *, frequency: float = 440.0) -> None:
    """Loud sine + color video (volume-boosted; deliberately off −16 LUFS)."""
    assert _FFMPEG is not None
    await _run(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=320x240:r=30:d={duration_s}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={duration_s}:sample_rate=48000",
            "-filter:a",
            "volume=8dB",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(path),
        ]
    )


async def _make_silent_video(path: Path, duration_s: float) -> None:
    assert _FFMPEG is not None
    await _run(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=320x240:r=30:d={duration_s}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(path),
        ]
    )


async def _concat_two_videos(a: Path, b: Path, out: Path) -> None:
    """Decode-concat two clips (filter concat) into one mux — multi-scene stand-in."""
    assert _FFMPEG is not None
    await _run(
        [
            _FFMPEG,
            "-y",
            "-i",
            str(a),
            "-i",
            str(b),
            "-filter_complex",
            "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ]
    )


@pytest.mark.skipif(_FFMPEG is None or _FFPROBE is None, reason="ffmpeg/ffprobe not on PATH")
def test_no_audio_copies_through_unchanged(tmp_path: Path):
    settings = _render_settings()
    silent = tmp_path / "silent.mp4"
    out = tmp_path / "out.mp4"
    asyncio.run(_make_silent_video(silent, 1.0))
    before = silent.read_bytes()
    result = asyncio.run(
        apply_loudness_target(
            silent,
            out,
            settings,
            target_lufs=-16.0,
            true_peak_db=-1.0,
        )
    )
    assert result == out
    assert out.read_bytes() == before


@pytest.mark.skipif(_FFMPEG is None or _FFPROBE is None, reason="ffmpeg/ffprobe not on PATH")
def test_loudnorm_hits_target_and_preserves_duration(tmp_path: Path):
    settings = _render_settings()
    src = tmp_path / "loud.mp4"
    out = tmp_path / "norm.mp4"
    duration_s = 4.0
    asyncio.run(_make_loud_sine_video(src, duration_s))

    before_audio = _stream_duration(src, "audio")
    before_lufs = _measure_lufs(src)
    assert before_lufs < -16.0 - 1.5 or before_lufs > -16.0 + 1.5

    asyncio.run(
        apply_loudness_target(
            src,
            out,
            settings,
            target_lufs=-16.0,
            true_peak_db=-1.0,
        )
    )

    after_audio = _stream_duration(out, "audio")
    after_lufs = _measure_lufs(out)
    assert abs(after_audio - before_audio) <= 0.020
    assert abs(after_lufs - (-16.0)) <= 1.5


@pytest.mark.skipif(_FFMPEG is None or _FFPROBE is None, reason="ffmpeg/ffprobe not on PATH")
def test_two_scene_concat_loudnorm_preserves_duration(tmp_path: Path):
    """§2.3: prove duration preservation on a real multi-scene (two-sine) mux."""
    settings = _render_settings()
    a = tmp_path / "scene_a.mp4"
    b = tmp_path / "scene_b.mp4"
    joined = tmp_path / "joined.mp4"
    out = tmp_path / "norm.mp4"
    asyncio.run(_make_loud_sine_video(a, 2.0, frequency=440.0))
    asyncio.run(_make_loud_sine_video(b, 2.0, frequency=660.0))
    asyncio.run(_concat_two_videos(a, b, joined))

    before_audio = _stream_duration(joined, "audio")
    before_video = _stream_duration(joined, "video")

    asyncio.run(
        apply_loudness_target(
            joined,
            out,
            settings,
            target_lufs=-16.0,
            true_peak_db=-1.0,
        )
    )

    after_audio = _stream_duration(out, "audio")
    after_video = _stream_duration(out, "video")
    after_lufs = _measure_lufs(out)
    assert abs(after_audio - before_audio) <= 0.020
    assert abs(after_video - before_video) <= 0.020
    assert abs(after_lufs - (-16.0)) <= 1.5
