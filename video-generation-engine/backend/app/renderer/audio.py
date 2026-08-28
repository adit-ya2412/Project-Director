"""Narration muxing: the M8 step-3 audio pass (implementation guide, Phase
M8, build order item 3 — "Mux narration into the render").

The visual composition path (`app/renderer/slideshow.py`) is untouched by
this module: narration is added as ONE final ffmpeg pass over its already
-finished silent output, never threaded through the per-run xfade graph.
Doing it any other way would recreate, for audio, exactly the drift D5
exists to prevent for video — an xfade's overlap subtracts real seconds
from the picture's timeline, so feeding raw per-scene audio through that
same graph would mean re-deriving D5's overlap arithmetic a second time,
in a second place, for a second medium (the "duplicating this logic
anywhere else" trap `app/timeline/duration.py`'s own docstring warns
about). Keeping the mux separate means the video graph, already proven,
needs no changes at all — see `RenderStep` for how the two passes compose.

## The concatenation trap — MP3 specifically

Per-scene narration audio is stored as MP3 (`elevenlabs_output_format`,
e.g. `mp3_44100_128`). MP3 is a FRAMED codec with encoder delay and
padding around every encoded stream, so joining encoded MP3 byte streams
end to end — ffmpeg's concat DEMUXER, or a raw byte concatenation — does
NOT reproduce "these clips played back to back": every boundary loses or
gains a few milliseconds depending on where the frame grid falls. On a
multi-scene video that is several boundaries of small, compounding error
— the audio drifts progressively later against the picture, and it
presents as "the voice slowly falls behind", not as an obvious concat
bug. Measured empirically while building this module: five MP3s whose
real decoded durations summed to 5.420998s came out to 5.565828s through
the concat demuxer (+145ms — about 36ms per boundary, and growing with
every scene) and exactly 5.420998s through the approach below. See
`tests/integration/test_narration_audio_concat.py` for the automated,
numeric version of that same proof.

The fix: use ffmpeg's `concat` FILTER, not the concat demuxer. The filter
operates on DECODED audio samples — every input is fully decoded to PCM
before joining, so "joining" is just placing sample buffers back to back
on the sample timeline. There is no encoder framing left at the boundary
to lose or pad, so the joined track's duration is exactly the sum of the
inputs' true decoded durations, by construction, regardless of how many
scenes are joined.

## OQ-1c — per-scene level matching (before concat)

Each scene is a separate TTS call, so integrated loudness can step at
boundaries. Before the concat filter runs, measurable scenes are gain-
matched to the *mean* of their integrated LUFS (not a second absolute
target — OQ-1a owns the mix). Unmeasurable scenes stay unadjusted;
failure never aborts the render.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.renderer.ebur128 import parse_ebur128_summary
from app.renderer.slideshow import RenderSettings, run_ffmpeg

logger = get_logger(__name__)

# Skip rewriting a scene when its gain would be noise-level.
_GAIN_EPS_DB = 0.05


def _db_to_linear(gain_db: float) -> float:
    return 10 ** (gain_db / 20)


async def _run_ffmpeg_capture(args: list[str]) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr_b = await process.communicate()
    stderr = stderr_b.decode("utf-8", errors="replace")
    return process.returncode or 0, stderr


async def measure_integrated_lufs(path: Path, ffmpeg_binary: str) -> float | None:
    """Integrated LUFS via ffmpeg ebur128, or None if unmeasurable."""
    try:
        code, stderr = await _run_ffmpeg_capture(
            [
                ffmpeg_binary,
                "-hide_banner",
                "-i",
                str(path),
                "-filter:a",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ]
        )
    except OSError as exc:
        logger.warning("narration level match: ebur128 failed for %s: %s", path, exc)
        return None
    parsed = parse_ebur128_summary(stderr)
    if parsed is None:
        if code != 0:
            logger.warning(
                "narration level match: ebur128 unparseable for %s (exit %s)",
                path,
                code,
            )
        else:
            logger.warning("narration level match: ebur128 summary missing for %s", path)
        return None
    return parsed["integrated_lufs"]


async def _apply_volume(
    src: Path,
    dest: Path,
    linear_gain: float,
    ffmpeg_binary: str,
) -> bool:
    """Write a duration-preserving PCM wav with ``volume=`` applied.

    Returns False on failure (caller leaves the scene unadjusted).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, stderr = await _run_ffmpeg_capture(
        [
            ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-i",
            str(src),
            "-filter:a",
            f"volume={linear_gain:.8f}",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )
    if code != 0 or not dest.is_file():
        logger.warning(
            "narration level match: volume apply failed for %s: %s",
            src,
            stderr[-500:] if stderr else f"exit {code}",
        )
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False
    return True


async def gain_match_narration_scenes(
    narration_paths: list[Path],
    *,
    work_dir: Path,
    ffmpeg_binary: str,
) -> list[Path]:
    """Gain-match measurable scenes to their mean integrated LUFS.

    Unmeasurable scenes are left at their original path and logged.
    If none can be measured, returns the input paths unchanged.
    """
    if len(narration_paths) < 2:
        return list(narration_paths)

    measured: dict[int, float] = {}
    for i, path in enumerate(narration_paths):
        lufs = await measure_integrated_lufs(path, ffmpeg_binary)
        if lufs is None or not math.isfinite(lufs):
            logger.warning(
                "narration level match: cannot measure scene %s (%s); leaving unadjusted",
                i,
                path,
            )
            continue
        measured[i] = lufs

    if not measured:
        logger.warning(
            "narration level match: no scenes measurable; concat as-is (%s files)",
            len(narration_paths),
        )
        return list(narration_paths)

    mean_lufs = sum(measured.values()) / len(measured)
    out: list[Path] = []
    for i, path in enumerate(narration_paths):
        if i not in measured:
            out.append(path)
            continue
        gain_db = mean_lufs - measured[i]
        if abs(gain_db) < _GAIN_EPS_DB:
            out.append(path)
            continue
        linear = _db_to_linear(gain_db)
        adj = work_dir / f".narr_lvl_{i}_{path.stem}.wav"
        if await _apply_volume(path, adj, linear, ffmpeg_binary):
            out.append(adj)
        else:
            out.append(path)
    return out


async def mux_narration(
    video_path: Path,
    narration_paths: list[Path],
    output_path: Path,
    settings: RenderSettings,
    *,
    level_match: bool = True,
) -> Path:
    """Decode-and-concatenate `narration_paths` (already in Timeline scene
    order — ordering is the caller's responsibility, the same contract
    `render_timeline` already has for `shot_images`) via the concat filter,
    then mux the joined track onto `video_path`, writing `output_path`.

    When ``level_match`` is True (OQ-1c), measurable per-scene files are
    gain-matched to their mean integrated LUFS into temp wavs under
    ``output_path.parent`` before the concat filter runs. The concat
    FILTER itself is unchanged (D1 / MP3 framing lesson above).

    Video is stream-copied (`-c:v copy`) — its bytes are already correct
    and this pass must not re-encode or otherwise touch them. The joined
    narration is encoded once, to AAC, the codec an MP4/`+faststart`
    container expects; re-encoding audio here is unavoidable (the concat
    filter's output is raw decoded samples) but happens exactly once, not
    once per scene boundary.

    Deliberately NO `-shortest`. `render_timeline`'s video is quantised to
    whole frames (each shot's `-t` duration gets re-timed onto
    `settings.fps`), so its true rendered length can land a few
    milliseconds either side of the narration's exact sum — measured
    empirically while building this: a 4-shot/4.153016s narrated timeline
    rendered to a 4.133333s silent video, ~20ms short. `-shortest` would
    have silently clipped that ~20ms off the END of the real, correct
    narration to match — which is exactly the "truncating audio is not an
    option; it cuts words off mid-sentence" the M8 design decisions rule
    out, just at a duration small enough to look tempting. Narration is
    the master clock (D1): it keeps its full, true length regardless of
    which way the video's frame quantisation happens to round, and any
    sub-frame gap between the two streams' reported durations is the
    video's rounding, not the audio's problem to absorb.
    """
    if not narration_paths:
        raise PermanentError("mux_narration called with no narration audio to mux")

    paths_for_concat = list(narration_paths)
    if level_match:
        paths_for_concat = await gain_match_narration_scenes(
            narration_paths,
            work_dir=output_path.parent,
            ffmpeg_binary=settings.ffmpeg_binary,
        )

    args = [settings.ffmpeg_binary, "-y", "-i", str(video_path)]
    for path in paths_for_concat:
        args += ["-i", str(path)]

    n = len(paths_for_concat)
    # Deterministic label order (I5): built from range(n), never a dict or
    # set, so the concat order is always exactly Timeline scene order.
    audio_labels = "".join(f"[{i + 1}:a]" for i in range(n))
    filter_complex = f"{audio_labels}concat=n={n}:v=0:a=1[aout]"

    args += [
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        # I5 (M8 step 6): strip non-deterministic muxer/encoder metadata
        # so the same inputs always produce the same output bytes - see
        # app/renderer/slideshow.py's own comment on this exact pair.
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
