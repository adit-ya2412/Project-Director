# Illustrated Faceless — an opt-in generated format with ffmpeg-composited motion

**Status:** DESIGN, with four probes already PASSED (§1). No production code touched.
**Written 2026-09-04.** Decided the same day: **all motion is ffmpeg compositing.
No AI image-to-video.** See §2.4 for the arithmetic that forced it.

---

## Verdict up front

**A new opt-in format: every picture generated as flat editorial illustration,
characters deliberately faceless, motion produced by compositing layers in
ffmpeg rather than by an image-to-video model.**

Three things make this cheap where the neighbouring plans are expensive:

- **Faceless removes character consistency entirely.** Identity becomes
  silhouette + wardrobe + palette, expressible in plain text. No reference
  images, no LoRA, no persisted character, no hosted URLs — all of which §1.1
  measured as *working* and this format then makes unnecessary.
- **Flat art chroma-keys cleanly.** Layer separation is the hard part of
  parallax, and it is hard on photographs. It is easy on flat illustration —
  measured in §1.4.
- **Generating layers separately means never segmenting anything.** This is
  why `animated_explainer.md` A4's cost estimate is too high for this route:
  A4 assumed authoring motion over flat raster that had to be cut apart. If
  the layers were never combined, there is nothing to cut.

**Cost: ~$2 for a stills-only film, ~$4–7 with parallax, on a 61-shot script
whose own budget cap is $24.50. Motion costs nothing per shot at render time,
forever, once built.**

**This is a FORMAT, not a fifth style preset.** `animated_explainer.md` §6.5
already states the rule and it applies unchanged here. See §3.

---

## 0. Navigation

### 0.1 Pickup protocol

1. **Do exactly one lettered task.** Do not bundle.
2. **Write a §7 log entry before finishing**: dated heading, *Scope executed*,
   *Changes* with `file:line`, *Measured* (real numbers, never "looks right"),
   *Verification* (the exact command), *Effects / notes*, *What is NOT done*.
3. **Never mark a visual task done on unit tests alone.** Every item in §2 ends
   in a human watching something. Say *"built, awaiting human pass"* and stop.
4. **If a finding contradicts this plan, change the plan text in the same
   commit** and say so in the log.
5. **Read §1 before writing any code.** Four probes already ran. Do not re-run
   them; they cost real money and the answers are recorded.
6. **Read §4 before touching the renderer or the schema.**

### 0.2 ⚠ START HERE

**F1 (§2.1).** The style itself, stills only, no motion. It is the only slice
that answers the question none of the probes could: *does a whole 61-shot film
in one illustrated world actually hold together, and does anyone want to watch
it?* Ten images passing is encouraging, not proof. Everything after F1 is
wasted if F1's human pass fails.

---

## 1. Origin — four probes, all PASSED, all paid for

Run 2026-09-04 via `backend/scripts/character_consistency_probe.py` and
`backend/scripts/parallax_probe.py`. Total spend **$1.20 / 30 images / 3 clips**.
Artefacts in `tmp/character-probe/` and `tmp/parallax-probe/`.

Neither script touches production code, the database, or a Timeline.
`FalQueueClient.submit` is already generic over model id and arguments, which is
why no provider change was needed to probe a model production does not use.

### 1.1 Photoreal character consistency WORKS — and is not needed

`fal-ai/bytedance/seedream/v4/edit` with `image_urls` reference plates:

- **Context changes (school / gym / wedding / casino / desk): 5 of 5 held.**
  Forehead scar, cheek moles, ear set, narrow jaw, and the hairline cowlick all
  carried across costume and location changes.
- **Age morph: holds to ~30, degrades at ~55.** At 55 the anchors survive but
  the face reads as a believable older relative, not the same man.
- **Baseline (prompt + fixed seed, no reference — what production can do
  today): FAILS.** The two baseline images are the same *type* of person but
  neither the hero nor each other, and the cowlick — the most distinctive
  marker in the description — is absent from both. This confirms
  `_project_seed`'s own docstring: a fixed seed buys *stylistic* consistency,
  never identity.

**Recorded so nobody re-derives it. This format does not use any of it** —
faceless characters have no face to keep consistent.

### 1.2 Cartoon styles keep silhouette, discard face structure

Four illustrated looks, restyled from the photoreal hero plates:

| look | identity retained |
|---|---|
| storybook gouache | **best** — face structure, moles, ear set, skin tone, all correct |
| 2D anime cel | cowlick, eyebrows, one mole; face replaced by the anime template |
| 3D stylised | cowlick and scar; reads as a generic animated-feature character |
| flat vector | cowlick only; identity gone |

**Systematic finding: skin tone drifted lighter, monotonically with abstraction
level.** Storybook kept it, flat vector lost it entirely. This is a consistent
directional bias, not four random misses.

**⚠ Binding consequence: ethnicity must be re-asserted in every prompt of this
format, never inherited from a reference.** Confirmed twice — the cartoon pass
and again in §1.3, where the blank-face treatment returned a white child from a
prompt that did not state otherwise.

### 1.3 Faceless illustrated characters WORK — 4 of 4 treatments

Text-to-image, **zero reference images**, one locked world token in the prompt.

| treatment | result |
|---|---|
| seen from behind | **pass** — the best frame of the set |
| solid silhouette against a window | **pass** |
| blank featureless face (no eyes/nose/mouth) | **pass** — reads as deliberate editorial illustration, not as an error |
| cropped above the chin | **pass** |

This was the treatment expected to fail: image models are heavily face-biased
and "no face" is a *negative* instruction. **All four positive framings were
respected.** Use positive framings; never rely on a negative.

**One world held across four environments** (bedroom / cram-school classroom /
factory floor / apartment towers at dusk): same palette, same paper grain, same
flat shading, same single-light logic. `animated_explainer.md` A2's kill
criterion is cleared — for a *style*, which is a far weaker demand than for a
face.

Two prompt-level drifts, both fixable, neither a model limit:
- hair came out ginger when hair colour was unstated (the palette's amber bled
  into it) — **state hair colour explicitly**;
- "on an open background" was read as "on an open **book**" — **say "plain flat
  background"**.

### 1.4 Parallax and element animation WORK, at zero per-shot render cost

Three 5-second clips at 720×1280, ffmpeg only over generated stills:

- **two-layer parallax** — background and subject at different drift rates: clean;
- **three-layer parallax** — adds a near-foreground plane: three unambiguous
  depth planes;
- **element animation** — background completely static, subject slides and fades
  in on its own. **The register Ken Burns structurally cannot reach.**

Chroma key on flat illustration is **clean** — no fringe, hard edges preserved.

### 1.5 ⚠ The key colour must be SAMPLED, never assumed

**Measured, and it failed silently first.** Asked for pure `#FF00FF`; seedream
returned **`#B43E7E`** — it harmonised the key colour into the world's own
limited palette and then laid the paper grain over it, so the plate varied ±10
per channel. A hardcoded `colorkey=0xFF00FF` matched nothing, the composite
built with exit code 0, and the "cut-out" rendered as an **opaque rectangle**.

Fix, now in `parallax_probe.py::_sample_key`: take the **median of the top
border strip** (the subject touches the bottom edge, so corners sample his
jacket; median so a stray subject pixel cannot pull the key).

**This is also the more correct design regardless of provider.** The key is
derived from the image bytes, so it is deterministic (I5) and cannot drift out
of agreement with what was delivered. It needs **no** fingerprint entry — those
bytes are already hashed via `shot_media`.

See §4.5 for the automated guard this failure mode earns.

### 1.6 House-world bake-off — four worlds x three subjects, 48c

`backend/scripts/world_probe.py`, 12 images, all succeeded. Artefacts in
`tmp/world-probe/`. Same subject wording in every row; the only variable is the
world token. Each world judged on all three subjects, because a world that
carries only two of them is a look for one kind of shot, not a house style.

| world | environment | figure | data | verdict |
|---|---|---|---|---|
| W1 flat editorial | good | good | good | versatile, least distinctive — the safe default |
| **W2 risograph** | **striking** | good | **excellent** | **selected — the punchy world** |
| W3 soft gouache | soft | **beautiful** | weak | rejected — cannot carry a graphic |
| **W4 line & wash** | good | **beautiful** | **cleanest** | **selected — the explainer world**, after the fix below |

- **W2 risograph** is the most *ownable* look — three spot colours, heavy ink
  grain, poster energy. Its data shot is the best of the four: two bars that
  read instantly and still look like the film. Its risk is register, not
  quality: it is high-energy, which fights a somber script.
- **W4 line & wash** is the best all-rounder for explainer content. Its bar
  chart is a genuine chart, and its figure is the most affecting of the four.
- **W3 gouache** is the most emotional and structurally the weakest: the washes
  bleed and the frame has no architecture, so it reads as a painting rather
  than a shot. It would be fought on every graphic beat.

### 1.7 ⚠ Prompt rule, measured twice: name the MEDIUM, never an object made of it

W4's token contained the phrase *"a technical notebook drawing"* — and the model
put a **physical notebook** into every W4 frame: the figure sits on lined
notebook paper, the bar chart is drawn on a notebook page. Earlier, in §1.3,
*"on an open background"* produced a chart drawn on an **open book**.

Twice now, a noun describing the *kind* of artwork became a physical object in
the frame. **Rule: describe the medium and technique ("ink line and wash,
translucent watercolour washes, untouched paper") and never name an artefact
that has the medium on it ("notebook drawing", "magazine spread", "printed
poster", "sketchbook page").** Remove "notebook" from W4's token before F1.

**Correction found during F1 (2026-09-04): this section's own actionable
sentence above named only W4, but W2's token (§1.6, `world_probe.py`) ends
*"...like a printed protest poster"* — the exact "printed poster" phrase
already sitting in this rule's own banned-example list two paragraphs up.
Missed when this section was first written; W2 is F1's SELECTED world, so
this was not a hypothetical gap. Fixed in F1: the trailing artefact clause
is dropped from the token carried into `shot_planner_styles/
illustrated_risograph_vertical.md` / `_horizontal.md` (see P-IF-F1 below for
the corrected token and why "poster-like shapes" was also generalised to
"graphic shapes" for the same reason). `world_probe.py` itself is left
unedited — it is the historical record of what was actually tested, not
production code.**

This belongs with §1.2's ethnicity/hair-colour rule and §1.3's positive-framing
rule as one set of prompt constraints the style fragment must carry.

**Second correction, found on a real render (project `7df10f6c-e6b9-4275-
b88a-7f07d0178011`), fixed in P-IF-F1-fixes (2026-09-04): the first
correction above was itself incomplete.** It removed "poster" but left
*"…printed on off-white uncoated paper"* standing — still a physical
substrate, just without the banned noun. Shot 1's source still came back
with a visible paper border, a signature mark, and a stamp. **It did not
appear in the rendered VIDEO only because Ken Burns zooms in and crops the
edges off** — a static shot would show it. **A Ken Burns crop masking a
substrate artefact in the finished video is not evidence the token is
clean: check the source still, not the video, for this failure mode.**
Fixed by rewording paper from an object the image is "printed on" to a
surface texture woven through the image, with an explicit "not a page or
sheet the picture sits on" negation — see `illustrated_risograph.md`'s
token and its extended HTML comment for the exact wording.

---

## 2. The build, cheapest first

Each slice is independently useful and each can stop the sequence.

### F1 — The illustrated format itself, stills only ⛔ START HERE

**No motion. No layers.** One opt-in format that generates every picture.

- A new `StylePacingBand` entry with its own canvas. **Both aspects are
  required** (user, 2026-09-04): 9:16 and 16:9. Two rows, or one row plus the
  `frame_aspect` mechanism — see §4.2, and note format is frozen per project,
  so both aspects means two projects.
- A `STYLE_GRADES` entry. The illustrated palette is baked into the prompt, so
  the grade should be close to identity — do not double-grade.
- A shot-planner style fragment carrying: the locked world token, the four
  proven faceless framings (§1.3) as *positive* instructions, explicit
  ethnicity and hair colour (§1.2), and "plain flat background" for graphic
  shots (§1.3).
- **A generation-only picture path, enforced in code** (§3.2), not by asking
  the Asset Planner nicely.

**Buys:** a shippable Ji-ho film at ~$2. **Does not buy:** any motion.

**⛔ Human pass, and it gates everything below:** render the full 61-shot Ji-ho
script and watch it. Does one illustrated world hold across 61 shots, not 10?
Does it read as a film or as a deck? **If this fails, close the plan** — every
slice below adds motion to something nobody wants to watch.

### F2 — Layers in the schema, and two-layer parallax

- `Shot.layers: list[ShotLayer]`, **defaulting to empty**. Empty means today's
  behaviour exactly, on every existing style. This is the isolation mechanism
  (§3.1), not a convention to remember.
- `ShotLayer`: role (background / subject / foreground), prompt, asset_plan,
  and motion parameters. Note the schema **already** carries a two-image shape
  for `split_frame` (`prompt`/`secondary_prompt`,
  `asset_plan`/`secondary_asset_plan`) — read that first and decide whether to
  generalise it or sit beside it. Do not build a third parallel mechanism.
- A new `CameraMovement` value so the planner can *ask* for parallax. **Canon
  3.1: the renderer executes direction, it never invents motion from style
  alone.**
- `app/renderer/parallax.py`, beside `ken_burns.py`, slotting into the existing
  composition pass.
- **Layer count, roles and drift rates into `compute_render_fingerprint`** (R2).

**Human pass:** does it read as animation, or as a moving photograph?

### F3 — Three layers, and per-layer scale and placement

The tuning §1.4 left open: all layers were scaled a uniform 1.2×, so the
subject dominated the frame. Per-layer scale and offset is the difference
between "technically works" and "looks directed." Small increment on F2.

### F4 — Timed layer entry, anchored to FRAGMENTS not seconds

The first slice that needs a real design decision, and the proposal is:

**A layer's entry is expressed as a narration FRAGMENT INDEX, never a time in
seconds.**

This is `app/planners/fragments.py`'s own thesis applied one level out. That
module exists because three separate incidents came from asking a model for
character offsets, and its conclusion is quoted here because it decides this
slice:

> **Models cannot count characters reliably — that is not a prompt-quality
> problem, and it is not a post-processing problem. It is the wrong thing to
> ask for.**

Asking a planner "at what second should this element appear" is the same
mistake in new clothes: it is asking a model to predict a duration that does
not exist yet, since narration is measured *after* planning. Asking "which
fragment's words does this element land on" is a judgement a model can actually
make, and the real time then falls out of measured narration deterministically
— exactly as `narration_span` already does for shots.

**D1 is preserved by construction:** narration stays the master clock, and no
animation can stretch it.

**Human pass:** do the reveals land on the words?

### F5 — Element transforms (grow, draw, wipe)

Extends F4's schedule from *entry* to *transform*: a bar growing, an arrow
drawing itself, a highlight sweeping. This is `animated_explainer.md` A4's real
substance, and it is the slice that would let a diagram assemble itself.

**Only build this if the content demands it.** Ji-ho does not — a static
illustrated chart under a text card covers his data beats at roughly 1% of the
build cost. The dopamine-loop script (the origin of this whole thread) *does*.

---

## 3. Isolation — how this stays out of the existing styles

Every mechanism below already exists in this codebase. Nothing here is new
invention.

### 3.1 Additive defaults, not remembered protection

- **Style fragments isolate by filename.** `shot_planner_styles/<style>.md` is
  loaded by name; a fifth file is never opened by the other four.
- **New `StylePacingBand` fields default to "use the flat setting."** Resolve
  with `is not None`, **never** `or` — styles.py states this explicitly because
  `0.0` is a legitimate override.
- **`Shot.layers` defaults to empty**, and empty is today's behaviour. Existing
  styles are correct because of the default, not because someone protected them.

### 3.2 One resolver, and the ladder override lives in CODE

Write **one** function — `resolve_picture_path(style)` — and make every call
site go through it. Never read the band directly at a use site.

This is the lesson of R1, quoted from `generate_timeline.py`'s own docstring:
two validators of one invariant diverged, and a full planning run was thrown
away after the Director, Scene Planner and every Shot Planner call had already
been paid for. Its conclusion: *"a single function neither call site can bypass
is what makes that true, not just making both agree today."*

**And the generation-only routing is deterministic code, not a prompt
instruction.** Verified 2026-09-04: `app/planners/asset/planner.py::
_build_user_content` sends only the scene title and, per shot,
`intent | framing | camera | prompt` — the Asset Planner **never sees
`render_style` and never sees `creative_context.constraints`.** You could tell
it in its prompt and it would usually comply. *Usually* is the defect. Override
`fallback_chain` after the planner returns:

```
if resolve_picture_path(style) is GENERATION_ONLY:  chain = [generate_image]
```

A non-illustrated style never reaches that line, so isolation is structural
rather than diligent.

### 3.3 Regression tests that assert the others did not move

styles.py's own framing is *"every style is a behaviour four planners can
regress against."* A fifth format means asserting the existing four produce
exactly what they produced before.

### 3.4 The one leak that cannot be scoped away

Adding any field to `TimelineMetadata` changes the fingerprint payload for
**every existing timeline**: `compute_render_fingerprint` does
`timeline.model_dump(mode="json")` and excludes only the eight
`_TIMELINE_BOOKKEEPING_FIELDS`. So a new field appears in the dump with its
default, the fingerprint changes, and every project re-encodes once.

**Output is byte-identical; only the cache key moved.** `frame_aspect`,
`grade_style` and `caption_romanization_attempted` each cost exactly this.
One-time, bounded, not a behaviour change — but say so in the log so it does
not read as a bug.

---

## 4. Cautions, in the order they will bite

### 4.1 R2 is the likeliest way this ships broken
Every new field — layer roles, layer count, drift rates, entry fragments,
transform parameters, the world token — changes render bytes. Any one missing
from `compute_render_fingerprint` means the cache serves stale video and the
bug surfaces days later as *"my edit did nothing."* **Add fingerprint coverage
in the same commit as each field, never after.**

### 4.2 Both aspect ratios, and format is frozen per project
The user requires 9:16 **and** 16:9. Canvas is owned by the style
(`render_width`/`render_height` on the band), and `frame_aspect` is currently
gated to `stillness` only (`frame_aspect_error`). styles.py also states
*"format rides render_style, frozen at planning start"* — so one project yields
one aspect. Two aspects means **two projects**. The "one master, many cutdowns"
idea in `remotion_integration.md` §30 is **not built**; do not imply it is.

### 4.3 Per-shot cost now scales with layer count
1 layer = 4¢, 2 = 8¢, 3 = 12¢. A careless planner could ask for six layers on
every shot. **This needs a cap in the same shape as
`max_video_shots_per_project`** — a per-project layer budget, sub-linear in
length, resolved through one function.

### 4.4 D1 inverts under pressure
The first time a reveal looks better a beat longer, someone will want to
stretch narration to fit. **Do not.** Narration is the clock. If the animation
needs more time, the planner asks for more words, or the animation gets faster.

### 4.5 The opaque-rectangle failure must be caught automatically
§1.5 failed *silently* with exit code 0. Earn a guard from it: after keying,
assert the keyed fraction of the frame falls inside a sane band (say 15–85%).
Zero means the key matched nothing — the opaque-rectangle bug. Near-100% means
it ate the subject. Both are cheap to detect and impossible to notice by
reading logs.

### 4.6 Do not route generated illustration through the depiction gate
`animated_explainer.md` §6.3 already argues this and it holds here: `A30` /
`depiction_check` exists to catch *retrieval* handing back the wrong thing. A
generated illustration matches its prompt by construction, and §17.7 measured
that gate flipping on identical bytes 2 times in 3 on hard images. It would
reject good frames at random.

### 4.7 This format is opt-in, and that is load-bearing
Stated by the user, 2026-09-04: *"animation will not be the default, only for
videos I choose."* So `animated_explainer.md` A1's global "route composed shots
to generation" is **wrong for this plan** — scoped to this format, it is simply
"this format generates everything," which is both simpler and safer.

### 4.8 Any prompt that reasons about whether media can be FOUND needs a
generation-only carve-out — this has now happened three times
This is the general shape behind P-IF-F1-review2 and P-IF-F1-review3, both
found live rather than by inspection first: a prompt written before this
format existed silently assumes "there is a photograph/archive/broadcast
somewhere to search for or be faithful to." For a `GENERATION_ONLY` style
that assumption is not merely unhelpful, it actively misfires — it can
reject the exact scripts the format exists to serve (suitability), or emit
constraints that get checked, and can fail, against a generated illustration
after real money was already spent generating it (the Director).

- **`script_suitability/v1.md` question 3** — fixed in P-IF-F1-review2:
  asked whether real archival material plausibly exists; inverted for a
  style that never searches.
- **`director/v1.md`** — fixed in P-IF-F1-review3 (this entry): "Documentary
  default… historical photographs… archival footage" and provenance-flavoured
  `constraints` ("licensed footage", "consent is documented") — the second
  half is the more dangerous one, because it survives past planning into
  `check_generated_image_constraints`, a vision model checking those same
  words against a generated illustration post-approval, where a false
  rejection is still billed (`GeneratedClipModel` bills a rejected attempt).
- **`asset_planner/v1.md`** — checked in P-IF-F1-review3, **found, not
  fixed**: "Reuse before generate", the six-rung ladder, "archival/
  government/historical-photo sources", and "real archive search engines…
  match file titles and categories" all assume retrieval is live. For F1
  this is *not* the same class of bug as the two above — `resolve_picture_
  path`/`_force_generation_only_picture_path` (§3.2) override every
  `GENERATION_ONLY` shot's `strategy`/`fallback_chain`/`preferred_type`
  after the Asset Planner returns, regardless of what it said, and its
  `entity`/`search_queries` are simply discarded unused (never billed
  against a vision model, never gated on). The cost is reasoning spent
  asking a model to solve a search problem this format structurally never
  runs — wasted tokens, not a wrong or billed result. Worth a prompt-level
  carve-out for cleanliness whenever this file is next touched, but it is
  not a defect on the scale of the other two and was not fixed in this
  pass.
- **`scene_planner/v1.md`, `act_planner/v1.md`** — checked, clean: both are
  pure narrative-structuring prompts (fragment ranges, emotion, narrative
  purpose) with no mention of photographs, footage, archives, or sourcing.
  Nothing to carve out.

**Standing rule for the next new format:** grep every prompt file for
"archival", "footage", "photograph", "licence"/"license", "search", "source",
"consent" before shipping a second `GENERATION_ONLY` style, not after a live
run surfaces the next instance.

---

## 5. What would kill this plan

Any one of these is a legitimate close. Write it in §7 and stop.

- **F1's human pass fails** — one illustrated world does not hold across 61
  shots, or the film reads as a deck. Everything else is motion on top of
  something nobody wants.
- **Parallax reads as a gimmick at length.** Three clips passing is not 61
  shots of it. If every shot drifting reads as seasick rather than alive, the
  answer is parallax on *selected* shots, not all of them.
- **F4's fragment anchoring cannot be made to land on words.** If reveals
  consistently miss their beat after narration reconciliation, timed layers are
  not reachable on this architecture and F5 should not be attempted.
- **The layer cost curve outruns the value.** If good shots need five layers
  routinely, the per-video cost approaches the image-to-video price this plan
  exists to avoid, and the comparison should be re-run rather than assumed.

---

## 6. Questions — four decided 2026-09-04, one still open

### Q1 → `layers` sits BESIDE split-screen, with a mutual-exclusion validator

Split-screen stacks two images as **panels** (each occupies part of the frame).
Layers stack them as **planes** (each occupies the whole frame, with
transparency). Those are different compositing operations that happen to share
a data shape, so they may legitimately never converge — this is not the
duplication the R1 lesson warns about.

**Binding: validate that `layers` and `secondary_prompt` are mutually exclusive
on a shot.** No shot may ever be half in each system. Revisit convergence after
F4, when what layers actually need is known. Migrating a shipped, working
feature to serve an unproven one is the wrong order.

### Q2 → Two house worlds, per-project. Bake-off run; see §1.6

`world` is a per-project field, not a global house style — confirmed by the
bake-off, where no single world carried all three subject types well. See §1.6
for the measured comparison and the two selected.

### Q3 → "Illustrated" and "faceless" are SEPARATE per-project choices

The plan originally bundled them into one format. That was wrong: they are
orthogonal, and §1.2 measured that illustrated *faces* work well (storybook
gouache held identity precisely). Bundling discards a proven capability for no
reason.

So: two independent per-project choices — *drawn or photographic*, and *faces
or no faces*. Illustrated-with-faces becomes testable later without rebuilding
anything.

Standing read on the underlying question: faceless works when the story is
about a **system** and the character is an archetype — which Ji-ho explicitly
is ("ये कहानी सिर्फ Ji-ho की नहीं"). It will tire on personality-driven content
where an expression has to carry the emotion. And facelessness is not one
trick: back-of-head is a *framing*, blank-face is a *look*, and varying across
§1.3's four proven treatments is what stops it reading as a repeated gimmick.

### Q4 → Defer the layer editor. Do not build a timeline UI.

At two layers the existing per-shot review mostly works: show the composite,
offer "regenerate background" / "regenerate subject". Two buttons.

**New failure mode to handle whenever it is built:** regenerating ONE layer
leaves the others, so a fresh background with a different light direction
against the old subject yields an incoherent composite. Nothing in the current
review has an analogue for this. It must either regenerate the set or warn.

### Q5 → 16:9 and 9:16 are DIFFERENT EDITS, exactly as the other styles are

Not one film reframed. Two reasons:

1. For a **layered** format, reframing buys nothing on the picture side, which
   is the entire cost — layers are generated to fit a canvas, so a 9:16
   background is not a crop of a 16:9 one. Both get generated regardless.
2. Vertical wants different direction: tighter framing, fewer elements per
   frame, subject larger. Horizontal wants room to establish. Treating one as a
   crop yields a bad version of both.

At $2–7 a film, making two is not the expensive part.

**⚠ One thing to check before F1 if both aspects are a standing requirement:**
whether the two can at least share NARRATION. It is cached by content hash, but
`narration_speed` rides the style — so two styles with different speeds hash
differently and each pay for TTS. Matching the speed across the two rows would
let them share the audio. Unverified; do not assume either way.

**⚠ 2026-09-04 addendum, F1 review follow-up:** `illustrated_risograph` was
collapsed from two `STYLE_PACING_BANDS`/`STYLE_GRADES` rows to one plus
`frame_aspect` (§7's follow-up log entry below) — the same mechanism
`stillness` already uses for its own other canvas. **This does not contradict
the verdict above.** Format still rides `render_style`, is still frozen at
planning start, and a project still ends up at exactly one canvas — nothing
is reframed at render time, and both canvases are still fully, independently
generated (reason 1 above is untouched: this format has no layers yet, and
even once it does, `frame_aspect` only selects which canvas the Shot Planner
and generation pipeline target, not a crop of an already-generated image).
What changed is only *how many registry rows* express "which style, which
canvas" — one row with an opt-in, instead of two rows that duplicated
everything except canvas and one framing bullet. "Two aspects means two
projects" remains true: a `stillness` project and an `illustrated_risograph`
project each still pick one canvas at creation and keep it. A later reader
should not read the collapse as this style now doing "one master, many
cutdowns" (§4.2) — it still isn't built.

### Still open

**Does the review UI eventually need a layer surface?** Q4 defers it, but does
not answer it. F3 is the earliest point at which there is enough to judge.

---

## 7. Implementation log

### P-IF-F1 — The illustrated format itself, code and prompt (2026-09-04)

**Scope executed:** exactly F1's §2.1 scope - the registry entries, grade,
style fragments, and the code-enforced generation-only picture path. Two
style rows (`illustrated_risograph_vertical` 720×1280, `illustrated_
risograph_horizontal` 1280×720), both `picture_path=GENERATION_ONLY`
(§3.2), both at the identity grade (§2.4's "do not double-grade"), both
carrying the corrected W2 world token, the four positive faceless
framings (§1.3), the ethnicity/hair-colour rule (§1.2), and "plain flat
background" (§1.3) in their Shot Planner fragments.

**NOT started, explicitly:** no render was produced and no human watched
anything - F1's own §2.1 gate ("Human pass, and it gates everything
below") is entirely outstanding; this entry is code + prompt + unit
tests only. `Shot.layers`, parallax, `CameraMovement` additions, and
`app/renderer/parallax.py` (F2+) were not touched. `split_frame`,
`secondary_prompt`, and `secondary_asset_plan` were not touched in code
(the new fragments *discourage* `split_frame` in prose, which is not an
enforcement). `text_card_min_shot_gap` and every other global `Settings`
value are untouched. `creative_context.constraints` was not threaded
into the Asset Planner. The existing four styles' bands, grades, and
fragments were not modified (verified below, not merely asserted).

**Changes:**
- `backend/app/script/styles.py:29` - new `PicturePath` StrEnum
  (`RETRIEVAL_LADDER` / `GENERATION_ONLY`).
- `backend/app/script/styles.py:153` - new `StylePacingBand.picture_path`
  field, default `PicturePath.RETRIEVAL_LADDER` (additive default, §3.1).
- `backend/app/script/styles.py:325` /`:333` - the two new
  `STYLE_PACING_BANDS` entries (`illustrated_risograph_vertical`,
  `illustrated_risograph_horizontal`). Neither overrides pacing/
  narration-speed/music-gain/whoosh - none of §1's probes measured a
  difference, so both are identical to `documentary_archival`'s inert
  defaults except canvas and `picture_path`.
- `backend/app/script/styles.py:391` - `resolve_picture_path(style)`,
  the one resolver every call site reads through (R1 shape, same as
  `resolve_sfx_whoosh_enabled`).
- `backend/app/renderer/grading.py:83-84` - `STYLE_GRADES` entries for
  both new styles at exact identity (`1.0/1.0/0.0`).
- `backend/app/prompts/shot_planner_styles/illustrated_risograph_
  vertical.md`, `..._horizontal.md` (new files) - the style fragments:
  corrected world token + `<!-- -->` comment recording the §1.7
  correction (see the §1.7 plan edit below), the four faceless framings,
  explicit ethnicity/hair-colour instruction, "plain flat background"
  rule, one orientation-specific framing clause each, and a
  `split_frame`-discouragement clause (prose only, not enforced in code
  - see "NOT started" above).
- `backend/app/workflow/steps/generate_timeline.py:51` -
  `_force_generation_only_picture_path(scenes)`, the code-level
  enforcement: overrides every shot's primary `asset_plan.strategy` to
  `GENERATE_IMAGE`, `fallback_chain` to `[GENERATE_IMAGE]`, and
  `preferred_type` to `IMAGE` (the last one is what actually guarantees
  "stills only" for F1 - `resolve_assets.py`'s real generation path
  branches on `preferred_type`, not `strategy`). `secondary_asset_plan`
  is left untouched, per the DO-NOT list.
- `backend/app/workflow/steps/generate_timeline.py:346-354` - the call
  site: `if resolve_picture_path(timeline.metadata.render_style) is
  PicturePath.GENERATION_ONLY:` runs
  `_force_generation_only_picture_path` immediately after
  `AssetPlanner(...).plan(...)` returns and before `_apply_assets`
  persists the scenes - the seam §3.2 specified.
- `docs/plans/illustrated_faceless.md:206-215` (this file) - plan
  correction, see "Effects / notes" below.

**Test files (new):**
- `backend/tests/unit/script/test_styles.py` (extended) - band/resolver
  tests, plus a byte-for-byte regression pin of all four pre-F1 bands.
- `backend/tests/unit/renderer/test_grading.py` (extended) - identity-
  grade tests, plus a byte-for-byte regression pin of all four pre-F1
  grades.
- `backend/tests/unit/planners/test_illustrated_risograph_fragment.py`
  (new) - fragment-loading tests for all three measured prompt rules,
  the artefact-noun-removal + explanatory-comment checks, and a
  regression guard that the four pre-existing styles' fragment
  resolution is unaffected.
- `backend/tests/unit/workflow/test_generation_only_picture_path.py`
  (new) - pure-function tests for the override (retrieval-first plans,
  video-preferred plans, multi-scene, no-asset-plan defensive case,
  `secondary_asset_plan` left alone, ladder-legality round-trip through
  pydantic), plus a source-inspection test proving the override is
  actually wired into `_run_real` in the right order.

**Measured:**
- Resolved canvas: `illustrated_risograph_vertical` -> 720×1280 (9:16);
  `illustrated_risograph_horizontal` -> 1280×720 (16:9). Both confirmed
  via `resolve_render_format`, not merely asserted from the band's own
  fields.
- Resolved grade for both: `StyleGrade(contrast=1.0, saturation=1.0,
  brightness=0.0)`; `grade_filter_fragment(style, "0:v", "graded")` ->
  `None` for both (the intended "no grade, no cost" outcome).
- `resolve_picture_path`: `GENERATION_ONLY` for both new styles;
  `RETRIEVAL_LADDER` for all four pre-F1 styles, for `None`, and for an
  unrecognised name.
- `resolve_constraint_bundle(style) == resolve_constraint_bundle(None)`
  for both new styles (True, confirmed) - i.e. pacing is exactly
  `documentary_archival`'s inert baseline, as intended.
- Registry now holds 6 styles total (was 4):
  `['archival_montage', 'documentary_archival',
  'illustrated_risograph_horizontal', 'illustrated_risograph_vertical',
  'retention_fast', 'stillness']`.
- Test counts: 64 passed across the four new/extended F1 test files
  (`test_styles.py`, `test_grading.py`,
  `test_generation_only_picture_path.py`,
  `test_illustrated_risograph_fragment.py`); 17 passed across three
  untouched-content regression files re-run to prove no collateral
  break (`test_generate_timeline_style_bounds.py`,
  `test_shot_text_cards.py`, `test_styled_prompt.py`) - 81 total, 0
  failed.
- `ruff check` on every touched/created Python file: clean (one
  pre-existing `B905` finding at `test_styles.py:177`, outside this
  diff - confirmed via `git diff` that line is untouched by this work).
- `mypy` on the three touched production files: 0 new errors (two
  pre-existing errors remain, both in files this work did not touch:
  `app/planners/shot/planner.py:822`, `app/providers/
  openai_provider.py:85`).

**Verification (exact commands, run from repo root unless noted):**
```
.venv/Scripts/python.exe -m black backend/app/script/styles.py backend/app/renderer/grading.py backend/app/workflow/steps/generate_timeline.py
.venv/Scripts/python.exe -m ruff check backend/app/script/styles.py backend/app/renderer/grading.py backend/app/workflow/steps/generate_timeline.py backend/tests/unit/workflow/test_generation_only_picture_path.py backend/tests/unit/planners/test_illustrated_risograph_fragment.py backend/tests/unit/script/test_styles.py backend/tests/unit/renderer/test_grading.py
  -> All checks passed! (except the pre-existing B905 at test_styles.py:177, not in this diff)
.venv/Scripts/python.exe -m mypy backend/app/script/styles.py backend/app/renderer/grading.py backend/app/workflow/steps/generate_timeline.py
  -> Found 2 errors in 2 files (both pre-existing, in files not touched here)
```
From `backend/`:
```
../.venv/Scripts/python.exe -m pytest tests/unit/script/test_styles.py tests/unit/renderer/test_grading.py tests/unit/workflow/test_generation_only_picture_path.py tests/unit/planners/test_illustrated_risograph_fragment.py -q
  -> 64 passed in 2.37s
../.venv/Scripts/python.exe -m pytest tests/unit/workflow/test_generate_timeline_style_bounds.py tests/unit/planners/test_shot_text_cards.py tests/unit/workflow/test_styled_prompt.py -q
  -> 17 passed in 2.81s
```
No DB-backed test was run (⚠ DATABASE HAZARD honoured - the shared
Postgres was never touched by this pass). `--noconftest` was never used.

**Effects / notes for the reviewer:**
- **Plan correction made in this pass (§1.7, docs/plans/illustrated_
  faceless.md:206-215):** §1.7's own actionable sentence said "Remove
  'notebook' from W4's token before F1" but never flagged that W2's
  token - the world F1 actually selected - ends "...like a printed
  protest poster", the exact "printed poster" phrase already sitting in
  that same section's banned-example list. A plan that states a rule and
  then doesn't apply it to the world it selected is worse than not
  stating the rule; fixed inline with a dated correction note rather
  than silently editing history.
- **World token, as shipped:** "Bold risograph print illustration: only
  three spot colours - deep teal, fluorescent orange and black - printed
  on off-white uncoated paper. Heavy visible ink grain, coarse halftone
  dot texture, deliberate slight misregistration where colours overlap,
  high contrast, simplified graphic shapes. Bold, graphic and urgent in
  feeling." Two changes from the bake-off token: the trailing "...like a
  printed protest poster" clause is gone (§1.7), and "simplified
  poster-like shapes" became "simplified graphic shapes" - "poster-like"
  was judged close enough to the same artefact-noun failure mode
  (describing the SHAPES via the same banned noun) to be worth
  generalising too, even though only the trailing clause was strictly
  named in §1.7's own example. This is a judgement call the plan did not
  make explicitly; flagging it here rather than treating it as obviously
  correct.
- **Why `preferred_type` is forced, not just `strategy`/`fallback_chain`:**
  the plan's own §3.2 pseudocode only mentions overriding
  `fallback_chain`. Reading `resolve_assets.py` (the real generation
  path) showed `is_video = asset_plan.preferred_type ==
  PreferredMediaType.VIDEO` is what actually selects video vs. image
  generation, independent of `strategy`. Forcing only `fallback_chain`
  would have left a shot whose camera movement made the Asset Planner
  pick `preferred_type=video` still generating a video, silently
  breaking F1's "stills only" requirement. This is the one place this
  implementation goes beyond the plan's literal pseudocode, and it does
  so because the plan's own §3.2 said to "find the right seam yourself
  and justify it in the log."
- **Why the fragments discourage `split_frame` in prose only:** the
  DO-NOT list forbids touching `split_frame`/`secondary_asset_plan` in
  code. If a split_frame shot slips through anyway despite the prompt
  instruction, its bottom panel keeps whatever the Asset Planner
  produced (possibly retrieval-first) while the top panel is forced
  generation-only - a real, if unlikely, gap. Flagged in both the code
  docstring (`generate_timeline.py:78-84`) and a dedicated test
  (`test_secondary_asset_plan_is_left_untouched`), not hidden.
- `illustrated_risograph_horizontal.md` and `_vertical.md` are
  near-duplicate files (same world token, same faceless/ethnicity/
  background rules, differing only in the orientation clause) rather
  than one shared fragment - `load_style_fragment` resolves by exact
  filename per style name, and the codebase has no cross-style-name
  fragment-sharing mechanism to fit into instead. Noted as duplication,
  not hidden.
- Registering these two styles in `STYLE_PACING_BANDS` makes them
  immediately selectable via the existing `POST /projects` and
  `POST /{id}/style` endpoints (`app/api/projects.py` validates
  dynamically against `STYLE_PACING_BANDS`, confirmed by reading it) -
  no API change was needed or made.
- §3.4's fingerprint leak applies here exactly as documented for
  `frame_aspect`/`grade_style`: no `TimelineMetadata` field was added by
  this slice, so this specific leak does not recur for F1 - noted for
  completeness, not because it fired.

**What is NOT done:**
- The human pass: rendering the full 61-shot Ji-ho script in either new
  style and watching it. This is F1's own gate and nothing below it
  should be attempted until that happens.
- No `split_frame`/`secondary_asset_plan` code-level mutual-exclusion
  guard for this style (Q1 of §6 is a broader, still-open item; this
  slice only discourages `split_frame` in prompt text, per the DO-NOT
  list above).
- No layers, parallax, `CameraMovement` additions, or per-layer budget
  cap (F2-F5, explicitly out of scope).
- `script_suitability`'s style-recommendation prompt
  (`app/prompts/script_suitability/v1.md`) was not updated to mention
  either new style - the plan does not ask for this and it is a
  separate suggestion-engine concern, not touched.
- No live image generation was run against either fragment - the world
  token's correctness is verified as text (contains the right
  vocabulary, omits the banned noun) via unit tests, not against a real
  render. That verification is exactly what the human pass above is for.

### P-IF-F1-review — Collapse the two style rows into one, plus `frame_aspect` (2026-09-04)

**Scope executed:** a review finding on P-IF-F1 above, not new plan scope.
`illustrated_risograph_vertical` / `illustrated_risograph_horizontal` were
23-line files differing on 3 lines - the W2 world token (with its §1.7
comment) lived in two places, exactly long_form_direction.md §4.3's named
lesson ("two styles, one base table - do not fix this twice"). Collapsed to
one `illustrated_risograph` style, default canvas 9:16, with
`frame_aspect="16:9"` opting into the landscape canvas - the same mechanism
`stillness` already uses for its own other canvas (`FRAME_ASPECTS`,
`_STILLNESS_REEL_ASPECT` before this change). Mid-task, the coordinator
flagged a THIRD hardcoded `stillness` check this collapse would otherwise
have shipped broken: `app/api/projects.py`'s `set_render_style` write path.
That fix is folded into this same entry rather than split out, since it is
the direct consequence of generalising `frame_aspect_error`.

**Changes:**
- `backend/app/script/styles.py:499-570` - `FRAME_ASPECTS` kept;
  `_STILLNESS_REEL_ASPECT` removed (no longer meaningful once more than one
  style opts in). New `_FRAME_ASPECT_OVERRIDE_STYLES = frozenset({"stillness",
  "illustrated_risograph"})` (:515) and `style_accepts_frame_aspect(style)`
  (:518-526) - the one function every rule-check call site now reads
  through. `frame_aspect_error` (:529-541) generalised from `if style !=
  "stillness"` to `if not style_accepts_frame_aspect(style)`.
  `resolve_render_format` (:544-...) generalised from the hardcoded
  `resolved == "stillness" and frame_aspect == _STILLNESS_REEL_ASPECT` /
  `RenderFormat(width=720, height=1280)` special case to: resolve the
  band's own default `RenderFormat`, then - if the style opts in AND
  `frame_aspect` names the aspect that is NOT that default - return the
  TRANSPOSE of the default (`width=default.height, height=default.width`).
  Verified this produces byte-identical output to the old hardcoded
  `stillness` branch (720x1280 for `frame_aspect="9:16"`) as well as the
  new `illustrated_risograph` case (1280x720 for `frame_aspect="16:9"`).
  `resolve_draft_format` was NOT touched - it already derives from
  `resolve_render_format` and is proven to follow automatically by
  `test_illustrated_risograph_canvas_defaults_9_16_and_frame_aspect_opts_
  into_16_9`'s draft-format assertions.
- `backend/app/script/styles.py:350-393` - `STYLE_PACING_BANDS` collapsed
  from two `illustrated_risograph_vertical` / `_horizontal` rows to one
  `"illustrated_risograph"` row (render_width=720, render_height=1280 -
  the portrait canvas as default, matching the fragment's own primary
  framing direction). Comment records the §4.3 citation, the mechanism
  reuse, and explicitly notes §6 Q5 is unaffected (see the plan-doc edit
  below) and that `world` is deliberately not a field (see "Effects" below).
- `backend/app/renderer/grading.py:57-90` - `STYLE_GRADES` collapsed the
  same way: one `"illustrated_risograph"` entry at exact identity
  (`1.0/1.0/0.0`), replacing the two identical entries. The identity value
  never varied by canvas, so this changes no rendered pixel.
- `backend/app/prompts/shot_planner_styles/illustrated_risograph.md` (new
  file, replacing `illustrated_risograph_vertical.md` and
  `illustrated_risograph_horizontal.md`, both deleted) - one fragment. All
  content kept verbatim (world token + §1.7 comment, four positive faceless
  framings, ethnicity/hair-colour rule, "plain flat background" rule,
  `split_frame` prohibition) except the two divergent framing bullets,
  replaced by one canvas-conditional bullet keyed off the `- canvas: WxH
  (...)` line `app/planners/shot/planner.py:523-528` already supplies and
  `shot_planner/v1.md`'s own `pan` direction rule already reads the same
  way.
- `backend/app/api/projects.py:161-166` - import `style_accepts_frame_aspect`
  alongside the existing `frame_aspect_error`/`STYLE_PACING_BANDS`/
  `resolve_draft_format` import.
- `backend/app/api/projects.py:293-299` - `CreateProjectRequest.frame_aspect`
  docstring generalised (was "Stillness-only"). **No behaviour change to
  `create_project` itself** - it already validated via `frame_aspect_error`
  and persisted `body.frame_aspect` as-is, so generalising the resolver
  underneath it was sufficient.
- `backend/app/api/projects.py:576-585` - `set_render_style`'s own
  docstring generalised the same way.
- `backend/app/api/projects.py:~617-621` (post-`black`) - **the coordinator's
  flagged bug, fixed:** `project.frame_aspect = body.frame_aspect if
  body.render_style == "stillness" else None` changed to `... if
  style_accepts_frame_aspect(body.render_style) else None`. Before this
  fix, `create_project` (persists `frame_aspect` as-is after validation)
  and `set_render_style` (used to discard it for any non-`"stillness"`
  style) would have disagreed the moment `illustrated_risograph` could
  accept an override: creating a new project at `illustrated_risograph` +
  `frame_aspect="16:9"` would have worked; switching an EXISTING project to
  the same style+aspect would have passed `frame_aspect_error` validation
  and then silently persisted `None`, rendering 9:16 with no error anywhere
  - an R1-shaped drift between two call sites expressing the same rule,
  caught before ship rather than after. Both write paths now read through
  `style_accepts_frame_aspect`, the same function `frame_aspect_error`
  itself reads through.

**grep audit of remaining `"stillness"` literals in `backend/app`, per the
coordinator's request** - four files matched before this change, all four
re-checked after:
- `app/script/styles.py` - the two rule-check comparisons
  (`frame_aspect_error`, `resolve_render_format`) are GONE, replaced by
  `style_accepts_frame_aspect`. The remaining `"stillness"` in this file is
  the `STYLE_PACING_BANDS["stillness"] = StylePacingBand(...)` registry key
  itself - data, not a rule check, left alone.
- `app/renderer/grading.py` - `STYLE_GRADES["stillness"] = StyleGrade(...)`
  - same shape, a registry key, left alone.
- `app/api/projects.py` - the one rule-check comparison (`set_render_style`,
  above) is fixed; no other `"stillness"` literal exists in this file.
- `app/script/suitability.py:49` - `"stillness": (...)` in the
  style-suitability DESCRIPTION table (human-readable text shown to a user
  picking a style) - data, not a rule check, left alone; not touched.

**Deliberately NOT done - `world` as a per-project field:** §6 Q2 already
settled `world` as conceptually per-project for FUTURE multi-world support,
but this collapse does not add a `world` field to `Timeline.metadata` or
`Project`. With one `STYLE_PACING_BANDS` row (and one fragment) per world,
two or three worlds is two or three registry rows/fragments with NO
duplication between them - exactly how `documentary_archival` and
`stillness` already coexist today as separate rows and separate fragments,
neither sharing a line with the other. A `world` field would let one style
row serve several worlds chosen at runtime, but nothing in this codebase
needs that yet - no project has ever needed to pick its world independent
of its style choice - so the field is not earning its cost and is not
built. Revisit if/when a second illustrated world ships (§1.6 selected two
house worlds; only W2 risograph reached F1) and a THIRD near-duplicate
fragment appears - at that point the "do not fix this twice" question would
recur one level up, at the style-row level rather than the file level, and
would be worth its own decision.

**Layers, parallax, and `layers`/per-project `world`:** none touched, per
the coordinator's DO-NOT list - F2-F5 scope, untouched.

**Not touched, per the brief's explicit DO-NOT list:** `PicturePath` enum,
`picture_path` field, `resolve_picture_path`, and
`_force_generation_only_picture_path` in `generate_timeline.py` - verified
via `git diff` that none of these changed (`generate_timeline.py`'s working-
tree diff, pre-existing from P-IF-F1 and never touched this pass, contains
no lines from this entry). The existing four styles' bands, grades, and
fragments - verified unchanged by re-running
`test_existing_four_style_bands_are_byte_for_byte_unchanged` and
`test_original_four_grades_are_byte_for_byte_unchanged`, both still passing
against their exact pre-F1 literal values.

**Test files (updated in place, not new):**
- `backend/tests/unit/script/test_styles.py` - F1 section rewritten for one
  style name; `test_illustrated_risograph_canvas_defaults_9_16_and_frame_
  aspect_opts_into_16_9` replaces the old two-row canvas test and adds
  `resolve_draft_format` coverage; new
  `test_style_accepts_frame_aspect_is_the_single_source_of_truth`; existing
  `test_frame_aspect_is_only_legal_on_stillness` and
  `test_archival_montage_is_9_16_and_rejects_the_stillness_only_aspect_flag`
  needed NO changes - both assert only the substring `"only settable"`,
  which the generalised error message still contains.
- `backend/tests/unit/renderer/test_grading.py` - the identity-grade test
  collapsed to one style name.
- `backend/tests/unit/planners/test_illustrated_risograph_fragment.py` -
  rewritten for one fragment file; new
  `test_framing_bullet_is_canvas_conditional_not_two_files` replaces
  `test_vertical_and_horizontal_differ_only_in_the_orientation_clause`; new
  assertion that the two collapsed style names no longer resolve to a
  fragment at all.
- `backend/tests/unit/api/test_frame_aspect.py` - new
  `test_switching_an_existing_project_to_illustrated_risograph_at_16_9_
  persists_16_9`, calling `set_render_style` directly (with
  `InMemoryProjectRepository` and a minimal `_NoActiveTimelineService`
  stub, since the real `TimelineService` needs a live DB session this pure
  unit test must not open) - the exact switch-path case that would have
  shipped broken without the `set_render_style` fix above.

**Measured:**
- `resolve_render_format("illustrated_risograph")` -> 720x1280, not
  landscape. `resolve_render_format("illustrated_risograph",
  frame_aspect="16:9")` -> 1280x720, landscape.
  `resolve_render_format("illustrated_risograph", frame_aspect="9:16")` and
  `frame_aspect=None` both equal the default. `resolve_draft_format` follows
  automatically for both (confirmed via `.is_landscape`, not merely
  asserted from the mechanism).
- `style_accepts_frame_aspect`: `True` for `stillness` and
  `illustrated_risograph`; `False` for `documentary_archival`,
  `retention_fast`, `archival_montage`, `None`, and an unrecognised name.
- `set_render_style("illustrated_risograph", frame_aspect="16:9")` on an
  EXISTING project (no active timeline) now persists `frame_aspect ==
  "16:9"` - confirmed via the new API-level test, not merely inferred from
  the styles.py fix.
- Registry now holds 5 styles total (was 6 immediately post-F1, 4 before
  F1): `['archival_montage', 'documentary_archival', 'illustrated_risograph',
  'retention_fast', 'stillness']`.
- Test counts: 68 passed across the five F1-adjacent test files
  (`test_styles.py`, `test_grading.py`,
  `test_generation_only_picture_path.py`,
  `test_illustrated_risograph_fragment.py`, `test_frame_aspect.py`) - up
  from P-IF-F1's 64 in four files, +1 file (`test_frame_aspect.py`, +2 new
  tests) with a net +2 tests overall after the vertical/horizontal
  test-pair collapses; 17 passed across the same three untouched-content
  regression files P-IF-F1 re-ran
  (`test_generate_timeline_style_bounds.py`, `test_shot_text_cards.py`,
  `test_styled_prompt.py`) - 85 total, 0 failed.
- `ruff check` on every touched file: clean except the SAME pre-existing
  `B905` finding at `test_styles.py:178` (line shifted by the new import;
  confirmed via `git diff` the finding's line itself is untouched by this
  pass, same as P-IF-F1 noted for its own line 177).
- `mypy` on the three touched production files
  (`app/script/styles.py`, `app/renderer/grading.py`, `app/api/projects.py`):
  0 new errors in any of the three. `app/api/projects.py`'s import graph
  pulls in `app/renderer/music.py`, `app/assets/cost.py`,
  `app/planners/shot/planner.py`, `app/providers/openai_provider.py`, and
  `app/workflow/steps/render.py` transitively, all of which mypy flags -
  every flagged line sits OUTSIDE the three files this pass touched, and
  `app/workflow/steps/render.py`'s errors match the task brief's own
  warning about uncommitted A15 work on this branch. None are in this
  entry's diff.

**Verification (exact commands, run from `backend/`):**
```
../.venv/Scripts/python.exe -m black app/script/styles.py app/renderer/grading.py app/api/projects.py tests/unit/script/test_styles.py tests/unit/renderer/test_grading.py tests/unit/planners/test_illustrated_risograph_fragment.py tests/unit/api/test_frame_aspect.py
  -> 1 file reformatted (app/api/projects.py, one long line wrapped), 6 unchanged
../.venv/Scripts/python.exe -m ruff check app/script/styles.py app/renderer/grading.py app/api/projects.py tests/unit/script/test_styles.py tests/unit/renderer/test_grading.py tests/unit/planners/test_illustrated_risograph_fragment.py tests/unit/api/test_frame_aspect.py
  -> 1 pre-existing B905 finding at test_styles.py:178, outside this diff
../.venv/Scripts/python.exe -m mypy app/script/styles.py app/renderer/grading.py app/api/projects.py
  -> 11 errors in 5 files, all outside the three touched files (see "Measured" above)
../.venv/Scripts/python.exe -m pytest tests/unit/script/test_styles.py tests/unit/renderer/test_grading.py tests/unit/workflow/test_generation_only_picture_path.py tests/unit/planners/test_illustrated_risograph_fragment.py tests/unit/api/test_frame_aspect.py -q
  -> 68 passed in 3.20s
../.venv/Scripts/python.exe -m pytest tests/unit/workflow/test_generate_timeline_style_bounds.py tests/unit/planners/test_shot_text_cards.py tests/unit/workflow/test_styled_prompt.py -q
  -> 17 passed in 2.13s
```
No `PYTEST_TRUNCATE_DB` was set; no DB-backed test was run; `--noconftest`
was never used; `make test` and the full suite were never run, per the
task brief - the ~59 pre-existing `render.py`/A15-related failures in
`tests/unit/renderer/test_fingerprint.py` and
`tests/unit/workflow/test_sfx_overlays_diegetic.py` were neither touched
nor re-verified, since they are out of scope for this pass exactly as they
were for P-IF-F1's own DB-hazard discipline.

**Effects / notes for the reviewer:**
- `resolve_render_format`'s new transpose logic is stated to generalise to
  "any future opt-in style whose 'other' canvas really is its own
  transpose" - both styles registered today satisfy this (each opts into
  exactly the 90°-rotated frame of its own default), but this is a
  documented assumption, not a proven invariant: a hypothetical future
  style wanting a THIRD, non-transpose canvas via `frame_aspect` would need
  a different mechanism, not an extension of this one. Flagged in the
  function's own docstring.
- `_STILLNESS_REEL_ASPECT` was removed rather than kept as an unused
  historical constant - nothing else referenced it (checked via grep before
  deleting), and keeping a same-shaped-but-now-competing constant beside
  `_FRAME_ASPECT_OVERRIDE_STYLES` would have been exactly the kind of
  "two places that must agree" this whole review finding exists to remove.
- The default canvas chosen for the collapsed row (9:16, i.e. what used to
  be `_vertical`) is a judgement call the brief left open ("Default canvas
  9:16 ... that is the primary edit") - taken directly from the brief's own
  wording, not independently decided here.

**What is NOT done:**
- No render was produced and no human watched anything - unchanged from
  P-IF-F1; this is a pure refactor of the registry/resolver/fragment shape,
  not new creative content, so it carries no new obligation to re-run the
  human pass, but the ORIGINAL human pass (§2.1's gate) is still entirely
  outstanding.
- `layers`, parallax, `CameraMovement` additions, a per-project `world`
  field, and `app/renderer/parallax.py` - still untouched, still F2+/
  explicitly-deferred scope (see the "Deliberately NOT done" note above for
  `world` specifically).
- `PicturePath`, `resolve_picture_path`,
  `_force_generation_only_picture_path`, and `generate_timeline.py` in
  general - untouched, per the brief's explicit DO-NOT list.
- `app/workflow/steps/render.py` and `app/planners/fragments.py` - untouched,
  both flagged by the brief as carrying unrelated uncommitted A15 work on
  this branch that this pass must not touch and did not.

```
### P-IF-<slice> — <title> (<date>)

**Scope executed:** exactly what, and explicitly what was NOT started.
**Changes:** file:line for each.
**Measured:** real numbers. Never "looks right".
**Verification:** the exact command run, and its output.
**Effects / notes for the reviewer:**
**What is NOT done:**
```

### P-IF-F1-review2 — suitability registry gap, caught in review (2026-09-04)

**Scope executed:** one omission found reviewing `P-IF-F1-review`, plus the
substantive prompt consequence it exposed. No other F1 behaviour touched.

**Changes:**
- `backend/app/script/suitability.py:65` — added the `illustrated_risograph`
  entry to `_STYLE_DESCRIPTIONS`. It was missing, and
  `tests/unit/script/test_suitability.py` failed on exactly the invariant it
  exists to protect (`test_style_descriptions_cover_every_pacing_band`, plus
  the per-style parametrised case).
- `backend/app/prompts/script_suitability/v1.md` — added the style to the
  system prompt's own style list, and amended **question 3 (material fit)**.

**Measured:** 2 failed → 290 passed across `tests/unit/script`, `tests/unit/api`,
`tests/unit/planners`, `test_grading.py`, `test_generation_only_picture_path.py`.
The single remaining failure,
`test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`, is
the PRE-EXISTING cross-project pollution bug documented twice in
`long_form_direction.md` (§4.6 and P-LF-A5's own log): it counts
`agent='director'` rows across the whole shared database with no project filter,
so it cannot pass without truncation. Not related to F1.

**Verification:**
```
pytest tests/unit/script tests/unit/api tests/unit/planners \
  tests/unit/renderer/test_grading.py \
  tests/unit/workflow/test_generation_only_picture_path.py -q
# 1 failed, 290 passed in 30.24s   (the failure is the pre-existing one above)
```

**Effects / notes for the reviewer:**

`_description_for`'s own docstring predicted this precisely — *"Raising is what
makes style #5 fail in review instead of shipping a fabricated verdict"* — and
style #5 is this one. The mechanism worked as designed; worth preserving.

**The substantive half is question 3, not the dict entry.** The suitability
prompt asked whether *real archival visual material plausibly exists* for the
subject, and marked a script with no real-world visual referent as a poor fit.
For a `GENERATION_ONLY` style that test is not merely irrelevant, it is
**inverted**: this style never searches, so the absence of a photograph is not a
defect, and the un-amended prompt would have marked exactly the scripts this
format exists to serve (systems, statistics, abstractions, archetypal figures)
as unsuitable for it. Question 3 now carries an explicit carve-out for
generated styles and tells the model what to judge instead.

**Generalisation for F2+ and for any later world:** `picture_path` is not only a
routing decision. Any prompt that reasons about whether media *can be found*
needs the same carve-out. Grep for archival/retrieval assumptions in prompts
before adding a second generation-only style.

**What is NOT done:** the F1 human pass (rendering the Ji-ho script and watching
it) — still outstanding, still F1's own gate.

### P-IF-F1-review3 — Director's own generation-only carve-out (2026-09-04)

**Scope executed:** the same root-cause bug P-IF-F1-review2 fixed in
`script_suitability`, found this time on a live planning run of project
`a7af429a-23c9-4456-9f0e-cdd0d8d94077`: the Director's base prompt
(`director/v1.md`) assumes a documentary/photographic world unconditionally
("Documentary default… historical photographs… archival footage") and its
`constraints` reach for provenance language ("licensed footage",
"consent is documented") that is meaningless — and, worse, checked — for a
`GENERATION_ONLY` style. Fixed by keying one additive override block on
`resolve_picture_path`, not on style name, per the brief's explicit
instruction not to create a per-style `director_styles/` fragment (that
would need duplicating for every future generation-only world — the
duplication P-IF-F1-review was dispatched to remove one level down).

**Changes:**
- `backend/app/prompts/director/generation_only.md` (new file) — the
  override block: `visual_style` must describe an illustrated world, not a
  documentary photographic look; `constraints` must describe depiction
  (stereotyping, sensationalising, glorifying, misrepresenting), never
  provenance (licensing, footage rights, archival sourcing, consent, "is
  this a real photograph") and must be answerable by looking at one still
  image; `historical_period` stays required and non-empty but must state
  the setting plainly ("contemporary, 2020s") rather than invent an
  archival era. Says nothing about camera language, mirroring the Shot
  Planner's `suppress_camera_language=style_fragment is not None`
  reasoning — the style fragment owns camera direction downstream, and a
  Director instruction here would contradict it with no stated precedence.
- `backend/app/planners/director/planner.py:14` — import `PicturePath`,
  `resolve_picture_path` from `app.script.styles`.
- `backend/app/planners/director/planner.py:18-24` — `_GENERATION_ONLY_PROMPT_VERSION
  = "generation_only"`, with a comment recording why this is one block
  keyed on picture path rather than a per-style fragment.
- `backend/app/planners/director/planner.py:27-43` — new `_system_prompt_for(render_style)`,
  a pure function (no provider/DB/repair loop) composing
  `load_prompt(AGENT, PROMPT_VERSION)` plus the override block exactly
  when `resolve_picture_path(render_style) is PicturePath.GENERATION_ONLY`
  — the same `base_prompt + "\n\n" + fragment` shape
  `ShotPlanner.plan` already uses for its own style fragment. Pulled out
  as its own function specifically so the composition is unit-testable
  without a DB session.
- `backend/app/planners/director/planner.py:73-86` — `DirectorPlanner.plan`
  gains a defaulted `render_style: str | None = None` keyword (so no
  existing caller breaks) and calls `_system_prompt_for(render_style)`
  instead of `load_prompt(AGENT, PROMPT_VERSION)` directly.
- `backend/app/workflow/steps/generate_timeline.py:259-267` — the call
  site: `DirectorPlanner(...).plan(...)` now passes
  `render_style=timeline.metadata.render_style` — RV2 ("resolve once,
  thread explicitly"), reading the value already loaded onto `timeline`
  at line 255-256 rather than reaching into `project`/settings/the DB a
  second time.
- `docs/plans/illustrated_faceless.md` §4.8 (new) — the generalisation the
  brief asked for: this pattern has now fired three times
  (`script_suitability`, the Director, and a checked-but-not-fixed finding
  in the Asset Planner), plus the grep discipline for the next new format.

**Test files (new):**
- `backend/tests/unit/planners/test_director_generation_only.py` — pure,
  no-DB tests of `_system_prompt_for`: the override is appended and starts
  with the base prompt for `illustrated_risograph`; **the regression that
  matters** — `_system_prompt_for` is byte-identical to
  `load_prompt("director","v1")` for `documentary_archival`,
  `retention_fast`, `archival_montage`, `stillness`, `None`, and an unknown
  style name; the override block itself names and rejects the provenance
  vocabulary (licensing, footage, consent, archival sourcing) rather than
  asking the model to use it, is checkable against "one still image",
  requires a plainly-stated (not invented-archival) `historical_period`,
  says nothing about camera language, and does not live under a new
  `director_styles/` directory.
- `backend/tests/unit/workflow/test_generation_only_picture_path.py` —
  added `test_run_real_threads_the_timelines_render_style_into_the_director_call`,
  a source-inspection test (same shape as the file's existing
  `test_run_actually_calls_the_override_after_the_asset_planner_returns`)
  proving `_run_real` actually passes `render_style=timeline.metadata.render_style`
  into the `DirectorPlanner(...).plan(...)` call, not merely that the
  keyword exists somewhere unused.

**Measured:**
- `_system_prompt_for("illustrated_risograph")` == `load_prompt("director","v1")`
  + `"\n\n"` + `load_prompt("director","generation_only")`, confirmed by
  exact string equality, not substring checks.
- `_system_prompt_for(style)` for `documentary_archival`, `retention_fast`,
  `archival_montage`, `stillness`, `None`, and `"not_a_real_style"` are all
  byte-identical to `load_prompt("director","v1")` — confirmed by exact
  equality.
- `test_director_planner.py`: 3 passed, 1 failed
  (`test_every_attempt_is_recorded_as_an_llm_call`, 34-35 rows instead of
  1) — the SAME pre-existing cross-project `agent='director'` pollution
  documented in P-IF-F1-review2's own log and `long_form_direction.md`
  §4.6; row count differed between runs (34 then 35) purely because more
  rows had accumulated in the shared DB between the two invocations, which
  is itself further confirmation this is unbounded cross-run pollution and
  not something this change caused.
- Wider re-run: `tests/unit/script tests/unit/api tests/unit/planners
  tests/unit/renderer/test_grading.py tests/unit/workflow/test_generation_only_picture_path.py`
  → 1 failed (the same pre-existing test above), 297 passed — up from
  P-IF-F1-review2's own 290 passed in the same command, the +7 being this
  pass's new tests (6 in `test_director_generation_only.py` + 1 in
  `test_generation_only_picture_path.py`).
- `black --check`: 4 files unchanged. `ruff check`: all checks passed, 0
  findings. `mypy` on the two touched production files: 0 new errors — the
  same 2 pre-existing errors as P-IF-F1's own log
  (`app/planners/shot/planner.py:822`, `app/providers/openai_provider.py:85`),
  both outside this diff.

**Verification (exact commands, run from `backend/`):**
```
../.venv/Scripts/python.exe -m pytest tests/unit/planners/test_director_generation_only.py tests/unit/workflow/test_generation_only_picture_path.py tests/unit/planners/test_illustrated_risograph_fragment.py -q
  -> 25 passed in 2.35s
../.venv/Scripts/python.exe -m pytest tests/unit/planners/test_director_planner.py -q
  -> 1 failed, 3 passed in 1.76s   (the pre-existing cross-project pollution failure, see "Measured" above)
../.venv/Scripts/python.exe -m pytest tests/unit/script tests/unit/api tests/unit/planners tests/unit/renderer/test_grading.py tests/unit/workflow/test_generation_only_picture_path.py -q
  -> 1 failed, 297 passed in 28.97s   (same pre-existing failure, no other failures)
../.venv/Scripts/python.exe -m black --check app/planners/director/planner.py app/workflow/steps/generate_timeline.py tests/unit/planners/test_director_generation_only.py tests/unit/workflow/test_generation_only_picture_path.py
  -> 4 files would be left unchanged
../.venv/Scripts/python.exe -m ruff check app/planners/director/planner.py app/workflow/steps/generate_timeline.py tests/unit/planners/test_director_generation_only.py tests/unit/workflow/test_generation_only_picture_path.py
  -> All checks passed!
../.venv/Scripts/python.exe -m mypy app/planners/director/planner.py app/workflow/steps/generate_timeline.py
  -> Found 2 errors in 2 files (both pre-existing, outside this diff)
```
No `PYTEST_TRUNCATE_DB` was set; `--noconftest` was never used; `make test`
and the full suite were never run, per the task brief. The ~59 pre-existing
`render.py`/A15-related failures in `tests/unit/renderer/test_fingerprint.py`
and `tests/unit/workflow/test_sfx_overlays_diegetic.py` were neither touched
nor re-verified — out of scope, `render.py` and `fragments.py` untouched by
this pass.

**Effects / notes for the reviewer:**
- **Why a pure `_system_prompt_for` function rather than inlining the
  composition in `plan()`:** the brief asks for a byte-identity regression
  test across six style values. Testing that through `DirectorPlanner.plan`
  directly would need a DB session and a fake provider for every case
  (matching `test_director_planner.py`'s own DB-backed shape) — pulling the
  composition into its own function makes the exact same assertion a
  no-DB, sub-second test, the same trade `load_style_fragment` already
  makes for the Shot Planner.
- **Asset Planner finding, not fixed (per the brief's instruction):** its
  prompt (`asset_planner/v1.md`) carries the identical assumption
  throughout — "Reuse before generate", the six-rung ladder, "archival/
  government/historical-photo sources" — but this is structurally
  different from the other two instances: `_force_generation_only_picture_path`
  (§3.2, already shipped in P-IF-F1) overrides every `GENERATION_ONLY`
  shot's `strategy`/`fallback_chain`/`preferred_type` regardless of what
  the Asset Planner said, and its `entity`/`search_queries` output is
  simply discarded unused rather than billed against a vision model or
  gated on. So the live defect class (money spent checking an
  already-generated image against an inapplicable/inverted constraint)
  does not recur here — the cost is wasted reasoning tokens, not a wrong
  or billed outcome. Recorded in §4.8, not fixed, per the brief's explicit
  "do NOT fix them in this pass."
- **Scene Planner and Act Planner checked, clean:** both prompts are pure
  narrative-structuring (fragment ranges, emotion, narrative purpose) with
  no photograph/footage/archive/licence/consent vocabulary at all —
  nothing to carve out.
- **Uncertain, flagged rather than silently decided:** the brief's own
  worked example for the override block reads "Keep constraints that
  describe what must not be *depicted* (stereotyping, sensationalising,
  glorifying, misrepresenting)" — this wording was used close to verbatim
  in the prompt file. Whether that four-item list is meant to be
  exhaustive or illustrative was not stated either way; the prompt file
  frames it as "the kind of constraint that describes..." (illustrative),
  which reads more consistent with the Director's base prompt's own "list
  explicit constraints... err toward more constraints, not fewer" —
  flagging this reading rather than treating it as obviously correct.
- The `historical_period` field's non-empty requirement was already
  enforced by `_validate`'s existing loop over `("tone", "visual_style",
  "historical_period", "audience", "camera_language")` — untouched by this
  pass; the override block only changes what the model is told to WRITE
  into that field, not the validation itself.

**What is NOT done:**
- The F1 human pass (rendering the Ji-ho script and watching it) — still
  outstanding, still F1's own gate, unaffected by this fix.
- The Asset Planner's own carve-out (found, not fixed — see "Effects /
  notes" above and §4.8).
- No live LLM call was made against either prompt file (base + override)
  to observe an actual Director output on the real `illustrated_risograph`
  project — verified as text (contains the right vocabulary, omits the
  provenance vocabulary as something to write) via unit tests, and by the
  exact byte-identity regression for every other style, not against a real
  model response. No external API was called and nothing was re-planned,
  per the brief's explicit DO-NOT list.
- `director/v1.md` itself was not modified — the override is purely
  additive, per the brief's constraint.
- `render.py` and `fragments.py` — untouched, both pre-existing
  uncommitted A15 work on this branch, out of scope for this pass exactly
  as flagged in the brief.

### P-IF-F1-fixes — three fixes from watching the first real render (2026-09-04)

**Scope executed:** exactly the three fixes below, all found by the user
watching `tmp/jiho-riso/jiho-30s-risograph.mp4` (project
`7df10f6c-e6b9-4275-b88a-7f07d0178011`) — F1's own §2.1 human pass, still
not fully re-run (no new render was produced by this pass; see "What is
NOT done"). No motion, layers, schema, or fingerprint work — none of that
is F1 scope. `render.py` and `fragments.py` left untouched, per the DO-NOT
list.

**Changes:**

*Fix 1 — no recurring character:*
- `backend/app/prompts/director/generation_only.md:9-27` — the
  `visual_style` bullet rewritten: it now says explicitly that
  `visual_style` owns cast/subject/mood/setting and must NOT describe
  medium/palette/technique (those belong to the named style), citing the
  §4.9 gouache-and-pencil measurement as the concrete example.
- `backend/app/prompts/director/generation_only.md:29-44` — new bullet:
  when the script has a recurring human character, `visual_style` must
  also carry a fixed figure block (build, hair length/shape/colour, skin
  tone, one or two signature garments/objects), grounded in the script,
  never invented, one block per named person if several, silent if none.
- `backend/app/prompts/shot_planner_styles/illustrated_risograph.md:21` —
  new bullet: when the Director's `visual_style` carries a figure block
  for a character a shot shows, reproduce it in `prompt` essentially
  verbatim — the same restate-every-time reasoning the world token
  already uses, for the same reason (no memory across calls).
- `docs/plans/illustrated_faceless.md` §4.9 (this file) — added a
  "Fixed in P-IF-F1-fixes" note under the existing finding, closing the
  open division-of-labour question option (2) (visual_style content
  rule), explicitly NOT building option (1) (suppressing `visual_style`
  from the Shot Planner entirely), and recording that a dedicated
  `CreativeContext` cast field would be a stronger, schema-costed
  alternative deliberately not built here.

*Fix 2 — paper substrate noun:*
- `backend/app/prompts/shot_planner_styles/illustrated_risograph.md:7` —
  world token reworded: "…printed on off-white uncoated paper" (a
  physical substrate the image sits on) became "…the coarse grain and
  texture of off-white uncoated paper woven through the image as a
  surface, never a page or sheet the picture sits on" (a texture of the
  image, explicitly negating a substrate reading). Risograph technique
  vocabulary (three spot colours, ink grain, halftone, misregistration,
  high contrast, simplified graphic shapes) unchanged.
- `backend/app/prompts/shot_planner_styles/illustrated_risograph.md:11`
  — the existing §1.7 HTML comment extended with a second paragraph
  recording that the first fix (dropping "poster") was incomplete, citing
  the real project and the Ken-Burns-masks-the-defect finding, and
  warning a future editor not to reintroduce "printed on paper" thinking
  the rule was only ever about the word "poster".
- `docs/plans/illustrated_faceless.md` §1.7 (this file, after the
  existing 2026-09-04 correction paragraph) — new correction paragraph:
  the first fix was incomplete, the measured symptom (paper border,
  signature mark, stamp on the source still), why it was invisible in the
  rendered video (Ken Burns crop), and the standing rule that a Ken Burns
  crop masking a substrate artefact in video is not evidence the token is
  clean — check the source still, not the video.

*Fix 3 — narration speed:*
- `backend/app/script/styles.py:374` — `illustrated_risograph`'s
  `StylePacingBand` gains `narration_speed=1.15`, with a comment citing
  the real render, `archival_montage`'s own documented 1.15-1.25
  Hinglish-safe band (this project is `language_code=hi`), why 1.15 (the
  conservative end) was chosen over 1.25 or `retention_fast`'s unrelated
  1.4, that the value is un-eared, and that it invalidates every cached
  narration for this style via `compute_narration_content_hash`.
- `backend/app/script/styles.py:333` — the "no narration-speed override"
  comment above the registry entry corrected (it no longer applies).

**Test files (updated in place, no new files):**
- `backend/tests/unit/planners/test_illustrated_risograph_fragment.py` —
  three new tests: the world token no longer names a physical substrate
  and still contains the technique vocabulary; the extended comment
  records "incomplete", "ken burns", the project id, and "source still";
  the fragment instructs verbatim figure-block reproduction. The
  pre-existing `test_the_world_token_is_present_and_the_artefact_noun_is_
  gone` needed NO change — the reworded token still contains
  "off-white uncoated paper" as a contiguous substring and still omits
  "poster", so its existing assertions still hold.
- `backend/tests/unit/planners/test_director_generation_only.py` — two
  new tests: the override names cast/subject/mood/setting and
  medium/palette/technique (plus the "gouache" regression citation), and
  the override asks for a recurring-character figure block (figure
  block/recurring/build/hair/skin tone/"never invent a character"). The
  existing `test_override_block_does_not_argue_about_camera_language`
  needed no change — neither new bullet mentions camera.
- `backend/tests/unit/script/test_styles.py` — `test_illustrated_
  risograph_defaults_to_documentary_archivals_inert_pacing` renamed to
  `..._except_speed` and its `narration_speed` assertion updated from
  1.0 to 1.15; new `test_illustrated_risograph_narration_speed_is_the_
  conservative_hinglish_value` (pins 1.15 and the 1.15-1.25 band); new
  `test_the_other_four_styles_narration_speed_is_unchanged_by_the_
  illustrated_risograph_fix` (regression: `None`/`documentary_archival`/
  `stillness` at 1.0, `retention_fast` at 1.4, `archival_montage` at
  1.25, all unchanged).

**Measured:**
- `resolve_narration_speed("illustrated_risograph")` → `1.15` (was
  `1.0`). `resolve_narration_speed` for `None`, `documentary_archival`,
  `stillness`, `retention_fast` (1.4), `archival_montage` (1.25) all
  unchanged — confirmed by exact equality, not substring.
- `resolve_constraint_bundle("illustrated_risograph") ==
  resolve_constraint_bundle(None)` still holds — `narration_speed` is not
  part of `ConstraintBundle`, so this fix does not touch it.
- World token line: `"printed on" not in token_line.lower()`,
  `"off-white uncoated paper" in token_line.lower()`,
  `"page or sheet" in token_line.lower()` — all confirmed on the actual
  loaded fragment text, not the source file by inspection alone.
- `generation_only.md` override text: contains "cast", "subject",
  "mood", "setting", "medium", "palette", "technique", "gouache" (the
  named regression), "figure block", "recurring", "build", "hair", "skin
  tone", "never invent a character" — confirmed on the loaded prompt
  text.
- Test counts: `test_styles.py` + `test_illustrated_risograph_fragment.py`
  + `test_director_generation_only.py` together: 60 passed (up from
  P-IF-F1-review3's totals across the equivalent files — 6 new tests
  added: 2 in `test_styles.py`, 3 in `test_illustrated_risograph_
  fragment.py`, 2 in `test_director_generation_only.py`, minus the one
  test renamed in place).
- Wider re-run, same command shape as every prior F1 entry:
  `tests/unit/script tests/unit/api tests/unit/planners
  tests/unit/renderer/test_grading.py
  tests/unit/workflow/test_generation_only_picture_path.py` → 1 failed,
  304 passed. The 1 failure is the SAME pre-existing
  `test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`
  cross-project pollution bug named in the task brief and in every prior
  F1 log entry (`long_form_direction.md` §4.6) — row count 38 this run,
  differing from the 34/35 seen in earlier entries purely because more
  rows have accumulated in the shared DB since, itself further
  confirmation this is unbounded cross-run pollution, not caused by this
  pass.
- `black --check` on the one touched production file and the three
  touched test files: 4 files unchanged. `ruff check` on the same four
  files: clean except the SAME pre-existing `B905` finding at
  `test_styles.py:178` (line shifted by earlier edits, confirmed via
  `git diff` untouched by this pass, same finding every prior F1 entry
  has noted). `mypy app/script/styles.py`: no issues found.

**Verification (exact commands, run from `backend/`):**
```
../.venv/Scripts/python.exe -m pytest tests/unit/script/test_styles.py tests/unit/planners/test_illustrated_risograph_fragment.py tests/unit/planners/test_director_generation_only.py -q
  -> 60 passed in 1.06s
../.venv/Scripts/python.exe -m pytest tests/unit/script tests/unit/api tests/unit/planners tests/unit/renderer/test_grading.py tests/unit/workflow/test_generation_only_picture_path.py -q
  -> 1 failed, 304 passed in 29.53s   (pre-existing cross-project pollution, see "Measured")
../.venv/Scripts/python.exe -m black --check app/script/styles.py tests/unit/script/test_styles.py tests/unit/planners/test_illustrated_risograph_fragment.py tests/unit/planners/test_director_generation_only.py
  -> 4 files would be left unchanged
../.venv/Scripts/python.exe -m ruff check app/script/styles.py tests/unit/script/test_styles.py tests/unit/planners/test_illustrated_risograph_fragment.py tests/unit/planners/test_director_generation_only.py
  -> 1 pre-existing B905 finding at test_styles.py:178, outside this diff
../.venv/Scripts/python.exe -m mypy app/script/styles.py
  -> Success: no issues found in 1 source file
```
No `PYTEST_TRUNCATE_DB` was set; no `--noconftest`; `make test` and the
full suite were never run, per the task brief. The ~59 pre-existing
`render.py`/A15-related failures in `tests/unit/renderer/test_fingerprint.py`
and `tests/unit/workflow/test_sfx_overlays_diegetic.py` were neither
touched nor re-verified — out of scope, exactly as every prior F1 entry
has noted.

**Effects / notes for the reviewer:**
- **Fix 1 deliberately lives in `visual_style` (free text), not a new
  schema field.** `_build_user_content` (`app/planners/shot/planner.py:
  562-564`) already threads `creative_context.visual_style` into every
  Shot Planner call for every scene — confirmed by reading that function,
  not assumed — so this is the seam that reaches every scene at zero
  schema/fingerprint cost. A dedicated `CreativeContext` field for the
  cast would be more structured (queryable, independently validatable)
  but is a schema change with its own §3.4/R2 fingerprint-coverage
  obligation, and was deliberately not built — flagged in §4.9's own
  updated text, not hidden.
- **Fix 1's figure-block instruction is prose-only, same enforcement
  level as the rest of this fragment.** There is no code-level check that
  a shot actually reproduced the figure block verbatim (that would need a
  post-hoc text-similarity check against `creative_context.visual_style`,
  which does not exist and was not built) — same class of limitation this
  file already accepted for `split_frame`-discouragement in P-IF-F1.
- **Fix 2's wording keeps the exact substring `"off-white uncoated
  paper"`** so the pre-existing artefact-noun test needed no change —
  this was a deliberate wording choice among several that would have
  satisfied §1.7's rule, not the only possible fix; flagging the
  choice rather than treating it as the obviously correct wording.
- **Fix 3's value (1.15) is UN-EARED.** Nobody has listened to a real
  narration clip at 1.15 for this style — the value is chosen from
  `archival_montage`'s own documented band by the same reasoning that
  set that style's value, not verified by ear for this one. The next
  render must be listened to, and dropped further only if the band's own
  lower bound turns out insufficient (not raised toward 1.25 without a
  reason).
- **Fix 3 invalidates every cached narration for `illustrated_risograph`
  going forward** (narration_speed is hashed into
  `compute_narration_content_hash`) — the next render of any project on
  this style, including a re-render of `7df10f6c`, pays for TTS again.
  At Ji-ho's ~30s length this is single-digit cents, stated here so it
  does not read as a surprise bill.
- No render was produced and no external API was called by this pass, per
  the brief's explicit DO-NOT list — every claim above about prompt
  content is verified as text (loaded via `load_prompt`/
  `load_style_fragment`, the same mechanism production uses), not against
  a live model response.

**What is NOT done:**
- **F1's own human pass is still not satisfied.** These three fixes
  respond to what the FIRST render showed; none of them has itself been
  watched. A second render, on the same or a comparable script, still
  needs a human pass before F1's own gate (§2.1) is considered closed.
- Option (1) from §4.9 (suppressing `visual_style` from the Shot
  Planner's user content when a style fragment exists) — not built; (2)
  was preferred as the cheaper fix and nothing yet shows (2) failing.
- A dedicated `CreativeContext` cast field — not built, schema-costed,
  noted in §4.9 as a future stronger alternative.
- Any code-level check that a shot's `prompt` actually contains the
  figure block near-verbatim — prompt instruction only, same as this
  file's other prose-level rules.
- `layers`, parallax, `CameraMovement`, and any other F2+ scope —
  untouched.
- `render.py` and `fragments.py` — untouched, per the brief's explicit
  DO-NOT list (both carry unrelated uncommitted A15 work on this branch).

### 4.9 ⚠ A style that owns the WORLD must stop the Director describing one

**Measured 2026-09-04 on project `7df10f6c`, after `P-IF-F1-review3` landed.**
The generation-only block correctly stopped the Director writing a
*photographic* `visual_style` — but it then wrote a different *illustrated*
one:

> "Poetic editorial illustration … hand-painted digital **gouache and pencil
> textures**, muted pre-dawn blue apartment interiors …"

while the style's own locked world is **risograph** — three spot colours, ink
grain, halftone. Two contradictory world descriptions in one request, with no
stated precedence between them.

**It caused no damage this run**: the style fragment won 9/9 (every shot prompt
carried the risograph token verbatim, none mentioned gouache or pencil). But it
won by prompt ordering and emphasis, not by rule — which is exactly the
condition this codebase already refused to accept once.

**The precedent is `suppress_camera_language`** (`app/planners/shot/planner.py`,
Q6): *"a style fragment that owns camera must not share the request with the
Director's `camera_language` — the two contradict with no stated precedence."*
Identical shape, one field over: a style fragment that owns the WORLD must not
share the request with a Director-authored `visual_style`.

**The fix is a division of labour, not a longer prompt.** Where a style carries
a locked world, the Director should describe **subject, mood and setting only**
and say nothing about medium, palette, or technique — those belong to the style.
Two candidate mechanisms, both already in the codebase:

1. suppress `visual_style` in the Shot Planner's user content when a style
   fragment exists, exactly as `camera_language` already is; or
2. tell the generation-only block to leave medium/palette/technique out of
   `visual_style` altogether.

(2) is cheaper and keeps `visual_style` honest for the review UI; (1) is the
stronger guarantee. Prefer (2), and add (1) if a later run shows the Director
still reaching for a medium.

**Not fixed in F1.** No shot was harmed, and F1's own gate is a human watching a
render — fixing this first would delay that for a defect that has not yet
produced a bad frame. Do it before a SECOND world ships, because two worlds is
when "the fragment happens to win" stops being reliable.

**Fixed in P-IF-F1-fixes (2026-09-04), option (2) above.** `director/
generation_only.md`'s `visual_style` bullet now says explicitly that
`visual_style` owns cast, subject, mood, and setting, and must NOT describe
medium, palette, or technique — those belong to the named style, quoting
this section's own "hand-painted digital gouache and pencil textures"
measurement as the concrete example of what not to repeat. Option (1)
(suppressing `visual_style` from the Shot Planner's user content, the
stronger guarantee) was **not** built — this pass took the cheaper route
this section already recommended trying first, on the same "no shot was
harmed yet" reasoning; revisit (1) if a later run shows the Director still
reaching for a medium despite the instruction.

**The same real render (project `7df10f6c`) also showed the division of
labour was incomplete in the other direction: nothing told the Director to
put a recurring character's identity anywhere Shot Planner calls could
share it**, so every scene invented its own version of the same named
character. Fixed in the same pass — `generation_only.md` now also asks the
Director for a fixed FIGURE BLOCK (build, hair, skin tone, one or two
signature items) inside `visual_style` when the script has a recurring
character, and `illustrated_risograph.md` now asks the Shot Planner to
reproduce it near-verbatim whenever a shot shows that character. See
P-IF-F1-fixes below for the full change. **A dedicated `CreativeContext`
field for the cast (rather than living inside the free-text `visual_style`
string) would be a stronger, more structured version of this** — it would
let future code validate or surface the figure block independently — but
it is a schema change (new field, new fingerprint coverage per §3.4/R2) and
was deliberately not done in this pass; `visual_style` was the seam that
already reaches every Shot Planner call with zero schema cost.

### 4.10 ⛔ The style fragment is sent to the model VERBATIM — comments included

**Found in review 2026-09-04, immediately after `P-IF-F1-fixes`, and it had
made §1.7 actively self-defeating.**

`app/prompts/loader.py::load_style_fragment` reads the whole `.md` file and the
Shot Planner appends it to its system prompt. **HTML comments are not stripped.**
An `<!-- ... -->` block is obvious to a *human* reader as a note rather than an
instruction; to a model receiving the file as text there is no such distinction.

So the §1.7 rationale — written specifically to keep artefact nouns away from
the image model — was being fed to the model on every scene call. Measured in
the shipped fragment:

| noun in the prompt | count |
|---|---|
| poster | **5** |
| printed on | 3 |
| notebook | 2 |
| page or sheet | 2 |
| paper border | 2 |
| signature mark / stamp | 1 each |
| open background / book / pages | 1 each |

The last three of the top group are the exact artefacts that appeared in the bad
still. And a test asserted the leak *stayed* — `test_a_comment_explains_why_the
_artefact_noun_was_removed` required `"poster"` to be present, justified by the
premise that a comment "is easy to spot as a note rather than an instruction."
That premise is true for a reviewer and false for the consumer.

**Rules, now enforced by test:**

1. **A style fragment names no forbidden noun, anywhere — comment included.**
   The rationale lives in this plan; the fragment carries a pointer and nothing
   more. `test_the_whole_fragment_names_no_artefact_or_negation_noun` checks the
   whole file, not just the token line.
2. **No negations in the token.** `P-IF-F1-fixes` replaced "printed on … paper"
   with "…never a page or sheet the picture sits on" — which contradicted the
   same fragment's own measured rule that a face-biased model honours a negation
   unreliably, *and* put the nouns back. Express the positive form of the intent
   instead: the token now ends "The image fills the frame completely, edge to
   edge."
3. **Prompt wording is never chosen to avoid editing a test.** The first fix
   preserved the substring "off-white uncoated paper" so an existing assertion
   would still pass. If a test and a measured prompt rule disagree, the test is
   what changes.

**Generalises beyond this fragment.** Every `shot_planner_styles/*.md` file, and
`director/generation_only.md`, reach a model the same way. Before adding an
explanatory comment to any prompt file, ask whether it would be safe as an
instruction — because that is what it becomes.

### P-IF-F2 — Layers in the schema, and two-layer parallax (2026-09-04)

**Scope executed:** exactly F2's §2.2 scope - `Shot.layers`/`ShotLayer` in
the schema (defaulting to empty), the §6 Q1 mutual-exclusion validator
against `secondary_prompt`/`secondary_asset_plan`, a new
`CameraMovement.PARALLAX` value, `app/renderer/parallax.py` (ported from
`parallax_probe.py`, beside `ken_burns.py`/`split_screen.py`), fingerprint
coverage for layer count/roles/drift/scale (R2), and the §4.5 keyed-fraction
guard. Read §8.1 first, per the brief - the substrate-crop fix it names as a
prerequisite for judging a real layered render is explicitly NOT attempted
here (deferred at the user's own request); nothing below produces or judges
a render, so that gap does not block this slice's own scope.

**NOT started, explicitly:** no wiring into `app/renderer/slideshow.py`'s
dispatch or `app/workflow/steps/render.py`'s media resolution - `parallax.py`
is a standalone, fully-tested module exactly like `ken_burns.py`/
`split_screen.py` are individually, but nothing calls it yet (`render.py` is
on the brief's DO-NOT list, and wiring `slideshow.py` alone with no caller
in `render.py` would leave dead code with no real coverage). No timed layer
entry, no element transforms, no third (foreground) layer, no per-layer
placement tuning, no per-project layer-count budget cap (§4.3 names one as
needed; not built - out of F2's own numbered scope). The Shot Planner's
structured-output schema (`app/planners/shot/schemas.py`,
`shot_planner/v1.md`) was read, not modified - `ShotLayer` has no authoring
path from the LLM yet, same as `asset_plan` already has none (`asset_plan`
is the Asset Planner's job; by the same shape, filling `ShotLayer.prompt`/
`asset_plan` from a planner is later scope). `render.py` and
`fragments.py` untouched, per the brief's DO-NOT list (uncommitted A15 work).
`split_frame`/`secondary_prompt`/`secondary_asset_plan` untouched beyond the
new validator. No external API call, no render, no commit.

**Changes:**
- `backend/app/schemas/timeline.py:92-109` - `CameraMovement.PARALLAX`, a
  new value the planner can write to request two-layer parallax (canon
  3.1 - the renderer only executes it; `camera.direction`/`intensity`
  are not consulted, the same way `PUNCH_IN` above does not consult
  `direction`). Documented as legitimately unguarded / unauthored by the
  Shot Planner in this slice (a shot carrying this movement with empty
  `layers` degrades to nothing, the same as an under-specified
  `SPLIT_FRAME` shot already does elsewhere).
- `backend/app/schemas/timeline.py:239-248` - `LayerRole` StrEnum
  (`background`/`subject`/`foreground`); F2 legalises only the first two,
  enforced by `parallax.py`'s own two-layer builder, not by the schema
  (F3 legitimately adds the third).
- `backend/app/schemas/timeline.py:252-296` - `ShotLayer`: `role`,
  `prompt`, `asset_plan` (reuses the existing `AssetPlan` model - no new
  asset-plan shape), `drift_x`/`drift_y` (px over the shot's
  `duration_s`), `scale` (`Field(default=1.2, gt=1.0)` - `parallax_probe.py`'s
  own measured oversize factor, and `gt=1.0` makes an under-1.0 scale a
  construction-time `ValidationError` rather than a filter that silently
  has nowhere to drift).
- `backend/app/schemas/timeline.py:369` - `Shot.layers: list[ShotLayer] =
  Field(default_factory=list)` - additive default (§3.1): empty on every
  shot that does not set it, which today is every shot on every existing
  Timeline.
- `backend/app/schemas/timeline.py:371-388` -
  `_layers_and_split_screen_are_mutually_exclusive`, a `model_validator
  (mode="after")` on `Shot`: raises when `layers` is non-empty AND
  either `secondary_prompt` or `secondary_asset_plan` is set. Checked
  both directions in tests below. `split_frame` itself (camera movement,
  compositing code) is untouched - only this one cross-field invariant
  is new.
- `backend/app/renderer/parallax.py` (new file, 357 lines) - the F2
  renderer module, ported from `backend/scripts/parallax_probe.py`:
  `oversized_size`/`base_offset`/`drift_expressions` (the probe's
  oversize/travel arithmetic, generalised from fixed constants to a
  layer's own `scale`/`drift_x`/`drift_y`), `sample_key_colour` (ported
  from `_sample_key`, generalised to take image BYTES rather than a
  path - §1.5/I5), `base_canvas_filter`/`layer_input_chain` (ported from
  `_base`/`_layer_in`), `ParallaxLayerInput`/
  `build_two_layer_parallax_filter_complex` (ported from `_clip_a`,
  generalised to a Shot's own `ShotLayer` values and rejecting anything
  but `(BACKGROUND, SUBJECT)` in that order), `validate_two_layer_shot`,
  and the §4.5 guard: `keyed_fraction` (measures what share of a layer's
  bytes fall within the sampled key's similarity - an approximation of
  ffmpeg's own `colorkey`, documented as such, not a reimplementation)
  and `check_keyed_fraction`/`ParallaxKeyGuardError` (raises, distinctly
  worded, on zero - §1.5's opaque-rectangle bug - and on anything above
  the ~85% ceiling - the key eating the subject).
- `backend/app/renderer/fingerprint.py:76-89` (module docstring),
  `:194,209` (`compute_render_fingerprint` gains `layer_content_hashes:
  dict[str, list[str]] | None = None`), `:228-270` (new `"shot_layers"`
  payload entry, keyed by `shot_id`, holding whatever hashes the caller
  supplies - `[]` when absent, matching every call site today) - R2
  coverage for a layer's resolved image BYTES (I2: the Timeline itself
  never carries those, so the full `timeline.model_dump` this function
  already does cannot see them; a layer's CREATIVE fields - role,
  prompt, asset_plan, drift_x, drift_y, scale - already ride into that
  same dump for free, exactly like `secondary_prompt`/
  `secondary_asset_plan` already do, so no separate entry was needed for
  those).
- `backend/app/renderer/fingerprint.py:408,424,456` -
  `compute_run_fingerprint` gains the same `layer_content_hashes` hook,
  same shape as its existing `secondary_content_hashes`/`secondary_hash`
  (its own `shot.model_dump(mode="json")` already covers the creative
  fields, same free ride as above).
- `backend/app/renderer/fingerprint.py:458-511` -
  `compute_shot_stream_fingerprint` gains BOTH an explicit `"layers":
  [layer.model_dump(...) for layer in shot.layers]` entry AND a new
  `layer_asset_hashes: list[str] | None = None` parameter. This is the
  one function in the module that does NOT dump the whole `Shot` (it
  hand-picks fields, deliberately excluding `transition_out`) - so
  unlike the two functions above, `Shot.layers` needed an EXPLICIT line
  here or a layer-only edit would silently miss this cache, exactly the
  R2 gap this whole module exists to close. Found by reading the
  function's own docstring rather than assumed from the other two
  functions' shape.

**Test files (new):**
- `backend/tests/unit/timeline/test_shot_layers.py` (21 tests) - schema
  defaults/isolation (`layers=[]` for a shot built the way each of the
  four pre-existing styles already builds one; the new field's presence
  in `model_dump` is pinned, not hidden), `ShotLayer`'s field shape and
  its `scale > 1.0` constraint, the mutual-exclusion validator in BOTH
  directions plus the "empty layers list never trips it" case,
  `CameraMovement`'s seven pre-existing values pinned unchanged plus the
  new `PARALLAX` value, and three source-inspection tests proving
  `ken_burns.py`/`split_screen.py`/`slideshow.py`/`render.py` do not yet
  reference `.layers` anywhere (the isolation claim as a fact about the
  code, not merely a plan statement).
- `backend/tests/unit/renderer/test_parallax.py` (28 tests) - the
  oversize/offset/drift arithmetic against `parallax_probe.py`'s own
  measured numbers (864×1536 at 1.2x on a 720×1280 canvas, etc.), every
  filter-graph fragment as a pure string assertion including the full
  two-layer `filter_complex` split apart and checked part-by-part
  against the probe's `_clip_a` shape, `sample_key_colour` sampling the
  DELIVERED colour rather than a requested one (using §1.5's own
  measured `#B43E7E` drift as the fixture) and ignoring a subject
  touching the bottom edge, and the keyed-fraction guard's zero
  (opaque-rectangle) and near-100% (ate-the-subject) cases with
  distinct, non-interchangeable messages.
- `backend/tests/unit/renderer/test_fingerprint_parallax.py` (19 tests)
  - kept in its OWN file rather than extended into the broken
    `test_fingerprint.py` (see that file's own docstring for why).
    Proves: no-layers is deterministic; adding layers, changing a
    layer's drift/scale/role, and adding a third layer each change
    `compute_render_fingerprint`; two identical layer lists fingerprint
    identically; `layer_content_hashes` absent/`None`/`{}` are all
    equivalent to today's behaviour; `layer_content_hashes` values
    themselves are real inputs; the same for `compute_shot_stream_
    fingerprint` (including a regression check that fields it already
    excludes, like `text_card`, still do not affect it) and
    `compute_run_fingerprint`.

**Measured:**
- `oversized_size(720, 1280, 1.2) == (864, 1536)`, `base_offset(720,
  1280, 864, 1536) == (-72, -128)` - exact match to
  `parallax_probe.py`'s own `_LW,_LH`/`_X0,_Y0` for its real 720×1280
  canvas.
- `sample_key_colour` on a synthetic image filled with §1.5's own
  measured drifted colour (`#B43E7E`) returns `"0xB43E7E"` exactly -
  confirmed the port samples what is DELIVERED, not a constant.
- `build_two_layer_parallax_filter_complex(...)` on the probe's own
  constants reproduces `_clip_a`'s filter shape token-for-token (base
  canvas, two `scale`+`setsar`(+`colorkey`)+`format=rgba` chains, two
  chained `overlay`s, `shortest=1` on the first) - confirmed by
  splitting the returned string on `;` and asserting each part.
- `check_keyed_fraction`: raises with `"matched nothing"` at
  `fraction=0.0`, raises with `"ate the subject"` at `fraction=0.95`,
  passes silently at the band boundaries `0.15`/`0.85` inclusive, and
  the two failure messages are asserted UNEQUAL (not just "both raise")
  so a caller reading the message can tell the two bugs apart.
- Fingerprint: `compute_render_fingerprint` changes when layers are
  added, when a layer's `drift_x`/`scale`/`role` changes, and when a
  third layer is added; is unchanged when two calls carry identical
  layers, and unchanged whether `layer_content_hashes` is omitted,
  `None`, or `{}` (all three equivalent - today's behaviour for every
  call site, since none pass it yet). `compute_shot_stream_fingerprint`
  changes when layers are added or a layer's drift changes, and when
  `layer_asset_hashes` differs even with identical `layers` - confirmed
  it does NOT change when only `id`/`intent_text`/`text_card` differ
  (fields this function already excludes), proving the new `layers`
  entry did not accidentally widen its sensitivity.
- Test counts: 68 passed across the three new F2 test files
  (21 + 28 + 19). Full-module regression:
  `tests/unit/timeline tests/unit/renderer` → 350 passed, 50 failed (all
  50 in `test_fingerprint.py`, all with the SAME pre-existing
  `TypeError: compute_render_fingerprint() missing 1 required
  keyword-only argument: 'sfx_diegetic_shot_carry_s'` - confirmed by
  grepping every failure's error line, not merely counting). Wider
  sweep `tests/unit/timeline tests/unit/renderer tests/unit/planners
  tests/unit/workflow tests/unit/script tests/unit/api` → 703 passed,
  56 failed - the same 50 in `test_fingerprint.py`, the 5 documented
  A15-related failures in `test_sfx_overlays_diegetic.py`, and the 1
  documented cross-project `test_director_planner.py::
  test_every_attempt_is_recorded_as_an_llm_call` pollution bug (56 = 50
  + 5 + 1, all three sources named in the brief itself). Zero new
  failures anywhere in either sweep.
- `black --check`: 6 files (3 touched production, 3 new test files)
  unchanged after one auto-format pass (`parallax.py`/
  `test_parallax.py` needed reformatting on first write; both re-run
  clean). `ruff check`: clean after two fixes - `UP031` (percent-format
  string in `sample_key_colour`, changed to an f-string) and an
  unsorted import block in `test_parallax.py` (`--fix`). `mypy` on the
  three touched/new production files: `Success: no issues found in 3
  source files`.

**Verification (exact commands, run from `backend/`):**
```
../.venv/Scripts/python.exe -m pytest tests/unit/renderer/test_parallax.py tests/unit/renderer/test_fingerprint_parallax.py tests/unit/timeline/test_shot_layers.py -q
  -> 68 passed in 1.16s
../.venv/Scripts/python.exe -m pytest tests/unit/timeline tests/unit/renderer -q
  -> 50 failed, 350 passed in 18.99s   (all 50 failures in test_fingerprint.py, same pre-existing TypeError)
../.venv/Scripts/python.exe -m pytest tests/unit/timeline tests/unit/renderer tests/unit/planners tests/unit/workflow tests/unit/script tests/unit/api -q
  -> 56 failed, 703 passed in 51.70s   (50 test_fingerprint.py + 5 test_sfx_overlays_diegetic.py + 1 test_director_planner.py, all pre-existing/documented)
../.venv/Scripts/python.exe -m black --check app/schemas/timeline.py app/renderer/parallax.py app/renderer/fingerprint.py tests/unit/timeline/test_shot_layers.py tests/unit/renderer/test_parallax.py tests/unit/renderer/test_fingerprint_parallax.py
  -> 6 files would be left unchanged
../.venv/Scripts/python.exe -m ruff check app/schemas/timeline.py app/renderer/parallax.py app/renderer/fingerprint.py tests/unit/timeline/test_shot_layers.py tests/unit/renderer/test_parallax.py tests/unit/renderer/test_fingerprint_parallax.py
  -> All checks passed!
../.venv/Scripts/python.exe -m mypy app/schemas/timeline.py app/renderer/parallax.py app/renderer/fingerprint.py
  -> Success: no issues found in 3 source files
```
No `PYTEST_TRUNCATE_DB` was set; `--noconftest` was never used; `make
test` and the full suite were never run, per the task brief. The
pre-existing failures above were identified by inspecting each one's
actual error line/message (not just counted), confirming every single
one is the SAME known root cause documented in the brief - none is a
new failure shape this pass introduced.

**Effects / notes for the reviewer:**
- **§3.4's one-time fingerprint leak recurs here, exactly as documented
  for `frame_aspect`/`grade_style`/`caption_romanization_attempted`.**
  `Shot.layers` is a new field with a default (`[]`), so
  `timeline.model_dump(mode="json")` now includes `"layers": []` for
  every existing shot on every existing project, changing
  `compute_render_fingerprint`'s output once. This is on top of the new
  `"shot_layers"` payload entry added deliberately (also a one-time,
  unconditional change, same shape as `shot_focal`). Both are the
  documented, harmless, bounded kind: output is byte-identical (nothing
  reads `.layers` anywhere in the render path yet - proven by the
  source-inspection tests above), only the cache key moves, and every
  project re-encodes once on its next render. Flagged here so it does
  not read as a bug when it fires.
- **A `CameraMovement.PARALLAX` shot with empty `layers` is a real,
  reachable, useless state, and F2 does not guard against it.** Since
  `ShotCameraOutput.movement` shares the SAME `CameraMovement` enum the
  Shot Planner's structured output already uses, adding this value makes
  it immediately selectable by that LLM call with zero other code
  changes - but `ShotPlanOutput` has no `layers` field, so nothing can
  ever populate `Shot.layers` through the normal planning pipeline in
  this slice. A shot could legally carry `movement=PARALLAX` with
  `layers=[]` today. Not guarded against at the schema level (no
  precedent for coupling `camera.movement` to another field that
  strictly - `SPLIT_FRAME` with an empty `secondary_prompt` already
  degrades silently to the static path rather than erroring), and not
  reachable through any code this pass wired, but worth flagging before
  a future task extends `ShotPlanOutput`/`shot_planner/v1.md` to author
  `layers` - at that point the Shot Planner prompt will need explicit
  guidance on when to reach for `PARALLAX`, the same way `split_frame`
  and `punch_in` already get dedicated guidance in `shot_planner/v1.md`.
- **`shot_planner/v1.md` and `app/planners/shot/schemas.py` were
  deliberately NOT touched**, despite being on the brief's own "read
  first" list. Reading them confirmed `CameraMovement` reaches the LLM
  schema automatically (no wiring needed for the enum value itself) but
  `ShotLayer` has no authoring path at all - filling that in is
  substantial new planner scope (a new sub-schema, `_to_domain_shot`
  changes, prompt guidance under the artefact-noun-free discipline
  §4.10 enforces) that F2's own numbered bullet list does not ask for.
  Flagging the boundary explicitly rather than silently expanding scope.
- **The keyed-fraction guard's `_pixel_distance` is a documented
  approximation of ffmpeg's own `colorkey` filter, not a bit-exact
  reimplementation** - normalised Euclidean RGB distance, matching the
  probe's own `_KEY_SIMILARITY`/`_KEY_BLEND` constants for the
  *threshold*, but not claiming to reproduce ffmpeg's internal colorkey
  math pixel-for-pixel. This is stated in the function's own docstring;
  it is adequate for a sanity guard on the keyed FRACTION (§4.5's actual
  ask) but would need real ffmpeg-side verification before anyone
  trusted its exact number for something more precise.
- **No per-project layer budget cap (§4.3).** The plan names this as
  needed once real parallax ships ("a careless planner could ask for six
  layers on every shot"), but it is a caution in §4, not one of F2's
  own six numbered scope bullets in §2.2 - not built, flagged rather
  than silently skipped.
- **§8.1's substrate-crop fix was read and deliberately NOT attempted**,
  per both the plan's own "PREREQUISITE FOR F2" framing and the task
  brief's explicit DO-NOT instruction (deferred at the user's request).
  Nothing in this pass produces or judges a real layered render, so the
  artefact §8.1 predicts (an off-white margin around a keyed subject)
  was never encountered - it remains a known, documented risk for
  whoever next renders a real parallax shot, not something this slice
  needed to work around.

**What is NOT done:**
- `app/renderer/slideshow.py`/`app/workflow/steps/render.py` wiring -
  `parallax.py` is not called from anywhere in the render pipeline yet.
- The Shot Planner's authoring path for `ShotLayer` (`ShotPlanOutput`,
  `shot_planner/v1.md` guidance for `PARALLAX`/layers) - not built, see
  "Effects" above.
- F3 (three layers, per-layer placement tuning), F4 (fragment-anchored
  timed entry), F5 (element transforms) - untouched, explicitly out of
  scope.
- The §4.3 per-project layer budget cap - not built, flagged above.
- §8.1's substrate crop - deliberately not attempted, per the DO-NOT
  list.
- No human pass of any kind (no render exists to watch) - F2's own
  "does it read as animation, or as a moving photograph?" gate is
  entirely outstanding, same as F1's gate was before P-IF-F1-fixes.
- `render.py`/`fragments.py` - untouched, both pre-existing uncommitted
  A15 work on this branch, out of scope per the brief.

### P-IF-F2a — Both ends connected: the planner can author layers, the renderer composites them (2026-09-05)

**Scope executed:** exactly §8.5's three bullets - the Shot Planner's
authoring path for `Shot.layers` (`ShotPlanOutput.layers`, the
`illustrated_risograph.md` prompt wording, and `_make_validator`'s
mirror of the `split_frame`/`secondary_prompt` rule), the composition-
pass wiring (`app/renderer/slideshow.py` dispatches a `parallax` shot
into `app/renderer/parallax.py`, `app/workflow/steps/render.py` threads
resolved layer images/hashes through to it), and the §4.3 per-project
layer budget cap. `render.py` was confirmed clean first (`c54a98a`
committed the A15 work this branch used to carry uncommitted) before it
was touched. `parallax.py` itself is untouched - every line below wires
or calls its existing functions, none rewrite them. §8.1's substrate
crop remains deliberately unattempted (DO-NOT list); no external API
call, no image generated, no project rendered, nothing committed.

**Changes:**
- `backend/app/planners/shot/schemas.py:11` - `LayerRole` import.
  `:28-39` - `ShotLayerOutput` (`role`, `prompt`) - narrower than
  `ShotLayer` itself: `asset_plan`/`drift_x`/`drift_y`/`scale` stay
  resolver/Asset-Planner concerns, the same way `Shot.asset_plan` is
  never on `ShotPlanOutput` either. `:91` - `ShotPlanOutput.layers:
  list[ShotLayerOutput]`, required, no `minItems` (this file's own
  strict-mode rule - quantity checks live in `_make_validator`).
- `backend/app/planners/shot/planner.py:50,52-53` - `LayerRole`/`Shot`/
  `ShotLayer` imports. `:721-765` - `_make_validator`'s new block, same
  shape as the `split_frame`/`secondary_prompt` pair immediately above
  it: a `parallax` shot needs exactly 2 layers in `[background,
  subject]` order with non-empty prompts; a non-parallax shot with any
  `layers` is rejected the other direction. A hard failure via
  `run_structured_with_repair`'s retry (not a silent downgrade) -
  unlike the three `_cap_*` passes below, the model already had every
  fact it needed in this same call. `:806-857` (`_to_domain_shot`),
  `:856` - `layers=[ShotLayer(role=layer.role, prompt=layer.prompt)
  for layer in s.layers]`; `asset_plan` stays `None` per layer, same
  reason the
  shot's own `asset_plan` two lines up is `None` (not authored by this
  planner - later scope, per F2's own log). `:447-500` -
  `_cap_parallax_layers(planned_scenes, *, max_layers)`: §4.3's budget,
  fourth instance of the `_cap_glitch_transitions`/`_cap_text_cards`/
  `_cap_sfx_cues` shape (the Shot Planner runs once per scene and
  cannot see another scene's layer spend) - clears a whole shot's
  `layers` (never a lone layer; `parallax.py`'s builder rejects
  anything but exactly two) once the running total would exceed the
  cap, in scene/shot order, logging
  `shot_planner.parallax_layer_budget_exceeded_downgrading`. `:876-877`
  (`plan()` signature) - new required `max_parallax_layers_per_project:
  int` parameter. `:981` - wired into the post-gather pipeline beside
  its three siblings.
- `backend/app/prompts/shot_planner_styles/illustrated_risograph.md:34-38`
  - the parallax bullet: a `parallax` shot needs exactly two `layers`
  (`background` then `subject`), the subject "isolated on one perfectly
  even, solid magenta field that fills the frame completely, edge to
  edge - flat, shadowless lighting, and the figure as the sole content
  in the frame" (the probe's own working phrasing, generalised to the
  positive form §4.10 requires - "shadowless"/"sole content" rather
  than "no shadow"/"no other object"). Names no artefact noun, no
  negation - `test_the_whole_fragment_names_no_artefact_or_negation_noun`
  (existing, unmodified) still passes over the whole file, comment
  included.
- `backend/app/core/config.py:503-519` - `max_parallax_layers_per_project:
  int = 10` (five two-layer shots, 40c) - a reasoned starting point, not
  measured, same epistemic status as `_DEAD_STOP_CEILING_MULTIPLIER`.
- `backend/app/script/styles.py:652` (`ConstraintBundle` gains the
  field), `:747-755` (`resolve_constraint_bundle` computes it with the
  IDENTICAL `sqrt(duration_ratio)` shape `max_video_shots_per_project`
  already uses two lines above), `:765` (returned). One function, read
  by generate_timeline.py's call site - never a band field at a use
  site (the R1 lesson `resolve_sfx_whoosh_enabled` cites).
- `backend/app/workflow/steps/generate_timeline.py:323` -
  `ShotPlanner(...).plan(...)` gains
  `max_parallax_layers_per_project=bundle.max_parallax_layers_per_project`.
- `backend/app/renderer/slideshow.py:72-79` (parallax.py imports),
  `:81` (`CameraMovement`/`LayerRole`/`ShotLayer` added to the timeline
  import) - `:527-546` `should_composite_parallax`, the parallax mirror
  of `should_composite_split`'s own degrade-on-missing-input shape:
  `False` unless movement is `parallax`, `layers` is exactly
  `[background, subject]`, both paths are resolved, and both are
  stills. `:568-573` (`_encode_or_reuse_shot_stream` gains
  `layer_srcs`/`layer_probes`/`layer_asset_hashes`), `:591-623` (the
  §4.5 guard: sample the subject's key from its own delivered bytes,
  check the keyed fraction, and on `ParallaxKeyGuardError`/`OSError`/
  `ValueError` log `render.parallax_guard_failed_degrading` and fall
  back to the plain single-image path - the same per-shot failure
  isolation `GenerateDiegeticSfxStep`'s own docstring states for one
  failed diegetic cue: "that shot simply renders with no diegetic
  sound," here "that shot simply renders with no parallax"), `:624-632`
  (`layer_asset_hashes` reaches `compute_shot_stream_fingerprint` only
  when `parallax` is actually true - a guard failure therefore
  fingerprints identically to a plain shot with the same `src`, so it
  reuses that cache rather than minting a new one), `:647-667` (the
  filter-graph branch: `-loop 1 -t {duration_s}`, not `-framerate` +
  `tpad` - see the inline comment for why `parallax.py`'s ported filter
  shape needs the probe's own looping-input convention, and why that
  reintroduces zero risk of this module's own documented 185-shot
  memory blowup, since §4.3's cap bounds how many shots this path ever
  runs for). `:949-951`/`:971-973` (`_render_run_two_pass` threads the
  three params to each call), `:1015-1017`/`:1057-1082` (`_render_run`
  gains `parallax_in_run`, the same "forces the per-shot cached path"
  role `split_in_run` already plays, since the plain single-pass batch
  path has no parallax support), `:1286-1293` (`_render_or_reuse_run`
  passes `layer_content_hashes` into `compute_run_fingerprint`),
  `:1349-1436` (`render_timeline` gains `shot_layer_images`, resolves
  each shot's layer PAIR through `probe_media`/`ensure_still_image`
  exactly like `shot_secondary_images` - skipping the whole pair, never
  a lone layer, the moment either plane is a motion clip - and computes
  `layer_content_hashes` from the resolved bytes).
- `backend/app/workflow/steps/render.py:229-244` - `shot_layer_images`/
  `layer_content_hashes`, declared and threaded through but populated
  `{}` for every shot today: `ShotBindingModel` carries no per-layer
  slots and no planner authors `ShotLayer.asset_plan` (later scope, per
  F2's own log) - see "What is NOT done" below. `:442` -
  `layer_content_hashes` reaches `compute_render_fingerprint`. `:471` -
  `shot_layer_images` reaches `render_timeline`.

**Test files (new):**
- `backend/tests/unit/planners/test_shot_planner_parallax_layers.py`
  (6 tests) - `ShotPlanOutput.layers` both directions (a `parallax`
  shot without 2 layers / with layers in the wrong role order / with an
  empty layer prompt all fail loudly; a non-parallax shot with layers
  fails loudly the other way; a well-formed pair lands on the domain
  `Shot` with `asset_plan=None` per layer; a non-parallax shot keeps
  `layers=[]`) - through the real `ShotPlanner.plan()` entry point via
  `FakePlanningProvider`, the same shape `test_split_frame_without_
  secondary_prompt_is_rejected` already uses.
- `backend/tests/unit/planners/test_shot_planner_parallax_layer_cap.py`
  (6 tests) - `_cap_parallax_layers` pure-function tests, same shape as
  `test_shot_planner_sfx_cue_cap.py`: under-cap is byte-identical (not
  even `model_copy`'d); a project with no layers is untouched; excess
  layers are cleared keeping the FIRST shots, never a lone layer left
  behind; **the budget is enforced project-wide, not per scene** (three
  scenes each individually within budget still get the third cleared);
  the log record's four fields are asserted exactly.
- `backend/tests/unit/renderer/test_parallax_dispatch.py` (8 tests) -
  `should_composite_parallax`, pure, no ffmpeg: the well-formed case,
  wrong movement, no layers, three layers (F3, not F2a), wrong role
  order, a missing layer path, no paths at all, and a motion clip on
  either plane - every one degrades to `False` rather than raising,
  mirroring `test_split_screen.py`'s own `test_should_composite_
  requires_two_stills_and_split_movement`.
- `backend/tests/integration/test_render_parallax.py` (3 tests, real
  ffmpeg, no DB) - mirrors `test_render_split_screen.py`'s shape
  exactly, with each shot's OWN `shot_images` entry a THIRD colour
  (red) distinct from both layers (blue background / green-on-magenta
  subject) so a test can tell from the rendered frame alone which path
  actually ran: (1) both layers composite over the shot's own image -
  blue and green both present, no magenta (the key was removed), no
  red (the plain path did NOT run); (2) a subject plate with nothing to
  cut out (§4.5's "ate the subject" failure) degrades to the shot's own
  red image and logs `render.parallax_guard_failed_degrading`, never
  killing the render; (3) a `parallax` shot with no resolved layer
  images at all renders as its own plain image, the same documented
  degrade `test_split_frame_without_a_second_still_is_a_static_shot`
  already proves for split-screen.
- `backend/tests/unit/timeline/test_shot_layers.py` - F2's own three
  isolation tests narrowed to the two modules F2a's brief named as
  untouched (`ken_burns.py`/`split_screen.py`,
  `test_untouched_composition_modules_do_not_reference_shot_layers`)
  plus a new test asserting the FLIP side
  (`test_render_py_and_slideshow_now_reference_shot_layers`) - a fact
  about the code, not merely this log entry.

**Test files (fixed, mechanical, per the brief's task 4):**
`backend/tests/unit/renderer/test_fingerprint.py` - its one shared
`_fingerprint()` helper (all ~50 call sites go through it) was missing
`sfx_diegetic_shot_carry_s`; added once, all 50 fixed. Also updated (new
required field, not a behaviour change): `_shot()`/`_shot_output()`
factories in `test_shot_planner.py`, `test_shot_planner_context.py`,
`test_shot_text_cards.py`, and `tests/integration/
test_generate_timeline_real.py` all gained `layers=[]`; every
`ShotPlanner(...).plan(...)` call site in `test_shot_planner.py`/
`test_shot_planner_context.py` gained
`max_parallax_layers_per_project=100`.

**Measured:**
- Debugging note, not a defect in shipped code: the FIRST working
  version of the parallax filter-graph branch staged the two layer
  inputs with `-framerate {fps} -i` (matching `split`'s own staging)
  and produced a 1-frame, 0.04s output regardless of `shot.duration_s`
  - `overlay=shortest=1` truncates to the shortest INPUT stream, and an
  image2 input without `-loop 1` decodes exactly one frame. Fixed by
  staging with `-loop 1 -t {duration_s}` instead (`parallax_probe.py`'s
  own convention, ported alongside its filter shape) - confirmed by
  `ffprobe` on a real encode: `nb_frames` 1 -> 37 at 24fps/1.5417s,
  matching `shot.duration_s=1.5` within one frame.
- The real composite: a 640x480 blue background plus a 640x480
  magenta-keyed plate with a green rectangle, rendered at 240x320/24fps,
  sampled at t=0.7s - `Image.getcolors` on the extracted frame: 46848px
  blue, 28216px green, a few hundred anti-aliased edge pixels, ZERO
  magenta and ZERO red (the shot's own distractor colour) above noise.
- The guard-degrade path: an all-magenta subject plate (nothing to key
  out) - `check_keyed_fraction` raises "ate the subject" exactly as
  `test_parallax.py` already proved in isolation; the integration test
  confirms the CALLER catches it, logs
  `render.parallax_guard_failed_degrading`, and the extracted frame
  shows only the shot's own red image, never a half-built composite and
  never a raised exception reaching `render_timeline`'s caller.
- Test counts: `test_shot_planner_parallax_layers.py` +
  `test_shot_planner_parallax_layer_cap.py` +
  `test_parallax_dispatch.py` -> 20 passed. `test_render_parallax.py`
  (real ffmpeg) -> 3 passed. `test_fingerprint.py` -> 65 passed (was 50
  failed / 15 passed). `test_shot_layers.py` -> 20 passed (was 21; F2's
  3-way parametrize narrowed to 2, its `render.py`-only test replaced
  by one covering both `render.py` and `slideshow.py`).
- Full sweep `tests/unit/timeline tests/unit/renderer tests/unit/
  planners tests/unit/workflow tests/unit/script tests/unit/api` ->
  **772 passed, 6 failed, 0 new**: 5 in `test_sfx_overlays_diegetic.py`
  (pre-A15 dissolve-swoosh behaviour, explicitly left red per the
  brief) and 1 in `test_director_planner.py::test_every_attempt_is_
  recorded_as_an_llm_call` (documented cross-project DB pollution) -
  both named in the brief as known-remaining, neither touched.
- A broader, NOT-required sweep also touching `tests/integration`
  turned up 20 unrelated failures (narration persistence/cache,
  workflow-trigger orphan reclaim, draft retention, a live-provider
  music test) - none in any file this slice touched, none mentioning
  `layers`/`parallax`/fingerprint kwargs, and reproducing the same
  cross-project DB-pollution shape the brief already documents for
  `test_director_planner.py`. Re-run narrowly instead: every render-
  pipeline integration file (`test_render_parallax.py`,
  `test_render_split_screen.py`, `test_render_determinism.py`,
  `test_render_ken_burns.py`, `test_render_two_pass.py`,
  `test_render_run_cache.py`, `test_render_motion_clips.py`) together
  -> 28 passed, confirming this slice caused none of the 20.
- `black --check`/`ruff check` clean on every touched file after one
  `ruff --fix` (an unsorted import in `test_parallax_dispatch.py`).
  `mypy` on the touched production files: no new errors.

**Verification (exact commands, run from `backend/`):**
```
../.venv/Scripts/python.exe -m pytest tests/unit/renderer/test_fingerprint.py -q
  -> 65 passed
../.venv/Scripts/python.exe -m pytest tests/unit/planners/test_shot_planner_parallax_layers.py tests/unit/planners/test_shot_planner_parallax_layer_cap.py tests/unit/renderer/test_parallax_dispatch.py -q
  -> 20 passed
../.venv/Scripts/python.exe -m pytest tests/integration/test_render_parallax.py -q
  -> 3 passed
../.venv/Scripts/python.exe -m pytest tests/unit/timeline/test_shot_layers.py -q
  -> 20 passed
../.venv/Scripts/python.exe -m pytest tests/unit/planners/test_shot_planner.py tests/unit/planners/test_shot_planner_context.py tests/unit/planners/test_shot_text_cards.py tests/unit/planners/test_illustrated_risograph_fragment.py -q
  -> 36 + 14 passed (both files unaffected beyond the new `layers=[]`/cap kwarg)
../.venv/Scripts/python.exe -m pytest tests/unit/timeline tests/unit/renderer tests/unit/planners tests/unit/workflow tests/unit/script tests/unit/api -q
  -> 6 failed, 772 passed (5 test_sfx_overlays_diegetic.py + 1 test_director_planner.py, both pre-existing/documented, neither touched)
../.venv/Scripts/python.exe -m pytest tests/integration/test_render_parallax.py tests/integration/test_render_split_screen.py tests/integration/test_render_determinism.py tests/integration/test_render_ken_burns.py tests/integration/test_render_two_pass.py tests/integration/test_render_run_cache.py tests/integration/test_render_motion_clips.py -q
  -> 28 passed (targeted render-pipeline integration re-run, after a broader tests/integration sweep surfaced 20 unrelated, pre-existing DB-pollution failures elsewhere - see Measured above)
```
No `PYTEST_TRUNCATE_DB` set; `--noconftest` used only for the pure
planner/renderer files that support it (no DB fixture). `make test` and
the full suite were never run, per the brief.

**Effects / notes for the reviewer:**
- **Production behaviour is unchanged for every project today.**
  `shot_layer_images`/`layer_content_hashes` are `{}` in `render.py`
  because nothing yet resolves a real image for `ShotLayer` (no
  `ResolveAssetsStep` support, no Asset-Planner authoring of
  `ShotLayer.asset_plan`) - so `should_composite_parallax` returns
  `False` for every shot in production, and every existing style stays
  byte-identical, same as F2's own claim. What is NEW and real: the
  Shot Planner CAN author `layers` for `illustrated_risograph` now, and
  the render pipeline WILL composite them correctly, guard them, and
  fingerprint them the moment a later slice supplies real layer image
  paths - proven directly with synthetic fixtures in `test_render_
  parallax.py`, not merely argued.
- **`-loop 1 -t` for parallax's two inputs only, not a reversion for
  everything else.** This module's own docstring explains why STATIC/
  SPLIT_FRAME abandoned looping inputs (10.6 GB resident at 185 shots);
  `parallax.py`'s ported filter shape has no per-input `tpad` hold
  (correctly - it was ported unmodified from a probe that used `-loop
  1 -t` throughout), and §4.3's own cap is precisely what keeps this
  reintroduction bounded to a handful of shots per project rather than
  every shot. If a future slice raises the layer cap by an order of
  magnitude, revisit whether this still holds.
- **R2 checked, nothing newly uncovered.** `subject_key` is sampled
  from bytes already in `layer_asset_hashes`/`layer_content_hashes` (no
  separate fingerprint entry needed, same as §1.5 states); `parallax`
  itself is a deterministic function of `shot.camera.movement`/
  `shot.layers` (already hashed) and path/kind presence (reflected by
  whether a `layer_*hashes` entry exists for that shot at all).

**What is NOT done:**
- **Real layer image resolution.** `ShotBindingModel` gained no columns
  and `ResolveAssetsStep`/`AssetPlanner` were not touched - `ShotLayer.
  asset_plan` still has no authoring OR resolution path, exactly as F2's
  own log flagged as later scope. This is why production stays inert;
  wiring the DISPATCH ahead of a real media source was the brief's own
  explicit shape (§8.5: "the composition-pass wiring in render.py,"
  listed as F2a scope, separately from resolving real files).
- No human pass (still nothing to render for real - §8.1's substrate
  crop is still the prerequisite for judging any real layered output).
- F3 (three layers), F4 (timed entry), F5 (element transforms) -
  untouched, explicitly out of scope.
- §8.1's substrate crop - deliberately not attempted.

---

## 8. F1 CLOSED — human pass given 2026-09-04

**Pacing signed off by the user on the second render** (`b521aacc-7afc-4ea9-a953-89a843f738df`,
`tmp/jiho-riso-v2/jiho-30s-risograph-v2.mp4`, 25.3 s, 720×1280, 47¢).

Two renders of the same 28 s / 9-shot excerpt of the Ji-ho script:

| | v1 (`7df10f6c`) | v2 (`b521aacc`) |
|---|---|---|
| character continuity | **failed** — boy, then a girl with a bob | **holds** — same boy, hair, backpack, all shots |
| narration | 1.0×, "too slow" | 1.15× → 25.3 s, **signed off** |
| paper border | present, masked by the Ken Burns crop | present, **3 of 5 sampled frames show it** |
| Director's `visual_style` | photographic ("observational documentary") | illustrated, no medium words |
| Director's `constraints` | provenance ("licensed footage", "consent") | depiction-only, frame-checkable |
| spend | 52¢ | 47¢ |

**What F1 proved:** the format works, and **facelessness plus a Director-authored figure
block gives real character continuity with no reference images, no LoRA, and no
persisted-character machinery** — the entire §1.1 capability turned out to be
unnecessary for this format, exactly as the Verdict predicted.

**What F1 did NOT prove:** that one world holds across a *full* 53-shot film. Nine
shots is a much better sample than twelve probe images, and it is not 53.

### 8.1 F1a — Deterministic substrate crop ⛔ PREREQUISITE FOR F2

**Prompt wording has now failed this twice** (§1.7, then `P-IF-F1-fixes`), and §4.10
records why a third rewording is a poor bet. The token needs the words "print" and
"paper" for the look; the model periodically renders paper as an object with edges.

**Fix deterministically, not linguistically:** for a `GENERATION_ONLY` style, request
the image slightly oversized and centre-crop it (~4%) when persisting, so any
substrate margin falls outside the frame by construction. Style-scoped, no RNG,
derived from nothing but the style — so it cannot drift, and unlike a Ken Burns crop
it also protects a STATIC shot.

**⚠ Why this blocks F2, not merely precedes it.** At the frame edge a border is ugly
but survivable. Once F2 composites a subject layer over a background, the subject's
margin is **off-white, not the key colour**, so `colorkey` will not remove it — it
composites as a pale rectangle floating inside the frame, around the character. That
is a worse artefact than the one being fixed, and it would make F2's own human pass
un-judgeable. Deferred at the user's request 2026-09-04; **do it before any layered
render is judged.**

### 8.2 Palette drifts shot to shot — undecided

The token declares three spot colours. Delivered frames carry four or five, and which
ones vary: one still went blue/yellow, another teal/orange/yellow. The *texture* of the
world holds; the *hue* does not. At 9 shots it reads as print variance; across 53 it may
read as inconsistency rather than design. **Not yet decided whether this is a prompt fix
or an accepted characteristic** — needs a viewing at length, which F1 did not provide.

### 8.3 ⚠ `storage_root` is CWD-relative — a live landmine, cost a render

`settings.storage_root` is `Path("./storage")`, and `narration.local_path` /
shot-binding paths are persisted **relative**. So where a project's files live depends on
the directory the server was launched from.

**Measured:** v1's render failed with *"timeline has a selected music track … but its
audio file is missing on disk"*. Cause: the planning run was served from the repo root
(music → `storage/`) and the render from `backend/` (looked in `backend/storage/`). The
project was split across two trees. There are **15 project directories in one and 60 in
the other**, so this predates today by a long way.

`make run` uses `--app-dir backend` *from the repo root* → repo-root `storage/`. Launching
from inside `backend/` → `backend/storage/`. **The Makefile and the habit disagree**, which
is very likely how the split started.

**Fix:** anchor `storage_root` absolutely (to the package or repo dir), never CWD. Carries
a migration question — 609 narration rows and every shot binding hold relative paths — so
it wants its own slice. Interim: always launch the same way.

### 8.4 ⚠ The narration cache is GLOBAL, so a purge can break another project

`narration_repository.py`'s own docstring: *"`content_hash` dedup is deliberately GLOBAL,
not per-project"*, and `narration.py:193` notes a resolved path may be *"another project's
path after a cache hit"*.

**Measured:** v1 had **zero narration rows of its own** and made **zero TTS calls**, yet
rendered with audio — every scene hashed identically to an abandoned earlier project and
resolved to *its* files. Consequences:

- narration cost 0¢ (correct, and good);
- anything querying narration **by `project_id` sees nothing**, so a project can look
  silent while its render has sound;
- **the render depends on another project's files staying on disk.**

That last point changes the purge script discussed earlier (see the user's
`project_purge_test_projects` note): deleting a project's storage by `project_id` can
silently break a *different* project's render. **A purge must check content-hash
reachability across all projects before unlinking any narration file**, not just filter by
project id.

### 8.5 F2a — Parallax is BUILT BUT NOT REACHABLE ⛔ required before any layered render

`P-IF-F2` delivered the primitives correctly — `Shot.layers` defaulting to empty,
the §6 Q1 mutual-exclusion validator, `renderer/parallax.py` ported from the
proven probe, the §1.5 sampled key colour, the §4.5 keyed-fraction guard, and
fingerprint coverage (including a real R2 gap it found: `compute_shot_stream_
fingerprint` hand-picks fields, so `layers` needed an EXPLICIT entry rather than
riding the document dump).

**But neither end is connected, so nothing can produce a parallax shot today.**
Verified 2026-09-04 by grepping every call site:

1. **The planner cannot author layers.** `app/planners/shot/schemas.py::ShotPlanOutput`
   has no `layers` field, so the Shot Planner has no way to populate one — even
   though `CameraMovement.PARALLAX` now exists for it to select. A shot may
   therefore legally carry `movement=PARALLAX` with `layers=[]`: a reachable
   no-op. (Not guarded; `SPLIT_FRAME` with an empty `secondary_prompt` already
   degrades the same silent way, so there is no precedent for that kind of
   cross-field enforcement — but the asymmetry is worth removing rather than
   matching.)
2. **The renderer never calls it.** `parallax.py` is standalone and unit-tested
   exactly as `ken_burns.py` and `split_screen.py` are, but no composition pass
   references `.layers`.

**Both gaps were caused by the brief, not by the work.** F2's agent was
instructed not to touch `render.py` because uncommitted A15 diegetic-SFX work
lives there on this branch — and `render.py` is precisely where the composition
pass wiring belongs. The planner schema was simply not in the six numbered
bullets. The agent reported both plainly instead of half-wiring around the
constraint, which was the right call.

**F2a's scope, then:**
- `ShotPlanOutput.layers` plus the shot-planner prompt wording that authors a
  background/subject pair (subject on a key colour), remembering §4.10: the whole
  fragment reaches the model, so name no artefact noun and use no negations;
- the composition-pass wiring in `render.py`, which needs the A15 work either
  committed or coordinated first — **check with the user before touching that
  file**;
- §4.3's per-project layer budget cap, in the shape of
  `max_video_shots_per_project`, so a planner cannot ask for six layers on every
  shot (1 layer = 4¢, 3 = 12¢).

**And §8.1 still gates the visual pass**: until the substrate crop lands, a
composited subject layer carries an off-white margin that `colorkey` will not
remove, so it appears as a pale rectangle inside the frame. Wire F2a if you like,
but do not judge parallax before F1a.
