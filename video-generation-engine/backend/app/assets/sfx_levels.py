"""C3c/C3d SFX level math (analysis.md, decisions 5b/5c).

Two pure functions + one ffmpeg probe:

- `gain_to_target_db` / `effective_gain_db`: C3c's per-clip loudness
  normalization. A clip whose measured peak is KNOWN gets exactly the
  gain that lands its peak on `target_db`; a clip with NO measurement
  (old timelines, DRY_RUN fakes, a failed probe) falls back to the flat
  `settings.sfx_gain_db` - never None-gain, never a crash. A per-kind
  offset (decision: `sfx_{kind}_gain_db`, default absent) rides on top
  of either path.
- `end_aligned_trim_start`: C3d. When a clip is longer than the trim
  ceiling, trim from the END (`start = duration - max`) so the impact
  transient survives; when it fits, or its length is unknown, no shift.

The probe shells out to ffmpeg's `volumedetect` and NEVER raises: any
failure returns `None`, which callers store as "unmeasured" and the gain
math treats as fallback. Measurement failing must degrade to yesterday's
behaviour, not fail a selection or an upload.
"""

import asyncio
import re
from pathlib import Path

_MAX_VOLUME_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def gain_to_target_db(peak_dbfs: float, target_db: float) -> float:
    """Gain (dB) that moves a measured peak onto the target: a clip
    peaking at −1.9 dB against a −8.0 target needs −6.1 dB."""
    return target_db - peak_dbfs


def effective_gain_db(
    peak_dbfs: float | None,
    *,
    target_db: float,
    fallback_db: float,
    kind_offset_db: float | None = None,
) -> float:
    """The per-clip volume decision. Known peak → normalize onto
    `target_db`; unknown → the legacy flat `fallback_db`
    (`settings.sfx_gain_db`). The optional per-kind offset applies in dB
    on top of either path (decision: `sfx_{kind}_gain_db`)."""
    base = gain_to_target_db(peak_dbfs, target_db) if peak_dbfs is not None else fallback_db
    return base if kind_offset_db is None else base + kind_offset_db


def end_aligned_trim_start(duration_s: float | None, max_clip_s: float) -> float:
    """Where `atrim` should START so the clip's tail (where impact
    transients live) is what survives the `max_clip_s` ceiling. Zero when
    the clip fits, its length is unknown (never invent an offset from no
    data), or there is no ceiling to enforce."""
    if duration_s is None or duration_s <= 0 or max_clip_s <= 0:
        return 0.0
    return max(duration_s - max_clip_s, 0.0)


async def measure_peak_dbfs(path: Path, *, ffmpeg_binary: str = "ffmpeg") -> float | None:
    """Peak loudness of an audio file in dBFS via `volumedetect`, or
    `None` when anything at all goes wrong (missing file, undecodable
    bytes, unexpected output). Callers store None and fall back - see
    this module's docstring."""
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg_binary,
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        match = _MAX_VOLUME_RE.search(stderr.decode(errors="replace"))
        if process.returncode != 0 or match is None:
            return None
        return float(match.group(1))
    except Exception:  # noqa: BLE001 - measurement must never be fatal
        return None
