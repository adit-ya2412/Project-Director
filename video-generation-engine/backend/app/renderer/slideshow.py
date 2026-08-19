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
import hashlib
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from weakref import WeakKeyDictionary

from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.renderer.ken_burns import WORKING_CANVAS_SCALE, ZoompanExpression, build_zoompan_expression
from app.renderer.motion import MediaKind, MediaProbe, build_duration_fit_fragment, probe_media
from app.schemas.timeline import Shot, Timeline
from app.timeline.duration import group_into_runs
from app.utils.bounded_gather import bounded_gather, ffmpeg_run_concurrency

logger = get_logger(__name__)

# R-C7: one ffmpeg pool for every `run_ffmpeg` caller, including nested
# `bounded_gather` (runs × shots). Recreated if the cap changes so tests
# that monkeypatch `ffmpeg_run_concurrency` still bind the right size.
#
# ## Why this is keyed PER EVENT LOOP and not one module-level object
#
# The first version of this was a single process-lifetime `Semaphore`, and
# that is wrong anywhere event loops are created and destroyed repeatedly
# - which is exactly what a test runner does. `backend/pytest.ini` sets
# `asyncio_mode = auto`, so pytest-asyncio builds a fresh event loop per
# test and discards it at teardown. A task still holding a permit when
# its loop is closed is destroyed without running `async with`'s
# `finally`, so the permit is not returned when the loop dies - and with
# a single shared semaphore that permit is missing for every LATER test
# in the same process.
#
# Measured old-vs-new, one abandoned render per simulated test, cap 14:
# the shared pool drains 13, 12, 11 ... 2, then jumps back to 13; the
# per-loop pool sits at 13 forever. The recovery is garbage collection -
# collecting an abandoned task closes its coroutine, which DOES run the
# `finally` and hands the permit back. So the failure mode is not a
# permanent deadlock but a repeated STALL: renders queue up until the
# collector happens to run, then drain, then queue again. That matches
# what was observed exactly - a full-suite run that crawled to ~62 tests
# over hours with zero-CPU ffmpeg children, while the same tests passed
# file-by-file (a fresh process each time means a fresh pool).
#
# Keying on the running loop makes the leak structurally impossible: a
# test's pool is garbage-collected with its loop, so nothing survives to
# be exhausted. Production is unaffected and keeps the identical
# guarantee - a server has one event loop for its whole life, so there is
# exactly one pool, sized once. `WeakKeyDictionary` (not `dict`) so a
# finished loop is not retained by this module.
_ffmpeg_slots: "WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    WeakKeyDictionary()
)
_ffmpeg_slot_caps: "WeakKeyDictionary[asyncio.AbstractEventLoop, int]" = WeakKeyDictionary()


def _ffmpeg_semaphore() -> asyncio.Semaphore:
    """The ffmpeg concurrency pool for the CURRENT event loop.

    Called only from `run_ffmpeg`, which is a coroutine, so there is
    always a running loop to key on.
    """
    loop = asyncio.get_running_loop()
    cap = ffmpeg_run_concurrency()
    slot = _ffmpeg_slots.get(loop)
    if slot is None or _ffmpeg_slot_caps.get(loop) != cap:
        slot = asyncio.Semaphore(cap)
        _ffmpeg_slots[loop] = slot
        _ffmpeg_slot_caps[loop] = cap
    return slot


def _atomic_copy(src: Path, dest: Path) -> None:
    """R-C8: write next to `dest`, then `os.replace`. `shutil.copy2`
    into the live cache path can be observed mid-write (`st_size > 0`
    but truncated) by a concurrent cache hit."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


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
    async with _ffmpeg_semaphore():
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


def _per_shot_filter(
    input_index: int,
    shot: Shot,
    probe: MediaProbe,
    settings: RenderSettings,
    label: str,
) -> str:
    frames = max(round(shot.duration_s * settings.fps), 1)
    if probe.kind is MediaKind.MOTION:
        return _motion_filter(input_index, settings, label, probe, shot.duration_s)
    expr = (
        build_zoompan_expression(shot.camera, frames=frames)
        if probe.kind is MediaKind.STILL
        else None
    )
    if expr is None:
        hold_s = (frames - 1) / settings.fps
        return _normalize_filter(input_index, settings, label, hold_s=hold_s)
    return _ken_burns_filter(input_index, settings, label, expr, frames)


def _h264_bitexact_args(settings: RenderSettings, output_arg: str) -> list[str]:
    return [
        "-map",
        "[vout]",
        "-r",
        str(settings.fps),
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


def _cwd_output_arg(output_path: Path, work_dir: Path) -> str:
    try:
        return output_path.resolve().relative_to(work_dir.resolve()).as_posix()
    except ValueError:
        return str(output_path)


async def _encode_or_reuse_shot_stream(
    *,
    shot: Shot,
    src: Path,
    probe: MediaProbe,
    settings: RenderSettings,
    dest: Path,
    work_dir: Path,
    run_stem: str,
    index: int,
    asset_hash: str,
    ffmpeg_version: str,
) -> Path:
    """Pass 1 of C3 (d): one shot's normalised stream, cached by
    `compute_shot_stream_fingerprint`. tpad, never `-loop 1 -t`.
    """
    from app.renderer.fingerprint import compute_shot_stream_fingerprint

    fingerprint = compute_shot_stream_fingerprint(
        shot=shot,
        asset_hash=asset_hash,
        render_settings=settings,
        ffmpeg_version=ffmpeg_version,
    )
    cache_dir = work_dir / "shot_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{fingerprint}.mp4"
    if cache_path.is_file() and cache_path.stat().st_size > 0:
        shutil.copy2(cache_path, dest)
        logger.info(
            "render.shot_cache_hit",
            extra={"shot_id": shot.id, "fingerprint": fingerprint[:12]},
        )
        return dest

    short = short_input_name(index, src, probe.kind, run_stem=run_stem)
    stage_short_input(src, work_dir / short)
    graph = _per_shot_filter(0, shot, probe, settings, "vout")
    script_name = f"{dest.stem}.filter"
    (work_dir / script_name).write_text(graph, encoding="utf-8")
    args = [settings.ffmpeg_binary, "-y"]
    if probe.kind is MediaKind.STILL:
        args += ["-framerate", str(settings.fps), "-i", short]
    else:
        args += ["-i", short]
    args += [
        filter_graph_file_flag(settings.ffmpeg_binary),
        script_name,
        *_h264_bitexact_args(settings, _cwd_output_arg(dest, work_dir)),
    ]
    logger.info(
        "render.shot_argv",
        extra={"shot_id": shot.id, "arg_count": len(args), "argv_chars": len(" ".join(args))},
    )
    await run_ffmpeg(args, cwd=work_dir)
    _atomic_copy(dest, cache_path)
    return dest


async def _xfade_shot_streams(
    run: list[Shot],
    stream_paths: list[Path],
    settings: RenderSettings,
    output_path: Path,
    *,
    work_dir: Path,
) -> None:
    """Pass 2 of C3 (d): xfade over pre-encoded streams. No zoompan/tpad."""
    run_stem = output_path.stem
    args = [settings.ffmpeg_binary, "-y"]
    filters: list[str] = []
    labels: list[str] = []
    for i, stream in enumerate(stream_paths):
        short = f"{run_stem}_i{i:03d}{stream.suffix.lower() or '.mp4'}"
        if stream.resolve() != (work_dir / short).resolve():
            stage_short_input(stream, work_dir / short)
        args += ["-i", short]
        label = f"n{i}"
        filters.append(f"[{i}:v]fps={settings.fps},format={settings.pixel_format}[{label}]")
        labels.append(label)

    cumulative = run[0].duration_s
    prev_label = labels[0]
    for i in range(1, len(run)):
        overlap = run[i - 1].transition_out.duration_s
        transition_name = run[i - 1].transition_out.type.value
        offset = max(cumulative - overlap, 0.0)
        out_label = f"x{i}" if i < len(run) - 1 else "vout"
        filters.append(
            f"[{prev_label}][{labels[i]}]xfade=transition={transition_name}:"
            f"duration={overlap:.3f}:offset={offset:.3f}[{out_label}]"
        )
        cumulative = cumulative + run[i].duration_s - overlap
        prev_label = out_label

    script_name = f"{run_stem}.xfade.filter"
    (work_dir / script_name).write_text(";".join(filters), encoding="utf-8")
    args += [
        filter_graph_file_flag(settings.ffmpeg_binary),
        script_name,
        *_h264_bitexact_args(settings, _cwd_output_arg(output_path, work_dir)),
    ]
    logger.info(
        "render.xfade_argv",
        extra={"shots": len(run), "arg_count": len(args), "argv_chars": len(" ".join(args))},
    )
    await run_ffmpeg(args, cwd=work_dir)


async def _render_run_two_pass(
    run: list[Shot],
    shot_images: dict[str, Path],
    media_probes: dict[str, MediaProbe],
    settings: RenderSettings,
    output_path: Path,
    *,
    work_dir: Path,
    shot_content_hashes: dict[str, str],
    ffmpeg_version: str,
) -> None:
    run_stem = output_path.stem

    async def _one(item: tuple[int, Shot]) -> Path:
        index, shot = item
        dest = work_dir / f"{run_stem}_i{index:03d}.mp4"
        return await _encode_or_reuse_shot_stream(
            shot=shot,
            src=shot_images[shot.id],
            probe=media_probes[shot.id],
            settings=settings,
            dest=dest,
            work_dir=work_dir,
            run_stem=run_stem,
            index=index,
            asset_hash=shot_content_hashes[shot.id],
            ffmpeg_version=ffmpeg_version,
        )

    gathered = await bounded_gather(
        list(enumerate(run)),
        _one,
        concurrency=ffmpeg_run_concurrency(),
    )
    stream_paths: list[Path] = []
    for item in gathered:
        if isinstance(item, Exception):
            raise item
        stream_paths.append(item)
    await _xfade_shot_streams(run, stream_paths, settings, output_path, work_dir=work_dir)


async def _render_run(
    run: list[Shot],
    shot_images: dict[str, Path],
    media_probes: dict[str, MediaProbe],
    settings: RenderSettings,
    output_path: Path,
    *,
    work_dir: Path,
    shot_content_hashes: dict[str, str] | None = None,
    ffmpeg_version: str | None = None,
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

    Multi-shot runs use two-pass (C3 (d)): per-shot cached streams, then
    an xfade-only chain. A single-shot run stays one encode.
    """
    if len(run) >= 2:
        if ffmpeg_version is None:
            from app.renderer.fingerprint import get_ffmpeg_version

            ffmpeg_version = await get_ffmpeg_version(settings.ffmpeg_binary)
        hashes = shot_content_hashes or {
            shot.id: _file_content_hash(shot_images[shot.id]) for shot in run
        }
        await _render_run_two_pass(
            run,
            shot_images,
            media_probes,
            settings,
            output_path,
            work_dir=work_dir,
            shot_content_hashes=hashes,
            ffmpeg_version=ffmpeg_version,
        )
        return
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


def _file_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _render_or_reuse_run(
    index: int,
    run: list[Shot],
    resolved_images: dict[str, Path],
    media_probes: dict[str, MediaProbe],
    settings: RenderSettings,
    work_dir: Path,
    shot_content_hashes: dict[str, str],
    ffmpeg_version: str,
) -> Path:
    """Encode one run, or copy a previous encode of the same run.

    Staging names stay `run_{index:03d}_s000.jpg` (R-C2) even under
    parallel gathers — two runs must never share `s000.jpg`.
    """
    from app.renderer.fingerprint import compute_run_fingerprint

    run_path = work_dir / f"run_{index:03d}.mp4"
    fingerprint = compute_run_fingerprint(
        shots=run,
        shot_content_hashes=shot_content_hashes,
        render_settings=settings,
        ffmpeg_version=ffmpeg_version,
    )
    cache_dir = work_dir / "run_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{fingerprint}.mp4"
    if cache_path.is_file() and cache_path.stat().st_size > 0:
        shutil.copy2(cache_path, run_path)
        logger.info(
            "render.run_cache_hit",
            extra={"run": index, "shots": len(run), "fingerprint": fingerprint[:12]},
        )
        return run_path

    await _render_run(
        run,
        resolved_images,
        media_probes,
        settings,
        run_path,
        work_dir=work_dir,
        shot_content_hashes=shot_content_hashes,
        ffmpeg_version=ffmpeg_version,
    )
    _atomic_copy(run_path, cache_path)
    return run_path


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

    # Lazy: fingerprint.py imports RenderSettings from this module.
    from app.renderer.fingerprint import get_ffmpeg_version

    ffmpeg_version = await get_ffmpeg_version(settings.ffmpeg_binary)
    shot_content_hashes = {shot.id: _file_content_hash(resolved_images[shot.id]) for shot in shots}

    async def _one_run(item: tuple[int, list[Shot]]) -> Path:
        index, run = item
        return await _render_or_reuse_run(
            index,
            run,
            resolved_images,
            media_probes,
            settings,
            work_dir,
            shot_content_hashes,
            ffmpeg_version,
        )

    gathered = await bounded_gather(
        list(enumerate(runs)),
        _one_run,
        concurrency=ffmpeg_run_concurrency(),
    )
    run_paths: list[Path] = []
    for item in gathered:
        if isinstance(item, Exception):
            raise item
        run_paths.append(item)

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
