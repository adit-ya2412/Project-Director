"""Shared real-media builder for tests that need a genuine, decodable h264
clip without a network call or a paid API - generalised from
`tests/integration/test_motion_classification.py::_make_real_clip` (plan
docs/plans/baked_in_letterbox.md §7: "Reuse the existing synthetic-clip
builder rather than inventing one ... lift it somewhere both suites can
import").

`pad_to` is the addition over the original: wrapping ffmpeg's own
`testsrc` lavfi source in a `pad=` filter produces a clip whose real
picture is a known `width x height` box at a known `(x, y)` inside a
larger, genuinely black-bordered frame - exactly the "baked-in pillarbox"
shape `app/assets/letterbox_crop.py` exists to detect, with the true
answer known up front because this function chose it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.config import settings


def make_real_clip(
    path: Path,
    *,
    duration_s: float = 2.0,
    width: int = 64,
    height: int = 64,
    rate: int = 24,
    pad_to: tuple[int, int, int, int] | None = None,
) -> None:
    """Write a genuine h264 clip to `path` via ffmpeg's `testsrc` source.

    `pad_to`, if given, is `(out_width, out_height, x, y)`: the
    `width x height` testsrc picture is placed at `(x, y)` inside a larger
    `out_width x out_height` black frame (`pad=out_w:out_h:x:y:color=black`)
    - the real content box a letterbox-crop detector should independently
    recover is `(x, y, x + width, y + height)`.
    """
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration_s}:size={width}x{height}:rate={rate}",
    ]
    if pad_to is not None:
        out_w, out_h, x, y = pad_to
        args += ["-vf", f"pad={out_w}:{out_h}:{x}:{y}:color=black"]
    args += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, capture_output=True, check=True)
