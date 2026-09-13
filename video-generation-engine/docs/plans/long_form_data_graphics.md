# Long-Form Data Graphics — evidence on screen, not a slideshow with the occasional chart

**Status:** DESIGN ONLY. Nothing built. Decisions in §3 are binding for this
plan; G-D2 was **revised 2026-09-11** (see §7) and the original "opaque chart
IS the picture" default is no longer the product.
**Written 2026-09-11** at the user's request: *"what would it take to extend this
style to long form videos where charts or explainer diagrams are given priority,
using Remotion's help."*
**Revised 2026-09-11** at the user's request, after watching what this plan
would actually ship ("that is no fun") and checking what 2024–2026 long-form
explainers do on screen. The missing product is not "more charts." It is
**annotation on the photo, every few seconds, with full-screen graphics only
when the picture *is* the data.**
**Letter:** this plan owns the **`G`** prefix. `A C D I K N Q R RV W` are taken by
existing plans; do not reuse them here, and do not use `G` elsewhere.

---

## Verdict up front

**The engine can make the long-form people actually watch. Remotion is the
right tool. The original shape of this plan would not have felt like those
videos, even if every chart rendered perfectly.**

Winning 8–20 minute explainers in 2024–2026 (Think School, Dhruv Rathee / Mohak
Mangal overlay kit, PolyMatter, Economics Explained, Wendover, Johnny Harris
*as overlay craft not as a host*) share one grammar:

**two layers.** A picture of the world, plus an annotation that answers the
sentence as it is said. Document highlight, pointer, big number, stamp, small
chart, split. The picture changes or a new overlay lands every **4–8 seconds**.
A host is optional. Naked Ken Burns is the "no fun" baseline. A full-screen
bar chart on a void is one instrument, not the band.

This pipeline is faceless and already has the two seams that grammar needs:

- **A photo (or motion clip) as the shot's picture** — Ken Burns, `punch_in`,
  `split_frame`, the motion-clip path.
- **Remotion as a layer producer** — `compositor.py` already draws stamp /
  counter / pivot as alpha and ffmpeg already does `overlay=0:0`.

What is wrong today, measured:

1. **That overlay never runs on 16:9.** `EmphasisPassStep` is hard-gated to
   `retention_fast`. Long-form is a photo and a voice.
2. **The overlay is one full-length alpha movie**, so cost scales with runtime.
   Measured 2026-09-11 on `833dfd54` (9 sparse cues, 1958 frames, 720×1280,
   ProRes 4444): **91s wall, 1.40× realtime, 53 MB, byte-identical cache**.
   Ten minutes of that is **~14 min of Remotion before a single chart is
   drawn**. Do not extend this shape.
3. **The first draft of this plan made the graphic the picture** (G-D2 opaque,
   no compositing over a photo). Correct for unreadability of type on a busy
   infographic (K8). Wrong as the *default* for long-form: it throws away the
   world the annotation is pointing at. That is PowerPoint, not Dhruv/Harris.

**The fix is still per-shot Remotion clips — two kinds, not one.**

| Kind | What it is | When | Cost scales with |
|---|---|---|---|
| **`Annotate`** (alpha, short) | pointer, highlight, number, stamp, callout, mini-chart **over the photo** | default evidence beat | annotation seconds |
| **`Graphic`** (opaque) | column / line / stacked bar / dumbbell, or a process diagram, on a designed ground | the picture IS the data, or K8 escalation | graphic seconds |

| 10-min video | Remotion cost (same 1.40× rate) |
|---|---|
| full-length alpha layer (today's shape) | 18,000 frames → **~14 min** |
| per-shot clips, 20% opaque graphic | 3,600 frames → **~2.8 min** |
| per-shot clips, 40% of shots annotated ~2s each | ~1,440 frames → **~1.1 min**, cached per shot |

16:9 is 1280×720 — **same pixel count** as 720×1280. Cost numbers transfer.

**Demand, still real, and broader than charts.** Census 2026-09-11, 45
timelines, 1615 shots: **124 (7.7%) data-shaped picture prompts**, clustered on
*The GDP Dilemma* 21/62, *the gdp game* 16/57, *The home loan scam* 11/51.
Those shots today get a stock photo or an image-model infographic. G0 must
also count **annotation-shaped** shots (document, single number, quote, name,
comparison) — that is the larger "fun" surface, and a low chart % must not
close this plan.

**Not in scope, recorded so it is not "forgotten":** this is **not**
`retention_fast` kinetic identity on a 10-minute film (no `pivot`, no 12
cues/min, do not lift the `_is_retention_fast` gate). It is not maps
(GeoLayers), not Johnny Harris collage, not Kurzgesagt, not a host, not
`animated_explainer.md`'s persistent diagram.

| # | Task | Effort | Depends on |
|---|---|---|---|
| **G0** | ⛔ GATE — chart-shaped AND annotation-shaped census | 0.5 d | — |
| **G1** | `GraphicSpec` + `AnnotationSpec` on the timeline | 1.5–2 d | G0 |
| **G2** | Evidence planner (device picker) + K8 guardrails in code | 2.5–3.5 d | G1 |
| **G3** | Third `PicturePath` for **opaque** graphics only; annotation shots still buy a photo | 1 d | G1 |
| **G10** | Remotion `Annotate` composition — the fun kit | 3–4 d | G1 |
| **G5** | Per-shot clip producer, alpha **and** opaque, content-hash cache, fingerprint | 2.5–3 d | G10 |
| **G11** | Shot-build overlay: composite the alpha clip onto the plate **inside the shot fragment** | 1.5–2 d | G5 |
| **G6** | `explainer_evidence` band + **all** lockstep registries + prompt files in §5.1 | 2–2.5 d | G2, G11 |
| **G4** | Remotion `Graphic` composition — four chart forms, opaque escalation | 3–4 d | G5 |
| **G7** | Explainer diagrams — separate grammar, opaque | 3–4 d | G4, G5 |
| **G8** | Chapter/act awareness so evidence lands at structural beats | 1 d | G6 |
| **G9** | Review surface for inferred values (K8 guardrail 4) | 1.5–2 d | G2 |

**~22–32 days all-in. A watchable v1 is G0 → G1 → G10 → G5 → G11 → G6
(~11–15 days): annotation on photos, no charts yet.** G4/G7 are the original
chart/diagram work and they plug into the same producer. G0 can still close
the whole plan, but only if **both** surfaces are empty — see §4.

Everything from G10 / G4 / G6 / G7 on ends in a human watching output.

---

## 0. Navigation — read before writing any code

### 0.1 Pickup protocol

Same rules as `output_quality_pass.md` §0.1, `animated_explainer.md` §0.1 and
`long_form_direction.md` §0.1, restated because this plan will be picked up cold:

1. **G0 is the gate for everything else.** It is a measurement. If it comes back
   below **both** of its own thresholds (charts **and** annotations), **close
   this plan** in §7 and stop. That is a success. A low chart % with a live
   annotation % is **not** a close — build G10 first.
2. **Do exactly one lettered task.** Do not bundle. Do not "while I was in
   there."
3. **Write a §7 log entry before finishing:** dated heading, *Scope executed*,
   *Changes* with `file:line`, *Measured* (real numbers, never "looks right"),
   *Verification* (the exact command), *Effects / notes for the reviewer*,
   *What is NOT done*.
4. **If a finding contradicts this plan, change the plan text in the same
   commit** and say so in the log. G-D2's revision is the precedent.
5. **Never mark a visual task done on unit tests alone.** G10, G4, G6 and G7
   end in a human watching a render. Say *"built, awaiting human pass"* and stop.
6. **Read §1 before touching the renderer.** Those invariants are inherited and
   already paid for in bugs.

### 0.2 ⚠ START HERE

**G0.** Three classifiers over data already in Postgres, plus a hand sample.
It prices every task below it and chooses **annotation-first vs chart-first**.

### 0.3 Standing constraints in this repo

- Do **not** set `PYTEST_TRUNCATE_DB=1` and do **not** run `make test`. Both wipe
  a SHARED Postgres holding real projects. Plain `pytest tests/unit` is safe.
- Never run seed with `--force`.
- Never delete anything under `backend/storage/**/overlays/` — real cached
  artifacts. New annotation/graphic clips live under
  `backend/storage/**/graphics/` (G5); same rule, do not delete.
- Do not run `ruff format`; the project uses black and the Makefile runs only
  `ruff check`.
- Clear leaked `*-test` project rows after test runs.
- Baseline with Postgres up, 2026-09-11: `pytest tests/unit` = **1698 passed, 6
  failed** (5 `test_sfx_overlays_diegetic.py` + 1
  `test_director_planner::test_every_attempt_is_recorded_as_an_llm_call`). ruff
  has **13 pre-existing errors** across 11 files. Match those numbers or explain.

---

## 1. Inherited invariants — binding, not up for renegotiation

These are not this plan's decisions to make. Each is already paid for.

- **D1 narration is the master clock.** A graphic or annotation never sets a
  duration. It is fitted to the shot the narration produced.
- **I2 immutable decision / I5 rendering is a pure function.** Content is
  decided at plan time, recorded in the versioned timeline, and the renderer
  is a pure function of it. No planner call at render time.
- **R2 fingerprint keys are present unconditionally**, `None` when moot. Every
  new render input follows this shape. **This is the single most repeated trap
  in this codebase.** An annotation clip that is not hashed will cache-hit and
  never appear. Keys this plan adds: `graphic_specs_hash`,
  `annotation_specs_hash` — both always present.
- **RV2 / R1 resolve a style knob once in the render caller and pass it down.**
  Never read a style band at a use site.
- **Fragment index, never seconds.** Anchoring is `anchor_fragment`; seconds
  are resolved later from real alignment.
- **Enforce in code after the planner returns, never by asking the prompt
  nicely.** K3's enforcement pass is the pattern.
- **Python owns geometry, the TSX consumes props.** A chart's box, a pointer's
  target rect, a highlight band, a number's slab — all Python.

---

## 2. The gap, concretely

### 2.1 `EmphasisValue` cannot describe a chart

Unchanged. `value: int`, no label, no form. Leave it for `counter` on
`retention_fast`. Long-form numbers live on `AnnotationSpec` / `GraphicSpec`.

### 2.2 The third `PicturePath` value does not exist

Unchanged in role, narrowed in meaning. `GRAPHIC` means **the Remotion opaque
clip IS the picture, buy no asset.** Annotation shots are **not** this path —
they still retrieve or generate a photo. G3.

### 2.3 Remotion is a full-length overlay producer, not a per-shot one

`compositor.py::_invoke_remotion` renders **one** composition (`COMPOSITION_ID =
"Emphasis"`) to **one** full-length alpha `.mov`, composited by
`emphasis_overlay_filter_fragment` as `overlay=0:0:format=auto`. That is the
right *kind* of tool for annotations and the wrong *shape* for ten minutes.

There is no path that renders a 2-second alpha clip for one shot and composites
it only inside that shot's fragment. That is G5 + G11.

The original G-D2 ("make the clip the picture, skip overlay") solved the cost
problem by deleting the layer that makes videos fun. Cost is solved by
**short clips**. Fun is solved by **keeping the layer, per shot**.

### 2.4 `picture_is_graphic` only ever says "no"

Unchanged. Flag is consumed only to *suppress* cues. Nothing draws. After this
plan: `True` means opaque `Graphic` / diagram (G3). Annotation shots stay
`False` so a photo is still acquired.

### 2.5 Long-form has no direction system

Unchanged. `long_form_direction.md`: the two 16:9 styles are planner-identical;
the Shot Planner is never told which act it is in. G8. Also: `punch_in`,
`split_frame`, and `text_card` already exist in the renderer and are almost
unused on 16:9. G6's fragment must ask for them. That is free visual change
with no new Remotion device.

### 2.6 Long-form has no annotation pass (the actual "no fun")

`EmphasisPassStep._is_retention_fast` returns false → the step no-ops. Stamps,
counters, pivots never author on `documentary_archival` / `stillness`.
**Do not lift that gate.** Importing K9 onto 10 minutes would ship 12 cues/min
and `pivot` bands — shorts identity, which this plan explicitly refuses
(G-D11). Long-form gets a new evidence pass with a different density and a
different device list (G2).

### 2.7 One value has no long-form device

K8 corollary: a one-bar chart is a bug; one spoken number is a `counter` over
the picture. On long-form that counter currently does not run, and G-D3 would
also refuse the chart. Without `AnnotationSpec.device = number`, single-number
shots stay dead photos. That is most "₹ / % / lakh" lines.

---

## 3. Decisions taken in this plan

**G-D1 — Per-shot clips, not a longer alpha layer.** Unchanged in force,
widened in kind. Both `Annotate` (alpha) and `Graphic` (opaque) are short
clips, content-hashed, produced concurrently through `bounded_gather`.
`retention_fast`'s full-length `Emphasis` overlay is **untouched**. Do not
merge the three compositions.

*Rejected:* extending the 10-minute alpha overlay. 5× more expensive, cannot
cache per shot.

**G-D2 — REVISED 2026-09-11. Default is annotation over the plate. Opaque
designed-ground graphic is the escalation, not the default.**

K8's measured failure (counter on an AI infographic, both unreadable) still
stands. Its documented fallback — *"escalate to full-frame on a designed
ground"* — is **when type and plate fight**, not a reason to delete every
plate. Winning explainers **stack**: B-roll or a document **plus** a pointer.

| Shot job | Picture | Remotion |
|---|---|---|
| One number, a name, a quote, a document clause, "look here" | **Photo / screenshot, keep it** | `Annotate` alpha on top |
| Several values, a trend, part-to-whole, before→after | **None** (G3) | `Graphic` opaque |
| Process (`COAL → GAS → FUEL`) | **None** | diagram opaque (G7) |
| Type would sit on a busy fake infographic | escalate | `Graphic` opaque |

*Rejected:* original G-D2 as a universal law. It produces the "corporate chart
on a void" minute the user called no fun.

**G-D3 — Four permitted chart forms, and a ban.** Unchanged for opaque
`Graphic`. Column, line, stacked bar (horizontal), dumbbell. **Banned: pie and
donut.** One value is **not a chart** — it is `Annotate.number` over the photo.

**G-D4 — Chart colour rules, inherited not invented.** Unchanged. Project
palette, one axis, sequential default, emphasis over categorical when the
narration is saying one number, `est.` / hatch for inferred (G-D5).

**G-D5 — Inferred values render as outline + `est.` on the mark.** Unchanged.
Applies to `Graphic` marks and to `Annotate.number` when `cited_fragment` is
None.

**G-D6 — Explainer diagrams are a separate task with a separate grammar (G7).**
Unchanged. One diagram per shot. Persistent-across-shots is
`animated_explainer.md`.

**G-D7 — Closed annotation vocabulary.** Five devices, no kitchen sink. Port
existing motion (spring, cluster stagger, `Intl.NumberFormat("en-IN")`) rather
than inventing.

| Device | Job | Looks like (market) | v1 honesty |
|---|---|---|---|
| **`pointer`** | "yeh dekho" | arrow or ring on a region | region is a **Python box** (safe-area centre, or a 3-slot grid: left/centre/right). Not OCR, not a mouse cursor |
| **`highlight`** | document theater | yellow bar / crawl on a clipping | v1 is a **band in the middle third** of a document-like plate, timed to the fragment. It does **not** OCR the sentence. Say so on every watch pass. True bbox highlight is a later plan |
| **`number`** | one cited value | counter / pop | the long-form counter. Hold ~1.3s. Indian grouping. Over the photo, slab if K4 would have |
| **`stamp`** | year / FACT / named lockup | rubber stamp | **rare.** Not the 12/min reel stamp. Chapter-level or correction |
| **`callout`** | lower-third fact | "EMI rises 18%" box | one line, bottom-safe, must not collide with captions (Python band; 16:9 caption MarginV is 4%) |

**Banned on 16:9:** `pivot` (full-bleed band is shorts), meme/emoji flashes,
pie, dual-axis, hover/tooltip (there is still no pointer-as-mouse; G-D4's old
line meant that, and it still does).

**G-D8 — Density is documentary-evidence, not reel-kinetic.** At most **one
`AnnotationSpec` per shot**. Target: on the evidence style, a visual question
(new picture, punch, split, annotation land, or opaque graphic) **inside every
8 seconds of a data-heavy act**. Cap **≤4 annotation shots/min** so a 10-minute
film is ~20–40 lockups, not 120. Enforce in code after the planner returns,
K3-style. Hook window (first 15s of the film, gap 1) may front-load; body uses
the cap.

**G-D9 — Two compositions, one producer.** `Annotate` (G10) and `Graphic` (G4)
are separate Remotion compositions. `render_or_reuse_graphic_clip` (G5) is the
shared cache/hash/invoke. Python still owns geometry.

**G-D10 — Composite annotation at shot-build time, not as a timeline-length
overlay.** Each annotated shot: Ken Burns (or punch / split) the plate, then
`overlay` the short alpha clip for that shot's duration, then duration-fit.
The concat graph does not grow a 10-minute overlay input. Track C's argv / OOM
lessons apply: do not reintroduce a film-length layer. Opaque `Graphic` clips
already *are* the shot picture via the motion-clip path — no overlay step.

**G-D11 — Do not turn on `EmphasisPassStep` for long-form.** New
`EvidencePassStep`, style-gated to the G6 band (and only that band). Different
prompt, different density, no `pivot`. Reusing K9 is how 12/min yellow type
lands on a GDP documentary.

**G-D12 — Existing renderer verbs are part of the kit.** G6's Shot Planner
fragment must request `punch_in` on document/number beats, `split_frame` on
before/after and "person + receipt", `text_card` on chapter titles. These
already render. Underuse is a prompt problem, not a Remotion problem.

**G-D13 — Do not edit `documentary_archival.md` or `stillness.md` to get
this look.** Those two fragments are the quiet documentary. The archival
one **bans `punch_in` on act-length films** (line 6: a hard zoom snap is
"the wrong register"). Stillness bans punch, split, pan, and almost all
text cards. Putting evidence grammar in those files would change every
existing 16:9 project. The evidence look is a **new style + new fragment**.
The base `shot_planner/v1.md` K13 rule ("figure → scene, not a chart")
stays: it is what makes `Annotate.number` reachable. The new fragment
*overrides* it only for multi-value / process shots.

**G-D14 — The style id is `explainer_evidence`.** One name, used in
`STYLE_PACING_BANDS`, `STYLE_GRADES`, `_STYLE_DESCRIPTIONS`,
`script_suitability/v1.md`, `frontend/src/lib/styles.ts`, and
`STYLE_DEFAULT_CANVAS`. A new style that misses any of those is the
illustrated_risograph / archival_montage lockstep bug: suitability
fabricates a verdict from the raw id, the UI never offers the style, or
the grade silently falls back to archival. G6 lands all of them in one
task. Label: **"Evidence explainer"**. Hint: **"16:9 · photos + pointers,
numbers, document zooms"**.

---

## 3.1 What this improves — a watchable minute, and what it will not

Reference topic: *"why your home-loan EMI jumped."* Today that minute is a
voice over a bank photo, then a rupee photo, then an AI pie. After v1 (G10+G11+G6)
and then G4:

| Time | Today | After this plan |
|---|---|---|
| 0–4s | Channel-less Ken Burns of a bank | `number` `+₹4,200 / month` pops on the still; impact SFX already exists |
| 4–10s | Same photo, slow push | `callout` lower third "Repo hike → floating loans"; `punch_in` on the phrase |
| 10–18s | Unrelated stock | Screenshot of the circular; `highlight` band; punch |
| 18–26s | Another photo | Opaque diagram G7, *or* v1: `pointer` on a simple generated schematic |
| 26–34s | Photo of a house | `split_frame` 2022 vs 2025; G4 bars if shipped, else two stills + `number` |
| 34–42s | Portrait, slow pan | Circle is later; v1: portrait + `stamp` `SAID IN 2023` + `callout` quote |
| 42–60s | Drift | Next proof object or chapter `text_card` |

**What gets better**

- Data beats stop *lying* (fake infographic JPEGs) and stop *disappearing*
  (stock standing in for a number).
- The eye has a job every few seconds on evidence acts — the actual retention
  mechanism of faceless long-form, not "we added a chart style."
- Single-number lines finally have a device (G-D3 + G-D7 `number`) without
  importing shorts kinetic identity.
- Photo shots **keep the world**. The annotation points at something.
- Render cost stays bounded (G-D1 / G-D10). Re-editing one number reburns one
  clip.
- Chart honesty (K8) is intact: no invented source, inferred looks inferred.
- Asset spend drops only on opaque graphic shots (~the old 20–34% on GDP
  films). Annotation shots still buy the photo — that is intended.

**What does not get better**

- No host, no parasocial chapter-break.
- No animated maps / routes (explicitly later, not a silent G13).
- No OCR-accurate sentence highlight in v1. The crawl is a convention.
- No persistent diagram across shots.
- Non-data films (biography, archival story) gain only sparse stamp/callout/
  punch. They will still mostly be documentaries. That is honest.
- Joke timing, match-cut headlines, Harris collage, Kurzgesagt worlds: out.
- `documentary_archival` **as it exists today** does not pick this up. New
  style (G6) or a re-plan onto it. Re-render of an old timeline will not
  author `AnnotationSpec`.

---

## 4. ⛔ G0 — GATE: the census, now two surfaces

**Do this first, alone.** It prices everything else and it can close the plan
— but the close condition is **both** surfaces empty, not "few charts."

### G0.1 — Chart-shaped (original)

Sample ~80 of the 124 data-shaped prompts. Classify: *column / line /
part-to-whole / before-after / process diagram / not a graphic*. Hand table
in the log. If 40% land in a fifth bucket, change G-D3 before building G4.

### G0.2 — Citable anchors (original)

For each chart-classified shot: does the spanned narration contain at least
one value under `emphasis_rules._fragment_contains_value`? A chart with no
anchor is undrawable under K8.

### G0.3 — Annotation-shaped (added 2026-09-11)

Same sample, plus ~40 shots **not** in the 124, so we do not only look where
the regex already fired. Classify: *document/headline / single number /
quote-or-name / comparison / pointer-at-region / none*. This is the fun
surface. A "crore" in a prompt that is really a street scene + one number is
G0.3, not G0.1.

**Thresholds, stated before the measurement:**

- **Annotation-shaped ≥25% of shots on data-heavy long-form (or ≥15% across
  the whole sample) → G10 is the v1.** Charts (G4) follow even if G0.1 is
  mediocre.
- **≥15% chart-shaped AND ≥70% of those have a citable anchor → G4 is on the
  critical path** alongside G10.
- **5–15% charts, anchors <70%, but G0.3 live → G10 + G7 (diagrams need no
  number). Do not weaken guardrail 1 to save G4.**
- **<5% charts AND <15% annotation-shaped → close this plan.** The channel's
  long-form wants archival pictures and camera moves
  (`long_form_direction.md` / `documentary_archival_watchability.md`), not
  this.

**Cost:** no API spend, no render. Queries + human reading. Half a day. Run
every census query **before** a pytest session (`clean_database` truncates).

---

## 5. The build, cheapest first — how to actually do it

### How the pieces click (read this before G1)

```
EvidencePass (G2)   after narration, like K9, different prompt
        │
        ├─ AnnotationSpec  →  PicturePath stays retrieval/generation
        │                    asset planner BUYS the photo
        │                    G5 renders Annotate alpha clip (~2s)
        │                    G11 overlays it on that shot's plate
        │
        └─ GraphicSpec     →  PicturePath.GRAPHIC, buy nothing
                             G5 renders Graphic opaque clip = the picture
                             motion-clip path already fits duration
```

Fingerprint (R2): `annotation_specs_hash` and `graphic_specs_hash` always
present, `None` when the style resolves neither. Prove with a cache **MISS**
when one datum changes.

Do **not** author either spec inside the Shot Planner. Shot Planner picks
`picture_is_graphic` / camera / whether the plate should look like a document.
Evidence pass authors the overlay/chart from narration + those flags, then
code enforces. Same split as K9 vs K3.

### G1 — `GraphicSpec` + `AnnotationSpec` on the timeline

Two models on `Shot`. One of them, or neither, never both (validator).

```python
class GraphicDatum(BaseModel):
    label: str                      # "2019", "Imports"
    value: float                    # float — percentages exist
    cited_fragment: int | None      # None == inferred (K8 guardrail 1)

class GraphicSpec(BaseModel):
    form: Literal["column", "line", "stacked_bar", "dumbbell"]
    title: str | None
    unit: str | None
    data: list[GraphicDatum]
    trend: Literal["rising", "falling", "flat"] | None
    emphasis_label: str | None      # which datum the VO is saying NOW

class AnnotationSpec(BaseModel):
    device: Literal["pointer", "highlight", "number", "stamp", "callout"]
    cited_fragment: int | None
    text: str | None                # stamp / callout copy; cluster-safe
    value: float | None             # number device
    unit: str | None
    target: Literal["center", "left", "right"] = "center"  # pointer / highlight
```

No `source` field, ever (K8 guardrail 5). Every field the planner must author
is **required, no default** (K12 silent-False trap).

`GraphicSpec` label budget still enforced in G2. `AnnotationSpec.text` character
budget: stamp 10 Latin / 14 Devanagari (K15); callout one line, ~28 chars
(K18's chunk size is the right order).

### G2 — The evidence planner, and the guardrails in code

New step `EvidencePassStep`, same slot as `EmphasisPassStep` (after
narration). Gate: `resolve_evidence_pass(style)`, not a style-name
literal. Prompt: `prompts/evidence/v1.md` — **copy from §5.1**, do not
reuse `emphasis/v1.md`. Output schema matches `AnnotationSpec` /
`GraphicSpec` (G1); every field the model must author is required, no
default (K12).

One LLM pass over the film (or per act once G8 exists), then a pure
enforcement function:

1. **Device picker, in code order, not prompt order.** If `len(values) >= 2`
   and a form fits G-D3 → `GraphicSpec`. Elif one cited value → `number`.
   Elif the shot was planned as a document/screenshot → `highlight`. Elif a
   named entity / quote → `callout` or `stamp`. Elif the VO is deictic
   ("yeh", "this clause", "look") → `pointer`. Else nothing.
2. **Anchor citation** for `GraphicSpec` and for `number` — reuse
   `_fragment_contains_value`. No citable anchor → **drop**, log it. Do not
   draw.
3. **Plausibility** for inferred graphic data (G-D5).
4. **Density** G-D8. Index gap + per-minute cap.
5. **Mutual exclusion.** `GraphicSpec` and `AnnotationSpec` cannot coexist.
   `GraphicSpec` and `text_card` cannot. `AnnotationSpec` and `emphasis_cue`
   cannot (shorts overlay vs long-form overlay on the same shot is undefined).
   `picture_is_graphic` must be True iff `GraphicSpec` is set — enforce after
   both planners return, so K13 cannot recur (number shots must NOT be
   flagged graphic or `number` is unreachable).

⚠ Structured-output strict mode drops defaulted fields (K12). ⚠ Specs are
plan-time: a G2 change needs a re-plan, not a re-render.

### G3 — Third `PicturePath` value

`GRAPHIC` only when `GraphicSpec` or a G7 diagram is present. Asset planner
resolves **no** asset. Enforced after Asset Planner returns.

Annotation shots: **do not** set `GRAPHIC`. The photo is the plate. A document
beat should be prompted as a clipping/screenshot/circular, not as "infographic
of the number" (that is how K13 / K8's fake pie get planned).

### G10 — The Remotion `Annotate` composition  **(v1 visual; watch this first)**

New composition `id="Annotate"`, props-driven, **alpha**, 1280×720 (from
Python canvas). Devices in G-D7. Port `Counter.tsx` / `Stamp.tsx` motion;
new TSX for pointer (spring arrow or ring), highlight (rect crawl), callout
(lower-third box).

Python passes: canvas, palette, device, text/value, `band` rects, hold frames.
Devanagari: `Intl.Segmenter`, variable-font `wght` (K6).

**Watch gate:** one 60-second GDP/EMI cut, real narration if a project is
handy, otherwise a props fixture. Pass is "I want to keep watching," not
"the box is on screen." Fail is CapCut-spam or corporate lower-thirds. Tune
before unlocking G4.

Not done on unit tests.

### G5 — The per-shot clip producer, cache, and fingerprint

Mirror `render_or_reuse_emphasis_overlay`, two output flavours:

- **Alpha** `Annotate` → ProRes 4444 / `yuva444p10le` (same as today's overlay;
  we need the hole). Short: hold + 2–4 frame pad, **not** the shot length if
  the shot is 5s and the number holds 1.3s. G11's `enable='between(t,…)'`
  places it. Cache key includes device + props + lockfile hash.
- **Opaque** `Graphic` → a non-alpha intermediate. Confirm `MediaKind.MOTION`.
  Duration **is** the shot (fitted).

Paths: `storage/{project}/graphics/{hash}.mov`. Byte-determinism was verified
for the overlay on this machine; still key on `package-lock.json` for
cross-version. Fingerprint keys unconditional (R2). Prove MISS.

Produce **before** ffmpeg, `bounded_gather`, one ffmpeg semaphore (Track C).
No second pool.

### G11 — Shot-build overlay

The architectural partner of G-D10. In the per-shot visual filter (wherever
Ken Burns / punch / split / motion is assembled today):

```
[plate]  = existing shot visual (still path, punch, split, motion-fit)
[annot]  = G5 alpha clip, setpts shifted to the cue's offset inside the shot
[plate][annot] overlay=0:0:format=auto:enable='between(t,local_start,local_end)'
```

Do **not** add a second film-length input in `render.py` next to
`emphasis_overlay_filter_fragment`. That is the 14-minute trap.

If a shot is `GRAPHIC`, skip this; the plate *is* the clip.

Ends in ffprobe: annotation input duration << shot duration, overlay only
inside the window, no argv blow-up on a 80-shot timeline (measure argv
length; Track C's 185-shot OOM is the ghost).

### G6 — `explainer_evidence`: band, lockstep registries, prompts

This is the style the user picks at project creation. Old
`documentary_archival` projects do **not** pick it up on re-render (G-D13).
A re-plan onto `explainer_evidence` is required.

#### G6.1 Band — reasoned starting points, not measured

New `STYLE_PACING_BANDS["explainer_evidence"]`. Do **not** copy
`retention_fast` geometry or density. Inherit palette discipline and
honesty. Every number below is a starting point in the same epistemic
class as `archival_montage`'s 2.25s — recalibrate after a watched film.

```
name: explainer_evidence
render_width / render_height: 1280 × 720
target_shot_duration_s: 4.0          # visual-question window (G-D8)
min_shot_duration_s_override: 1.5
max_shot_duration_s_override: 8.0    # dead-stop; do not hold a still 12s
max_shots_override: None             # long-form capacity, like archival
narration_speed: 1.15                # slight urgency; below montage 1.25
                                     # Hinglish warning. Listen before 1.2+.
music_bed_gain_db: -12.0
music_duck_gain_db: -16.0            # between archival -14/-20 and montage
whoosh_enabled: True                 # punches are sparse, unlike retention_fast
transition_sfx_structural_only: False
picture_path: RETRIEVAL_LADDER       # G3 is per-shot GRAPHIC, not this band
emphasis_* (slab, gap, hook, accent, stamp_top, caption_chunk): all None
                                     # so K9 still no-ops (G-D11)
evidence_pass: True                  # NEW band field, default False on every
                                     # other style. Read through
                                     # resolve_evidence_pass (RV2).
```

`StylePacingBand` gains `evidence_pass: bool = False`.
`EvidencePassStep` gates on `resolve_evidence_pass(style)`, never
`style == "explainer_evidence"`. Same shape as `resolve_emphasis_min_shot_gap`.

Grade (`STYLE_GRADES`): start at archival-plus — `contrast=1.08,
saturation=0.95, brightness=0.0`. Punchier than muted archival, short of
montage's 1.10/1.05. Identity-grade is wrong: these are still photographs.

#### G6.2 Lockstep — miss one of these and the style is silently broken

`test_suitability.py` already asserts `_STYLE_DESCRIPTIONS.keys() ==
STYLE_PACING_BANDS.keys()`. Archival_montage and illustrated_risograph
each shipped without a row once. G6 includes **all** of:

| Registry | What to add |
|---|---|
| `app/script/styles.py` `STYLE_PACING_BANDS` | the band above |
| `app/script/styles.py` `resolve_evidence_pass` | new, RV2 |
| `app/script/suitability.py` `_STYLE_DESCRIPTIONS` | see copy below |
| `app/prompts/script_suitability/v1.md` | one new bullet (this file **is** edited; it is the one shared prompt that must name every style or the model fabricates) |
| `app/renderer/grading.py` `STYLE_GRADES` | the grade above |
| `frontend/src/lib/styles.ts` `RENDER_STYLES` | `{ id, label: 'Evidence explainer', hint: '16:9 · photos + pointers, numbers, document zooms', targetShotDurationS: 4.0, gradeHint: 'Slightly punchier than archival' }` |
| `frontend/src/lib/resolution.ts` `STYLE_DEFAULT_CANVAS` | `explainer_evidence: { width: 1280, height: 720 }` |
| `DirectorPlanner._system_prompt_for` | append `load_style_fragment("director", render_style)` when present, **after** the generation_only block. `render_style=None` stays byte-identical to today's base prompt (same regression the generation_only fix paid for). |

Suitability description (both dict and `script_suitability/v1.md` bullet,
keep in lockstep):

> 16:9 long-form explainer: real photographs and documents, with on-screen
> numbers, highlights, and pointers landing as the voice says them, and
> full-screen charts only when several figures are being compared. Right
> for GDP, policy, scams, home loans, process explainers. Wrong for solemn
> memorial (that's stillness) and wrong for 9:16 punchy reels (that's
> retention_fast). Pictures are still found, not generated-only, so the
> archival material test in question 3 still applies.

#### G6.3 Prompt inventory (binding)

| File | Action | Why |
|---|---|---|
| `prompts/shot_planner_styles/explainer_evidence.md` | **NEW** — load-bearing. Full text in §5.1 | Shot Planner already loads `load_style_fragment`. |
| `prompts/evidence/v1.md` | **NEW** — G2 owns the step; G6 lands the file so the style has a pass. Full text in §5.1 | Do **not** reuse `emphasis/v1.md`. |
| `prompts/director_styles/explainer_evidence.md` | **NEW**. Full text in §5.1 | Director today only appends `generation_only.md`. G6.2 wires the fragment. |
| `prompts/script_suitability/v1.md` | **EDIT** — add the bullet in G6.2 | Lockstep. Only shared prompt that must name the style. |
| `prompts/director/v1.md` | **Do not edit** | Shared. "Not flashy animation" stays correct for archival. |
| `prompts/shot_planner/v1.md` | **Do not edit** | K13 block (lines 137–146) is what makes `Annotate.number` reachable. Override only in the new fragment. |
| `prompts/shot_planner_styles/documentary_archival.md` | **Do not edit** | Line 6 bans `punch_in` on act-length films. G-D13. |
| `prompts/shot_planner_styles/stillness.md` | **Do not edit** | Opposite thesis. |
| `prompts/asset_planner/v1.md` | **Do not edit** | G3 is **code** after return. |
| `prompts/asset_planner_styles/explainer_evidence.md` | **skip v1** | Asset Planner does not load style fragments. Search follows the Shot Planner `prompt`. |
| `prompts/emphasis/v1.md` | **Do not edit, do not call** | G-D11. |
| `prompts/script_rewrite/v1.md` | **Do not edit** | Finer cuts live in the Shot Planner fragment, not rewrite. |

#### G6.4 Without these prompts, Remotion can draw and the film still looks like today

| If you skip | What the planner still does |
|---|---|
| New Shot Planner fragment | Long holds; **no punch_in** (archival ban is in the other file, but the *base* table also says punch is "rarely right"); number beats become a bank photo **or** a fake infographic; two figures get combined into one 12s still. |
| K13 override in that fragment | Every "18%" shot is `picture_is_graphic=true` → G2 cannot put `number` on it (K13 / G2 rule 5). Or the plate is an AI pie and K8 unreadability returns. |
| Director fragment | `visual_style` asks for "infographic, dashboard, pie chart" → asset search / image model paints the data into the photo → annotation sits on a second copy of the number. |
| `evidence/v1.md` + `EvidencePassStep` | Style is picked, shots look right, **nothing draws**. Same hole as `picture_is_graphic` today. |
| Suitability / UI lockstep | Style is unselectable, or the model fabricates a verdict from the raw id. |
| Editing `documentary_archival.md` instead | Every existing 10-minute archival film suddenly punch-zooms. |

#### G6.5 G6 done-when

A **new** project created as `explainer_evidence`, planned through Shot
Planner (evidence pass may still be a stub if G2 is not yet wired — then
stop at JSON): shots mix (queue photo, `picture_is_graphic` false),
(circular photo + `punch_in`, false), (two-number compare, true, prompt
has **no** bars/pies/axes). Not a render of overlays — read the timeline.
Human watch of the G10 overlay on that timeline is G10+G11, not G6.

Copy the prompt files from §5.1. Do not paraphrase them in the implementer's
own voice.

---

## 5.1 Prompt texts — copy these (do not invent a second version)

These are the G6/G2 files. Implementers paste them. If a watch pass needs
a wording change, change **this section and the file in the same commit**.

### `backend/app/prompts/shot_planner_styles/explainer_evidence.md`

~~~~
## Style override: explainer_evidence

This project uses the `explainer_evidence` style — a 16:9 long-form
explainer whose picture is still a photograph or document, with a later
pass drawing numbers, highlights, and pointers on top, and a full-screen
chart only when several figures are being compared. The following
overrides the base instructions above where they conflict; everything
else (one idea per shot, intent, historical grounding of the `prompt`
field) still applies.

- **This style is evidence-on-picture, not a quiet hold.** The base
  intent→camera table still applies, with three overrides. (1) `emphasize`,
  and any shot whose `prompt` is a document, circular, headline, clipping,
  receipt, rate sheet, or screenshot, uses `punch_in` — a hard zoom snap
  onto the proof. (2) `compare`, before/after, and "a person + what they
  said / a receipt" use `split_frame` (`prompt` top, `secondary_prompt`
  bottom, as the base already requires). (3) If you are told this scene
  opens an act, that scene's first shot may carry a `text_card` naming
  the chapter — use the exact wording from the Long-form context `act:`
  line, not a paraphrase. Elsewhere `text_card` stays empty.
- **`punch_in` is in-register here.** The base table says it is rarely
  right for slow styles; ignore that for this style. Intensity on a punch
  stays inside 0.10–0.25. Do not punch every shot — only document,
  number, and emphasize beats. Other shots keep `slow_push` / `pan` /
  `static` / `pull_back` as the base table says. `fadeblack` is the
  act-boundary transition when you are told the scene opens an act;
  otherwise `cut` on evidence beats, `dissolve` on continuous mood.
- **Override the base "when the narration STATES A FIGURE, depict a
  scene" rule as follows, and only this far.**
  - One number ("18%", "two lakh", "₹4,200 extra a month") → depict the
    *scene or the source document*, and leave `picture_is_graphic` false.
    A later pass draws that number on top of your picture. Do not paint
    the digits into the plate (no "18%" on a sign, no rupee note with
    the amount written on it).
  - Two or more figures, a trend, a share, or a before/after →
    `picture_is_graphic` true. `prompt` names the *subject of the
    comparison in one line* (good: "India vs China manufacturing share,
    2014 and 2024"). It must **not** describe bars, pies, axes, colours,
    legends, or "an infographic of". A later pass draws the chart;
    inventing one in the prompt is treated as close to forgery.
  - A process (A then B then C) → `picture_is_graphic` true, same "do
    not draw the diagram in the prompt" rule. Name the steps in prose
    ("coal to gasification to liquid fuel") so a later pass has labels.
- **Document theater.** When the narration cites a rule, circular,
  headline, tweet, clause, judgement, or "this line" / "yeh line" → the
  `prompt` is that object as a photographable still (RBI circular on a
  desk, newspaper clipping, screenshot of a rate sheet), not a person
  reading it, not an infographic of its number. Use `punch_in`.
  `picture_is_graphic` is false — the paper is a photo; a later pass
  highlights it.
- **Do not combine a number-or-document fragment with the next
  scene-setting fragment** just to make a longer shot. An evidence beat
  needs its own shot so the overlay has a window. Other beats may still
  combine when they are one idea.
- **Never put overlay copy in `prompt` or `text_card`.** No "18% in
  yellow", no arrows, no circles, no "FACT" stamps. `text_card` is
  chapter signage only (act title), never the number being said.
- **`sfx_cue`:** documents, charts, and text cards stay silent, as the
  base already says. Do not author a whoosh or hit for a punch or a
  number land — those are render-side.
~~~~

### `backend/app/prompts/director_styles/explainer_evidence.md`

~~~~
## Style override: explainer_evidence

This project uses the `explainer_evidence` style. Append this to the
base Director instructions; where they conflict, this wins.

- **Visual world is proof objects, not infographics.** Prefer
  `visual_style` language like archival photographs, newspaper
  clippings, government circulars, bank queues, receipts, rate sheets,
  parliament, street-level consequence. Name the period and place
  exactly enough to search.
- **Never ask downstream to design a chart, pie, dashboard, bar graph,
  or "infographic of the GDP".** Those are drawn by a later pass from
  cited numbers. If you put "infographic" or "pie chart" in
  `visual_style` or `constraints`, image search and image models will
  paint fake data into the plate, which this pipeline treats as close
  to forgery.
- **Camera language:** measured 16:9 documentary, with hard punch-ins
  onto documents and numbers, and split-screens for then-vs-now. Not
  whip pans, not "kinetic typography", not meme edits, not a host on
  camera.
- **Tone:** explainer, not memorial and not a 9:16 reel. Music may sit
  a little more forward than a quiet archival film, still under the
  voice. Keep `search_terms` as simple literal tags (`documentary`,
  `cinematic`, `strings`, `tension`), never production-library jargon.
~~~~

### `backend/app/prompts/evidence/v1.md`

G2's pass. Lands on disk in G2 or G6, whichever ships first; both
commits must leave this exact file.

~~~~
# Evidence Planner

You author the on-screen evidence devices for one `explainer_evidence`
long-form film. You see the whole film: every scene's narration, every
numbered fragment, every shot (intent, prompt, picture_is_graphic,
text_card, duration). You emit every annotation or chart spec in this
one call.

You do **not** decide when something appears in seconds. You name a
fragment INDEX (`cited_fragment` / `anchor_fragment`). Code times it
later from real alignment. Never emit seconds, never guess a timestamp.

You do **not** emit `pivot`. You do **not** emit shorts kinetic identity.
This is not the emphasis planner.

## What you may emit (exactly these)

Per shot, **at most one** of:

- `annotation` with `device=number` — the narration STATES exactly one
  figure on this shot, and `picture_is_graphic` is false. `value` is
  that figure as a float (`2 lakh` → `200000`, `18%` → `18`, `₹4,200`
  → `4200`), `unit` is `"%"`, `"₹"`, `""`, etc. `text` is a short kicker
  (`EMI`, `SHARE`) or empty. `cited_fragment` is the fragment that
  states it. Never invent a supporting year or a source line.
- `annotation` with `device=highlight` — the shot's picture is a
  document, circular, clipping, screenshot, or rate sheet (read the
  `prompt`). `cited_fragment` is the clause being read. `text` empty.
  `target` is `center` unless the prompt is clearly a left- or
  right-stacked page.
- `annotation` with `device=pointer` — the narration is deictic ("yeh",
  "this clause", "look at", "idhar") and the picture is a scene or
  document, not a graphic. `target` `center` / `left` / `right`.
- `annotation` with `device=callout` — a named entity, a quote, or a
  one-line fact that is not a number (`SAID IN 2023`, a ministry name).
  `text` is at most 28 characters, copied from narration where possible,
  not translated. `cited_fragment` set.
- `annotation` with `device=stamp` — a year lockup or a single charged
  word the narrator said (`2016`, `SCAM` only if the narrator said it).
  Length budget: 10 Latin characters or 14 Devanagari, spaces included.
  Rare — prefer `callout` unless it is a year or a one-word verdict.
- `graphic` — the shot has `picture_is_graphic=true` AND the narration
  spanning it states **two or more** citable figures, or is a process.
  `form` is exactly one of `column`, `line`, `stacked_bar`, `dumbbell`.
  Each `data[]` entry has `label`, `value` (float), `cited_fragment`
  (or null if inferred). At least one datum MUST have a
  `cited_fragment`. `emphasis_label` is the datum the voice is saying
  NOW. `title` short or null. Never a pie, never a donut, never a
  one-bar chart (one value is `number`, not `graphic`). Never invent a
  source, logo, or "Data: …" line. There is no `source` field.

Skip a shot that already has a `text_card`. Skip a shot that should be
quiet (establishing place with no figure, no document, no name).

## Density

At most one device per shot. Front-load the first ~15 seconds (consecutive
shots may both carry a device there). In the body, leave gaps — a
visual question every few shots, not every shot. Code will cap you at
4 annotation-or-graphic shots per minute and drop the rest; prefer
dropping scene-setting callouts before dropping a cited `number` or a
`graphic`. Do not try to count per-minute yourself across the whole
film; hit the important evidence beats and trust the cap.

## Honesty

- Only cite a number the fragment actually states (digits or spoken
  "two lakh" / "atharah percent" / "pachas hazaar"). If you are not
  sure, do not emit the device.
- Inferred extra points on a `graphic` (a year the voice did not say,
  to make a line) must have `cited_fragment` null. Do not infer a
  source. Do not infer a value more than one order of magnitude off
  the anchor.
- Do not emit a `graphic` for a single number.
- Do not emit an `annotation` on `picture_is_graphic=true` shots —
  those are `graphic` or nothing.

## Palette

Do not emit colours. The project palette is already on the timeline.
~~~~

### `script_suitability/v1.md` — add this bullet only

Insert with the other style bullets, do not rewrite the three questions:

~~~~
- **explainer_evidence**: 16:9 long-form explainer — real photographs and
  documents, with on-screen numbers, highlights, and pointers landing as
  the voice says them, and full-screen charts only when several figures
  are compared. Right for GDP, policy, scams, home loans, process
  explainers that have something photographable (a bank, a circular, a
  city). Wrong for solemn memorial (that's stillness), wrong for 9:16
  punchy reels (that's retention_fast), and wrong when there is no real
  visual referent at all (question 3 still applies; this style still
  searches for photographs).
~~~~

### G4 — The Remotion `Graphic` composition

Original four forms, now clearly the **escalation**. Same producer as G5.
`emphasis_label` is the in-chart pointer (accent that bar, grey the rest).
Do not also fire `Annotate.pointer` (G2 exclusion).

Ends in a human watching four stills and one render.

### G7 — Explainer diagrams

Unchanged in grammar (nodes, arrows, labels, highlight states; one per shot;
closed vocabulary from `remotion_integration.md` §9). Shares G5. Own spec,
not `GraphicSpec`. Unblocked if G0.2 is weak.

### G8 — Chapter/act awareness

Unchanged. Persist act `title`, tell the Shot Planner and the evidence pass
which act they are in. Charts and highlights want the claim/evidence beat.

### G9 — Review surface for inferred values

Unchanged. Until it lands, guardrail 4 is "read the JSON."

---

## 6. What would kill this plan — stated in advance

- **G0: both surfaces empty.** Close it. Camera moves over archival pictures.
- **G0.2 anchors rare AND G0.3 also dead.** Do not weaken guardrail 1.
- **G10 watch fail: CapCut spam or corporate lower-thirds.** Tune density /
  type. If two watch passes still fail, close annotations and keep G4 only —
  that is the original plan, and the user already said it is no fun, so
  closing *annotations* and keeping *only* charts needs an explicit user
  confirmation, not a quiet fallback.
- **Per-shot clips not reusable** (every annotation unique). Cost argument
  still holds (scales with seconds). Record hit rate in G5.
- **Remotion determinism fails across a version bump.** Key on lockfile; if
  fragile, drop the cache rather than ship wrong figures.
- **G11 reintroduces a film-length overlay** "just for now." Forbidden. That
  is the measured 14-minute failure mode.
- **Someone lifts `_is_retention_fast`.** Forbidden (G-D11).
- **Someone edits `documentary_archival.md` instead of adding
  `explainer_evidence`.** Forbidden (G-D13). It would punch-zoom every
  existing archival film.
- **G6 ships the band but misses a lockstep registry.** Forbidden. The
  style is unselectable or suitability fabricates a verdict. G6.2 is the
  checklist.

---

## 7. Implementation log

### 2026-09-11 — Design revision: annotation-default, opaque-escalation

*Scope executed:* plan-only. No code. User rejected the original product
picture ("slideshow + occasional chart is no fun") and asked what 2024–2026
long-form explainers actually do, and whether this engine can do that.

*Changes:* this file. G-D2 revised; G-D7–G-D12 added; G0.3 added; G10/G11
added; v1 path is now Annotate-on-photo; G4/G7 remain the chart/diagram
escalation; G-D11 forbids lifting the shorts emphasis gate.

*Measured:* overlay cost numbers in §Verdict are still the 2026-09-11
`833dfd54` run (91s / 1958 frames / 1.40×). Market grammar is from a sourced
pass over Indian explainer overlay kits and Western faceless channels
(PolyMatter, Economics Explained, Wendover, Harris overlay craft). Not a
new render.

*Verification:* none (design). Next verification is G0 queries against
Postgres **before** any pytest.

*Effects / notes for the reviewer:* original G0 close-on-low-charts would have
killed the thing the user actually wants. That threshold is now "both
surfaces empty."

*What is NOT done:* G0 has not been run. Nothing in `compositor/` or
`app/renderer/` has changed. `EmphasisPassStep` is still shorts-only.
Prompt files are unchanged; G6's inventory is design only.

### 2026-09-11 — Prompt inventory for long-form styles

*Scope executed:* plan-only. User asked whether long-form styles need
prompt changes.

*Changes:* this file. G-D13 (do not edit `documentary_archival` /
`stillness`). G6 expanded to a per-file prompt table plus a draft of the
new Shot Planner fragment. Director needs `load_style_fragment` wired
(today it only appends `generation_only.md`). Asset Planner skip stays
code, not prompt.

*Measured:* `documentary_archival.md:6` bans `punch_in` on act-length
films; `shot_planner/v1.md:137-146` is the global K13 "figure → scene"
rule; `stillness.md` bans punch/split; Asset Planner and Director do not
load `*_styles/` fragments today except Director's generation-only block.

*Verification:* `load_style_fragment("shot_planner", "documentary_archival")`
already returns that file; there is no `shot_planner_styles` entry for a
new evidence style yet.

*What is NOT done:* no prompt file written. Style name not picked.

### 2026-09-11 — Full prompt texts, style id, lockstep

*Scope executed:* plan-only. User: "please add all of it in plan" after
the prompt-change analysis.

*Changes:* this file. G-D14 (`explainer_evidence`). G6 rewritten as band
+ lockstep registries (styles, grades, suitability, frontend, Director
wiring) + inventory + without-prompts failure table. §5.1 is the
copy-paste source for `shot_planner_styles/explainer_evidence.md`,
`director_styles/explainer_evidence.md`, `evidence/v1.md`, and the
suitability bullet. G2 points at that file. G6 effort 1.5–2d → 2–2.5d.

*Measured:* still no new render. Frontend `RENDER_STYLES` /
`STYLE_DEFAULT_CANVAS` and `test_suitability.py` lockstep are the
precedent this is matching.

*What is NOT done:* none of those files exist on disk yet. G0 not run.

*Empty of code entries. First implementation entry should be G0 — including a
close-out if both surfaces come back under threshold.*
