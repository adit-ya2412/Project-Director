"""Strip a source video's own baked-in pillarbox/letterbox bars, once, at
ingest (docs/plans/baked_in_letterbox.md §4).

Video sibling of `app/assets/substrate_crop.py`. That module's thesis -
"the fix is not linguistic: ... crop it back, in code, before anything is
persisted" - applies unchanged here, to a different failure: some video
files arrive with black bars burned into their actual pixels (a vertical
phone clip exported or downloaded into a landscape container, 656px of
pure black down each side of a 1920x1080 frame whose real picture is a
608x1080 box in the centre). `app/renderer/slideshow.py` contain-fits the
WHOLE bordered frame into the output canvas and pads it again, so the
picture ends up as a small box marooned inside a black frame ("tunnel
vision" - measured on a real project, 4 of 21 assets, ~68.4% of the frame
dead black each; see the plan's §1). The renderer cannot tell "black
pixels that are a bar" from "black pixels that are night sky" - nothing
downstream of ingest can. The only place that question can be answered is
once, here, against the source file itself, before its bytes are ever
hashed (content-addressable storage means a byte-for-byte correction after
the hash is taken requires re-hashing every persisted reference to it -
see the plan's §2 for the manual repair this function exists to make
unnecessary).

`strip_baked_in_letterbox` is shaped like `fit_upload_to_canvas`: it
always returns bytes, and "nothing to do" returns the input bytes
unchanged. Its failure contract is the opposite of `substrate_crop.py`'s
on purpose: that module raises loudly because its precondition (an
oversized delivered image) is the CALLER's to satisfy, so a violation is a
caller bug worth surfacing. This function's job is opportunistic cleanup
of arbitrary third-party video of unknown quality, where "could not tell"
is an ordinary outcome - a human's upload must never fail because
`cropdetect` had a bad day. Every failure path (subprocess failure,
timeout, unparseable output, a guard-band rejection) returns the input
bytes unchanged and logs why. A missed border is a cosmetic bug a later
re-run can still fix; a wrongly cropped video is destroyed picture,
because this runs before the original bytes are ever persisted anywhere -
every doubt below resolves to "leave it alone."
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path

from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.renderer.slideshow import run_ffmpeg

logger = get_logger(__name__)

# --- Sampling -----------------------------------------------------------

# Sample cropdetect at these fractions of total duration rather than
# decoding the whole clip - 5 points spread across the clip, never at the
# very first/last instant (a fade-to-black frame at 0.0 or 1.0 would read
# as "the whole frame is a bar"). §1 measured that a real baked-in bar is
# identical in EVERY sampled frame for 3 of 4 real cases, so 5 samples is
# already generous for the common case; it exists mainly to catch the 4th,
# which varied under 2% of frame height at one transition.
_SAMPLE_FRACTIONS = (0.1, 0.3, 0.5, 0.7, 0.9)
# Decode this many seconds per sample point rather than a single frame -
# cropdetect accumulates its answer across frames it has seen and only
# converges once given more than one (plan §4 step 2). This is a CEILING,
# not the window actually used - see `_sample_window_s_for`. Real shots in
# this app run 1.5-8s; at this ceiling with 5 samples spaced across
# `_SAMPLE_FRACTIONS` (20% of duration apart), any clip under ~2.5s has
# windows that OVERLAP their neighbour. An overlapping window can straddle
# both positions of a moving dark region and report their union as one
# sample's own box, which INFLATES `max_sample_area` - that is the wrong
# direction, because the cross-sample stability guard compares the
# combined union against `max_sample_area` and becomes LESS likely to fire
# the shorter that gap looks, i.e. more likely to crop.
_SAMPLE_WINDOW_S = 0.5
# Floor beneath which a sample window stops being trustworthy at all -
# cropdetect needs several frames to move past its own first (least
# converged) reading, and at a plausible worst-case frame rate (~24fps)
# 0.15s is still ~3-4 frames. Below this the window shrinks the sample
# into near-uselessness for a marginal gain in inter-sample spacing.
_MIN_SAMPLE_WINDOW_S = 0.15
# Generous relative to how little work each subprocess does (a fraction of
# a second of decode, or a metadata-only probe) - a real timeout here means
# something is actually stuck, not merely slow.
_SUBPROCESS_TIMEOUT_S = 20.0

_CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")

# --- The guard band (plan §4) --------------------------------------------
#
# Every constant below trades in one direction only: when in doubt, refuse
# to crop. A missed border costs nothing but a later re-run; a wrong crop
# destroys picture, because this runs before the original bytes are ever
# persisted anywhere.

# Floor: below 2% of frame area, what cropdetect found is encoder edge
# noise or a one-pixel mastering artifact, not a bar worth a re-encode.
# Real cases (§1) removed 68.3-68.4% - nowhere near this floor.
_MIN_REMOVED_FRACTION = 0.02

# Ceiling: 88%, deliberately NOT 75%. A 9:16 picture inside a 16:9
# container occupies (9/16)/(16/9) = 81/256 ≈ 31.64% of the frame by
# construction, so a CORRECT detection on the single most common real
# case removes 1 - 0.3164 ≈ 68.36% - a 75% ceiling would leave almost no
# headroom above that ordinary case for a slightly wider bar or a
# marginally noisy read. 88% still catches the failure this ceiling is
# actually for: cropdetect on a near-black night shot returning a small
# bright island, which scores 95%+.
_MAX_REMOVED_FRACTION = 0.88

# Aspect sanity on the SURVIVING content box - a generous band around real
# video shapes so this only rejects a truly implausible sliver. A tall
# modern phone clip (9:19.5) is ≈0.46; wide cinematic content (21:9) is
# ≈2.33. The floor/ceiling here sit well outside both.
_MIN_CONTENT_ASPECT_RATIO = 0.3
_MAX_CONTENT_ASPECT_RATIO = 3.0

# Absolute pixel floor on the surviving content box, independent of the
# fractional guards above - rejects a degenerate sliver outright regardless
# of how it scores on aspect or area.
_MIN_CONTENT_DIM_PX = 64

# Cross-sample stability: if the UNION box's area is more than 10% larger
# than the largest individual sample's own area, the dark region MOVED
# between samples rather than sitting still - that is content (a shadow, a
# subject, a scene change), not a bar. §1's measurement is what justifies
# leaning on this: real bars were pixel-identical across the entire
# duration in 3 of 4 files, and the 4th varied under 2% of frame height at
# one transition - 10% leaves a wide margin above that ordinary jitter
# while still catching genuine movement (see
# `test_skips_when_the_dark_region_moves_between_samples`, which
# constructs a case where the union area grows far past this ceiling).
_MAX_UNION_GROWTH_FRACTION = 0.10

# The crop pass itself (plan §4): matches the 2026-09-13 hand-fix used on
# all four real files, checked frame-by-frame against the originals and
# visually indistinguishable.
_CROP_CRF = "16"
_CROP_PRESET = "medium"


async def strip_baked_in_letterbox(
    video_bytes: bytes,
    *,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> bytes:
    """Detect and remove a baked-in pillarbox/letterbox border from
    `video_bytes`, returning corrected bytes. Returns `video_bytes`
    unchanged whenever there is nothing to do, cropdetect could not agree,
    or anything at all went wrong - see the module docstring for why this
    never raises.

    Bare-string binary defaults with `settings.*` threaded from the call
    site, matching `validate_and_identify_video(content,
    ffprobe_binary=settings.ffprobe_binary)` (`app/assets/validation.py`).
    """
    if not video_bytes:
        return video_bytes

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = Path(tmp.name)

    out_path: Path | None = None
    try:
        probe = await _probe_dimensions(tmp_path, ffprobe_binary)
        if probe is None:
            logger.info("letterbox_crop.no_op", extra={"reason": "probe_failed"})
            return video_bytes
        frame_w, frame_h, duration_s = probe

        window_s = _sample_window_s_for(duration_s)
        samples: list[tuple[int, int, int, int]] = []
        for fraction in _SAMPLE_FRACTIONS:
            timestamp_s = max(0.0, fraction * duration_s)
            box = await _sample_cropdetect(tmp_path, ffmpeg_binary, timestamp_s, window_s)
            if box is not None:
                samples.append(box)

        if not samples:
            logger.info("letterbox_crop.no_op", extra={"reason": "no_samples"})
            return video_bytes

        x1 = min(box[0] for box in samples)
        y1 = min(box[1] for box in samples)
        x2 = max(box[2] for box in samples)
        y2 = max(box[3] for box in samples)
        w, h, x, y = _snap_even_box(x1, y1, x2, y2)

        if w < 1 or h < 1:
            logger.info("letterbox_crop.no_op", extra={"reason": "degenerate_union"})
            return video_bytes

        frame_area = frame_w * frame_h
        removed_fraction = 1.0 - (w * h) / frame_area
        max_sample_area = max((bx2 - bx1) * (by2 - by1) for bx1, by1, bx2, by2 in samples)
        union_area = w * h
        aspect_ratio = w / h

        reason = None
        if removed_fraction < _MIN_REMOVED_FRACTION:
            reason = "below_floor"
        elif removed_fraction > _MAX_REMOVED_FRACTION:
            reason = "above_ceiling"
        elif not (_MIN_CONTENT_ASPECT_RATIO <= aspect_ratio <= _MAX_CONTENT_ASPECT_RATIO):
            reason = "implausible_aspect"
        elif w < _MIN_CONTENT_DIM_PX or h < _MIN_CONTENT_DIM_PX:
            reason = "below_absolute_floor"
        elif union_area > max_sample_area * (1.0 + _MAX_UNION_GROWTH_FRACTION):
            reason = "unstable_across_samples"

        log_extra = {
            "box": f"{w}:{h}:{x}:{y}",
            "removed_fraction": round(removed_fraction, 4),
            "sample_count": len(samples),
        }
        if reason is not None:
            logger.info("letterbox_crop.no_op", extra={**log_extra, "reason": reason})
            return video_bytes

        out_path = tmp_path.with_name(f"{tmp_path.stem}_cropped.mp4")
        args = [
            ffmpeg_binary,
            "-y",
            "-i",
            str(tmp_path),
            "-vf",
            f"crop={w}:{h}:{x}:{y}",
            "-c:v",
            "libx264",
            "-crf",
            _CROP_CRF,
            "-preset",
            _CROP_PRESET,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(out_path),
        ]
        try:
            await run_ffmpeg(args)
        except PermanentError as exc:
            logger.warning(
                "letterbox_crop.encode_failed", extra={**log_extra, "error": str(exc)[:300]}
            )
            return video_bytes

        cropped_bytes = out_path.read_bytes()
        logger.info("letterbox_crop.cropped", extra=log_extra)
        return cropped_bytes
    except Exception:  # noqa: BLE001 - never raise (module docstring): a
        # human's upload must never fail because cropdetect had a bad day.
        logger.exception("letterbox_crop.unexpected_failure")
        return video_bytes
    finally:
        tmp_path.unlink(missing_ok=True)
        if out_path is not None:
            out_path.unlink(missing_ok=True)


async def _probe_dimensions(
    tmp_path: Path, ffprobe_binary: str
) -> tuple[int, int, float] | None:
    """`(width, height, duration_s)` for the video stream at `tmp_path`, or
    `None` for anything that is not cleanly readable. Copies the tempfile
    idiom `validate_and_identify_video` established
    (`app/assets/validation.py:103-106`) for the same reason it did: an
    arbitrary bag of bytes needs a real file on disk before ffprobe can
    read it. Unlike that function this never raises - see the module
    docstring."""
    args = [
        ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration:format=duration",
        "-of",
        "json",
        str(tmp_path),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(), timeout=_SUBPROCESS_TIMEOUT_S
        )
    except (OSError, asyncio.TimeoutError):
        return None
    if process.returncode != 0:
        return None

    try:
        data = json.loads(stdout.decode())
        streams = data.get("streams") or []
        if not streams:
            return None
        stream = streams[0]
        width, height = stream.get("width"), stream.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            return None
        raw_duration = stream.get("duration") or (data.get("format") or {}).get("duration")
        duration = float(raw_duration)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if width < 2 or height < 2 or duration <= 0:
        return None
    return width, height, duration


def _sample_window_s_for(duration_s: float) -> float:
    """Scale the per-sample decode window down for a short clip, so
    adjacent samples never overlap (module comment beside `_SAMPLE_WINDOW_S`
    for the false-positive mechanism this avoids). `duration_s / 10` keeps
    each window comfortably inside the ~20%-of-duration gap between
    `_SAMPLE_FRACTIONS`, with `_SAMPLE_WINDOW_S` as a ceiling (no reason to
    decode more than that even on a long clip) and `_MIN_SAMPLE_WINDOW_S`
    as a floor (a sample must still see several frames to converge)."""
    return max(_MIN_SAMPLE_WINDOW_S, min(_SAMPLE_WINDOW_S, duration_s / 10.0))


async def _sample_cropdetect(
    tmp_path: Path, ffmpeg_binary: str, timestamp_s: float, window_s: float
) -> tuple[int, int, int, int] | None:
    """Run `cropdetect` over `window_s` seconds starting at `timestamp_s`,
    and return the LAST `crop=w:h:x:y` box it reported as
    `(x1, y1, x2, y2)` - cropdetect accumulates its answer across frames,
    so the last line is its most-converged one (plan §4 step 2). `None` on
    any subprocess trouble or if no `crop=` line was ever emitted."""
    args = [
        ffmpeg_binary,
        "-nostdin",
        "-ss",
        f"{timestamp_s:.3f}",
        "-i",
        str(tmp_path),
        "-t",
        f"{window_s:.3f}",
        "-an",
        "-vf",
        "cropdetect=round=2",
        "-f",
        "null",
        "-",
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=_SUBPROCESS_TIMEOUT_S
        )
    except (OSError, asyncio.TimeoutError):
        return None
    if process.returncode != 0:
        return None

    matches = _CROP_RE.findall(stderr.decode(errors="replace"))
    if not matches:
        return None
    w, h, x, y = (int(value) for value in matches[-1])
    return (x, y, x + w, y + h)


def _snap_even_box(x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int, int]:
    """Re-round a UNION box (min/max across samples) to even `w`/`h`/`x`/`y`
    - h264 requires even width and height, and `cropdetect=round=2` only
    rounds each SAMPLE individually, so a union combined from several
    already-even boxes is re-snapped here defensively rather than assumed
    to still be even (plan §4 step 3). Every edge only ever moves INWARD,
    into the content box `(x1, y1, x2, y2)` - `x1`/`y1` round UP and
    `x2`/`y2` round DOWN, each by at most one pixel - so this never retains
    a bar pixel that was outside the detected content. (An earlier version
    rounded `x1`/`y1` down, which kept one bar pixel on an odd edge while
    still computing `w`/`h` from the pre-round `x1`/`y1` - dropping a real
    content pixel on the FAR edge instead. `cropdetect=round=2` makes every
    sample already even in practice, so an odd union edge is near-
    unreachable, but the invariant below is what the docstring promises
    either way: shrink into content, never keep a bar.)

    Returns `(w, h, x, y)`, the `crop=w:h:x:y` filter's own argument order.
    """
    x1_even = x1 + (x1 % 2)
    y1_even = y1 + (y1 % 2)
    x2_even = x2 - (x2 % 2)
    y2_even = y2 - (y2 % 2)
    w = x2_even - x1_even
    h = y2_even - y1_even
    return w, h, x1_even, y1_even
