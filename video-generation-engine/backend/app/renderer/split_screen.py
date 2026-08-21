"""Split-screen composite (plan §2.6). Two stills, top and bottom.

9:16 makes a vertical stack the usable layout; 16:9 inverts that to
side-by-side (`hstack`). Ken Burns correctly still returns `None` for
`SPLIT_FRAME` — this is a second input, not a `zoompan` expression.

Missing second still, or a motion clip on either panel, degrades to
the single-image static path. Never a fake split of one photograph.

Panel fit (human verdict 2026-08-20, padded-panel bake-off): crop-to-
fill. Letterbox kept the whole still (the Gorki map legend survives)
but left ~25% pad on 3:2 archival photos. Fill covers each half of the
9:16 frame; edges are discarded — the same crop Ken Burns already
takes on a static shot.
"""

from pathlib import Path

from app.renderer.motion import MediaKind
from app.schemas.timeline import CameraMovement

# Hashed into every render/run/shot-stream fingerprint so a later
# letterbox revert cannot cache-HIT these filled frames (§7 / R2).
SPLIT_PANEL_FIT = "fill"


def panel_heights(frame_height: int) -> tuple[int, int]:
    """Top and bottom panel heights that sum to `frame_height` even when
    the frame is odd."""
    top = frame_height // 2
    return top, frame_height - top


def panel_widths(frame_width: int) -> tuple[int, int]:
    """Left and right panel widths that sum to `frame_width` even when
    the frame is odd."""
    left = frame_width // 2
    return left, frame_width - left


def should_composite_split(
    movement: CameraMovement,
    *,
    secondary_path: Path | None,
    top_kind: MediaKind,
    bot_kind: MediaKind | None,
) -> bool:
    return (
        movement == CameraMovement.SPLIT_FRAME
        and secondary_path is not None
        and top_kind is MediaKind.STILL
        and bot_kind is MediaKind.STILL
    )


def build_split_filter(
    top_index: int,
    bot_index: int,
    *,
    width: int,
    height: int,
    fps: int,
    pixel_format: str,
    label: str,
    hold_s: float,
) -> str:
    """Scale each still to cover half the frame (crop-to-fill).

    Portrait (`height >= width`): `vstack` (top/bottom). Landscape:
    `hstack` (left/right). Layout is derived from the canvas so the
    render fingerprint already covers it via width/height (§19.3).
    """
    def _cover(index: int, panel_w: int, panel_h: int, name: str) -> str:
        return (
            f"[{index}:v]scale={panel_w}:{panel_h}:force_original_aspect_ratio=increase,"
            f"crop={panel_w}:{panel_h},setsar=1[{name}]"
        )

    if width > height:
        left_w, right_w = panel_widths(width)
        stack = (
            f"{_cover(top_index, left_w, height, 'spl')};"
            f"{_cover(bot_index, right_w, height, 'spr')};"
            f"[spl][spr]hstack=inputs=2,"
        )
    else:
        top_h, bot_h = panel_heights(height)
        stack = (
            f"{_cover(top_index, width, top_h, 'spt')};"
            f"{_cover(bot_index, width, bot_h, 'spb')};"
            f"[spt][spb]vstack=inputs=2,"
        )
    return (
        f"{stack}"
        f"fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={hold_s:.6f},"
        f"fps={fps},"
        f"format={pixel_format}[{label}]"
    )
