"""Subject focal point — asset-derived Ken Burns aim (OQ-2).

A focal point is a property of the image bytes, not of `Camera`. Same
image, same subject, every style. Persisted as a JSON sidecar next to
the asset file, keyed by content hash (`{hash}.focal.json`), so no
migration / no Timeline field is required.

Coverage is incomplete by design: only searched top candidates that
pass `check_candidate_plausibility` get a vision-derived point.
Generated clips, entity-curated assets, and skipped checks fall back
to the geometric centre (0.5, 0.5) — and that fallback MUST be logged,
because a systematic vision failure would otherwise look "correct".
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_FOCAL: tuple[float, float] = (0.5, 0.5)
FOCAL_SOURCE_VISION = "vision"
FOCAL_SOURCE_FALLBACK = "fallback"
# long_form_direction.md A13b: a human stating the focal point directly
# (per-shot override upload). Outranks a vision answer for the same
# content hash - the same "human decision wins" precedent `asset_locked`
# already sets for a re-plan - by being written last and unconditionally
# whenever coordinates are supplied, overwriting any existing sidecar.
FOCAL_SOURCE_HUMAN = "human"


def sidecar_path(assets_dir: Path, content_hash: str) -> Path:
    """`{assets_dir}/{content_hash}.focal.json` — keyed by content hash."""
    return assets_dir / f"{content_hash}.focal.json"


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_focal(fx: float | None, fy: float | None) -> tuple[float, float] | None:
    """Return a valid (fx, fy) in 0..1, or None when either coord is missing."""
    if fx is None or fy is None:
        return None
    try:
        x, y = float(fx), float(fy)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return (clamp_unit(x), clamp_unit(y))


def write_focal_sidecar(
    assets_dir: Path,
    content_hash: str,
    *,
    focal_x: float,
    focal_y: float,
    source: str,
) -> Path:
    assets_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_path(assets_dir, content_hash)
    payload = {
        "content_hash": content_hash,
        "focal_source": source,
        "focal_x": clamp_unit(focal_x),
        "focal_y": clamp_unit(focal_y),
    }
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return path


def read_focal_sidecar(assets_dir: Path, content_hash: str) -> tuple[float, float] | None:
    """Load a vision-derived focal, or None when absent / unreadable."""
    path = sidecar_path(assets_dir, content_hash)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return normalize_focal(data.get("focal_x"), data.get("focal_y"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def persist_vision_focal(
    assets_dir: Path,
    content_hash: str,
    *,
    focal_x: float | None,
    focal_y: float | None,
    shot_id: str | None = None,
) -> tuple[float, float]:
    """Write a sidecar from a depiction verdict. Invalid/missing → centre
    + logged fallback (OQ-2 §2.6 / §5.2)."""
    normalised = normalize_focal(focal_x, focal_y)
    if normalised is None:
        logger.warning(
            "focal.fallback",
            extra={
                "content_hash": content_hash,
                "shot_id": shot_id,
                "reason": "vision_missing_or_invalid",
                "focal_x": focal_x,
                "focal_y": focal_y,
            },
        )
        write_focal_sidecar(
            assets_dir,
            content_hash,
            focal_x=DEFAULT_FOCAL[0],
            focal_y=DEFAULT_FOCAL[1],
            source=FOCAL_SOURCE_FALLBACK,
        )
        return DEFAULT_FOCAL
    write_focal_sidecar(
        assets_dir,
        content_hash,
        focal_x=normalised[0],
        focal_y=normalised[1],
        source=FOCAL_SOURCE_VISION,
    )
    return normalised


def resolve_shot_focals(
    *,
    shot_ids: list[str],
    content_hashes: dict[str, str],
    assets_dir: Path,
) -> dict[str, tuple[float, float] | None]:
    """Resolve once per shot for render (RV2). Missing sidecar → None
    (caller logs fallback and aims at centre)."""
    out: dict[str, tuple[float, float] | None] = {}
    for shot_id in shot_ids:
        content_hash = content_hashes.get(shot_id)
        if not content_hash:
            out[shot_id] = None
            logger.warning(
                "focal.fallback",
                extra={"shot_id": shot_id, "reason": "no_content_hash"},
            )
            continue
        focal = read_focal_sidecar(assets_dir, content_hash)
        if focal is None:
            logger.warning(
                "focal.fallback",
                extra={
                    "shot_id": shot_id,
                    "content_hash": content_hash,
                    "reason": "no_sidecar",
                },
            )
        out[shot_id] = focal
    return out


def format_focal_fingerprint(focal: tuple[float, float] | None) -> str:
    """Fingerprint payload value: `\"fx,fy\"` or `\"\"` when unresolved
    so a later resolve cannot cache-HIT the gap (R16)."""
    if focal is None:
        return ""
    return f"{focal[0]:.6f},{focal[1]:.6f}"
