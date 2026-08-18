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

## Motion clips (motion_new_styles_and_long_form_videos.md, Track A, A1/A2)

A shot's resolved media may be a real video clip rather than a still
(Kling generation, or a future Pexels-video rung) - `render_timeline`
classifies every shot's media exactly once (`app/renderer/motion.py`,
Pillow-then-ffprobe) before grouping into runs, and `_render_run` below
dispatches on the result: a STILL shot is unchanged (the plain loop path
or Ken Burns, as above); a MOTION shot is fed to ffmpeg fully decoded
(`-i path`, no `-loop`/`-t` - the SAME input shape Ken Burns uses and for
an adjacent reason: both need a real decode, never a pre-looped copy),
never gets a `zoompan` filter regardless of what `shot.camera` says
(moving the camera over already-moving footage reads as a bug, not a
style), and is duration-fitted to exactly `shot.duration_s` by
`app/renderer/motion.py::build_duration_fit_fragment` (A2) so the
crossfade arithmetic below still gets a stream of the length it expects.

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
from app.renderer.motion import MediaKind, MediaProbe, build_duration_fit_fragment, probe_media
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


def _motion_filter(
    index: int, settings: RenderSettings, label: str, probe: MediaProbe, target_duration_s: float
) -> str:
    """The motion-clip equivalent of `_normalize_filter` - the same
    scale/pad/setsar/fps/format envelope, plus the ONE extra stage A2's
    duration-fit arithmetic (`app/renderer/motion.py`) inserts between
    `fps=` and `format=`: trim a too-long clip, or hold the last frame of
    a too-short one, so every motion shot's stream is EXACTLY
    `target_duration_s` seconds long - the same guarantee a still shot's
    `-t` flag already gives, and the property the crossfade offset
    arithmetic below (D5) depends on."""
    assert probe.duration_s is not None
    w, h = settings.width, settings.height
    fit_fragment = build_duration_fit_fragment(
        actual_duration_s=probe.duration_s, target_duration_s=target_duration_s
    )
    fit_stage = f"{fit_fragment}," if fit_fragment else ""
    return (
        f"[{index}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={settings.fps},"
        f"{fit_stage}format={settings.pixel_format}[{label}]"
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
    media_probes: dict[str, MediaProbe],
    settings: RenderSettings,
    output_path: Path,
) -> None:
    """Render one run (shots joined only by crossfades, no hard cuts) to
    a single MP4."""
    args = [settings.ffmpeg_binary, "-y"]
    # M8 step 5: a Ken-Burns shot's frame count is computed HERE (the one
    # place duration-to-frames arithmetic lives for this module, D5's
    # "compute it once" discipline) and reused for both the input args
    # (which input shape a shot gets) and the filter (zoompan's `d`). A1
    # (2026-08-18): a MOTION shot never gets a zoompan expression at all,
    # regardless of what `shot.camera` says - moving the camera over
    # already-moving footage reads as a bug, not a style.
    frame_counts = [max(round(shot.duration_s * settings.fps), 1) for shot in run]
    ken_burns_exprs = [
        (
            build_zoompan_expression(shot.camera, frames=f)
            if media_probes[shot.id].kind is MediaKind.STILL
            else None
        )
        for shot, f in zip(run, frame_counts, strict=True)
    ]

    for shot, expr in zip(run, ken_burns_exprs, strict=True):
        image_path = shot_images[shot.id]
        if media_probes[shot.id].kind is MediaKind.MOTION or expr is not None:
            # A real decoded clip (A1) and a Ken-Burns still (M8 step 5)
            # share this input shape for adjacent reasons: both need
            # ffmpeg to decode the input itself, never a pre-looped copy
            # - see this module's own docstring and `ken_burns.py`'s.
            args += ["-i", str(image_path)]
        else:
            args += ["-loop", "1", "-t", f"{shot.duration_s:.3f}", "-i", str(image_path)]

    filters: list[str] = []
    labels: list[str] = []
    for i, (shot, expr) in enumerate(zip(run, ken_burns_exprs, strict=True)):
        label = f"n{i}"
        probe = media_probes[shot.id]
        if probe.kind is MediaKind.MOTION:
            filters.append(_motion_filter(i, settings, label, probe, shot.duration_s))
        elif expr is None:
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

    # A1 (2026-08-18): classify each shot's resolved media exactly once,
    # here. A STILL still goes through the existing GIF-flatten gate
    # (`ensure_still_image`) - deferred-imported because `still.py`
    # itself imports `RenderSettings`/`run_ffmpeg` from this module, and
    # importing it at module scope here would be a circular import. A
    # real MOTION clip is left untouched (that gate would flatten it to a
    # single frame, the exact frozen-frame failure this whole track
    # exists to fix) and is instead fitted to the shot's duration by
    # `_render_run` below (A2).
    from app.renderer.still import ensure_still_image

    media_probes: dict[str, MediaProbe] = {}
    resolved_images: dict[str, Path] = {}
    for shot in shots:
        path = shot_images[shot.id]
        probe = await probe_media(path, ffprobe_binary=settings.ffprobe_binary)
        media_probes[shot.id] = probe
        resolved_images[shot.id] = (
            path
            if probe.kind is MediaKind.MOTION
            else await ensure_still_image(
                path, shot_id=shot.id, work_dir=work_dir, settings=settings
            )
        )

    runs = group_into_runs(shots)

    run_paths: list[Path] = []
    for i, run in enumerate(runs):
        run_path = work_dir / f"run_{i:03d}.mp4"
        await _render_run(run, resolved_images, media_probes, settings, run_path)
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
