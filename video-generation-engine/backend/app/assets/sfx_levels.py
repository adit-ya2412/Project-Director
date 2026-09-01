"""C3c/C3d SFX level math (analysis.md, decisions 5b/5c).

Two pure functions + one ffmpeg probe:

- `gain_to_target_db` / `effective_gain_db`: C3c's per-clip loudness
  normalization. A clip whose measured peak is KNOWN gets exactly the
  gain that lands its peak on `target_db`; a clip with NO measurement
  (old timelines, DRY_RUN fakes, a failed probe) falls back to the flat
  `settings.sfx_gain_db` - never None-gain, never a crash. A per-kind
  offset (decision: `sfx_{kind}_gain_db`, default absent) rides on top
  of either path.
- `diegetic_effective_gain_db`: A11 (long_form_direction.md, 2026-09-01).
  DIEGETIC-only replacement for peak normalization: matches a clip's
  measured INTEGRATED LOUDNESS (LUFS) onto a target instead of its peak,
  since a diegetic cue's crest (25-27dB) makes peak-matching leave its
  audible body tens of dB under a music bed. `effective_gain_db` above
  is reused unchanged as the fallback path (unmeasured clip, or a clip
  too short for integrated loudness to mean anything) and is still the
  ONLY path for WHOOSH/STINGER/TRANSITION - this module makes no change
  to those three kinds.
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


def diegetic_effective_gain_db(
    loudness_lufs: float | None,
    peak_dbfs: float | None,
    duration_s: float | None,
    *,
    loudness_target_lufs: float,
    peak_target_db: float,
    fallback_db: float,
    min_loudness_duration_s: float,
    kind_offset_db: float | None = None,
) -> float:
    """DIEGETIC-only gain decision (long_form_direction.md A11, 2026-09-01).

    Peak normalisation measures the wrong thing for a diegetic cue: these
    clips can carry 25-27dB of crest (a bell's decay, a Geiger click
    against near-silence), so matching the single loudest instant to a
    target leaves the audible BODY of the sound tens of dB below a music
    bed matched the same way (a bed's own crest is ~10-12dB). Measured on
    the two real cues that motivated this: at a -18dB offset, the Geiger
    counter's peak/mean landed -38.0/-64.9 dBFS and the church bell's
    -38.0/-63.3 dBFS - "inaudible" understates a -63dBFS mean under a
    -14dBFS bed. Loudness (integrated LUFS) answers "how much sound
    overall" instead of "how tall is the spike", so one target lands a
    click-heavy cue (Geiger) and a continuous one (wind, machinery hum) at
    a comparable PERCEIVED level.

    Falls back to the exact peak-based path the three structural kinds
    use (`effective_gain_db`, byte-identical call) when: no loudness
    measurement exists yet (an old timeline, a failed probe, DRY_RUN), or
    the clip is shorter than `min_loudness_duration_s` - below that it
    reads as punctuation (a single tap, a doorbell) rather than ambience,
    and ITU BS.1770 integrated loudness needs several 400ms gating blocks
    to mean anything; a sub-floor measurement is noisy enough that
    loudness-matching it against a long clip can send the gain the wrong
    way. The per-kind offset (`sfx_diegetic_gain_db`) rides on top of
    either path, exactly as it does for the three structural kinds -
    unchanged by which path was taken.
    """
    long_enough = (duration_s or 0.0) >= min_loudness_duration_s
    if loudness_lufs is not None and long_enough:
        base = gain_to_target_db(loudness_lufs, loudness_target_lufs)
    else:
        base = effective_gain_db(peak_dbfs, target_db=peak_target_db, fallback_db=fallback_db)
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
