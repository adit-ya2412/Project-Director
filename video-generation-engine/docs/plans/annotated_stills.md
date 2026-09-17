# Annotated stills — marks, leader lines, and labels on a picture

**Status:** PLAN, **and the spike is BUILT and watched** (§0,
2026-09-14). No production code written; `compositor/src/
AnnotationSpike.tsx` is a throwaway dev harness.
**Written 2026-09-13**, from the user's own description rather than a
reference file: *"some historical figure, his face is marked in a red
circle with name on an arrow"*, and *"a video on discontinued Tata
models, where the gate is highlighted in red with text appearing like
some handwritten report"*.

**This is a DEVICE FAMILY, not a style.** That distinction is the whole
reason it is cheap. It composes onto `documentary_archival` for long
form and `retention_fast` for short form; it forks nothing and replaces
nothing.

Sibling plan `marble_strip_card_style.md` describes a *text-led card*
style from a supplied reference reel. It is a separate, deferred thing.
Where the two disagree, this plan wins for the user's stated content —
see §1.1.

---

## Verdict up front

**Two of the three hard parts already exist, and the architectural
problem that dominated the card-style plan does not arise here at all.**

- **Where to point** is solved: `assets/focal.py` + `focal_check.py`
  already run a vision call that returns a normalised `(x, y)` for an
  image's subject, persisted as a content-hash sidecar, audited as an
  `llm_call` row, with a **human per-shot override that outranks
  vision**.
- **Where to land the label** is solved: `renderer/caption_placement.py`
  (K17) already finds the calmest free box in a frame by luma standard
  deviation and already excludes occupied overlay rectangles.
- **Z-order is already correct.** An annotation belongs *on top of* the
  picture. The full-film alpha overlay composited last
  (`render.py:887-904`) — fatal for the card style's
  headline-behind-subject device — is exactly right here.

⚠ **"There is no §4-style decision to make" was the original verdict and
it no longer holds.** Wanting the shot to MOVE reintroduces one — see
**§0.5**, written after the user watched the fast spike and called it
dull. The choice is now punch vs. architectural simplicity.

The genuinely new work is a positional payload resolved at render, a
vision call for *non-subject* regions, three Remotion components, and
one direction rule about motion (§5.1).

**One real catch:** Ken Burns moves the picture under a fixed overlay,
so a circle drifts off the face. §5.1 turns that into a direction rule
rather than an engineering problem, at no cost.

---

## 0. Spike — built and rendered 2026-09-14

**The device works. It was built and watched before any task below was
started.**

`compositor/src/AnnotationSpike.tsx` + a dev `Composition` in
`Root.tsx`. Renders 10s at 720×1280 through the **real** compositor
(`npx remotion render`, ProRes 4444, the same invocation
`compositor.py` makes). Output: `tmp/annot-spike/annotation_demo.mp4`,
frame strip `strip2.png`.

Three annotations stage in over 10s on a real project asset
(`backend/storage/14191ca3-…/assets/a4199410….jpg`). **Annotation 1's
coordinates are that asset's real focal sidecar value**
(`focal_source="vision"`, 0.47, 0.31) — the Tier-1 path, which already
ships. Annotations 2 and 3 are hand-placed, standing in for Tier 3.

### 0.1 What it proved

- Mark → leader → label, staged, on a static still **reads as a
  marked-up photograph**, which is the thing. §5.2's staggering is
  doing the work; an early build with a faster stagger read noticeably
  more like a graphic pasted on.
- §5.4's imperfect, overshooting stroke is worth its ten lines. It is
  the difference between "software drew this" and "someone marked this".
- §5.1 (no Ken Burns) costs nothing and looks right.

### 0.2 What it found — three things that change the plan

**1. A deterministic PRNG is mandatory, not a nicety.** `Math.random()`
re-seeds every frame, so the wobble would crawl and the mark would
boil. The spike uses a seeded `mulberry32`. Any production component
must do the same.

**2. K17 label placement (N4) is REQUIRED, not optional.** Hand-placed
labels landed on busy pixels on **both** attempts — the first over the
face and the medals, the second still over the collar insignia and the
ribbons. Legibility, not polish, is at stake. N4 moves up: without it
the device produces text nobody can read.

**3. Prefer an ellipse over a box for Tier-1 marks.** The real vision
focal for this asset is `y=0.31`; the face centre is nearer `0.36`. So
**Tier 1 gives a usable but imprecise point** — the mark sits slightly
high and clips the cap brim. A generous ellipse absorbs that error and
still reads as "this region"; a tight rectangle would look simply
wrong. This is a direction rule earned from real data, and it would not
have surfaced from planning.

### 0.3 What is faked in the spike

Not to be mistaken for built: label positions are hand-placed (N4), and
nothing is props-driven (N7). The font is **no longer** faked — see §0.4.

### 0.5 Punch pass — 2026-09-14, and it changes the verdict

The user watched the fast spike and called it **"kind of dull"**. They
were right, and the diagnosis matters more than the fix.

**Five causes, in order of how much each cost:**

1. **Everything was linear.** `interpolate` with no easing is constant
   velocity, which reads mechanical. A marker stroke is *struck*, not
   drawn. Fixed with an expo-out (`Easing.bezier(0.16, 1, 0.3, 1)`);
   almost all the travel now happens in the first third.
2. **The label faded in.** Opacity 0→1 is the dullest entrance there
   is. Replaced with a `spring()` that overshoots and settles, sliding
   in along the leader line's own direction so it reads as *delivered
   by* the line.
3. **Nothing happened on impact.** The stroke closed and the frame just
   sat there. Added a scale pulse (1 → 1.075 → 1) on the instant the
   mark completes — this is the beat that was missing.
4. **The stroke was thin.** 5px reads as a pen. 7px reads as a marker.
5. **The picture never moved** — see below.

**§5.1 was wrong, and it was wrong in a way worth understanding.** The
rule "an annotated shot does not move" was derived from a *technical*
constraint (a fixed overlay cannot track ffmpeg's zoompan) and then
rationalised as direction. On screen it is a still that sits inert for
1.9s. In the spike the picture and the annotation live in **one
component**, so a slow push (1 → 1.045) costs nothing and the shot stops
feeling embalmed.

**The consequence: there IS an architectural decision here after all,
and the Verdict above is too optimistic.** If annotated shots move,
either

| | |
|---|---|
| **(a) Remotion owns the picture for annotated shots** | motion is free and exact, because one renderer owns picture and mark together. But those shots bypass the ffmpeg still/Ken-Burns path — the same shape as the card plan's "option B", narrowed to annotated shots only |
| **(b) Remotion mirrors ffmpeg's zoompan** | keeps the overlay architecture, but **two independent implementations of the same motion must agree to sub-pixel accuracy on every frame**, or the mark creeps off the face over 57 frames. A classic drift bug, and the failure is silent |

**Recommend (a).** The risk in (b) is not the work, it is that the bug
it invites is invisible until someone watches a specific shot.

If motion is dropped, the original verdict stands unchanged and there
is no decision to make. So this is genuinely a choice between *punch*
and *architectural simplicity* — the first honest trade-off in this
plan.

### 0.4 The label face — decided 2026-09-14: **Kalam**

The first render used `Segoe Print`, a **system** font, which
`compositor/src/font.ts` warns against by name. Seven candidates were
rendered at real size on the real photo
(`tmp/annot-spike/font_compare.png`): Segoe Print, Permanent Marker,
Caveat, Architects Daughter, Kalam, Patrick Hand, Rock Salt. All six
non-system candidates are SIL OFL, so all are vendorable.

On looks alone it is close between **Architects Daughter** and
**Kalam** — both are even, legible printed hands that sit right against
a heavy marker stroke. (Permanent Marker matches the circle's
instrument but is caps-only and shouts; Caveat is too light to survive
next to a 5px stroke; Rock Salt eats width; Patrick Hand is legible but
characterless.)

**The tiebreak is not taste, it is measured coverage.** With
`fontTools`, Devanagari glyphs in U+0900-097F:

| face | total glyphs | Devanagari |
|---|---|---|
| **Kalam** | 1026 | **94** |
| Architects Daughter | 348 | **0** |
| Patrick Hand | 515 | 0 |
| Caveat | 753 | 0 |
| Permanent Marker | 229 | 0 |

This codebase burns Devanagari captions, vendors
`NotoSansDevanagari`, and has a whole romanisation planner. **A Hindi
label in any face but Kalam is tofu.** Re-rendered with it
(`tmp/annot-spike/annotation_demo_kalam.mp4`) and it also simply reads
better than Segoe Print did.

Loaded via `FontFace` + `delayRender`, the same pattern `font.ts` uses —
bundled, never a system font, never a Google Fonts request at render.

---

## 1. What the device is

A still photograph holds. On it, in sequence:

1. a **mark** — a circle, box, or underline — draws on over a specific
   feature of the image;
2. a **leader line** extends from that mark, travelling across the
   frame;
3. a **label** appears at the far end, in a handwritten register.

Three variants, one mechanism:

| variant | mark | label | user's example |
|---|---|---|---|
| **identify** | circle on a face | a name | Lumumba, Mobutu |
| **call out** | circle/box on a part | a descriptive note | the Tata's grille |
| **enumerate** | 2-5 marks in sequence on ONE held image | short labels | countries on a map |

The third is the premium case and the best thing this device does — see
§5.5.

### 1.1 How this differs from what already exists

| | text and picture |
|---|---|
| `retention_fast` | text **over** the picture |
| `marble_strip_card_style.md` | text **instead of** the picture |
| **this** | **text pointing *at* the picture** |

The picture stays primary and the text is attached to a *location on
it*. Neither existing model does that.

---

## 2. What already exists

Verified 2026-09-13 by reading the files, not inferred.

### 2.1 Subject localisation — `assets/focal.py`, `assets/focal_check.py`

A focal point is `(fx, fy)` normalised 0-1, **a property of the image
bytes, not of `Camera`** — "same image, same subject, every style". It
is persisted as a JSON sidecar keyed by content hash
(`{hash}.focal.json`), so **no migration and no Timeline field**.

Three sources, ranked: `FOCAL_SOURCE_HUMAN` (a per-shot override upload
— *"a human stating the focal point directly… outranks a vision
answer"*, A13b) > `FOCAL_SOURCE_VISION` > `FOCAL_SOURCE_FALLBACK`
(explicit centre, **which must be logged**).

`focal_check.py` **refuses to guess**: *"there is no safe fabricated
coordinate"* — every failure returns `None` and the caller writes an
explicit fallback sidecar. Inherit that behaviour exactly; an annotation
pointing confidently at the wrong thing is worse than no annotation.

**The measured lesson to reuse (`SubjectFocal`, `providers/base.py:364`):**
asking for coordinates alone returns 0.5,0.5 every time. Forcing the
model to **name the subject and describe its position in words BEFORE
emitting numbers** produces real, varied answers. *"Keep the field order
— it is the ordering of a structured response that does the work."*
Any new region-localisation call (N2) must keep that shape.

### 2.2 Label placement — `renderer/caption_placement.py` (K17)

Already finds the calmest free candidate box using Rec. 601 luma
**population** standard deviation, resolved once at render from the
plate map, and **already excludes occupied `OverlayCue.band`
rectangles** so two overlays cannot share pixels. This is precisely the
"run a long line out to clear space" problem, already built and tuned.

### 2.3 Timing — `EmphasisCue.anchor_fragment` + `offset_s`

A fragment index authored by the planner; seconds resolved from real
alignment by `resolve_emphasis_cue_offsets`. Existing, shipped.

### 2.4 The compositor seam

Props → JSON → `npx remotion render Emphasis` → **ProRes 4444 with real
alpha** → one `overlay=0:0`. Device dispatch is a string switch in
`Emphasis.tsx:69-121`; `Root.tsx`'s production composition is fully
props-driven and **needs no change** for a new device.

### 2.5 The schema split — the spine of this plan

`EmphasisCue`'s docstring states a hard rule:

> *"Creative decisions only (canon 3.1): which word, which device, which
> register, which text. **No colours, no positions, no pixels.**"*

and `OverlayCue` already carries render-resolved geometry (`band`,
`treatment`) with **a per-device resolver**.

So the split is already designed and must be honoured:

| layer | owns | for an annotation |
|---|---|---|
| `EmphasisCue` (planner) | the creative decision, in **words** | *"mark: the front grille"*, *"mark: the subject"* |
| `OverlayCue` (render) | the **pixels** | resolved `(x, y)`, mark radius, label box, line path |

**The planner never authors a coordinate.** This is not a constraint to
work around — it is the same shape `SubjectFocal` was built around, and
it is why N2 is an extension rather than an invention.

---

## 3. What is genuinely new

| | |
|---|---|
| A positional payload on `OverlayCue` | it carries `band` today; an annotation needs mark point, mark size, label box, and line endpoints — all **resolved**, none authored |
| A region-localisation vision call (N2) | focal answers *"where is the subject"*; this must answer *"where is the front grille"*. Same call shape, different question |
| Three Remotion components (N5) | mark draw-on, leader extend, label reveal |
| A handwriting face (N6) | vendored once, reaching libass **and** Remotion from one place — `compositor/src/font.ts` records this codebase already being bitten by a silent font fallback |

---

## 4. The real work: coordinates

Everything else in this plan is assembly. This is the part that can fail.

**Tier 1 — the subject.** Free. `focal.py` already has it, for every
image that passed a plausibility check. The "circle the historical
figure's face" case is Tier 1: on a portrait, the face **is** the
subject. This alone delivers the user's first example.

**Tier 2 — a named region.** New (N2). "The front grille", "the rear
gate", "Katanga". A vision call in `focal_check.py`'s shape, keyed by
content hash + region name so it caches like a focal sidecar does.
Accuracy will be variable and **must degrade to `None`, never to a
centre**.

**Tier 3 — the human.** `FOCAL_SOURCE_HUMAN` already exists as a
per-shot override upload with UI precedent. For a channel where a
specific mark matters, this is not a fallback so much as **the
authoring tool** — and it means Tier 2 missing is an inconvenience, not
a blocker.

**Ship Tier 1 + Tier 3 first.** Tier 2 is where the cost and the risk
both live, and the device is useful without it.

---

## 5. Direction — what will actually look good

The user asked directly. This section is opinion, grounded where it can
be.

### 5.1 Motion stops when you are asked to read

**An annotated shot does not move.**

Technically this is forced: the overlay is a separate full-film sheet
with no knowledge of the per-shot zoompan expression, so a panning
picture drifts out from under a fixed mark. But it is also simply
right — a drifting frame fights a label you are asking someone to read.

The rhythm this creates is the best thing about the device: **the frame
settles when there is something to read and drifts when there is not.**
That is a real directorial grammar, and it comes free.

(The alternative — passing the zoompan expression into the overlay props
so Remotion mirrors the motion — is possible and is real work. Reach for
it only if moving annotated shots are specifically wanted. They almost
certainly are not.)

This also answers the user's question "*do we even need Ken Burns*"
precisely: **yes, on un-annotated shots.** Ken Burns exists to disguise
the fact that a still is still. An annotation does that job *better*,
because its motion is meaningful — it directs the eye instead of moving
pixels. But it only does it on shots that have one.

### 5.2 Stagger the reveal, always

Mark ~0.25s → line ~0.35s → label ~0.15s. **Never simultaneous.**
Simultaneous reads as a graphic slapped onto a photo; staged reads as
someone marking the picture up in front of you. The whole appeal of the
device is in that difference, and it costs three `interpolate` calls.

### 5.3 Long lines are the point

The user is right about this. A label 40px from its mark is a caption.
A line that travels across the frame to clear space is an annotation: it
makes the eye travel, and the travel is what tells you the label belongs
to *that* thing. K17's calmest-box search (§2.2) will naturally pick
distant clear space — **do not add a proximity preference to it.**

### 5.4 The mark should be imperfect

A geometrically perfect vector ellipse reads as software. A slightly
irregular, over-drawn circle — a stroke that overshoots its start, the
way a real marker does — reads as a human annotating. This is the
"handwritten report" quality the user asked for, and it is one SVG path
detail, not a feature.

### 5.5 Annotation count sets shot duration — not the other way round

**One annotation ≈ 4s. Three staged annotations ≈ 12s.**

A static still with one annotation holds interest for about four
seconds. Ask it to hold twelve and it dies. So the duration follows the
device count, which makes multi-mark images the way to earn a long hold:
a map that holds 15-20s while three countries arrive in sequence is
*more* watchable than three 5s cuts, because the viewer is building one
picture instead of re-reading three.

For the user's DRC long form, that is the "Africa's World War" card, and
it is the single best shot this device can produce.

### 5.6 Do not annotate everything

The device's power is that it says *"this specific thing matters."* If
every shot has one, it means nothing. It needs a density cap in K3's
shape (`emphasis_max_cues_per_minute`, `emphasis_min_shot_gap` — both
already exist as band fields and already have enforcement).

### 5.7 Short form — measured 2026-09-14, second spike

**Built and rendered:** `compositor/src/AnnotationFast.tsx`, output
`tmp/annot-spike/annotation_fast.mp4` — three real assets, hard cuts,
1.9s per shot, every mark on that asset's **real** vision focal value.

**The arithmetic.** `AnnotationSpike`'s long-form reveal is not readable
until frame 38 (**1.27s**). Add ~0.75s to read a three-word label and
~0.3s for the picture to register and one annotation needs **~2.3s**.
`retention_fast`'s median shot is **1.75s**. It does not fit.

**The fix is a compressed reveal, not a longer shot.** Same three
stages, roughly half the frames:

| stage | long form | short form |
|---|---|---|
| mark | 13f | 10f |
| line | to 30f | to 23f |
| label | to 38f (**1.27s**) | to 29f (**0.97s**) |

Landed by 0.97s inside a 1.9s shot leaves ~0.9s of read time. **The
stagger survives; only the dawdling goes.**

Three rules follow, and two of them contradict the long-form rules
above — that is the point of having measured it:

1. **Two-word labels, maximum.** Three words do not fit the read budget.
2. **Short lines.** §5.3's long travelling lines are a **long-form
   luxury**: a line that crosses the frame costs frames a fast shot does
   not have.
3. **Static still holds up at speed.** §5.1 worried a still would read
   as dead. In a fast reel **the cut supplies the energy**, so it does
   not.

**Two editorial modes, and they want different settings:**

| | hero annotation | rapid-fire |
|---|---|---|
| reveal | long-form timing | compressed |
| shot | 3–3.5s (near the ceiling) | 1.9s |
| frequency | once per reel | most shots |
| reads as | a deliberate pattern interrupt | a forensic breakdown |
| the user's case | the one fact to remember | the Tata models reel |

**Incidental finding worth more than the rest:** across three randomly
chosen assets, the **real** vision focal put the mark somewhere sensible
every time — a face in a crowded parade rank, the wall screen in a
control room, the pointing officer at a desk. Tier 1 is not a
degraded mode; on this evidence it is most of the device.

### 5.8 Persistence

The annotation stays for the rest of the shot and leaves on the cut. Do
not fade it early — the viewer may still be reading. This differs from
`stamp`/`pivot`, which have tuned holds (`STAMP_HOLD_S = 0.86` etc.);
an annotation's hold is *the shot*.

---

## 6. Tasks

**N** for annotation. Sizing: **S** under a slice, **M** one slice,
**L** more than one or needs its own gate.

| id | task | size | blocked by |
|---|---|---|---|
| **N1** | `EmphasisDevice.ANNOTATION` + planner payload: the region **named in words**, mark kind, label text. **No coordinates** (§2.5). | S | — |
| **N2** | Region-localisation vision call — `focal_check.py`'s shape, answering "where is `<named region>`". Keep `SubjectFocal`'s name-then-words-then-numbers field order (§2.1). Cache by content hash + region. **Return `None`, never a centre.** | **L** | — |
| **N3** | Tier-1 + Tier-3 resolution: use the existing focal sidecar for "the subject"; extend the human override path to annotations. **Delivers the device without N2.** | M | N1 |
| **N4** | Label placement: reuse `caption_placement.py`'s calmest-box search; exclude the mark rect. Do **not** add a proximity preference (§5.3). | S | N1 |
| **N5** | Remotion components — `Mark.tsx` (draw-on, imperfect stroke §5.4), `Leader.tsx` (extend), `Label.tsx` (reveal). Staged per §5.2. | M | N6 |
| **N6** | Vendor **Kalam** (SIL OFL) — decided 2026-09-14, §0.4. Move it to `backend/vendor/fonts/` so libass and Remotion read one file (`package.json`'s `fonts` script already stages that dir into `public/`). | S | — |
| **N7** | Props plumbing: positional payload on `OverlayCue` + its own resolver (the seam `band` already uses); `_overlay_props`; `Emphasis.tsx` device switch. **No `Root.tsx` change.** | M | N1, N5 |
| **N8** | **Static-hold rule** (§5.1): a shot carrying an annotation gets no Ken Burns. Enforced where motion is decided, not in the compositor. | S | N1 |
| **N9** | Density + duration enforcement in K3's shape: cap per minute, min gap, **and a minimum shot duration for an annotated shot** (§5.7). | M | N1, N8 |
| **N10** | Multi-mark on one image (§5.5) — several marks arriving in sequence on one held shot, and the duration rule that follows from the count. | M | N7 |
| **N11** | **Authoring:** who decides what to annotate. Extends the emphasis planner and its prompt. The editorial judgement, not the rendering, is the hard half. | **L** | N1 |
| **N12** | Fingerprint hooks — annotation cues, resolved coordinates, and the font, each hashed separately the way `emphasis_cue_hash` is kept apart from `cue_list_hash`. | S | N7 |

**Slice 1: N1 + N3 + N4 + N5 + N6 + N7 + N8.** That is the identify
variant (§1) end to end — circle the subject, run a line to clear space,
label it in handwriting, hold the shot still — with **no new vision
call** and no planner work beyond naming the device. It delivers the
user's first example (a historical figure's face, circled, named)
completely.

N2 and N11 are slice 2 and carry all the real risk.

---

## 7. Open questions

1. **Mark colour.** Red is the user's stated intent and the obvious
   choice, but it collides with `retention_fast`'s existing
   `emphasis_pivot_ground="#FF2E2E"`. Band field or fixed?
2. **How does the planner name a region it has not seen?** The image is
   generated or retrieved **after** planning. So the planner can say
   *"mark the subject"* reliably, and *"mark the front grille"* only as
   an instruction that N2 may fail to honour. This is the deepest design
   question in the plan and N3's Tier-1-only slice sidesteps it
   deliberately.
3. **Does a leader line ever need to avoid busy pixels**, or is crossing
   the image simply what annotation looks like? Assume the latter until
   a render says otherwise — it is cheaper and probably correct.
4. **Short-form band changes** (§5.7) — raise `retention_fast`'s floor
   for annotated shots, or give annotations their own duration rule?

---

## 8. What NOT to do

- **Do not put coordinates on `EmphasisCue`.** §2.5. The planner names
  the region in words; render resolves pixels. Breaking this would break
  canon 3.1 and re-create the bug `focal_check.py` was re-cut to remove.
- **Do not let a failed localisation become a centre.** `focal_check.py`
  returns `None` and logs an explicit fallback precisely because a
  silent `(0.5, 0.5)` looked correct. An annotation pointing confidently
  at nothing is worse than no annotation.
- **Do not animate an annotated shot.** §5.1.
- **Do not reveal mark, line and label together.** §5.2.
- **Do not add a proximity preference to K17's placement.** §5.3.
- **Do not build this as a style.** It is a device family that composes
  onto the existing picture-led styles. Forking a style would duplicate
  every band knob for no gain.
