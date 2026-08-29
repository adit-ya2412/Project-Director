# Animated Explainer — a second format on the same spine

**Status:** DESIGN ONLY. Nothing built, nothing decided, no code touched.
**Written 2026-08-29** at the user's request, off the back of
`output_quality_pass.md` §18.7.1 (RV-Q24). This plan is deliberately
**gated**: §4 is a measurement that can kill the whole thing for under a
day's work, and no line of production code should be written before it
returns a number.

---

## Verdict up front

**The current pipeline cannot make "how earthquakes work" videos, and the
gap is not a missing feature — it is a different unit of composition.**

- This pipeline's atomic unit: **one picture per shot, plus a camera move
  over it.** Find or generate a still, push in on it, cut, next still.
- An explainer's atomic unit: **one diagram that persists and evolves
  across many beats.** The picture is not replaced at each cut; its
  *state* advances while narration explains it.

Nothing in `app/renderer/` can hold the second thing. Every shot resolves
its asset independently — there is no notion of *"the same diagram as
shot 3, two seconds later."*

**But the system is already reaching for this format and failing at it,
measurably.** That is the reason to write this plan now rather than
file it as a nice idea. See §1.

**Honest framing: this is a second product sharing this one's spine, not
a feature bolted onto the current planner.** Roughly a new asset strategy
plus a new renderer path plus a new planner contract. Anyone who scopes
it smaller than that has not read §3.

---

## 0. Navigation — read before writing any code

### 0.1 Pickup protocol

Same rules as `output_quality_pass.md` §0.1, restated because this plan
will most likely be picked up cold, months from now, by an agent that has
not read that one:

1. **§4 is the gate for everything else.** It is a measurement, not a
   build. If §4 comes back below its own threshold, **the correct outcome
   is to close this plan**, write that in §9, and stop. That is a success,
   not a failure.
2. **Do exactly one lettered task.** Do not bundle. Do not "while I was
   in there."
3. **Write a §9 log entry before finishing**: dated heading, *Scope
   executed*, *Changes* with `file:line`, *Measured* (real numbers, never
   "looks right"), *Verification* (the exact command run), *Effects /
   notes for the reviewer*, *What is NOT done*.
4. **If a finding contradicts this plan, change the plan text in the same
   commit** and say so in the log. A plan that silently disagrees with
   the code is worse than no plan.
5. **Never mark a visual task done on unit tests alone.** Every item in
   §5 and §6 ends in a human watching something. Say *"built, awaiting
   human pass"* and stop.
6. **Read §2 before touching the renderer.** The invariants there are
   inherited, already paid for in bugs, and are not up for renegotiation
   by this format.

### 0.2 ⚠ START HERE

**§4 — the realizability census.** It is a query and a classifier over
data you already have. It answers *"how much of what the planner already
asks for is an explainer frame?"* Everything downstream is priced off
that number, and if it is small the honest answer is to keep making
documentaries.

---

## 1. Origin — the system is already asking for this

Not a hypothetical market observation. `output_quality_pass.md` §18
measured the asset gate across 16 projects and found a **70% reject rate**
(313/448). §18.5b then replayed 12 archival rungs through the production
Wikimedia provider and ranker, and §18.7.1 read the result:

**the stable rejects cluster on shot prompts that describe a *composed*
image rather than a photographable one.** The load-bearing example, a
real production shot prompt:

> *"1940s German strategic map focused on Germany, stark dry fuel
> reservoir gauge and empty oil storage tank motif"*

with the production search subject derived from it:

> *"Germany strategic map 1940 / German wartime map / WWII oil storage /
> **empty fuel gauge**"*

Wikimedia Commons answers "empty fuel gauge" with a Honda dashboard, then
a Mazda dashboard. The gate correctly rejects both. **The photograph being
asked for was never taken.**

That prompt is an **explainer frame**: a map fused with a gauge motif to
convey *"Germany is running out of fuel."* It is the same visual logic as
"how floods work". Meanwhile the two rungs in that sweep whose top
candidate passed immediately were the two plainest nameable subjects —
a German tank column, an apartheid-era building with segregated signage.

**So the pull toward this format is already visible in the reject rate as
a defect.** §4 turns that observation into a count.

### 1.1 What this plan is *not*

- **Not** a fix for the 70% reject rate. That is `output_quality_pass.md`
  §15.7's thread and stands on its own.
- **Not** a replacement for the documentary formats. The four existing
  styles (`documentary_archival`, `retention_fast`, `archival_montage`,
  `stillness`) are unaffected by everything here.
- **Not** a general animation engine. The target is *diagrammatic
  explanation driven by narration* — a bounded visual grammar, and the
  bound is the only reason it is tractable.

---

## 2. Inherited invariants — binding, not up for renegotiation

Carried from `analysis.md`, `motion_new_styles_and_long_form_videos.md`,
`style_extensions.md` and `output_quality_pass.md`. Each was paid for in
a real bug. A new format does not get an exemption.

| | Invariant | What it means here |
|---|---|---|
| **D1** | **Narration is the master clock; picture is fitted to it.** | An explainer makes this *more* binding, not less: a diagram's state changes must land on the words that describe them. Never stretch narration to fit an animation. |
| **I5** | **Rendering is a pure function of its inputs.** | No wall-clock, no `set` iteration order, no RNG without a seeded, persisted value. An animation timeline is a *planned artifact stored in the timeline document*, never computed at render time from style alone. |
| **R2** | **Any value that changes render bytes enters `compute_render_fingerprint`.** | Every new field — diagram id, keyframe times, label positions, style token — must be in the fingerprint or the cache serves stale video. This is the single most likely way this feature ships broken. |
| **R16** | **Per-shot fingerprint data is keyed by `shot_id` in timeline order.** | An assignment, not a bag. Applies to per-shot animation state identically. |
| **RV2** | **Resolve once, thread explicitly.** | Diagram assets and their state resolve in the workflow step, and are threaded into the renderer. The renderer never re-derives them. |
| **canon 3.1** | **Camera decisions are written by the planner, never applied by the renderer from style alone.** | Extends directly: *animation* decisions are planner-authored too. The renderer executes a plan; it does not invent motion. |
| **A30 / §18.5b** | The depiction gate checks the top candidate and abandons the rung on reject. | Generated diagrams are not search candidates and must not be routed through that gate as if they were. See §6.3. |
| **§11 DB hazard** | `conftest.py`'s autouse `clean_database` truncates the shared dev Postgres. | Any census query in §4 runs **before** a pytest session, never after. |

---

## 3. The gap, concretely — three missing capabilities

What exists today, from `app/renderer/`: `still.py`, `ken_burns.py`,
`motion.py`, `split_screen.py`, `text_cards.py`, `captions.py`,
`grading.py`, `sfx.py`, `music.py`, `watermark.py`. That is a documentary
montage vocabulary: **a photograph, a camera move, and typography.**

### 3.1 Persistent visual state across shots — *missing*

Shot 4 does not know what shot 3 looked at. `resolve_assets` walks each
shot's `fallback_chain` independently and binds one asset. An explainer
needs a **scene object** that survives across shots: *this* cross-section,
in *this* visual style, now at *this* state.

Hardest of the three, because it changes the timeline schema and the
planner contract, not just the renderer.

### 3.2 Element-level animation — *missing*

`ken_burns.py` moves a **camera** over a fixed image (`zoompan`, with the
focal work from `output_quality_pass.md` §14 aiming it). An explainer needs
the **content** to move: water rising, an arrow tracing a path, a plate
sliding, a layer fading in on cue.

That is a different filter graph — compositing timed layers — not a
parameter change to the existing one.

### 3.3 Diagram authorship instead of photo retrieval — *missing*

The entire asset stack exists to *find a photograph that already exists*:
the ladder (`project_assets → historical_search → public_domain →
stock_search → generate_video → generate_image`), Wikimedia and Pexels
providers, ranking, the relevance gate, the depiction gate. Explainers
need images **made to specification**, in a **consistent visual language
across the whole video** — which no retrieval path and no per-shot
text-to-image call gives you.

### 3.4 What transfers unchanged — the reason this is worth considering

A large majority of the system, in fact:

- **D1 and the whole narration spine** — and D1 fits explainers *better*
  than documentaries, since the explanation's logic is the edit's logic.
- **The entire audio finishing stack** — loudness, ducking, the bed,
  SFX, `narration_tempo`, batched TTS, caption romanization.
- **Render, fingerprint, caching, the workflow engine, the review UI.**
- **`locate_subject` on gpt-5.5** (`output_quality_pass.md` §14) — it
  answers *"where in this image is X"*, which is exactly the primitive a
  label-anchoring system needs. Built, measured, already paid for.

**The spine is format-agnostic. The gap is entirely in the picture path.**

---

## 4. ⛔ GATE — the realizability census (do this first, alone)

**Question:** how much of what the planner already writes is an explainer
frame that retrieval can never satisfy?

**Method.** No new data collection — this is a query plus a classifier
over what is already in Postgres.

1. Pull every shot prompt and its `search_subject` from the timelines of
   3–4 archival projects (`b6a2ae69`, `3d56cf87`, `6b790c76`), joined to
   the recorded `depiction_check` verdicts in `llm_call`. §18.7.2 already
   specifies this join; reuse `scripts/measure_gate_reject_rate.py`'s
   read pattern rather than rewriting it.
2. Classify each prompt as:
   - **findable** — a nameable subject, event, person, or place a
     photographer plausibly stood in front of ("German tank column on a
     muddy road");
   - **composed** — fuses motifs, specifies an arrangement or an action,
     or names an abstract state ("strategic map with an empty fuel gauge
     motif", "dark liquid fuel flowing from a steel refinery pipe").
3. **Write the classifier's rule down explicitly, and hand-check a
   sample of its labels.** The entire finding rests on that boundary
   being real rather than fitted to the outcome. If an LLM does the
   labelling, it gets the §17.6 treatment: **more than one draw per
   item**, rates reported, unstable items flagged. `gpt-4o-mini`
   disagrees with itself on byte-identical input; a single draw is not
   a label.
4. Report: reject rate for **findable** vs **composed**, and composed's
   share of all shots.

**Thresholds, fixed in advance so the result cannot be rationalised:**

| composed share of shots | reject rate gap | verdict |
|---|---|---|
| < 15% | any | **Close this plan.** Not enough demand. Fix search terms instead. |
| 15–30% | composed rejects ≥ 2× findable | Worth §5's cheapest slice only (A1), then re-decide. |
| > 30% | composed rejects ≥ 2× findable | The format is worth building. Proceed to §5. |
| any | no meaningful gap | **Close this plan.** The composed/findable split is not the mechanism; the diagnosis in §1 was wrong. Say so in §9. |

**Cost:** well under a day. **This is the whole point of the plan being
written before anything is built.**

---

## 5. If the gate passes — the build, cheapest first

Deliberately ordered so each slice is independently useful and each one
can stop the sequence.

### A1 — Route composed shots to generation, up front

**The smallest useful thing, and it needs none of §3.1–3.3.**

Today a composed shot walks the ladder, burns 2–3 searches and a gate
call per rung, fails, and *then* falls through to `generate_image`. The
§18 census shows this costing real money and latency for an outcome that
was determined at planning time.

Have the shot planner mark a shot's `fallback_chain` as generation-first
when the prompt is composed. That is a planner change plus a
`fallback_chain` that legally starts at `generate_image` — already a
valid subsequence of `ASSET_LADDER`.

- **Buys:** the wasted searches back; the 20% generation fallback stops
  being a failure mode and becomes an intent.
- **Does not buy:** any visual improvement. The generated image is still
  a one-off, in no consistent style, with no state.
- **Human pass:** watch one render and confirm the generated frames are
  not *worse* than the archival misses they replace. They may well be
  better; that is not obvious and must be seen, not assumed.

### A2 — A locked visual language across a video

The first thing that makes a video *look* like an explainer rather than a
bag of unrelated AI images.

One **style token** per project — palette, line weight, era, flat vs
dimensional — resolved once (RV2), stored in the timeline, threaded into
every generation prompt, and entered into the fingerprint (R2).

- **Human pass:** two projects side by side. Do the frames read as one
  designed film?
- **Kill criterion:** if `fal_image_model` cannot hold a style across
  ~30 prompts, A3 and A4 are not worth attempting on this provider —
  record that in §9 and stop.

### A3 — Persistent diagram state (§3.1)

The schema and planner work. A `diagram` object on the scene, referenced
by shots, each carrying a **state delta** rather than a fresh prompt.

Open design question, do not pick without measuring: **regenerate per
state** (simple, risks visual drift between beats) versus **generate once,
animate a stored artifact** (stable, needs A4, and needs the generator to
emit something layered — likely SVG, which points away from
`fal_image_model` entirely).

### A4 — Element-level animation (§3.2)

The renderer path: timed compositing of layers over a base, planner
authored (canon 3.1), fingerprinted (R2), deterministic (I5).

Prerequisite for A4 being *cheap*: a layered source artifact from A3.
Doing A4 on flat raster output means masks and motion paths authored
blind, which is a much larger job.

---

## 6. Cautions, in the order they will bite

### 6.1 R2 is the likeliest way this ships broken
Every new field — diagram id, state index, keyframe times, style token,
label anchors — changes render bytes. Any one of them missing from
`compute_render_fingerprint` means the cache serves a stale video and the
bug shows up as *"my edit did nothing"*, days later. Add fingerprint
coverage in the **same commit** as each field, never after.

### 6.2 D1 inverts under pressure
The first time an animation looks better a beat longer, someone will want
to stretch narration to fit. **Do not.** Narration is the clock. If the
animation needs more time, the planner asks for more words, or the
animation gets faster.

### 6.3 Do not route generated diagrams through the depiction gate
A30 exists to catch *retrieval* handing back a Polish coal elevator for
Leuna. A generated diagram is made to the prompt by construction; asking
`check_depiction` "is this confidently wrong" is a question it was not
calibrated for, and §17.7 measured that gate flipping on identical bytes
2 times in 3 on hard images. It would reject good diagrams at random.
If generated output needs a check, it needs its **own** check, calibrated
separately — and its own entry in this plan.

### 6.4 Cost will not be invisible here
`output_quality_pass.md` §15.3 shipped the cost meter and the migration
is applied as of 2026-08-29, so from now on every LLM call carries real
`cost_cents` and its rates. **Use it.** A3's regenerate-per-state option
in particular multiplies image generation by the number of states; that
is now a measurable number instead of an argument, and §9 entries should
quote it.

### 6.5 This is a format, not a style preset
Resist implementing it as a fifth entry in `styles.py` alongside
`retention_fast` / `stillness`. Those four differ in *pacing, mix and
camera* over a shared picture path. This differs in the **picture path
itself**. Forcing it into `StylePacingBand` will produce a preset that
lies about what it does.

---

## 7. What would kill this plan — stated in advance

Any one of these is a legitimate close. Write it in §9 and stop:

- **§4 returns < 15% composed share**, or no reject-rate gap.
- **A2 fails**: the image provider cannot hold a visual language across a
  video. Everything visual downstream depends on it.
- **A1 ships and the generated frames are worse than the archival
  misses.** Then the composed prompts are the defect, and the fix is in
  the shot planner's *writing* — cheaper than everything in §5.
- **The audience is not there.** This plan proves the system keeps asking
  for explainer frames. It does not prove anyone wants explainer videos
  from this product. That is the user's call, not a measurement.

---

## 8. Open questions — unanswered on purpose

1. **Which generator?** `fal_image_model` (seedream v4) is text-to-image
   raster. A layered/SVG generator would make A4 far cheaper but is a new
   provider and a new failure surface. Undecided; A2 informs it.
2. **Regenerate per state, or animate one artifact?** §5 A3. Needs a
   measurement, not a preference.
3. **Do labels come from the generator or the renderer?** Renderer-drawn
   text is crisp, deterministic and translatable — and `text_cards.py`
   plus `locate_subject` already do most of it. Generator-drawn text is
   usually malformed and never translatable. Leaning renderer, unproven.
4. **Does this need its own review UI surface?** The existing one is
   built around per-shot asset swaps. A diagram spanning shots does not
   fit that model.
5. **Hindi/Hinglish?** Renderer-drawn labels inherit
   `caption_romanization.md`'s work. Generator-drawn labels do not.
   Another point for question 3.

---

## 9. Implementation log

*Empty. First entry should be the §4 census — including a close-out if
that is what it returns.*

Entry shape (from `output_quality_pass.md` §0.1):

```
### P-AE-<slice> — <title> (<date>)

**Scope executed:** exactly what, and explicitly what was NOT started.
**Changes:** file:line for each.
**Measured:** real numbers. Never "looks right".
**Verification:** the exact command run, and its output.
**Effects / notes for the reviewer:**
**What is NOT done:**
```
