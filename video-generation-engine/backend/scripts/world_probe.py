"""House-world bake-off for the illustrated format (docs/plans/
illustrated_faceless.md §6 Q2).

Q2 is a TASTE question, and the plan says to settle it the way the
storybook/anime/3D comparison was settled - by eye, on real renders, not
by discussion. This is that comparison.

## The matrix, and why it is these three subjects

Four candidate worlds x three subjects, same subject wording in every
world so the ONLY variable is the world token:

- **environment** (cram-school classroom at 2am, no people) - can the
  world carry atmosphere and place?
- **figure** (faceless student from behind) - can it carry a person?
  Uses the back-of-head treatment, which §1.3 measured as the strongest
  of the four faceless framings.
- **data** (two bars, one ~3x the other) - can it carry an infographic?
  This is the one that decides whether the statistics live in the same
  medium as the film or need a separate register (§6 Q4 of the parent
  plan's own concern about two visual classes).

A world that only does two of the three is not a house style; it is a
look for one kind of shot.

## Prompt lessons already paid for, applied here

From `illustrated_faceless.md` §1.2 / §1.3, both measured:

- **Ethnicity and hair colour are stated explicitly in every prompt.**
  Skin tone drifted lighter monotonically with abstraction level, and an
  unstated hair colour came back ginger because the palette's amber bled
  into it.
- **"Plain flat background", never "open background".** The latter was
  read as "open BOOK" and the chart was drawn on a book's pages.
- **Facelessness is a POSITIVE instruction** ("seen from behind, face
  turned away"), never the negative "no face" - negatives are honoured
  unreliably by face-biased models.

Makes NO decision and changes NO production code. 12 images at 4c = 48c.
`--estimate` prints every prompt and spends nothing. Never prints the
API key.

    .venv/Scripts/python.exe backend/scripts/world_probe.py --estimate
    .venv/Scripts/python.exe backend/scripts/world_probe.py
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.providers.fal_queue import FalQueueClient  # noqa: E402

_OUT = _REPO / "tmp" / "world-probe"
_W, _H = 720, 1280  # the real 9:16 canvas
_CONCURRENCY = 3
_NO_TEXT = "No text, no lettering, no numbers, no watermark."


@dataclass(frozen=True)
class World:
    slug: str
    label: str
    token: str
    note: str


_WORLDS: list[World] = [
    World(
        slug="w1_flat_editorial",
        label="W1 · flat editorial",
        note="The already-proven token from §1.3. Muted, restrained, magazine-like.",
        token=(
            "Flat editorial illustration in a strictly limited palette: muted slate blue, "
            "warm amber, off-white and charcoal. Soft paper-grain texture, simple geometric "
            "shapes, no outlines, flat shading with a single soft light direction, generous "
            "negative space. Restrained and serious in tone - documentary, not cute, not "
            "corporate. Modern print-magazine illustration."
        ),
    ),
    World(
        slug="w2_risograph",
        label="W2 · risograph / bold graphic",
        note="Punchier. Few spot colours, heavy grain, deliberate misregistration.",
        token=(
            "Bold risograph print illustration: only three spot colours - deep teal, "
            "fluorescent orange and black - printed on off-white uncoated paper. Heavy visible "
            "ink grain, coarse halftone dot texture, deliberate slight misregistration where "
            "colours overlap, high contrast, simplified poster-like shapes. Graphic and urgent, "
            "like a printed protest poster."
        ),
    ),
    World(
        slug="w3_gouache",
        label="W3 · soft gouache",
        note="Warmer and more emotional. Visible brushwork, hand-painted.",
        token=(
            "Soft gouache painting on textured paper: visible brush strokes and dry-brush edges, "
            "warm muted palette of dusty blue, ochre, terracotta and cream, gentle tonal "
            "gradients, soft irregular hand-painted outlines, slightly uneven washes. Quiet, "
            "intimate, hand-made feeling - a painted children's-book plate for adults."
        ),
    ),
    World(
        slug="w4_line_wash",
        label="W4 · line and wash",
        note="Diagrammatic. Ink linework over flat washes - closest to an explainer.",
        token=(
            "Ink line-and-wash illustration: precise thin dark ink linework describing every "
            "form, filled with flat translucent watercolour washes in a narrow palette of "
            "indigo, ochre and warm grey, left slightly loose so washes sit just off their "
            "lines, plenty of untouched paper. Clear, analytical and diagrammatic - a technical "
            "notebook drawing."
        ),
    ),
]


@dataclass(frozen=True)
class Subject:
    slug: str
    label: str
    body: str


_SUBJECTS: list[Subject] = [
    Subject(
        slug="s1_environment",
        label="environment · classroom, 2am",
        body=(
            "A private cram-school classroom at 2am: rows of narrow desks under hard "
            "fluorescent ceiling light, stacks of workbooks, a dark window showing distant "
            "city lights. No people."
        ),
    ),
    Subject(
        slug="s2_figure",
        label="figure · faceless student",
        body=(
            "A single teenage East Asian student with straight black hair, seated alone at a "
            "narrow desk in a dim classroom, seen entirely FROM BEHIND - the back of his head "
            "and shoulders fill the frame, his face is turned away and cannot be seen. He wears "
            "a dark green hooded jacket, with a grey backpack on the chair beside him."
        ),
    ),
    Subject(
        slug="s3_data",
        label="data · two bars",
        body=(
            "An infographic of exactly two vertical bars side by side on a plain flat empty "
            "background with generous margins: the left bar is short, the right bar is roughly "
            "three times taller. Purely graphic rectangles, nothing else in the frame."
        ),
    ),
]


@dataclass
class Cell:
    world: World
    subject: Subject
    ok: bool = False
    error: str | None = None
    paid: int = 0

    @property
    def slug(self) -> str:
        return f"{self.world.slug}__{self.subject.slug}"

    @property
    def prompt(self) -> str:
        return f"{self.world.token} {self.subject.body} {_NO_TEXT}"


async def _one(queue: FalQueueClient, cell: Cell) -> Cell:
    path = _OUT / f"{cell.slug}.png"
    if path.exists():
        cell.ok = True
        return cell
    arguments = {
        "prompt": cell.prompt,
        "image_size": {"width": _W, "height": _H},
        "num_images": 1,
    }
    try:
        job_id = await queue.submit(settings.fal_image_model, arguments)
    except Exception as exc:  # noqa: BLE001
        cell.error = f"submit failed: {exc}"
        return cell
    for _ in range(45):
        try:
            state, result, error = await queue.poll_once(settings.fal_image_model, job_id)
        except Exception as exc:  # noqa: BLE001
            cell.error, cell.paid = f"poll failed: {exc}", 1
            return cell
        if state == "failed":
            cell.error, cell.paid = f"generation failed: {error}", 1
            return cell
        if state == "completed":
            cell.paid = 1
            images = (result or {}).get("images") or []
            if not images:
                cell.error = "no images returned"
                return cell
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(images[0]["url"], follow_redirects=True)
                    response.raise_for_status()
                path.write_bytes(response.content)
            except Exception as exc:  # noqa: BLE001
                cell.error = f"download failed: {exc}"
                return cell
            cell.ok = True
            return cell
        await asyncio.sleep(2.0)
    cell.error, cell.paid = "timed out", 1
    return cell


def _write_sheet(cells: list[Cell]) -> Path:
    by_world: dict[str, list[Cell]] = {}
    for cell in cells:
        by_world.setdefault(cell.world.slug, []).append(cell)

    rows = []
    for world in _WORLDS:
        cs = by_world.get(world.slug, [])
        imgs = "".join(
            (
                f"<div class=c><img src='{html.escape(c.slug)}.png'>"
                f"<div class=cap>{html.escape(c.subject.label)}</div></div>"
                if c.ok
                else f"<div class=c><div class=bad>{html.escape(c.error or 'failed')}</div>"
                f"<div class=cap>{html.escape(c.subject.label)}</div></div>"
            )
            for c in cs
        )
        rows.append(
            f"<h2>{html.escape(world.label)}</h2>"
            f"<p class=note>{html.escape(world.note)}</p>"
            f"<div class=row>{imgs}</div>"
        )

    page = f"""<!doctype html><meta charset=utf-8><title>House world bake-off</title>
<style>
body{{background:#141414;color:#e8e8e8;font:14px system-ui;margin:0;padding:24px}}
h1{{font-size:20px;margin:0 0 6px}} h2{{font-size:15px;margin:30px 0 2px}}
p.note{{color:#9a9a9a;margin:2px 0 10px}} p.lead{{color:#9a9a9a;max-width:74ch;line-height:1.55}}
.row{{display:flex;gap:14px;flex-wrap:wrap}} .c{{width:210px}}
.c img{{width:210px;border-radius:6px;display:block;background:#000}}
.cap{{color:#bdbdbd;font-size:12px;margin-top:5px}} .bad{{color:#ff8080;font-size:12px}}
</style>
<h1>House world bake-off &mdash; four candidates, three subjects each</h1>
<p class=lead>Same subject wording in every row; the only variable is the world token.
Judge each world on <b>all three</b>: does it carry atmosphere (environment), a person
(figure), <i>and</i> an infographic (data)? A world that only does two of the three is a
look for one kind of shot, not a house style. Also watch for the two known drifts &mdash;
skin tone lightening, and the data shot picking up scenery it was not asked for.</p>
{''.join(rows)}"""
    path = _OUT / "sheet.html"
    path.write_text(page, encoding="utf-8")
    return path


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimate", action="store_true", help="print prompts, spend nothing")
    args = parser.parse_args()

    cells = [Cell(world=w, subject=s) for w in _WORLDS for s in _SUBJECTS]

    if args.estimate:
        for cell in cells:
            print(f"\n-- {cell.world.label} / {cell.subject.label}\n{cell.prompt}")
        todo = [c for c in cells if not (_OUT / f"{c.slug}.png").exists()]
        rate = settings.fal_image_cost_cents_estimate
        print(f"\n=== {len(todo)} images x {rate}c = {len(todo) * rate}c ===")
        return 0

    if not settings.fal_key:
        print("FAL_KEY is not set", file=sys.stderr)
        return 2
    _OUT.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    queue = FalQueueClient()

    async def _guarded(cell: Cell) -> Cell:
        async with semaphore:
            print(f"  -> {cell.world.label} / {cell.subject.label}", flush=True)
            done = await _one(queue, cell)
            print(
                f"  <- {done.world.label} / {done.subject.label}: "
                f"{'ok' if done.ok else 'FAILED ' + (done.error or '')}",
                flush=True,
            )
            return done

    done = list(await asyncio.gather(*(_guarded(c) for c in cells)))
    sheet = _write_sheet(done)
    paid = sum(c.paid for c in done)
    summary = {
        "out_dir": str(_OUT),
        "sheet": str(sheet),
        "model": settings.fal_image_model,
        "paid_generation_calls": paid,
        "estimated_cents": paid * settings.fal_image_cost_cents_estimate,
        "cells": {c.slug: ("ok" if c.ok else c.error) for c in done},
        "failures": [f"{c.slug}: {c.error}" for c in done if not c.ok],
    }
    (_OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nOpen: {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
