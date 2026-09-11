# Long-Form Data Graphics — charts and explainer diagrams as the primary picture

**Status:** DESIGN ONLY. Nothing built, nothing decided beyond the decisions
recorded in §3, no code touched.
**Written 2026-09-11** at the user's request: *"what would it take to extend this
style to long form videos where charts or explainer diagrams are given priority,
using Remotion's help."*
**Letter:** this plan owns the **`G`** prefix. `A C D I K N Q R RV W` are taken by
existing plans; do not reuse them here, and do not use `G` elsewhere.

---

## Verdict up front

**Three of the four things this needs already exist. The missing one is a renderer
boundary, and the boundary we have today is the wrong shape — measured, not
assumed.**

What exists:

- **Long-form itself is done.** `track_c_long_form_video.md` closed 2026-08-20:
  planning at length, narration concurrency, per-run render caching, the argv
  limit, the 185-shot OOM, budget per minute, music per act. 90s → ~10 min is
  shipped, not scoped.
- **The chart *data policy* is fully decided** and is the hardest part of this
  problem. `retention_fast_kinetic_text.md`'s "Data graphics — the honesty
  problem" settles it: permissive-with-provenance plus five guardrails (anchor
  citation, inferred values must LOOK inferred, plausibility against the anchor,
  reviewable in the timeline, **never invent a source**). **Do not reopen any of
  it.** This plan consumes it verbatim.
- **A Remotion clip can already be a shot's picture.** Track A built the
  motion-clip input path: `app/renderer/motion.py` classifies media
  (`MediaKind.STILL | MOTION`), `_motion_filter` composites it, and
  `build_duration_fit_fragment` fits it to the shot's duration. A video input is
  no longer frozen to frame one.

What is missing, and why today's boundary cannot carry it:

**Remotion is wired in as a single full-length alpha layer, so its cost scales
with the video's RUNTIME rather than with how much graphic is in it.**

Measured on this machine, 2026-09-11, by rendering `833dfd54`'s real production
props (`overlays/49e575eb….json`, 9 sparse kinetic cues, 720×1280, ProRes 4444
`yuva444p10le`):

| | measured |
| --- | --- |
| frames | 1958 (65.3s @ 30fps) |
| wall time | **91s** |
| rate | 21.5 fps = **1.40× realtime** |
| output | 52,872,236 bytes = **27 KB/frame** |
| determinism | **byte-identical** to the cached `.mov` (sha256 `64e3e53c17d8e385…`) |

That layer is **almost entirely transparent** — nine brief cues across 65
seconds — and it still costs 1.40× realtime and 53 MB. Extrapolated to ten
minutes (18,000 frames):

- **~14 minutes of Remotion for an essentially empty overlay**, on top of Track
  C's measured **~18.6 min** of ffmpeg (1.86× realtime, Ken Burns) → **~33 min
  per render** before a single chart is drawn.
- ~486 MB at the same sparsity, and sparsity is exactly what a chart-priority
  video does not have. ProRes 4444 at this frame size runs a few hundred Mbps
  when frames carry real content, so the honest band for a graphic-dense
  full-length alpha layer is **multiple GB**.

**The fix is to stop making one long layer and start making one short clip per
graphic shot**, opaque, delivered through the motion-clip path as that shot's
picture. Cost then scales with *graphic seconds*:

| 10-min video, 20% graphic | Remotion cost |
| --- | --- |
| full-length alpha layer (today's shape) | 18,000 frames → **~14 min** |
| per-shot opaque clips | 3,600 frames → **~2.8 min**, and cached per shot |

**Five times cheaper, and cacheable** — the byte-determinism above is what makes
content-hash caching of those clips sound.

**One free result:** 16:9 in this codebase is **1280×720** (`styles.py`
`render_width`/`render_height`), which is the *same pixel count* as the 720×1280
reel (921,600). Every cost number above transfers to long-form landscape
unchanged. Aspect needs no re-measurement.

**And the demand is real.** Census over all 45 projects that have a timeline
(1615 shots), 2026-09-11: **124 shots (7.7%) have a data-shaped picture prompt**,
and they cluster hard on exactly the content this channel makes —
*The GDP Dilemma* **21 of 62 shots**, *the gdp game* 16 of 57, *The home loan
scam* 11 of 51. On a GDP-type long-form video **roughly a third of the shots
already want a chart**, and today every one of them is answered by a stock photo
search or an image model. See §4 for the honest limits of that number and the
rigorous version.

| # | Task | Effort | Depends on |
| --- | --- | --- | --- |
| **G0** | ⛔ GATE — the graphic census, done properly | 0.5 d | — |
| **G1** | `GraphicSpec` on the timeline — the data contract | 1–1.5 d | G0 |
| **G2** | The graphic planner stage + K8's five guardrails in code | 2–3 d | G1 |
| **G3** | Third `PicturePath` value; asset planner buys nothing for a graphic shot | 1 d | G1 |
| **G4** | Remotion `Graphic` composition — the four chart forms | 3–4 d | G1 |
| **G5** | Per-shot clip producer, content-hash cache, fingerprint | 2–2.5 d | G4 |
| **G6** | The 16:9 long-form graphic-priority style band + prompt fragment | 1–1.5 d | G2, G5 |
| **G7** | Explainer diagrams — a separate, bounded grammar | 3–4 d | G4, G5 |
| **G8** | Chapter/act awareness so graphics land at structural beats | 1 d | G6 |
| **G9** | Review surface for inferred values (K8 guardrail 4) | 1.5–2 d | G2 |

**~16.5–21.5 days, and G0 can kill it for half a day.** Everything from G4 on
ends in a human watching output; none of that compresses.

---

## 0. Navigation — read before writing any code

### 0.1 Pickup protocol

Same rules as `output_quality_pass.md` §0.1, `animated_explainer.md` §0.1 and
`long_form_direction.md` §0.1, restated because this plan will be picked up cold:

1. **G0 is the gate for everything else.** It is a measurement. If it comes back
   below its own threshold, **close this plan** in §7 and stop. That is a
   success.
2. **Do exactly one lettered task.** Do not bundle. Do not "while I was in
   there."
3. **Write a §7 log entry before finishing:** dated heading, *Scope executed*,
   *Changes* with `file:line`, *Measured* (real numbers, never "looks right"),
   *Verification* (the exact command), *Effects / notes for the reviewer*,
   *What is NOT done*.
4. **If a finding contradicts this plan, change the plan text in the same
   commit** and say so in the log.
5. **Never mark a visual task done on unit tests alone.** G4, G6 and G7 end in a
   human watching a render. Say *"built, awaiting human pass"* and stop.
6. **Read §1 before touching the renderer.** Those invariants are inherited and
   already paid for in bugs.

### 0.2 ⚠ START HERE

**G0.** It is two queries and a classifier over data already in Postgres. It
prices every task below it.

### 0.3 Standing constraints in this repo

- Do **not** set `PYTEST_TRUNCATE_DB=1` and do **not** run `make test`. Both wipe
  a SHARED Postgres holding real projects. Plain `pytest tests/unit` is safe.
- Never run seed with `--force`.
- Never delete anything under `backend/storage/**/overlays/` — real cached
  artifacts.
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

- **D1 narration is the master clock.** A graphic never sets a duration. It is
  fitted to the shot the narration produced.
- **I2 immutable decision / I5 rendering is a pure function.** A graphic's
  content is decided at plan time, recorded in the versioned timeline, and the
  renderer is a pure function of it. No planner call at render time.
- **R2 fingerprint keys are present unconditionally**, `None` when moot. Every
  new render input follows this shape. **This is the single most repeated trap in
  this codebase** — the palette, the caption highlight size, the K17 placement
  table and the K18 chunk budget all shipped invisible before their key was
  added. A graphic clip that is not hashed will cache-hit and never appear.
- **RV2 / R1 resolve a style knob once in the render caller and pass it down.**
  Never read a style band at a use site. `app/renderer/captions.py`'s "free of
  I/O and config reads" docstring is the standard.
- **Fragment index, never seconds.** Anchoring is `anchor_fragment`; seconds are
  resolved later from real alignment. A model cannot predict a duration that does
  not exist yet.
- **Enforce in code after the planner returns, never by asking the prompt
  nicely.** K3's enforcement pass is the pattern; `resolve_picture_path`'s
  docstring states the principle.
- **Python owns geometry, the TSX consumes props.** The K4/K5 band was once
  hand-mirrored in both and diverged; the band is now Python-authoritative and
  passed in props. A chart's box, safe area and label budget are Python's.

---

## 2. The gap, concretely — five missing pieces

### 2.1 `EmphasisValue` cannot describe a chart

```python
class EmphasisValue(BaseModel):
    value: int
    unit: str | None = None
    cited_fragment: int = Field(ge=1)
```

Three blockers, all real:

- **No label.** A bar chart needs `2019`, `2024`, `Imports` per value. There is
  nowhere to put one. This field set describes a *counter* — one number counting
  up — which is exactly what it was built for (K11).
- **`value: int` only.** Percentages and ratios with a decimal cannot be
  represented. K3's own test set normalises `2.5 lakh` to `250_000`, which works
  for counts and not for `27.4%`.
- **No form, no axis, no series.** Nothing says "these five values are one line
  over time" versus "these three are parts of a whole".

`EmphasisValue` should be left exactly as it is — `counter` depends on it — and a
new `GraphicSpec` added beside it (G1).

### 2.2 The third `PicturePath` value does not exist

`app/script/styles.py` has `RETRIEVAL_LADDER` and `GENERATION_ONLY`. The K8
design already names the third — *"a composed shot whose picture IS the graphic,
on a designed ground, with no asset resolved for it"* — precisely so the asset
planner stops buying an image nobody will see. It was never added (G3).

### 2.3 Remotion is an overlay producer, not a picture producer

`compositor.py::_invoke_remotion` renders **one** composition (`COMPOSITION_ID =
"Emphasis"`) to **one** full-length alpha `.mov`, composited by ffmpeg with
`overlay=0:0:format=auto`. There is no path that renders a short opaque clip for
a single shot. That is G4+G5, and §Verdict has the numbers for why it matters.

### 2.4 `picture_is_graphic` only ever says "no"

K12 shipped the signal and it is consumed in exactly three places — all
suppressive: `emphasis_rules.py:365` (don't put a cue on a graphic),
`pivot.py:107` (skip), and the emphasis prompt (context). **Nothing draws.** The
flag is a working input waiting for a consumer.

### 2.5 Long-form has no direction system

`long_form_direction.md`'s verdict: the two 16:9 styles are *planner-identical*,
differing only in colour grade and music gain, and the Shot Planner is **never
told which act it is in** — the act `title` is generated then discarded before
the Timeline is written. A chart belongs at a structural beat ("here is the
claim, here is the evidence"), and today nothing knows where those are (G8).

---

## 3. Decisions taken in this plan

**G-D1 — Per-shot opaque clips, not a longer alpha layer.** Decided on the
§Verdict measurements. A graphic shot's picture is a Remotion-rendered clip,
sized to the shot, delivered through the existing motion-clip path. The existing
full-length alpha overlay stays exactly as it is for kinetic text; the two
mechanisms coexist and must not be merged.

*Rejected:* extending the alpha layer. It costs 5× more, grows without bound in
file size, and cannot be cached per shot — one changed number reburns ten
minutes.

**G-D2 — Charts are opaque, on a designed ground.** No transparency, no
compositing over a photo. K8 already measured the failure of a data device over a
busy plate (a counter landed on an AI infographic and both became unreadable),
and its documented fallback is *"escalate to full-frame on a designed ground"*.
For long form that fallback becomes the default: the graphic IS the shot.

**G-D3 — Four permitted forms, and a ban.** Picked with the `dataviz` form
heuristic against K8's label budget (~4 labels, "prefer fewer, larger values"):

| Job the narration is doing | Form | Colour job |
| --- | --- | --- |
| compare magnitudes | **column** (vertical bars) | sequential, one hue |
| trend over time | **line** (single series; area if one) | sequential |
| part-to-whole | **stacked bar, horizontal** | categorical, ≤4 |
| before → after | **dumbbell** | one hue, two shades |

**Banned: pie and donut.** The AI infographic this whole thread started from
shipped a market-share donut with fabricated slices; a two-slice pie is a meter,
and a many-slice pie is unreadable at 1280×720 in three seconds. A single ratio
against a limit uses the existing `meter` device, not a chart.

**Not a chart at all:** one value, even with a trend, is the existing `counter`
device over the picture. This is K8's own corollary (*"`counter` and `chart` are
genuinely different devices, not variations"*) and the `dataviz` "is it even a
chart" rule agreeing with it. **A one-bar bar chart is a bug.**

**G-D4 — Chart colour rules, inherited not invented.** The project palette is
already authored once per project and recorded on the timeline
(`EmphasisPalette`, accent + pivotGround — K5/K8 decision 7, scenario A). A
graphic uses that accent as its sequential hue and must not introduce a second
palette. Binding rules, from `dataviz`:

- **One axis. Never a dual-axis chart.** Two measures of different scale → two
  shots, or index both to a common base.
- **Sequential is the default** (one hue, more-is-darker). Categorical only when
  the series *are* the subject, capped at 4 with direct labels mandatory at 4.
- **Colour follows the entity, never its rank.**
- **Text wears text tokens, never the series colour.** Labels and values stay in
  ink; the coloured mark beside them carries identity.
- **Emphasis over categorical** when one value is the point: accent that one,
  grey the rest. This is the most useful form for narration-driven charts,
  because the narration always has exactly one number it is saying right now.
- Run `scripts/validate_palette.js` from the `dataviz` skill against the **dark**
  video ground before shipping any categorical set. Do not eyeball CVD.

**Deliberately dropped from the `dataviz` procedure, because this is video:** the
hover/tooltip layer, filter controls, and the table view. There is no pointer.
Their accessibility role is carried instead by mandatory direct labels and by the
narration saying the number aloud.

**G-D5 — Inferred values render as outline + `est.` on the mark.** K8 guardrail 2
is a rendering requirement, not a data field, and it is this plan's job to
implement it: stated values solid, inferred values outlined or hatched at reduced
opacity with a visible `est.` on or beside the mark — **never a footnote at
12px**, which is the exact behaviour of the AI infographic being replaced.

**G-D6 — Explainer diagrams are a separate task with a separate grammar (G7).**
A chart plots numbers; a process diagram (`COAL → GASIFICATION → SYNTHESIS →
LIQUID FUEL`, from `remotion_integration.md` §9) has no numbers and needs nodes,
arrows, labels and highlight states. Sharing the clip producer (G5) is right;
sharing the data contract is not. And **neither is `animated_explainer.md`'s
unit** — that plan's atomic unit is *one diagram that persists and evolves across
many shots*, which needs shot-spanning state this plan does not build. G7 is one
diagram per shot. If the persistent-diagram format is wanted, that is
`animated_explainer.md` and it has its own gate.

---

## 4. ⛔ G0 — GATE: the graphic census, done properly

**Do this first, alone. It prices everything else and it can close the plan.**

A lenient pre-measurement is already in hand (2026-09-11, §Verdict): 124 of 1615
shots (7.7%) have a data-shaped picture prompt, concentrated at ~34% on GDP-type
projects. **Be honest about what that number is:** the classifier is a keyword
regex (`chart|graph|infographic|diagram|percent|%|crore|lakh|billion|million|
trend|share|growth|rate`). It over-counts — "crore" in a prompt does not make the
shot a chart — and `picture_is_graphic` is only 0.4% because K12 shipped
2026-09-09 and almost nothing has been re-planned since. The pre-measurement is
enough to justify G0; it is **not** enough to justify G1.

G0 answers two questions with real rigour:

**G0.1 — How many shots are genuinely chart-shaped?** Sample ~80 shots at random
from the 124, read the picture prompt and the narration fragment it covers, and
classify each into: *column / line / part-to-whole / before-after / process
diagram / not a graphic at all*. Hand-classified, recorded in the log as a table.
This also tells you whether G-D3's four forms are the right four — if 40% land in
a fifth bucket, change G-D3 before building it.

**G0.2 — Can the data actually be extracted?** For each shot classified as a
chart, check whether the narration fragments it spans contain **at least one
citable value** under the matcher K3 already ships
(`emphasis_rules._fragment_contains_value`). This is the K8 anchor guardrail
applied in advance. A chart whose anchor cannot be cited is a chart this pipeline
is not allowed to draw.

**Thresholds, stated before the measurement so the result cannot be rationalised:**

- **≥15% of shots on data-heavy long-form projects are genuinely chart-shaped
  AND ≥70% of those have a citable anchor** → proceed to G1.
- **5–15%, or anchors below 70%** → build **G7 (diagrams) first and charts
  later**. A process diagram needs no citable number, so it is unblocked by a
  weak G0.2 while charts are not.
- **<5% chart-shaped** → **close this plan.** Write that in §7. The honest
  outcome is that this channel's long-form wants archival pictures with good
  camera moves, which is `long_form_direction.md`'s territory, not this one.

**Cost:** no API spend, no render. Two queries plus human reading. Half a day.
Run every census query **before** a pytest session, never after — `conftest.py`'s
autouse `clean_database` truncates the shared dev Postgres (the hazard
`animated_explainer.md` §11 records).

---

## 5. The build, cheapest first

### G1 — `GraphicSpec` on the timeline

The data contract. A new model beside `EmphasisValue`, not a change to it.

```python
class GraphicDatum(BaseModel):
    label: str                      # "2019", "Imports" — required, this is the gap
    value: float                    # float, not int — percentages exist
    cited_fragment: int | None      # None == inferred (K8 guardrail 1)

class GraphicSpec(BaseModel):
    form: Literal["column", "line", "stacked_bar", "dumbbell"]   # G-D3
    title: str | None               # short; the narration carries the sentence
    unit: str | None                # "%", "crore", "cars"
    data: list[GraphicDatum]        # label budget enforced in code, not prompt
    trend: Literal["rising", "falling", "flat"] | None  # for G2's monotonicity check
    emphasis_label: str | None      # which datum the narration is saying NOW
```

Lands on `Shot` (one graphic per shot, G-D6), versioned like any planner
decision, so K8 guardrail 4 (reviewable) is satisfied by construction.

Deliberately absent: **no `source` field, at any point, ever.** K8 guardrail 5 is
the one line the design holds absolutely. Not having the field is stronger than
validating it.

### G2 — The graphic planner stage, and the guardrails in code

Author `GraphicSpec` in a planner pass, then enforce K8's guardrails **after it
returns**, in code, the way `emphasis_rules.py` does:

1. **Anchor citation** — at least one datum has `cited_fragment`, and
   `_fragment_contains_value` confirms that fragment states that number. Reuse
   the existing matcher; do not write a second one. A spec with no citable anchor
   is **dropped**, and logged as such.
2. **Plausibility** — inferred data within one order of magnitude of the anchor,
   and monotonic when `trend` is set. A 2021 figure above the 2025 anchor in a
   growth story is a bug.
3. **Label budget** — `len(data) <= 4` for categorical forms; more labels than
   the budget means it is the wrong graphic. Enforced here, not requested in the
   prompt.
4. **Mutual exclusion** — a graphic shot carries no `text_card` and no emphasis
   cue. K3 already suppresses cues on `picture_is_graphic`; this closes the other
   direction.

⚠ **Two traps this stage will hit, both already paid for once:**

- **Structured-output strict mode drops a defaulted field from `required`**, so
  the model is never asked for it and it silently stays `False`/empty forever.
  K12 hit exactly this. Every field the planner must author is **required, no
  default**.
- **The value fix in `numerals.py` runs at PLAN time.** As of 2026-09-11 the
  romaniser's compound-tier bug (K19/K19.1) is fixed in code but the merged text
  is baked into stored timelines — a re-render does not pick it up. Same will be
  true of `GraphicSpec`: it is authored at plan time, so changing G2 requires a
  re-plan, not a re-render. Say so in the log.

### G3 — Third `PicturePath` value

Add the composed/drawn value; make `resolve_picture_path` return it for a graphic
shot under the new style; make the asset planner resolve **no asset** for those
shots. Enforced in code after the Asset Planner returns, never by prompting it to
skip. Saves the image spend on every chart shot, which is a real budget line at
~34% of a 10-minute video.

### G4 — The Remotion `Graphic` composition

One new composition, props-driven, opaque, rendering G-D3's four forms under
G-D4's colour rules and G-D5's inferred treatment. Props carry canvas, palette,
the `GraphicSpec`, and the **box/safe-area geometry computed in Python** (§1).

Port the animation vocabulary that already works rather than inventing: the
`Counter.tsx` value roll with `Intl.NumberFormat("en-IN")` grouping, the
`Stamp.tsx` spring overshoot and per-grapheme-cluster stagger (`Intl.Segmenter`,
**never** `split("")`). Devanagari labels are reachable — a Hindi axis label is
ordinary here — so the cluster rule and the variable-font `wght` descriptor
(K6: the file named `-Regular.ttf` IS the variable font) both apply.

Ends in a human watching four stills and one render. Not done on unit tests.

### G5 — The per-shot clip producer, cache, and fingerprint

The architectural core. Mirror `render_or_reuse_emphasis_overlay`'s shape:

- Content-hash the resolved props → `storage/{project}/graphics/{hash}.mov`.
  Byte-determinism is **verified on this machine** (§Verdict), so a hash hit can
  safely skip the render. Cross-machine and cross-Remotion-version determinism is
  **not** verified — key the cache on the compositor's `package-lock.json` hash
  too, or a version bump silently serves stale clips.
- Opaque codec, not ProRes 4444. There is no alpha to preserve, and an opaque
  intermediate is a fraction of the size. Confirm it survives the motion-clip
  probe as `MediaKind.MOTION`.
- **The fingerprint key is mandatory and unconditional** (R2). `graphic_specs_hash`
  present always, `None` when the style resolves no graphics. Prove it the way
  K18 was proved: render, change one datum, re-render, show a cache **MISS**.
  This trap has now bitten four times in this codebase; do not make it five.
- Clips are produced **before** the ffmpeg composite, concurrently, through
  `bounded_gather` — Track C already owns the concurrency primitive and the one
  ffmpeg semaphore. Do not add a second pool.

### G6 — The long-form graphic-priority style band

A new entry in `STYLE_PACING_BANDS`: 1280×720, long-form pacing, the new
`PicturePath`, graphics enabled, plus a prompt fragment telling the Shot Planner
when a shot should be a graphic. Everything resolved once in the render caller
(RV2).

This is where the *style* question gets answered: `retention_fast`'s kinetic
identity is 9:16 and 90s, and its stamp/counter geometry is tuned to 720 width.
**Deriving the new style from `retention_fast` is a trap** — inherit the palette
discipline and the honesty rules, not the band geometry.

### G7 — Explainer diagrams

Nodes, arrows, labels, highlight states; one diagram per shot; a closed grammar
(`remotion_integration.md` §9 sketches the vocabulary). No numbers, therefore no
citation guardrail, therefore unblocked even if G0.2 comes back weak. Shares G5's
clip producer and G4's geometry; its own spec model, not `GraphicSpec`.

### G8 — Chapter/act awareness

From `long_form_direction.md`: persist the act `title` that is currently
generated and discarded, and tell the Shot Planner which act it is in. A chart
wants to land where a claim needs evidence, and that is a structural position.
Small change, real effect on where graphics go.

### G9 — Review surface for inferred values

K8 guardrail 4 says inferred values are reviewable before render. G1 makes them
present in the timeline; G9 makes them visible and overridable in the UI, in the
shape of the existing per-shot planner veto (A12). Until G9 lands, the guardrail
is satisfied only by reading JSON.

---

## 6. What would kill this plan — stated in advance

- **G0 returns <5% chart-shaped.** Close it. The answer is better camera moves
  over archival pictures.
- **G0.2 shows anchors are rarely citable.** Charts become undrawable under K8's
  own rules. Build G7 only; do not weaken guardrail 1 to make charts possible —
  that guardrail is the entire reason drawing charts beautifully is defensible.
- **Per-shot clips turn out not to be reusable in practice** (every chart differs,
  so the cache never hits). The cost argument survives anyway — it scales with
  graphic seconds either way — but the re-render cost of a one-number edit goes
  from seconds to minutes. Measure the hit rate in G5 and record it.
- **Remotion determinism fails across a version bump** and the cache serves stale
  clips. Mitigated in G5 by keying on the lockfile; if that proves fragile, drop
  the cache rather than ship wrong figures.
- **The user watches G4 and the charts read as corporate.** This is the real
  aesthetic risk and no measurement can pre-empt it. The reference-reel work in
  `retention_fast_kinetic_text.md` found the look by watching and cutting, not by
  specifying; expect the same here and budget a watch-and-tune pass.

---

## 7. Implementation log

*Empty. First entry should be G0 — including a close-out if it comes back under
threshold.*
