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


# --------------------------------------------------------------------------
# Band geometry — ONE definition, and Python owns it.
#
# Review finding 3 (2026-09-09). These five numbers used to exist TWICE:
# as `_SPIKE_*` in `emphasis_contrast.pivot_spike_box`, which decided
# where to MEASURE the plate, and again as `SPIKE_*` inside
# `compositor/src/Pivot.tsx`, which decided where to DRAW the band.
# Nothing guarded that mirror. Move the band in the TSX and Python keeps
# measuring the old rectangle: it picks a treatment for a place the text
# is not, with no exception, no ffmpeg error and no failing test. It is
# the only failure mode in K4 that is completely silent, which is why it
# was fixed first.
#
# The fix is structural rather than a guard or a test: the band is
# resolved HERE, in canvas pixels, carried on the cue
# (`OverlayCue.band`), measured through `PivotBand.box_on` and shipped to
# the TSX through `_overlay_props` as `cue.band`. `Pivot.tsx` positions
# itself from that prop. The measured rectangle and the drawn rectangle
# are now the same numbers rather than two copies of the same arithmetic,
# so drift is impossible by construction. `Pivot.tsx` keeps the spike
# constants ONLY as a fallback for the standalone spike compositions
# (`SuvRetention.tsx`), which pass no band; that fallback is labelled as
# such in the TSX and production never reaches it.
#
# Spike origin (do not "improve" the look): `SuvRetention.tsx` Beat 5 on
# a 720x1280 canvas — font 132, top 380, vertical padding 18, full width.
# Font scales with WIDTH, top and padding with HEIGHT, exactly as the
# spike did; on the reference canvas the band is (0, 380, 720, 548).
_PIVOT_REF_WIDTH = 720
_PIVOT_REF_HEIGHT = 1280
_PIVOT_REF_FONT = 132
_PIVOT_REF_TOP = 380
_PIVOT_REF_PAD = 18


@dataclass(frozen=True)
class PivotBand:
    """Where the pivot band sits, in the pixels of the canvas it was cut for.

    Both halves of K4 read this object and nothing else: `box_on()` gives
    the rectangle to measure, `as_props()` gives the rectangle to draw.
    `canvas_width`/`canvas_height` are carried because `box_on` needs to
    know what the band's pixels are a fraction OF.
    """

    canvas_width: int
    canvas_height: int
    left: int
    top: int
    width: int
    height: int
    font_size: int
    pad: int

    def as_props(self) -> dict[str, int]:
        """The props contract consumed by `Pivot.tsx`.

        camelCase to match every other key in `_overlay_props`; the TSX
        reads these verbatim and computes no layout of its own.

        `height` is deliberately NOT in here, and that is the one place
        this contract is not literally one number. The band's drawn
        height comes out of `fontSize`, `pad` and the CSS line-height
        (1.1, for Devanagari matras above the shirorekha), so it is
        ~13px taller on the reference canvas than the nominal
        `font + 2*pad` this class reports as `height`. Two reasons the
        nominal number stays the measured one rather than being
        reconciled:

        1. It is the box the six reference-reel luma measurements were
           taken through, and `LIGHT_MAX_LUMA = 105` is justified by
           two of them (98.3 good, 108.6 untested). Widening the box to
           the drawn height moves those to 100.6 and 103.3, which would
           put the threshold ABOVE the untested plate and silently undo
           the rationale in `emphasis_contrast`.
        2. Forcing the drawn band down to 168px means an explicit
           height and re-centred type — a change to a look the plan
           says twice not to change.

        So: `top`/`left`/`width`/`fontSize`/`pad` are the single source
        of truth and cannot drift. The residual ~8% height difference is
        known, bounded, and on the safe side (the measured slice sits
        inside the drawn band).
        """
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "fontSize": self.font_size,
            "pad": self.pad,
        }

    def hash_payload(self) -> dict[str, int]:
        """What the fingerprint and the overlay cache hash.

        The canvas is already hashed separately, but the band is not a
        pure function of it forever: the five module constants above are
        CODE, and moving the band by editing them must invalidate both
        the overlay `.mov` and the cached `final.mp4`. Without this the
        plan's own fingerprint warning applies — the render step would
        serve a cached video whose band sits in the old place and
        nothing would error.
        """
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "font_size": self.font_size,
            "pad": self.pad,
        }

    def box_on(self, width: int, height: int) -> tuple[int, int, int, int] | None:
        """`(x0, y0, x1, y1)` for this band projected onto a `width`x`height` image.

        K4 measures `shot_images`, which holds the RAW resolved asset —
        frequently 1920x1080 — not a canvas-sized frame; the crop into
        720x1280 happens later inside ffmpeg. So the band is mapped by
        its fraction of the canvas rather than recomputed from the
        asset's own dimensions. Recomputing was subtly wrong on any
        asset whose aspect differs from the canvas: font (and therefore
        band height) scales with WIDTH while top scales with HEIGHT, so
        on a 1920x1080 asset the old code measured a band 0.35 of the
        picture tall where the drawn one covers 0.13.

        Still an approximation, and deliberately left as one: a
        ken-burns crop decides which of the asset's pixels actually land
        under the band, and knowing that exactly means extracting the
        rendered frame. That is a bigger change than this review, and
        the fractional map is strictly closer than what it replaces.
        """
        if width <= 0 or height <= 0:
            return None
        if self.canvas_width <= 0 or self.canvas_height <= 0:
            return None
        scale_x = width / self.canvas_width
        scale_y = height / self.canvas_height
        x0 = max(0, min(width, round(self.left * scale_x)))
        x1 = max(0, min(width, round((self.left + self.width) * scale_x)))
        y0 = max(0, min(height, round(self.top * scale_y)))
        y1 = max(0, min(height, round((self.top + self.height) * scale_y)))
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1, y1)


def pivot_band(canvas_width: int, canvas_height: int) -> PivotBand | None:
    """Resolve the pivot band for a canvas, or None if it cannot be formed.

    The single source of truth described in the block comment above. On
    the 720x1280 reference canvas this is top 380, height 168
    (font 132 + 2*pad 18), full width — i.e. the box (0, 380, 720, 548)
    that K4's regression tests pin.
    """
    if canvas_width <= 0 or canvas_height <= 0:
        return None
    font_size = round(_PIVOT_REF_FONT * (canvas_width / _PIVOT_REF_WIDTH))
    top = round(_PIVOT_REF_TOP * (canvas_height / _PIVOT_REF_HEIGHT))
    pad = round(_PIVOT_REF_PAD * (canvas_height / _PIVOT_REF_HEIGHT))
    band_height = font_size + pad * 2
    y0 = max(0, min(canvas_height, top))
    y1 = max(0, min(canvas_height, top + band_height))
    if y1 <= y0:
        return None
    return PivotBand(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        left=0,
        top=y0,
        width=canvas_width,
        height=y1 - y0,
        font_size=font_size,
        pad=pad,
    )


@dataclass(frozen=True)
class OverlayCue:
    """One cue as handed to the compositor AND hashed into the render
    fingerprint (RV2: one value gates derivation and cache).

    `treatment` is K4, resolved at render from the covering plate —
    never a planner field. Default `slab` is the safe unmeasured value
    (light-on-transparent is the 2025 failure). `shot_id` is how the
    chooser finds that plate; it is not a compositor input.

    `band` is the cue's resolved geometry (review finding 3). It is on
    the cue rather than passed around separately so that the rectangle
    K4 measures, the rectangle the fingerprint hashes and the rectangle
    `Pivot.tsx` draws are one value read three times. `None` means the
    canvas could not produce a band (degenerate dimensions) or the
    device does not have one yet — pivot is the only device with a band
    in this slice.
    """

    device: str
    text: str
    text_register: str
    offset_s: float
    start_frame: int
    end_frame: int
    shot_id: str | None = None
    treatment: str = "slab"
    band: PivotBand | None = None


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def emphasis_font_content_hash() -> str:
    """Hash the vendored file's bytes, not its path — swapping Regular
    for Bold (K6) must miss every overlay cache and every render
    fingerprint."""
    if not EMPHASIS_FONT_PATH.exists():
        raise PermanentError(f"vendored emphasis font missing on disk: {EMPHASIS_FONT_PATH}")
    return hashlib.sha256(EMPHASIS_FONT_PATH.read_bytes()).hexdigest()


def collect_pivot_overlay_cues(
    timeline: Timeline, *, fps: int, width: int, height: int
) -> list[OverlayCue]:
    """Film-absolute frames from each shot's resolved `offset_s`.

    Hold is `PIVOT_HOLD_S` (0.91s, the spike window), clamped so the
    cue cannot outlive the remaining shot or the remaining film.
    Unknown devices are ignored — this slice only composites `pivot`.

    `width`/`height` are the CANVAS, and they are required rather than
    defaulted because they resolve the cue's `band` (review finding 3).
    This is the resolver that already turns creative decisions into
    render-time numbers — frames from fragment offsets — so geometry
    belongs here too, and a defaulted 720x1280 would be exactly the kind
    of unguarded assumption finding 3 removed.
    """
    shots = timeline.all_shots()
    if not shots:
        return []
    band = pivot_band(width, height)
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
                shot_id=shot.id,
                band=band,
            )
        )
    return cues


def emphasis_cue_content_hash(cues: list[OverlayCue]) -> str | None:
    """Fingerprint input: RESOLVED cues (device, text, offset_s,
    text_register, treatment, band). Not the untimed planner output.
    Treatment is hashed because a plate-driven flip must miss the render
    cache (retention_fast_kinetic_text.md fingerprint warning). `band`
    is hashed for the same reason one level down: the band's five
    constants live in code, so editing them moves the drawn band, and a
    `final.mp4` keyed on an unchanged cue list would be served with the
    band still in its old place — the plan's own "serves the cached
    video and nothing errors" trap. None when there are no cues so a
    no-cue timeline hashes with the key present and the value null.

    Adding `band` changes every historical value of this hash, so the
    first render of each existing project after this review re-renders.
    That is correct: the props contract it fingerprints did change.
    """
    if not cues:
        return None
    payload = [
        {
            "device": cue.device,
            "text": cue.text,
            "offset_s": cue.offset_s,
            "text_register": cue.text_register,
            "treatment": cue.treatment,
            "band": cue.band.hash_payload() if cue.band is not None else None,
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
    """Cache key for the rendered `.mov`. Every pixel input, nothing else.

    `band` joined this payload with review finding 3. The canvas is
    already here and the band is derived from it today, but the
    derivation lives in code (`_PIVOT_REF_*`), so the band is hashed
    explicitly: editing those constants must miss this cache instead of
    reusing a `.mov` with the band in the old position. Consequence,
    expected and correct: every overlay cached before this change misses
    once and re-renders.
    """
    payload = {
        "cues": [
            {
                "device": cue.device,
                "text": cue.text,
                "textRegister": cue.text_register,
                "startFrame": cue.start_frame,
                "endFrame": cue.end_frame,
                "treatment": cue.treatment,
                "band": cue.band.as_props() if cue.band is not None else None,
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
    """The props contract handed to the `Emphasis` composition.

    `cue.band` is the finding-3 half of it: Python resolves the band and
    `Pivot.tsx` positions itself from these numbers instead of holding
    its own copy of the layout. Keys are camelCase because that is what
    the TSX types declare; the Python-side names are snake_case and the
    translation happens only here.
    """
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
                "treatment": cue.treatment,
                "band": cue.band.as_props() if cue.band is not None else None,
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
