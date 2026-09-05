"""F1a + F2b micro-test: two layers, the real crop, the real compositor. 8c.

The cheapest possible check of the two things F1a/F2b claim, before
committing ~50c to a full cut:

1. **Did the deterministic substrate crop kill the paper border?**
   §1.7 and `P-IF-F1-fixes` both tried to fix this with prompt wording and
   both failed; §8.1 replaced that with an oversize-then-centre-crop. This
   requests through the PRODUCTION resolver
   (`resolve_generation_request_format`) and crops with the PRODUCTION
   function (`center_crop_to_canvas`) - not a reimplementation - so a pass
   here is a pass for the real path.
2. **Does the chroma key work on a real generated subject layer?**
   The probe proved it on one hand-written prompt; this uses the wording the
   shipped style fragment actually asks the Shot Planner for, and keys with
   the production `sample_key_colour` + `keyed_fraction` + the §4.5 guard.

Then it composites with the production
`build_two_layer_parallax_filter_complex` and writes a clip, so the motion
is judged on production code rather than on `parallax_probe.py`'s prototype.

Deliberately NOT the full pipeline: no project, no planner, no narration, no
DB, no approval gate. Two paid image calls and ffmpeg. Everything it touches
on the production side is a pure function.

    .venv/Scripts/python.exe backend/scripts/f1a_f2b_microtest.py --estimate
    .venv/Scripts/python.exe backend/scripts/f1a_f2b_microtest.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

from app.assets.substrate_crop import center_crop_to_canvas  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.providers.fal_queue import FalQueueClient  # noqa: E402
from app.schemas.timeline import LayerRole  # noqa: E402
from app.renderer.parallax import (  # noqa: E402
    ParallaxKeyGuardError,
    ParallaxLayerInput,
    build_two_layer_parallax_filter_complex,
    check_keyed_fraction,
    keyed_fraction,
    sample_key_colour,
)
from app.script.styles import (  # noqa: E402
    resolve_generation_request_format,
    resolve_render_format,
)

_STYLE = "illustrated_risograph"
_OUT = _REPO / "tmp" / "f1a-f2b-microtest"
_FPS = 30
_DURATION_S = 5.0

# The world token exactly as the shipped fragment carries it, so this tests
# the real thing rather than a paraphrase.
_WORLD = (
    "Bold risograph print illustration: only three spot colours - deep teal, "
    "fluorescent orange and black - carrying the coarse tooth and grain of off-white "
    "uncoated paper through the whole image as its surface. Heavy visible ink grain, "
    "coarse halftone dot texture, deliberate slight misregistration where colours "
    "overlap, high contrast, simplified graphic shapes. Bold, graphic and urgent in "
    "feeling. The image fills the frame completely, edge to edge."
)

# Layer wording follows the fragment's own parallax bullet: background is a
# full setting described exactly as any shot would be; subject is the figure
# alone on an even magenta field.
_BACKGROUND = (
    f"{_WORLD} A private cram-school classroom at 2am: rows of narrow desks under hard "
    "fluorescent ceiling light, stacks of workbooks, a dark window showing distant city "
    "lights. No people. No text, no lettering, no numbers, no watermark."
)
_SUBJECT = (
    f"{_WORLD} A single school-age Korean boy with straight black hair in a neat short "
    "cut, light-medium skin tone, slim build, wearing a white shirt with a dark backpack, "
    "seated and seen entirely FROM BEHIND - the back of his head and shoulders only, his "
    "face turned away and not visible. He is the sole content in the frame, isolated on "
    "one perfectly even solid magenta field that fills the frame completely, edge to "
    "edge, with flat shadowless lighting. No text, no lettering, no numbers, no watermark."
)


def _edge_report(path: Path) -> str:
    """Pale, uniform frame edges are the substrate-border signature (§8.1)."""
    import statistics

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        w, h = rgb.size
        edge = [rgb.getpixel((x, y)) for x in range(0, w, 9) for y in (2, 5, h - 6, h - 3)]
        edge += [rgb.getpixel((x, y)) for y in range(0, h, 9) for x in (2, 5, w - 6, w - 3)]
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in edge]
    mean, sd = statistics.mean(lum), statistics.pstdev(lum)
    verdict = "BORDER STILL PRESENT" if mean > 200 and sd < 25 else "clean"
    return f"edge_lum={mean:6.1f} sd={sd:5.1f}  {verdict}"


async def _generate(queue: FalQueueClient, prompt: str, w: int, h: int, out: Path) -> bool:
    if out.exists():
        print(f"  {out.name}: reused (0c)")
        return True
    args = {"prompt": prompt, "image_size": {"width": w, "height": h}, "num_images": 1}
    job = await queue.submit(settings.fal_image_model, args)
    for _ in range(45):
        state, result, error = await queue.poll_once(settings.fal_image_model, job)
        if state == "failed":
            print(f"  {out.name}: FAILED {error}", file=sys.stderr)
            return False
        if state == "completed":
            url = ((result or {}).get("images") or [{}])[0].get("url")
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
            out.write_bytes(resp.content)
            print(f"  {out.name}: generated (4c)")
            return True
        await asyncio.sleep(2.0)
    print(f"  {out.name}: timed out", file=sys.stderr)
    return False


async def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--estimate", action="store_true")
    args = ap.parse_args()

    canvas = resolve_render_format(_STYLE)
    request = resolve_generation_request_format(_STYLE, canvas)
    print(f"style={_STYLE}  canvas={canvas.width}x{canvas.height}  "
          f"request={request.width}x{request.height}  "
          f"(oversize {settings.substrate_crop_oversize_fraction:.0%})")

    if args.estimate:
        for name, p in (("background", _BACKGROUND), ("subject", _SUBJECT)):
            print(f"\n-- {name}\n{p}")
        print(f"\n=== 2 images x {settings.fal_image_cost_cents_estimate}c = "
              f"{2 * settings.fal_image_cost_cents_estimate}c (ffmpeg free) ===")
        return 0

    if not settings.fal_key:
        print("FAL_KEY not set", file=sys.stderr)
        return 2
    _OUT.mkdir(parents=True, exist_ok=True)
    queue = FalQueueClient()

    raw = {"background": _OUT / "raw_background.png", "subject": _OUT / "raw_subject.png"}
    print("\nGenerating at the OVERSIZED request size:")
    for name, prompt in (("background", _BACKGROUND), ("subject", _SUBJECT)):
        if not await _generate(queue, prompt, request.width, request.height, raw[name]):
            return 1

    print("\nCropping with the PRODUCTION crop, and checking the edges:")
    cropped: dict[str, Path] = {}
    for name in ("background", "subject"):
        out = _OUT / f"{name}.png"
        out.write_bytes(center_crop_to_canvas(raw[name].read_bytes(), canvas.width, canvas.height))
        cropped[name] = out
        print(f"  {name:11} BEFORE crop  {_edge_report(raw[name])}")
        print(f"  {name:11} AFTER  crop  {_edge_report(out)}")

    print("\nKeying the subject with the production sampler + §4.5 guard:")
    subject_bytes = cropped["subject"].read_bytes()
    key = sample_key_colour(subject_bytes)
    frac = keyed_fraction(subject_bytes, key)
    print(f"  sampled key={key}  keyed_fraction={frac:.3f}")
    guard = "PASS"
    try:
        check_keyed_fraction(frac, shot_id="microtest", layer_role="subject")
    except ParallaxKeyGuardError as exc:
        guard = f"GUARD TRIPPED: {exc}"
    print(f"  guard: {guard}")

    print("\nCompositing with the production filter builder:")
    fc = build_two_layer_parallax_filter_complex(
        ParallaxLayerInput(role=LayerRole.BACKGROUND, index=0, key=None, drift_x=24.0, drift_y=0.0, scale=1.2),
        ParallaxLayerInput(role=LayerRole.SUBJECT, index=1, key=key, drift_x=110.0, drift_y=0.0, scale=1.2),
        canvas_w=canvas.width, canvas_h=canvas.height,
        fps=_FPS, duration_s=_DURATION_S,
    )
    clip = _OUT / "parallax.mp4"
    cmd = [settings.ffmpeg_binary, "-y"]
    for name in ("background", "subject"):
        cmd += ["-loop", "1", "-t", str(_DURATION_S), "-i", str(cropped[name])]
    cmd += ["-filter_complex", fc, "-map", "[out]", "-r", str(_FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(clip)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = proc.returncode == 0
    print(f"  {clip.name}: {'ok' if ok else 'FAILED'}")
    if not ok:
        print("\n".join(proc.stderr.strip().splitlines()[-6:]), file=sys.stderr)

    for t in (0, 2, 4):
        subprocess.run([settings.ffmpeg_binary, "-y", "-v", "error", "-ss", str(t),
                        "-i", str(clip), "-frames:v", "1", "-q:v", "3",
                        str(_OUT / f"frame_{t}s.jpg")], capture_output=True)

    summary = {
        "canvas": f"{canvas.width}x{canvas.height}",
        "requested": f"{request.width}x{request.height}",
        "sampled_key": key,
        "keyed_fraction": round(frac, 4),
        "guard": guard,
        "clip": str(clip),
        "paid_calls": sum(1 for p in raw.values() if p.exists()),
    }
    (_OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
