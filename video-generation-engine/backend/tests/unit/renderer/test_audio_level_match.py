"""OQ-1c: per-scene narration mean-LUFS gain match before concat.

Uses real ffmpeg ebur128. Never touches Postgres.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.renderer.audio import (
    gain_match_narration_scenes,
    measure_integrated_lufs,
    mux_narration,
)
from app.renderer.slideshow import RenderSettings

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")

pytestmark = pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None, reason="ffmpeg/ffprobe required"
)


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


async def _make_sine_mp3(
    path: Path, duration_s: float, *, volume_linear: float = 1.0
) -> None:
    assert _FFMPEG is not None
    await _run(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_s},volume={volume_linear}",
            "-ar",
            "44100",
            "-b:a",
            "128k",
            "-c:a",
            "libmp3lame",
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
            str(path),
        ]
    )


async def test_gain_match_flattens_per_scene_lufs_spread(tmp_path: Path):
    """Two sines at deliberately different levels; after mean-match, spread
    of pre-concat adjusted files is under ~1.5 LU."""
    loud = tmp_path / "loud.mp3"
    quiet = tmp_path / "quiet.mp3"
    await _make_sine_mp3(loud, 2.0, volume_linear=1.0)
    await _make_sine_mp3(quiet, 2.0, volume_linear=0.5)  # −6 dB

    before = []
    for p in (loud, quiet):
        lufs = await measure_integrated_lufs(p, _FFMPEG)  # type: ignore[arg-type]
        assert lufs is not None
        before.append(lufs)
    before_spread = max(before) - min(before)
    assert before_spread > 2.0, f"fixture levels too close: {before}"

    matched = await gain_match_narration_scenes(
        [loud, quiet],
        work_dir=tmp_path,
        ffmpeg_binary=_FFMPEG,  # type: ignore[arg-type]
    )
    after = []
    for p in matched:
        lufs = await measure_integrated_lufs(p, _FFMPEG)  # type: ignore[arg-type]
        assert lufs is not None
        after.append(lufs)
    after_spread = max(after) - min(after)
    assert after_spread < 1.5, f"after={after} spread={after_spread} before={before}"


async def test_mux_narration_level_match_preserves_concat_duration(tmp_path: Path):
    """Full mux path: matched concat duration equals sum of inputs (±20 ms)."""
    settings = _render_settings()
    scene_a = tmp_path / "a.mp3"
    scene_b = tmp_path / "b.mp3"
    await _make_sine_mp3(scene_a, 1.013, volume_linear=1.0)
    await _make_sine_mp3(scene_b, 0.877, volume_linear=0.5)

    true_total = sum(_stream_duration(p, "audio") for p in (scene_a, scene_b))
    video = tmp_path / "silent.mp4"
    await _make_silent_video(video, true_total + 3.0)
    out = tmp_path / "muxed.mp4"
    await mux_narration(video, [scene_a, scene_b], out, settings, level_match=True)

    assembled = _stream_duration(out, "audio")
    assert abs(assembled - true_total) < 0.02, (
        f"assembled={assembled}s true_total={true_total}s"
    )


async def test_mux_narration_level_match_off_skips_adjustment(tmp_path: Path):
    settings = _render_settings()
    scene_a = tmp_path / "a.mp3"
    scene_b = tmp_path / "b.mp3"
    await _make_sine_mp3(scene_a, 1.0, volume_linear=1.0)
    await _make_sine_mp3(scene_b, 1.0, volume_linear=0.5)

    video = tmp_path / "silent.mp4"
    await _make_silent_video(video, 5.0)
    out = tmp_path / "muxed.mp4"
    await mux_narration(video, [scene_a, scene_b], out, settings, level_match=False)

    # No adjusted wav sidecars when matching is off.
    assert not list(tmp_path.glob(".narr_lvl_*.wav"))
    assert out.is_file()


async def test_unmeasurable_scene_does_not_raise(tmp_path: Path):
    """A garbage 'audio' file is left unadjusted; measurable peer still matches."""
    good = tmp_path / "good.mp3"
    await _make_sine_mp3(good, 1.0, volume_linear=1.0)
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not-an-mp3-at-all")

    matched = await gain_match_narration_scenes(
        [good, bad],
        work_dir=tmp_path,
        ffmpeg_binary=_FFMPEG,  # type: ignore[arg-type]
    )
    assert matched[1] == bad
    # Only one measurable scene → mean is that scene; gain ≈ 0 → original path.
    assert matched[0] == good
