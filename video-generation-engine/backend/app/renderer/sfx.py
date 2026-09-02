"""SFX overlays (parent plan §5.5 / leftover item 2).

Placement is deterministic from Timeline events already there: punch-in
snaps, text cards, non-cut transitions, and (long_form_direction.md A8)
`Shot.sfx_cue`. The palette (`SfxPlan.clips`) is the creative half - the
three structural kinds filled by `SelectSfxStep` (search), DIEGETIC by
`GenerateDiegeticSfxStep` (generation, one clip per cue-bearing shot).
Mixing is N delayed overlays amixed onto the existing audio — routed
through `run_ffmpeg` (R-C7), never a raw subprocess.

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

# A15: the transitions that read as a deliberate beat rather than
# everyday continuity. `DISSOLVE`/`FADE` are excluded on purpose - they are
# the connective tissue a documentary uses constantly, and a swoosh on each
# one is texture, not punctuation. The three `glitch_*` ARE included: the
# base prompt reserves them for "a moment of digital corruption", which is
# by definition a beat.
_STRUCTURAL_TRANSITIONS = frozenset(
    {
        TransitionType.WIPE_LEFT,
        TransitionType.DIP_TO_BLACK,
        TransitionType.GLITCH_SHIFT,
        TransitionType.GLITCH_TEAR,
        TransitionType.GLITCH_JITTER,
    }
)

_DEFAULT_MAX_CLIP_S = 1.5
_FADE_OUT_S = 0.08


@dataclass(frozen=True)
class SfxOverlay:
    """One scheduled SFX event's complete mix inputs: WHERE it lands, HOW
    LOUD it plays (`volume_factor`, precomputed by the caller from C3c's
    normalization math), and WHERE its trim starts (`trim_start_s`, C3d's
    end-alignment for clips that exceed the ceiling). `mux_sfx` never
    re-measures or re-decides anything - rendering stays a pure function
    of what the caller assembled."""

    path: Path
    offset_s: float
    volume_factor: float
    trim_start_s: float = 0.0
    # long_form_direction.md A8: `None` means "use `mux_sfx`'s own
    # `max_clip_s` argument" - the structural WHOOSH/STINGER/TRANSITION
    # path, byte-identical to before this field existed. A DIEGETIC
    # overlay sets this explicitly (`settings.sfx_diegetic_max_clip_s`)
    # so one `mux_sfx` call can mix a 1.5s stinger and an 8s ambience bed
    # in the same pass without the stinger's ceiling truncating the
    # ambience or the ambience's ceiling stretching the stinger's fade.
    max_clip_s: float | None = None


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
    # long_form_direction.md A8: which Shot this event belongs to. `None`
    # for the three structural kinds (a single shared clip per kind - the
    # event alone is enough to pick it). Set for DIEGETIC events, since
    # `SfxPlan.clips` can hold several different DIEGETIC clips and the
    # caller needs to know which shot's cue this particular event answers.
    shot_id: str | None = None


def derive_sfx_events(
    timeline: Timeline,
    *,
    fps: int,
    whoosh_enabled: bool,
    transition_structural_only: bool = False,
) -> list[SfxEvent]:
    """Whoosh at each punch-in snap, stinger at each text-card start,
    transition SFX at each non-cut overlap. Sorted for I5.

    `whoosh_enabled` is resolved from the style ONCE by the caller and
    handed in here (review of P2, analysis.md RV2): the same single
    value must gate both this derivation and `compute_render_fingerprint`,
    so the two cannot drift apart the way two independent resolutions
    could."""
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
        # A15 (long_form_direction.md, 2026-09-02): `transition_structural_
        # only` restricts this layer to the transitions the base prompt
        # itself calls "a genuinely deliberate structural beat", leaving a
        # plain `dissolve` silent. On the first finished long-form video 45
        # of 77 shots fired a swoosh - `documentary_archival` dissolves
        # heavily - at 10 dB LOUDER than that video's diegetic cues. Same
        # shape of density failure `whoosh_enabled` already exists for, and
        # the same fix: a per-style gate, resolved ONCE by the caller (RV2)
        # so this derivation and `compute_render_fingerprint` cannot drift.
        if (
            transition.type != TransitionType.CUT
            and transition.duration_s > 0
            and (not transition_structural_only or transition.type in _STRUCTURAL_TRANSITIONS)
        ):
            overlap_start = start_s + shot.duration_s - transition.duration_s
            events.append(SfxEvent(kind=SfxKind.TRANSITION, offset_s=max(overlap_start, 0.0)))
        # long_form_direction.md A8: v1 places a diegetic cue at the
        # shot's start - crude (the story may want it on a specific word,
        # not a shot boundary) but honest; word-relative placement via
        # `narration_span` is a later slice (open question 1, §3 A8).
        # Never gated by `whoosh_enabled` - that gate is WHOOSH-specific
        # (a fast-cut style's own punch-in density problem), unrelated to
        # a content-driven cue.
        if (shot.sfx_cue or "").strip():
            events.append(SfxEvent(kind=SfxKind.DIEGETIC, offset_s=start_s, shot_id=shot.id))
    events.sort(key=lambda event: (event.offset_s, event.kind.value))
    # Decisions 5 + 5a (analysis.md, 2026-08-24): a style can opt out of
    # the WHOOSH layer entirely (`retention_fast` - two punch-ins per
    # ~1.75s shot made one clip play ~100 times per reel). Stinger and
    # transition events are untouched: on a fastcut reel they are the
    # only remaining kinds, and both stay rare (D3). The CALLER owns the
    # style resolution - see this function's docstring (RV2).
    if not whoosh_enabled:
        events = [event for event in events if event.kind != SfxKind.WHOOSH]
    return events


async def mux_sfx(
    video_path: Path,
    overlays: list[SfxOverlay],
    output_path: Path,
    settings: RenderSettings,
    *,
    max_clip_s: float = _DEFAULT_MAX_CLIP_S,
) -> Path:
    """Mix `overlays` onto `video_path`'s existing audio, or *become* the
    audio if the video is silent (R13). Each overlay is trimmed (C3d:
    end-aligned when the caller set `trim_start_s`, so the impact
    transient survives the ceiling), faded out at the trim so a hard
    `atrim` is not a click (R15), scaled by its OWN precomputed volume
    factor (C3c: per-clip normalization - there is no global gain here
    any more), delayed, and amixed. Empty overlays is a no-op copy."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not overlays:
        if video_path.resolve() != output_path.resolve():
            output_path.write_bytes(video_path.read_bytes())
        return output_path

    ordered = sorted(overlays, key=lambda item: item.offset_s)
    has_audio = await _has_audio_stream(video_path, settings.ffprobe_binary)
    args: list[str] = [settings.ffmpeg_binary, "-y", "-i", str(video_path)]
    for overlay in ordered:
        args += ["-i", str(overlay.path)]
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
    for index, overlay in enumerate(ordered, start=1):
        delay_ms = max(int(round(overlay.offset_s * 1000)), 0)
        label = f"s{index}"
        # long_form_direction.md A8: each overlay's OWN ceiling - `None`
        # (every structural WHOOSH/STINGER/TRANSITION overlay, byte-
        # identical to before this field existed) falls back to this
        # call's `max_clip_s`; a DIEGETIC overlay carries its own, longer
        # ceiling (`settings.sfx_diegetic_max_clip_s`) so one call can mix
        # both kinds of clip without either's ceiling leaking onto the
        # other.
        clip_ceiling = overlay.max_clip_s if overlay.max_clip_s is not None else max_clip_s
        fade_s = min(_FADE_OUT_S, clip_ceiling / 2)
        fade_start = max(clip_ceiling - fade_s, 0.0)
        # C3d: end-aligned trim when the caller knows the clip outgrew
        # the ceiling - keep the TAIL (impact transient), not the head.
        # Both branches produce exactly `clip_ceiling` seconds, so the
        # fade-out timing above is identical either way.
        if overlay.trim_start_s > 0:
            atrim = (
                f"atrim=start={overlay.trim_start_s:.3f}:"
                f"end={overlay.trim_start_s + clip_ceiling:.3f}"
            )
        else:
            atrim = f"atrim=0:{clip_ceiling:.3f}"
        filter_parts.append(
            f"[{index}:a]{atrim},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.3f}:d={fade_s:.3f},"
            f"volume={overlay.volume_factor:.6f},adelay={delay_ms}:all=1[{label}]"
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
