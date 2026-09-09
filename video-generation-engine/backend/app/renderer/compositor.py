"""Remotion as a layer producer (retention_fast_kinetic_text.md K7).

One parameterized composition driven by `--props`. Cache by INPUT hash
(never output bytes) so headless Chromium's non-determinism cannot
break I5 at the assembly level. Missing Node/compositor is a
PermanentError — silently skipping would ship a reel with no kinetic
text and nothing would error.

This slice renders `pivot` only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.schemas.timeline import EmphasisDevice, Timeline
from app.timeline.duration import compute_shot_start_times, compute_timeline_duration

logger = get_logger(__name__)

# Spike Beat 5: 4.94s → 5.85s. Documented in the plan work log.
PIVOT_HOLD_S = 0.91

COMPOSITOR_ROOT = Path(__file__).resolve().parents[3] / "compositor"
EMPHASIS_FONT_PATH = Path(__file__).resolve().parents[2] / "vendor" / "fonts" / "NotoSansDevanagari-Regular.ttf"
COMPOSITION_ID = "Emphasis"


@dataclass(frozen=True)
class OverlayCue:
    """One cue as handed to the compositor AND hashed into the render
    fingerprint (RV2: one value gates derivation and cache)."""

    device: str
    text: str
    text_register: str
    offset_s: float
    start_frame: int
    end_frame: int


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def emphasis_font_content_hash() -> str:
    """Hash the vendored file's bytes, not its path — swapping Regular
    for Bold (K6) must miss every overlay cache and every render
    fingerprint."""
    if not EMPHASIS_FONT_PATH.exists():
        raise PermanentError(f"vendored emphasis font missing on disk: {EMPHASIS_FONT_PATH}")
    return hashlib.sha256(EMPHASIS_FONT_PATH.read_bytes()).hexdigest()


def collect_pivot_overlay_cues(timeline: Timeline, *, fps: int) -> list[OverlayCue]:
    """Film-absolute frames from each shot's resolved `offset_s`.

    Hold is `PIVOT_HOLD_S` (0.91s, the spike window), clamped so the
    cue cannot outlive the remaining shot or the remaining film.
    Unknown devices are ignored — this slice only composites `pivot`.
    """
    shots = timeline.all_shots()
    if not shots:
        return []
    starts = compute_shot_start_times(shots)
    total_s = compute_timeline_duration(shots)
    duration_frames = max(1, round(total_s * fps))
    cues: list[OverlayCue] = []
    for shot in shots:
        cue = shot.emphasis_cue
        if cue is None or cue.device is not EmphasisDevice.PIVOT:
            continue
        shot_start_s = starts.get(shot.id, 0.0)
        start_s = shot_start_s + cue.offset_s
        remaining_shot_s = max(0.0, shot.duration_s - cue.offset_s)
        remaining_film_s = max(0.0, total_s - start_s)
        hold_s = min(PIVOT_HOLD_S, remaining_shot_s, remaining_film_s)
        if hold_s <= 0:
            continue
        start_frame = max(0, round(start_s * fps))
        end_frame = min(duration_frames, start_frame + max(1, round(hold_s * fps)))
        if end_frame <= start_frame:
            continue
        cues.append(
            OverlayCue(
                device=cue.device.value,
                text=cue.text,
                text_register=cue.text_register.value,
                offset_s=cue.offset_s,
                start_frame=start_frame,
                end_frame=end_frame,
            )
        )
    return cues


def emphasis_cue_content_hash(cues: list[OverlayCue]) -> str | None:
    """Fingerprint input: RESOLVED cues (device, text, offset_s,
    text_register). Not the untimed planner output. None when there are
    no cues so a no-cue timeline hashes with the key present and the
    value null."""
    if not cues:
        return None
    payload = [
        {
            "device": cue.device,
            "text": cue.text,
            "offset_s": cue.offset_s,
            "text_register": cue.text_register,
        }
        for cue in cues
    ]
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def overlay_input_hash(
    *,
    cues: list[OverlayCue],
    width: int,
    height: int,
    fps: int,
    duration_in_frames: int,
    font_hash: str,
) -> str:
    payload = {
        "cues": [
            {
                "device": cue.device,
                "text": cue.text,
                "textRegister": cue.text_register,
                "startFrame": cue.start_frame,
                "endFrame": cue.end_frame,
            }
            for cue in cues
        ],
        "canvas": {"width": width, "height": height},
        "fps": fps,
        "duration_in_frames": duration_in_frames,
        "font_hash": font_hash,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def emphasis_overlay_filter_fragment(
    input_label: str, output_label: str, overlay_input_index: int
) -> str:
    return (
        f"[{input_label}][{overlay_input_index}:v]overlay=0:0:format=auto[{output_label}]"
    )


def _overlay_props(cues: list[OverlayCue], *, width: int, height: int, fps: int, duration_in_frames: int) -> dict:
    return {
        "canvas": {"width": width, "height": height},
        "fps": fps,
        "durationInFrames": duration_in_frames,
        "cues": [
            {
                "device": cue.device,
                "text": cue.text,
                "textRegister": cue.text_register,
                "startFrame": cue.start_frame,
                "endFrame": cue.end_frame,
            }
            for cue in cues
        ],
    }


def _ensure_compositor_toolchain() -> str:
    if not (COMPOSITOR_ROOT / "package.json").exists():
        raise PermanentError(
            f"compositor package missing at {COMPOSITOR_ROOT} — "
            "kinetic-text overlay cannot be rendered. Refusing to skip."
        )
    if not (COMPOSITOR_ROOT / "node_modules" / "remotion").exists():
        raise PermanentError(
            f"compositor dependencies missing under {COMPOSITOR_ROOT} — "
            "run `npm install` in compositor/. Refusing to skip."
        )
    npx = shutil.which("npx")
    if npx is None:
        raise PermanentError(
            "npx not found on PATH — the compositor requires Node 18+ "
            "(retention_fast_kinetic_text.md K7). Refusing to skip: a "
            "missing overlay would ship a reel with no kinetic text and "
            "nothing would error."
        )
    return npx


async def _invoke_remotion(props_path: Path, output_path: Path) -> None:
    npx = _ensure_compositor_toolchain()
    public_font = COMPOSITOR_ROOT / "public" / EMPHASIS_FONT_PATH.name
    if not public_font.exists():
        public_font.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EMPHASIS_FONT_PATH, public_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # ABSOLUTE paths, because this subprocess runs with cwd=COMPOSITOR_ROOT
    # while both paths are built from `settings.storage_root`, which is
    # relative ("./storage") and resolves against the BACKEND's cwd. Passed
    # through relative, the CLI cannot find the props file (it reports
    # "neither valid JSON nor a file path to a valid JSON file") and would
    # write the .mov into compositor/storage/... even if it could. Found
    # 2026-09-09 the first time `_invoke_remotion` was ever really called:
    # every unit test injects a fake `invoke`, so this line had never run.
    props_arg = props_path.resolve()
    output_arg = output_path.resolve()
    process = await asyncio.create_subprocess_exec(
        npx,
        "remotion",
        "render",
        COMPOSITION_ID,
        str(output_arg),
        f"--props={props_arg}",
        "--codec=prores",
        "--prores-profile=4444",
        "--pixel-format=yuva444p10le",
        "--image-format=png",
        cwd=str(COMPOSITOR_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise PermanentError(
            "compositor render failed "
            f"(exit {process.returncode}): {stderr.decode(errors='replace')[-4000:]}"
        )
    if not output_path.exists():
        raise PermanentError(
            f"compositor reported success but wrote no file at {output_path}; "
            f"stdout={stdout.decode(errors='replace')[-1000:]}"
        )


async def render_or_reuse_emphasis_overlay(
    *,
    project_id: str,
    cues: list[OverlayCue],
    width: int,
    height: int,
    fps: int,
    duration_in_frames: int,
    storage_root: Path | None = None,
    invoke=_invoke_remotion,
) -> Path:
    """Return `{storage_root}/{project_id}/overlays/{input_hash}.mov`.

    Cache HIT skips Chromium. Cache is keyed on the INPUT hash, never
    on output bytes.
    """
    if not cues:
        raise PermanentError("render_or_reuse_emphasis_overlay called with no cues")
    font_hash = emphasis_font_content_hash()
    input_hash = overlay_input_hash(
        cues=cues,
        width=width,
        height=height,
        fps=fps,
        duration_in_frames=duration_in_frames,
        font_hash=font_hash,
    )
    root = storage_root if storage_root is not None else settings.storage_root
    overlays_dir = root / project_id / "overlays"
    cache_path = overlays_dir / f"{input_hash}.mov"
    if cache_path.exists():
        logger.info(
            "compositor.overlay_cache_hit",
            extra={"project_id": project_id, "input_hash": input_hash},
        )
        return cache_path

    overlays_dir.mkdir(parents=True, exist_ok=True)
    props_path = overlays_dir / f"{input_hash}.json"
    # Must still END in .mov: the Remotion CLI validates the output
    # extension against the codec ("prores ... must end in one of: mov,
    # mkv, mxf") before it renders anything, so a ".mov.tmp" suffix is
    # rejected outright. Leading dot keeps it out of the way and
    # `os.replace` below keeps the swap atomic. Found 2026-09-09 on the
    # first real invocation.
    tmp_path = overlays_dir / f".{input_hash}.partial.mov"
    props_path.write_text(
        json.dumps(
            _overlay_props(
                cues,
                width=width,
                height=height,
                fps=fps,
                duration_in_frames=duration_in_frames,
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        if tmp_path.exists():
            tmp_path.unlink()
        await invoke(props_path, tmp_path)
        os.replace(tmp_path, cache_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    logger.info(
        "compositor.overlay_cache_miss",
        extra={"project_id": project_id, "input_hash": input_hash},
    )
    return cache_path
