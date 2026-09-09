# retention_fast — Kinetic Text & Data Graphics

**Status:** PLAN, gate PASSED. A working spike exists
(`tmp/remotion-spike/`, throwaway); no production code written.
**Written 2026-09-08**, off a build-and-watch session against project
`fba52b6d` ("The king of midsize SUV", `retention_fast`, 720x1280, 46.5s,
Hindi). The user's framing: *"captions aside — I want text all over the
video"*, then *"make fast retention solid, so the reels start to feel
really the high retention that they are meant for."*

**Scope: `retention_fast` ONLY.** Sibling plan
`documentary_archival_watchability.md` covers long-form; the two share a
mechanism and deliberately not a look.

**Target length: 30-45s** (user, 2026-09-08). The SUV reference at 46.5s
sits at the top of that range. Three consequences worth stating up front,
because they shape several tasks below:

- At ~1.64s median that is roughly **18-28 shots per reel**, so "one cue
  per shot" is a ceiling of ~25, far above any sane density. The real cap
  comes from taste, not from shot count (K3).
- A whole-film emphasis pass (K10) sees only 30-45s of narration and
  ~25 shots. That is a small prompt and one cheap call per video - the
  main cost objection to a new planner stage does not really apply here.
- `max_shots_override=58` was budgeted for 90s ("90s / 1.75s/shot =~ 51
  shots"). At 30-45s it is never reached. It stays as harmless headroom;
  do not "fix" it.

---

## Verdict up front

**This style is already well directed for pacing, and has no typographic
or data-graphics system at all.**

`retention_fast.md` (the style fragment) is substantive and working:
finest fragment granularity, `punch_in` as the default move, **`cut` only
— never `dissolve` or `fade`**, and it respects tuned duration bounds. The
band backs it with real numbers: `target_shot_duration_s=1.75`,
`min_shot_duration_s_override=0.8`, `max_shot_duration_s_override=3.5`,
`max_shots_override=58`, `narration_speed=1.4`, `whoosh_enabled=False`,
duck to -18 dB (ear-signed).

Measured on the SUV film that direction lands: **27 shots, 7 scenes,
median 1.64s, min 0.83s, max 3.03s.** Nothing about the pacing needs
fixing. Do not touch it.

Two things are missing, and the second is a correctness problem, not a
polish problem:

1. **Nothing punctuates.** The only on-screen text is a romanized
   Hinglish caption track. Captions TRANSCRIBE.
2. **Data moments are AI-generated pictures of charts, and they lie.**
   See "Data graphics" below — this is the highest-value item in the plan.

---

## Current state — updated 2026-09-09

First slice landed in `175e0c9` ("Put the pivot on the reel"). It is
labelled K10 but delivers more than that. Reviewed the same day; findings
and their disposition are below.

| task | state |
|---|---|
| **K1** EmphasisCue schema | **done** — `schemas/timeline.py`, with `offset_s` split from `anchor_fragment` exactly as `ShotLayer.enter_on_fragment` does |
| **K2** resolve timing from alignment | **done** — `resolve_emphasis_cue_offsets` in `narration_fit.py`, called from `NarrationStep` |
| **K10** pivot detection | **done** — `timeline/pivot.py`, lexical, one per reel |
| **K7** compositor seam | **partial** — `renderer/compositor.py` + props-driven `Pivot.tsx`/`Emphasis.tsx`. Fingerprint hooks (`emphasis_cue_hash`, `emphasis_font_hash`) are in and correctly separate from `cue_list_hash` |
| **K9** emphasis pass | **stub** — `steps/emphasis_pass.py` exists and is style-gated, but runs only pivot detection. The LLM pass is not written |
| **K3** enforcement rules | **partial** — only the `text_card` exclusion, inline in `pivot.py`. No density cap, no graphic-asset exclusion, no safe zones |
| **K4** contrast adaptation | **not started** |
| **K5** palette resolution | **not started** (the commit says so explicitly) |
| **K6** reach the vendored Bold | **done 2026-09-09** — was never a download |
| **K8** data graphics | **not started** |

**Why shipping the pivot first worked without K6.** The pivot is the one
device whose weight comes from its slab rather than its font, so a
Regular-only Devanagari is enough for it and only for it. Every other
Devanagari device needs K6.

### Review findings from 175e0c9

- **Fix APPLIED 2026-09-09:** `emphasis_pass.py`'s placement rationale cites
  pre-A8 behaviour - it claims render "muxes audio only when the active
  version is `produced_by=NARRATION`". `render.py` checks
  `metadata.narration_locked`, which A8 introduced precisely so later
  versions do NOT silence the render. The placement is right; the reason
  is stale. The surviving reason is the approval gate (a post-narration
  append lands a DRAFT version).
- **Fix APPLIED 2026-09-09, REVERSING a documented decision:**
  `EmphasisCue.register` shadowed `ABCMeta.register` via pydantic's
  `BaseModel` and warned on every import. Renamed to `text_register`.
  Read the 13:05 work-log entry below before judging the implementer:
  it SPOTTED the warning and kept the name anyway, because "renaming
  would diverge from the schema in this document". The plan was wrong
  and was followed correctly. The spec sketch above is now fixed; the
  work-log entries stay as history. Lesson: a spec sketch in a plan is
  not evidence, and an implementer noticing a real defect should be
  able to say so without diverging - that is a gap in how these plans
  ask to be read, not in the agent.
- **Known gap, PINNED BY TEST 2026-09-09:** the regex word-boundary
  anchor does NOT protect Devanagari the way `pivot.py`s comment claims.
  Base Devanagari letters ARE word characters; combining marks are NOT
  (े U+0947 Mn, ि U+093F Mc, ् U+094D Mn), so a boundary fires
  between a consonant and a matra and the pivot pattern matches INSIDE
  लेकिनी. Latin IS protected - `button`, `butter` and
  `magarmach` are all correctly rejected, and the existing tests cover
  those. Not being fixed: लेकिनी is not a word, and changing
  the matching rule is a design decision. The risk grows if the token
  list gains words that inflect.
- **Note:** `मगर` also means "crocodile". Irrelevant for cars and
  history, a false red band on a wildlife reel.
- **Open design question:** when a `text_card` sits on the pivot shot the
  card wins and the reel loses its pivot entirely, and detection does not
  look further. For this style the turn is arguably worth more than a
  card. The existing text-card spacing pass already has a precedence
  concept (chapter cards outrank ordinary ones) worth mirroring. Decide
  rather than inherit.
- **Minor:** `attach_pivot_cue` re-checks `shot.text_card` after
  `detect_pivot` already filtered those shots. Unreachable; blurs which
  layer owns the K3 rule.

### Pick up next, in this order

The ordering principle: **everything that makes cues SAFE lands before
K9, because K9 is where the cue count stops being one.**

1. ~~**K6**~~ **DONE 2026-09-09.** Not a download - the vendored file was
   already the variable font. One `FontFace` weight descriptor. See K6.
2. **K4 — contrast adaptation.** Today's single red band is slab-backed
   and safe on any plate. The first bare-text device is not. Regression
   case is named in the Build notes: the SUV plate at t=3.0s, mean luma
   216.
3. **K3 — the full enforcement pass.** Promote the `text_card` rule out
   of `pivot.py` into the shared pass, then add the graphic-asset
   exclusion, the density cap and per-shot safe zones. With one cue per
   reel none of these bite yet; with K9 they all do.
4. **K5 — palette resolution.** Needed before any device that is not the
   fixed red band.
5. **K9 — the real emphasis pass.** Replace the stub with the whole-film
   LLM call. Do this only once 1-4 are in place.
6. **K8 — data graphics.** Last, and largest.

`K10`'s own follow-ups (the homonym note, the precedence question) can
ride along with whichever of the above touches the same file.

---

## What the spike proved (2026-09-08, all watched)

Six beats over the first 7.0s of the SUV film, captions stripped
(`work/silent_final.mp4` as the plate, audio from `renders/final.mp4`),
built in Remotion 4.0.522, exported ProRes 4444 alpha (`yuva444p12le`),
composited with a plain ffmpeg `overlay`. 216 frames in ~30s after a
one-time Chrome Headless Shell download. Zero API spend.

Real word onsets, from that render's own ASS:

| beat | onsets | treatment | verdict |
|---|---|---|---|
| `EVERY / 3rd / SUV` | 0.69 / 0.83 / 1.17 | word-by-word drop-in, amber `3rd` at 168px | **works** |
| `HYUNDAI CRETA` | 1.49 / 1.92 | dark slab wipes open, tilted -4°, name slams on | **works** |
| `2025` | 2.69 | 190px white, scale 1.45 -> 1.0 | **FAILED** |
| `2,00,000+` | 3.60 | counter, Indian grouping, landing on "lakh", plus meter | **FAILED** |
| `लेकिन` | 4.94 | full-bleed red band, decaying shake | **works, best in reel** |
| `REALLY?` | 5.42 | lower band, `?` spinning in from -25° | **works** |

Also proven on the long-form spike and portable here: a **correction**
(`सच` struck through in red, `→`, `झूठ` arriving) and **per-cluster
stagger** on Devanagari via `Intl.Segmenter` grapheme splitting — `झूठ`
is 3 code points but 2 clusters, and a naive `split("")` orphans the
vowel sign.

### The two failures are the useful part

**1. White type on a bright plate.** Plate mean luma across those seven
seconds ran **93 -> 216** — a 2.3x swing inside one hook. The `2025` beat
sits on the 216 frame and washes out; only its drop shadow keeps it
legible. The amber rule directly beneath reads fine. **Amber was the
robust choice and white the fragile one** — the opposite of the intuition
that picked it.

**2. Type over an asset that is already a graphic.** The counter landed
on an AI-generated infographic; two data displays fighting, both
unreadable.

### The escape hatch the failures point to

`लेकिन` in a red band was legible at every plate brightness in the reel,
because **a slab brings its own background**. Bare type does not. For a
style whose plates swing 2.3x inside seven seconds, slabs are the robust
default and bare type is the exception that must earn its contrast.

---

## Devanagari typography — four measured rules

Hard-won on 2026-09-08 and recorded here because they otherwise live only
in throwaway spike code. This script does not tolerate Latin defaults,
and every one of these was found by rendering a frame and looking at it.

**1. Letter-spacing destroys Devanagari in libass.** An ASS style with
`Spacing: 2` rendered `झूठ` with a **dotted circle** - the Unicode
placeholder for a combining mark that failed to attach to its base. The
existing caption style renders the same word correctly because it carries
`Spacing: 0`. Rule: never track Devanagari in ASS. There is no workaround;
tracking and shaping are mutually exclusive there.

**2. Chromium survives the same operation.** `letterSpacing: 14px` on
`झूठ` in the compositor keeps the vowel sign correctly attached, just with
air between clusters. This is a concrete capability difference in the
compositor's favour that has nothing to do with animation - tracking is
basic typography and the current renderer cannot do it on Hindi at all.

**3. Per-character stagger must split by GRAPHEME CLUSTER.** `झूठ` is
three code points (झ + ू + ठ) but only TWO clusters, because ू belongs to
झ. `Array.from()` or `.split("")` tears the vowel sign off its base and
animates it as an orphan - reproducing rule 1's dotted circle from the
other direction. Use `Intl.Segmenter(locale, {granularity: "grapheme"})`.

**4. Strike-through sits higher than in Latin.** A correction's strike at
56% of the line box - the Latin-centred position - reads as an UNDERLINE
on Devanagari, because the script carries its visual mass high under the
shirorekha. 48% reads as a cancellation. Any device that crosses out,
underlines or highlights needs a script-aware vertical position.

**Consequence for K6 (corrected 2026-09-09):** these four rules are why
a real Bold matters — but the Bold was already vendored. The file named
`-Regular.ttf` is the variable font, `wght` 100-900. See K6; the fix was
a `FontFace` weight descriptor, not a download.

---

## Data graphics — the honesty problem

The SUV film's "2 lakh sold" shot is an AI-generated infographic. It
renders a six-year bar chart: 2020: 110k, 2021: 135k, 2022: 160k,
2023: 195k, 2024: ~205k, 2025: projected — plus a dealership report, a
market-share donut, and its own invented footnote
"* Data marked estimates/projections for 2025".

**The narration states exactly one number:** *"2025 mein iske 2 lakh se
zyada models bike."* Five of those six values were fabricated by an image
model and shipped in a finished video as a credible-looking chart.

Its Devanagari is also partly garbled — "हुंडई की प्रबक बाजार हगन",
"जसी-निक मांत" are not words. Image models cannot render Devanagari
reliably.

So this is not a rendering defect. It is a **truth defect**, and drawing
the same chart beautifully in Remotion would make it worse, because a
crisp chart carries more authority than a mushy one.

### DECIDED 2026-09-08 (user): permissive, with provenance

The planner **may** add supporting values it believes are true, so a
one-number script can still produce a trend chart. The restrictive
alternative (plot only what the narration states) was put to the user
with its trade-off - plainer data moments than the reference reels -
and rejected.

That is the product decision. What follows are the guardrails that make
it defensible, and they are not optional extras: the whole risk of this
choice is a crisp chart carrying more authority than its weakest number
deserves.

**1. Every chart must be anchored by a cited value.** At least one value
carries `cited_fragment`, and code verifies those digits appear in that
fragment's narration text. A chart made entirely of inferred numbers is
rejected. In the SUV case `2,00,000` is the anchor and the five earlier
years are inferred.

**2. Inferred values must LOOK inferred, on frame.** This is a rendering
requirement, not a data field. Stated values render solid; inferred ones
render outlined, hatched or at reduced opacity, with a visible `est.`
marker in the graphic itself - not in a footnote at 12px. The viewer
should be able to tell which number the voiceover actually said. Done
well this reads as deliberate design rather than a disclaimer.

**3. Inferred values must be plausible against the anchor**, and this is
checkable: same order of magnitude, and monotonic when the narration
frames a trend ("climbing", "since", "grew"). A 2021 figure larger than
the 2025 anchor in a growth story is a bug, not a judgement call.

**4. Inferred values are recorded in the timeline and reviewable.** They
land in the versioned document like any other planner decision, so a
human can see and override them before render - the same shape as the
existing per-shot planner veto (A12).

**5. Never invent a SOURCE.** This is the one line the plan holds
absolutely: the planner may estimate a number, and may never attribute
it. No "Data: SIAM 2025", no organisation names, no logos, no invented
report titles. Estimating a value is a creative liberty the user has
taken; manufacturing a citation for it is forgery, and it is also what
turns a screenshot into a problem. The current AI infographic already
invents its own footnote - that behaviour must not be reproduced
deliberately.

### Integration

A data shot should not also carry a generated picture. `PicturePath`
today is `RETRIEVAL_LADDER` or `GENERATION_ONLY`; this wants a third
value — a composed shot whose picture IS the graphic, on a designed
ground, with no asset resolved for it. That keeps the asset planner from
buying an image nobody will see.

---

## The full device set (all in v1)

The user's call: correction and pivot ship with the first release, not
after it.

| device | what it does | source of truth |
|---|---|---|
| `stamp` | one stressed word, punched on frame | a narration word |
| `counter` | a value counting to a stated number | a cited narration number |
| `meter` | the same value as length | same |
| `comparison` | two values side by side | one cited number + inferred, marked |
| `correction` | claim struck through, truth replaces it | a claim + its refutation |
| `pivot` | the turn, full-bleed band | the pivot word ("lekin") |
| `question` | a rhetorical beat the narration does not say | a closed vocabulary |

`pivot` is the cheapest and highest-impact: retention scripts are built
around the turn, the pivot word is lexically detectable ("lekin",
"but", "magar"), and the red-band treatment was the strongest thing in
the whole spike.

`correction` is the strongest creatively and the hardest to author — see
Open Question 2.

`question` is the riskiest: it puts words on screen the voiceover never
said. It needs a closed vocabulary and a validation that the text is
either drawn from narration or from that list. Otherwise this feature
ships confident on-screen claims nobody wrote.

---

## Architecture: who decides what

Every row has a precedent already in this codebase.

| decides | owner | precedent |
|---|---|---|
| which word, which device | planner (LLM) | `text_card`, `sfx_cue` are planner-authored |
| **when, to the millisecond** | **code, from the alignment** | **F4 `resolve_layer_entry_offsets` — "the cue is a word not a second"** |
| the project's palette | human or LLM, **once, recorded** | `metadata.voice_id` via a HUMAN `append_version` |
| role structure, contrast floor, slab policy | the style band | `StylePacingBand` owns gains, canvas, whoosh |
| light / dark / slab per shot | code, from the measured plate | `sample_substrate_colour` — "never assumed" |
| whether a cue is allowed at all | code, after the planner returns | the text-card spacing pass; `resolve_picture_path` |
| final say per shot | the human | A12 per-shot planner veto |

**Timing is never LLM-authored.** The planner names a fragment INDEX;
code resolves it to seconds once real alignment exists. D1 applied one
level in, exactly as F4 already does for a layer's entry. Re-narrating at
a different voice re-times every cue for free.

**Colour is decided once and written down, not improvised per render.**
Per-VIDEO distinctness is a goal, not a hazard. What must not happen is a
hex chosen fresh at render time: it breaks I5 and the render fingerprint,
and the model cannot verify contrast against a plate it cannot see. A
palette proposed once from the script, or derived from the film's own
assets, then recorded in `metadata`, is deterministic, reviewable, and
free to change — palette costs render time, never API spend.

**Roles, not hues.** The band defines `accent` / `alert` / `neutral` plus
a contrast floor; the project binds roles to colours; the renderer applies
by role. Per shot, code may flip the TREATMENT (light/dark/slab) but
never the hue.

---

## Audio: explicitly out of scope

**DECIDED 2026-09-08 (user): no stingers, no SFX of any kind on cues for
this style.** An earlier draft of this plan proposed extending
`derive_sfx_events` with a stinger per cue. That is withdrawn. Kinetic
text carries this style on its own; `whoosh_enabled=False` already stands
on this band and nothing here adds a new audio layer.

---

## Tasks

### K1 — `EmphasisCue` on the shot
**Status (2026-09-09): implemented for the pivot-first slice (other devices remain schema-only).**

Creative decisions only, canon 3.1 (no colours, no positions, no pixels):

```
EmphasisCue:
  device:          stamp | counter | meter | comparison | correction | pivot | question
  anchor_fragment: int         # WHICH WORD - index, never seconds
  text:            str
  text_register:   hi | en     # see Open Question 4. NOT `register`:
                               # that shadows ABCMeta.register via BaseModel
  values:          [{value: int, unit: str|None, cited_fragment: int}]
  replaced_text:   str | None  # correction
```

`values[].cited_fragment` is what makes the honesty rule enforceable.

### K2 — Resolve cue timing from alignment
Mirror `resolve_layer_entry_offsets` exactly: `{shot_id: [seconds]}` from
fragment indices, at the same seam `reconcile_spoken_durations` occupies.
Do not build a second timing path.

### K3 — Enforcement pass (the fixed rules)
In code AFTER the planner returns, same discipline as
`resolve_picture_path` and the same shape as the project-wide text-card
spacing pass:

- At most one cue per shot.
- **Mutually exclusive with `text_card`** — measured: a stacked
  correction landed on "The Myth and the Burned Scroll", both unreadable.
- **Never over an asset that is already a graphic** — measured.
- **Every `values[]` entry must cite a fragment whose text contains that
  number.** Drop the cue otherwise.
- Density cap and min-gap per band. Kinetic text stops working the moment
  it is constant: it becomes the baseline and nothing punctuates.
- **Per-SHOT safe zones, not per-video.** The spike's zones were read off
  one frame, right at 1.3s and wrong at 4.3s.

### K4 — Contrast adaptation
Measure each cue's own plate (mean luma, ideally local luma under the
cue's box) and choose light type / dark type / slab. Slab is the default
for this style. This is the task that would have caught `2025`.

### K5 — Palette resolution
Precedence: `human override > per-project (LLM or derived) > channel
default > style band default`. Unset must produce something correct.
If derived from assets, pick an accent that OPPOSES the film's dominant
hue — matching makes type sink into the picture.

### K6 — Reach the Bold that is already vendored  **(CORRECTED 2026-09-09)**

**This task was described wrongly in every earlier version of this plan,
including its "PREREQUISITE" note and the build order. There is nothing
to download.**

`backend/vendor/fonts/NotoSansDevanagari-Regular.ttf` is MISNAMED. It is
the full variable font (Noto Sans Devanagari v2.006, Monotype), measured
with fontTools on 2026-09-09:

```
wght  min=100  default=400  max=900
wdth  min=62.5 default=100  max=100
named instances: Thin ... Regular(400) ... Bold(700) ... Black(900)
```

A real Bold master has been in the repo since 2026-08-17. The filename is
the only thing that ever said "Regular", and this plan believed it.

The actual defect was one missing descriptor. `new FontFace(family, src)`
with no `weight` defaults to `"400"`, which caps the matcher at the
Regular instance, so every heavier request became SYNTHETIC bold - the
matra smearing this plan kept citing as a reason to vendor a second file.

The fix, applied: declare the axis range on the `FontFace`
(`{ weight: "100 900" }`) and ask for `fontWeight: 700`. Nothing
downloaded, nothing vendored, no supply-chain question, no second binary
to keep in sync.

Two consequences worth carrying forward:

- **The slab is now a design choice, not a workaround.** Earlier text in
  this plan justified slabs partly because Devanagari could not be bold.
  It can. Slabs remain the right default for CONTRAST robustness (the
  luma 93-216 finding), which is a separate and still-valid argument.
- **libass does not follow the axis.** It uses the default instance, so
  captions stay Regular. Irrelevant for `retention_fast` (captions are
  off) but it means the compositor and libass will render different
  weights from the same file. Do not treat that as a bug.

Also worth renaming the file to `-Variable.ttf` eventually - the current
name has now caused two wrong decisions in this document - but the
rename touches `captions.py`'s font registry and the compositor's copy
script, so it is not part of this task.

### K7 — Compositor integration
Remotion as a **layer producer**, never a renderer replacement. It emits
alpha; ffmpeg stays the assembler; master clock, D5 arithmetic, audio mux
and loudness are untouched. `remotion_integration.md` §17 proposes a
`Renderer` interface with FFmpeg and Remotion as ALTERNATIVES — this plan
takes §18's other reading ("these capabilities may be combined"), because
swapping the renderer means re-deriving everything that works.

Determinism: headless Chromium is not byte-stable. Cache a rendered
overlay by the hash of its INPUTS (cue spec + palette + plate id), exactly
as `generated_clip` caches an AI image by `prompt_hash`. I5 then holds at
the assembly level, where it matters.

### K8 — Data graphics
The honesty rule above, the four permitted forms, the third `PicturePath`
value, and drawn charts rendered by the same compositor. Sequence this
AFTER K1-K4 — it reuses the cue timing, the palette and the contrast work,
and it is the item most likely to change what a shot IS.

### K9 — The emphasis pass (DECIDED: this is the authoring home)
A planner stage that runs AFTER the shot plan and BEFORE narration, with
the whole film visible: full narration, all fragment indices, all shots
and their durations. It emits every `EmphasisCue` for every scene in one
call.

Why it is the right home, beyond `correction`:

- **Density becomes computable rather than enforced afterwards.** One
  pass sees every cue it is about to emit, so it can space them
  deliberately. K3's caps become a backstop instead of the mechanism.
- **Duration-outlier scoring needs the whole film** to know what "held
  4x longer than the average word" means. In the SUV hook `teesri`,
  `SUV`, `Hyundai`, `2025`, `lakh` and `lekin` all sit well above the
  line average - the narrator is pointing at the cues.
- **Pivot detection is one lexical scan** over the full narration.
- 30-45s of narration is a small prompt; this is a cheap call.

Note it must run after fragments exist (it anchors by fragment index) and
before narration synthesis is irrelevant either way - cue timing is
resolved later by K2 from real alignment, so this pass never sees or
guesses seconds.

### K10 — Pivot detection
**Status (2026-09-09): implemented in the K10 + pivot-device slice.**

Lexical, not semantic, for v1: "lekin", "magar", "but". Cheap, testable,
and it hits the single most important beat in the script. This is the one
task that could ship on its own and improve every reel.

---

## Decisions and open questions

All six answered 2026-09-08. Density (5) is defined by a test rather
than a fixed number - see below.

**1. Captions — ANSWERED 2026-09-08 (user), then STRENGTHENED.**
`retention_fast` ships with **no burned captions at all** - not "off when
cues are dense", but not part of the style. The caption track is replaced
by the cue system, not suppressed around it.

Rationale, in the order it matters:

- **Dense kinetic text does the job captions were doing.** The spike's
  hook reads as a complete hook with the sound off: `EVERY 3rd SUV` ->
  `HYUNDAI CRETA` -> `2,00,000+` -> `लेकिन` -> `REALLY?`. Silent autoplay
  was the main argument for burned captions, and purpose-built
  punctuation serves it better than a transcript.
- **Frame budget.** Crowding was the spike's single worst problem. The
  bottom band is also where the platform's own UI sits (measured on the
  long-form film: captions at 4% from the frame bottom are occluded by
  player chrome).
- **Redundancy.** Two text systems saying the same words, one of them
  designed and one auto-generated.
- **It removes the caption romanizer from this style's critical path.**
  That is an LLM step with a real failure mode - it failed on
  2026-09-08 with "word count changed: 16 -> 15" after 2 attempts. One
  less flaky dependency and one less call per reel.

Substitution, not deletion: ship an uploaded `.srt` sidecar
(`documentary_archival_watchability.md` W5, style-agnostic). Selectable,
translatable, indexable, zero frame budget - strictly better than burned
captions for accessibility.

Accepted cost: this band runs `narration_speed=1.4`, so the voice is 40%
faster than natural, and fast Hindi with no on-screen transcript is
harder to follow for some viewers. Judged acceptable over 30-45s.

**CONSEQUENCE - this makes cue density a functional floor, not a taste
setting.** With captions gone a muted viewer sees only cues, so sparse
cues means a near-blank video for part of the audience. K3's density cap
therefore needs a MINIMUM as well as a maximum, and the minimum is
defined by a testable property: *watch it muted and see whether the hook
still lands.* See Open Question 4.

**2. Correction authoring — ANSWERED 2026-09-08 (user): option C.**
A separate emphasis pass, after the shot plan, seeing the whole narration,
every fragment index and every shot at once. See K9.

Rejected: authoring in the shot planner (it is called per scene and
cannot see the refutation - in the SUV script the pivot sits in scene 1
and the answer arrives several scenes later, so `correction` would be
structurally impossible), and restricting corrections to within-scene
pairs (these scripts are built as one film-length correction, so it would
fire rarely and almost never at the moment that matters).

**3. Chart honesty — ANSWERED 2026-09-08 (user): permissive (scenario B).**
The planner may add supporting values it believes are true, flagged as
estimates, so a one-number script can still produce a trend chart. Full
decision and the five guardrails that make it defensible are in
"Data graphics" above - including the one hard line: estimate a value,
never attribute it.

**4. On-screen register — ANSWERED 2026-09-08 (user): mixed, by a FIXED
role table (scenario C).** A table in the style fragment, not a per-cue
planner choice - "mixed by role" degenerates into "mixed at random" the
moment the model gets to decide each time.

| cue content | register | reason |
|---|---|---|
| numbers, years, quantities, counters | **Latin** | nobody reads "दो लाख"; they read "2 lakh". Latin digits also give tabular figures, which the counter needs |
| brands, model names, proper nouns | **Latin** | the name is Latin in life (`HYUNDAI CRETA`) |
| the pivot / the turn | **Devanagari** | `लेकिन` was the strongest beat of the whole session |
| a correction's claim and truth | **Devanagari** | same emotional register as the pivot; proven on the long-form spike (`सच` -> `झूठ`) |
| rhetorical `question` | **Latin** | worked in the spike (`REALLY?`), but the least certain row - revisit after a full reel |
| `stamp` (a word the narrator said) | **inherit the source word's own script** | no decision needed: the narration is Hinglish, so if the voice said "Comment" it stamps Latin, if it said "झूठ" it stamps Devanagari |

That last row is the important one - a `stamp` echoes a spoken word, so
it can simply mirror what was spoken. Most cues resolve with no rule at
all.

**Consequence for K6 (corrected 2026-09-09):** with Devanagari carrying
the pivot and corrections, real weight matters — and it was always
available. The vendored file is the variable font; declaring the axis
range was the whole task. Slabs stay the default for CONTRAST reasons,
which is a separate argument and still holds.

**5. Density — RESOLVED BY METHOD, not by a number. Not blocking.**
No longer purely taste, because captions are gone (see 1). The spike ran
6 cues in 7s (~40/min), which will not sustain for 30-45s. But the floor
is now functional: too few and a muted viewer gets nothing.

The test is defined rather than guessed: **mute a full reel and check
whether the story still lands.** That is also the acceptance test for the
whole feature.

Build against **8-12 cues/min with the pivot guaranteed** - roughly 5-9
cues in a 35s reel - and tune from a watched reel rather than settling
the number now. Both bounds are real: too few and a muted viewer gets
nothing (captions are gone), too many and nothing punctuates because
everything does.

**6. Graphic placement — ANSWERED 2026-09-08 (user): overlay the
photographic plate (scenario A), "for now".** Drawn graphics composite
over live footage rather than replacing the shot. Full-frame (scenario B)
is NOT discarded - it becomes the documented fallback, see below.

The reel keeps feeling shot rather than made, which is the point. But the
spike's 4.3s failure WAS scenario A failing, so three things are load
bearing rather than optional:

**1. A scrim is mandatory, not styling.** A graphic over footage needs
its own ground: a darkened or blurred panel behind the graphic's own
area. This is the slab principle from the stamp work, scaled up from a
word to a panel. Bare charts over live footage is the case that already
failed once.

**2. A label budget.** A stamp is one text element; a chart is many. A
six-bar chart with year labels, value labels and an axis is ~13 elements
over moving footage. Cap the number of labelled values per overlaid
graphic (starting point: 4) and prefer fewer, larger values. If a
graphic needs more labels than the budget allows, it is the wrong
graphic for an overlay.

**3. Contrast is measured under the graphic's own box**, not the frame
mean (K4). A panel in the lower third of a bright sky shot and the same
panel over dark tarmac need different treatments, and the frame average
tells you neither.

**Documented fallback:** when the contrast check cannot be satisfied or
the label budget is exceeded, escalate to full-frame on a designed ground
(the third `PicturePath` value described under "Integration" above).
Keep that path built even though A is the default - it is the only
guaranteed-legible option, and the "for now" in this decision anticipates
revisiting it once real charts have been watched.

**Corollary:** `counter` and `chart` are genuinely different devices, not
variations. A single value over a photograph reads fine and needs no
panel (proven: `2,00,000+`). A multi-value labelled graphic needs the
panel, the budget and the measurement. Split them in K8.

---

## Deliberately NOT in this plan

- **Any change to `retention_fast`'s pacing, camera or transitions.**
  Measured as working.
- **The 6.47s audio overrun** in `mux_music`'s `amix duration=longest` —
  real, open, and orthogonal.
- **Any SFX or stinger work.** Decided against by the user; see "Audio"
  above. Do not reintroduce it as a "small addition".

---

## Build notes — for whoever implements this

Everything above is WHAT and WHY. This section is WHERE and IN WHAT
ORDER, written for someone (or something) with no memory of the session
that produced the plan. Paths were verified against the tree on
2026-09-09.

### Read these first, in this order

1. `app/timeline/narration_fit.py` module docstring — D1, the master
   clock, and why shot duration is derived from spoken characters. Cue
   timing obeys the same law.
2. `resolve_layer_entry_offsets` in that file — the EXACT pattern K2
   copies. A layer's entry is anchored to a fragment INDEX and resolved
   to seconds only when real alignment exists.
3. `app/prompts/shot_planner_styles/retention_fast.md` — the style's
   existing direction. Do not contradict it.
4. `app/renderer/fingerprint.py::compute_render_fingerprint` — read the
   whole signature before writing any code. See the warning below.

### Build order (dependencies are real)

```
K6  reach the vendored Bold          <- one FontFace descriptor; DONE 2026-09-09
K1  EmphasisCue schema
 |
K9  emphasis pass (authoring)       <- needs K1's shape to emit into
 |
K2  resolve cue timing              <- needs cues to exist
 |
K3  enforcement pass  ---+
K4  contrast adaptation  |          <- both need resolved cues
K5  palette resolution   |
 |                       |
K7  compositor seam <----+          <- needs everything above to have
 |                                     something to render
K8  data graphics                   <- needs K7's seam and K4's contrast
K10 pivot detection                 <- independent; can ship any time
                                       after K9 exists
```

**K10 and K6 are the two that stand alone.** If you want a first commit
that improves every reel on its own, K10 (lexical pivot detection) plus
the pivot device is it.

### File map

| task | touch |
|---|---|
| K1 | `app/schemas/timeline.py` — `EmphasisCue` model, and a field on `Shot` (class at line 358; `ShotLayer` at 280 is the closest precedent for a planner-authored sub-model, including its "creative decisions only" docstring) |
| K2 | `app/timeline/narration_fit.py` — a `resolve_emphasis_cue_offsets` beside `resolve_layer_entry_offsets`; call it from `app/workflow/steps/narration.py` at the same seam as line 585 |
| K3 | new module, e.g. `app/timeline/emphasis_rules.py`; called from the emphasis pass. Precedent for "enforce after the planner returns": the text-card spacing pass in `app/planners/shot/planner.py` (see `chapter_shot_ids` / `min_gap`, lines ~132-177) |
| K4 | `app/renderer/` — plate measurement. `sample_substrate_colour` in `app/renderer/parallax.py:307` is the existing example of reading pixels off an asset |
| K5 | palette on `timeline.metadata` (precedent: `metadata.voice_id`); band defaults in `app/script/styles.py` beside `StylePacingBand` |
| K6 | `compositor/src/font.ts` only — declare the `FontFace` weight range. Nothing in `backend/vendor/fonts/`: the file there is already the variable font (DONE) |
| K7 | new `app/renderer/compositor.py` + a tracked `compositor/` package; wired into `app/workflow/steps/render.py` |
| K8 | extends K7's composition and K1's schema; third `PicturePath` value in `app/script/styles.py:29` |
| K9 | new step class + registration in `DEFAULT_PIPELINE`, `app/workflow/engine.py` |
| K10 | inside the K9 pass; pure function, unit-testable with no DB |

### ⚠ The fingerprint. Read this before writing code.

`compute_render_fingerprint` (`app/renderer/fingerprint.py:170`) decides
whether `RenderStep` reuses the existing `final.mp4`. **If cues are not
in it, the render step serves the cached video with no text on it and
nothing errors.** That failure looks exactly like "the feature doesn't
work" and it will cost hours.

Add, as new keyword arguments:

- `emphasis_cue_hash` — over the RESOLVED cues (device, text, resolved
  seconds, register, values, treatment). Not the raw planner output.
- `emphasis_font_hash` — same reason `caption_font_hash` and
  `text_card_font_hash` already exist: a changed font must invalidate.
- `palette_hash` — a changed palette must re-render (K5).

The codebase's own rule for this, from analysis.md RV2: **one value gates
both the derivation and the fingerprint.** Resolve style-derived values
once in the caller and hand the same value to both, exactly as
`whoosh_enabled` is handled.

**Naming trap:** `cue_list_hash` already exists in that signature and
means CAPTION cues. Do not overload it. Use `emphasis_cue_hash`.

### K9 — where the step goes

`WorkflowStep` is a Protocol in `app/workflow/step.py:31`: `name`,
`retryable`, `max_attempts`, `async is_satisfied(ctx) -> bool`,
`async run(ctx) -> StepResult`.

`DEFAULT_PIPELINE` in `app/workflow/engine.py` is currently:

```
GenerateTimelineStep, ResolveAssetsStep(search), SelectMusicStep,
SelectSfxStep, RomanizeCaptionsStep, NarrationStep, AwaitApprovalStep,
ResolveAssetsStep(generate), GenerateDiegeticSfxStep, AwaitReviewStep,
RenderStep, CompleteStep
```

Insert `EmphasisPassStep()` **after `SelectSfxStep()` and before
`AwaitApprovalStep()`**. Three reasons:

- It needs only the timeline (shots + fragments), which
  `GenerateTimelineStep` has already produced.
- It must land **before the approval gate** so a human reviews cues where
  they already review the plan. Cues are creative decisions.
- It must NOT depend on narration. Cue timing is resolved later by K2
  from real alignment, so this pass never sees or guesses seconds. An
  earlier draft of this plan said "before narration" and then muddled it;
  the correct statement is that narration order is irrelevant to
  AUTHORING and mandatory for TIMING.

`is_satisfied` should return true when the active timeline version was
produced by this step — the same shape every other planner step uses.

### K7 — the compositor seam, specified

This is the part the rest of the plan only gestured at.

**One parameterized composition, driven by props.** Do NOT generate a
`.tsx` file per video. The compositor package exposes a single
composition whose entire content comes from `--props`: canvas, fps,
duration, palette, and the resolved cue list. Codegen per project is the
obvious wrong turn here and it will not survive twenty reels.

Python side, `app/renderer/compositor.py`:

1. Build an input hash over (resolved cues + palette + font hashes +
   canvas + fps + duration + plate ids).
2. Look for `{storage_root}/{project_id}/overlays/{hash}.mov`. Return it
   on a hit — **this is what makes headless Chromium acceptable under
   I5.** Cache by INPUT hash, never by output bytes, exactly as
   `generated_clip` caches an AI image by `prompt_hash`.
3. On a miss: write props to a temp JSON, invoke the compositor
   (`npx remotion render <id> <out> --props=<file>` with the alpha flags
   below), and atomically move into place.
4. Alpha flags, verified working: `--codec=prores
   --prores-profile=4444 --pixel-format=yuva444p10le --image-format=png`.
   The output reports `yuva444p12le`; that is expected.

Render side, `app/workflow/steps/render.py`: composite with
`[base][overlay]overlay=0:0:format=auto`. The overlay is one more layer
in a chain that already burns captions, text cards and a watermark — it
does not need a new mechanism.

**Do not touch** `mux_narration`, `mux_music`, `mux_sfx`, the loudness
stage, `compute_timeline_duration`, or anything in `narration_fit`
besides K2's addition. Remotion produces a layer; ffmpeg remains the
assembler. `remotion_integration.md` §17 proposes replacing the renderer
outright — this plan deliberately does not.

**Deploy consequence:** a Node toolchain plus a Chromium binary now sit
beside Python and ffmpeg. Node 18+ is required (v22.15.1 verified);
Chrome Headless Shell downloads itself into `node_modules` on first
render. Vendor the fonts (K6) rather than relying on host fonts — the
same discipline `captions.py` already applies with its explicit
`fontsdir=`.

### Done-criteria, per task

Each of these is checkable, and "it looked fine" is not one of them.

- **K1** — a cue round-trips through `append_version` and back out of the
  DB unchanged; a cue with no `anchor_fragment` is rejected by validation.
- **K2** — for a known alignment, resolved seconds equal the fragment's
  own onset to within a frame. Re-narrating at a different `narration_speed`
  moves every cue and requires no cue edits.
- **K3** — with a deliberately colliding plan as input, zero cues survive
  on shots carrying a `text_card` or a graphic asset; a chart with no
  citable anchor value is dropped.
- **K4** — for the SUV plate at t=3.0s (mean luma 216) the chosen
  treatment is NOT light-on-transparent. That exact frame is the
  regression case; it is in the repo history as a failure.
- **K5** — the same project renders byte-identical twice; changing the
  palette changes the fingerprint and forces a re-render.
- **K6** — `झूठ` renders from the vendored Bold with no synthetic-bold
  smearing, and with `letterSpacing` applied the vowel sign stays
  attached (rule 2 above).
- **K7** — second render of an unchanged project performs zero Chromium
  invocations (cache hit). `ffprobe` reports `yuva444p*` on the overlay
  before compositing; a lost alpha channel produces a black rectangle,
  not an error.
- **K8** — every chart carries a citable anchor; the `est.` marking is
  legible at phone size; no chart carries an attribution string.
- **K9** — cue count per reel falls inside the density band; the pivot is
  present in every reel that contains a pivot word.
- **K10** — pure-function unit tests over Hinglish narration strings; no
  DB, no LLM.

### And the feature-level test, which supersedes all of the above

**Mute a full reel and watch it.** Captions are gone, so if the story
does not land with no sound, the cue system has failed regardless of what
any unit test says.

---

## Gate — PASSED 2026-09-08

The user watched `tmp/suv_test/SUV_AB_captions_vs_kinetic.mp4` on a phone
and confirmed the kinetic version is better. This plan proceeds.

Original gate text, kept for the record: **watch
`tmp/suv_test/SUV_AB_captions_vs_kinetic.mp4`** on a phone (original with
captions left, kinetic without right). If the kinetic version is not
obviously better, this plan is wrong and the money is entirely in K8.

The spike is throwaway and lives in gitignored `tmp/`. Promote it to a
real `compositor/` package beside `backend/` and `frontend/` only after
that gate passes.

## Verification

Reuse the session's method rather than trusting a status field:

- `ffprobe` the overlay for `yuva444p*` before compositing; a lost alpha
  channel produces a black rectangle, not an error.
- `signalstats` the plate under every cue; assert the chosen treatment
  clears the contrast floor. This is the check that was missing.
- Assert every chart has at least one anchored value whose digits appear
  in its cited fragment's narration text; reject charts with none.
- Assert inferred values pass the plausibility check (magnitude,
  monotonicity when a trend is framed).
- Grab a frame of every chart and confirm the `est.` marking is legible
  at phone size - the guardrail is worthless if it renders at 12px.
- Assert no chart carries an attribution string. Estimating is allowed;
  citing a source is not.
- Grab a frame at each cue's midpoint and LOOK. Every failure in the
  spike was invisible in the numbers and obvious in the picture.
- Count cues colliding with a `text_card` or a graphic asset. Expect zero.

---

## Work log — K10 + pivot device (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 13:00 — starting

- read / opened: plan (K1 schema, K2, K7 compositor seam, K10, fingerprint warning, DEFAULT_PIPELINE notes, Devanagari rules, role table); `narration_fit.py` module docstring + `resolve_layer_entry_offsets`; `fingerprint.py::compute_render_fingerprint`; `SuvRetention.tsx` Pivot (~line 285); `font.ts`, compositor README, `Root.tsx`; `timeline.py` Shot / ShotLayer / ProducedBy; `engine.py` DEFAULT_PIPELINE invariant; `fragments.py` (1-based, character spans); `render.py` overlay chain; `romanize_captions.py` / `select_sfx.py` step shape; existing tests named in the slice brief.
- decided: this slice is K10 + parameterized pivot + minimum glue (schema, attach step before Narration, K2 offset resolve, compositor seam for pivot only, fingerprint). Not K3-K6, not other devices, no PR, no push.
- decided: `is_satisfied` will NOT trust `produced_by` (Narration overwrites it). Derive from "pivot cue already present / nothing attachable / pass attempted / not this style". Skip already-narrated (`narration_locked`) projects the same way romanize does, so a resume cannot append after narration and drop audio. Dry-run WILL attach (unlike romanize) — there is no LLM, and fake timelines should still carry the pivot.
- decided: first lexical match in film order is THE turn. If that covering shot already has a non-empty `text_card`, skip attaching and do not search further (K3 mutual exclusion; reel has no pivot).
- files: this plan (status lines on K1/K10; this work log)
- tests: none yet
- next: schema (K1, pivot-first), then `app/timeline/pivot.py` + unit tests

### 13:05 — schema (K1, pivot-first)

- read / opened: `Shot`, `ShotLayer` (creative-only docstring + `enter_offset_s` split), `ProducedBy.CAPTION_ROMANIZATION`, `TimelineMetadata.caption_romanization_attempted`, existing Shot validators.
- decided: full device enum now so later devices do not churn the model; this slice only authors/renders `pivot`. `anchor_fragment` required (`Field(ge=1)`), `offset_s` defaults 0.0. At most one cue per shot = a single optional field. Validator refuses non-empty `text_card` + `emphasis_cue`. Added `ProducedBy.EMPHASIS_PASS` because the step does append a version (placed before Narration). Added `metadata.emphasis_pass_attempted` as a backstop stamp, not as the primary `is_satisfied` signal.
- decided: keep the field name `register` as the plan specifies. Pydantic warns that it shadows a `BaseModel` attribute; renaming would diverge from the schema in this document. Lived with the warning.
- files: `backend/app/schemas/timeline.py`
- tests: `tests/unit/timeline/test_emphasis_cue.py` (written, not yet run)
- next: K10 `pivot.py`

### 13:08 — K10 detection + attach

- read / opened: `split_narration_fragments` (1-based, `[start, end)` character spans), `Shot.narration_span`.
- decided: word-boundary regex, case-insensitive, Unicode. Canonical display: `lekin`/`लेकिन`/`but` → `लेकिन`; `magar`/`मगर` → `मगर`; `register=hi`. First match in film order is THE turn. No covering shot → skip, do not invent. Covering shot has a non-empty `text_card` → skip attaching and do not search further (reel has no pivot). `attach_pivot_cue` always returns a deep copy.
- files: `backend/app/timeline/pivot.py`, `backend/tests/unit/timeline/test_pivot.py`
- tests: not yet run
- next: thin authoring step

### 13:09 — emphasis pass step + pipeline slot

- read / opened: `romanize_captions.py` (`is_satisfied`, dry-run, `narration_locked` landmine), `engine.py` DEFAULT_PIPELINE comment (Narration must be last append before the gate).
- decided: insert `EmphasisPassStep()` after `RomanizeCaptionsStep()` and before `NarrationStep()` (the slice brief, tighter than the older "after SelectSfx / before AwaitApproval" note — romanize already occupies that window). Style-gate on `timeline.metadata.render_style == "retention_fast"` exactly (None / other styles are no-ops). Skip `narration_locked` so a resume cannot restamp DRAFT and drop audio. Dry-run attaches (no LLM; fake timelines should carry the pivot). `is_satisfied` keys off cue present / nothing attachable / attempted stamp / style / narration_locked — never `produced_by`.
- files: `backend/app/workflow/steps/emphasis_pass.py`, `backend/app/workflow/engine.py`, `backend/tests/unit/workflow/test_emphasis_pass_step.py`, `backend/tests/unit/workflow/test_render_only.py`, `backend/tests/integration/test_narration_pipeline_ordering.py`
- tests: not yet run
- next: K2 timing

### 13:10 — K2 timing

- read / opened: `resolve_layer_entry_offsets` / `_fragment_onset_offset_s` / `_clamp_entry_offset`; `NarrationStep._reconcile_and_append`.
- decided: `resolve_emphasis_cue_offsets` beside the F4/F5 resolvers, same arithmetic, same clamp. Called from NarrationStep at the same seam. No alignment yet → `offset_s` stays 0.0 (schema default). No second timing path.
- files: `backend/app/timeline/narration_fit.py`, `backend/app/workflow/steps/narration.py`, `backend/tests/unit/timeline/test_narration_fit.py` (K2 cases appended)
- tests: not yet run
- next: compositor pivot + Python seam + fingerprint

### 13:11 — compositor pivot + Python seam + fingerprint + render wire

- read / opened: spike `Pivot` (Beat 5), `font.ts`, `Root.tsx`, `render.py` filter chain, `fingerprint.py` signature, `watermark_filter_fragment` extra-input indexing, `compute_shot_start_times`.
- decided: extract parameterized `Pivot.tsx` (spike look unchanged: `#FF2E2E`, clipPath wipe, `Math.sin(local * 1.9) * Math.max(0, 10 - local * 1.6)`, −1.5deg, 3-frame snap exit). Spike composition imports it. New `Emphasis` composition driven by `--props` (`calculateMetadata` from canvas/fps/duration). Transparent `AbsoluteFill`. Pivot-only; other devices ignored. No per-video TSX. No letter-spacing. No type stagger (spike did not stagger). Vendored Regular via `font.ts` (K6 Bold is later).
- decided: hold `PIVOT_HOLD_S = 0.91` (spike 4.94→5.85). Clamped to remaining shot and remaining film. Film-absolute `startFrame = round((shot_start_s + offset_s) * fps)`.
- decided: Python `app/renderer/compositor.py` caches `{storage_root}/{project_id}/overlays/{input_hash}.mov` by INPUT hash (cues + canvas + fps + duration + font file hash). Miss invokes `npx remotion render Emphasis` with ProRes 4444 / `yuva444p10le` / png. Missing Node/package is `PermanentError`, never a silent skip. Tests stub `_invoke_remotion`.
- decided: fingerprint adds `emphasis_cue_hash` and `emphasis_font_hash` as new kwargs defaulting to None, keys always present in the payload even when None. This changes every historical fingerprint (accepted; no golden hashes in unit tests). Do not overload `cue_list_hash`. Palette hash skipped (K5). RenderStep resolves overlay cues once and hands the same list to the fingerprint and the compositor (RV2). Overlay sits after captions, before watermark: `[base][overlay]overlay=0:0:format=auto`.
- files: `compositor/src/Pivot.tsx`, `compositor/src/Emphasis.tsx`, `compositor/src/SuvRetention.tsx`, `compositor/src/Root.tsx`, `compositor/README.md`, `backend/app/renderer/compositor.py`, `backend/app/renderer/fingerprint.py`, `backend/app/workflow/steps/render.py`, `backend/tests/unit/renderer/test_fingerprint.py`, `backend/tests/unit/renderer/test_compositor.py`
- tests: not yet run
- next: run the slice tests

### 13:13 — tests

- tests: `cd backend`; venv pytest on `test_pivot.py`, `test_emphasis_cue.py`, `test_narration_fit.py`, `test_fingerprint.py`, `test_emphasis_pass_step.py`, `test_compositor.py`, `test_render_only.py` → **157 passed** in ~5s. Related: `test_fingerprint_parallax.py`, `test_fingerprint_reveal.py`, `test_romanize_captions_step.py` → **45 passed**.
- decided: ruff SIM103 on `is_satisfied`'s final `narration_locked` return; isort on compositor test imports. Re-ran the 157 after the fix, still green.
- warning: Pydantic `Field name "register" shadows an attribute in parent "BaseModel"` — kept the plan's field name.
- next: work-log summary + local commit. No push, no PR.

### 13:14 — finish / summary

Slice is a vertical cut: a `retention_fast` timeline with `lekin` in narration gets `EmphasisCue(device=pivot, text=लेकिन, register=hi)` on the covering shot; NarrationStep fills `offset_s` from alignment; RenderStep fingerprints the resolved cues and composites a props-driven red-band overlay.

**Files changed**

- Schema: `backend/app/schemas/timeline.py`
- K10: `backend/app/timeline/pivot.py`
- Step: `backend/app/workflow/steps/emphasis_pass.py`, `backend/app/workflow/engine.py`
- K2: `backend/app/timeline/narration_fit.py`, `backend/app/workflow/steps/narration.py`
- Compositor (visual): `compositor/src/Pivot.tsx`, `compositor/src/Emphasis.tsx`, `compositor/src/SuvRetention.tsx`, `compositor/src/Root.tsx`, `compositor/README.md`
- Compositor (Python) + fingerprint + render: `backend/app/renderer/compositor.py`, `backend/app/renderer/fingerprint.py`, `backend/app/workflow/steps/render.py`
- Tests: `backend/tests/unit/timeline/test_pivot.py`, `test_emphasis_cue.py`, `test_narration_fit.py` (appended); `backend/tests/unit/workflow/test_emphasis_pass_step.py`, `test_render_only.py`; `backend/tests/unit/renderer/test_fingerprint.py`, `test_compositor.py`; `backend/tests/integration/test_narration_pipeline_ordering.py`
- This plan (status lines + this work log)

**Decisions (also in the entries above)**

- One cue per shot via a single optional field. Pivot is Devanagari, canonical text table is fixed.
- First lexical match wins; a `text_card` on that shot means the reel has no pivot.
- Step before Narration; `is_satisfied` does not trust `produced_by`. Skip `narration_locked`. Dry-run attaches.
- Hold 0.91s, clamped. Overlay cache by input hash. Fingerprint keys always present (None when no overlay) — historical hashes change.
- Pivot-only rendering. Unknown devices ignored. No SFX, no Bold vendor, no per-video TSX.

**Deviations from the plan**

- K9 as specified is an LLM pass; this slice is the K10 stub only, as the brief asked.
- Older K9 placement note said "after SelectSfx / before AwaitApproval". The slice brief (and the silent-video invariant) put the step after romanize and before Narration. That is what shipped.
- `ProducedBy.EMPHASIS_PASS` was added because the step appends; `is_satisfied` still does not key off it.
- Already-narrated (`narration_locked`) retention_fast projects are skipped rather than backfilled. Same landmine romanize documented. Fresh pipelines attach before narration.
- `emphasis_cue_hash` / `emphasis_font_hash` are always in the fingerprint payload, even when None, so every pre-slice cache entry misses. Accepted; unit tests compare equality, not golden hex.
- Pydantic warning on field name `register` left in place so the on-disk field matches this document.
- K6 (Bold Devanagari) not done; Regular + slab, as the brief allowed.

**Not done (out of slice):** stamp/counter/meter/comparison/correction/question rendering, K3 density pass, K4 contrast, K5 palette, K6 Bold, K8 charts, K9 LLM authoring.

Stopping for human review. No push, no PR.
