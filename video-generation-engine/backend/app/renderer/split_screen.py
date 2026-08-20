"""Split-screen composite (plan §2.6). Two stills, top and bottom.

9:16 makes a vertical stack the usable layout: a side-by-side split
would be two ~540×1920 strips. Ken Burns correctly still returns
`None` for `SPLIT_FRAME` — this is a second input, not a `zoompan`
expression.

Missing second still, or a motion clip on either panel, degrades to
the single-image static path. Never a fake split of one photograph.
"""

from pathlib import Path

from app.renderer.motion import MediaKind
from app.schemas.timeline import CameraMovement


def panel_heights(frame_height: int) -> tuple[int, int]:
    """Top and bottom panel heights that sum to `frame_height` even when
    the frame is odd."""
    top = frame_height // 2
    return top, frame_height - top


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
    """Scale each still into half the frame (letterboxed), `vstack`,
    then the same fps/tpad/format envelope `_normalize_filter` uses so
    the stream is exactly `duration_s` at `fps`."""
    top_h, bot_h = panel_heights(height)

    def _panel(index: int, panel_h: int, name: str) -> str:
        return (
            f"[{index}:v]scale={width}:{panel_h}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{panel_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[{name}]"
        )

    return (
        f"{_panel(top_index, top_h, 'spt')};"
        f"{_panel(bot_index, bot_h, 'spb')};"
        f"[spt][spb]vstack=inputs=2,"
        f"fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={hold_s:.6f},"
        f"fps={fps},"
        f"format={pixel_format}[{label}]"
    )
