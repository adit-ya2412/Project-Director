# marble_strip — Letterboxed Card Reel (working name)

**Status:** PLAN ONLY. No code written, no spike run.
**Updated 2026-09-13** twice: **§2.5** records channel direction
(historical + scientific, long form 5-10 min and short 40-50s) and
revises M1/M3/M4/M7; **§6.1** works every remaining open question
through scenarios and recommends an answer to each — all still awaiting
user confirmation. The working name is wrong; §6.1 Q1 proposes
**`exhibit`**.
**Corrected same day:** an earlier draft over-weighted the statue
headline because it is the costliest device. **§2.0** counts device
frequency off the reference and **§2.7** shows D4 detaches, which moves
M6 and M7 out of v1 entirely. **§0** was added last and states what the
style *is* — read it first; the rest of this plan describes parts.
**Written 2026-09-13**, off one 44.3s reference reel the user supplied:
`tmp/WhatsApp Video 2026-09-13 at 20.45.30.mp4` (`@themehboobalam`,
"Ultra Successful People's / Morning Routine"). Frames and measurements
at `tmp/wa-style-ref/`.

**This is a NEW style, not a variant of `retention_fast`.** The sibling
plan `retention_fast_kinetic_text.md` covers kinetic type over
full-bleed photographic shots. This one is full-bleed *nothing*: every
frame is a synthetic card inside a fixed chrome frame. The two share
exactly two mechanisms — the alignment-derived cue clock
(`timeline/narration_fit.py`) and the Remotion compositor seam
(`renderer/compositor.py`) — and share no geometry, no palette, no
picture path, and no pacing.

---

## 0. What this style actually is

**Added 2026-09-13, after the rest of the plan was written.** Everything
below described the style's *parts* without ever saying what the thing
is. This is that.

### 0.1 Text-led, not picture-led

**Every other style in this codebase is picture-led. This one is
text-led.**

`documentary_archival`, `retention_fast`, `stillness`,
`archival_montage` and `illustrated_risograph` all work the same way
underneath: a picture fills the frame and text — captions, text cards,
kinetic type — is added over it. That is precisely why
`retention_fast_kinetic_text.md` exists; it opens by recording the ask
as *"captions aside — I want text all over the video."*

**This style is what you get when text is the substrate rather than the
addition.** The viewer *reads* the narration as it is spoken. The
picture is backdrop — subordinate, and on most cards absent entirely.

That is structural, not decorative, and it explains every measurement in
§1 that otherwise looks odd:

| observation | why |
|---|---|
| the card is only 30% of frame area | you do not need much picture |
| ~10 of 18 cards carry no photograph | flat colour is fine — the text is the content |
| the cut-out subject is fill (§2.0) | it exists so an empty card is not empty |
| it works at 45s **and** at 10 min | **reading pace** is the constraint, not shot supply |
| the asset budget is tiny | most cards need no asset at all |

### 0.2 Why it fits this channel

Names, dates, numbers and technical terms are hard to catch by ear.
Self-help narration contains almost none; history and science narration
is *made* of them (§2.5). A text-led style makes them **readable** —
hearing "Antikythera" once is not the same as seeing it spelled.

### 0.3 Scenario A — 45s short, 9:16

"The Antikythera Mechanism", ~19 cards. A representative run:

| t | card | on screen |
|---|---|---|
| 0.0–2.6 | photo, light | wreck-site photo scaled into the 16:9 card; caption builds `In 1901, sponge divers` |
| 2.6–5.2 | photo | `found a wreck off a Greek island` — committed white, incoming grey |
| 5.2–7.6 | white, ghost @10% | `Inside was a lump of corroded bronze` |
| 7.6–9.4 | white | red stamp **2,000 YEARS** over `It had been underwater for` |
| 9.4–20 | alternating light/dark | six caption cards, **no imagery** |
| 20–28 | white | **list builds** one line per beat: `It could predict —` / `eclipses` / `the Moon's phases` / `the Olympic cycle` / `planetary positions` |
| 35–38 | dark | **GEARS**, cut-out fragment occluding the G — **slice 2 only** |

Eleven of those cards are text on colour. Two assets do real work.

### 0.4 Scenario B — 8 min long form, 16:9

Same devices. Three changes: the card goes **full-bleed 1280×720** (no
black field), chrome becomes an inset lower-third carrying the series
name only (§6.1 Q2), and cards hold **~12s** (§6.1 Q4). ~40 cards.

The caption grammar shifts with it, and this is the load-bearing part:

- **Short:** a sentence builds, the card cuts.
- **Long:** a card holds while three or four sentences build, the text
  **retires at the paragraph**, and the next group starts on the same
  card.

The card stops being a shot and becomes a **slide** — it earns a
12-second hold because something happens on it the whole time. That is
the mechanism that lets one style serve both lengths, and it is why the
asset budget barely moves: 40 cards for eight minutes is a lower rate
than Scenario A's.

### 0.5 What it is NOT for

**When the picture is the argument, use `documentary_archival`.** If the
best asset is the image — a volcano, a nebula flythrough, wildlife, a
restored film clip — this style shrinks it to a third of the screen and
puts words over it.

For this channel: *how eclipse prediction works* is a good fit;
*astrophotography* is not.

---

## Verdict up front

**Three of the four signature devices are cheap. The fourth cannot be
built where the overlay currently lives, and choosing where to build it
is the only real architectural decision in this plan.**

The cheap news first, because it is better than expected:

- The **typewriter-accumulation caption** — the spine of the whole look —
  is a **pure ASS serialization change**. No new renderer, no new
  device, no new schema. Two functions and one extra colour field.
  (M4; the highest value-per-line item here by a wide margin.)
- The **red numeric stamp** is the *existing* `STAMP` device with a
  different palette and position. Effectively free. (M8.)
- The **card-in-a-black-field geometry** is reachable from parts that
  already exist: `parallax.py::base_canvas_filter` already builds a
  solid-colour full-frame clip, and `slideshow.py::_normalize_filter`
  already pillarboxes with `force_original_aspect_ratio=decrease` +
  `pad`. (M3.)

**Weight before cost (§2.0):** the accumulation caption is on ~16 of the
reference's ~18 cards; the statue headline is on ~6, and never appears
without that headline. **D1 is the style; D4 is punctuation** — and
§2.7 shows D4 detaches cleanly, taking the expensive news below with it.

The expensive news, which therefore applies to **slice 2, not slice 1**:
the reference's headline device puts a giant word **behind** a cut-out
statue. The Remotion compositor is a single
full-film alpha `.mov` composited with one `overlay=0:0` onto the
finished concat (`workflow/steps/render.py:887-904`). It can only ever
sit on top. A headline drawn there covers the statue instead of going
behind it. See §4.

---

## 1. The reference, measured

Measured from the supplied file, not eyeballed. Every value below is
**identical on every frame** — the chrome is a fixed frame, not
per-shot art.

### 1.1 Geometry

| element | measurement |
|---|---|
| canvas | 720×1280, pure `#000000` |
| **content card** | x `13`→`706`, y `445`→`835` = **694×391** |
| card aspect | 694/391 = **1.775** — a 16:9 landscape frame |
| card position | vertically **exact centre** (445 + 835 = 1280) |
| side gutter | 13px both sides |
| header band | y `397`→`432` (35px tall) |
| footer band | y `861`→`881` (20px tall) |
| watermark band | y `1184`→`1201` (17px tall) |

The composition is a **16:9 landscape frame pillarboxed into 9:16**. It
reads as a podcast clip framed for the feed; the black above and below
is deliberate room for chrome, not accidental letterbox.

Note this inverts both existing aspect opt-ins. `stillness` is 16:9
with a 9:16 opt-in; `illustrated_risograph` is 9:16 with a 16:9 opt-in
(`style_accepts_frame_aspect`, mirrored in `frontend/src/lib/
resolution.ts`). Here the **canvas is 9:16 and the picture is 16:9,
always, simultaneously** — a third case neither helper models. Expect to
touch `style_accepts_frame_aspect` and `canvasForStyle`, not just
extend a list.

### 1.2 Palette

| token | value | note |
|---|---|---|
| canvas | `#000000` | pure black, never graded |
| chrome red | `#FE0A00` | header + footer + numeric stamps |
| card light bg | `#FFFFFF` | ink `#000000` |
| card dark bg | `#131119` | faintly violet near-black; ink `#FFFFFF` |
| watermark grey | `#656565` | |
| caption committed ink (dark card) | `#F1EFF7` | |
| caption incoming ink (dark card) | `#6E6C74` | ≈45% toward bg |

Card polarity alternates light/dark across the reel, and both the
caption and the headline take ink from the card they sit on. That is
exactly the measurement `renderer/emphasis_contrast.py` already performs
for `retention_fast` (plate luma → light/dark/slab). **Reusable as-is**;
its input gets *easier*, since a flat authored card colour is a trivial
luma read compared to a photograph's plate.

### 1.3 Typography — three faces, none of them vendored

`backend/vendor/fonts/` holds exactly one file:
`NotoSansDevanagari-Regular.ttf`. Per `compositor/src/font.ts` it is
misnamed — it is a **variable font carrying the full 100–900 range**, so
weights are one descriptor away.

| role | face in reference | status |
|---|---|---|
| chrome (header/footer) | red **brush-marker script** | must vendor |
| headline | **very heavy condensed grotesque**, uppercase | must vendor |
| watermark | **handwriting script**, wide-tracked | must vendor |
| caption body | regular humanist sans ≈26px | **have it** — the vendored Noto covers Latin |

This is a licensing + vendoring task (M2), not a rendering task, but it
blocks every visual device and has a failure mode this codebase has
already been bitten by: `font.ts`'s own comment records a CSS font
request silently falling back to a different typeface than libass used.
**Any new face must be vendored once and passed explicitly to BOTH
libass (`fontsdir=`) and Remotion (`staticFile`)**, or the two diverge
silently and the reel ships in two voices.

### 1.4 Pacing

≈18–20 distinct cards in 44.3s → **median card ≈2.2–2.5s**, with one
deliberate long hold (the `MOVERS` list card runs ~8s while six lines
build).

That is materially **slower than `retention_fast`'s 1.75s**, and
`retention_fast`'s 3.5s ceiling would clip the list card outright. This
style needs its own band numbers; do not inherit them. Starting point
for M1: `target_shot_duration_s=2.3`,
`min_shot_duration_s_override=1.2`, `max_shot_duration_s_override=9.0`.
The wide ceiling is not sloppiness — it is what a list card costs, and
it is the one number a copied band would get wrong.

---

## 2. The devices

### 2.0 Device weight — counted, not eyeballed

**Corrected 2026-09-13.** An earlier draft of this plan let D4 (the
statue headline) dominate, because it is the most expensive device and
the most visually striking. Cost is not weight. Counted off the contact
sheets at `tmp/wa-style-ref/`:

| device | cards (of ~18) | notes |
|---|---|---|
| **D1** accumulation caption | **~16** | on essentially every card, photographic ones included |
| flat card + ghost backdrop | ~10 | |
| **D4** headline + cut-out subject | **~6** | |
| photographic card (no device) | ~3 | |
| **D3** red stamp | 2 | |
| **D2** list card | **1** | the `MOVERS` card — **and it has no statue on it** |

Two things follow, and they set the priorities for the whole plan:

1. **D1 is the style.** If a render has the framed card and the
   accumulating caption and nothing else, it will read as the reference.
   Everything else is punctuation.
2. **The cut-out subject never appears without the headline.** There is
   no card where a statue does a job of its own. Its function is narrow:
   fill the headline card so a flat ground is not empty, and give the
   word something to hide behind. **D4 is a detachable limb** — see
   §2.6.

### D0 — The chrome frame (not a device, but every device needs it)

Black canvas, red header, red footer, grey watermark — fixed for the
whole film, drawn once, never animated.

Two of the three strings are **per-channel, not per-video**:
`Ultra Successful People's` is the series, `Morning Routine` is the
episode. Neither is authored by any existing planner and neither belongs
in the band (a band holds numbers, not copy). This needs a small
project-level or channel-level settings surface — the same shape as
K5's channel palette (`channel_accent` / `channel_pivot_ground`,
`styles.py:708-709`), which is the precedent to follow.

`renderer/watermark.py` is the nearest existing machinery — applied last
in the chain, above everything (`render.py:906-921`) — but it overlays a
**logo image**, not tracked script type, and it sits where a logo goes,
not at y≈1190. Expect to extend it, not reuse it unchanged.

### D1 — Typewriter accumulation caption  *(the spine)*

The sentence builds **word by word and stays on screen**: already-spoken
words at full contrast, the word currently landing at ~45% toward the
background, words not yet spoken **not drawn at all**.

This is neither karaoke nor the current behaviour. Today
`_highlighted_dialogue_lines` (`captions.py:796-867`) emits one Dialogue
event per word window `[w_i.start, w_{i+1}.start)`, each drawing the
**entire chunk** with word *i* wrapped in a single highlight override
(`_highlight_override_ass`, 712-723). There is no committed/pending
distinction — only "current word" vs "everything else".

**The tiling machinery is exactly right; only the per-event colouring
rule changes.** See M4 for the precise diff surface.

### D2 — Progressive list card

`MOVERS` → six lines (`M - Meditation` … `S - Scribing`) appearing one
per narration beat, each arriving in the incoming grey then committing
to full contrast. Same grammar as D1, one dimension up.

`renderer/text_cards.py` is the nearest existing thing and it explicitly
refuses this. Its docstring: *"Static text, simple fade in/out — NOT
kinetic typography… the honest version of that, not a half-built attempt
at the dishonest one."* That refusal was right for ASS and does not bind
a Remotion component, which is where D2 belongs.

D2 also needs an **authoring** side that does not exist: something must
decide a passage is a list, extract its items, and anchor each item to a
fragment. That is a new emphasis-planner device, not a renderer concern,
and it is the single largest *non-render* task in this plan (M9).

### D3 — Red numeric stamp

`5 MINUTES`, `30 MINUTES` in chrome red, scaling in over the card.
**This is the existing `STAMP` device** (`EmphasisDevice.STAMP`,
`compositor/src/Stamp.tsx`) with a different palette and position.
Near-free: a band palette value and a `emphasis_stamp_top_fraction`
change. No new device, no new seam. (M8.)

### D4 — Headline behind a cut-out subject  *(the expensive one)*

A giant uppercase word (`MORNING`, `PAPER`, `UPGRADE`, `KNOWLEDGE`,
`MINDSET`, `MOVERS`) spanning the card's full width, with a
background-removed marble statue standing **in front of it**, occluding
one or two letters. Behind both, the *same* statue asset again at ~10%
alpha (measured: `#FFFFFF` card, ghost at `#E0DFE2`), scaled large and
bled off the card edges.

One card is therefore **four planes**:

```
1. flat card colour          (#FFFFFF or #131119)
2. ghost statue  @ ~10% α    (same asset, scaled large, bled off-edge)
3. HEADLINE                  (heavy condensed, card ink colour)
4. statue cut-out            (full opacity, occludes the headline)
```

The current overlay can draw planes 2–4, but only as one flat sheet
*above the picture* — which is the wrong z-order for plane 4 and makes
plane 1 pointless.

---

## 2.5 Channel direction — decided 2026-09-13

The user's channel is **historical and scientific** content, long form
(5-10 min) and short form (40-50s). They liked the reference's look and
had no attachment to its subject matter. Three decisions follow.

### 2.5.1 The statue is furniture, not style

The reference channel does stoicism content, so its cut-outs are Roman
busts. Strip that and what remains is channel-agnostic: a card in a
chrome frame, accumulation captions, a progressive list card, and a
headline occluded by a cut-out subject. **The cut-out slot is content.**
Each video fills it — a bust, a map, an artifact, a specimen, an
apparatus, a diagram.

This resolves M7's shape: it is not "generate marble statues", it is
"a shot's picture can be a transparent-background subject". More
general, and the same amount of work.

**Keep the property marble was providing, though.** A marble bust has no
skin and no eyes — it walks past the photoreal-AI-face problem this
project already measured and rejected. That is why the reference looks
clean, and it is not a coincidence. Consequences by subject:

| subject | cut-out source | risk |
|---|---|---|
| ancient / classical history | marble, genuinely on-genre | none — just use it |
| science | specimen, instrument, diagram | none — needs no faces at all |
| **modern history** | a person | **AI portrait → the measured failure**. Treat as the hard case; do not assume it falls out of M7. |

### 2.5.2 The reference is already a 16:9 design — the vertical frame is a wrapper

**The single most useful structural fact in this plan.** The card
measures 694×391 = **1.775**. The 9:16 black field is a wrapper around a
landscape design, not a vertical design with dead space.

That matters because long-form watch time is landscape — both long-form
bands here are 1280×720 (`documentary_archival` at `styles.py:264-265`,
`stillness` at `443-444`) — and vertical feeds cap at a few minutes, so a
10-minute 9:16 render has no real home. It does not need one:

| mode | canvas | card | chrome |
|---|---|---|---|
| **short** (40-50s) | 720×1280 | pillarboxed per §1.1 | in the surrounding black field |
| **long** (5-10 min) | 1280×720 | **full-bleed** | inset lower-third |

Same devices, same fonts, same palette. **One style with a framing mode,
not two styles.** This also dissolves a problem rather than fixing it:
70% black screen is a stylistic choice for 45 seconds and punishing for
ten minutes — in long mode there is no black field at all.

Revises M1 and M3: `card_rect` becomes a **framing mode** (`wrapped` /
`full_bleed`) plus the shared card aspect, and the chrome renderer needs
both placements. Long mode also needs a **caption retirement policy** —
accumulation that holds for 45s is fine; holding across ten minutes is
not, so a line must retire at sentence or paragraph end (M4).

### 2.5.3 Register risk

Red marker script + marble + `MINDSET` is a **recognisable genre** right
now (hustle / stoicism). Transplanted wholesale onto a video about the
Antikythera mechanism it will read as that genre commenting on science.
The structure is what is worth taking; **the marker face is the most
genre-loaded element in it**. Keep the frame, change the register — this
is an M2 (font choice) and M5 (fragment tone) concern, and it is the
main reason not to simply clone the reference's type.

One point in favour: the devices fit this subject matter *better* than
they fit the reference's. A progressive list card is built for
taxonomies, timelines, step sequences and mnemonics. Self-help has to
invent `MOVERS` to use one; history and science supply them free.

---

## 2.7 D4 is optional — what v1 costs without it

Because the cut-out subject serves exactly one device (§2.0), D4
detaches cleanly. Cutting it removes, in one stroke:

- **M6** — the entire §4 z-order decision, the plan's only architectural
  fork
- **M7** — the L-sized alpha-matte dependency
- the HEADLINE half of **M10** (LIST survives; it needs no cut-out)
- **§2.5.1's face problem** in full, modern history included

What survives is the chrome frame, accumulation captions, list cards,
red stamps, light/dark alternation, and ghost backdrops — **most of the
reference's actual screen time**, and every device appearing on more
than six cards.

This is not an argument against ever building D4. It is an argument
that D4 is a **second** slice, not a prerequisite, and that the §4
decision blocks nothing until then.

---

## 3. What adding the style costs at all

Independent of any device. There is **no DB enum and no migration** —
`render_style` is a plain `str` column, `Timeline.metadata.render_style`
is `str | None` (`schemas/timeline.py:960`), and **`STYLE_PACING_BANDS`
dict membership *is* the enumeration** (validated at
`api/projects.py:762-770`). That is the cheapest part of this whole plan.

| layer | file | change |
|---|---|---|
| band | `app/script/styles.py` | new `StylePacingBand` entry; **plus new fields** for card geometry + chrome (M1) |
| prompt | `app/prompts/shot_planner_styles/<style>.md` | new fragment; injected at `planners/shot/planner.py:1157-1159` via `load_style_fragment`, which returns `None` harmlessly if absent |
| picture path | `styles.py::PicturePath` | statue cutouts are generated, not retrieved → `GENERATION_ONLY`, same as `illustrated_risograph` |
| grade | `renderer/grading.py::STYLE_GRADES` | a flat card takes no grade — needs an explicit **no-op** entry, not a default |
| aspect rules | `script/styles.py::style_accepts_frame_aspect`, `frontend/src/lib/resolution.ts::canvasForStyle` | §1.1's third case |
| frontend | `frontend/src/lib/styles.ts`, `types.ts` | label / hint / grade copy |

---

## 4. The one architectural decision — where D4 gets composed

**Constraint, verified:** `render.py`'s filter chain is
`concat → grade → text-cards → captions → emphasis-overlay → watermark`,
each one `overlay=`ing onto a single flat running label. The Remotion
layer is one ProRes 4444 `.mov` with real alpha, composited with
`overlay=0:0` at 887-904. By the time it runs, the film is one flat base
track. **There is no insertion point beneath the picture.**

Reordering the fragment list is cheap and real — moving the overlay
block above the caption block puts kinetic type *under* captions, a
one-line-order change in `render.py` with no compositor edit. But no
reordering puts the overlay under the **picture**, because the picture
is the base. So:

| | **A — compose per-shot in ffmpeg** | **B — Remotion renders the card** | **C — cut-out as a late overlay** |
|---|---|---|---|
| how | card ground via `base_canvas_filter`; ghost + cut-out via `parallax.py`'s sampled-key → `alphaextract` → `median` → `alphamerge`; headline via `drawtext` between them | Remotion renders the whole 694×391 card as a clip; ffmpeg only pillarboxes it and adds chrome | picture = bare card, Remotion draws the headline, then a **third** timed input overlays the statue cut-out *after* the emphasis fragment |
| reuses | the proven keying + despeckle + both guards (`check_keyed_fraction`, `check_keyed_distribution`) | the proven props / cache / fingerprint seam | existing fragment-append pattern |
| typography | `drawtext` — no tracking, no layered fills, crude | full CSS; handles D2 for free | full CSS |
| per-shot motion | native | must be re-implemented in Remotion | statue can't Ken-Burns with its own card |
| cost | medium, all in known code | higher | low, but brittle |
| risk | headline quality ceiling is low | headless-Chromium non-determinism now affects the **picture**, not just an overlay — `I5` exposure widens | per-shot timing of a film-length input; the seam it needs doesn't exist |

**Recommendation: B, scoped narrowly.** Remotion renders only the
*graphic* cards (statue + headline + list); photographic cards (the two
talking-head shots in the reference) stay on the existing
still/Ken-Burns path and are scaled into the card rect by
`_normalize_filter`, which already pillarboxes.

The planner signal for that split **already exists and already ships**:
`Shot.picture_is_graphic`, authored by the Shot Planner (K12, `23f83e9`),
required with no default, already enforced by K3. That is a genuinely
lucky fit and it is the reason B is cheaper here than it looks.

**Decide M6 before starting M10.** Everything else in this plan is
independent of the outcome.

---

## 5. Tasks

Sizing is relative: **S** = under a slice, **M** = one slice, **L** =
more than one slice or needs its own gate.

| id | task | size | blocked by |
|---|---|---|---|
| **M1** | Band entry + new fields: **`framing_mode`** (`wrapped` / `full_bleed`, §2.5.2), card aspect + gutter, `canvas_colour`, `chrome_colour`, card light/dark pair. Pacing per §1.4 for short mode; **long mode gets its own row** per §6.1 Q4 (`target≈12`, `min≈4`, `max≈25`, `max_shots≈60`). | S | — |
| **M2** | Vendor three fonts (marker, condensed black, handwriting). Licence check. Wire to **both** libass `fontsdir=` and Remotion `staticFile` in one place. | S | — |
| **M3** | Chrome renderer, **both placements** (§2.5.2): surrounding black field in short mode, inset lower-third in long mode. Extend `watermark.py` or a sibling; applied once post-concat. | M | M2 |
| **M4** | **Typewriter accumulation caption mode.** In `captions.py`: `_line` closure (831-840) joins `words[a:i+1]` instead of `words[a:b]`; `_highlight_override_ass` (712-723) gains a second "committed" colour; `CaptionStyle` gains that colour field; band gains an opt-in flag. `_chunk_word_ranges` (K18) **untouched**; K17 placement **untouched**; `cue_list_content_hash` unaffected (it hashes timing/text, not style). Preserve the zero-duration-word branch (856-864) and the never-drop fallback (865-867) exactly. Breaks one invariant: the doc-comment guarantee at 807-808 that the whole chunk is on screen at all times — any test asserting full-chunk-text-per-event needs updating, deliberately. **Long mode needs a retirement policy** (§2.5.2): accumulation that holds 45s is fine, holding ten minutes is not — retire at sentence or paragraph end. | **M** | — |
| **M5** | Shot-planner style fragment. The brief is now clear from §0.1: direct a **text-led** style. The planner's usual job — find a picture for this beat — is mostly *not* the job here; most cards carry no photograph and the shot exists to hold text. That inversion is the whole difficulty, and it is why no existing fragment is a useful template. | M | — |
| **M6** | **DECIDE §4.** Recommendation is B-narrow. | S | — |
| **M7** | **Subject cut-out** asset path (§2.5.1 — *not* "marble statues"): a shot's picture can be a transparent-background subject. Today there is **no background removal** anywhere in `app/assets/` — `parallax.py` keys live against a **sampled** chroma substrate. **§6.1 Q3 picks real alpha matte** — magenta would make cut-outs generation-only, and this channel's best assets are retrieved (Wikimedia/Openverse, already wired). **Reuse `check_keyed_fraction` / `check_keyed_distribution` unchanged** — they measure the alpha mask, not how it was made; only the matting step is new. **Modern-history faces are a separate, harder case** and must not be assumed to fall out of this task. | **L** | — |
| **M8** | Red numeric stamp: palette + `emphasis_stamp_top_fraction`. Existing device. | S | M1, M2 |
| **M9** | New `LIST` emphasis device — planner side: detect a list passage, extract items, anchor each to a fragment. Extends `EmphasisDevice`, the emphasis prompt, and K3's enforcement. | **L** | — |
| **M10** | New `HEADLINE` + `LIST` renderers. Per the agent survey the seam is 4 mechanical steps: extend `OverlayCue.device` + `_overlay_props` payload; add `.tsx` components beside `Stamp.tsx`; add branches to `Emphasis.tsx`'s device switch (69-121); **no `Root.tsx` change** — the production `Composition` is already fully props-driven. | M | M6, M9 |
| **M11** | Ghost-statue backdrop plane @10% α. Falls out of M10 under option B; needs its own ffmpeg plane under A. | S | M6 |
| **M12** | Chrome copy, **split by lifetime** (§6.1 Q2): series → a `settings.*` global (K5's `channel_accent` shape; there is no `Channel` model); episode → derived from the project's own topic + one nullable override column. Long mode renders header only. | S | — |
| **M13** | Frontend: style card, hint copy, the §1.1 aspect third-case in `resolution.ts`. | S | M1 |
| **M14** | Fingerprint hooks for every new input (chrome copy, card colours, caption mode, new devices) — separate hashes, the way `emphasis_cue_hash` is kept separate from `cue_list_hash`. | S | M1, M4, M10 |

**Slice 1 — and per §2.0/§2.7, plausibly the whole of v1:** M1 + M2 +
M3 + M4. Not a foot in the door: D1 is on ~16 of ~18 reference cards,
so the framed card plus the accumulating caption *is* what makes a
render read as the reference. M6/M7/D4 are slice 2, and block nothing.

It delivers the chrome frame and the accumulation caption with zero new
devices, zero planner work, and no dependency on the §4 decision.

---

## 6. Open questions for the user

**Answered 2026-09-13** — see §2.5:

- ~~Is the statue motif fixed, or this channel's choice?~~ Neither: the
  cut-out slot is **content**, filled per video (§2.5.1).
- ~~Does this survive 5-10 minutes?~~ Yes, in **full-bleed 16:9 long
  mode**; the vertical frame is a short-form wrapper (§2.5.2).
- ~~Cut-outs vs. the illustrated-character direction?~~ Marble's
  no-face property is the thing to preserve; **modern history is the
  hard case** and does not fall out of M7 (§2.5.1).

### 6.1 Worked through 2026-09-13 — recommendations

All four were costed against scenarios. **These are recommendations, not
user decisions** — none has been confirmed.

#### Q1 Style name → **`exhibit`**

The id is effectively permanent: it lands in the `render_style` column
of every project made with it and is the prompt filename. The human
label is separate (`frontend/src/lib/styles.ts`), so the id does not
need to be pretty — it needs to not go stale.

| scenario | outcome |
|---|---|
| subject-named (`marble_*`) | dead on arrival — §2.5.1 |
| geometry-named (`strip_card`) | stale the first time long mode renders full-bleed; **and `card` collides with the existing `shot.text_card` / `text_cards.py` concept** |
| mechanism-named (`framed_build`) | cannot go stale; dry but safe |
| **feel-named (`exhibit`)** | house precedent exists (`stillness`) |

An exhibit is literally a subject on a plain ground with a headline and
a label — it describes the composition *and* lands on history/science
without naming either. Survives both framing modes and any subject.
Label "Exhibit", hint `9:16 or 16:9 · built-up type, cut-out subject`.
Fallback: `framed_build`.

#### Q2 Chrome copy → **split by lifetime**

**Finding that reframes the question: there is no channel entity.**
`channel_accent` / `channel_pivot_ground` are plain `settings.*` globals
(`styles.py:708-709`, read at `render.py:534-535`); `app/models/` has no
`Channel`. "Channel-level" here means a global in `config.py`.

The two strings have different lifetimes, and that is the answer:

| string | lifetime | source |
|---|---|---|
| header (series) | changes ~never | **global setting**, exactly K5's `channel_accent` precedent. No schema. |
| footer (episode) | every video | **derive from the project's own topic** — it is already data — plus one nullable override column |

Zero typing per video and no drift across the channel. The alternative
(both as per-project fields) means retyping the series string every
time, which is how chrome ends up with three spellings.

**Long mode: header only.** A lower-third stacking series *and* episode
is too much furniture to hold for ten minutes.

#### Q3 Cut-out mechanism → **real alpha matte**

Changed from the plan's original hedge; the channel's subject matter
decides it.

| scenario | cost | what it forbids |
|---|---|---|
| magenta substrate + sampled key (reuse `parallax.py`) | cheapest; two measured guards already work | **makes cut-outs generation-only by construction** |
| **real alpha matte** | new dependency + a guard | nothing |
| both, staged | S1 now, S2 later | the fragment gets written around generated subjects and retrieval never lands |

Decisive: **you cannot key a retrieved image**, because you cannot
regenerate a Wikimedia photo on magenta. For history and science the
best assets are the real ones; Wikimedia and Openverse are already wired
as providers, and a genuine photograph of an artifact beats a generated
one on both quality and honesty.

Two more pushes the same way. The keying is already known-fragile on
easy input — `_KEY_SIMILARITY` went 0.16 → 0.06 **plus** a median
despeckle, and that was on flat illustration; instrument wires, fossil
edges, feathers and hair will fringe. And **any subject containing
magenta breaks outright**: flamingo, nebula, stained histology slide,
anatomical illustration. Not hypothetical for this channel.

**Cheaper than it looks:** `check_keyed_fraction` and
`check_keyed_distribution` measure the resulting **alpha mask**, not how
it was produced. The safety net transfers unchanged; only the matting
step is new. Reuse them rather than writing new guards.

#### Q4 Long-mode pacing → **fewer cards, longer holds**

Computable against A9 (`styles.py:1142-1163`):
`capacity_s = min(max_shots, n_fragments) × max_shot_duration_s`, and
`settings.max_long_form_duration_s = 600.0` — exactly the 10-minute top
end.

| scenario | cards per 10-min film |
|---|---|
| same grammar, more cards (2.3s) | **261** — dead on arrival, on asset cost and authoring both |
| **fewer cards, longer holds (~12s)** | **50** |

This is what accumulation buys: a card with text building on it has
**internal motion**, so it holds 15s without going static. 50 is the
same order as `retention_fast`'s `max_shots_override=58` — **a 10-minute
film costs roughly one short reel's asset budget.**

Starting band for long mode: `target_shot_duration_s≈12`,
`min_shot_duration_s_override≈4`, `max_shot_duration_s_override≈25`,
`max_shots_override≈60`. Checks out against A9: 50 × 25 = 1250s
capacity, well above the 600s ceiling.

**Budget note:** `styles.py`'s own C6 comment puts a 10-minute film at
**~6667¢ ≈ $67** against the project budget cap, vs 1000¢ for 90s. Worth
knowing before committing to long form as the primary format.

#### Q5 (M6) z-order → **B-narrow, reinforced**

Unchanged recommendation, strengthened two ways by §2.5 and Q4:

- Long mode means ~50 long-holding cards, not 260 fast ones, so Remotion
  is invoked **less**, not more.
- B's stated risk — headless-Chromium non-determinism reaching the
  *picture* — is bounded to graphic cards, whose content is flat colour,
  type and a PNG. About as deterministic as browser rendering gets.

Option A's failure is simpler: `drawtext` has no tracking control and no
layered fills. In a style where the headline **is** the look, that
ceiling is the whole problem.

### 6.2 Still genuinely open

- Every recommendation in §6.1 awaits user confirmation.
- Register (§2.5.3): which marker/condensed faces. Cheap now, annoying
  after M3 and M8 are both built against them.
- Modern-history cut-out subjects (§2.5.1) — the one case M7 does not
  solve on its own.

---

## 7. What NOT to do

- **Do not clone `retention_fast`'s band.** Its 1.75s target and 3.5s
  ceiling are wrong for this style and the ceiling would clip the list
  card. §1.4 has starting numbers.
- **Do not put the chrome copy in the band.** A band holds numbers.
- **Do not add a `render_style` enum or a migration.** There isn't one;
  `STYLE_PACING_BANDS` membership is the check.
- **Do not extend `text_cards.py` into kinetic typography.** Its
  docstring refuses this deliberately and that refusal is still correct.
- **Do not bend `retention_fast`'s caption path.** M4 must be an
  **opt-in band flag**. `retention_fast` ships a tuned
  `caption_chunk_chars=28` + highlight behaviour (K17/K18) that the user
  has already watched and signed off; accumulation must not reach it.
- **Do not download fonts at render time.** Vendor them (§1.3).
- **Do not build this as two styles, one vertical and one landscape.**
  §2.5.2: it is one device set with two framing modes. Forking it would
  duplicate every device and let the two drift, which is the failure
  `long_form_direction.md §4.3` already names ("two styles, one base").
- **Do not bake the marble in.** §2.5.1: the cut-out slot is content.
  Hardcoding statues into the style fragment would make every science
  video look like a stoicism video.
