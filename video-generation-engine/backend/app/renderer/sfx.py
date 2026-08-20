"""SFX overlays (parent plan §5.5 / leftover item 2).

Placement is deterministic from Timeline events already there: punch-in
snaps, text cards, non-cut transitions. The palette (`SfxPlan.clips`) is
the creative half, filled by `SelectSfxStep`. Mixing is N delayed
overlays amixed onto the existing audio — routed through `run_ffmpeg`
(R-C7), never a raw subprocess.

I5: overlay order is sorted by (offset_s, kind), never set iteration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.renderer.ken_burns import punch_in_frame_offsets
from app.renderer.slideshow import RenderSettings, probe_duration_seconds, run_ffmpeg
from app.schemas.timeline import CameraMovement, SfxKind, Timeline, TransitionType
from app.timeline.duration import compute_shot_start_times

_DEFAULT_MAX_CLIP_S = 1.5
_FADE_OUT_S = 0.08


async def _has_audio_stream(path: Path, ffprobe_binary: str) -> bool:
    """R13: mux_sfx used to assume `[0:a]` exists."""
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


@dataclass(frozen=True)
class SfxEvent:
    kind: SfxKind
    offset_s: float


def derive_sfx_events(timeline: Timeline, *, fps: int) -> list[SfxEvent]:
    """Whoosh at each punch-in snap, stinger at each text-card start,
    transition SFX at each non-cut overlap. Sorted for I5."""
    shots = timeline.all_shots()
    starts = compute_shot_start_times(shots)
    events: list[SfxEvent] = []
    for shot in shots:
        start_s = starts[shot.id]
        if shot.camera.movement == CameraMovement.PUNCH_IN:
            frames = max(int(round(shot.duration_s * fps)), 1)
            offsets = punch_in_frame_offsets(shot.camera, frames=frames)
            if offsets:
                events.extend(
                    SfxEvent(kind=SfxKind.WHOOSH, offset_s=start_s + frame / fps)
                    for frame in offsets
                )
        if (shot.text_card or "").strip():
            events.append(SfxEvent(kind=SfxKind.STINGER, offset_s=start_s))
        transition = shot.transition_out
        if transition.type != TransitionType.CUT and transition.duration_s > 0:
            overlap_start = start_s + shot.duration_s - transition.duration_s
            events.append(SfxEvent(kind=SfxKind.TRANSITION, offset_s=max(overlap_start, 0.0)))
    events.sort(key=lambda event: (event.offset_s, event.kind.value))
    return events


async def mux_sfx(
    video_path: Path,
    overlays: list[tuple[Path, float]],
    output_path: Path,
    settings: RenderSettings,
    *,
    gain_db: float,
    max_clip_s: float = _DEFAULT_MAX_CLIP_S,
) -> Path:
    """Delay each `(path, offset_s)` overlay and amix onto `video_path`'s
    existing audio, or *become* the audio if the video is silent (R13).
    Each overlay is faded out at the trim so a hard `atrim` is not a
    click (R15). Empty overlays is a no-op copy."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not overlays:
        if video_path.resolve() != output_path.resolve():
            output_path.write_bytes(video_path.read_bytes())
        return output_path

    ordered = sorted(overlays, key=lambda item: item[1])
    gain_linear = 10 ** (gain_db / 20)
    fade_s = min(_FADE_OUT_S, max_clip_s / 2)
    fade_start = max(max_clip_s - fade_s, 0.0)
    has_audio = await _has_audio_stream(video_path, settings.ffprobe_binary)
    args: list[str] = [settings.ffmpeg_binary, "-y", "-i", str(video_path)]
    for path, _offset in ordered:
        args += ["-i", str(path)]
    silence_index: int | None = None
    if not has_audio:
        duration_s = await probe_duration_seconds(video_path, settings.ffprobe_binary)
        args += [
            "-f",
            "lavfi",
            "-t",
            f"{max(duration_s, 0.1):.3f}",
            "-i",
            "anullsrc=r=48000:cl=stereo",
        ]
        silence_index = 1 + len(ordered)

    filter_parts: list[str] = []
    mix_labels: list[str] = []
    if has_audio:
        mix_labels.append("[0:a]")
    else:
        mix_labels.append(f"[{silence_index}:a]")
    for index, (_path, offset_s) in enumerate(ordered, start=1):
        delay_ms = max(int(round(offset_s * 1000)), 0)
        label = f"s{index}"
        filter_parts.append(
            f"[{index}:a]atrim=0:{max_clip_s:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.3f}:d={fade_s:.3f},"
            f"volume={gain_linear:.6f},adelay={delay_ms}:all=1[{label}]"
        )
        mix_labels.append(f"[{label}]")
    n_inputs = len(mix_labels)
    filter_parts.append(
        f"{''.join(mix_labels)}amix=inputs={n_inputs}:duration=first:"
        "dropout_transition=0:normalize=0[aout]"
    )
    args += [
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path
