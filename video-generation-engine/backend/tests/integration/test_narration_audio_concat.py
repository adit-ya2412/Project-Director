"""Proves the drift-avoidance claim in `app/renderer/audio.py`'s module
docstring with real numbers, not a comment: naively concatenating encoded
MP3 files (the concat DEMUXER) inserts a small gap at every boundary
because MP3 is a framed codec with encoder delay/padding, and that gap
compounds across scenes. `mux_narration`'s use of the concat FILTER
(decode every input to PCM, then join on the sample timeline) must not
show that drift, at all, no matter how many scenes are joined.

Five real MP3 files (not `FakeNarrationProvider` bytes - those aren't
decodable audio at all) are synthesised locally via ffmpeg's `sine`
source at deliberately non-round durations, specifically so a naive
concat's boundary error - a fraction of an MP3 frame each time - cannot
hide behind numbers that happen to land on a frame boundary. Five files
means four boundaries: enough to show the error accumulating rather than
being a one-off rounding artefact from a single join (the brief's own
warning: "a one-boundary test cannot show accumulation").
"""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.renderer.audio import mux_narration
from app.renderer.slideshow import RenderSettings

# Deliberately not round numbers, and not multiples of the MP3 frame
# duration (1152 samples / 44100 Hz = 26.122ms) - if the concat filter's
# result matched the true sum despite that, no boundary-alignment fluke
# could be hiding the difference.
_SCENE_DURATIONS_S = [1.013, 0.877, 1.241, 0.956, 1.334]


def _ffprobe(path: Path, *entries: str) -> dict:
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        ":".join(entries),
        str(path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
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
        raise RuntimeError(stderr.decode(errors="replace"))


async def _make_sine_mp3(path: Path, duration_s: float) -> None:
    """A real, decodable MP3 of a known duration - stands in for one
    scene's ElevenLabs narration file without calling ElevenLabs."""
    await _run(
        [
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
        ]
    )


async def _make_silent_video(path: Path, duration_s: float) -> None:
    """A video comfortably longer than the joined narration, purely so
    `mux_narration`'s `-shortest` never trims the AUDIO stream being
    measured - only the video's length is padded, never trusted here."""
    await _run(
        [
            settings.ffmpeg_binary,
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


async def test_concat_filter_reproduces_true_summed_duration_across_five_boundaries(tmp_path):
    render_settings = RenderSettings(
        width=320,
        height=240,
        fps=30,
        pixel_format="yuv420p",
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )

    scene_paths = []
    for i, duration in enumerate(_SCENE_DURATIONS_S):
        path = tmp_path / f"scene_{i}.mp3"
        await _make_sine_mp3(path, duration)
        scene_paths.append(path)

    # The TRUE spoken duration of each file, per the brief's instruction to
    # compare against measured per-scene durations, not the requested ones
    # (MP3 encoding itself rounds to the nearest frame - ffprobe is the
    # only source of truth for what was actually written).
    true_durations = [_stream_duration(p, "audio") for p in scene_paths]
    true_total = sum(true_durations)

    video_path = tmp_path / "silent.mp4"
    await _make_silent_video(video_path, duration_s=true_total + 5.0)

    output_path = tmp_path / "muxed.mp4"
    await mux_narration(video_path, scene_paths, output_path, render_settings)

    assembled_duration = _stream_duration(output_path, "audio")

    # The proof: assembled duration matches the TRUE sum to well within a
    # single MP3 frame (26ms) - not "close enough for four scenes", exact
    # regardless of scene count, because the concat filter joins decoded
    # samples rather than encoded frames.
    assert abs(assembled_duration - true_total) < 0.01, (
        f"assembled={assembled_duration}s true_total={true_total}s "
        f"(per-scene: {true_durations})"
    )

    # Same five files through the concat DEMUXER - the trap this module's
    # docstring warns about - to prove the drift is real and would have
    # shown up here if `mux_narration` took that route instead.
    concat_list = tmp_path / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in scene_paths),
        encoding="utf-8",
    )
    demuxer_output = tmp_path / "demuxer_concat.mp3"
    await _run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(demuxer_output),
        ]
    )
    demuxer_probe = _ffprobe(demuxer_output, "format=duration")
    demuxer_duration = float(demuxer_probe["format"]["duration"])

    # The demuxer's drift must be measurably larger than our tolerance
    # above - proving the concat filter's accuracy is a deliberate choice
    # that fixed a real, reproducible bug, not a coincidence of this
    # particular set of durations.
    assert abs(demuxer_duration - true_total) > 0.05, (
        "expected the concat DEMUXER to visibly drift from the true total "
        f"(demuxer={demuxer_duration}s true_total={true_total}s) - if it "
        "didn't, this test's chosen durations no longer demonstrate the bug"
    )


async def test_mux_narration_rejects_empty_narration_list(tmp_path):
    render_settings = RenderSettings(
        width=320,
        height=240,
        fps=30,
        pixel_format="yuv420p",
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )
    video_path = tmp_path / "silent.mp4"
    await _make_silent_video(video_path, duration_s=1.0)

    from app.core.errors import PermanentError

    with pytest.raises(PermanentError):
        await mux_narration(video_path, [], tmp_path / "out.mp4", render_settings)
