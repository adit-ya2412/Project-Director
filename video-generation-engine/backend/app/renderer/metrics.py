"""Read-only render metrics report.

Read-only reporting tool; `build_render_metrics_report` must not be imported
from the render path. The ebur128 stderr parser lives in `ebur128.py` so
OQ-1c can reuse it without pulling this module into encode. ffmpeg here is
analysis-only — never mutates the timeline, never writes the DB.
"""

from __future__ import annotations

import contextlib
import re
import statistics
import subprocess
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.renderer.captions import MAX_CHARS_PER_CUE, MAX_CUE_DURATION_S
from app.renderer.ebur128 import parse_ebur128_summary
from app.schemas.timeline import CameraMovement, Shot, Timeline, TransitionType
from app.timeline.duration import compute_shot_start_times

logger = get_logger(__name__)

SILENCE_GAP_THRESHOLD_S = 0.5

_BLACKDETECT_RE = re.compile(
    r"black_start:\s*([-+]?\d+(?:\.\d+)?)\s+"
    r"black_end:\s*([-+]?\d+(?:\.\d+)?)\s+"
    r"black_duration:\s*([-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_FREEZE_START_RE = re.compile(
    r"(?:lavfi\.freezedetect\.)?freeze_start:\s*([-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_FREEZE_END_RE = re.compile(
    r"(?:lavfi\.freezedetect\.)?freeze_end:\s*([-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_FREEZE_DURATION_RE = re.compile(
    r"(?:lavfi\.freezedetect\.)?freeze_duration:\s*([-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_FFPROBE_DURATION_RE = re.compile(
    r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
)


def build_render_metrics_report(
    timeline: Timeline,
    video_path: Path | None = None,
    *,
    asset_ids: Mapping[str, str] | None = None,
    scene_narration_paths: Sequence[Path] | None = None,
    alignment_by_scene: Sequence[Mapping[str, Any]] | None = None,
    caption_cues: Sequence[Mapping[str, Any]] | None = None,
    ffmpeg_binary: str | None = None,
) -> dict[str, Any]:
    """Emit a JSON-serialisable metrics blob for a finished render.

    Optional sections that lack inputs are present as null with an
    ``unavailable_reason`` — keys are never omitted.
    """
    ffmpeg = ffmpeg_binary or settings.ffmpeg_binary
    shots = timeline.all_shots()

    mux: dict[str, float] | None = None
    mux_reason: str | None = None
    near_black: list[dict[str, Any]] | None = None
    frozen: list[dict[str, Any]] | None = None
    defects_reason: str | None = None

    if video_path is None:
        mux_reason = "video_path not provided"
        defects_reason = "video_path not provided"
    else:
        mux, mux_reason, near_black, frozen, defects_reason = _analyse_video(
            video_path, ffmpeg
        )

    audio = _audio_metrics_from_parts(
        timeline,
        mux=mux,
        mux_reason=mux_reason,
        scene_narration_paths=scene_narration_paths,
        ffmpeg_binary=ffmpeg,
    )
    if near_black is not None:
        near_black = _annotate_time_ranges(near_black, shots)
    if frozen is not None:
        frozen = _annotate_time_ranges(frozen, shots)
    video_defects = {
        "near_black": near_black,
        "frozen": frozen,
        "unavailable_reason": defects_reason,
    }

    return {
        "source": {
            "timeline_id": timeline.timeline_id,
            "project_id": timeline.project_id,
            "version": timeline.version,
            "video_path": str(video_path) if video_path is not None else None,
        },
        "shots": _shot_duration_stats(shots),
        "camera_movements": _camera_movement_distribution(shots),
        "transitions": _transition_metrics(shots),
        "asset_reuse": _asset_reuse_metrics(shots, asset_ids),
        "audio": audio,
        "silence_gaps": _silence_gap_metrics(timeline, alignment_by_scene),
        "video_defects": video_defects,
        "caption_overflow": _caption_overflow_metrics(caption_cues),
    }


def _shot_duration_stats(shots: list[Shot]) -> dict[str, Any]:
    durations = [float(s.duration_s) for s in shots]
    if not durations:
        return {
            "count": 0,
            "duration_s": {
                "mean": None,
                "median": None,
                "min": None,
                "max": None,
                "stddev": None,
            },
        }
    return {
        "count": len(durations),
        "duration_s": {
            "mean": statistics.fmean(durations),
            "median": statistics.median(durations),
            # Sample stddev (n-1); None when n < 2.
            "min": min(durations),
            "max": max(durations),
            "stddev": statistics.stdev(durations) if len(durations) >= 2 else None,
        },
    }


def _camera_movement_distribution(shots: list[Shot]) -> dict[str, Any]:
    counts = {m.value: 0 for m in CameraMovement}
    for shot in shots:
        counts[shot.camera.movement.value] += 1
    n = len(shots)
    shares = (
        {k: 0.0 for k in counts} if n == 0 else {k: v / n for k, v in counts.items()}
    )
    return {"counts": counts, "shares": shares}


def _transition_metrics(shots: list[Shot]) -> dict[str, Any]:
    counts = {t.value: 0 for t in TransitionType}
    duration_gte_shot: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        tr = shot.transition_out
        counts[tr.type.value] += 1
        # Hard cuts do not overlap (D5); their duration_s is unused.
        if tr.type == TransitionType.CUT or tr.duration_s <= 0.0:
            continue
        # D5 overlap is taken from both the outgoing shot and the incoming
        # next shot, so a transition longer than either is the hazard.
        next_shot = shots[index + 1] if index + 1 < len(shots) else None
        compared = shot
        if next_shot is not None and next_shot.duration_s < shot.duration_s:
            compared = next_shot
        if tr.duration_s >= compared.duration_s:
            duration_gte_shot.append(
                {
                    "shot_id": shot.id,
                    "transition_type": tr.type.value,
                    "transition_duration_s": float(tr.duration_s),
                    "shot_duration_s": float(shot.duration_s),
                    "compared_shot_id": compared.id,
                    "compared_duration_s": float(compared.duration_s),
                }
            )
    return {"counts": counts, "duration_gte_shot": duration_gte_shot}


def _asset_reuse_metrics(
    shots: list[Shot],
    asset_ids: Mapping[str, str] | None,
) -> dict[str, Any]:
    empty = {
        "available": False,
        "unavailable_reason": "asset_ids not provided",
        "distinct_assets": None,
        "shot_count": None,
        "distinct_per_shot": None,
        "min_reuse_gap_s": None,
    }
    if asset_ids is None:
        return empty

    starts = compute_shot_start_times(shots)
    by_identity: dict[str, list[float]] = defaultdict(list)
    counted = 0
    for shot in shots:
        identity = asset_ids.get(shot.id)
        if identity is None:
            continue
        counted += 1
        by_identity[identity].append(starts[shot.id])

    if counted == 0:
        return {
            "available": True,
            "unavailable_reason": None,
            "distinct_assets": 0,
            "shot_count": 0,
            "distinct_per_shot": None,
            "min_reuse_gap_s": None,
        }

    distinct = len(by_identity)
    min_gap: float | None = None
    for times in by_identity.values():
        if len(times) < 2:
            continue
        ordered = sorted(times)
        for a, b in zip(ordered, ordered[1:], strict=False):
            gap = b - a
            if min_gap is None or gap < min_gap:
                min_gap = gap

    return {
        "available": True,
        "unavailable_reason": None,
        "distinct_assets": distinct,
        "shot_count": counted,
        "distinct_per_shot": distinct / counted,
        "min_reuse_gap_s": min_gap,
    }


def _audio_metrics_from_parts(
    timeline: Timeline,
    *,
    mux: dict[str, float] | None,
    mux_reason: str | None,
    scene_narration_paths: Sequence[Path] | None,
    ffmpeg_binary: str,
) -> dict[str, Any]:
    per_scene: list[dict[str, Any]] | None = None
    spread: float | None = None
    per_scene_reason: str | None = None
    if scene_narration_paths is None:
        per_scene_reason = "scene_narration_paths not provided"
    elif len(scene_narration_paths) != len(timeline.scenes):
        per_scene_reason = (
            f"scene_narration_paths length {len(scene_narration_paths)} "
            f"!= timeline scene count {len(timeline.scenes)}"
        )
    else:
        per_scene, spread, per_scene_reason = _measure_per_scene_narration(
            timeline, scene_narration_paths, ffmpeg_binary
        )

    return {
        "mux": mux,
        "mux_unavailable_reason": mux_reason,
        "per_scene_narration": per_scene,
        "per_scene_narration_spread_lufs": spread,
        "per_scene_unavailable_reason": per_scene_reason,
    }


def _analyse_video(
    video_path: Path,
    ffmpeg_binary: str,
) -> tuple[
    dict[str, float] | None,
    str | None,
    list[dict[str, float]] | None,
    list[dict[str, float]] | None,
    str | None,
]:
    """Single ffmpeg pass for mux loudness + black/freeze detection."""
    if not video_path.is_file():
        reason = f"video file not found: {video_path}"
        return None, reason, None, None, reason

    has_audio = False
    audio_reason = "no audio stream in video"
    try:
        has_audio = _probe_has_audio(video_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffprobe audio check failed: %s", exc)
        audio_reason = f"ffprobe audio check failed: {_error_tail(exc)}"

    try:
        parsed = _run_video_analysis(
            video_path, ffmpeg_binary, include_audio=has_audio
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("video analysis failed: %s", exc)
        reason = _error_tail(exc)
        mux_reason = reason if has_audio else audio_reason
        return None, mux_reason, None, None, reason

    if parsed.get("error"):
        err = str(parsed["error"])
        mux_reason = err if has_audio else audio_reason
        return None, mux_reason, None, None, err

    if has_audio:
        mux = parsed.get("mux")
        mux_reason = (
            None if mux is not None else "ebur128 summary not found in ffmpeg stderr"
        )
    else:
        mux = None
        mux_reason = audio_reason

    return mux, mux_reason, parsed["near_black"], parsed["frozen"], None


def _silence_gap_metrics(
    timeline: Timeline,
    alignment_by_scene: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Silence from alignment character intervals on the audio-concat clock.

    Scene i starts at the sum of previous scenes' last character_end.
    Gaps reported: leading silence before the first character (> 0.5 s),
    and holes between consecutive character_end → character_start (> 0.5 s).
    Trailing after the last character is omitted — the concat clock ends at
    that last end (the next scene starts there).
    """
    if alignment_by_scene is None:
        return {
            "gaps": None,
            "unavailable_reason": "alignment_by_scene not provided",
        }
    if len(alignment_by_scene) != len(timeline.scenes):
        return {
            "gaps": None,
            "unavailable_reason": (
                f"alignment_by_scene length {len(alignment_by_scene)} "
                f"!= timeline scene count {len(timeline.scenes)}"
            ),
        }

    gaps: list[dict[str, float]] = []
    scene_offset = 0.0
    for _scene, alignment in zip(timeline.scenes, alignment_by_scene, strict=True):
        starts = list(alignment.get("character_start_times_seconds") or [])
        ends = list(alignment.get("character_end_times_seconds") or [])
        if not starts or not ends or len(starts) != len(ends):
            # Empty / malformed scene alignment: advance offset only if we
            # have a last end; otherwise leave offset unchanged.
            if ends:
                with contextlib.suppress(TypeError, ValueError):
                    scene_offset += float(ends[-1])
            continue

        try:
            local_starts = [float(x) for x in starts]
            local_ends = [float(x) for x in ends]
        except (TypeError, ValueError):
            continue

        if local_starts[0] > SILENCE_GAP_THRESHOLD_S:
            _append_gap(gaps, scene_offset, scene_offset + local_starts[0])

        for end_s, next_start in zip(local_ends, local_starts[1:], strict=False):
            hole = next_start - end_s
            if hole > SILENCE_GAP_THRESHOLD_S:
                _append_gap(gaps, scene_offset + end_s, scene_offset + next_start)

        scene_offset += local_ends[-1]

    return {"gaps": gaps, "unavailable_reason": None}


def _annotate_time_ranges(
    events: list[dict[str, Any]],
    shots: list[Shot],
) -> list[dict[str, Any]]:
    """Attach overlapping shots so a freeze on STATIC is separable from Q1."""
    if not events:
        return events
    starts = compute_shot_start_times(shots)
    annotated: list[dict[str, Any]] = []
    for event in events:
        overlapping: list[dict[str, str]] = []
        for shot in shots:
            shot_start = starts[shot.id]
            shot_end = shot_start + shot.duration_s
            if event["start_s"] < shot_end and event["end_s"] > shot_start:
                overlapping.append(
                    {
                        "shot_id": shot.id,
                        "camera_movement": shot.camera.movement.value,
                    }
                )
        annotated.append({**event, "shots": overlapping})
    return annotated


def _append_gap(gaps: list[dict[str, float]], start_s: float, end_s: float) -> None:
    gaps.append(
        {
            "start_s": float(start_s),
            "end_s": float(end_s),
            "duration_s": float(end_s - start_s),
        }
    )


def _caption_overflow_metrics(
    caption_cues: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if caption_cues is None:
        return {
            "cues": None,
            "unavailable_reason": "caption_cues not provided",
        }
    flagged: list[dict[str, Any]] = []
    for index, cue in enumerate(caption_cues):
        text = str(cue.get("text", ""))
        start_s = float(cue["start_s"])
        end_s = float(cue["end_s"])
        duration_s = end_s - start_s
        reasons: list[str] = []
        if len(text) > MAX_CHARS_PER_CUE:
            reasons.append("chars")
        if duration_s > MAX_CUE_DURATION_S:
            reasons.append("duration")
        if reasons:
            flagged.append(
                {
                    "index": index,
                    "chars": len(text),
                    "duration_s": duration_s,
                    "reasons": reasons,
                    "text_preview": text[:80],
                }
            )
    return {"cues": flagged, "unavailable_reason": None}


# ---------------------------------------------------------------------------
# ffmpeg helpers (analysis only; capture stderr; never shell=True)
# ---------------------------------------------------------------------------


def _measure_per_scene_narration(
    timeline: Timeline,
    paths: Sequence[Path],
    ffmpeg_binary: str,
) -> tuple[list[dict[str, Any]] | None, float | None, str | None]:
    rows: list[dict[str, Any]] = []
    values: list[float] = []
    for scene, path in zip(timeline.scenes, paths, strict=True):
        try:
            loudness = _run_ebur128_file(path, ffmpeg_binary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("per-scene ebur128 failed for %s: %s", path, exc)
            return None, None, _error_tail(exc)
        if loudness is None:
            return None, None, f"ebur128 summary missing for {path}"
        integrated = loudness["integrated_lufs"]
        rows.append({"scene_id": scene.id, "integrated_lufs": integrated})
        values.append(integrated)
    spread = max(values) - min(values) if values else None
    return rows, spread, None


def _probe_has_audio(video_path: Path) -> bool:
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe exit {result.returncode}")
    return bool(result.stdout.strip())


def _run_ffmpeg_capture(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    stderr = result.stderr or ""
    return result.returncode, stderr


def _run_video_analysis(
    video_path: Path,
    ffmpeg_binary: str,
    *,
    include_audio: bool,
) -> dict[str, Any]:
    """One analysis pass. Returns parsed fields; on failure sets ``error``."""
    args = [ffmpeg_binary, "-hide_banner", "-i", str(video_path)]
    if include_audio:
        args.extend(["-filter:a", "ebur128=peak=true"])
        args.extend(
            [
                "-filter:v",
                "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=0.003:d=2",
            ]
        )
    else:
        args.extend(
            [
                "-an",
                "-filter:v",
                "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=0.003:d=2",
            ]
        )
    args.extend(["-f", "null", "-"])

    code, stderr = _run_ffmpeg_capture(args)
    # Non-zero is fine when filters still emitted parseable lines.
    if (
        code != 0
        and "Error" in stderr
        and "Summary:" not in stderr
        and not _BLACKDETECT_RE.search(stderr)
        and not _FREEZE_START_RE.search(stderr)
    ):
        return {"error": _tail(stderr) or f"ffmpeg exit {code}", "mux": None}

    duration_s = _parse_container_duration_s(stderr)
    near_black = _parse_blackdetect(stderr)
    frozen = _parse_freezedetect(stderr, fallback_end_s=duration_s)
    mux = parse_ebur128_summary(stderr) if include_audio else None
    return {
        "error": None,
        "mux": mux,
        "near_black": near_black,
        "frozen": frozen,
    }


def _run_ebur128_file(path: Path, ffmpeg_binary: str) -> dict[str, float] | None:
    if not path.is_file():
        raise FileNotFoundError(f"narration file not found: {path}")
    args = [
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
    code, stderr = _run_ffmpeg_capture(args)
    parsed = parse_ebur128_summary(stderr)
    if parsed is None and code != 0:
        raise RuntimeError(_tail(stderr) or f"ffmpeg exit {code}")
    return parsed


def parse_blackdetect(stderr: str) -> list[dict[str, float]]:
    return _parse_blackdetect(stderr)


def parse_freezedetect(
    stderr: str,
    *,
    fallback_end_s: float | None = None,
) -> list[dict[str, float]]:
    return _parse_freezedetect(stderr, fallback_end_s=fallback_end_s)


def _parse_blackdetect(stderr: str) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for match in _BLACKDETECT_RE.finditer(stderr):
        start_s = float(match.group(1))
        end_s = float(match.group(2))
        duration_s = float(match.group(3))
        out.append({"start_s": start_s, "end_s": end_s, "duration_s": duration_s})
    return out


def _parse_freezedetect(
    stderr: str,
    *,
    fallback_end_s: float | None,
) -> list[dict[str, float]]:
    """Parse freezedetect lines; open-ended freeze_start uses fallback_end_s."""
    events: list[tuple[str, float]] = []
    for line in stderr.splitlines():
        start_m = _FREEZE_START_RE.search(line)
        if start_m:
            events.append(("start", float(start_m.group(1))))
            continue
        end_m = _FREEZE_END_RE.search(line)
        if end_m:
            events.append(("end", float(end_m.group(1))))
            continue
        dur_m = _FREEZE_DURATION_RE.search(line)
        if dur_m:
            events.append(("duration", float(dur_m.group(1))))

    out: list[dict[str, float]] = []
    pending_start: float | None = None
    pending_duration: float | None = None
    for kind, value in events:
        if kind == "start":
            if pending_start is not None:
                # Close previous open freeze at EOF fallback if available.
                end_s = fallback_end_s if fallback_end_s is not None else pending_start
                if pending_duration is not None:
                    end_s = pending_start + pending_duration
                out.append(
                    {
                        "start_s": pending_start,
                        "end_s": end_s,
                        "duration_s": end_s - pending_start,
                    }
                )
            pending_start = value
            pending_duration = None
        elif kind == "duration":
            pending_duration = value
            if pending_start is not None:
                out.append(
                    {
                        "start_s": pending_start,
                        "end_s": pending_start + value,
                        "duration_s": value,
                    }
                )
                pending_start = None
                pending_duration = None
        elif kind == "end":
            if pending_start is not None:
                duration_s = (
                    pending_duration
                    if pending_duration is not None
                    else value - pending_start
                )
                out.append(
                    {
                        "start_s": pending_start,
                        "end_s": value,
                        "duration_s": duration_s,
                    }
                )
                pending_start = None
                pending_duration = None

    if pending_start is not None:
        if pending_duration is not None:
            end_s = pending_start + pending_duration
        elif fallback_end_s is not None:
            end_s = fallback_end_s
        else:
            end_s = pending_start
        out.append(
            {
                "start_s": pending_start,
                "end_s": end_s,
                "duration_s": end_s - pending_start,
            }
        )
    return out


def _parse_container_duration_s(stderr: str) -> float | None:
    match = _FFPROBE_DURATION_RE.search(stderr)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _tail(text: str, n: int = 400) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[-n:]


def _error_tail(exc: BaseException) -> str:
    return _tail(str(exc)) or exc.__class__.__name__


