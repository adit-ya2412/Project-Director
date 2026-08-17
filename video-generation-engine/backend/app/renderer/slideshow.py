"""The M0 renderer: Timeline + resolved shot images -> MP4 (silent).

Proves the visual composition path: normalisation, crossfade transitions,
and hard cuts, against real FFmpeg, on real Windows path handling. Audio
is deliberately NOT this module's job — `app/renderer/audio.py` mixes
narration onto the finished output of `render_timeline` as a separate
final pass (M8 step 3), so this file's graph stays exactly what it was
when it was first proven, video-only.

## Ken Burns (M8 step 5)

A shot whose `camera.movement` isn't `STATIC`/`SPLIT_FRAME` gets a
`zoompan` filter instead of the plain static-frame path -
`app/renderer/ken_burns.py` owns the expression arithmetic (kept
separate and unit-testable without shelling out); this module only
builds the ffmpeg filter STRING around it. Critically, a Ken-Burns
shot's INPUT is `-i path` (no `-loop`/`-t`) - not the static path's
`-loop 1 -t duration` - because `zoompan` must see exactly ONE decoded
frame to accumulate its `zoom` variable correctly across the `d` frames
it generates internally; feeding it the static path's already-looped,
multi-frame input is the well-known cause of `zoompan` resetting to
zoom=1 every single frame (see that module's own docstring). Both paths
still produce a stream of exactly `duration_s` seconds at `settings.fps`
- the crossfade arithmetic below never needs to know which path a given
shot took.

Determinism (Invariant I5): every ffmpeg invocation is built as an argument
list (never a shell string — see security guidance in the implementation
guide), inputs are normalised individually before composition, and nothing
here reads the wall clock or iterates an unordered collection.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import PermanentError
from app.renderer.ken_burns import WORKING_CANVAS_SCALE, ZoompanExpression, build_zoompan_expression
from app.schemas.timeline import Shot, Timeline
from app.timeline.duration import group_into_runs


@dataclass(frozen=True)
class RenderSettings:
    width: int
    height: int
    fps: int
    pixel_format: str
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    # Unlike the music gains (read from config once, directly, since they
    # never vary by call site), this DOES vary per call site - drafts
    # never burn captions regardless of `settings.burn_captions`
    # (docs/14_Captions_Plan.md §4.3), the same reason width/height are
    # already here rather than read from config inside `render_video`.
    burn_captions: bool = False
    # Same reasoning, same carve-out: drafts never get the watermark
    # either (docs/plans/watermark_implementation_plan.md §5).
    watermark_enabled: bool = False
    # Same carve-out again, same reasoning (motion_new_styles_and_long_
    # form_videos.md §2.6, Tier 2, 2026-08-17) - a draft is for spotting
    # wrong-asset/wrong-order bugs quickly, not for reviewing a title
    # card's own look.
    burn_text_cards: bool = False


async def run_ffmpeg(args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        tail = stderr.decode(errors="replace")[-4000:]
        raise PermanentError(f"ffmpeg failed (exit {process.returncode}): {tail}")


def _normalize_filter(index: int, settings: RenderSettings, label: str) -> str:
    w, h = settings.width, settings.height
    return (
        f"[{index}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={settings.fps},"
        f"format={settings.pixel_format}[{label}]"
    )


def _ken_burns_filter(
    index: int, settings: RenderSettings, label: str, expr: ZoompanExpression, frames: int
) -> str:
    """The Ken-Burns equivalent of `_normalize_filter` - scales up to an
    oversized working canvas first (so `zoompan` resamples real extra
    pixels rather than upscaling an already-target-resolution frame),
    then applies the zoom/pan envelope, landing on the exact same output
    size/pixel format `_normalize_filter` would have. No `fps=` filter
    needed afterwards - `zoompan`'s own `fps=` parameter already sets it,
    and its `d` parameter is what makes this stream exactly `frames`
    frames long (== `shot.duration_s` seconds at `settings.fps`, the
    caller's arithmetic, not this function's)."""
    w, h = settings.width, settings.height
    canvas_w = round(w * WORKING_CANVAS_SCALE)
    canvas_h = round(h * WORKING_CANVAS_SCALE)
    return (
        f"[{index}:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
        f"crop={canvas_w}:{canvas_h},setsar=1,"
        f"zoompan=z='{expr.zoom_expr}':x='{expr.x_expr}':y='{expr.y_expr}':"
        f"d={frames}:s={w}x{h}:fps={settings.fps},"
        f"format={settings.pixel_format}[{label}]"
    )


async def _render_run(
    run: list[Shot],
    shot_images: dict[str, Path],
    settings: RenderSettings,
    output_path: Path,
) -> None:
    """Render one run (shots joined only by crossfades, no hard cuts) to
    a single MP4."""
    args = [settings.ffmpeg_binary, "-y"]
    # M8 step 5: a Ken-Burns shot's frame count is computed HERE (the one
    # place duration-to-frames arithmetic lives for this module, D5's
    # "compute it once" discipline) and reused for both the input args
    # (which input shape a shot gets) and the filter (zoompan's `d`).
    frame_counts = [max(round(shot.duration_s * settings.fps), 1) for shot in run]
    ken_burns_exprs = [
        build_zoompan_expression(shot.camera, frames=f)
        for shot, f in zip(run, frame_counts, strict=True)
    ]

    for shot, expr in zip(run, ken_burns_exprs, strict=True):
        image_path = shot_images[shot.id]
        if expr is None:
            args += ["-loop", "1", "-t", f"{shot.duration_s:.3f}", "-i", str(image_path)]
        else:
            # Exactly one decoded frame - see this module's own docstring
            # and `app/renderer/ken_burns.py`'s for why `-loop`/`-t` must
            # NOT be used here.
            args += ["-i", str(image_path)]

    filters: list[str] = []
    labels: list[str] = []
    for i, expr in enumerate(ken_burns_exprs):
        label = f"n{i}"
        if expr is None:
            filters.append(_normalize_filter(i, settings, label))
        else:
            filters.append(_ken_burns_filter(i, settings, label, expr, frame_counts[i]))
        labels.append(label)

    if len(run) == 1:
        vout = labels[0]
    else:
        cumulative = run[0].duration_s
        prev_label = labels[0]
        for i in range(1, len(run)):
            overlap = run[i - 1].transition_out.duration_s
            transition_name = run[i - 1].transition_out.type.value
            offset = max(cumulative - overlap, 0.0)
            out_label = f"x{i}"
            filters.append(
                f"[{prev_label}][{labels[i]}]xfade=transition={transition_name}:"
                f"duration={overlap:.3f}:offset={offset:.3f}[{out_label}]"
            )
            cumulative = cumulative + run[i].duration_s - overlap
            prev_label = out_label
        vout = prev_label

    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        f"[{vout}]",
        "-r",
        str(settings.fps),
        # I5 (M8 step 6): `+bitexact` strips non-deterministic muxer/
        # encoder metadata (creation_time, encoder version string) that
        # ffmpeg otherwise stamps into the output on every run even given
        # byte-identical inputs; `-threads 1` pins libx264 to a single
        # thread, since its default multi-threaded mode is not guaranteed
        # to make the same internal decisions run to run. Both are
        # required for `tests/integration/test_render_determinism.py`'s
        # actual byte-for-byte proof, not just asserted here.
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-threads",
        "1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        settings.pixel_format,
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await run_ffmpeg(args)


async def render_timeline(
    timeline: Timeline,
    shot_images: dict[str, Path],
    settings: RenderSettings,
    output_path: Path,
    *,
    work_dir: Path,
) -> Path:
    """Render an approved Timeline plus resolved shot images into a single
    MP4. Hard cuts between runs are joined losslessly via the concat
    demuxer; non-cut transitions become an ffmpeg xfade crossfade inside a
    run (see app.timeline.duration for the grouping rule, D5)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    shots = timeline.all_shots()
    if not shots:
        raise PermanentError("timeline has no shots to render")
    missing = [shot.id for shot in shots if shot.id not in shot_images]
    if missing:
        raise PermanentError(f"no resolved image for shots: {missing}")

    runs = group_into_runs(shots)

    run_paths: list[Path] = []
    for i, run in enumerate(runs):
        run_path = work_dir / f"run_{i:03d}.mp4"
        await _render_run(run, shot_images, settings, run_path)
        run_paths.append(run_path)

    if len(run_paths) == 1:
        run_paths[0].replace(output_path)
        return output_path

    concat_list = work_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in run_paths),
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
        str(concat_list),
        "-c",
        "copy",
        # I5: even a stream-copy pass stamps a fresh `creation_time` into
        # the container by default - `+bitexact` suppresses that too, so
        # concatenating the same runs twice produces the same bytes.
        "-fflags",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path


async def probe_duration_seconds(path: Path, ffprobe_binary: str = "ffprobe") -> float:
    """Read the actual rendered duration back out of the file — the only
    way to prove the render pipeline's arithmetic is correct rather than
    merely self-consistent."""
    args = [
        ffprobe_binary,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise PermanentError(f"ffprobe failed: {stderr.decode(errors='replace')}")
    return float(stdout.decode().strip())
