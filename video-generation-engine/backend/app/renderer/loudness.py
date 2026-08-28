"""OQ-1a: final-mix loudness target (two-pass linear loudnorm).

Applied AFTER music and SFX on the finished mux. Video is stream-copied
(`-c:v copy`); audio is re-encoded once under a measured linear gain so
integrated loudness lands near the configured LUFS target with a true-
peak ceiling.

`linear=true` is a request, not a guarantee (RV-Q6): ffmpeg is silent
when it falls back to dynamic. Pass 2 sets `print_format=json` so the
reported `normalization_type` is logged. Dynamic is rejected on
*creative* grounds (time-varying gain would squash OQ-1b bed swells),
not duration — both modes were measured sample-exact (§12.6). Pin
`-ar` to the input rate so a dynamic fallback cannot emit 96 kHz AAC
(RV-Q7).

Never fails the render (§2.6): unmeasurable or ≥ 0 LUFS audio is copied
through unchanged and logged (RV-Q8). Does not call `run_ffmpeg` (that
raises PermanentError).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from app.core.logging import get_logger
from app.renderer.slideshow import RenderSettings

logger = get_logger(__name__)

# Streaming-friendly LRA; not a separate config knob for OQ-1a.
# Fingerprinted as `loudness_lra` so a constant change cannot cache-HIT.
DEFAULT_LRA = 11.0

_LOUDNORM_JSON_RE = re.compile(
    r"\{\s*\"input_i\"\s*:.*?\"target_offset\"\s*:\s*\"[^\"]+\"\s*\}",
    re.DOTALL,
)


def _loudnorm_json_blob(stderr: str) -> dict | None:
    match = _LOUDNORM_JSON_RE.search(stderr)
    if match is None:
        start = stderr.rfind("{")
        end = stderr.rfind("}")
        if start < 0 or end <= start:
            return None
        blob = stderr[start : end + 1]
    else:
        blob = match.group(0)
    try:
        raw = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def parse_loudnorm_measurement(stderr: str) -> dict[str, float] | None:
    """Extract pass-1 loudnorm JSON fields from ffmpeg stderr.

    Returns measured_I / measured_TP / measured_LRA / measured_thresh /
    offset, or None when the JSON block is missing or unparseable.
    """
    raw = _loudnorm_json_blob(stderr)
    if raw is None:
        return None
    try:
        return {
            "measured_I": float(raw["input_i"]),
            "measured_TP": float(raw["input_tp"]),
            "measured_LRA": float(raw["input_lra"]),
            "measured_thresh": float(raw["input_thresh"]),
            "offset": float(raw["target_offset"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def parse_loudnorm_normalization_type(stderr: str) -> str | None:
    """Pass-2 `print_format=json` reports linear vs dynamic (RV-Q6)."""
    raw = _loudnorm_json_blob(stderr)
    if raw is None:
        return None
    value = raw.get("normalization_type")
    if not isinstance(value, str) or not value:
        return None
    return value.lower()


async def _probe_audio_sample_rate(path: Path, ffprobe_binary: str) -> int | None:
    """Input audio sample rate, so pass 2 can pin `-ar` (RV-Q7)."""
    process = await asyncio.create_subprocess_exec(
        ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        rate = int(float(text.splitlines()[0]))
    except ValueError:
        return None
    return rate if rate > 0 else None


async def _has_audio_stream(path: Path, ffprobe_binary: str) -> bool:
    process = await asyncio.create_subprocess_exec(
        ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    return bool(stdout.strip())


async def _run_ffmpeg_capture(args: list[str]) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr_b = await process.communicate()
    stderr = stderr_b.decode("utf-8", errors="replace")
    return process.returncode or 0, stderr


def _copy_through(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    return dest


def _loudnorm_filter(
    *,
    target_lufs: float,
    true_peak_db: float,
    measured: dict[str, float] | None,
    print_format: str | None,
) -> str:
    parts = [
        f"loudnorm=I={target_lufs}:TP={true_peak_db}:LRA={DEFAULT_LRA}",
    ]
    if measured is not None:
        parts.append(
            f"measured_I={measured['measured_I']}:"
            f"measured_TP={measured['measured_TP']}:"
            f"measured_LRA={measured['measured_LRA']}:"
            f"measured_thresh={measured['measured_thresh']}:"
            f"offset={measured['offset']}:"
            f"linear=true"
        )
    if print_format is not None:
        parts.append(f"print_format={print_format}")
    return ":".join(parts)


async def apply_loudness_target(
    video_path: Path,
    output_path: Path,
    settings: RenderSettings,
    *,
    target_lufs: float,
    true_peak_db: float,
) -> Path:
    """Two-pass linear loudnorm on ``video_path`` -> ``output_path``.

    On any failure (no audio, missing pass-1 JSON, ffmpeg non-zero): log a
    warning with the error tail, copy bytes through unchanged, return
    ``output_path``. Never raises for loudness failure.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not await _has_audio_stream(video_path, settings.ffprobe_binary):
        logger.warning(
            "loudness pass skipped: no audio stream in %s; copying through unnormalized",
            video_path,
        )
        return _copy_through(video_path, output_path)

    measure_filter = _loudnorm_filter(
        target_lufs=target_lufs,
        true_peak_db=true_peak_db,
        measured=None,
        print_format="json",
    )
    pass1_args = [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-y",
        "-i",
        str(video_path),
        "-af",
        measure_filter,
        "-f",
        "null",
        "-",
    ]
    code1, stderr1 = await _run_ffmpeg_capture(pass1_args)
    measured = parse_loudnorm_measurement(stderr1)
    if measured is None:
        tail = stderr1[-4000:] if stderr1 else f"ffmpeg exit {code1}"
        logger.warning(
            "loudness pass-1 measurement failed (exit %s); copying through unnormalized. tail=%s",
            code1,
            tail,
        )
        return _copy_through(video_path, output_path)

    if measured["measured_I"] >= 0.0:
        # RV-Q8: loudnorm rejects measured_I outside [-99, 0]. The mixes
        # most in need of a target are exactly the ones that would abort.
        logger.warning(
            "loudness skipped: mix measured_I=%s LUFS is >= 0; "
            "loudnorm cannot apply (RV-Q8); copying through unnormalized",
            measured["measured_I"],
        )
        return _copy_through(video_path, output_path)

    # Stage pass-2 into a sibling temp so a failed encode never leaves a
    # half-normalized file at output_path (same staging rule as pre_sfx).
    staged = output_path.parent / f".loudnorm_{output_path.stem}{output_path.suffix}"
    if staged.resolve() == video_path.resolve() or staged.resolve() == output_path.resolve():
        staged = output_path.parent / f".loudnorm_tmp_{output_path.name}"

    apply_filter = _loudnorm_filter(
        target_lufs=target_lufs,
        true_peak_db=true_peak_db,
        measured=measured,
        print_format="json",
    )
    sample_rate = await _probe_audio_sample_rate(video_path, settings.ffprobe_binary)
    pass2_args = [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-y",
        "-i",
        str(video_path),
        "-af",
        apply_filter,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
    ]
    if sample_rate is not None:
        pass2_args.extend(["-ar", str(sample_rate)])
    pass2_args.extend(
        [
            "-fflags",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            "-movflags",
            "+faststart",
            str(staged),
        ]
    )
    code2, stderr2 = await _run_ffmpeg_capture(pass2_args)
    mode = parse_loudnorm_normalization_type(stderr2)
    if mode is not None:
        logger.info(
            "loudness pass-2 normalization_type=%s (linear=true is a request, not a guarantee)",
            mode,
        )
        if mode != "linear":
            logger.warning(
                "loudness pass-2 ran %s, not linear — bed swells may be compressed (RV-Q6)",
                mode,
            )
    if code2 != 0 or not staged.is_file():
        tail = stderr2[-4000:] if stderr2 else f"ffmpeg exit {code2}"
        logger.warning(
            "loudness pass-2 encode failed (exit %s); copying through unnormalized. tail=%s",
            code2,
            tail,
        )
        if staged.exists():
            staged.unlink(missing_ok=True)
        return _copy_through(video_path, output_path)

    if output_path.exists():
        output_path.unlink()
    staged.replace(output_path)
    return output_path
