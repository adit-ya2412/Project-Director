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

OQ-1b (2026-08-28): when per-character alignment is available (the same
`character_start_times_seconds` / `character_end_times_seconds` arrays
captions already consume), duck windows follow real speech runs on the
audio-concat clock — scene i starts at the sum of previous scenes' last
`character_end`. Gaps ≤ `DUCK_MERGE_THRESHOLD_S` (`MIN_CUE_DURATION_S`
from captions, 0.8 s) stay ducked so a breath is not a release; leading
silence before the first character and trailing silence after a scene's
last character are NOT ducked. Ramps in/out of each duck are a small
number of stepped `between()` windows (not ffmpeg volume expressions —
see above), still a precomputed static envelope (I5; no live sidechain).

When alignment is missing/None, fall back to per-SCENE granularity from
ffprobe-measured narration file durations (`compute_narration_intervals`),
exactly as before OQ-1b.

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

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.renderer.captions import MIN_CUE_DURATION_S
from app.renderer.slideshow import RenderSettings, probe_duration_seconds, run_ffmpeg

logger = get_logger(__name__)

_FADE_SECONDS = 1.0

# Same pause threshold as captions so ducking and captions agree what a
# pause is (OQ-1b). Constant, not a Settings knob — ear sign-off pending.
DUCK_MERGE_THRESHOLD_S = MIN_CUE_DURATION_S  # 0.8 s

# Starting ear default for duck in/out ramps — not signed off (OQ-1b).
DUCK_RAMP_S = 0.080
DUCK_RAMP_STEPS = 4


def offset_bed_and_duck_gain_db(
    bed_gain_db: float, duck_gain_db: float, gain_offset_db: float
) -> tuple[float, float]:
    """Applies the human's per-track dB offset (`gain_offset_db` - the
    BGM upload slider, analysis.md decision 7) to BOTH the bed and the
    duck gain, so the whole envelope shifts together and the style's duck
    DEPTH (`bed_gain_db - duck_gain_db`) is preserved.

    Analysis.md RV6: `_volume_chain` below computes
    `relative_duck = duck_linear / bed_linear` and applies that RATIO on
    top of an unconditional `volume=bed_linear` - which makes the level
    during a narration window resolve to the ABSOLUTE `duck_gain_db`,
    independent of the bed. Offsetting the bed alone therefore does not
    move the ducked floor at all; it only changes how far above that
    fixed floor the bed sits. Once the offset drops the bed below the
    duck gain (`gain_offset_db < duck_gain_db - bed_gain_db`, i.e. more
    negative than the style's own duck depth), `relative_duck` exceeds
    1.0 and ducking INVERTS - music gets LOUDER, not quieter, under
    narration. Applying the offset to both gains keeps `relative_duck`
    identical to the un-offset style mix for every offset value, so
    ducking can never invert."""
    return bed_gain_db + gain_offset_db, duck_gain_db + gain_offset_db


async def assemble_act_bed(
    segments: list[tuple[Path, float]],
    output_path: Path,
    settings: RenderSettings,
) -> Path:
    """Loop-and-trim each `(path, duration_s)` segment, then concat in
    order to `output_path`. One segment is still loop+trim so a short
    library track covers a 2-minute act the same way Path A's single bed
    covers the whole video. Hard cuts between acts — a 1.5–3 minute
    change does not need a crossfade, and a cut stays I5-simple."""
    if not segments:
        raise ValueError("assemble_act_bed requires at least one segment")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_path.parent / f"_act_bed_{output_path.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)
    trimmed: list[Path] = []
    for i, (path, duration_s) in enumerate(segments):
        piece = work_dir / f"act_{i:03d}.m4a"
        args = [
            settings.ffmpeg_binary,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(path),
            "-t",
            f"{duration_s:.3f}",
            "-c:a",
            "aac",
            "-fflags",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            str(piece),
        ]
        await run_ffmpeg(args)
        trimmed.append(piece)

    if len(trimmed) == 1:
        trimmed[0].replace(output_path)
        return output_path

    list_path = work_dir / "concat.txt"
    list_path.write_text(
        "".join(f"file '{p.name}'\n" for p in trimmed),
        encoding="utf-8",
    )
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        "-fflags",
        "+bitexact",
        str(output_path),
    ]
    await run_ffmpeg(args, cwd=work_dir)
    return output_path


def _db_to_linear(gain_db: float) -> float:
    return 10 ** (gain_db / 20)


def speaking_intervals_from_alignment(
    alignment_by_scene: Sequence[Mapping[str, Any] | None],
    *,
    merge_threshold_s: float = DUCK_MERGE_THRESHOLD_S,
) -> list[tuple[float, float]]:
    """Duck windows from per-character alignment on the audio-concat clock.

    Scene i starts at the sum of previous scenes' last `character_end`
    (same clock as OQ-0a silence map / `derive_caption_cues`). Inside a
    scene, consecutive characters form one speaking run; a gap
    (`next_start - this_end`) ≤ `merge_threshold_s` stays ducked. Leading
    silence before the first character and trailing silence after the
    last character of a scene are NOT ducked. Empty/malformed alignment
    for a scene skips that scene's windows (logged) without raising.
    """
    parsed: list[tuple[list[float], list[float]] | None] = []
    for scene_index, alignment in enumerate(alignment_by_scene):
        parsed.append(_parse_scene_alignment(alignment, scene_index=scene_index))
    if any(scene is None for scene in parsed):
        # RV-Q2: one unusable scene used to leave scene_offset stuck, so
        # every later window sat on the wrong concat clock. Captions
        # refuse a row/scene mismatch outright; we do the same and let
        # mux_music fall back to file-duration intervals.
        logger.warning(
            "music.duck_alignment_abandoned",
            extra={
                "reason": "unusable_scene",
                "scenes": len(parsed),
                "unusable": sum(1 for scene in parsed if scene is None),
            },
        )
        return []

    intervals: list[tuple[float, float]] = []
    scene_offset = 0.0
    for local_starts, local_ends in parsed:
        run_start = local_starts[0]
        run_end = local_ends[0]
        for i in range(1, len(local_starts)):
            gap = local_starts[i] - local_ends[i - 1]
            if gap <= merge_threshold_s:
                run_end = local_ends[i]
            else:
                intervals.append((scene_offset + run_start, scene_offset + run_end))
                run_start = local_starts[i]
                run_end = local_ends[i]
        intervals.append((scene_offset + run_start, scene_offset + run_end))
        scene_offset += local_ends[-1]

    return _merge_touching_intervals(intervals)


def _parse_scene_alignment(
    alignment: Mapping[str, Any] | None,
    *,
    scene_index: int,
) -> tuple[list[float], list[float]] | None:
    if alignment is None:
        logger.warning(
            "music.duck_alignment_skipped",
            extra={"scene_index": scene_index, "reason": "alignment is None"},
        )
        return None
    starts_raw = list(alignment.get("character_start_times_seconds") or [])
    ends_raw = list(alignment.get("character_end_times_seconds") or [])
    if not starts_raw or not ends_raw or len(starts_raw) != len(ends_raw):
        logger.warning(
            "music.duck_alignment_skipped",
            extra={
                "scene_index": scene_index,
                "reason": "empty_or_length_mismatch",
                "n_starts": len(starts_raw),
                "n_ends": len(ends_raw),
            },
        )
        return None
    try:
        return [float(x) for x in starts_raw], [float(x) for x in ends_raw]
    except (TypeError, ValueError):
        logger.warning(
            "music.duck_alignment_skipped",
            extra={"scene_index": scene_index, "reason": "non_numeric_times"},
        )
        return None


def _merge_touching_intervals(
    intervals: list[tuple[float, float]],
    *,
    min_gap_s: float | None = None,
) -> list[tuple[float, float]]:
    """Collapse runs closer than 2*ramp so in/out ramps cannot overlap.

    RV-Q3: a 20–80 ms gap at a scene join is ordinary TTS leading
    silence; ramps of 80 ms on each side would multiply below the duck
    floor. Merging anything closer than two ramps removes the collision.
    """
    if not intervals:
        return []
    gap = 2 * DUCK_RAMP_S if min_gap_s is None else min_gap_s
    ordered = sorted(intervals)
    merged: list[tuple[float, float]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def duck_envelope_content_hash(
    intervals: list[tuple[float, float]],
    *,
    merge_threshold_s: float = DUCK_MERGE_THRESHOLD_S,
    ramp_s: float = DUCK_RAMP_S,
) -> str:
    """Fingerprint input for the alignment-derived duck envelope (OQ-1b).

    Hashes the canonical `(start, end)` duck windows plus merge/ramp
    constants. When alignment is absent the render step passes `None`
    instead (file-duration fallback is fully determined by
    `narration_content_hashes`).
    """
    payload = {
        "intervals": [[round(start, 3), round(end, 3)] for start, end in intervals],
        "merge_threshold_s": merge_threshold_s,
        "ramp_s": ramp_s,
        "ramp_steps": DUCK_RAMP_STEPS,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def duck_ramp_windows(
    intervals: list[tuple[float, float]],
    *,
    relative_duck: float,
    ramp_s: float = DUCK_RAMP_S,
    steps: int = DUCK_RAMP_STEPS,
) -> list[tuple[float, float, float]]:
    """Expand each duck into ramp-in steps + full duck + ramp-out steps.

    Returns `(start, end, relative_gain)` triples in chronological order
    per input interval. Relative gain is the multiplier applied on top of
    the unconditional bed `volume=` (same architecture as a flat duck).
    80 ms / 4 steps is the OQ-1b starting ear default — not signed off.

    ⚠ RV-Q3 (reopened 2026-08-29): these windows become `volume=` filters
    chained in series, so any two that overlap MULTIPLY. Correctness
    therefore depends on the input intervals being at least `2*ramp_s`
    apart, and that invariant is enforced HERE rather than left to the
    caller — the first fix put the guard only in
    `speaking_intervals_from_alignment`, and `compute_narration_intervals`
    (the fallback RV-Q2's own refusal routes into) returns per-scene
    intervals explicitly "back to back with no gap". Measured on that
    path before this guard: at a scene join both full ducks and both ramp
    sets were live at once, multiplying to **16.1 dB below the intended
    duck floor** for ~80 ms — an audible hole at every boundary, on a bed
    already sitting at −28 dB. Merging here is idempotent for the
    alignment path (already merged at the same threshold), so it changes
    no already-correct output and no fingerprint.
    """
    if ramp_s <= 0 or steps < 1:
        return [(start, end, relative_duck) for start, end in intervals]

    intervals = _merge_touching_intervals(intervals, min_gap_s=2 * ramp_s)

    windows: list[tuple[float, float, float]] = []
    dt = ramp_s / steps
    for start, end in intervals:
        if end <= start:
            continue
        for k in range(1, steps + 1):
            t0 = start - ramp_s + (k - 1) * dt
            t1 = start - ramp_s + k * dt
            gain = 1.0 + (relative_duck - 1.0) * (k / steps)
            if t1 <= 0 or t1 <= t0:
                continue
            windows.append((max(t0, 0.0), t1, gain))
        windows.append((start, end, relative_duck))
        for k in range(1, steps + 1):
            t0 = end + (k - 1) * dt
            t1 = end + k * dt
            # k/steps of the way from full duck back toward bed (1.0).
            gain = relative_duck + (1.0 - relative_duck) * (k / steps)
            if t1 <= t0:
                continue
            # Last step lands at gain≈1.0 (noop multiply); skip it.
            if abs(gain - 1.0) < 1e-12:
                continue
            windows.append((t0, t1, gain))
    windows.sort(key=lambda item: (item[0], item[1]))
    return windows


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
    for start, end, rel in duck_ramp_windows(intervals, relative_duck=relative_duck):
        # A single `between(t,a,b)` per filter - the escaped comma is
        # the only one, never nested inside a broader if()/expression.
        filters.append(f"volume={rel:.6f}:enable='between(t\\,{start:.3f}\\,{end:.3f})'")
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
    amix_normalize: int = 0,
    alignment_by_scene: Sequence[Mapping[str, Any] | None] | None = None,
) -> Path:
    """Mixes `music_path` (looped/trimmed to `video_path`'s real length,
    ducked under `narration_paths` if any) onto `video_path`, writing
    `output_path`. `video_path`'s own existing streams are copied through
    unchanged (`-c:v copy`); when it already carries a narration audio
    stream (`narration_paths` not empty/None), that stream is mixed with
    the ducked bed via `amix` - when it doesn't (no narration, or
    DRY_RUN's caller never gets here at all - see
    `RenderStep._resolve_music_track`), the ducked bed becomes the
    output's only audio stream.

    `amix_normalize` is the ffmpeg `amix` normalize flag (OQ-1d). 0 keeps
    narration at the same level with or without a bed; 1 is ffmpeg's
    default (scale 1/n). The render step fingerprints the same value
    (RV2).

    `alignment_by_scene` (OQ-1b): when provided, duck windows come from
    `speaking_intervals_from_alignment`; otherwise file-duration
    per-scene intervals (`compute_narration_intervals`).
    """
    video_duration = await probe_duration_seconds(video_path, settings.ffprobe_binary)
    if alignment_by_scene is not None:
        intervals = speaking_intervals_from_alignment(alignment_by_scene)
        source = "alignment"
        if not intervals and narration_paths:
            # Alignment present but produced no windows (all scenes
            # malformed) — do not leave the bed unducked under speech.
            intervals = await compute_narration_intervals(
                narration_paths, settings.ffprobe_binary
            )
            source = "file_duration_fallback"
    elif narration_paths:
        intervals = await compute_narration_intervals(narration_paths, settings.ffprobe_binary)
        source = "file_duration"
    else:
        intervals = []
        source = "none"

    logger.info(
        "music.duck_envelope",
        extra={
            "source": source,
            "interval_count": len(intervals),
            "merge_threshold_s": DUCK_MERGE_THRESHOLD_S,
            "ramp_s": DUCK_RAMP_S,
            "ramp_steps": DUCK_RAMP_STEPS,
        },
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
            # Default ffmpeg normalize=1 scales each active input by 1/n
            # (~−6 dB with two inputs). Same flag as mux_sfx (RV11).
            f"[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0:"
            f"normalize={int(amix_normalize)}[aout]",
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
