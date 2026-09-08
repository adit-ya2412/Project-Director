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
Creative decisions only, canon 3.1 (no colours, no positions, no pixels):

```
EmphasisCue:
  device:          stamp | counter | meter | comparison | correction | pivot | question
  anchor_fragment: int         # WHICH WORD - index, never seconds
  text:            str
  register:        hi | en     # see Open Question 4
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

### K6 — Vendor a heavy Devanagari weight  **(PREREQUISITE)**
`backend/vendor/fonts/` ships `NotoSansDevanagari-Regular.ttf` only.
Chromium synthesises bold and it smears the matras, so every spike beat
ran at weight 400 and got impact from size and slabs. Vendor
`NotoSansDevanagari-Bold.ttf`. Latin is fine on this host (Arial Black,
Segoe UI Black, Impact, Bahnschrift) but **do not depend on host fonts**:
`captions.py` passes libass an explicit `fontsdir=` precisely to avoid
"host-fontconfig non-determinism". Vendor every face the compositor uses.

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

**Consequence: K6 (vendor a Bold Devanagari) is now a PREREQUISITE, not
a polish item.** With Devanagari carrying the pivot and corrections - the
two loudest beats - Regular-only forces both onto slabs for weight. Slabs
are the right default anyway (contrast robustness), but the choice should
be design, not a font limitation.

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
