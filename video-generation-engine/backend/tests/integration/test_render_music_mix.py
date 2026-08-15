"""`app/renderer/music.mux_music` (M8 step 4, D6/21.2) - proves the
ducking envelope actually reduces the music bed's measured volume during
a narration-speaking interval and returns it to bed level outside one,
not just that ffmpeg runs without error. Real, small MP3/silent-video
files synthesised locally via ffmpeg (same technique as
test_narration_audio_concat.py) - no real Pixabay call, no
`FakeMusicProvider` bytes (deliberately undecodable, see its docstring).
"""

import asyncio
import re
from pathlib import Path

from app.core.config import settings
from app.renderer.audio import mux_narration
from app.renderer.music import build_ducked_bed, mux_music
from app.renderer.slideshow import RenderSettings

from .test_narration_audio_concat import _make_silent_video, _make_sine_mp3, _stream_duration

_RENDER_SETTINGS = RenderSettings(
    width=640,
    height=360,
    fps=30,
    pixel_format="yuv420p",
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)


async def _mean_volume_db(path: Path, *, start: float, duration: float) -> float:
    args = [
        settings.ffmpeg_binary,
        "-i",
        str(path),
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    text = stderr.decode(errors="replace")
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", text)
    if not match:
        raise AssertionError(f"no mean_volume in ffmpeg output:\n{text}")
    return float(match.group(1))


async def test_ducked_bed_is_quieter_during_the_speaking_interval(tmp_path):
    """The ducking envelope itself, isolated from narration entirely -
    measuring a POST-MIX signal cannot distinguish "the music got
    quieter" from "narration is simply loud" (a real dead end hit while
    building this test), so this measures `build_ducked_bed`'s own
    output directly: a music-only file, no narration signal anywhere in
    it to confound the reading."""
    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 8.0)

    bed_path = tmp_path / "bed.m4a"
    await build_ducked_bed(
        music_path,
        video_duration=6.0,
        intervals=[(0.0, 2.0)],  # duck window: [0, 2)
        output_path=bed_path,
        settings=_RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,  # an exaggerated, easily-measurable gap
    )

    # Well inside the duck window (past the 1s fade-in) and well inside
    # the bed-only window after it (before the fade-out near the end) -
    # clear of every transition edge.
    duck_volume = await _mean_volume_db(bed_path, start=1.5, duration=0.3)
    bed_volume = await _mean_volume_db(bed_path, start=4.0, duration=0.3)

    assert bed_volume - duck_volume > 8.0, (
        f"expected the bed to measure louder than the duck window by roughly the "
        f"configured 14dB gap; got bed={bed_volume}dB duck={duck_volume}dB"
    )


async def test_mux_music_combines_narration_and_ducked_bed_without_truncating(tmp_path):
    """The full two-input pass: narration is short (2s) relative to a
    longer (6s) video - `amix=duration=longest` must not truncate the
    output to narration's own shorter length (a real bug caught while
    building this: an earlier version used `duration=first`, and the
    mixed output silently ended at 2s)."""
    silent_path = tmp_path / "silent.mp4"
    await _make_silent_video(silent_path, 6.0)

    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 8.0)

    narration_path = tmp_path / "narration.mp3"
    await _make_sine_mp3(narration_path, 2.0)

    narrated_path = tmp_path / "narrated.mp4"
    await mux_narration(silent_path, [narration_path], narrated_path, _RENDER_SETTINGS)

    output_path = tmp_path / "out.mp4"
    await mux_music(
        narrated_path,
        music_path,
        [narration_path],
        output_path,
        _RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,
    )

    # The video's own length is untouched (`-c:v copy`), and the mixed
    # audio covers the FULL video length, not truncated to narration's
    # shorter 2 seconds.
    assert _stream_duration(output_path, "video") > 5.5
    assert _stream_duration(output_path, "audio") > 5.5


async def test_mux_music_with_no_narration_plays_at_bed_level_throughout(tmp_path):
    """No narration to duck under - the bed plays at a constant level,
    proven by comparing two non-adjacent windows and finding them equal
    (within measurement noise), not just that the file has audio."""
    video_path = tmp_path / "video.mp4"
    await _make_silent_video(video_path, 6.0)

    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 8.0)

    output_path = tmp_path / "out.mp4"
    await mux_music(
        video_path,
        music_path,
        None,
        output_path,
        _RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,
    )

    early = await _mean_volume_db(output_path, start=1.5, duration=0.3)
    late = await _mean_volume_db(output_path, start=4.0, duration=0.3)
    # A generous tolerance, not a precision claim - `volumedetect` over a
    # short window of an MP3-then-AAC-transcoded tone carries some real
    # measurement noise; the point is "not a ~14dB duck", not "identical
    # to the millidecibel".
    assert abs(early - late) < 3.0


async def test_mux_music_loops_a_short_track_to_cover_the_full_video(tmp_path):
    """A track shorter than the video is looped (`-stream_loop -1`) and
    trimmed (`atrim`) to the video's own length - never left short."""
    video_path = tmp_path / "video.mp4"
    await _make_silent_video(video_path, 6.0)

    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 1.5)  # much shorter than the 6s video

    output_path = tmp_path / "out.mp4"
    await mux_music(
        video_path,
        music_path,
        None,
        output_path,
        _RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,
    )

    assert _stream_duration(output_path, "audio") > 5.5
