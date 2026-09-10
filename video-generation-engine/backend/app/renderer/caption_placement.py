"""K17 content-aware caption placement: calmest free candidate box.

Resolves ONCE at render time from the plate map RenderStep already
builds for K4. `captions.py` stays pure (no Path / PIL): it only emits
the resolved margins and ``\\an`` into ASS. Occupied
``OverlayCue.band`` rectangles are excluded so a stamp cannot share
pixels with the caption (``tmp/demo/frame_C_0.55.png``).

Busyness is Rec. 601 luma **population** standard deviation inside the
candidate box (divide by N, not N-1) — variance, not K4's mean. Lower
is calmer and preferred. Candidate order is the stable tie-break.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.colour import rec601_luma
from app.core.logging import get_logger
from app.renderer.captions import CaptionCue
from app.renderer.compositor import OverlayCue
from app.schemas.timeline import Shot
from app.timeline.duration import compute_shot_start_times

logger = get_logger(__name__)

# Demo reference canvas (`tmp/demo/make_placement_demos.py`). Margins and
# boxes are stored as fractions so they scale to any canvas.
_REF_WIDTH = 720
_REF_HEIGHT = 1280


@dataclass(frozen=True)
class CandidateBox:
    """One placement option, as fractions of canvas width/height."""

    name: str
    an: int
    margin_l_frac: float
    margin_r_frac: float
    margin_v_frac: float
    # (x0, y0, x1, y1) as fractions of (W, H, W, H).
    box_frac: tuple[float, float, float, float]


# Demo PLACEMENTS, fractional. Table order is the deterministic
# tie-break when busyness ties (I5).
CANDIDATE_BOXES: tuple[CandidateBox, ...] = (
    CandidateBox(
        name="bottom-centre",
        an=2,
        margin_l_frac=20 / _REF_WIDTH,
        margin_r_frac=20 / _REF_WIDTH,
        margin_v_frac=205 / _REF_HEIGHT,
        box_frac=(0.0, 0.72, 1.0, 0.88),
    ),
    CandidateBox(
        name="bottom-left",
        an=1,
        margin_l_frac=60 / _REF_WIDTH,
        margin_r_frac=20 / _REF_WIDTH,
        margin_v_frac=205 / _REF_HEIGHT,
        box_frac=(0.0, 0.72, 0.7, 0.88),
    ),
    CandidateBox(
        name="upper-centre",
        an=8,
        margin_l_frac=20 / _REF_WIDTH,
        margin_r_frac=20 / _REF_WIDTH,
        margin_v_frac=300 / _REF_HEIGHT,
        box_frac=(0.0, 0.22, 1.0, 0.38),
    ),
)


@dataclass(frozen=True)
class CaptionPlacement:
    """Resolved per-``CaptionCue`` block placement (all word-walk lines share it)."""

    name: str
    an: int
    margin_l: int
    margin_r: int
    margin_v: int
    box: tuple[int, int, int, int]


def scale_candidate(
    candidate: CandidateBox, *, canvas_width: int, canvas_height: int
) -> CaptionPlacement:
    """Margins scale with W (L/R) and H (V); box corners round to int pixels."""
    x0, y0, x1, y1 = candidate.box_frac
    return CaptionPlacement(
        name=candidate.name,
        an=candidate.an,
        margin_l=round(candidate.margin_l_frac * canvas_width),
        margin_r=round(candidate.margin_r_frac * canvas_width),
        margin_v=round(candidate.margin_v_frac * canvas_height),
        box=(
            round(x0 * canvas_width),
            round(y0 * canvas_height),
            round(x1 * canvas_width),
            round(y1 * canvas_height),
        ),
    )


def boxes_overlap(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> bool:
    """Axis-aligned bounding-box overlap. Touching edges do not overlap."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _population_stdev(values: Sequence[float]) -> float:
    """Population standard deviation (divide by N). Documented choice for K17.3."""
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


def luma_stdev_in_box(
    image: Image.Image, box: tuple[int, int, int, int]
) -> float:
    """Rec. 601 luma population stdev of pixels inside ``box`` on an open image."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width <= 0 or height <= 0:
        raise ValueError("image has zero width or height")
    x0, y0, x1, y1 = box
    x0 = max(0, min(width, int(x0)))
    y0 = max(0, min(height, int(y0)))
    x1 = max(0, min(width, int(x1)))
    y1 = max(0, min(height, int(y1)))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("box has zero area after clamp")
    region = rgb.crop((x0, y0, x1, y1))
    lumas = [rec601_luma(r, g, b) for r, g, b in region.getdata()]
    return _population_stdev(lumas)


def _decode_plate(path: Path | None) -> Image.Image | None:
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        logger.info(
            "caption_placement.unreadable",
            extra={"path": str(path), "reason": "unreadable"},
        )
        return None
    if not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            decoded = image.convert("RGB")
            decoded.load()
            return decoded
    except (UnidentifiedImageError, OSError, ValueError):
        logger.info(
            "caption_placement.unreadable",
            extra={"path": str(path), "reason": "not_a_still"},
        )
        return None


def _shot_id_for_cue(
    cue: CaptionCue, shots: Sequence[Shot], starts: Mapping[str, float]
) -> str | None:
    """Map caption cue.start_s onto a shot via compute_shot_start_times windows.

    Safe across transition overlap (see `_overlay_live` for the full
    clock argument): a shot's video window is
    `[narration onset - incoming overlap, narration offset)`, because
    `compute_shot_start_times` starts the shot at the head of its
    incoming crossfade while `narration_fit` inflated `duration_s` by
    that same overlap. That window strictly CONTAINS the shot's own
    `[onset, offset)` narration window, so every cue still lands on the
    shot whose words it carries, dissolve or no dissolve.
    """
    if not shots:
        return None
    t = cue.start_s
    for shot in shots:
        start = starts.get(shot.id, 0.0)
        end = start + shot.duration_s
        if start <= t < end:
            return shot.id
    last = shots[-1]
    last_start = starts.get(last.id, 0.0)
    if t >= last_start:
        return last.id
    return shots[0].id


def _overlay_live(
    overlay: OverlayCue, *, cue_start_s: float, cue_end_s: float, fps: int
) -> bool:
    """Live iff overlay [start_frame/fps, end_frame/fps) overlaps caption [start, end).

    ## Both operands are FINISHED-VIDEO time — no conversion belongs here

    Writing this down because it looks wrong and has been raised once
    already. `overlay.start_frame` is derived through
    `compute_shot_start_times` (D5, transition-overlap-aware) while
    `cue_start_s` comes from `derive_caption_cues`, which `captions.py`'s
    "Which clock" section calls audio-concat time and explicitly warns is
    a DIFFERENT timeline from `compute_shot_start_times`. That warning is
    true, and it is about a shot's ONSET — neither of which this function
    reads:

    - `overlay.start_frame` is a frame index into the composited video,
      so `start_frame / fps` is literally the moment those pixels are
      painted.
    - `cue_start_s` is the timestamp `serialize_ass` writes into the ASS
      file, and `render.py` burns that ASS onto the same composited video
      via the `subtitles` filter with no seek and no `setpts` before
      `mux_narration` runs — so it is literally the moment those pixels
      are painted too.

    The two axes coincide because narration and picture share t=0 and
    share a length: `narration_fit.py` inflates every post-transition
    shot's `duration_s` by exactly the overlap D5 subtracts, so
    `compute_timeline_duration(shots) == sum of scene narration
    durations` on any timeline, transitions and all. What still differs
    is the per-shot onset — a shot after a 0.4s dissolve starts 0.4s
    before its first spoken character — and occupancy never asks for a
    shot onset. It asks "do these two layers share a frame", and both
    operands already answer in frames.

    Pinned on a timeline that HAS overlap by
    `test_overlay_live_uses_finished_video_time_across_a_dissolve`;
    measured on the real 19-shot `captions_test_project.json` (12
    dissolves + 2 fades, 5.2s of overlap) where both totals are 58.329s.
    """
    if fps <= 0:
        return False
    ov_start = overlay.start_frame / fps
    ov_end = overlay.end_frame / fps
    return ov_start < cue_end_s and cue_start_s < ov_end


def _occupied_names(
    *,
    scaled: Sequence[CaptionPlacement],
    overlay_cues: Sequence[OverlayCue],
    cue_start_s: float,
    cue_end_s: float,
    fps: int,
    image_width: int,
    image_height: int,
) -> set[str]:
    occupied: set[str] = set()
    for overlay in overlay_cues:
        if overlay.band is None:
            continue
        if not _overlay_live(
            overlay, cue_start_s=cue_start_s, cue_end_s=cue_end_s, fps=fps
        ):
            continue
        band_box = overlay.band.box_on(image_width, image_height)
        if band_box is None:
            continue
        for candidate in scaled:
            if boxes_overlap(candidate.box, band_box):
                occupied.add(candidate.name)
    return occupied


def apply_caption_placements(
    cues: list[CaptionCue],
    shot_images: Mapping[str, Path],
    overlay_cues: list[OverlayCue],
    *,
    shots: Sequence[Shot],
    canvas_width: int,
    canvas_height: int,
    fps: int,
) -> list[CaptionPlacement | None]:
    """One placement per caption cue, same order. Per-cue, not per word-walk line.

    Missing / unreadable plates fall back to bottom-centre. If every
    candidate is occupied, the least-busy of the three is kept (no fourth
    box). Same inputs → same placements (I5).
    """
    scaled = [
        scale_candidate(c, canvas_width=canvas_width, canvas_height=canvas_height)
        for c in CANDIDATE_BOXES
    ]
    bottom_centre = scaled[0]
    starts = compute_shot_start_times(list(shots))
    plate_cache: dict[str, Image.Image | None] = {}
    resolved: list[CaptionPlacement | None] = []

    for cue in cues:
        shot_id = _shot_id_for_cue(cue, shots, starts)
        if shot_id is None or shot_id not in plate_cache:
            path = shot_images.get(shot_id) if shot_id else None
            plate_cache[shot_id or ""] = _decode_plate(path)
        image = plate_cache.get(shot_id or "")

        if image is None:
            logger.info(
                "caption_placement.fallback",
                extra={
                    "shot_id": shot_id,
                    "reason": "missing_or_unreadable_plate",
                    "chosen": bottom_centre.name,
                },
            )
            resolved.append(bottom_centre)
            continue

        img_w, img_h = image.size
        # Candidate boxes are authored on the canvas; map onto the plate
        # the same fractional way PivotBand.box_on does (asset may differ).
        plate_scaled = [
            CaptionPlacement(
                name=c.name,
                an=c.an,
                margin_l=c.margin_l,
                margin_r=c.margin_r,
                margin_v=c.margin_v,
                box=(
                    round(c.box[0] * img_w / canvas_width),
                    round(c.box[1] * img_h / canvas_height),
                    round(c.box[2] * img_w / canvas_width),
                    round(c.box[3] * img_h / canvas_height),
                ),
            )
            for c in scaled
        ]

        # Occupancy: overlay bands and candidate boxes in plate space.
        occupied = _occupied_names(
            scaled=plate_scaled,
            overlay_cues=overlay_cues,
            cue_start_s=cue.start_s,
            cue_end_s=cue.end_s,
            fps=fps,
            image_width=img_w,
            image_height=img_h,
        )

        busyness: dict[str, float | None] = {}
        for candidate, plate_box in zip(scaled, plate_scaled, strict=True):
            try:
                busyness[candidate.name] = luma_stdev_in_box(image, plate_box.box)
            except ValueError:
                busyness[candidate.name] = None

        free = [c for c in scaled if c.name not in occupied]
        all_occupied = not free
        pool = free if free else list(scaled)

        # B023 ("does not bind loop variable `busyness`") is a false
        # positive here, and the `noqa` is deliberate rather than a
        # default-argument rebind: this closure is created, consumed by
        # the `min()` two lines down, and dropped, all inside ONE
        # iteration. It is never stored, returned, deferred or collected
        # into a list, so it can never outlive the `busyness` it read —
        # the bug B023 exists to catch. Rebinding `busyness` as a hidden
        # default argument would silence the same warning while making
        # the sort key read worse, so the reason lives here instead.
        def _sort_key(c: CaptionPlacement) -> tuple[float, int]:
            value = busyness.get(c.name)  # noqa: B023 — see above, single-iteration closure
            # Unmeasurable boxes sort last within the pool; table order
            # breaks remaining ties. Round to kill float dust on flat
            # plates (full-width boxes can accumulate ~1e-14 while a
            # narrower crop is exactly 0.0).
            rank = next(i for i, s in enumerate(scaled) if s.name == c.name)
            if value is None:
                return (math.inf, rank)
            return (round(value, 6), rank)

        chosen = min(pool, key=_sort_key)
        logger.info(
            "caption_placement.choice",
            extra={
                "shot_id": shot_id,
                "cue_start_s": cue.start_s,
                "cue_end_s": cue.end_s,
                "busyness": {
                    name: (round(v, 3) if v is not None else None)
                    for name, v in busyness.items()
                },
                "occupied": sorted(occupied),
                "chosen": chosen.name,
                "all_occupied": all_occupied,
            },
        )
        if all_occupied:
            logger.info(
                "caption_placement.all_occupied",
                extra={"chosen": chosen.name, "shot_id": shot_id},
            )
        resolved.append(chosen)

    return resolved


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def caption_placement_content_hash(
    placements: list[CaptionPlacement | None] | None,
    *,
    candidates: Sequence[CandidateBox] = CANDIDATE_BOXES,
) -> str | None:
    """Hash candidate table + per-cue chosen placements. None → None.

    The candidate table is always in the payload so retuning a box
    fraction misses the cache even when every cue still picks the same
    name (K17.4).
    """
    if placements is None:
        return None
    payload = {
        "candidates": [
            {
                "name": c.name,
                "an": c.an,
                "margin_l_frac": c.margin_l_frac,
                "margin_r_frac": c.margin_r_frac,
                "margin_v_frac": c.margin_v_frac,
                "box_frac": list(c.box_frac),
            }
            for c in candidates
        ],
        "placements": [
            None
            if p is None
            else {
                "name": p.name,
                "an": p.an,
                "margin_l": p.margin_l,
                "margin_r": p.margin_r,
                "margin_v": p.margin_v,
                "box": list(p.box),
            }
            for p in placements
        ],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
