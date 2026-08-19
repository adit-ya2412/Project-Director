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
builds the ffmpeg filter STRING around it. Every still input is a
single-decode `-i path` (Track C §4.1b): Ken Burns because `zoompan`
must see exactly ONE decoded frame to accumulate its `zoom` variable
across the `d` frames it generates internally, and STATIC/SPLIT_FRAME
because a looping `-loop 1 -t` demuxer held ~10.6 GB resident on a
185-shot dissolve run. Duration for a static still comes from
`tpad=stop_mode=clone` inside the graph, the same "one decode, generate
duration internally" shape `zoompan`'s `d=` already used. Both paths
still produce a stream of exactly `duration_s` seconds at `settings.fps`
- the crossfade arithmetic below never needs to know which path a given
shot took.

## Motion clips (motion_new_styles_and_long_form_videos.md, Track A, A1/A2)

A shot's resolved media may be a real video clip rather than a still
(Kling generation, or a future Pexels-video rung) - `render_timeline`
classifies every shot's media exactly once (`app/renderer/motion.py`,
Pillow-then-ffprobe) before grouping into runs, and `_render_run` below
dispatches on the result: a STILL shot is Ken Burns or static-tpad (as
above); a MOTION shot is fed to ffmpeg fully decoded (`-i path` - the
same input shape every still now uses), never gets a `zoompan` filter
regardless of what `shot.camera` says (moving the camera over
already-moving footage reads as a bug, not a style), and is
duration-fitted to exactly `shot.duration_s` by
`app/renderer/motion.py::build_duration_fit_fragment` (A2) so the
crossfade arithmetic below still gets a stream of the length it expects.

Determinism (Invariant I5): every ffmpeg invocation is built as an argument
list (never a shell string — see security guidance in the implementation
guide), inputs are normalised individually before composition, and nothing
here reads the wall clock or iterates an unordered collection.
"""

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.renderer.ken_burns import WORKING_CANVAS_SCALE, ZoompanExpression, build_zoompan_expression
from app.renderer.motion import MediaKind, MediaProbe, build_duration_fit_fragment, probe_media
from app.schemas.timeline import Shot, Timeline
from app.timeline.duration import group_into_runs

logger = get_logger(__name__)


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


async def run_ffmpeg(args: list[str], *, cwd: Path | None = None) -> None:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        tail = stderr.decode(errors="replace")[-4000:]
        raise PermanentError(f"ffmpeg failed (exit {process.returncode}): {tail}")


def stage_short_input(src: Path, dest: Path) -> None:
    """Make `dest` a same-bytes alias of `src` inside the ffmpeg cwd.

    Track C §4.2 half 2: argv carries `run_000_s000.jpg`, never
    `storage/{uuid}/assets/{64-hex}.jpg`. Symlink first (no copy),
    hardlink next (works on Windows without Developer Mode when both
    paths share a volume), copy last. I5 cares about decoded pixels,
    not whether dest is a link. Re-renders unlink a leftover dest
    from a previous run in the same work_dir.

    Copy is the fallback when `storage_root` and `work_dir` sit on
    different volumes (~110 MB at 185 shots). Production Linux and
    same-volume Windows are free (symlink/hardlink). Not a defect —
    Track C §14.3.
    """
    if dest.is_symlink() or dest.exists():
        dest.unlink()
    src = src.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.symlink_to(src)
        return
    except OSError:
        pass
    try:
        os.link(src, dest)
        return
    except OSError:
        pass
    shutil.copy2(src, dest)


@lru_cache
def filter_graph_file_flag(ffmpeg_binary: str) -> str:
    """Argv flag that loads a filtergraph from a file.

    Probe the modern flag (`-/filter_complex`, ffmpeg ≥ 7) against a
    missing script file. "Unrecognized option" means this binary is
    older than 7 and needs `-filter_complex_script`. Any other failure
    (file not found, etc.) means the option exists. Cached per binary
    so the subprocess runs once per process, not per render.

    Version-string parsing is deliberately not used: nightlies like
    `N-120345-g…` parse as major 0, and an unparseable string is more
    likely new than old (Track C §14.6). Probe failure (binary
    missing, timeout) also defaults to the modern flag.
    """
    try:
        result = subprocess.run(
            [
                ffmpeg_binary,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=2x2:d=0.04",
                "-/filter_complex",
                "__no_such_filter_script.filter",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        text = (result.stderr or "") + (result.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return "-/filter_complex"
    if "unrecognized option" in text.lower() and "filter_complex" in text.lower():
        return "-filter_complex_script"
    return "-/filter_complex"


def short_input_name(index: int, src: Path, kind: MediaKind, *, run_stem: str) -> str:
    """Per-run unique name (Track C §14.2 / R-C2).

    `i` is the index *within the run*. Every run shares `work_dir`, so
    a bare `s000.jpg` collides the moment §12 step 9c renders runs
    concurrently — a silent wrong-picture, not a crash. The filter
    file already used `output_path.stem` (`run_000.filter`); inputs
    inherit that same stem. Do not simplify this back to `s000.jpg`.
    """
    suffix = src.suffix.lower()
    if not suffix:
        suffix = ".mp4" if kind is MediaKind.MOTION else ".png"
    return f"{run_stem}_s{index:03d}{suffix}"


def _normalize_filter(index: int, settings: RenderSettings, label: str, *, hold_s: float) -> str:
    """STATIC/SPLIT_FRAME still: one decoded frame, duration from tpad.

    Filter order is scale/pad/setsar, then `fps`, then `tpad`, then
    format. The C0 probe put tpad *before* fps and that is fine for
    still-only xfades; ffmpeg 7.1.5 (production) rejects a motion-clip
    + tpad-still xfade with `rate of 1/0 is invalid` unless the still
    is already CFR when tpad clones it. `fps` first also makes the
    decoded frame last `1/fps` seconds, so `hold_s = (frames - 1) / fps`
    is exact (Track C §14.1). `frames == 1` → `0.0`. Do not "fix"
    the `- 1` back.
    """
    w, h = settings.width, settings.height
    return (
        f"[{index}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"fps={settings.fps},"
        f"tpad=stop_mode=clone:stop_duration={hold_s:.6f},"
        f"fps={settings.fps},"
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
    `tpad` hold already gives, and the property the crossfade offset
    arithmetic below (D5) depends on."""
    assert probe.duration_s is not None
    w, h = settings.width, settings.height
    fit_fragment = build_duration_fit_fragment(
        actual_duration_s=probe.duration_s, target_duration_s=target_duration_s
    )
    fit_stage = f"{fit_fragment}," if fit_fragment else ""
    # fps again after trim/setpts: ffmpeg 7.1.5's xfade rejects a
    # post-setpts stream as rate 1/0 when the other input is a still.
    return (
        f"[{index}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={settings.fps},"
        f"{fit_stage}fps={settings.fps},format={settings.pixel_format}[{label}]"
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
    *,
    work_dir: Path,
) -> None:
    """Render one run (shots joined only by crossfades, no hard cuts) to
    a single MP4.

    Track C §4.2 + §4.1b: every input is a short work-dir name
    (`run_000_s000.jpg` — run-unique, §14.2); the filter graph lives
    in a sibling `.filter` file; ffmpeg runs with `cwd=work_dir`.
    There is no `-loop 1 -t` branch left — STATIC duration is `tpad`
    in the graph. Both halves of the argv fix are required: the
    filter file alone leaves ~31k chars of long input paths against
    Windows' 32,767 limit.
    """
    # M8 step 5: a Ken-Burns shot's frame count is computed HERE (the one
    # place duration-to-frames arithmetic lives for this module, D5's
    # "compute it once" discipline) and reused for zoompan's `d` and for
    # STATIC tpad's hold. A1 (2026-08-18): a MOTION shot never gets a
    # zoompan expression at all, regardless of what `shot.camera` says.
    frame_counts = [max(round(shot.duration_s * settings.fps), 1) for shot in run]
    ken_burns_exprs = [
        (
            build_zoompan_expression(shot.camera, frames=f)
            if media_probes[shot.id].kind is MediaKind.STILL
            else None
        )
        for shot, f in zip(run, frame_counts, strict=True)
    ]

    args = [settings.ffmpeg_binary, "-y"]
    run_stem = output_path.stem
    for i, shot in enumerate(run):
        src = shot_images[shot.id]
        short = short_input_name(i, src, media_probes[shot.id].kind, run_stem=run_stem)
        stage_short_input(src, work_dir / short)
        # image2 defaults to 25 fps; pin stills to the output rate so
        # xfade on ffmpeg 7.1.5 sees CFR on both sides (Track C §14.6).
        if media_probes[shot.id].kind is MediaKind.STILL:
            args += ["-framerate", str(settings.fps), "-i", short]
        else:
            args += ["-i", short]

    filters: list[str] = []
    labels: list[str] = []
    for i, (shot, expr) in enumerate(zip(run, ken_burns_exprs, strict=True)):
        label = f"n{i}"
        probe = media_probes[shot.id]
        if probe.kind is MediaKind.MOTION:
            filters.append(_motion_filter(i, settings, label, probe, shot.duration_s))
        elif expr is None:
            # tpad appends after the decoded frame (§14.1). Holding
            # `frames / fps` yields frames+1. `frames == 1` → 0.0, which
            # is correct — no hold.
            hold_s = (frame_counts[i] - 1) / settings.fps
            filters.append(_normalize_filter(i, settings, label, hold_s=hold_s))
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

    script_name = f"{output_path.stem}.filter"
    (work_dir / script_name).write_text(";".join(filters), encoding="utf-8")
    try:
        output_arg = output_path.resolve().relative_to(work_dir.resolve()).as_posix()
    except ValueError:
        output_arg = str(output_path)

    args += [
        filter_graph_file_flag(settings.ffmpeg_binary),
        script_name,
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
        output_arg,
    ]
    logger.info(
        "render.run_argv",
        extra={
            "shots": len(run),
            "arg_count": len(args),
            "argv_chars": len(" ".join(args)),
        },
    )
    await run_ffmpeg(args, cwd=work_dir)


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
        await _render_run(
            run, resolved_images, media_probes, settings, run_path, work_dir=work_dir
        )
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
