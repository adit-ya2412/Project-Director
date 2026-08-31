"""The M0 renderer: Timeline + resolved shot images -> MP4 (silent).

Proves the visual composition path: normalisation, crossfade transitions,
and hard cuts, against real FFmpeg, on real Windows path handling. Audio
is deliberately NOT this module's job — `app/renderer/audio.py` mixes
narration onto the finished output of `render_timeline` as a separate
final pass (M8 step 3), so this file's graph stays exactly what it was
when it was first proven, video-only.

## Ken Burns (M8 step 5)

A shot whose `camera.movement` isn't `STATIC`/`SPLIT_FRAME` gets a
`zoompan` filter instead of the plain static-frame path. `SPLIT_FRAME`
with a second still is a `vstack` composite (`split_screen.py`), not
a `zoompan`. Without a second still it takes the static tpad path.
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
from app.renderer.ken_burns import (
    WORKING_CANVAS_SCALE,
    MovingCropExpression,
    ZoompanExpression,
    build_zoompan_expression,
    ken_burns_crop_and_zoompan_focal,
)
from app.renderer.motion import MediaKind, MediaProbe, build_duration_fit_fragment, probe_media
from app.renderer.split_screen import build_split_filter, should_composite_split
from app.schemas.timeline import Shot, Timeline, TransitionType
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
    index: int,
    settings: RenderSettings,
    label: str,
    expr: ZoompanExpression,
    frames: int,
    *,
    crop_x: int | None = None,
    crop_y: int | None = None,
) -> str:
    """The Ken-Burns equivalent of `_normalize_filter` - scales up to an
    oversized working canvas first (so `zoompan` resamples real extra
    pixels rather than upscaling an already-target-resolution frame),
    then applies the zoom/pan envelope, landing on the exact same output
    size/pixel format `_normalize_filter` would have. No `fps=` filter
    needed afterwards - `zoompan`'s own `fps=` parameter already sets it,
    and its `d` parameter is what makes this stream exactly `frames`
    frames long (== `shot.duration_s` seconds at `settings.fps`, the
    caller's arithmetic, not this function's).

    `crop_x`/`crop_y` (RV-Q1): when set, the pre-zoompan crop is aimed at
    the subject instead of the geometric centre. Omitted → today's
    centred `crop=w:h` (byte-identical for a centre/None focal).
    """
    w, h = settings.width, settings.height
    canvas_w = round(w * WORKING_CANVAS_SCALE)
    canvas_h = round(h * WORKING_CANVAS_SCALE)
    if crop_x is None or crop_y is None:
        crop = f"crop={canvas_w}:{canvas_h}"
    else:
        crop = f"crop={canvas_w}:{canvas_h}:{crop_x}:{crop_y}"
    return (
        f"[{index}:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
        f"{crop},setsar=1,"
        f"zoompan=z='{expr.zoom_expr}':x='{expr.x_expr}':y='{expr.y_expr}':"
        f"d={frames}:s={w}x{h}:fps={settings.fps},"
        f"format={settings.pixel_format}[{label}]"
    )


def _ken_burns_pan_filter(
    index: int,
    settings: RenderSettings,
    label: str,
    expr: MovingCropExpression,
    frames: int,
) -> str:
    """PAN's mechanism (A2 horizontal, A5 vertical, long_form_direction.md
    §3) - a moving `crop` over the FULL scaled image, not `zoompan`.
    `crop` has no `zoompan`-style `d=`/`fps=` pair to manufacture `frames`
    frames from a single decoded input, so - exactly like STATIC's own
    `_normalize_filter` - `tpad=stop_mode=clone` materialises the hold
    first, with the same double-`fps=` bracket around it (Track C §14.1:
    ffmpeg 7.1.5's xfade rejects a post-tpad stream as rate 1/0 when the
    other input is a motion clip). `crop`'s `x`/`y` are evaluated PER
    OUTPUT FRAME using ffmpeg's own `n`/`iw`/`ih` - confirmed against a
    real render (a synthetic horizontal-gradient still, sampled
    centre-pixel colour per frame): ffmpeg 9.0's `crop` has no `eval`
    AVOption at all (`ffmpeg -h filter=crop` lists none), and evaluates
    `x`/`y` per frame by default, so the expression's arithmetic runs
    against the real per-frame width/height with no extra flag needed -
    see `MovingCropExpression`.

    Dispatches on `expr.y_expr` (A5): `None` means horizontal (A2) - this
    branch is BYTE-IDENTICAL to what it always emitted, `scale=-2:{h}`
    (height-only, aspect preserved, `-2` keeps width even) and a literal
    `0` for `y`. A set `y_expr` means vertical (A5's mirror): `scale=
    {w}:-2` instead (width-only, so the FULL scaled height is the travel
    margin) and a literal `0` for `x` (see `MovingCropExpression`'s own
    docstring for why `0` is the correct "centred" value there). Either
    way, the `force_original_aspect_ratio=increase` + centred-crop pair
    every other movement uses is deliberately avoided - that pair THROWS
    AWAY the margin PAN needs to travel across (A2's whole finding).
    """
    w, h = settings.width, settings.height
    hold_s = (frames - 1) / settings.fps
    # A2 shipped `scale=-2:{h}` for horizontal (and A5 mirrored it as
    # `scale={w}:-2`), which pins ONE axis and lets the other fall where
    # the source aspect puts it. When the source is narrower than the
    # output aspect that leaves the scaled frame NARROWER than the crop
    # window, and `crop` does not degrade - it refuses to configure:
    #   "Invalid too big or non positive size for width '1280'"
    # -> exit 127, nothing written, the whole render dies. Measured
    # 2026-08-31 against this project's own 648 assets: 111 (17.1%) are
    # narrower than 9:16 and would kill a horizontal PAN on the SHIPPED
    # 720x1280 canvas; 582 (89.8%) are narrower than 16:9 and would kill
    # one on 1280x720. The `max(...,0)` guard in `ken_burns.py` cannot
    # help - it clamps TRAVEL, and the failure is the crop window itself
    # not fitting, which happens before travel is ever evaluated.
    #
    # Scaling to COVER the output instead guarantees both axes are >= the
    # crop window, so `crop` always configures, and it yields travel on
    # whichever axis actually has excess pixels (zero on the other -
    # degrading to a static hold, which is what the guard intended).
    # This is byte-identical in PIXELS to A2 wherever A2 worked: for a
    # source wider than the output aspect, cover-scaling pins height
    # exactly as `-2:{h}` did (verified: 2980x1676 -> 2276x1280 both
    # ways). The emitted STRING changes for every pan, which is why the
    # A2/A5 filter-string tests were updated alongside this.
    scale = f"{w}:{h}:force_original_aspect_ratio=increase"
    if expr.y_expr is None:
        crop = f"crop={w}:{h}:'{expr.x_expr}':0"
    else:
        crop = f"crop={w}:{h}:0:'{expr.y_expr}'"
    return (
        f"[{index}:v]scale={scale},setsar=1,"
        f"fps={settings.fps},"
        f"tpad=stop_mode=clone:stop_duration={hold_s:.6f},"
        f"fps={settings.fps},"
        f"{crop},"
        f"format={settings.pixel_format}[{label}]"
    )


def _ken_burns_aim(
    probe: MediaProbe,
    settings: RenderSettings,
    focal: tuple[float, float] | None,
) -> tuple[int | None, int | None, tuple[float, float] | None]:
    """Map an original-image focal through the scale+crop into zoompan
    space. Missing pixel size → centred crop, original focal unused."""
    if probe.width is None or probe.height is None:
        return None, None, None
    canvas_w = round(settings.width * WORKING_CANVAS_SCALE)
    canvas_h = round(settings.height * WORKING_CANVAS_SCALE)
    return ken_burns_crop_and_zoompan_focal(
        probe.width, probe.height, canvas_w, canvas_h, focal
    )


def _per_shot_filter(
    input_index: int,
    shot: Shot,
    probe: MediaProbe,
    settings: RenderSettings,
    label: str,
    *,
    focal: tuple[float, float] | None = None,
) -> str:
    frames = max(round(shot.duration_s * settings.fps), 1)
    if probe.kind is MediaKind.MOTION:
        return _motion_filter(input_index, settings, label, probe, shot.duration_s)
    crop_x, crop_y, zoompan_focal = _ken_burns_aim(probe, settings, focal)
    expr = (
        build_zoompan_expression(
            shot.camera,
            frames=frames,
            focal=zoompan_focal,
            canvas_w=settings.width,
            canvas_h=settings.height,
            duration_s=shot.duration_s,
        )
        if probe.kind is MediaKind.STILL
        else None
    )
    if expr is None:
        hold_s = (frames - 1) / settings.fps
        return _normalize_filter(input_index, settings, label, hold_s=hold_s)
    if isinstance(expr, MovingCropExpression):
        return _ken_burns_pan_filter(input_index, settings, label, expr, frames)
    return _ken_burns_filter(
        input_index, settings, label, expr, frames, crop_x=crop_x, crop_y=crop_y
    )


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
    secondary_src: Path | None = None,
    secondary_probe: MediaProbe | None = None,
    secondary_asset_hash: str = "",
    focal: tuple[float, float] | None = None,
    focal_fingerprint: str = "",
) -> Path:
    """Pass 1 of C3 (d): one shot's normalised stream, cached by
    `compute_shot_stream_fingerprint`. tpad, never `-loop 1 -t`.
    Split-screen is two still inputs composited here, so xfade still
    sees one stream per shot.
    """
    from app.renderer.fingerprint import compute_shot_stream_fingerprint

    split = should_composite_split(
        shot.camera.movement,
        secondary_path=secondary_src,
        top_kind=probe.kind,
        bot_kind=secondary_probe.kind if secondary_probe is not None else None,
    )
    fingerprint = compute_shot_stream_fingerprint(
        shot=shot,
        asset_hash=asset_hash,
        render_settings=settings,
        ffmpeg_version=ffmpeg_version,
        secondary_asset_hash=secondary_asset_hash if split else "",
        focal=focal_fingerprint,
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

    frames = max(round(shot.duration_s * settings.fps), 1)
    hold_s = (frames - 1) / settings.fps
    args = [settings.ffmpeg_binary, "-y"]
    if split:
        assert secondary_src is not None
        short_top = f"{run_stem}_s{index:03d}_top{src.suffix.lower() or '.png'}"
        short_bot = f"{run_stem}_s{index:03d}_bot{secondary_src.suffix.lower() or '.png'}"
        stage_short_input(src, work_dir / short_top)
        stage_short_input(secondary_src, work_dir / short_bot)
        args += ["-framerate", str(settings.fps), "-i", short_top]
        args += ["-framerate", str(settings.fps), "-i", short_bot]
        graph = build_split_filter(
            0,
            1,
            width=settings.width,
            height=settings.height,
            fps=settings.fps,
            pixel_format=settings.pixel_format,
            label="vout",
            hold_s=hold_s,
        )
    else:
        short = short_input_name(index, src, probe.kind, run_stem=run_stem)
        stage_short_input(src, work_dir / short)
        graph = _per_shot_filter(0, shot, probe, settings, "vout", focal=focal)
        if probe.kind is MediaKind.STILL:
            args += ["-framerate", str(settings.fps), "-i", short]
        else:
            args += ["-i", short]
    script_name = f"{dest.stem}.filter"
    (work_dir / script_name).write_text(graph, encoding="utf-8")
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


# Feature C (style_extensions.md §5, P-C2): the three glitch transitions
# are NOT real `xfade` transition names (unlike WIPE_LEFT/DIP_TO_BLACK) -
# they need a custom multi-stage filter fragment, not a single-line
# `xfade=transition=X`. `_glitch_transition_filter` below is that
# fragment; every other `TransitionType` still takes the plain xfade path.
_GLITCH_TRANSITIONS = frozenset(
    {TransitionType.GLITCH_SHIFT, TransitionType.GLITCH_TEAR, TransitionType.GLITCH_JITTER}
)

# Every pixel-based parameter below was measured against a 480x270
# reference canvas (style_extensions.md P-C2's spike) and verified at
# real 720x1280 output (1.5x the reference width) - both the "does it
# still look like a glitch" check (against real archival photos) and the
# "does it need recalibrating at real size" check (it did: unscaled
# values read as visibly too subtle at 720x1280). Horizontal-extent
# parameters (channel-shift, tear/jitter x-offsets) scale with output
# WIDTH; vertical-extent parameters (v3's vertical channel-shift, v2's
# band heights/y-positions) scale with output HEIGHT - each against the
# same 480x270 reference. Noise intensity has no real spatial meaning but
# was found empirically to need the same width-ratio scaling to keep
# pace with a stronger channel-shift, so it rides the width ratio too.
# These are starting points from one measured resolution (720x1280), the
# same epistemic status style_extensions.md §4.3 gives archival_montage's
# pacing numbers - recalibrate after a real viewing pass at any OTHER
# resolution this ends up shipping at (e.g. documentary_archival's
# 1280x720 landscape), don't assume the ratio holds untested.
_GLITCH_REFERENCE_WIDTH = 480
_GLITCH_REFERENCE_HEIGHT = 270


def _glitch_scale(settings: RenderSettings) -> tuple[float, float]:
    """(width_ratio, height_ratio) against the reference canvas §P-C2 was
    measured against - see the module-level comment above this."""
    return (
        settings.width / _GLITCH_REFERENCE_WIDTH,
        settings.height / _GLITCH_REFERENCE_HEIGHT,
    )


def _glitch_transition_filter(
    prev_label: str,
    cur_label: str,
    transition: TransitionType,
    *,
    duration_s: float,
    offset_s: float,
    out_label: str,
    settings: RenderSettings,
) -> str:
    """One of the three glitch transitions (§ above) - a plain `xfade=fade`
    crossfade with `rgbashift` (RGB channel-split) and `noise` (film
    grain) layered on top, active only during the crossfade window
    itself (`enable='between(t,offset,offset+duration)'`), so shots
    either side of the cut are untouched. `GLITCH_TEAR`/`GLITCH_JITTER`
    add one more stage each on top of `GLITCH_SHIFT`'s base. Real
    `duration_s`/`offset_s` from the caller's own D5 arithmetic - never
    the spike's hardcoded 1.5/0.5."""
    # Every intermediate label is namespaced off `out_label` (unique per
    # transition in the caller's run - "x{i}"/"vout") so two glitch
    # transitions in the same filter graph can never collide on a label,
    # the way fixed names like `[gx]` would.
    p = f"g{out_label}"
    wr, hr = _glitch_scale(settings)
    end_s = offset_s + duration_s
    window = f"between(t,{offset_s:.3f},{end_s:.3f})"
    fade = (
        f"[{prev_label}][{cur_label}]xfade=transition=fade:"
        f"duration={duration_s:.3f}:offset={offset_s:.3f}[{p}x]"
    )
    if transition is TransitionType.GLITCH_SHIFT:
        rh = max(round(14 * wr), 1)
        noise_base = max(round(26 * wr), 1)
        return ";".join(
            [
                fade,
                f"[{p}x]rgbashift=rh={rh}:bh=-{rh}:enable='{window}'[{p}r]",
                f"[{p}r]noise=alls={noise_base}:allf=t+u:enable='{window}'[{out_label}]",
            ]
        )

    if transition is TransitionType.GLITCH_JITTER:
        # `rv`/`bv` are a shift MAGNITUDE, not a frame position - scale
        # with the same width ratio as every other shift amount here, NOT
        # `hr` (reserved for true vertical POSITIONS - GLITCH_TEAR's band
        # y/height below): for a 720x1280 portrait frame against the
        # landscape-ish 480x270 reference, `hr` (~4.7x) is far more
        # extreme than `wr` (1.5x) purely because the reference canvas's
        # aspect differs from the target's, not because vertical shift
        # should genuinely be ~3x more aggressive than horizontal.
        #
        # ⚠ These base values are a still-open interim correction, not a
        # finished measurement (unlike GLITCH_SHIFT's 14/26, which a
        # second independent check cross-verified exactly). A blind ×1.5
        # of the original unscaled base (20/6/32 -> 30/9/48) was tried at
        # real 720x1280 against real archival photos and judged to
        # OVERSHOOT - heavier channel separation and tripled ghosting
        # than the unscaled reference, less legible. That check was
        # interrupted before finishing the correction; these three bases
        # (17/5/28, giving ~26/8/42 at the 1.5x ratio) are the
        # interrupted pass's own suggested interim range, not a value a
        # human has looked at and approved. Re-run the same real-photo
        # visual comparison GLITCH_SHIFT got before treating this as
        # settled.
        rh_j = max(round(17 * wr), 1)
        rv_j = max(round(5 * wr), 1)
        jitter_px = max(round(15 * wr), 1)
        noise_j = max(round(28 * wr), 1)
        return ";".join(
            [
                fade,
                f"[{p}x]crop={settings.width}:{settings.height}:"
                f"x='if({window},(random(3)*2-1)*{jitter_px},0)':y='0'[{p}c]",
                f"[{p}c]rgbashift=rh={rh_j}:bh=-{rh_j}:rv=-{rv_j}:bv={rv_j}:"
                f"enable='{window}'[{p}r]",
                f"[{p}r]noise=alls={noise_j}:allf=t+u:enable='{window}'[{out_label}]",
            ]
        )

    # GLITCH_TEAR - its own originally-spiked base values (rh=10, gv=6,
    # noise=18), distinct from GLITCH_SHIFT's (14/26) - kept separate
    # rather than sharing GLITCH_SHIFT's `rh`, matching what §P-C3's
    # cross-check against a second, independently-measured fix
    # (`_spike_glitch/real_res/v2_720x1280_fixed.fg`) actually verified:
    # rh=15, gv=9 at this 1.5x width ratio (10*1.5, 6*1.5) - every other
    # value below (band positions/heights/shifts, noise) already matched
    # that independent verification exactly before this fix.
    rh_t = max(round(10 * wr), 1)
    gv_t = max(round(6 * wr), 1)
    band1_h = max(round(34 * hr), 1)
    band1_y = round(60 * hr)
    band1_shift = max(round(90 * wr), 1)
    band2_h = max(round(22 * hr), 1)
    band2_y = round(170 * hr)
    band2_shift = max(round(130 * wr), 1)
    noise_t = max(round(18 * wr), 1)
    return ";".join(
        [
            fade,
            f"[{p}x]rgbashift=rh={rh_t}:bh=-{rh_t}:gv={gv_t}:enable='{window}'[{p}r]",
            f"[{p}r]split[{p}ba][{p}bb]",
            f"[{p}bb]crop=iw:{band1_h}:0:{band1_y}[{p}t1]",
            f"[{p}ba][{p}t1]overlay=x='if({window},(random(1)*2-1)*{band1_shift},0)':"
            f"y={band1_y}:enable='{window}'[{p}o1]",
            f"[{p}o1]split[{p}oa][{p}ob]",
            f"[{p}ob]crop=iw:{band2_h}:0:{band2_y}[{p}t2]",
            f"[{p}oa][{p}t2]overlay=x='if({window},(random(2)*2-1)*{band2_shift},0)':"
            f"y={band2_y}:enable='{window}'[{p}o2]",
            f"[{p}o2]noise=alls={noise_t}:allf=t+u:enable='{window}'[{out_label}]",
        ]
    )


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
        transition_type = run[i - 1].transition_out.type
        offset = max(cumulative - overlap, 0.0)
        out_label = f"x{i}" if i < len(run) - 1 else "vout"
        if transition_type in _GLITCH_TRANSITIONS:
            filters.append(
                _glitch_transition_filter(
                    prev_label,
                    labels[i],
                    transition_type,
                    duration_s=overlap,
                    offset_s=offset,
                    out_label=out_label,
                    settings=settings,
                )
            )
        else:
            filters.append(
                f"[{prev_label}][{labels[i]}]xfade=transition={transition_type.value}:"
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
    shot_secondary_images: dict[str, Path] | None = None,
    secondary_probes: dict[str, MediaProbe] | None = None,
    secondary_content_hashes: dict[str, str] | None = None,
    shot_focals: dict[str, tuple[float, float] | None] | None = None,
    shot_focal_fingerprints: dict[str, str] | None = None,
) -> None:
    run_stem = output_path.stem
    secondaries = shot_secondary_images or {}
    sec_probes = secondary_probes or {}
    sec_hashes = secondary_content_hashes or {}
    focals = shot_focals or {}
    focal_fps = shot_focal_fingerprints or {}

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
            secondary_src=secondaries.get(shot.id),
            secondary_probe=sec_probes.get(shot.id),
            secondary_asset_hash=sec_hashes.get(shot.id, ""),
            focal=focals.get(shot.id),
            focal_fingerprint=focal_fps.get(shot.id, ""),
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
    shot_secondary_images: dict[str, Path] | None = None,
    secondary_probes: dict[str, MediaProbe] | None = None,
    secondary_content_hashes: dict[str, str] | None = None,
    shot_focals: dict[str, tuple[float, float] | None] | None = None,
    shot_focal_fingerprints: dict[str, str] | None = None,
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
    hashes = shot_content_hashes or {
        shot.id: _file_content_hash(shot_images[shot.id]) for shot in run
    }
    secondaries = shot_secondary_images or {}
    sec_probes = secondary_probes or {}
    sec_hashes = secondary_content_hashes or {}
    focals = shot_focals or {}
    focal_fps = shot_focal_fingerprints or {}
    split_in_run = any(
        should_composite_split(
            shot.camera.movement,
            secondary_path=secondaries.get(shot.id),
            top_kind=media_probes[shot.id].kind,
            bot_kind=sec_probes[shot.id].kind if shot.id in sec_probes else None,
        )
        for shot in run
    )
    if len(run) >= 2 or split_in_run:
        if ffmpeg_version is None:
            from app.renderer.fingerprint import get_ffmpeg_version

            ffmpeg_version = await get_ffmpeg_version(settings.ffmpeg_binary)
        if len(run) == 1 and split_in_run:
            shot = run[0]
            await _encode_or_reuse_shot_stream(
                shot=shot,
                src=shot_images[shot.id],
                probe=media_probes[shot.id],
                settings=settings,
                dest=output_path,
                work_dir=work_dir,
                run_stem=output_path.stem,
                index=0,
                asset_hash=hashes[shot.id],
                ffmpeg_version=ffmpeg_version,
                secondary_src=secondaries.get(shot.id),
                secondary_probe=sec_probes.get(shot.id),
                secondary_asset_hash=sec_hashes.get(shot.id, ""),
                focal=focals.get(shot.id),
                focal_fingerprint=focal_fps.get(shot.id, ""),
            )
            return
        await _render_run_two_pass(
            run,
            shot_images,
            media_probes,
            settings,
            output_path,
            work_dir=work_dir,
            shot_content_hashes=hashes,
            ffmpeg_version=ffmpeg_version,
            shot_secondary_images=secondaries,
            secondary_probes=sec_probes,
            secondary_content_hashes=sec_hashes,
            shot_focals=focals,
            shot_focal_fingerprints=focal_fps,
        )
        return
    # M8 step 5: a Ken-Burns shot's frame count is computed HERE (the one
    # place duration-to-frames arithmetic lives for this module, D5's
    # "compute it once" discipline) and reused for zoompan's `d` and for
    # STATIC tpad's hold. A1 (2026-08-18): a MOTION shot never gets a
    # zoompan expression at all, regardless of what `shot.camera` says.
    frame_counts = [max(round(shot.duration_s * settings.fps), 1) for shot in run]
    ken_burns_aims = [
        _ken_burns_aim(media_probes[shot.id], settings, focals.get(shot.id))
        for shot in run
    ]
    ken_burns_exprs = [
        (
            build_zoompan_expression(
                shot.camera,
                frames=f,
                focal=aim[2],
                canvas_w=settings.width,
                canvas_h=settings.height,
                duration_s=shot.duration_s,
            )
            if media_probes[shot.id].kind is MediaKind.STILL
            else None
        )
        for shot, f, aim in zip(run, frame_counts, ken_burns_aims, strict=True)
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
        elif isinstance(expr, MovingCropExpression):
            filters.append(_ken_burns_pan_filter(i, settings, label, expr, frame_counts[i]))
        else:
            crop_x, crop_y, _residual = ken_burns_aims[i]
            filters.append(
                _ken_burns_filter(
                    i, settings, label, expr, frame_counts[i], crop_x=crop_x, crop_y=crop_y
                )
            )
        labels.append(label)

    if len(run) == 1:
        vout = labels[0]
    else:
        # (Found while wiring Feature C, style_extensions.md §5/P-C3):
        # this `else` branch is unreachable in practice - the caller,
        # `_render_run`, returns early via `_render_run_two_pass` (->
        # `_xfade_shot_streams`, the SAME `_glitch_transition_filter`
        # call as here) for every `len(run) >= 2`, so control only ever
        # reaches this point with `len(run) == 1`. Kept in sync with
        # `_xfade_shot_streams` anyway (both call the same shared
        # `_glitch_transition_filter`/`_GLITCH_TRANSITIONS`, so there is
        # no logic to drift) rather than deleted, in case a future
        # refactor ever does reach it directly.
        cumulative = run[0].duration_s
        prev_label = labels[0]
        for i in range(1, len(run)):
            overlap = run[i - 1].transition_out.duration_s
            transition_type = run[i - 1].transition_out.type
            offset = max(cumulative - overlap, 0.0)
            out_label = f"x{i}"
            if transition_type in _GLITCH_TRANSITIONS:
                filters.append(
                    _glitch_transition_filter(
                        prev_label,
                        labels[i],
                        transition_type,
                        duration_s=overlap,
                        offset_s=offset,
                        out_label=out_label,
                        settings=settings,
                    )
                )
            else:
                filters.append(
                    f"[{prev_label}][{labels[i]}]xfade=transition={transition_type.value}:"
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
    shot_secondary_images: dict[str, Path] | None = None,
    secondary_probes: dict[str, MediaProbe] | None = None,
    secondary_content_hashes: dict[str, str] | None = None,
    shot_focals: dict[str, tuple[float, float] | None] | None = None,
    shot_focal_fingerprints: dict[str, str] | None = None,
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
        secondary_content_hashes=secondary_content_hashes,
        shot_focal=shot_focal_fingerprints,
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
        shot_secondary_images=shot_secondary_images,
        secondary_probes=secondary_probes,
        secondary_content_hashes=secondary_content_hashes,
        shot_focals=shot_focals,
        shot_focal_fingerprints=shot_focal_fingerprints,
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
    shot_secondary_images: dict[str, Path] | None = None,
    shot_focals: dict[str, tuple[float, float] | None] | None = None,
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

    resolved_secondary: dict[str, Path] = {}
    secondary_probes: dict[str, MediaProbe] = {}
    for shot_id, path in (shot_secondary_images or {}).items():
        probe = await probe_media(path, ffprobe_binary=settings.ffprobe_binary)
        if probe.kind is MediaKind.MOTION:
            continue
        secondary_probes[shot_id] = probe
        resolved_secondary[shot_id] = await ensure_still_image(
            path, shot_id=f"{shot_id}__split", work_dir=work_dir, settings=settings
        )

    runs = group_into_runs(shots)

    # Lazy: fingerprint.py imports RenderSettings from this module.
    from app.renderer.fingerprint import get_ffmpeg_version

    ffmpeg_version = await get_ffmpeg_version(settings.ffmpeg_binary)
    shot_content_hashes = {shot.id: _file_content_hash(resolved_images[shot.id]) for shot in shots}
    secondary_content_hashes = {
        shot_id: _file_content_hash(path) for shot_id, path in resolved_secondary.items()
    }
    # OQ-2: focals are resolved once in RenderStep and threaded in (RV2).
    # Fingerprint strings use "" when unresolved so a later sidecar cannot
    # cache-HIT a centre-aimed encode.
    from app.assets.focal import format_focal_fingerprint

    focals = shot_focals or {}
    focal_fingerprints = {
        shot.id: format_focal_fingerprint(focals.get(shot.id)) for shot in shots
    }

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
            shot_secondary_images=resolved_secondary,
            secondary_probes=secondary_probes,
            secondary_content_hashes=secondary_content_hashes,
            shot_focals=focals,
            shot_focal_fingerprints=focal_fingerprints,
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
