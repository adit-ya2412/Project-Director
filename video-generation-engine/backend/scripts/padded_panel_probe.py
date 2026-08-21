"""Bake-off frames for the padded-panel leftover.

Human verdict 2026-08-20: crop-to-fill. The renderer now uses
`SPLIT_PANEL_FIT = "fill"`. This script still writes all three
treatments so the call stays inspectable.

    ../.venv/Scripts/python.exe scripts/padded_panel_probe.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.renderer.split_screen import build_split_filter, panel_heights  # noqa: E402

_ASSETS = (
    Path(__file__).resolve().parents[2]
    / "storage"
    / "58f0a5e6-008d-468e-862a-e365e463878e"
    / "assets"
)
_OUT = Path(__file__).resolve().parents[2] / "tmp" / "padded-panel"
_WIDTH = 720
_HEIGHT = 1280
_GUTTER = 16

# 3:2 landscapes (the review's padding case) and the Gorki reconnaissance
# map (legend in the corner — the crop that Ken Burns already loses).
_PLANT_TOP = _ASSETS / "4363a4319390cdcda982d2b6bc684c8e3c6d1c28b8df3449b4fda68c72ee05e6.jpg"
_PLANT_BOT = _ASSETS / "c76ad98f605bc9e8cd51b238e790b9db6e49e82581dbf9fc9e714143ea856ccf.jpg"
_MAP = _ASSETS / "73eabb13c51145691282a0d9fea55f6ba4055212c63f1cd749e08592926e1c48.jpg"


def _letterbox(index: int, panel_h: int, name: str) -> str:
    return (
        f"[{index}:v]scale={_WIDTH}:{panel_h}:force_original_aspect_ratio=decrease,"
        f"pad={_WIDTH}:{panel_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[{name}]"
    )


def _fill(index: int, panel_h: int, name: str) -> str:
    return (
        f"[{index}:v]scale={_WIDTH}:{panel_h}:force_original_aspect_ratio=increase,"
        f"crop={_WIDTH}:{panel_h},setsar=1[{name}]"
    )


def _stack(top: str, bot: str) -> str:
    return f"{top};{bot};[spt][spb]vstack=inputs=2,format=yuv420p[vout]"


def _gutter_letterbox() -> str:
    top_h, bot_h = panel_heights(_HEIGHT - _GUTTER)
    top = _letterbox(0, top_h, "spt0")
    bot = _letterbox(1, bot_h, "spb")
    # Gutter sits on the top panel's bottom edge so vstack still fills
    # the frame exactly.
    pad = f"[spt0]pad={_WIDTH}:{top_h + _GUTTER}:0:0:black,setsar=1[spt]"
    return f"{top};{bot};{pad};[spt][spb]vstack=inputs=2,format=yuv420p[vout]"


def _current_letterbox() -> str:
    return build_split_filter(
        0,
        1,
        width=_WIDTH,
        height=_HEIGHT,
        fps=30,
        pixel_format="yuv420p",
        label="vout",
        hold_s=0.0,
    )


def _crop_fill() -> str:
    top_h, bot_h = panel_heights(_HEIGHT)
    return _stack(_fill(0, top_h, "spt"), _fill(1, bot_h, "spb"))


def _render(top: Path, bot: Path, filter_graph: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(top),
            "-i",
            str(bot),
            "-filter_complex",
            filter_graph,
            "-map",
            "[vout]",
            "-frames:v",
            "1",
            str(dest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    pairs = {
        "plants-3x2": (_PLANT_TOP, _PLANT_BOT),
        "map-plus-plant": (_MAP, _PLANT_TOP),
    }
    layouts = {
        "letterbox": _current_letterbox(),
        "crop-fill": _crop_fill(),
        "letterbox-gutter": _gutter_letterbox(),
    }
    for pair_name, (top, bot) in pairs.items():
        for layout_name, graph in layouts.items():
            dest = _OUT / f"{pair_name}-{layout_name}.png"
            _render(top, bot, graph, dest)
            print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
