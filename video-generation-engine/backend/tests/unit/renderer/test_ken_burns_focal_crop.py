"""RV-Q1: focal is measured on the original image and must be consumed
after the pre-zoompan scale+crop, not as if zoompan's iw/ih were the
source. Banded-image method from output_quality_pass.md §12.1.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.renderer.ken_burns import (
    WORKING_CANVAS_SCALE,
    build_zoompan_expression,
    compute_aimed_crop,
    ken_burns_crop_and_zoompan_focal,
    scale_increase_size,
)
from app.renderer.slideshow import RenderSettings, _ken_burns_filter
from app.schemas.timeline import Camera, CameraMovement

_FFMPEG = shutil.which("ffmpeg")

# Review's measured canvas: 1280×720 × 1.6 = 2048×1152, 600×800 portrait.
_ORIG_W, _ORIG_H = 600, 800
_OUT_W, _OUT_H = 1280, 720
_CANVAS_W = round(_OUT_W * WORKING_CANVAS_SCALE)
_CANVAS_H = round(_OUT_H * WORKING_CANVAS_SCALE)

_BAND_COLORS = [
    (255, 0, 0),  # 0
    (0, 255, 0),  # 1 green  — fy=0.20
    (0, 0, 255),  # 2 blue   — fy=0.35
    (255, 255, 0),  # 3 yellow
    (255, 0, 255),  # 4 magenta
    (0, 255, 255),
    (255, 128, 0),
    (128, 0, 255),
]


def test_scale_increase_matches_ffmpeg_9_portrait_into_landscape():
    assert _CANVAS_W == 2048
    assert _CANVAS_H == 1152
    assert scale_increase_size(_ORIG_W, _ORIG_H, _CANVAS_W, _CANVAS_H) == (2048, 2731)


def test_centre_focal_keeps_default_crop_and_centre_zoompan():
    crop_x, crop_y, residual = ken_burns_crop_and_zoompan_focal(
        _ORIG_W, _ORIG_H, _CANVAS_W, _CANVAS_H, (0.5, 0.5)
    )
    assert crop_x is None and crop_y is None and residual is None
    assert ken_burns_crop_and_zoompan_focal(
        _ORIG_W, _ORIG_H, _CANVAS_W, _CANVAS_H, None
    ) == (None, None, None)


def test_fy_020_clamps_crop_to_top_and_leaves_residual_for_zoompan():
    """Review table: fy=0.20 is outside the centred crop [0.289, 0.711]."""
    aimed = compute_aimed_crop(_ORIG_W, _ORIG_H, _CANVAS_W, _CANVAS_H, 0.5, 0.20)
    assert aimed.crop_y == 0
    # Subject at 0.20 of 2731px = 546px into the 1152 crop → residual ≈ 0.47
    assert aimed.residual_fy == pytest.approx(0.20 * 2731 / 1152, abs=0.01)
    crop_x, crop_y, residual = ken_burns_crop_and_zoompan_focal(
        _ORIG_W, _ORIG_H, _CANVAS_W, _CANVAS_H, (0.5, 0.20)
    )
    assert crop_y == 0
    assert residual is not None
    assert residual[1] == pytest.approx(aimed.residual_fy)


def test_unclamped_fy_035_crop_is_off_centre_residual_near_half():
    aimed = compute_aimed_crop(_ORIG_W, _ORIG_H, _CANVAS_W, _CANVAS_H, 0.5, 0.35)
    assert aimed.crop_y > 0
    assert aimed.residual_fy == pytest.approx(0.5, abs=0.02)


def _write_banded_png(path: Path) -> None:
    im = Image.new("RGB", (_ORIG_W, _ORIG_H))
    band_h = _ORIG_H // len(_BAND_COLORS)
    for i, color in enumerate(_BAND_COLORS):
        y0 = i * band_h
        y1 = _ORIG_H if i == len(_BAND_COLORS) - 1 else (i + 1) * band_h
        im.paste(color, (0, y0, _ORIG_W, y1))
    im.save(path)


def _centre_rgb(path: Path) -> tuple[int, int, int]:
    im = Image.open(path).convert("RGB")
    return im.getpixel((im.size[0] // 2, im.size[1] // 2))


def _nearest_band(rgb: tuple[int, int, int]) -> int:
    best, best_d = 0, 10**9
    for i, color in enumerate(_BAND_COLORS):
        d = sum(abs(a - b) for a, b in zip(rgb, color, strict=True))
        if d < best_d:
            best, best_d = i, d
    return best


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not on PATH")
def test_banded_portrait_fy_020_lands_on_green_not_yellow(tmp_path: Path):
    """§12.1: before the crop-aim fix, fy=0.20 showed band 3 (yellow)."""
    src = tmp_path / "bands.png"
    out = tmp_path / "out.png"
    _write_banded_png(src)

    settings = RenderSettings(
        width=_OUT_W,
        height=_OUT_H,
        fps=30,
        pixel_format="yuv420p",
        ffmpeg_binary=_FFMPEG,
    )
    crop_x, crop_y, residual = ken_burns_crop_and_zoompan_focal(
        _ORIG_W, _ORIG_H, _CANVAS_W, _CANVAS_H, (0.5, 0.20)
    )
    camera = Camera(movement=CameraMovement.PULL_BACK, intensity=1.0)
    expr = build_zoompan_expression(camera, frames=30, focal=residual)
    assert expr is not None
    filt = _ken_burns_filter(
        0, settings, "vout", expr, 30, crop_x=crop_x, crop_y=crop_y
    )
    result = subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-i",
            str(src),
            "-filter_complex",
            filt,
            "-map",
            "[vout]",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(out),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1500:]
    assert out.is_file()
    band = _nearest_band(_centre_rgb(out))
    assert band == 1, f"expected band 1 (green) at fy=0.20, got band {band}"
