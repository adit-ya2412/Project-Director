"""Music mixing: the M8 step-4 ducking pass (D6/21.2).

A STATIC volume envelope, never a live sidechain compressor - I5
requires rendering to be a pure function of its inputs, and a real-time
compressor's behaviour depends on the actual sample stream in ways that
are not exactly reproducible the way a precomputed, timestamped envelope
is. The bed plays throughout at `MUSIC_BED_GAIN_DB`, ducked to
`MUSIC_DUCK_GAIN_DB` across every interval narration is speaking, with a
fade in/out at the video's boundaries.

## How the envelope is built without ffmpeg expression escaping

A `volume` filter's own expression mode (`volume='if(between(t,a,b),x,y)'`)
needs every comma inside the expression escaped for the surrounding
filtergraph syntax, which nests badly once there is more than one
interval. Instead: chain one `volume` filter per speaking interval, each
scoped with `enable='between(t,start,end)'` (ffmpeg's per-filter time
gate) to a RELATIVE gain of `duck_linear / bed_linear` - applied on top
of a base `volume=bed_linear` filter that runs unconditionally across
the whole stream. Outside every `enable` window each interval's filter
is a no-op (multiply by 1); inside one, the two multiply out to exactly
`duck_linear`. Deterministic, no nested expressions, and the chain is
built from a plain Python list of intervals in a fixed order (I5 - never
from unordered iteration).

## What "every interval narration is speaking" means here

Per-SCENE granularity, not per-character. Each scene's own narration
audio is one continuous "speaking" interval, from its offset in the
final muxed narration track (computed the same way `mux_narration`
joins scenes - real, ffprobe-measured durations, back to back with no
gap) to that offset plus its own duration. Sub-scene pauses (a breath, a
pause after punctuation - see `app/timeline/narration_fit.py`'s own
docstring) are NOT sub-divided into separate on/off windows:
`narration_fit.py` already attributes any such gap to whichever shot is
still on screen during it, i.e. treats it as part of that shot's
continuous "speaking" window rather than silence to stop ducking for -
the identical simplification applies here, for the identical reason,
and avoids needing character-level timing data this module has no
access to in the first place (it only ever sees per-scene audio files).

## Looping and length

The music input is read with `-stream_loop -1` (repeat indefinitely) and
then `atrim`med to the video's own real (ffprobe-measured) duration -
this covers a track shorter OR longer than the video with the same two
ffmpeg options, so no duration-based preference is needed when ranking
candidates (see `app/assets/music_ranking.py`).

## Two ffmpeg passes, not one, and why

`_build_ducked_bed` produces the ducked, faded, video-length music track
as its OWN file first; `mux_music` then does a second, simpler pass that
either maps that file straight through (no narration) or `amix`es it
with the video's existing narration stream. Splitting it this way keeps
the ducking envelope directly testable in isolation - measuring a mixed
narration+music signal cannot distinguish "the music got quieter" from
"narration is simply loud", which is exactly the failure a first-draft,
single-pass version of this module ran into while it was being built.
"""

from pathlib import Path

from app.renderer.slideshow import RenderSettings, probe_duration_seconds, run_ffmpeg

_FADE_SECONDS = 1.0


def _db_to_linear(gain_db: float) -> float:
    return 10 ** (gain_db / 20)


async def compute_narration_intervals(
    narration_paths: list[Path], ffprobe_binary: str
) -> list[tuple[float, float]]:
    """`[(start, end), ...]` in the FINAL, muxed narration track's own
    time base - one interval per scene, back to back with no gap,
    matching exactly how `mux_narration`'s concat FILTER joins them (real
    decoded durations, never an encoder-framed estimate - see that
    module's own docstring on why the concat DEMUXER's duration would be
    wrong here)."""
    intervals: list[tuple[float, float]] = []
    cursor = 0.0
    for path in narration_paths:
        duration = await probe_duration_seconds(path, ffprobe_binary)
        intervals.append((cursor, cursor + duration))
        cursor += duration
    return intervals


def _volume_chain(
    intervals: list[tuple[float, float]], *, bed_gain_db: float, duck_gain_db: float
) -> str:
    bed_linear = _db_to_linear(bed_gain_db)
    duck_linear = _db_to_linear(duck_gain_db)
    relative_duck = duck_linear / bed_linear

    filters = [f"volume={bed_linear:.6f}"]
    for start, end in intervals:
        # A single `between(t,a,b)` per filter - the escaped comma is
        # the only one, never nested inside a broader if()/expression.
        filters.append(f"volume={relative_duck:.6f}:enable='between(t\\,{start:.3f}\\,{end:.3f})'")
    return ",".join(filters)


async def build_ducked_bed(
    music_path: Path,
    video_duration: float,
    intervals: list[tuple[float, float]],
    output_path: Path,
    settings: RenderSettings,
    *,
    bed_gain_db: float,
    duck_gain_db: float,
) -> Path:
    """The music bed alone (looped/trimmed to `video_duration`, ducked
    across `intervals`, faded in/out at the boundaries) - no video, no
    narration, an audio-only file. Directly testable in isolation (see
    tests/integration/test_render_music_mix.py) precisely because nothing
    else is mixed into it yet."""
    fade_seconds = min(_FADE_SECONDS, video_duration / 2)
    fade_out_start = max(video_duration - fade_seconds, 0.0)
    chain = _volume_chain(intervals, bed_gain_db=bed_gain_db, duck_gain_db=duck_gain_db)

    args = [
        settings.ffmpeg_binary,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(music_path),
        "-filter_complex",
        f"[0:a]atrim=0:{video_duration:.3f},asetpts=PTS-STARTPTS,{chain},"
        f"afade=t=in:st=0:d={fade_seconds:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_seconds:.3f}[aout]",
        "-map",
        "[aout]",
        "-c:a",
        "aac",
        # I5 (M8 step 6): see app/renderer/slideshow.py's own comment on
        # this exact pair - strips non-deterministic muxer/encoder
        # metadata from the (intermediate) ducked-bed file too, so the
        # final mux downstream is reproducible from identical inputs.
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path


async def mux_music(
    video_path: Path,
    music_path: Path,
    narration_paths: list[Path] | None,
    output_path: Path,
    settings: RenderSettings,
    *,
    bed_gain_db: float,
    duck_gain_db: float,
) -> Path:
    """Mixes `music_path` (looped/trimmed to `video_path`'s real length,
    ducked under `narration_paths` if any) onto `video_path`, writing
    `output_path`. `video_path`'s own existing streams are copied through
    unchanged (`-c:v copy`); when it already carries a narration audio
    stream (`narration_paths` not empty/None), that stream is mixed with
    the ducked bed via `amix` - when it doesn't (no narration, or
    DRY_RUN's caller never gets here at all - see
    `RenderStep._resolve_music_track`), the ducked bed becomes the
    output's only audio stream."""
    video_duration = await probe_duration_seconds(video_path, settings.ffprobe_binary)
    intervals = (
        await compute_narration_intervals(narration_paths, settings.ffprobe_binary)
        if narration_paths
        else []
    )

    ducked_bed_path = output_path.parent / f"_ducked_bed_{output_path.stem}.m4a"
    await build_ducked_bed(
        music_path,
        video_duration,
        intervals,
        ducked_bed_path,
        settings,
        bed_gain_db=bed_gain_db,
        duck_gain_db=duck_gain_db,
    )

    args = [
        settings.ffmpeg_binary,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(ducked_bed_path),
    ]

    has_narration_audio = bool(narration_paths)
    if has_narration_audio:
        # `duration=longest`, not `first` (a first draft used `first`
        # and it was wrong): the ducked bed is already trimmed to the
        # VIDEO's own length, but narration's own real length can be a
        # hair shorter (rounding - `mux_narration` never pads it) or, in
        # theory, a test double could hand this function a mismatched
        # pair. `first` would silently truncate the whole mixed output
        # to narration's length the moment it is even slightly shorter
        # than the video/music - `longest` is the only option that
        # cannot truncate a real track early.
        args += [
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0[aout]",
            "-map",
            "0:v",
            "-map",
            "[aout]",
        ]
    else:
        args += ["-map", "0:v", "-map", "1:a"]

    args += [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path
