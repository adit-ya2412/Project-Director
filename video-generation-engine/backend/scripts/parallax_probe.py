"""Parallax / element-animation probe: continuous motion from illustrated
stills, with NO per-shot video generation (ad hoc, feeds
docs/plans/animated_explainer.md A4 and remotion_integration.md §7).

## The question

The user wants continuous motion, not a camera push over a fixed picture,
and image-to-video is too expensive: `fal_video_cost_cents_estimate = 50`
against 4c for a still, and `max_video_shots_per_project` caps motion
shots at ~8 of 61 for a script this length precisely because of that
ratio. 61 animated shots at 54c would be ~$33 against that script's own
$24.50 budget cap - over.

Parallax costs NOTHING per shot at render time. The only cost is one
extra generated LAYER per shot (4c), and the motion itself is ffmpeg.

## Why flat illustration makes this tractable

Layer separation is the hard part of parallax, and it is hard on
PHOTOGRAPHS - soft hair edges, motion blur, depth ambiguity. Flat
editorial illustration has none of that: the shapes are flat, the edges
are hard, and the palette is fixed and known. So the subject can be
generated on a solid key colour and chroma-keyed out deterministically,
in ffmpeg, with no depth model and no segmentation model.

Magenta is the key colour: it is nowhere in the world's declared palette
(slate blue, warm amber, off-white, charcoal), so `colorkey` cannot eat
part of the subject.

## Existing plumbing this would reuse

The Timeline ALREADY carries two prompts and two asset plans per shot -
`prompt`/`secondary_prompt` and `asset_plan`/`secondary_asset_plan` -
added for `split_frame`, where they are two stacked PANELS. A parallax
shot is the same data shape (two images for one shot) composited
differently at render time. This probe does not touch that code; it only
establishes whether the RESULT is worth wiring.

## What it produces

Three clips, all 5s, 720x1280 (the real `archival_montage` canvas):

- **A - two-layer parallax.** Background and subject drift at different
  rates. The classic 2.5D read.
- **B - three-layer parallax.** Adds a near-foreground layer, so there
  are three different rates and the depth is unambiguous.
- **C - element animation.** Background completely static; the SUBJECT
  slides and fades in on its own. This is A4's register - content
  moving, not the camera - and it is the one Ken Burns can never do.

Makes NO decision and changes NO production code. Reuses the illustrated
stills already in `tmp/character-probe/` as the background, generates at
most two new layers, and writes clips plus an HTML page to
`tmp/parallax-probe/`. Never prints the API key.

    .venv/Scripts/python.exe backend/scripts/parallax_probe.py --estimate
    .venv/Scripts/python.exe backend/scripts/parallax_probe.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.providers.fal_queue import FalQueueClient  # noqa: E402

_SRC = _REPO / "tmp" / "character-probe"
_OUT = _REPO / "tmp" / "parallax-probe"

# The background layer comes from the illustrated probe - already paid
# for, and the point is that these composite into ONE world.
_BACKGROUND = _SRC / "il_q2b_hagwon.png"

_W, _H = 720, 1280
_FPS = 30
_DUR = 5.0
# Layers are generated oversized so there is room to travel. 1.2x gives
# 144px of horizontal slack and 256px vertical - the same "scale must
# COVER the output" rule long_form_direction.md §4.7 states for PAN
# (pinning one axis is a crash, so both are scaled).
_OVER = 1.2
_LW, _LH = int(_W * _OVER), int(_H * _OVER)
_X0, _Y0 = -(_LW - _W) // 2, -(_LH - _H) // 2

# The key colour is SAMPLED from the delivered image, never assumed.
# Measured 2026-09-04: asked for pure #FF00FF, seedream returned
# ~#B43E7E - it harmonised the key colour into the world's own limited
# palette and then laid the paper grain over it, so the requested value
# was off by ~120 in the red channel and the plate varied +-10 per
# channel across the field. A hardcoded key silently matched nothing and
# the "cut-out" composited as an opaque rectangle.
#
# Sampling is also the more correct design regardless of the model: it
# is derived from the image bytes, so it is deterministic (I5) and it
# cannot drift out of agreement with what was actually delivered.
_KEY_SIMILARITY = 0.16  # covers the grain's +-10/channel spread
_KEY_BLEND = 0.05  # flat art has hard edges; a narrow blend keeps them crisp

_WORLD = (
    "Flat editorial illustration in a strictly limited palette: muted slate blue, "
    "warm amber, off-white and charcoal. Soft paper-grain texture, simple geometric "
    "shapes, no outlines, flat shading with a single soft light direction. "
    "Restrained and serious in tone - documentary, not cute, not corporate. "
    "Modern print-magazine illustration. No text, no watermark."
)
_KEYED = (
    "The subject is isolated on a COMPLETELY UNIFORM SOLID MAGENTA background "
    "(pure #FF00FF), edge to edge, with no shadow, no gradient, no texture and no "
    "other object anywhere in the frame."
)


@dataclass(frozen=True)
class Layer:
    slug: str
    label: str
    prompt: str


_LAYERS: list[Layer] = [
    Layer(
        slug="px_subject",
        label="subject layer (keyed)",
        prompt=(
            f"{_WORLD} A single teenage East Asian student with black hair, seen "
            "entirely FROM BEHIND - the back of his head, shoulders and upper back "
            "only, his face turned away and not visible. He wears a dark green hooded "
            "jacket. He is seated, cropped at the waist. "
            f"{_KEYED}"
        ),
    ),
    Layer(
        slug="px_foreground",
        label="near-foreground layer (keyed)",
        prompt=(
            f"{_WORLD} The backs of two empty classroom chairs and the near edge of a "
            "desk, seen close-up from behind as a near-foreground element, occupying "
            "the lower third of the frame only. Nothing else. "
            f"{_KEYED}"
        ),
    ),
]


async def _generate(queue: FalQueueClient, layer: Layer) -> tuple[bool, str]:
    path = _OUT / f"{layer.slug}.png"
    if path.exists():
        return True, "reused (already on disk, 0 paid calls)"
    arguments = {
        "prompt": layer.prompt,
        "image_size": {"width": _LW, "height": _LH},
        "num_images": 1,
    }
    try:
        job_id = await queue.submit(settings.fal_image_model, arguments)
    except Exception as exc:  # noqa: BLE001
        return False, f"submit failed: {exc}"
    for _ in range(45):
        try:
            state, result, error = await queue.poll_once(settings.fal_image_model, job_id)
        except Exception as exc:  # noqa: BLE001
            return False, f"poll failed: {exc}"
        if state == "failed":
            return False, f"generation failed: {error}"
        if state == "completed":
            images = (result or {}).get("images") or []
            if not images:
                return False, "no images returned"
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(images[0]["url"], follow_redirects=True)
                response.raise_for_status()
            path.write_bytes(response.content)
            return True, "generated"
        await asyncio.sleep(2.0)
    return False, "timed out"


def _base() -> str:
    return f"color=c=0x101418:s={_W}x{_H}:r={_FPS}:d={_DUR}[base]"


def _sample_key(path: Path) -> str:
    """Median colour of the TOP border strip, as `0xRRGGBB`.

    The top strip only: the subject is cropped at the waist and touches
    the BOTTOM edge, so a corner-average would sample his jacket. Median
    rather than mean so a stray pixel of subject cannot pull the key.
    """
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, _height = rgb.size
        pixels = [rgb.getpixel((x, y)) for x in range(0, width, 5) for y in range(0, 24, 4)]
    channels = [sorted(p[i] for p in pixels)[len(pixels) // 2] for i in range(3)]
    return "0x%02X%02X%02X" % tuple(channels)


def _layer_in(index: int, name: str, *, keyed: bool, key: str | None = None) -> str:
    """Scale to the oversized working size, then key if it is a cut-out."""
    chain = f"[{index}:v]scale={_LW}:{_LH},setsar=1"
    if keyed:
        chain += f",colorkey={key}:{_KEY_SIMILARITY}:{_KEY_BLEND}"
    return f"{chain},format=rgba[{name}]"


def _drift(travel_x: float, travel_y: float = 0.0) -> tuple[str, str]:
    """Linear travel over the clip, expressed for `overlay`'s per-frame
    x/y. Deterministic in `t` only - no RNG, no wall-clock (I5)."""
    x = f"{_X0}-({travel_x}*t/{_DUR})"
    y = f"{_Y0}-({travel_y}*t/{_DUR})"
    return x, y


def _run(inputs: list[Path], filter_complex: str, out_map: str, out: Path) -> tuple[bool, str]:
    cmd = [settings.ffmpeg_binary, "-y"]
    for path in inputs:
        cmd += ["-loop", "1", "-t", str(_DUR), "-i", str(path)]
    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        out_map,
        "-r",
        str(_FPS),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        return False, tail
    return True, "ok"


def _clip_a(bg: Path, subject: Path) -> tuple[bool, str]:
    bx, by = _drift(24)
    sx, sy = _drift(110)
    fc = ";".join(
        [
            _base(),
            _layer_in(0, "bg", keyed=False),
            _layer_in(1, "sub", keyed=True, key=_sample_key(subject)),
            f"[base][bg]overlay=x='{bx}':y='{by}':shortest=1[b1]",
            f"[b1][sub]overlay=x='{sx}':y='{sy}'[out]",
        ]
    )
    return _run([bg, subject], fc, "[out]", _OUT / "clip_a_two_layer.mp4")


def _clip_b(bg: Path, subject: Path, fg: Path) -> tuple[bool, str]:
    bx, by = _drift(18)
    sx, sy = _drift(90)
    fx, fy = _drift(230)
    fc = ";".join(
        [
            _base(),
            _layer_in(0, "bg", keyed=False),
            _layer_in(1, "sub", keyed=True, key=_sample_key(subject)),
            _layer_in(2, "fg", keyed=True, key=_sample_key(fg)),
            f"[base][bg]overlay=x='{bx}':y='{by}':shortest=1[b1]",
            f"[b1][sub]overlay=x='{sx}':y='{sy}'[b2]",
            f"[b2][fg]overlay=x='{fx}':y='{fy}'[out]",
        ]
    )
    return _run([bg, subject, fg], fc, "[out]", _OUT / "clip_b_three_layer.mp4")


def _clip_c(bg: Path, subject: Path) -> tuple[bool, str]:
    """Element animation: the background never moves; the SUBJECT slides
    up and fades in. Ken Burns cannot express this at all."""
    slide = 90
    sx = f"{_X0}"
    sy = f"{_Y0}+{slide}*(1-min(1\\,t/1.6))"
    fc = ";".join(
        [
            _base(),
            _layer_in(0, "bg", keyed=False),
            _layer_in(1, "sub", keyed=True, key=_sample_key(subject))
            + ";[sub]fade=t=in:st=0.2:d=1.2:alpha=1[subf]",
            f"[base][bg]overlay=x={_X0}:y={_Y0}:shortest=1[b1]",
            f"[b1][subf]overlay=x='{sx}':y='{sy}'[out]",
        ]
    )
    return _run([bg, subject], fc, "[out]", _OUT / "clip_c_element_anim.mp4")


def _write_page(results: dict[str, str]) -> Path:
    rows = "\n".join(
        f"<div class=c><video src='{name}' controls loop muted autoplay></video>"
        f"<div class=l>{label}</div><div class=s>{status}</div></div>"
        for name, (label, status) in results.items()
    )
    html = f"""<!doctype html><meta charset=utf-8><title>Parallax probe</title>
<style>body{{background:#141414;color:#e8e8e8;font:14px system-ui;padding:24px}}
h1{{font-size:20px}}p{{color:#9a9a9a;max-width:70ch;line-height:1.5}}
.row{{display:flex;gap:18px;flex-wrap:wrap}}.c{{width:260px}}
video{{width:260px;border-radius:6px;background:#000}}
.l{{margin-top:6px;color:#ddd}}.s{{color:#8a8a8a;font-size:12px}}</style>
<h1>Parallax / element animation &mdash; no video generation</h1>
<p>All three clips are ffmpeg over generated STILLS. Zero per-shot video cost.
A and B are parallax (layers moving at different rates). C is element animation:
the background is completely static and only the subject moves &mdash; the thing
Ken Burns cannot do. Judge whether this reads as animation or as a moving
photograph.</p>
<div class=row>{rows}</div>"""
    path = _OUT / "sheet.html"
    path.write_text(html, encoding="utf-8")
    return path


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimate", action="store_true", help="print prompts and cost only")
    args = parser.parse_args()

    _OUT.mkdir(parents=True, exist_ok=True)
    todo = [layer for layer in _LAYERS if not (_OUT / f"{layer.slug}.png").exists()]

    if args.estimate:
        for layer in _LAYERS:
            print(f"\n-- {layer.label}  [{_LW}x{_LH}]\n{layer.prompt}")
        rate = settings.fal_image_cost_cents_estimate
        print(f"\n=== {len(todo)} new layers x {rate}c = {len(todo) * rate}c ===")
        print("(ffmpeg composition is free; clips cost nothing per shot)")
        return 0

    if not _BACKGROUND.exists():
        print(f"missing background {_BACKGROUND} - run the --illustrated probe first", file=sys.stderr)
        return 2
    if todo and not settings.fal_key:
        print("FAL_KEY is not set", file=sys.stderr)
        return 2

    queue = FalQueueClient()
    paid = 0
    for layer in _LAYERS:
        ok, note = await _generate(queue, layer)
        if note == "generated":
            paid += 1
        print(f"  {layer.label}: {note}", flush=True)
        if not ok:
            print("layer generation failed - stopping", file=sys.stderr)
            return 1

    subject = _OUT / "px_subject.png"
    fg = _OUT / "px_foreground.png"

    results: dict[str, tuple[str, str]] = {}
    for name, label, fn in (
        ("clip_a_two_layer.mp4", "A - two-layer parallax", lambda: _clip_a(_BACKGROUND, subject)),
        (
            "clip_b_three_layer.mp4",
            "B - three-layer parallax",
            lambda: _clip_b(_BACKGROUND, subject, fg),
        ),
        (
            "clip_c_element_anim.mp4",
            "C - element animation (static bg)",
            lambda: _clip_c(_BACKGROUND, subject),
        ),
    ):
        ok, note = fn()
        print(f"  {label}: {'ok' if ok else 'FAILED'}", flush=True)
        if not ok:
            print(note, file=sys.stderr)
        results[name] = (label, "ok" if ok else f"failed: {note[:120]}")

    page = _write_page(results)
    summary = {
        "out_dir": str(_OUT),
        "sheet": str(page),
        "background_reused": str(_BACKGROUND),
        "paid_generation_calls": paid,
        "estimated_cents": paid * settings.fal_image_cost_cents_estimate,
        "per_shot_render_cost": 0,
        "clips": {k: v[1] for k, v in results.items()},
    }
    (_OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nOpen: {page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
