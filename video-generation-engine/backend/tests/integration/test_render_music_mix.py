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
from app.renderer.music import (
    build_ducked_bed,
    build_ducked_bed_segments,
    combine_duck_windows,
    duck_ramp_windows_segments,
    mux_music,
)
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
    # `-ss` before `-i`: on ffmpeg 9, `-ss` after `-i` with volumedetect
    # does not reliably seek before analysis, which falsely flat-lines
    # mid-timeline duck windows (OQ-1b gap test). Input-side seek matches
    # atrim-based probes on WAV/AAC here.
    args = [
        settings.ffmpeg_binary,
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(path),
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


async def test_ducked_bed_is_louder_in_gap_between_two_speech_ducks(tmp_path):
    """OQ-1b: a 1.2 s hole between two ducks must release the bed — gap
    mean volume louder than inside either duck window (clear of the
    80 ms ramps and the 1 s boundary fades)."""
    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 10.0)

    # Ducks [1.5, 2.5] and [3.7, 4.7] — gap 1.2 s. Fades occupy [0,1]
    # and ~[7,8] on an 8 s bed.
    bed_path = tmp_path / "bed_gap.m4a"
    await build_ducked_bed(
        music_path,
        video_duration=8.0,
        intervals=[(1.5, 2.5), (3.7, 4.7)],
        output_path=bed_path,
        settings=_RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,
    )

    duck_a = await _mean_volume_db(bed_path, start=1.8, duration=0.4)
    gap = await _mean_volume_db(bed_path, start=2.85, duration=0.4)
    duck_b = await _mean_volume_db(bed_path, start=4.0, duration=0.4)

    assert gap - duck_a > 8.0, (
        f"expected gap louder than duck_a by ~14 dB; gap={gap}dB duck_a={duck_a}dB"
    )
    assert gap - duck_b > 8.0, (
        f"expected gap louder than duck_b by ~14 dB; gap={gap}dB duck_b={duck_b}dB"
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


# -- A11 (long_form_direction.md, 2026-09-01): the bed ducks for a
# diegetic cue too, at its own (shallower) depth, combined with narration
# so an overlap never double-ducks.


async def test_diegetic_cue_ducks_the_bed_at_its_own_shallower_depth(tmp_path):
    """`combine_duck_windows` + `build_ducked_bed_segments` end to end,
    real ffmpeg: a cue window with NO narration overlap must duck the bed
    to its OWN (shallower) depth - measurably less than narration's own
    duck depth would produce."""
    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 8.0)

    bed_gain_db = -6.0
    narration_duck_gain_db = -20.0  # deep
    effect_duck_gain_db = -12.0  # shallow (closer to the bed level)

    combined = combine_duck_windows(
        [],  # no narration anywhere in this file
        narration_duck_gain_db,
        [(2.0, 4.0)],  # the cue window
        effect_duck_gain_db,
        bed_gain_db=bed_gain_db,
    )
    segments = duck_ramp_windows_segments(combined)

    bed_path = tmp_path / "bed_effect_only.m4a"
    await build_ducked_bed_segments(
        music_path,
        video_duration=6.0,
        segments=segments,
        output_path=bed_path,
        settings=_RENDER_SETTINGS,
        bed_gain_db=bed_gain_db,
    )

    duck_volume = await _mean_volume_db(bed_path, start=2.5, duration=1.0)
    bed_volume = await _mean_volume_db(bed_path, start=4.5, duration=1.0)

    # Ducked, but by the SHALLOW effect depth (~6dB), not narration's deep
    # one (~14dB) - proves the effect's own gain was actually used.
    depth = bed_volume - duck_volume
    assert 3.0 < depth < 10.0, f"expected a shallow ~6dB duck; measured {depth}dB"


async def test_overlapping_narration_and_cue_ducks_to_the_deeper_depth_only(tmp_path):
    """A cue firing DURING narration must read at the deeper of the two
    depths, never their product (the "double-duck into mud" failure this
    slice exists to prevent) - measured on the real ducked-bed audio, not
    just the gain arithmetic already covered by unit tests."""
    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 8.0)

    bed_gain_db = -6.0
    narration_duck_gain_db = -20.0  # deeper
    effect_duck_gain_db = -12.0  # shallower

    # Cue [2,4] sits entirely inside a wider narration window [0,6] - a
    # naive multiply would land near -32dB (a -20dB duck stacked on a
    # -12dB one); combine_duck_windows must instead read exactly -20dB
    # (the deeper of the two, alone) throughout the overlap.
    combined = combine_duck_windows(
        [(0.0, 6.0)],
        narration_duck_gain_db,
        [(2.0, 4.0)],
        effect_duck_gain_db,
        bed_gain_db=bed_gain_db,
    )
    segments = duck_ramp_windows_segments(combined)

    bed_path = tmp_path / "bed_overlap.m4a"
    await build_ducked_bed_segments(
        music_path,
        video_duration=8.0,
        segments=segments,
        output_path=bed_path,
        settings=_RENDER_SETTINGS,
        bed_gain_db=bed_gain_db,
    )

    inside_cue = await _mean_volume_db(bed_path, start=2.7, duration=0.6)
    narration_only = await _mean_volume_db(bed_path, start=0.5, duration=0.8)
    # Clear of narration (ends at 6.0) and clear of the tail fade
    # (starts at video_duration - 1.0 = 7.0).
    bed_only = await _mean_volume_db(bed_path, start=6.3, duration=0.5)

    # The overlap must measure the SAME as narration-only ducking (the
    # deeper depth alone) - not measurably deeper still, which is what a
    # product/double-duck would produce.
    assert abs(inside_cue - narration_only) < 1.5, (
        f"expected overlap to read as narration's own depth; "
        f"inside_cue={inside_cue}dB narration_only={narration_only}dB"
    )
    # And both duck windows are clearly quieter than the released bed.
    assert bed_only - narration_only > 8.0
    assert bed_only - inside_cue > 8.0


async def test_mux_music_ducks_for_a_diegetic_cue_with_no_narration(tmp_path):
    """Full `mux_music` entry point, real ffmpeg: a project with a
    diegetic cue but no narration at all must still duck the bed under
    the cue window when `effect_intervals` is supplied."""
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
        effect_intervals=[(2.0, 4.0)],
        effect_duck_gain_db=-12.0,
    )

    duck_volume = await _mean_volume_db(output_path, start=2.5, duration=1.0)
    bed_volume = await _mean_volume_db(output_path, start=4.5, duration=1.0)
    assert bed_volume - duck_volume > 3.0


async def test_mux_music_with_empty_effect_intervals_matches_narration_only_path(tmp_path):
    """Byte-identical-behaviour guard: `effect_intervals=[]` (every
    project with no `Shot.sfx_cue` today) must reproduce EXACTLY the
    pre-A11 narration-only ducking, not merely something similar."""
    video_path = tmp_path / "video.mp4"
    await _make_silent_video(video_path, 6.0)

    music_path = tmp_path / "music.mp3"
    await _make_sine_mp3(music_path, 8.0)

    narration_path = tmp_path / "narration.mp3"
    await _make_sine_mp3(narration_path, 6.0)

    narrated_path = tmp_path / "narrated.mp4"
    await mux_narration(video_path, [narration_path], narrated_path, _RENDER_SETTINGS)

    baseline_path = tmp_path / "baseline.mp4"
    await mux_music(
        narrated_path,
        music_path,
        [narration_path],
        baseline_path,
        _RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,
    )

    with_empty_effect_path = tmp_path / "with_empty_effect.mp4"
    await mux_music(
        narrated_path,
        music_path,
        [narration_path],
        with_empty_effect_path,
        _RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,
        effect_intervals=[],
        effect_duck_gain_db=-12.0,
    )

    assert baseline_path.read_bytes() == with_empty_effect_path.read_bytes()


async def _make_near_silent_mp3(path: Path, duration_s: float) -> None:
    """Sine at −60 dB so bed energy cannot hide amix attenuation."""
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:duration={duration_s}:sample_rate=44100",
        "-af",
        "volume=-60dB",
        "-ar",
        "44100",
        "-b:a",
        "128k",
        "-c:a",
        "libmp3lame",
        str(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace"))


async def test_mux_music_does_not_attenuate_narration_under_silent_bed(tmp_path):
    """OQ-1d: amix default normalize=1 scaled each input by 1/n (~−6 dB).
    With normalize=0, narration+near-silent bed must match narration-only
    loudness within 1.5 dB, and audio still covers the video (longest)."""
    silent_path = tmp_path / "silent.mp4"
    await _make_silent_video(silent_path, 4.0)

    narration_path = tmp_path / "narration.mp3"
    await _make_sine_mp3(narration_path, 4.0)

    narrated_path = tmp_path / "narrated.mp4"
    await mux_narration(silent_path, [narration_path], narrated_path, _RENDER_SETTINGS)

    bed_path = tmp_path / "near_silent_bed.mp3"
    await _make_near_silent_mp3(bed_path, 4.0)

    mixed_path = tmp_path / "mixed.mp4"
    await mux_music(
        narrated_path,
        bed_path,
        [narration_path],
        mixed_path,
        _RENDER_SETTINGS,
        bed_gain_db=-6.0,
        duck_gain_db=-20.0,
    )

    narr_only = await _mean_volume_db(narrated_path, start=0.5, duration=2.0)
    mixed = await _mean_volume_db(mixed_path, start=0.5, duration=2.0)
    assert abs(mixed - narr_only) < 1.5, (
        f"expected |Δ mean_volume| < 1.5 dB after normalize=0; "
        f"got narr_only={narr_only}dB mixed={mixed}dB delta={mixed - narr_only}dB"
    )
    assert _stream_duration(mixed_path, "video") > 3.5
    assert _stream_duration(mixed_path, "audio") > 3.5
