"""`mux_sfx` overlays a delayed clip onto existing audio via run_ffmpeg."""

from pathlib import Path

import pytest

from app.core.config import settings
from app.renderer.audio import mux_narration
from app.renderer.sfx import mux_sfx
from app.renderer.slideshow import RenderSettings, probe_duration_seconds

from .test_narration_audio_concat import _make_silent_video, _make_sine_mp3, _stream_duration

_RENDER_SETTINGS = RenderSettings(
    width=320,
    height=240,
    fps=30,
    pixel_format="yuv420p",
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)


async def test_mux_sfx_keeps_video_duration_and_adds_audio_overlay(tmp_path: Path):
    video = tmp_path / "silent.mp4"
    await _make_silent_video(video, 4.0)
    narration = tmp_path / "narr.mp3"
    await _make_sine_mp3(narration, 4.0)
    with_narration = tmp_path / "narrated.mp4"
    await mux_narration(video, [narration], with_narration, _RENDER_SETTINGS)

    whoosh = tmp_path / "whoosh.mp3"
    await _make_sine_mp3(whoosh, 0.4)

    out = tmp_path / "with_sfx.mp4"
    await mux_sfx(
        with_narration,
        [(whoosh, 1.0)],
        out,
        _RENDER_SETTINGS,
        gain_db=-6.0,
        max_clip_s=1.5,
    )
    duration = await probe_duration_seconds(out, settings.ffprobe_binary)
    assert duration == pytest.approx(4.0, abs=0.15)
    assert _stream_duration(out, "audio") > 0


async def test_mux_sfx_on_a_silent_video_becomes_the_audio(tmp_path: Path):
    """R13: no [0:a] on a silent mp4 must not crash."""
    video = tmp_path / "silent.mp4"
    await _make_silent_video(video, 4.0)
    whoosh = tmp_path / "whoosh.mp3"
    await _make_sine_mp3(whoosh, 0.4)
    out = tmp_path / "sfx_only.mp4"
    await mux_sfx(
        video,
        [(whoosh, 0.5)],
        out,
        _RENDER_SETTINGS,
        gain_db=-6.0,
        max_clip_s=1.5,
    )
    assert await probe_duration_seconds(out, settings.ffprobe_binary) == pytest.approx(
        4.0, abs=0.15
    )
    assert _stream_duration(out, "audio") > 0
