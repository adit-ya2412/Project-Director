"""`mux_sfx` overlays a delayed clip onto existing audio via run_ffmpeg."""

from pathlib import Path

import pytest

from app.core.config import settings
from app.renderer.audio import mux_narration
from app.renderer.sfx import SfxOverlay, mux_sfx
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
        [SfxOverlay(path=whoosh, offset_s=1.0, volume_factor=10 ** (-6.0 / 20))],
        out,
        _RENDER_SETTINGS,
        max_clip_s=1.5,
    )
    duration = await probe_duration_seconds(out, settings.ffprobe_binary)
    assert duration == pytest.approx(4.0, abs=0.15)
    assert _stream_duration(out, "audio") > 0


async def test_mux_sfx_overlay_own_ceiling_overrides_the_call_level_default(tmp_path, monkeypatch):
    """long_form_direction.md A8: a DIEGETIC overlay carries its own,
    longer `max_clip_s` so a single `mux_sfx` call can mix a 1.5s
    structural stinger and an 8s diegetic ambience bed without either
    ceiling leaking onto the other. Asserted directly against the
    generated filter string (captured via a `run_ffmpeg` monkeypatch,
    same technique other renderer unit tests use to check filter
    construction without a real encode) rather than inferred from
    output duration, which `amix duration=first` would make identical
    either way."""
    import app.renderer.sfx as sfx_module

    captured_args: list[list[str]] = []

    async def _fake_run_ffmpeg(args: list[str]) -> None:
        captured_args.append(args)

    monkeypatch.setattr(sfx_module, "run_ffmpeg", _fake_run_ffmpeg)

    async def _fake_has_audio_stream(path, ffprobe_binary) -> bool:
        return True

    monkeypatch.setattr(sfx_module, "_has_audio_stream", _fake_has_audio_stream)

    video = tmp_path / "narrated.mp4"
    video.write_bytes(b"not-really-a-video")  # never read - both probes above are faked
    stinger = tmp_path / "stinger.mp3"
    stinger.write_bytes(b"not-really-audio")
    ambience = tmp_path / "ambience.mp3"
    ambience.write_bytes(b"not-really-audio")

    out = tmp_path / "with_sfx.mp4"
    await mux_sfx(
        video,
        [
            SfxOverlay(path=stinger, offset_s=0.0, volume_factor=1.0),  # default ceiling (1.5s)
            SfxOverlay(
                path=ambience, offset_s=0.0, volume_factor=1.0, max_clip_s=8.0
            ),  # own, longer ceiling
        ],
        out,
        _RENDER_SETTINGS,
        max_clip_s=1.5,
    )

    assert len(captured_args) == 1
    filter_complex = captured_args[0][captured_args[0].index("-filter_complex") + 1]
    assert "atrim=0:1.500" in filter_complex
    assert "atrim=0:8.000" in filter_complex


async def test_mux_sfx_on_a_silent_video_becomes_the_audio(tmp_path: Path):
    """R13: no [0:a] on a silent mp4 must not crash."""
    video = tmp_path / "silent.mp4"
    await _make_silent_video(video, 4.0)
    whoosh = tmp_path / "whoosh.mp3"
    await _make_sine_mp3(whoosh, 0.4)
    out = tmp_path / "sfx_only.mp4"
    await mux_sfx(
        video,
        [SfxOverlay(path=whoosh, offset_s=0.5, volume_factor=10 ** (-6.0 / 20))],
        out,
        _RENDER_SETTINGS,
        max_clip_s=1.5,
    )
    assert await probe_duration_seconds(out, settings.ffprobe_binary) == pytest.approx(
        4.0, abs=0.15
    )
    assert _stream_duration(out, "audio") > 0
