"""Character-consistency probe: can one hero image drive a recurring
character across contexts and ages? (ad hoc, feeds
docs/plans/animated_explainer.md A2's kill criterion)

## What this answers

`animated_explainer.md` A2 asks whether the image provider can hold a
visual LANGUAGE across a video. This probe asks the stronger question the
user actually wants: can it hold a PERSON - the same recognisable
character at school, at the gym, at his own wedding, at 14, at 30.

The production image path cannot express this at all. `FalImageProvider.
generate` (`app/providers/fal_image.py`) sends exactly `prompt`,
`image_size`, `num_images` and an optional `seed` - there is no
reference-image parameter, and `settings.fal_image_model` points at
seedream v4's TEXT-TO-IMAGE endpoint. The reference path is a different
endpoint (`/edit`, which takes `image_urls`).

**This probe needs no production change to run.** `FalQueueClient.submit`
is already generic over model id and arguments - its own docstring says
so ("fal's queue exposes the same submit/status/result shape for every
model") - so this script drives the `/edit` model directly and touches
NO production code, NO database, and NO Timeline.

## Why the fixed project seed is not the answer

`_project_seed` (`app/workflow/steps/resolve_assets.py`) pins one seed
per project, and its docstring gives the reason as "prefer stylistic
consistency over per-shot novelty". Same seed with a DIFFERENT prompt is
a different person. That is why this probe is about reference images, not
seeds - and `--arm 0` renders the seed-only baseline so the comparison is
on the sheet rather than in an argument.

## The two arms, kept separate on purpose

- **Arm 1 - context changes, age fixed.** School, gym, wedding, casino,
  desk at night. The easier ask: same face, new place and new clothes.
- **Arm 2 - age morph.** 14, 22, 30, 55. Genuinely harder and a genuinely
  different capability: ageing alters the bone structure and skin that
  identity is read FROM, so a model can preserve the mole and the scar
  and still produce a stranger.

Split so a failure is diagnosable. "Context holds, age breaks" is a
usable result (a character system with a no-age-jumps constraint);
"nothing holds" kills reference-driven characters on this provider.

## Identity lives in the face, not the outfit

`_CHARACTER` below is pasted VERBATIM into every prompt, hero and variant
alike. Every anchor in it is structural - scar through the eyebrow, mole
on the cheek, cowlick, ear set, jaw - because the variants change both
clothing AND facial age, so any anchor that depends on either is worth
nothing. A vague description produces a different person per call, and
that outcome would say nothing about the provider.

## Cost

4c per generated image (`settings.fal_image_cost_cents_estimate`) - which
is a PLANNING estimate whose own comment says "fal's actual per-model
pricing varies; refine these after real usage" and has never been
reconciled against an invoice. This script prints its exact paid call
count so that number can finally be checked against the fal dashboard.

    3 hero plates + 5 arm-1 + 4 arm-2 = 12 images ~= 48c

`--estimate` prints every prompt and the cost and spends nothing.
`--hero PATH` uploads your own photo instead of generating the plates
(3 fewer calls, and the better test - it proves the pipeline works on a
face you chose rather than one the model finds easy to redraw).

Makes NO decision and changes NO production code. Writes images, an HTML
contact sheet and a JSON summary under `tmp/character-probe/`. The
verdict is a human looking at the sheet; it cannot be made
programmatically. Never prints the API key.

    .venv/Scripts/python.exe backend/scripts/character_consistency_probe.py --estimate
    .venv/Scripts/python.exe backend/scripts/character_consistency_probe.py
    .venv/Scripts/python.exe backend/scripts/character_consistency_probe.py --hero tmp/my-face.jpg
    .venv/Scripts/python.exe backend/scripts/character_consistency_probe.py --arm 1
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

import fal_client  # noqa: E402
import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.providers.fal_queue import FalQueueClient  # noqa: E402

# seedream v4's REFERENCE-IMAGE endpoint - a different model id from
# `settings.fal_image_model` (which is `/text-to-image`). Deliberately a
# constant here rather than a new setting: nothing in production reads
# it yet, and adding a Settings field would imply it does. If this 404s
# the id has moved - check https://fal.ai/models, same convention as
# config.py's own note on `fal_image_model`.
_EDIT_MODEL = "fal-ai/bytedance/seedream/v4/edit"
_T2I_MODEL = settings.fal_image_model

_OUT = _REPO / "tmp" / "character-probe"

_POLL_INTERVAL_S = 2.0
_MAX_POLL_ATTEMPTS = 45  # ~90s; edit calls run longer than plain t2i
_CONCURRENCY = 3

# Production 9:16, so the sheet is directly comparable to what the
# pipeline would really emit (720x1280 - `retention_fast` /
# `archival_montage` in app/script/styles.py). Framing is specified per
# variant instead of enlarging the canvas, so the face stays big enough
# to judge at the real output size rather than at a flattering one.
_VAR_W, _VAR_H = 720, 1280
# Hero plates are square: this is reference material, not a shot, and
# face detail is the entire point of it.
_HERO_W, _HERO_H = 1024, 1024

# Pasted VERBATIM into every prompt below. See the module docstring:
# every anchor is structural, because the variants change both clothing
# and facial age.
_CHARACTER = (
    "A South Asian man with a narrow oval face, warm medium-brown skin, thick dark "
    "eyebrows set low and close together, a small vertical scar through the outer end "
    "of the left eyebrow, deep-set dark brown eyes, a straight nose with a slightly "
    "broad tip, a small dark mole on the right cheek two finger-widths below the eye, "
    "prominent ears that sit slightly forward, a narrow jaw, and thick black hair with "
    "a stubborn cowlick at the front right of the hairline. Lean build, slightly narrow "
    "shoulders."
)

_SAME_PERSON = (
    "This is the SAME PERSON as the reference images. Preserve his face exactly: the "
    "scar through the left eyebrow, the mole on the right cheek, the ear set, the jaw "
    "line and the hairline cowlick must all be unchanged and clearly visible."
)

_PHOTO = "Sharp photograph, natural skin texture, natural lighting, no text, no watermark."


@dataclass(frozen=True)
class Plate:
    """One generation call: a slug for the filename and a full prompt."""

    slug: str
    label: str
    prompt: str
    width: int
    height: int


_HERO_PLATES: list[Plate] = [
    Plate(
        slug="hero_1_front",
        label="hero / front headshot",
        prompt=(
            f"{_CHARACTER} Age 24. Straight-on passport-style headshot, head and "
            "shoulders, neutral relaxed expression, looking directly at camera, plain "
            "mid-grey seamless backdrop, soft even frontal light, no glasses, no hat, "
            f"plain dark crew-neck t-shirt. 85mm lens look. {_PHOTO}"
        ),
        width=_HERO_W,
        height=_HERO_H,
    ),
    Plate(
        slug="hero_2_threequarter",
        label="hero / three-quarter",
        prompt=(
            f"{_CHARACTER} Age 24. Three-quarter profile turned 45 degrees to his left, "
            "head and shoulders, neutral expression, plain mid-grey seamless backdrop, "
            "soft even frontal light, no glasses, no hat, plain dark crew-neck t-shirt. "
            f"{_PHOTO}"
        ),
        width=_HERO_W,
        height=_HERO_H,
    ),
    Plate(
        slug="hero_3_fullbody",
        label="hero / full body",
        prompt=(
            f"{_CHARACTER} Age 24. Full body standing straight, arms relaxed at sides, "
            "facing camera, plain mid-grey seamless backdrop, soft even light, plain "
            "dark crew-neck t-shirt, dark jeans, plain white sneakers. Full-length "
            f"photograph. {_PHOTO}"
        ),
        width=_HERO_W,
        height=_HERO_H,
    ),
]

# Arm 1 - age fixed at 24, context and clothing change.
_ARM1: list[Plate] = [
    Plate(
        slug="a1_1_school",
        label="arm 1 / at school",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Age 24, but dressed as a student: he stands in "
            "a school classroom in a buttoned school uniform shirt and tie, holding a "
            "notebook under one arm, blackboard and wooden desks behind him. Medium "
            f"shot, waist up, facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a1_2_gym",
        label="arm 1 / at the gym",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Age 24, mid-workout in a gym: sleeveless grey "
            "training vest, sweat on his forehead and neck, holding a dumbbell at his "
            "side, racks of weights and mirrors behind him. Medium shot, waist up, "
            f"facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a1_3_wedding",
        label="arm 1 / his own wedding",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Age 24, at his own wedding: cream embroidered "
            "sherwani, a thick flower garland around his neck, standing on a decorated "
            "wedding stage under warm string lights, guests blurred behind him. Medium "
            f"shot, chest up, facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a1_4_casino",
        label="arm 1 / blackjack table",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Age 24, seated at a blackjack table in a "
            "casino: dark open-collar shirt, stacks of chips and dealt cards on the "
            "green felt in front of him, dealer's hands out of focus across the table, "
            f"low warm casino lighting. Medium shot, chest up, facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a1_5_desk_night",
        label="arm 1 / desk at night",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Age 24, at a desk late at night: plain dark "
            "t-shirt, laptop screen glow lighting his face from below, dark room behind "
            f"him. Medium shot, chest up, facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
]

# Arm 2 - the age morph. The hard arm; see the module docstring.
_ARM2: list[Plate] = [
    Plate(
        slug="a2_1_age14",
        label="arm 2 / age 14",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Now show him as a 14-YEAR-OLD BOY: a younger, "
            "rounder, thinner-necked version of the same face, no facial hair, same "
            "eyebrow scar and same cheek mole, school uniform shirt, standing in a "
            f"school corridor. Medium shot, chest up, facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a2_2_age22",
        label="arm 2 / age 22",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Now show him at 22 YEARS OLD: light patchy "
            "stubble, same eyebrow scar and same cheek mole, casual hoodie, standing in "
            f"a college corridor. Medium shot, chest up, facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a2_3_age30",
        label="arm 2 / age 30",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Now show him at 30 YEARS OLD: a slightly "
            "fuller face and heavier build, trimmed short beard, faint lines beginning "
            "at the corners of the eyes, same eyebrow scar and same cheek mole, "
            "button-down shirt, standing in an open-plan office. Medium shot, chest up, "
            f"facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a2_4_age55",
        label="arm 2 / age 55",
        prompt=(
            f"{_CHARACTER} {_SAME_PERSON} Now show him at 55 YEARS OLD: greying temples "
            "and greying beard, deeper lines around the eyes and mouth, heavier jawline, "
            "same eyebrow scar and same cheek mole, plain dark shirt, standing indoors "
            f"against a plain wall. Medium shot, chest up, facing camera. {_PHOTO}"
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
]

# Arm 0 - the seed-only baseline the production path can already do
# TODAY: no reference image, locked character prefix, fixed seed. Two
# contexts is enough to show whether prompt-plus-seed alone reads as one
# person. This is the floor the reference arms have to beat to be worth
# any production work at all.
_ARM0_SEED = 424242
_ARM0: list[Plate] = [
    Plate(
        slug="a0_1_school_noref",
        label="arm 0 / school (no reference, fixed seed)",
        prompt=_ARM1[0].prompt.replace(_SAME_PERSON, "").replace("  ", " "),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="a0_2_gym_noref",
        label="arm 0 / gym (no reference, fixed seed)",
        prompt=_ARM1[1].prompt.replace(_SAME_PERSON, "").replace("  ", " "),
        width=_VAR_W,
        height=_VAR_H,
    ),
]


# --stylize: the photoreal hero read as obviously AI-generated (the whole
# uncanny-valley problem: a photoreal synthetic face has to clear it on
# every single shot). An ILLUSTRATED character does not have to clear it
# at all - "looks drawn" is the intended look, so the failure mode
# disappears rather than being fought. These four are ONE call each,
# using the already-paid-for photoreal hero plates as the reference, so
# the same person survives the style change and the four looks are
# directly comparable. Pick one, then run `--arm` with it as the hero.
_STYLE_PLATES: list[Plate] = [
    Plate(
        slug="st_1_flat_vector",
        label="style / flat vector",
        prompt=(
            "Redraw the person in the reference images as a FLAT VECTOR ILLUSTRATION: "
            "clean bold outlines, flat areas of colour with no gradients, simplified "
            "geometric shapes, limited palette, modern editorial/explainer illustration "
            "style. Keep him recognisably the same character - same hairstyle with the "
            "cowlick at the front right, same eyebrow shape, same ear set, same lean "
            "build. Head and shoulders, neutral expression, facing camera, plain "
            "light-grey background. No text, no watermark."
        ),
        width=_HERO_W,
        height=_HERO_H,
    ),
    Plate(
        slug="st_2_anime",
        label="style / 2D anime cel",
        prompt=(
            "Redraw the person in the reference images as a 2D ANIME CEL-SHADED "
            "CHARACTER: clean line art, cel shading with hard shadow edges, expressive "
            "stylised eyes, modern anime television style. Keep him recognisably the "
            "same character - same hairstyle with the cowlick at the front right, same "
            "eyebrow shape, same ear set, same lean build. Head and shoulders, neutral "
            "expression, facing camera, plain light-grey background. No text, no "
            "watermark."
        ),
        width=_HERO_W,
        height=_HERO_H,
    ),
    Plate(
        slug="st_3_3d_stylised",
        label="style / 3D stylised",
        prompt=(
            "Redraw the person in the reference images as a STYLISED 3D ANIMATED "
            "CHARACTER: soft rounded forms, slightly exaggerated proportions, smooth "
            "subsurface-scattered skin, soft studio lighting, modern animated-feature "
            "look. Keep him recognisably the same character - same hairstyle with the "
            "cowlick at the front right, same eyebrow shape, same ear set, same lean "
            "build. Head and shoulders, neutral expression, facing camera, plain "
            "light-grey background. No text, no watermark."
        ),
        width=_HERO_W,
        height=_HERO_H,
    ),
    Plate(
        slug="st_4_storybook",
        label="style / storybook gouache",
        prompt=(
            "Redraw the person in the reference images as a STORYBOOK ILLUSTRATION: "
            "textured gouache and coloured-pencil rendering, visible brush and paper "
            "texture, warm muted palette, soft hand-drawn outlines. Keep him "
            "recognisably the same character - same hairstyle with the cowlick at the "
            "front right, same eyebrow shape, same ear set, same lean build. Head and "
            "shoulders, neutral expression, facing camera, plain light-grey background. "
            "No text, no watermark."
        ),
        width=_HERO_W,
        height=_HERO_H,
    ),
]


# --illustrated: the real ask. An OPT-IN illustrated format - generated
# environments with FACELESS characters in them - not a search discipline
# over photographs. Three questions, each with a kill criterion fixed
# before spending:
#
#   Q1 will the model render a faceless character AT ALL? Image models
#      are heavily face-biased and "no face" is a NEGATIVE instruction,
#      which they honour unreliably. Four positive framings are tried
#      instead of one negative one. If all four fail, faceless characters
#      are not reachable by prompt and the answer is a drawn/rigged asset.
#   Q2 does ONE illustrated world hold across different environments?
#      This is animated_explainer.md A2's own kill criterion, minus the
#      face - holding a palette and a line weight is a far weaker demand
#      than holding a person.
#   Q3 can that same world render a DATA shot? Failing this kills
#      nothing; it just means the statistics stay as text cards.
#
# NOTE: text-to-image, NO reference images. That is the whole point of
# faceless - identity is silhouette and palette, expressible in text, so
# none of the reference plumbing (persisted character, hosted URLs,
# re-upload per run) is needed at all.
_WORLD = (
    "Flat editorial illustration in a strictly limited palette: muted slate blue, "
    "warm amber, off-white and charcoal. Soft paper-grain texture, simple geometric "
    "shapes, no outlines, flat shading with a single soft light direction, generous "
    "negative space. Restrained and serious in tone - documentary, not cute, not "
    "corporate. Modern print-magazine illustration. No text, no watermark."
)

# Q1 - four POSITIVE framings for facelessness, same scene each time.
_FACELESS_TREATMENTS: list[Plate] = [
    Plate(
        slug="il_q1a_back_of_head",
        label="Q1a / seen from behind",
        prompt=(
            f"{_WORLD} A teenage student sitting at a small desk in a cramped bedroom "
            "at 6am, seen entirely FROM BEHIND - the back of his head and shoulders "
            "fill the foreground, his face is turned away from the viewer and cannot "
            "be seen."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="il_q1b_silhouette",
        label="Q1b / silhouette",
        prompt=(
            f"{_WORLD} A teenage student standing at a window in a cramped bedroom at "
            "6am, rendered as a SOLID DARK SILHOUETTE against the bright window - a "
            "flat featureless shape, no facial detail whatsoever."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="il_q1c_blank_face",
        label="Q1c / blank featureless face",
        prompt=(
            f"{_WORLD} A teenage student sitting at a small desk in a cramped bedroom "
            "at 6am, facing the viewer. His head is a smooth BLANK OVAL of flat skin "
            "tone with NO eyes, NO nose and NO mouth - a deliberately featureless "
            "face, in the style of faceless editorial illustration. Hair and body are "
            "fully drawn as normal."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="il_q1d_cropped",
        label="Q1d / cropped above the chin",
        prompt=(
            f"{_WORLD} A teenage student sitting at a small desk in a cramped bedroom "
            "at 6am, framed from the chest down to the desk - the composition is "
            "CROPPED so his head is entirely above the top edge of the frame and out "
            "of view. Hands resting on an open notebook."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
]

# Q2 - one world, four environments from the real script.
_ENVIRONMENTS: list[Plate] = [
    Plate(
        slug="il_q2a_bedroom",
        label="Q2a / bedroom, 6am",
        prompt=(
            f"{_WORLD} A cramped teenage bedroom at 6am. An alarm clock on a bedside "
            "table reading early morning, an unmade bed, a school bag on the floor, "
            "pale first light through a thin curtain. No people."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="il_q2b_hagwon",
        label="Q2b / hagwon, 2am",
        prompt=(
            f"{_WORLD} A private cram-school classroom at 2am: rows of narrow desks "
            "under hard fluorescent ceiling light, stacks of workbooks, a dark window "
            "showing city lights outside. No people."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="il_q2c_factory",
        label="Q2c / factory floor",
        prompt=(
            f"{_WORLD} The floor of a large electronics factory: long assembly lines, "
            "industrial machinery, a very high ceiling with rows of overhead lights, "
            "cool even illumination. No people."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="il_q2d_apartments",
        label="Q2d / Seoul apartments at dusk",
        prompt=(
            f"{_WORLD} A dense cluster of tall residential apartment towers at dusk, "
            "hundreds of small lit windows in repeating grids, a hazy city skyline "
            "behind them. No people."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
]

# Q3 - a data shot in the same world. Q4 - character INSIDE an
# environment, which is the combination the real film actually needs.
_COMBINED: list[Plate] = [
    Plate(
        slug="il_q3_chart",
        label="Q3 / data shot (0.72 vs 2.1)",
        prompt=(
            f"{_WORLD} A simple, clean comparison of two vertical bars of very "
            "different heights - one short bar and one bar roughly three times "
            "taller - on an open background with generous negative space. An "
            "infographic in this illustration style, purely graphic shapes, no "
            "labels and no numbers."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
    Plate(
        slug="il_q4_character_in_world",
        label="Q4 / faceless character in an environment",
        prompt=(
            f"{_WORLD} A private cram-school classroom at 2am under hard fluorescent "
            "light, rows of narrow desks. A single teenage student sits alone at one "
            "desk, seen FROM BEHIND - the back of his head and shoulders only, his "
            "face turned away and not visible. He wears a dark green hooded jacket "
            "with a grey backpack on the chair beside him."
        ),
        width=_VAR_W,
        height=_VAR_H,
    ),
]


@dataclass
class Outcome:
    plate: Plate
    ok: bool
    path: Path | None = None
    hosted_url: str | None = None
    error: str | None = None
    paid_calls: int = 0


@dataclass
class Tally:
    paid_calls: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def cents(self) -> int:
        return self.paid_calls * settings.fal_image_cost_cents_estimate


async def _run_one(
    queue: FalQueueClient,
    plate: Plate,
    *,
    model: str,
    image_urls: list[str] | None,
    seed: int | None,
) -> Outcome:
    arguments: dict = {
        "prompt": plate.prompt,
        "image_size": {"width": plate.width, "height": plate.height},
        "num_images": 1,
    }
    if image_urls:
        arguments["image_urls"] = image_urls
    if seed is not None:
        arguments["seed"] = seed

    try:
        job_id = await queue.submit(model, arguments)
    except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
        return Outcome(plate=plate, ok=False, error=f"submit failed: {exc}")

    for _ in range(_MAX_POLL_ATTEMPTS):
        try:
            state, result, error = await queue.poll_once(model, job_id)
        except Exception as exc:  # noqa: BLE001
            return Outcome(plate=plate, ok=False, error=f"poll failed: {exc}", paid_calls=1)
        if state == "failed":
            return Outcome(plate=plate, ok=False, error=f"generation failed: {error}", paid_calls=1)
        if state == "completed":
            images = (result or {}).get("images") or []
            if not images:
                return Outcome(
                    plate=plate, ok=False, error="completed with no images", paid_calls=1
                )
            url = images[0]["url"]
            path = _OUT / f"{plate.slug}.png"
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(url, follow_redirects=True)
                    response.raise_for_status()
                path.write_bytes(response.content)
            except Exception as exc:  # noqa: BLE001
                return Outcome(
                    plate=plate, ok=False, error=f"download failed: {exc}", paid_calls=1
                )
            return Outcome(plate=plate, ok=True, path=path, hosted_url=url, paid_calls=1)
        await asyncio.sleep(_POLL_INTERVAL_S)

    return Outcome(
        plate=plate,
        ok=False,
        error=f"did not complete within {_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_S:.0f}s",
        paid_calls=1,
    )


async def _run_many(
    queue: FalQueueClient,
    plates: list[Plate],
    *,
    model: str,
    image_urls: list[str] | None = None,
    seed: int | None = None,
) -> list[Outcome]:
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def _guarded(plate: Plate) -> Outcome:
        async with semaphore:
            print(f"  -> {plate.label} ...", flush=True)
            outcome = await _run_one(
                queue, plate, model=model, image_urls=image_urls, seed=seed
            )
            mark = "ok" if outcome.ok else f"FAILED ({outcome.error})"
            print(f"  <- {plate.label}: {mark}", flush=True)
            return outcome

    return list(await asyncio.gather(*(_guarded(p) for p in plates)))


def _write_sheet(groups: list[tuple[str, list[Outcome]]], hero_note: str) -> Path:
    """One self-contained HTML page. Deliberately not
    `app/renderer/contact_sheet.py` - that builds a sheet from a
    Timeline's shots and midpoint frames, and this has neither."""
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        "<title>Character consistency probe</title>",
        "<style>",
        "body{background:#141414;color:#e8e8e8;font:14px system-ui;margin:0;padding:24px}",
        "h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 10px;",
        "border-bottom:1px solid #333;padding-bottom:6px}",
        ".note{color:#9a9a9a;max-width:70ch;line-height:1.5}",
        ".row{display:flex;flex-wrap:wrap;gap:14px}",
        ".cell{width:220px}.cell img{width:220px;border-radius:6px;display:block;",
        "background:#000}.cap{color:#bdbdbd;font-size:12px;margin-top:6px}",
        ".bad{color:#ff8080;font-size:12px}",
        "</style>",
        "<h1>Character consistency probe</h1>",
        f"<p class='note'>{html.escape(hero_note)}</p>",
        "<p class='note'>The question for each image: <b>would a viewer say this is "
        "the same person?</b> Arm 0 is the floor the production path can already reach "
        "today (no reference image, fixed seed). Arm 1 must hold across all five for "
        "reference-driven characters to be worth productionising. Arm 2 breaking while "
        "arm 1 holds is still a usable result - a character system with a no-age-jumps "
        "constraint.</p>",
    ]
    for title, outcomes in groups:
        if not outcomes:
            continue
        parts.append(f"<h2>{html.escape(title)}</h2><div class='row'>")
        for outcome in outcomes:
            parts.append("<div class='cell'>")
            if outcome.ok and outcome.path is not None:
                parts.append(f"<img src='{html.escape(outcome.path.name)}'>")
                parts.append(f"<div class='cap'>{html.escape(outcome.plate.label)}</div>")
            else:
                parts.append(f"<div class='cap'>{html.escape(outcome.plate.label)}</div>")
                parts.append(f"<div class='bad'>{html.escape(outcome.error or 'failed')}</div>")
            parts.append("</div>")
        parts.append("</div>")
    path = _OUT / "sheet.html"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _print_estimate(plates: list[tuple[str, list[Plate]]], hero_calls: int) -> None:
    total = hero_calls
    for title, group in plates:
        print(f"\n=== {title} ({len(group)} calls) ===")
        for plate in group:
            print(f"\n-- {plate.label}  [{plate.width}x{plate.height}]")
            print(plate.prompt)
        total += len(group)
    rate = settings.fal_image_cost_cents_estimate
    print(f"\n=== TOTAL: {total} generation calls x {rate}c = {total * rate}c ===")
    print("(rate is settings.fal_image_cost_cents_estimate - a planning estimate,")
    print(" never reconciled against a real fal invoice. Check the dashboard after.)")


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hero",
        type=Path,
        default=None,
        help="use this local image as the character reference instead of generating "
        "the three hero plates (3 fewer paid calls)",
    )
    parser.add_argument(
        "--arm",
        choices=["0", "1", "2", "both", "all"],
        default="all",
        help="'both' = arms 1+2 (reference arms). 'all' = arm 0 baseline too (default).",
    )
    parser.add_argument(
        "--illustrated",
        action="store_true",
        help="skip everything else: the OPT-IN illustrated format probe - faceless "
        "character treatments (Q1), one world across four environments (Q2), a data "
        "shot (Q3) and a character inside an environment (Q4). Text-to-image, no "
        "reference images. 10 calls.",
    )
    parser.add_argument(
        "--stylize",
        action="store_true",
        help="skip the arms entirely: take the existing hero plates in tmp/"
        "character-probe/ as the reference and render the same character in four "
        "illustrated art styles (4 calls). Pick a look, then re-run with --hero.",
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="print every prompt and the cost, spend nothing",
    )
    args = parser.parse_args()

    _other = args.stylize or args.illustrated
    run_arm0 = args.arm in ("0", "all") and not _other
    run_arm1 = args.arm in ("1", "both", "all") and not _other
    run_arm2 = args.arm in ("2", "both", "all") and not _other
    needs_reference = run_arm1 or run_arm2 or args.stylize

    selected: list[tuple[str, list[Plate]]] = []
    if args.illustrated:
        selected.append(("Q1 - faceless character treatments", _FACELESS_TREATMENTS))
        selected.append(("Q2 - one world, four environments", _ENVIRONMENTS))
        selected.append(("Q3/Q4 - data shot, and character in world", _COMBINED))
    if args.stylize:
        selected.append(("Illustrated looks - same character, four art styles", _STYLE_PLATES))
    if run_arm0:
        selected.append(("Arm 0 - no reference, fixed seed (today's ceiling)", _ARM0))
    if run_arm1:
        selected.append(("Arm 1 - context changes, age fixed", _ARM1))
    if run_arm2:
        selected.append(("Arm 2 - age morph", _ARM2))

    # --stylize reuses the hero plates already on disk from a previous
    # run - it never re-pays for them.
    existing_hero = sorted(_OUT.glob("hero_*.png")) if args.stylize else []
    hero_calls = (
        0
        if (args.hero is not None or existing_hero or not needs_reference)
        else len(_HERO_PLATES)
    )

    if args.estimate:
        if hero_calls:
            print(f"=== Hero reference plates ({hero_calls} calls) ===")
            for plate in _HERO_PLATES:
                print(f"\n-- {plate.label}  [{plate.width}x{plate.height}]")
                print(plate.prompt)
        elif needs_reference:
            print(f"=== Hero reference: local file {args.hero} (0 calls) ===")
        _print_estimate(selected, hero_calls)
        return 0

    if not settings.fal_key:
        print("FAL_KEY is not set - nothing to probe.", file=sys.stderr)
        return 2
    if args.hero is not None and not args.hero.is_file():
        print(f"--hero {args.hero} is not a file", file=sys.stderr)
        return 2

    _OUT.mkdir(parents=True, exist_ok=True)
    queue = FalQueueClient()
    tally = Tally()
    groups: list[tuple[str, list[Outcome]]] = []

    reference_urls: list[str] = []
    hero_note = ""
    hero_outcomes: list[Outcome] = []

    if needs_reference:
        local_refs = [args.hero] if args.hero is not None else existing_hero
        if local_refs:
            print(f"Uploading {len(local_refs)} local reference image(s) ...", flush=True)
            client = fal_client.AsyncClient(key=settings.fal_key)
            for ref in local_refs:
                try:
                    reference_urls.append(await client.upload_file(ref))
                except Exception as exc:  # noqa: BLE001
                    print(f"reference upload failed for {ref}: {exc}", file=sys.stderr)
                    return 1
                print(f"  <- uploaded {ref.name}", flush=True)
            origin = "your own image" if args.hero is not None else "the existing hero plates"
            hero_note = (
                f"Reference: {origin} - {', '.join(r.name for r in local_refs)} "
                "(uploaded, 0 paid calls)."
            )
        else:
            print(f"Generating {len(_HERO_PLATES)} hero reference plates ...", flush=True)
            hero_outcomes = await _run_many(queue, _HERO_PLATES, model=_T2I_MODEL)
            for outcome in hero_outcomes:
                tally.paid_calls += outcome.paid_calls
                if outcome.ok and outcome.hosted_url:
                    # Reusing the provider-hosted URL rather than
                    # re-uploading the bytes - exactly what
                    # `ImageResult.hosted_url` is documented to be for
                    # (`app/providers/base.py`), which already does this
                    # for image-to-video keyframes.
                    reference_urls.append(outcome.hosted_url)
                else:
                    tally.failures.append(f"{outcome.plate.slug}: {outcome.error}")
            hero_note = (
                f"Reference: {len(reference_urls)} generated hero plates "
                f"({len(_HERO_PLATES)} paid calls)."
            )
            groups.append(("Hero reference plates", hero_outcomes))

        if not reference_urls:
            print("no usable hero reference - stopping before spending on variants", file=sys.stderr)
            _write_sheet(groups, hero_note or "hero generation failed")
            print(json.dumps({"paid_calls": tally.paid_calls, "cents": tally.cents}, indent=2))
            return 1

    if args.illustrated:
        for title, plates in (
            ("Q1 - faceless character treatments", _FACELESS_TREATMENTS),
            ("Q2 - one world, four environments", _ENVIRONMENTS),
            ("Q3/Q4 - data shot, and character in world", _COMBINED),
        ):
            print(f"{title} - {len(plates)} images ...", flush=True)
            outcomes = await _run_many(queue, plates, model=_T2I_MODEL)
            groups.append((title, outcomes))
            for outcome in outcomes:
                tally.paid_calls += outcome.paid_calls
                if not outcome.ok:
                    tally.failures.append(f"{outcome.plate.slug}: {outcome.error}")

    if args.stylize:
        print(f"Illustrated looks - {len(_STYLE_PLATES)} images ...", flush=True)
        outcomes = await _run_many(
            queue, _STYLE_PLATES, model=_EDIT_MODEL, image_urls=reference_urls
        )
        groups.append(("Illustrated looks - same character, four art styles", outcomes))
        for outcome in outcomes:
            tally.paid_calls += outcome.paid_calls
            if not outcome.ok:
                tally.failures.append(f"{outcome.plate.slug}: {outcome.error}")

    if run_arm0:
        print(f"Arm 0 - {len(_ARM0)} images, no reference, seed {_ARM0_SEED} ...", flush=True)
        outcomes = await _run_many(queue, _ARM0, model=_T2I_MODEL, seed=_ARM0_SEED)
        groups.append(("Arm 0 - no reference, fixed seed (today's ceiling)", outcomes))
        for outcome in outcomes:
            tally.paid_calls += outcome.paid_calls
            if not outcome.ok:
                tally.failures.append(f"{outcome.plate.slug}: {outcome.error}")

    for run, title, plates in (
        (run_arm1, "Arm 1 - context changes, age fixed", _ARM1),
        (run_arm2, "Arm 2 - age morph", _ARM2),
    ):
        if not run:
            continue
        print(f"{title} - {len(plates)} images ...", flush=True)
        outcomes = await _run_many(queue, plates, model=_EDIT_MODEL, image_urls=reference_urls)
        groups.append((title, outcomes))
        for outcome in outcomes:
            tally.paid_calls += outcome.paid_calls
            if not outcome.ok:
                tally.failures.append(f"{outcome.plate.slug}: {outcome.error}")

    sheet = _write_sheet(groups, hero_note)
    summary = {
        "out_dir": str(_OUT),
        "sheet": str(sheet),
        "t2i_model": _T2I_MODEL,
        "edit_model": _EDIT_MODEL,
        "reference_images": len(reference_urls),
        "paid_generation_calls": tally.paid_calls,
        "estimated_cents": tally.cents,
        "cost_rate_cents_per_image": settings.fal_image_cost_cents_estimate,
        "cost_rate_caveat": "planning estimate, never reconciled against a fal invoice",
        "images": {
            outcome.plate.slug: ("ok" if outcome.ok else outcome.error)
            for _title, outcomes in groups
            for outcome in outcomes
        },
        "failures": tally.failures,
    }
    (_OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nOpen the sheet: {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
