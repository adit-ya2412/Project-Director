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
| **K7** compositor seam | **proven end-to-end 2026-09-09** — `renderer/compositor.py` + props-driven `Pivot.tsx`/`Emphasis.tsx`. Fingerprint hooks (`emphasis_cue_hash`, `emphasis_font_hash`) are in and correctly separate from `cue_list_hash` |
| **K9** emphasis pass | **implemented 2026-09-09; one of two review findings fixed and measured, the other measured and NOT reproduced** — whole-film LLM call authors `pivot`/`stamp`/`counter` plus the palette pair; K3 still enforces; lexical `attach_pivot_cue` is the pivot backstop. Stamps now prefer concrete nouns and the brand reaches the screen (3 of 5 live runs vs 0 of 2 before). Density: no prompt wording raised the delivered rate above the 8.51/min floor across 5 live runs; the binding number is `_build_user_content`'s `Target cue count`, not prose. See the 21:0x log entries |
| **K3** enforcement rules | **implemented 2026-09-09, reviewed and the three findings fixed same day** — shared pass in `app/timeline/emphasis_rules.py`; `text_card` rule moved out of `pivot.py`; graphic signal is planner-authored `Shot.picture_is_graphic` (option 1). Safe-zone geometry deferred (no plate at authoring time). Review applied: `min_shot_gap` is an index distance (the off-by-one made the effective gap 4, measured 8.57/min instead of the band's 12.00/min); the citation matcher now reads spelled-out Devanagari-Hindi/English numbers and decimals, reusing `caption_romanizer.numerals`, plus romanised Hindi (added 2026-09-09, guarded against English-word collisions); the call site's two knobs are pinned by a step-level test |
| **K4** contrast adaptation | **done 2026-09-09, reviewed same day** — render-time plate luma → light/dark/slab on OverlayCue. Slab default for retention_fast. The bright `2025` plate is never `light`. Review applied: band box is now Python-authoritative and travels through the props; `LIGHT_MAX_LUMA` 90 → 105 on six measured plates; the measurement is kept and logged under the slab policy; one decode per plate |
| **K5** palette resolution | **implemented and reviewed 2026-09-09** (`4a8c00a`) — scenario A, planner-authored and recorded on the timeline (decision 7). The accent and the pivot ground are palette; white/ink stay K4's contrast treatments | Review: one finding, a near-white `pivot_ground` renders invisible white-on-white; fixed separately. Only the channel and band rungs are reachable today — see K5's task section.
| **K6** reach the vendored Bold | **done 2026-09-09** — was never a download |
| **K11** device renderers (stamp, counter) | **implemented 2026-09-09; two render-found defects fixed same day** — stamp + counter renderers; unblocks K9. The counter band is now content-derived (its type overflowed a hardcoded 420 by 118px, measured) and `treatment="dark"` gained the light halo it never had |
| **K8** data graphics | **not started** |
| **K12** planner authors `picture_is_graphic` | **implemented and reviewed 2026-09-09** (`23f83e9`) — Shot Planner authors required `ShotPlanOutput.picture_is_graphic` (no default) and maps it onto `Shot`. Live re-plan: data shot True, ordinary shots False. K3 already enforces. K8 unblocked on the signal, not yet implemented |
| **K16.7 / K16.8** what the captioned reel showed | **K16.7 DONE 2026-09-10; K16.8 DONE 2026-09-10 (awaiting review)** — outline FIRST then LIGHT_MAX_LUMA 105→175 (K16.7); `RenderStep.is_satisfied` now compares stored vs current render fingerprint via shared `resolve_render_inputs` (K16.8). Missing render row → unsatisfied. Binding mtime gate kept. Pivot.tsx untouched. |
| **K16** captions carry the text | **K16.1 + K16.2 + K16.3 + K16.4 + K16.5 + K16.7 + K16.8 in 2026-09-10; finding 1 FIXED; finding 3 FIXED; highlight size/weight/colour fingerprint hole FIXED; is_satisfied fingerprint FIXED (awaiting review). Awaiting watched reel — do not imply a render was done.** — captions ON; Feature A highlight size/weight plus palette accent colour (`#00D9FF` → `{\fs102\b1\c&HFFD900&}`); `emphasis_slab_default=False`; stamp top 0.18; LIGHT_MAX_LUMA=175 after outline. `caption_highlight_size_fraction`/`caption_highlight_bold`/`caption_highlight_colour` are unconditional fingerprint inputs (`None` when `burn_captions` is False). **Not done:** K16.6 translucent figure. Pivot.tsx look unchanged. |
| **K15** a multi-word stamp has no band | **DONE 2026-09-10, unwatched** - `stamp_band(w, h, text=, text_register=)` fits the phrase to ONE line (largest font inside `width - 4*pad`) and `Stamp.tsx` sets `whiteSpace: nowrap`, so a wrap is impossible even on a bad measurement. Devanagari widths are REAL metrics at the **wght=700** instance (the `hmtx` default is 8-10% narrow — the error that puts the wrap back); Latin reuses K11's measured Black stack, max of the two faces. Band tracks the fitted font, so K4 still measures inside the drawn ink; K4 thresholds unchanged. Character budget 10 Latin / 14 Devanagari in `emphasis/v1.md`, derived from a 90px floor on rendered frames. All 9 rendered cases one line, ink inside slab; the single-word control is byte-identical (same PNG md5, same cue and overlay hashes). Fallback NOT needed. Open, pre-existing and smaller than before: Devanagari matras clip 0.15 em against `lineHeight: 1` on a slab (`लेकिन` at 190 loses 15px today) |
| **K14** the hook is empty | **implemented 2026-09-10, four review findings fixed same day, awaiting watched reel** — hook window 5.0s / gap 1; **K14.2 body-only 12.0/min cap** (hook cues extra; did not raise the whole-reel ceiling); K9 prompt + `Target cue count` front-load at 12.0/min with the hook floor now **clipped to how many shots start inside the window** (2 on the watched shape, not 3); the body gap counts from the last kept **BODY** cue, so the hook no longer opens a dead zone just past itself; stamp word delays scheduled against the cue's real window instead of a fixed 0/4/14/24. K14.6 not done. **The longest empty stretch did NOT improve on the probe (5.46s → 6.73s hold-aware): the body-only cap trims in film order, so the reel's LAST cue is what goes.** A NEW project is required (`34dd1ee1` cannot be re-authored). BLOCKS captions-off until the numbers beat 7.15s / 7.29 per min / 7.75s |
| **K13** the counter has no reachable input | **not started, ADDED 2026-09-09, BLOCKING** — number-stating shots are planned as graphics, K3 rule 2 forbids cues there, so the counter is unreachable. First real reel produced 0 counters from 3 spoken numbers. Recommended fix: stop the Shot Planner making number shots into graphics (option B) |

**Why shipping the pivot first worked without K6.** The pivot is the one
device whose weight comes from its slab rather than its font, so a
Regular-only Devanagari is enough for it and only for it. Every other
Devanagari device needs K6.

### Proven end-to-end 2026-09-09 (project `3b6dcf8b`, `k7-pivot-test`)

First real workflow run carrying a cue. 30s target, 402-char Hinglish
script with a pivot; 8 shots; the seven unfilled ones bound by uploading
images from the SUV reel (`fba52b6d`) through
`POST /shots/{id}/override`, which cost nothing. **Total spend: 21c.**

What it proved, in order: `EmphasisPassStep` attached one pivot cue
(v9, `emphasis_pass_attempted=True`); `NarrationStep` appended v10 with
`narration_locked=True`; the render invoked the compositor for real,
writing `overlays/ffaa2979....mov` (16.7 MB) plus its props sidecar; the
props carried `startFrame: 302` = 10.07s, matching the cue's shot start
exactly; and the production filter fragment composited it. The delivered
frame at 10.55s shows the red band with a genuinely bold `लेकिन` on the
narration's own beat.

Four things this run corrected or exposed:

- **The approval gate requires EVERY shot filled BEFORE approval.** This
  document assumed the paid generation pass fills them after. It does not
  — `approve_timeline` refuses with "these shots have no image yet" and
  points at `override` / `generate`. The post-approval pass only upgrades
  shots that already have a binding. Consequence for K9: when the
  emphasis pass runs, pictures do not exist yet; when the RENDER runs,
  they all do. Any rule that needs to know what a shot's picture IS (K3's
  graphic-asset exclusion, K4's contrast measurement) can only run at
  render time, not at authoring time.
- **`offset_s = 0.0` is an ambiguous value, and it is a test-design
  trap.** It is simultaneously the schema default and the CORRECT answer
  whenever a cue anchors to its shot's first fragment — which is what
  happened here, because that scene opens with `लेकिन`. So this run
  verified K2's write path (`narration.py` line ~645 does set it) but NOT
  its arithmetic. Any K2 test using a first-fragment cue proves nothing.
  **Assert on a cue that lands MID-shot, where a correct resolver must
  return non-zero.**
- **The confirm-cost figure is not a ceiling.** The gate demanded
  `confirmed_cost_cents=17` (5 spent + 12 estimated) and the run finished
  at 21c, because the remaining estimate does not account for
  `GenerateDiegeticSfxStep`. Harmless against a 1000c cap, but do not
  read it as a budget.
- **Length calibration:** 402 characters at `narration_speed=1.4`
  produced 21.6s, i.e. roughly 19 chars/second of finished reel. A 30s
  target wants ~560 characters.

Captions are still burned in (romanized) — expected, since switching them
off is deliberately sequenced after the cue system (Decision 1).

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
5. **K11 — device renderers for `stamp` and `counter`.** ADDED
   2026-09-09 and it comes BEFORE K9, not after: the compositor can draw
   only `pivot`, so K9 would author cues nothing can render. Also the
   first real consumer of K4's `treatment`.
6. **K9 — the real emphasis pass.** Replace the stub with the whole-film
   LLM call. Do this only once 1-5 are in place.
7. **K8 — data graphics.** Last, and largest.

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
carries `cited_fragment`, and code verifies that the fragment's narration
text STATES that number — as digits (`200000`, `2,00,000`), as digits
plus a scale word (`2 lakh`, `2.5 lakh`), or spelled out in Devanagari
Hindi (`दो लाख`, `दो हजार छब्बीस`, `पाँच`), in romanised Hindi (`do
lakh`, `das lakh`, `paanch`) or in English (`two lakh`, `five stars`).
A chart made entirely of inferred numbers is rejected. In the SUV case `2,00,000` is
the anchor and the five earlier years are inferred.

Be precise about what that check proves, because the drop is logged as
`rule=values_citation` and gets read as an accusation (corrected
2026-09-09; the earlier wording here claimed only that a value's
"digits appear", which was both too narrow — the narration spells
numbers out, in two languages — and too strong). A KEPT value proves
only that the number is FINDABLE in the cited fragment under the
readings `emphasis_rules._fragment_contains_value` implements: not that
the sentence is about it, and not that the number is true. A DROPPED
value proves only that THIS matcher could not find it — it is not
evidence the model invented a number. The matcher is deliberately
lenient and still incomplete, and every gap in it is on the side of
dropping rather than forging. Not read: English compounds (`twenty five
lakh`); ordinals, fractions, ranges and percentages-of; the romanised
`sau`/`hazaar` tier (`do hazaar chhabbis`, `unnis sau ikatees` — Hindi
puts the remainder AFTER those tiers, so a two-token read would state
2000 or 1900, numbers the narration did not say, and no closed Latin
table exists to parse the whole run the way `caption_romanizer.numerals`
parses the Devanagari one); a romanised spelling that collides with an
ordinary English word, unless a scale word sits beside it (`do lakh` is
200000, `I do think` is nothing); `so` for `सौ` at all, because "do so"
is ordinary English and 200 would be a FORGED citation; and a bare scale
word carrying no coefficient (`lakh` alone). Widen it when a real miss
is measured — never in a way that can invent a citation — rather than
treating it as a hallucination detector.

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
**Status (2026-09-09): implemented, then reviewed and the three review findings fixed the same day.** Shared pass in `emphasis_rules.py`; graphic rule unblocked via planner-authored `Shot.picture_is_graphic`. Density is an INDEX distance (gap 3 keeps shots 0, 3, 6, …), values citation reads spelled-out numbers in Devanagari Hindi, romanised Hindi and English (romanised added 2026-09-09 — it is the script this pipeline's narration is actually written in; colliding spellings like `do`/`char` are read only next to a scale word, and `so`/`sau`/`hazaar` are not read at all, because forging a citation is worse than missing one), and the step's two band knobs are pinned against a silent swap.
In code AFTER the planner returns, same discipline as
`resolve_picture_path` and the same shape as the project-wide text-card
spacing pass:

- At most one cue per shot.
- **Mutually exclusive with `text_card`** — measured: a stacked
  correction landed on "The Myth and the Burned Scroll", both unreadable.
- **Never over an asset that is already a graphic** — measured, and
  **CURRENTLY UNIMPLEMENTABLE. See the blocker below.**
- **Every `values[]` entry must cite a fragment whose text contains that
  number.** Drop the cue otherwise.
- Density cap and min-gap per band. Kinetic text stops working the moment
  it is constant: it becomes the baseline and nothing punctuates. **This
  is the rule most likely to decide whether K9's first output is any
  good, and it is the one still missing.**
- **Per-SHOT safe zones, not per-video.** The spike's zones were read off
  one frame, right at 1.3s and wrong at 4.3s.

Note on sequencing: with one pivot cue per reel, NONE of these bite yet.
`pivot.py` carries the `text_card` exclusion inline and that has been
sufficient. K9 removes that guarantee in a single step, which is why the
enforcement pass has to exist first. K3's first job is a MOVE, not new
code: promote the `text_card` rule out of `pivot.py` into the shared
pass.

#### BLOCKER: "is this asset a graphic?" has no answer in the data

The rule exists because of a measured failure — at t=4.3s a counter
landed on an AI-generated infographic (bar chart + dealership report +
dense labels) and both became unreadable. To enforce it, code must ask
whether a shot's picture is a chart. Nothing can answer:

- `MediaKind` is `STILL | MOTION` — that is "photo or video", not
  "picture of what".
- The `asset` table records provider, source_url, type, licence,
  attribution, content_hash, confidence, description. None describes
  subject matter.
- Measured 2026-09-09 on `fba52b6d`: **all 26 assets are `type=image`**
  (24 `provider=project_assets`, 2 `pexels`) and `description` is EMPTY
  on every one. The infographic and the photograph of the Creta are the
  same row with the same values.

Three ways to create the signal, needing a human decision:

1. **Planner-authored field (recommended).** The planner wrote the
   prompt that ASKED for an infographic, so it knows at authoring time.
   A field on the shot or `asset_plan`; free, deterministic, reviewable
   in the timeline like every other planner decision. Covers GENERATED
   assets, which is what actually broke.
2. **Prompt-text heuristic.** Grep the shot's own `prompt` for
   chart/infographic/diagram. Zero cost, no schema change, fairly
   reliable because planner prompts are formulaic — but false-positives
   on "a chart on the wall behind him".
3. **Vision classification.** `settings.openai_vision_model` already
   exists for constraint checks. Costs a call per shot, and is the only
   option that works on assets the planner did not author — Pexels
   results and human uploads via `POST /shots/{id}/override`.

**One decision unblocks two tasks, at opposite polarity.** K3 asks "is
this a graphic? then do NOT put text on it". K8 asks "is this a data
shot? then DRAW it instead of generating an image". K8 is the higher-
value consumer: that infographic does not merely collide with text, it
fabricates five of its six numbers from a one-number script and renders
partly garbled Devanagari.

### K4 — Contrast adaptation
**Status (2026-09-09): implemented, then reviewed and revised the same
day.** Render-time plate luma → light/dark/slab on `OverlayCue`. Not a
planner field. Measure each cue's own plate (mean luma, local luma under
the cue's box) and choose light type / dark type / slab. Slab is the
default for this style. This is the task that would have caught `2025`.

#### What the 2026-09-09 review changed

**1. The band box is Python-authoritative and travels through the props.**
As first shipped, the pixel box K4 measured was a hand-copied mirror of
five layout constants in `compositor/src/Pivot.tsx` (`top 380`,
`font 132`, `pad 18` on a 720x1280 reference canvas). Nothing tied the
copies together. Moving the band in the TSX would have left Python
measuring the old rectangle and choosing a treatment for a place the
text is not — **no exception, no ffmpeg error, no failing test.** It was
the only failure mode in K4 that was completely silent, which is why it
was fixed first and fixed structurally rather than with a guard:

```
pivot_band(canvas_w, canvas_h) -> PivotBand      # app/renderer/compositor.py
      |                                          #   the ONE definition
      +--> PivotBand.box_on(plate_w, plate_h)    # the rectangle MEASURED
      +--> PivotBand.as_props()                  # the rectangle DRAWN
      +--> PivotBand.hash_payload()              # overlay cache + fingerprint
```

The band is resolved once by `collect_pivot_overlay_cues` (which now
takes the canvas), carried on `OverlayCue.band`, and shipped to the TSX
as `cue.band`. `Pivot.tsx` positions itself from that prop and holds no
production layout arithmetic. Its `SPIKE_*` constants survive **only** as
a fallback for the standalone spike compositions (`SuvRetention.tsx`
passes no band) and are labelled as such in the file. Drift is now
impossible by construction: the measured region is the drawn region
because they are the same numbers.

**Props contract, before → after** (`_overlay_props`, per cue):

```
before:  device, text, textRegister, startFrame, endFrame, treatment
after:   device, text, textRegister, startFrame, endFrame, treatment,
         band: { left, top, width, fontSize, pad } | null
```

`band` is hashed into `overlay_input_hash` AND
`emphasis_cue_content_hash`. The five band constants are code, so
editing them must invalidate both the `.mov` and the cached `final.mp4`
— otherwise the plan's own fingerprint warning applies and the render
step serves a video with the band in its old place. **Consequence,
correct and expected: every overlay and every render fingerprint from
before this change misses once.**

Two things deliberately left as they are, both recorded in
`PivotBand.as_props`:

- `height` is NOT in the props. The drawn band's height comes out of
  `fontSize`, `pad` and the CSS line-height (1.1, needed for Devanagari
  matras above the shirorekha), so it measures ~183px against the
  nominal `font + 2*pad = 168`. The nominal number stays the *measured*
  one because it is the box the threshold below was derived through;
  widening it moves 98.3 → 100.6 and 108.6 → 103.3 and silently inverts
  that argument. Forcing the drawn band down to 168 instead would change
  a look the plan says twice not to change. The residue is bounded and
  on the safe side — the measured slice sits inside the drawn band.
- `box_on` maps the band by its **fraction of the canvas**, because
  `shot_images` holds the raw resolved asset (often 1920x1080), not a
  canvas-sized frame. Recomputing the band from the asset's own
  dimensions was subtly wrong on any non-matching aspect: font (hence
  band height) scales with width while top scales with height, so on
  1920x1080 the old code measured a slice 0.35 of the picture tall where
  the drawn band covers 0.13. Still an approximation — the ken-burns
  crop decides which asset pixels actually land under the band, and
  knowing that exactly means extracting the rendered frame. Out of
  scope; the fractional map is strictly closer than what it replaced.

**2. `LIGHT_MAX_LUMA` 90.0 → 105.0. `DARK_MIN_LUMA` stays 180.0.**
Measured, not chosen. Six plates, one per moment the hand-built spike
put type on screen, taken through the band box `(0, 380, 720, 548)` on
`tmp/suv_test/plate_nocaptions.mp4` (720x1280, reproduced 2026-09-09):

| t (s) | box luma | frame mean | what the spike drew there |
|---|---|---|---|
| 1.30 | **98.3** | 99.6 | bare white type — **inspected, read well** |
| 2.20 | **108.6** | 88.7 | dark slab — bare type **never tested** |
| 3.00 | **236.9** | 231.7 | bare white `2025` — **washed out** |
| 4.30 | 190.1 | 199.0 | counter on an infographic (the other failure) |
| 5.20 | 159.8 | 105.5 | red pivot band (slab, brings its own ground) |
| 5.90 | 132.2 | 98.6 | lower band (slab) |

- 98.3 is a **measured good case that 90.0 excluded.**
- 236.9 is the failure this feature exists to prevent; 105 still calls
  it `dark`, with 132 units of clearance.
- 108.6 is the nearest plate above the good case and is **unproven**, so
  105 admits the one proven case with ~7 units of margin and stops below
  it.
- **Worth stating plainly: at 90.0, `light` never fired on ANY plate in
  the reference reel.** The branch had zero coverage in real data —
  only in synthetic test fixtures. It was never a measured floor, just a
  cautious one. At 105 exactly one real plate reaches it.
- `DARK_MIN_LUMA` does not move: 190.1 is the only reference plate above
  it, dark type there was never inspected either, and unlike the light
  side there is no measured good case asking the boundary to shift.

Note on the plan's own `216`: the historical figure for the `2025` beat
is not reproducible to the digit. Re-measured, that frame is 236.9 in the
band box and 231.7 as a frame mean, and the archived
`tmp/suv_test/fail_2025.png` reads 228.8. `SUV_T3_MEAN_LUMA = 216.0`
stays as the name the plan, the commit history and the regression test
all speak in; every one of those values is far above 180 and classifies
identically, so nothing downstream turns on which is used.

**3. The measurement is kept under the slab policy, and logged.**
`retention_fast` sets `emphasis_slab_default=True`, so `choose_treatment`
returns `slab` for every cue it currently emits and the measured luma
changes nothing on frame. The tempting optimisation — skip the decode
when the policy is on — is **explicitly rejected**: a PIL decode of one
still is a few milliseconds against a render measured in minutes, and
the measured numbers are the only thing that will let a human relax the
policy with evidence rather than a second guess. The threshold move in
(2) is exactly that kind of decision, and it was only possible because
somebody went and measured.

So `apply_emphasis_treatments` emits one `emphasis_contrast.treatment`
line per cue carrying: `device`, `shot_id`, `measured`, `luma`,
`treatment`, **`threshold_treatment`** (what the floors alone would have
picked), `slab_default`, **`policy_override`**, both thresholds, and
`band_box`. Every render now accumulates the calibration data for free.
The reason not to optimise it away is written next to the code, in the
`emphasis_contrast` module docstring and in `choose_treatment`, because
someone will see a discarded value and try.

**4. One decode per plate.** `measure_plate_luma` used to open and
convert the bytes to learn the image size, then call `mean_luma`, which
opened and converted the identical bytes again. Both paths now share
`_mean_luma_of_image` and decode once. Error behaviour is unchanged and
deliberately non-uniform: empty bytes RAISE out of `mean_luma`; empty,
missing, unreadable or non-image bytes return `None` from
`measure_plate_luma` and log; `None` becomes `slab` at the chooser.
A render must not fail because a shot resolved to a motion clip, and an
unmeasured plate must never default to `light` — that is the 2025 bug in
another costume.

### K5 — Palette resolution  **(DECISION RECORDED 2026-09-09: scenario A)**
Precedence: `human override > per-project planner-authored (recorded) >
channel default > style band default`. Unset must produce something
correct — it falls back to the style band default, never to a second
colour-choosing system.

Authored once by a planner and recorded on the timeline; see decision 7.
NOT sampled at render time. Whatever chooses the colour should pick an
accent that OPPOSES the film's dominant hue — matching makes type sink
into the picture.

**Which colours are actually palette, and which are not.** Measured in
the tree on 2026-09-09, the three device renderers hold four hexes
between them:

| hex | name | belongs to |
|---|---|---|
| `#FFC300` | amber (`Stamp.tsx`, `Counter.tsx`) | **palette** — the accent, the colour a number or a stressed word is drawn in |
| `#FF2E2E` | red (`Pivot.tsx`) | **palette** — the pivot band's ground |
| `#FFFFFF` | white | **not palette** — this is K4's `light` treatment |
| `#0A0A0B` | ink, and the `rgba(10,10,11,0.88)` slab ground | **not palette** — K4's `dark` and `slab` |

So a palette is at least a pair (accent + pivot ground), not one colour,
and K5 must not absorb the contrast decisions K4 already owns. Leaving
white and ink alone is a requirement, not an omission.

**Which rungs are actually reachable (2026-09-09).** Two of the four are
live; two are aspirational, and nobody should build a route for them
speculatively:

| rung | reachable today | how |
|---|---|---|
| human override | **no** | `emphasis_palette_override` has no API route. `grade_style` — the field this was modelled on — does have one (`api/projects.py`), so the analogy is only half-built. Deliberately NOT built: nothing authors a palette yet, so there is nothing to override. Build it when K9 picks a colour a human wants to change on ONE reel without re-planning |
| planner-authored | **no** | K9's job. `emphasis_palette` is written by nothing today |
| channel default | **yes** | `EMPHASIS_ACCENT` / `EMPHASIS_PIVOT_GROUND` in `.env`. `Settings` has no `env_prefix`, so the field names ARE the env var names. This is the knob a one-person channel actually reaches for |
| style band | **yes** | `retention_fast` records the spike pair |

So K5 changed no output on its own: every reel still resolves to
amber + red. The slice built the mechanism for per-video colour, not
per-video colour itself. That arrives with K9.

**The seam.** The resolved palette reaches the renderers the same way
`treatment` and `band` already do — resolved in Python, passed through
props. Never read from inside the compositor, and never a second
resolution site (RV2 / R1): resolve once, pass the values in.

**What this slice must answer by measurement rather than preference:**
what a stored timeline with no palette renders as (the fallback must be
watched, not assumed correct), and whether an authored accent can be
illegible enough that K4's contrast chooser fights it — an amber-on-amber
plate is the case to look for.

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


### K11 — Device renderers: `stamp` and `counter`  **(ADDED 2026-09-09, implemented 2026-09-09, pending review)**

**This is the task that unblocks K9, and it was missing from the plan.**

`compositor/src/Emphasis.tsx` reads
`if (cue.device !== "pivot") return null;` and
`collect_pivot_overlay_cues`'s docstring says "unknown devices are
ignored". So the pipeline can author seven device types and DRAW exactly
one. Point K9 at this today and it would emit `stamp`/`counter`/
`correction` cues that are silently dropped at both ends: an LLM call, a
plausible timeline, and a video with nothing new on it, with no error
anywhere. That is the worst failure shape available - expensive,
invisible, and it reads as "the prompt is bad" when the prompt was fine.

**Port, do not invent.** `compositor/src/SuvRetention.tsx` already has
both devices working and watched, hardcoded to one film's onsets:
`stamp` as a word-by-word drop-in with spring overshoot and per-CLUSTER
stagger (`Intl.Segmenter`, never `split("")` - see "Devanagari
typography"), `counter` as a value counting to a target with
`Intl.NumberFormat("en-IN")` grouping plus the filling meter. Copy
`Pivot.tsx` + `PivotBand` + `collect_pivot_overlay_cues` as the
props-driven pattern. Leave `SuvRetention.tsx` / `DirectedHook.tsx`
alone; they are labelled spike proofs.

Four gaps this will hit, all real:

- **`OverlayCue` has no `values`**, so a counter has no target number.
  `EmphasisValue` (value / unit / cited_fragment) exists on
  `EmphasisCue` but does not reach the compositor. It must go into
  props AND into both `overlay_input_hash` and
  `emphasis_cue_content_hash` - missing the cue hash means editing a
  target number keeps the hash and `RenderStep` serves a cached
  `final.mp4` with the old figure.
- **`PIVOT_HOLD_S = 0.91` is pivot-specific.** Each device needs its own
  hold, still clamped so a cue cannot outlive its shot or the film.
- **`treatment` (K4) currently has NO consumer.** The pivot ignores it
  because the device IS a slab. `stamp` is the first device that must
  branch on light/dark/slab, which means K4's entire decision is
  untested against a real device until this lands.
- **`band` is pivot-only geometry.** Either give stamp/counter their own
  (Python-authoritative, passed in props, never duplicated in the TSX -
  finding 3) or none. With no band, K4 falls back to the frame mean:
  say so in a comment, because that is a measured loss of precision
  (frame vs box diverged by 54 luma units on a real plate).

**Verification needs no K9.** Construct `OverlayCue` objects directly
and call `render_or_reuse_emphasis_overlay` for `fba52b6d`, then ffprobe
for `yuva444p*`, composite with the production filter fragment, and LOOK
at a frame per device. A lost alpha channel renders a black rectangle
rather than raising.

#### Two defects, found only by rendering, fixed 2026-09-09

Both shipped in `f19370b` behind 592 green tests and clean lint, which
is the point: neither is reachable from a unit test. They are pixel
facts, and the K11 work skipped the live render.

**1. The counter's type overflowed its own slab. FIXED — the band width
is now derived from the content.**

`_COUNTER_REF_BAND_WIDTH = 420` was the band WIDTH. `2,00,000` plus a
unit at font 116 does not fit in 420, so the band described a region the
type EXCEEDED — the exact inversion of the invariant in `Emphasis.tsx`
("the treatment can no longer describe a region the type does not
cover"). Measured on a real 720x1280 render, on the overlay's own alpha
so the plate cannot confuse the reading (`tmp/k11_fix`):

| | declared band | slab drawn | type drawn | inside? |
|---|---|---|---|---|
| before (420) | x 150..570 | x 150..569 | x 171..**687** | **no — 118px out** |
| after (derived) | x 17..703 | x 17..702 | x 100..617 | yes, 83px / 85px margin |

Both rows are the SAME cue (`value=200000, unit="+"`, kicker "SOLD IN A
YEAR", `treatment="slab"`) drawn by the same TSX in the same render; the
only difference is the rectangle Python resolved. In the composite the
before-frame reads the way the defect was first reported: amber digits
to x=635 and the white `+` beyond it, against a scrim ending at x=570.

The width is `max(420-scaled, digits + unit + 2*pad)`, so the spike look
survives for every value that fits inside 420 and the box grows only
when it must. **Sized to the FINAL value, not the current one** —
`Counter.tsx` re-formats `round(t * target)` every frame with no
padding, and the count only goes up, so the final value is the widest
string the cue ever shows; a band tracking the current value would have
to be a different rectangle every frame, which this design cannot
express (one band, measured once by K4, hashed by both caches). The cost
is a slab slightly wider than the digits early in the count, centred, so
it reads as margin.

The estimate is a glyph count times a per-em advance ratio biased WIDE
(0.70 em per tabular digit, 0.40 per group separator, 1.10 per arbitrary
glyph), measured from the `hmtx` tables of the faces the CSS stack
actually resolves to — Arial Black digits .667 is the widest in the
stack, Segoe UI Black `W` 1.053 the widest glyph of any kind. Erring
wide leaves unused slab; erring narrow reproduces the bug. Consequences
recorded rather than hidden: a 7-digit target with a unit now rounds up
to a full-bleed band, and a target too long for the canvas at font 116
is clamped with a `compositor.counter_band_exceeds_canvas` warning
instead of silently overflowing.

One value, three readers still holds, and it is now tested: widening the
band moved `box_on` (the plate measurement of `k_4.30.png` through the
counter box went 185.75 → 197.61 luma), `emphasis_cue_content_hash` and
`overlay_input_hash`.

**2. `textShadow` was on the wrong treatment. FIXED — `dark` gets a
light halo.**

`treatment === "light" ? SHADOW : "none"` had it backwards. `light`
means the plate measured DARK, so white type already has a dark ground
and the dark shadow adds little; `dark` means the plate measured BRIGHT
(the 236.9 SUV plate) and near-black type had NO protection at all,
which is where black type loses its edges on an uneven plate. `dark` now
gets `HALO` — two white glows, tight 10px at 0.95 plus wide 26px at 0.8,
and no offset ledge, because offsetting a light halo protects one side
of each glyph and an uneven plate is uneven in no direction. `SHADOW` is
unchanged (`light` was never the broken case) and `slab` still gets
neither, since the device brings its own ground. Measured on the
overlay's alpha, where a halo cannot hide: for `treatment="dark"` the
stamp draws ink type on transparency and nothing else white, so
near-white partial-alpha pixels are the halo and nothing else — ink
x 136..459, halo x 117..478, 28,761 such pixels. Pre-fix that count is
zero by construction.

### K12 — The planner authors `picture_is_graphic`  **(ADDED 2026-09-09)**

K3 added `Shot.picture_is_graphic: bool = False` and enforces it as rule
2 of `enforce_emphasis_rules`, but nothing ever sets it. The rule is
therefore unreachable in production, and K8 — which reuses the same
signal at the opposite polarity ("this IS a data shot, so DRAW it") — is
blocked behind it. This task is only the wiring; K3 already owns the
enforcement.

**Why the Shot Planner and not the Asset Planner.** The field lives on
`Shot`, and the Shot Planner is what authors `Shot.prompt` — the prompt
that ASKS for an infographic — so it is the one stage that knows at
authoring time. `Shot.asset_plan` is filled by planner CODE afterwards
and is never on `ShotPlanOutput`, so an LLM could not populate a field
hung there. The prompt already distinguishes picture kinds for `sfx_cue`
("a portrait, a document, a map, a diagram, or a text card",
`prompts/shot_planner/v1.md`); keep the two consistent rather than
inventing a second taxonomy.

- Add to `ShotPlanOutput` (`planners/shot/schemas.py`), additive default
  `False`, and map it through `planners/shot/planner.py`.
- Teach `prompts/shot_planner/v1.md` when to set it: the picture's job is
  to DISPLAY INFORMATION — chart, graph, diagram, infographic, dashboard,
  table, map-with-data — not to show a scene.
- **Verify with a real re-plan, not a unit test.** A `retention_fast`
  project whose script carries a data line must come back with
  `picture_is_graphic=True` on that shot and `False` on the ordinary
  ones. Record the shot ids and the flag values. A green suite with no
  re-plan is not evidence: that exact gap shipped two defects in K7 and
  one in K11.

**The limitation, to be written down rather than designed around.** The
flag describes what the planner INTENDED to acquire. A Pexels search
result or a human upload via override was never described by the planner,
so the flag cannot speak for those. Vision classification stays the only
complete answer if that ever matters.

### K13 — The counter has a renderer and no reachable input  **(ADDED 2026-09-09, BLOCKING)**

Found by the first real end-to-end reel (`nexon-reel2-test`,
`0c23acfd`, 2026-09-09). A 24.63s `retention_fast` reel whose script
states three numbers out loud produced **zero counters**.

**The collision.** Every shot whose narration states a number was
planned as an infographic, so K12's flag went True on exactly those
shots:

| shot | narration | `picture_is_graphic` |
|---|---|---|
| `sc_02_sh_01` | *Safety rating mein **paanch** stars / Price bhi **das lakh** se kam* | True |
| `sc_03_sh_01` | *har mahine **bees hazaar** se zyada bikti hai* | True |

`planners/emphasis/planner.py` passes `picture_is_graphic` to K9 per
shot and `prompts/emphasis/v1.md` tells it those shots cannot carry a
cue, so K9 correctly declined to author there. K3 rule 2 would have
dropped them anyway. The result is structural, not stochastic:

**A counter needs a shot that states a number AND is not a graphic. The
Shot Planner reliably turns number-stating shots into graphics. So the
counter is close to unreachable, on every reel.**

K11 built the counter renderer and proved it draws. Decision 8
sequenced `correction`/`meter`/`comparison` behind renderers. Nobody
noticed the counter had the opposite problem — a live renderer with no
reachable input. It is also the device the user singled out as the one
that made the spike work ("the numbers that increase upto 2000").

**Two ways to fix it, and they are not equivalent.**

*Option A — exempt a slabbed counter from rule 2.* Allow a counter on a
graphic shot when its treatment is `slab`. Rule 2's original reason was
the spike's 4.3s failure, which was BARE type over a busy infographic;
K4's slab exists precisely to give type its own ground, and
`retention_fast` forces it. Cheap. But it puts an animated number on
top of a picture of that same number, which is duplication, and the
plate underneath is an AI-generated chart nobody asked for.

*Option B (RECOMMENDED) — stop the Shot Planner making number shots
into graphics.* Teach `prompts/shot_planner/v1.md` that a shot whose
narration states a figure should depict a SCENE, because the counter
will animate the figure over it. The plan's own evidence points here:
the spike's AI-generated "2 lakh sold" infographic was the **4.3s
FAILURE**, and the data-graphics honesty section already treats
AI-authored data pictures as close to forgery. An animated number over
a real photograph is both the honest option and the one that was
watched and worked. It resolves the collision at the source, and the
counter stops being unreachable rather than being excused past a rule.

Option B does NOT make K12 wrong. The flag is still needed for K8 and
for genuinely graphic material (a real archival chart, a document of
figures). B narrows what the planner CHOOSES to depict when narration
states a figure; it does not narrow what the flag means.

**Sequencing.** BLOCKING: do not spend generation money on a
`retention_fast` reel until this is fixed, because the reel cannot
contain its strongest device. Also note a fixed pipeline cannot be
verified on an existing project — `0c23acfd` is `narration_locked` with
`emphasis_pass_attempted=True`, so it can never be re-authored. Verify
on a NEW project.


---

## Decisions and open questions

All eight answered — six on 2026-09-08, the palette (7) and K9's device
scope (8) on 2026-09-09.
Density (5) is defined by a test rather than a fixed number - see below.

**1. Captions — ANSWERED 2026-09-08 (user), then STRENGTHENED, then
REVERSED 2026-09-10 by K16. READ K16 BEFORE ACTING ON THIS.** The
reference reel the user wants keeps captions ON and carries emphasis
INSIDE them. What follows is the superseded reasoning, kept because
its diagnosis of dense text was right even though its conclusion was
not.

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

**7. Palette resolution — ANSWERED 2026-09-09 (user): scenario A.**
The per-project palette is **authored once by a planner and recorded on
the timeline**. It is not sampled from the assets at render time, and it
is not a channel-wide constant.

Rationale, in the order it matters:

- **"Each video carries its own colours" becomes a recorded fact rather
  than an emergent side effect.** The reason for wanting a per-video
  palette at all was that the reels should not all look alike. A recorded
  field is the only version of that which survives a re-render.
- **It is where every other creative decision already lives.** Tone,
  visual style and on-screen register are planner-authored and immutable
  (I2). A palette is the same kind of statement about the film.
- **Rendering stays a pure function of the timeline (I5).** Choosing the
  accent from the pictures at render time would mean swapping a single
  asset silently changes the type colour of the whole reel, with nothing
  in the timeline recording why.

**What was rejected, and what survives of it.** Scenario B — derive the
accent from the film's dominant hue at render time — is rejected as a
*timing*, not as an idea: "pick an accent that OPPOSES the dominant hue"
stays good guidance for whatever chooses the colour, the planner
included. Scenario C (one channel accent for every video) was rejected
directly. Scenario D (A, falling back to B when unset) was rejected as
premature: an unset palette falls back to the style band default, which
is deterministic and already exists, rather than to a second
colour-choosing system nobody has watched.

**The precedence chain therefore closes** the `(LLM or derived)`
ambiguity in K5's original line — LLM, recorded:
`human override > per-project planner-authored (recorded) > channel
default > style band default`.

**8. Which devices K9 v1 authors — RESOLVED 2026-09-09 by the tree, not
by taste: the three that can be drawn.** `pivot`, `stamp`, `counter`.

This closes a contradiction between two documents that both shipped.
`EmphasisDevice` carries the full six-value set — `stamp`, `counter`,
`meter`, `comparison`, `correction`, `pivot` — deliberately, so later
devices do not churn the model, and its own docstring says "other
devices are ignored until they have a renderer". But the device-set
section above is headed "all in v1", and `Emphasis.tsx` dispatches
exactly three: `pivot`, `stamp`, `counter`. An agent reading the
device-set heading would have K9 author `correction`, `meter` and
`comparison` cues that pass K3's enforcement, land in the timeline,
cost tokens, survive into the fingerprint — and never appear on
screen. Silent, and expensive.

So K9 v1 emits only the three drawable devices. `EmphasisDevice` keeps
all six; the schema is not narrowed, because a later device must not
churn stored timelines (the reason the enum was written wide in the
first place).

**This is sequencing, not a reversal.** `correction` was answered
directly in decision 2 (option C) and is still wanted. It is behind a
renderer, not behind a doubt — and it deserves its own watched render
the way `stamp` and `counter` got one in K11, rather than arriving as a
side effect of K9 and being seen for the first time in a finished reel.
Same for `meter` and `comparison`.

**The device-set section's "all in v1" heading is therefore wrong as
written** and should be read as "all in the v1 *schema*". Corrected
here rather than by editing that section, because its per-device
descriptions are still the specification for whoever builds the
remaining three.



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
K11 device renderers                <- stamp + counter; K9 has nothing
 |                                     to author into without this
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
  regression case; it is in the repo history as a failure. (Re-measured
  2026-09-09: that frame is 236.9 in the band box, 231.7 as a frame
  mean. The `216` is historical and not reproducible to the digit; see
  the note under K4. The criterion is unaffected — all three values are
  well above `DARK_MIN_LUMA`.)
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
- Assert every chart has at least one anchored value that its cited
  fragment's narration text states — digits, digits-plus-scale-word, or
  spelled out in either language; reject charts with none. A pass here
  means "citable", not "true" (see the guardrail note above).
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

---

## Work log — K4 contrast adaptation (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 15:06 — starting

- read / opened: this plan (K4 task, architecture table, the two failures, done-criteria, fingerprint warning, "K4 cannot run at authoring time", K10 work log); `parallax.py::sample_substrate_colour`; `compositor.py` (`OverlayCue`, `collect_pivot_overlay_cues`, `emphasis_cue_content_hash`, `overlay_input_hash`, `_overlay_props`); `render.py` (shot_images populated before fingerprint ~237, overlay collect ~384); `fingerprint.py` emphasis docstring; `timeline.py` EmphasisCue (no treatment); `styles.py` StylePacingBand; `Pivot.tsx` / `Emphasis.tsx`; existing compositor/fingerprint/substrate_crop tests.
- decided: K4 only. Treatment is code-from-the-plate, on OverlayCue, never on EmphasisCue. Measure at RenderStep after shot_images exist (RV2: one resolved list to fingerprint AND compositor). Pivot drawing stays the red band. No K3/K5/K8/K9, no stamp visuals, no push, no PR.
- decided: local box for pivot mirrors Pivot.tsx spike numbers (top=380, font=132, pad=18 on 720×1280; full width; band height ≈ font+2*pad; scale like the TSX). Unusable box → frame mean. Unreadable/video plate → unmeasured → slab, never light. No ffmpeg frame-extract.
- decided: chooser takes `slab_default: bool`. retention_fast opts in via a band field + `resolve_emphasis_slab_default` (R1, like whoosh). Numeric floors live as module constants, not hues. luma 216 must not be `light` even with slab_default=False.
- files: this plan (K4 status line + this work log)
- tests: none yet
- next: pure measurement + chooser module, then OverlayCue/hash/render wiring, then tests

### 15:12 — measurement function

- read / opened: `sample_substrate_colour` (PIL, RGB convert, raise on zero-size); `Pivot.tsx` scale (`SPIKE_TOP * height/1280`, font `* width/720`, pad `* height/1280`).
- decided: new `app/renderer/emphasis_contrast.py`. Rec. 601 `Y = 0.299R + 0.587G + 0.114B`. `mean_luma` raises on empty/zero-size (never a guessed number). Local box for `device=pivot` is `(0, top, width, top + font + 2*pad)` — on 720×1280 that is `(0, 380, 720, 548)`. Unusable box falls back to frame mean. Video/garbage bytes: log `emphasis_contrast.unmeasured` and return None. No ffmpeg extract.
- files: `backend/app/renderer/emphasis_contrast.py`
- tests: not yet run
- next: chooser thresholds

### 15:13 — chooser thresholds

- decided: `choose_treatment(luma, *, slab_default)`. Unmeasured → slab, never light. `slab_default=True` (retention_fast) → always slab, even when dark/light would be legal — this style's policy, not a "always-slab-until-stamp" workaround; the floors are still real and tested with the policy off. `LIGHT_MAX_LUMA=90` (white type only on a dark plate). `DARK_MIN_LUMA=180` (black type only on a bright plate). Mid band (including ~128) → slab. luma 216 ≥ 180 so `dark` when policy off, `slab` when on, never `light` (white contrast at 216 is 39 units; the floor is well above that). Named constant `SUV_T3_MEAN_LUMA = 216.0`. No hues.
- decided: knobs: `StylePacingBand.emphasis_slab_default` (False additive default; True only on `retention_fast`) + `resolve_emphasis_slab_default`. Numeric floors stay module constants — they are a measurement fact, not a per-style mix knob. Resolve the bool once in RenderStep (RV2).
- files: `backend/app/script/styles.py`
- tests: not yet run
- next: OverlayCue / hash / render / compositor props

### 15:14 — render / compositor / fingerprint wiring

- decided: `OverlayCue.treatment` default `"slab"`, plus `shot_id` so the chooser can find the plate (not hashed — not a compositor pixel input). `collect_pivot_overlay_cues` still timing-only; `apply_emphasis_treatments` is the one place tests can drive without RenderStep. RenderStep: collect → apply (from `shot_images`, slab policy resolved once) → same list to `emphasis_cue_content_hash` and `render_or_reuse_emphasis_overlay`.
- decided: `emphasis_cue_content_hash`, `overlay_input_hash`, and `_overlay_props` all include `treatment`. Emphasis.tsx adds the field on props; Pivot drawing is unchanged (the device IS a slab). No `treatment` on planner `EmphasisCue`.
- files: `backend/app/renderer/compositor.py`, `backend/app/workflow/steps/render.py`, `backend/app/renderer/fingerprint.py` (docstring), `compositor/src/Emphasis.tsx`
- tests: not yet run
- next: unit tests

### 15:16 — tests

- files: `backend/tests/unit/renderer/test_emphasis_contrast.py` (new); `test_compositor.py` (treatment hash + collect sets shot_id); `test_fingerprint.py` (docstring); `test_styles.py` (resolver + retention_fast band pin).
- tests: `cd backend`; venv pytest on `test_emphasis_contrast.py`, `test_compositor.py`, `test_fingerprint.py` → **86 passed** in ~2.7s. Same plus `test_styles.py` → **130 passed**. One false start: a 0×0 PNG cannot be encoded by PIL (`SystemError: tile cannot extend outside image`); dropped that branch and kept empty-bytes → `ValueError`. Gated `tmp/suv_test/fail_2025.png` assertion is skippable; it is not a CI fixture.
- ruff: UP035 (`Mapping` from `collections.abc`) and I001 (resolver import order) fixed. Pre-existing B905 on `zip()` in `test_styles.py` left alone.
- next: work-log summary + local commit. No push, no PR.

### 15:19 — finish / summary

K4 is a render-time chooser. After `shot_images` exist, each overlay cue's covering plate is measured (Rec. 601 mean luma, local box under the pivot band) and `treatment` is set on `OverlayCue`. retention_fast always gets slab. luma 216 is never `light`, even with the policy off. Pivot still draws the red band.

**Files changed**

- Measurement + chooser: `backend/app/renderer/emphasis_contrast.py` (new)
- OverlayCue + hashes + props: `backend/app/renderer/compositor.py`
- Render RV2: `backend/app/workflow/steps/render.py`
- Band knob: `backend/app/script/styles.py` (`emphasis_slab_default`, `resolve_emphasis_slab_default`)
- Fingerprint docstring: `backend/app/renderer/fingerprint.py`
- Compositor props type: `compositor/src/Emphasis.tsx` (field only; Pivot.tsx untouched)
- Tests: `backend/tests/unit/renderer/test_emphasis_contrast.py`; `test_compositor.py`; `test_fingerprint.py` (docstring); `backend/tests/unit/script/test_styles.py`
- This plan (K4 status line + this work log)

**Decisions (also in the entries above)**

- Treatment lives on OverlayCue, never on planner EmphasisCue.
- Measure at RenderStep, not EmphasisPassStep. One resolved list to fingerprint and compositor.
- Local box `(0, 380, 720, 548)` on the spike canvas, scaled like Pivot.tsx. Unusable box → frame mean. Unreadable/video → unmeasured → slab.
- `slab_default=True` always returns slab. Floors (`LIGHT_MAX_LUMA=90`, `DARK_MIN_LUMA=180`) are tested with the policy off so luma 216 → `dark`, not `light`.
- Numeric floors are module constants, not band fields. Only the slab-default bool is on the band.

**Deviations from the plan**

- None material. `slab_default=True` meaning always-slab (rather than "earn bare type on this style too") is the stronger test the brief asked for, not a workaround. Stamp can later pass `slab_default=False` per-device if we want earned bare type on retention_fast.
- Did not add `treatment` to `emphasis_cue_content_hash`'s "values" (OverlayCue has no values yet; pivot does not use them).
- Gated extra assert against `tmp/suv_test/fail_2025.png` when present; CI does not need `tmp/`.
- Pre-existing ruff B905 in `test_styles.py` not touched.

**Not done (out of slice):** stamp/counter/year visuals, K3 density, K5 palette, K8, K9 LLM, pivot look changes, SFX, pacing.

Stopping for human review. No push, no PR.




---

## Work log — K4 review findings applied (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries. Four review findings against `1a8aade` ("Never white type on luma 216"); all four applied.

### 15:31 — starting

- read / opened: this plan (Current state table, K4 task, the two failures, done-criteria, the fingerprint warning, both prior work logs); `backend/app/renderer/emphasis_contrast.py` in full; `backend/app/renderer/compositor.py` (`OverlayCue`, `collect_pivot_overlay_cues`, `emphasis_cue_content_hash`, `overlay_input_hash`, `_overlay_props`, `_invoke_remotion`); `compositor/src/Pivot.tsx`, `Emphasis.tsx`, `Root.tsx`, `compositor/README.md`, `SuvRetention.tsx`'s `Pivot` wrapper (~line 289); `app/workflow/steps/render.py` (`shot_images` at ~241, overlay collect at ~385, filter chain at ~600); `app/renderer/fingerprint.py` emphasis docstring; `tests/unit/renderer/test_emphasis_contrast.py`, `test_compositor.py`.
- decided: finding 3 first, because it is the only one that can fail silently. Then 2 (needs the plate measured before anything else moves), then 1, then 4.
- decided: no commit, no push. Working tree only, for review.
- files: none yet
- tests: none yet
- next: reproduce the six reference-plate luma numbers before changing any threshold

### 15:33 — reproducing the measurement

- read / opened: `tmp/suv_test/` (the six `k_*.png` frames from the spike session, `fail_2025.png`, `plate_nocaptions.mp4` — 720x1280, 30fps, 359 frames, 11.97s).
- did: extracted t = 1.30 / 2.20 / 3.00 / 4.30 / 5.20 / 5.90 fresh with ffmpeg into `tmp/suv_test/_f2review/` and measured each through `measure_plate_luma(..., device="pivot")`.
- measured: **98.3, 108.6, 236.9, 190.1, 159.8, 132.2** — every one an exact match for the numbers in the review brief. Box confirmed `(0, 380, 720, 548)`.
- found, and it contradicts the plan: **the `216` figure for the t=3.0s beat does not reproduce.** That frame is 236.9 in the band box, 231.7 as a frame mean; the archived `tmp/suv_test/fail_2025.png` (same frame, spike-era encode) is 228.8. Recorded in the K4 section and beside `SUV_T3_MEAN_LUMA` rather than "fixed": every value is far above `DARK_MIN_LUMA`, the classification is identical, and 216 is the number the plan, the commit history and the regression test all speak in. Renaming it would churn three places to change nothing.
- files: none
- tests: none
- next: finding 3

### 15:36 — finding 3: the band box becomes Python-authoritative

- decided: geometry lives in `compositor.py`, not `emphasis_contrast.py`. `emphasis_contrast` already imports `compositor` for `OverlayCue`, so the reverse direction would be a cycle; and the band IS the props contract, so it belongs next to `_overlay_props`. No new module.
- decided: `PivotBand` frozen dataclass carrying the canvas it was cut for, with three readers and nothing else — `box_on()` (measure), `as_props()` (draw), `hash_payload()` (cache). `pivot_band(w, h)` resolves it. `pivot_spike_box` is gone; `emphasis_contrast.pivot_band_box` is the thin measurement helper.
- decided: **the band goes ON the cue** (`OverlayCue.band`) rather than being passed around beside it. That is what makes `apply_emphasis_treatments` need no canvas argument, and it puts the band in `emphasis_cue_content_hash` for free — which matters, because without it a band moved by editing the five constants would keep the same cue hash and `RenderStep` would serve a cached `final.mp4` with the band in the old place. Exactly the trap the plan's fingerprint warning describes.
- decided: `collect_pivot_overlay_cues` takes `width`/`height` as REQUIRED kwargs. A defaulted 720x1280 would be the same unguarded assumption the finding removes.
- decided: `box_on` maps by canvas FRACTION, not by recomputing from the plate's own size. `shot_images` holds the raw asset; the old code measured a band 0.35 of a 1920x1080 picture tall where the drawn one covers 0.13.
- decided: `height` stays OUT of the props, and this is the one honest seam left. Drawn height is `fontSize`, `pad` and line-height 1.1 (needed for matras) and measures ~183px; nominal `font + 2*pad` is 168. Measured both boxes before choosing: widening the measured box to the drawn height moves the two numbers finding 2 rests on to 100.6 and 103.3, which puts a 105 threshold ABOVE the untested plate and inverts the argument. Narrowing the drawn band to 168 needs an explicit height and re-centred type — a change to a look this plan says twice not to change. So: nominal box measured, ~8% residue documented in `PivotBand.as_props`, and the measured slice sits inside the drawn band.
- decided: `Pivot.tsx` positions from `band` and keeps its `SPIKE_*` constants ONLY as the nullish-coalescing fallback for `SuvRetention.tsx`, which passes no band. Labelled as such. `SuvRetention.tsx` / `DirectedHook.tsx` not otherwise touched — spike code, per `compositor/README.md`.
- files: `backend/app/renderer/compositor.py`, `backend/app/renderer/emphasis_contrast.py`, `backend/app/workflow/steps/render.py`, `compositor/src/Pivot.tsx`, `compositor/src/Emphasis.tsx`
- tests: not yet run
- next: finding 2

### 15:40 — finding 2: LIGHT_MAX_LUMA 90.0 to 105.0

- decided: 105.0 with the six measurements, the good case (98.3, inspected), the failure (236.9), and the nearest unproven plate (108.6) all written into the constant's comment block. `DARK_MIN_LUMA` unchanged at 180.0 — 190.1 is the only plate above it and dark type there was never inspected either, so there is no measured case asking it to move.
- decided: record the consequence that makes the old number cheap to change — **at 90.0 `light` never fired on any plate in the reference reel**, so the branch had no coverage in real data at all. Pinned as a test rather than only a comment.
- files: `backend/app/renderer/emphasis_contrast.py`
- tests: not yet run
- next: finding 1

### 15:43 — finding 1: keep the measurement, log it

- decided: `choose_treatment` stays a pure function of its arguments and keeps the `slab_default` short-circuit. Logging goes in `apply_emphasis_treatments`, which is where the device, the shot and the policy are all in scope, and it keeps the chooser trivially testable at boundary values.
- decided: call `choose_treatment` twice per cue — once with `slab_default=False` for `threshold_treatment`, once with the real policy. `policy_override` is the difference. That is the field a human actually needs before relaxing the policy: how often the policy is doing work, and what it is overriding.
- decided: one `emphasis_contrast.treatment` line per cue with `device`, `shot_id`, `measured`, `luma` (2dp — enough to compare against the thresholds, not enough to pretend the crop is exact), `treatment`, `threshold_treatment`, `slab_default`, `policy_override`, both thresholds, `band_box`.
- decided: write the reason NOT to optimise the decode away in two places — the module docstring at length, and a paragraph in `choose_treatment` beside the short-circuit itself. The brief is right that someone will see a discarded value and try; the docstring is where they will be standing when they do.
- files: `backend/app/renderer/emphasis_contrast.py`
- tests: not yet run
- next: finding 4

### 15:45 — finding 4: one decode per plate

- decided: extract `_mean_luma_of_image(image, box)` and have both `mean_luma` (which opens) and `measure_plate_luma` (which opens once, reads `.size` off the lazy handle, then converts) call it. `Image.open` is lazy, so reading `.size` before `convert("RGB")` costs no pixel load — that is what makes one decode enough.
- decided: error behaviour preserved exactly and documented as deliberately non-uniform. Empty bytes RAISE out of `mean_luma`. Empty / `None` / unreadable / non-image return `None` from `measure_plate_luma` (and log), which becomes `slab`. Do not collapse those into each other: an exception fails a render that had nothing wrong with it, and a default number is how bare white type lands on a white frame.
- files: `backend/app/renderer/emphasis_contrast.py`
- tests: not yet run
- next: tests, then a real render

### 15:47 — tests

- files: `backend/tests/unit/renderer/test_compositor.py` (three `collect_pivot_overlay_cues` call sites gained the canvas; five new tests for the band contract — resolved geometry, canvas scaling, degenerate canvases, the fraction map onto a 1920x1080 plate, the props key set, and a moved band missing BOTH hashes), `backend/tests/unit/renderer/test_emphasis_contrast.py` (`pivot_spike_box` becomes `pivot_band_box`, the pivot fixture now carries its band, plus eight new tests: the new threshold against the proven and unproven plates, `light`'s zero coverage at 90.0, a gated re-measurement of the six literals off the real frames, the calibration log's fields in all three shapes, single-decode via a counted `Image.open`, and unchanged error behaviour).
- decided: assert the six numbers as literals so the suite needs no `tmp/` fixture, and add a `pytest.skip`-gated test that re-measures them off the real frames whenever they are present. Same pattern the existing `fail_2025.png` test already uses.
- decided: the drift the finding describes can no longer be tested for from Python — there are no production constants left in the TSX to drift. What IS testable is the props key set, so that is what the test pins: a rename on either side breaks it.
- tests: `cd backend`; venv pytest `tests/unit/renderer tests/unit/script tests/unit/timeline` gives **670 passed** in 43s. `tests/unit/workflow` gives 92 passed and **5 pre-existing failures** in `test_sfx_overlays_diegetic.py` (stale stub missing `transition_structural_only`), untouched.
- ruff: two B905 (`zip()` without `strict=`) in the new tests, fixed. `ruff check` clean on all five touched files. Did NOT run `ruff format` — this project uses black.
- next: a real render, because no unit test exercises the subprocess

### 15:52 — real render, and looking at it

- did: drove the production path with no stubbed `invoke` — one `OverlayCue` at `offset_s=1.30` (startFrame 39, endFrame 66), project `fba52b6d-9c1a-44dd-bb95-5b03ba18eb8f`, 720x1280 at 30fps, 359 frames, through `render_or_reuse_emphasis_overlay`. Rendered it TWICE: once with the Python-resolved band, once with `band=None` so `Pivot.tsx` falls back to its spike constants — i.e. the exact pre-review layout path.
- measured: `ffprobe` on both gives `prores`, **`yuva444p12le`**, 720x1280, 359 frames. Alpha intact, as K7's done-criteria requires.
- measured: composited both over `tmp/suv_test/plate_nocaptions.mp4` with the production `emphasis_overlay_filter_fragment` (`[0:v][1:v]overlay=0:0:format=auto`) and diffed the first 60 frames pixel-by-pixel: **all 60 identical, zero differing pixels.** The props change moved the band by nothing. Band located in the composite at rows 379-561 (height 183), matching the predicted line-height overshoot and containing the measured box 380-548.
- did: **looked at the frame** (`tmp/suv_test/f3_band_props_driven.png`). Full-bleed red band at the same height over the Creta grille, white लेकिन correctly shaped with the matra attached, the -1.5deg tilt and the drop shadow present, and the plate visible everywhere outside the band — not a black rectangle, which is what a lost alpha channel would have produced silently.
- measured: re-ran the same call and got a cache hit in 3.0s wall, no Chromium invocation.
- files: `backend/storage/fba52b6d-.../overlays/7eda5fd5....mov` plus its props sidecar (kept — a real cached artifact of the new contract). The `band=None` comparison render and the 120 diff frames were throwaway and were deleted; nothing pre-existing under `overlays/` was touched.
- next: this work-log entry, then stop

### 15:56 — finish / summary

Four findings applied. The one that mattered most was invisible: K4 measured a rectangle defined twice, and only one of the two definitions decided where the band actually got drawn.

**Files changed**

- Band geometry + props contract: `backend/app/renderer/compositor.py` (`PivotBand`, `pivot_band`, `OverlayCue.band`, canvas args on `collect_pivot_overlay_cues`, band in `emphasis_cue_content_hash` / `overlay_input_hash` / `_overlay_props`)
- Measurement, thresholds, logging, single decode: `backend/app/renderer/emphasis_contrast.py`
- Canvas into the collector: `backend/app/workflow/steps/render.py`
- Layout from props: `compositor/src/Pivot.tsx`, `compositor/src/Emphasis.tsx`
- Tests: `backend/tests/unit/renderer/test_compositor.py`, `backend/tests/unit/renderer/test_emphasis_contrast.py`
- This plan (K4 section, K4 status row, K4 done-criteria note, this work log)

**Decisions (also in the entries above)**

- One band definition, in `compositor.py`, read by the measurement, the props and both hashes. No cycle, no new module, and the TSX keeps no production layout arithmetic.
- Band on the cue, so the render fingerprint covers a moved band and no caller needs to pass a canvas around.
- Both caches intentionally miss once. The props contract changed; that is what a cache key is for.
- `height` stays out of the props; the nominal box is the measured box, because the threshold rationale was derived through it.
- 105.0 from six measured plates, with the good case, the failure and the nearest unproven plate all named. 180.0 unchanged for want of a measured case.
- Measurement retained under the policy and logged with `threshold_treatment` / `policy_override`. The reason not to skip it is written where someone tempted to skip it will be reading.
- One decode; three distinct error shapes preserved verbatim.

**Deviations / contradictions found**

- **The plan's `216` for the t=3.0s beat does not reproduce.** Measured 236.9 (band box) / 231.7 (frame mean) / 228.8 (`fail_2025.png`). Documented in place; `SUV_T3_MEAN_LUMA` deliberately left at 216.0 because all values classify identically and 216 is the shared vocabulary. Saying so rather than quietly keeping a number that does not measure.
- The drawn band is ~183px against a nominal 168px. Pre-existing, now measured, documented, and deliberately not reconciled — reconciling it either invalidates finding 2's own rationale or changes the pivot look.
- `box_on`'s fractional map is an improvement, not a fix: a ken-burns crop still decides which asset pixels land under the band. Exact would mean extracting the rendered frame. Noted, out of scope.
- Could not typecheck the TSX — no `typescript` in `compositor/node_modules`, and Remotion bundles with esbuild, which strips types without checking them. The real render plus the pixel diff is what stands in for it.

**Not done (out of slice):** K3 density, K5 palette, K6 already done, K8 charts, K9 LLM authoring, any other device's visuals, any change to the pivot look.

No commit, no push. Working tree left for review.

---

## Work log — K11 device renderers: stamp and counter (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 16:05 — start

- read / opened: this plan (K11 ~772, device table, Devanagari rules, role table, K4 finding 3, fingerprint warning, the two spike failures, current-state table); `compositor/src/SuvRetention.tsx` (Beat 1 drop, Beat 3 Year stamp 2.69–3.55, Beat 4 Counter 3.60–4.90); `compositor/src/EmphasisOverlay.tsx` (`Intl.Segmenter` grapheme stagger); `Pivot.tsx` / `Emphasis.tsx` (props-driven production, pivot-only gate); `backend/app/renderer/compositor.py` (`OverlayCue`, `PivotBand`, `collect_pivot_overlay_cues`, both hashes, `_overlay_props`); `emphasis_contrast.py` (`measure_plate_luma` still boxes only `device=="pivot"`); `timeline.py` (`EmphasisValue`, `STAMP`/`COUNTER` already on the enum); `render.py` collect → treat → hash; `test_compositor.py`, `test_emphasis_contrast.py`, `test_fingerprint.py`.
- decided: port SuvRetention Year/Counter + EmphasisOverlay cluster stagger into new `Stamp.tsx`/`Counter.tsx`; do not edit the spike files. Rename `collect_pivot_overlay_cues` → `collect_emphasis_overlay_cues` completely (the leftover name would be a lie once stamp/counter are collected). Reuse `PivotBand` rather than a CueBand rename. Give both stamp and counter a Python-resolved band so K4 measures the box the type sits in; counter without a band would be frame mean and that is a measured 54-luma loss. Hold constants pinned from the spike windows: pivot 0.91s, stamp 0.86s (2.69–3.55), counter 1.30s (3.60–4.90). No K9, no Chromium in unit tests, no commit.
- files: this plan (K11 heading + current-state row + this log)
- tests: not yet
- next: OverlayCue.values + per-device hold + collector + stamp/counter bands

### 16:40 — OverlayCue.values + collector + per-device holds

- read / opened: `compositor.py` OverlayCue / collect / hashes; `render.py` collect call site; `timeline.py` EmphasisValue.
- decided: rename `collect_pivot_overlay_cues` → `collect_emphasis_overlay_cues` completely (render.py + tests). Keep `PIVOT_HOLD_S` exported; add `STAMP_HOLD_S = 0.86` (year 2.69–3.55) and `COUNTER_HOLD_S = 1.30` (3.60–4.90). Frozen `OverlayValue(value, unit, cited_fragment)` as a tuple on OverlayCue. Empty-values counter is skipped + logged, not drawn as 0→0. Meter/comparison/correction/question still ignored.
- files: `backend/app/renderer/compositor.py`, `backend/app/workflow/steps/render.py`, `backend/app/schemas/timeline.py` (enum docstring only)
- tests: not yet
- next: Python-authoritative stamp/counter bands

### 16:48 — Python-authoritative geometry (finding 3)

- decided: reuse `PivotBand` rather than a CueBand rename (don't over-refactor pivot). `stamp_band`: spike Year top 320, font 190, pad 14, full width → (0, 320, 720, 538) on 720×1280. `counter_band`: spike Counter top 300, font 116, pad 16, meter 420 centred → (150, 300, 570, 448). Prefer a counter band over none because the 54-luma frame-vs-box gap is a measured loss. Scale like pivot (font/width with width, top/pad with height).
- files: `backend/app/renderer/compositor.py` (`stamp_band`, `counter_band`, `_band_for_device`)
- tests: not yet
- next: Stamp.tsx

### 16:55 — Stamp.tsx

- decided: port Year (scale 1.45→1.0, amber 300×10 rule, snap 3-frame exit) plus EmphasisOverlay per-grapheme-cluster stagger via `Intl.Segmenter`. Never `.split("")`. Vendored Noto + fontWeight 700 for `hi`; spike CSS stack (`Segoe UI Black` / `Arial Black` / Impact) for `en` — no new font file. Tracking 4 for Latin, 0 for Devanagari. Treatment branch: light = white + drop shadow; dark = ink on transparent; slab = ink wipe like Brand. Layout from `band`; SPIKE_* labelled fallback only. Hue: white / ink / amber only.
- files: `compositor/src/Stamp.tsx`
- tests: not yet
- next: Counter.tsx

### 17:02 — Counter.tsx

- decided: port Beat 4: 0 → `values[0].value` over 0.95 of the hold, `Easing.out(Easing.cubic)`, `Intl.NumberFormat("en-IN")`, tabular nums, filling meter, snap exit. Unit as suffix (tracking 0). `text` is the kicker — not hardcoded "SOLD IN A YEAR". Slab = 0.88 ink scrim over the Python band (the 4.3s infographic escape). Light/dark = bare type. Latin CSS stack for digits.
- files: `compositor/src/Counter.tsx`
- tests: not yet
- next: Emphasis.tsx treatment/device branching

### 17:08 — Emphasis.tsx branching + hashes + K4

- decided: switch on `cue.device`; else → null (explicit, not "only pivot exists"). Props gain `values`. Pivot look unchanged (still ignores treatment). Both hashes and `_overlay_props` include values (value / unit / citedFragment). `measure_plate_luma`: if `band` is present, measure that box for any device; pivot without a band keeps the diagnostic image-as-canvas path; any other device without a band uses frame mean, with the 54-luma comment.
- files: `compositor/src/Emphasis.tsx`, `compositor/README.md`, `backend/app/renderer/compositor.py` (hashes + props), `backend/app/renderer/emphasis_contrast.py`, `backend/app/renderer/fingerprint.py` (docstring)
- tests: not yet
- next: tests

### 17:20 — tests

- did: collector emits stamp+counter, still ignores correction/question; per-device holds pinned; empty-values counter dropped+logged; stamp/counter round-trip into `_overlay_props` with values+treatment+band; both hashes miss on target number, unit, cited_fragment, and stamp-vs-pivot device; stamp/counter bands used as K4 local boxes; band-less non-pivot falls back to frame mean (the 54-luma path). Existing pivot tests kept.
- files: `backend/tests/unit/renderer/test_compositor.py`, `backend/tests/unit/renderer/test_emphasis_contrast.py`
- tests: `.venv\Scripts\python.exe -m pytest --rootdir=backend -c backend/pytest.ini backend/tests/unit/renderer/test_compositor.py backend/tests/unit/renderer/test_emphasis_contrast.py backend/tests/unit/renderer/test_fingerprint.py -q` → **108 passed in 2.80s**. ruff check on the changed Python files: all passed. First attempt used system `python -m pytest` (no pytest); reran with the repo `.venv`.
- next: finish / summary

### 17:28 — finish / summary

K11 unblocks K9: the compositor can now DRAW stamp and counter, not only pivot. OverlayCue.values reach props and both hashes. Stamp is the first K4 treatment consumer. Holds are per-device and clamped. Layout is Python-authoritative.

**Files changed**

- Collector + OverlayValue + per-device holds + stamp/counter bands + hashes + props: `backend/app/renderer/compositor.py` (`collect_emphasis_overlay_cues`, `OverlayValue`, `STAMP_HOLD_S` 0.86 / `COUNTER_HOLD_S` 1.30, `stamp_band`, `counter_band`)
- K4 measures any cue's band, frame-mean fallback commented: `backend/app/renderer/emphasis_contrast.py`
- RenderStep collect call: `backend/app/workflow/steps/render.py`
- Fingerprint docstring: `backend/app/renderer/fingerprint.py`
- Enum docstring: `backend/app/schemas/timeline.py`
- Production renderers: `compositor/src/Stamp.tsx`, `compositor/src/Counter.tsx`, `compositor/src/Emphasis.tsx`
- README production-shape note: `compositor/README.md`
- Tests: `backend/tests/unit/renderer/test_compositor.py`, `backend/tests/unit/renderer/test_emphasis_contrast.py`
- This plan (K11 heading, current-state row, this work log)

**Decisions (also in the entries above)**

- Renamed `collect_pivot_overlay_cues` → `collect_emphasis_overlay_cues` completely. A leftover name that only collected pivot would be a lie.
- Reused `PivotBand` rather than a CueBand rename.
- Both stamp and counter get a Python band. Counter without one would be frame mean, a measured 54-luma loss.
- Hold constants pinned from the spike windows: pivot 0.91s, stamp 0.86s (2.69–3.55), counter 1.30s (3.60–4.90).
- Empty-values counter is skipped and logged, not drawn as 0→0, not a crash.
- `cited_fragment` is hashed even though the compositor does not draw it.
- Stamp branches on light / dark / slab. Pivot still ignores treatment (the device IS a slab).
- Latin compositor faces: spike CSS stack. Devanagari: vendored Noto. No new font file.

**Deviations / contradictions found**

- **Stamp pad 14 is not in the Year spike.** Year was bare type with no inset. Slab treatment needs a rectangle to draw and K4 needs the same rectangle to measure, so pad is the slab inset. On 720×1280 the stamp box is (0, 320, 720, 538) = font 190 + 2×14.
- **Count lands at 0.95 of the actual hold, not `0.95 * fps` as in the spike.** The spike's 0.95s was for a 1.3s window. A hold clamped to remaining shot must scale; using a fixed 0.95s would overshoot a short shot.
- **Latin faces depend on the host CSS stack** (`Segoe UI Black` / `Arial Black` / Impact), matching the spike. The plan also says not to depend on host fonts for compositor faces. Chose the spike stack over vendoring a new Latin file (K6 is done; do not add a font). Devanagari is bundled. Documented here rather than quietly inventing a Noto-Latin look the spike never had.
- **Stamp combines Year's 1.45→1.0 whole-word scale with EmphasisOverlay's per-cluster stagger**, rather than picking one. The plan asked for both energies.
- **Counter always draws `text` as the kicker.** Schema requires `text` min_length=1, so a kicker is always present. K9 should put the label in `text` and the number in `values`; if it puts the number in both, the kicker duplicates. Not this slice's planner.
- Did not run a live Chromium render. **[Corrected in review: the render WAS then done, by the reviewer, and it found two defects a green test suite could not - see "Two defects, found only by rendering". The reasoning here inverted the brief: "you do not need K9" became "no Chromium required", and "a lost alpha is a black rectangle rather than a raise, so looking is the only real check" became a reason not to look.]**
- Did not switch `SuvRetention.tsx` onto `Stamp.tsx` / `Counter.tsx`. Spike files left alone.

**Not done (out of slice):** correction / question / meter-as-separate-device / comparison, K3 density, K5 palette, K8 charts, K9 LLM authoring, stamp/counter authoring in EmphasisPassStep, pivot look changes, SFX, pacing.

No commit, no `git add`, no push. Working tree left dirty for review. Stopping.

---

## Work log — K11 defects: counter band overflow + wrong-treatment shadow (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries. Two defects documented in `f19370b`'s own commit message; both fixed against that baseline.

### 18:10 — starting

- read / opened: `f19370b` commit message in full (both defects); this plan (K4 task + the 2026-09-09 review findings, K11 task, the three prior work logs, the fingerprint warning, done-criteria); `backend/app/renderer/compositor.py` in full (`PivotBand`, `pivot_band` / `stamp_band` / `counter_band`, `_band_for_device`, `OverlayValue`, `collect_emphasis_overlay_cues`, `emphasis_cue_content_hash`, `overlay_input_hash`, `_overlay_props`, `_invoke_remotion`, `render_or_reuse_emphasis_overlay`); `backend/app/renderer/emphasis_contrast.py` (`measure_plate_luma`'s band branch); `compositor/src/Emphasis.tsx`, `Counter.tsx`, `Stamp.tsx`, `Pivot.tsx`; `backend/tests/unit/renderer/test_compositor.py`, `test_emphasis_contrast.py`; `tmp/suv_test/` and `tmp/k11_check/`.
- decided: fix 1 by deriving the counter band width from the cue's own content in Python, not by compensating in the TSX. `counter_band` gains `values`/`kicker` keyword arguments and `_band_for_device` passes them through from the collector. The 420 becomes a FLOOR so every value that already fits keeps the spike look.
- decided: no real text metrics available in Python — the counter's faces come from a CSS stack Chromium resolves, and no Latin file is vendored — so a glyph-count estimate with per-em advance ratios, biased wide. Measure the ratios off the actual host faces rather than guessing them.
- decided: verify by RENDERING. That is why these two defects exist.
- files: none yet
- tests: none yet
- next: measure the advance ratios before writing any arithmetic

### 18:22 — the glyph-width assumption, measured

- did: read `hmtx` advances (normalised by unitsPerEm) off every face in the counter's CSS stack — `C:\Windows\Fonts\seguibl.ttf` (Segoe UI Black), `ariblk.ttf` (Arial Black), `impact.ttf` — plus the vendored `NotoSansDevanagari-Regular.ttf` for a Devanagari unit.
- measured: **tabular digits** Segoe UI Black .599 (.483–.621 proportional), Arial Black .667, Impact .381–.542. **Group separator** Arial Black .333, Segoe UI Black .320, Impact .168. **Widest glyph of any kind** Segoe UI Black `W` 1.053 and `%` .898, Arial Black `W` 1.000 and `%` 1.000.
- decided: 0.70 em per digit (clears the widest digit in the stack by 5%), 0.40 per separator (clears the widest by 20%), 1.10 per arbitrary glyph for the unit and the kicker (clears the widest by 4%). Counting a separator at its own ratio rather than as a digit matters: at three separators, digit-width commas alone would inflate the reference band by ~120px and push it into the canvas clamp.
- measured: the value's spring overshoot, because the number is `transform: scale`d. damping 13 / mass 0.5 / stiffness 150 gives ζ=0.751, peak s=1.028, i.e. scale 1.0085 — 0.85%, inside the digit ratio's 5% headroom. Written into the constant's comment so nobody has to redo it.
- decided: reimplement `Intl.NumberFormat("en-IN")` grouping in Python (`format_counter_value`) instead of grouping in threes. The band counts glyphs and the separators ARE glyphs; threes would undercount `2,00,000` by one comma, and undercounting is the bug.
- files: `backend/app/renderer/compositor.py`
- tests: not yet
- next: the band itself

### 18:35 — content-derived counter band + the halo

- decided: `_counter_content_width` sizes the value line to the FINAL target, not the current one, and the reason is written where the choice is made: `Counter.tsx` formats `round(t * target)` with no padding and re-centres, the count only rises, so the final value is the widest string; a band tracking the current value would need a different rectangle every frame, which this design cannot express, since the band is one value that K4 measures once and both caches key on. Right-padding the digits instead would change a watched look to buy nothing.
- decided: the kicker's longest WORD is measured too. It wraps at spaces inside the band but an unbreakable word cannot, and that is the same overflow one font size down. It does not bind on "SOLD IN A YEAR".
- decided: clamp to the canvas with a `compositor.counter_band_exceeds_canvas` WARNING rather than in silence. Clamping in silence is how the 420 shipped. The log names its number `estimated_width` and the comment says the estimate can fire slightly early, so a wolf-cry is diagnosable.
- decided: fix 2 with a new `HALO` in `Stamp.tsx` and `Counter.tsx` — two white glows (tight 10px at 0.95, wide 26px at 0.8) and NO offset ledge, unlike `SHADOW`: offsetting a light halo under dark type protects one side of each glyph and a bright uneven plate is uneven in no particular direction. `SHADOW` untouched, `slab` still gets neither.
- files: `backend/app/renderer/compositor.py`, `compositor/src/Stamp.tsx`, `compositor/src/Counter.tsx`
- tests: not yet
- next: the render, before the tests — the render is what these defects needed

### 18:48 — real render, and the measurement

- did: drove `render_or_reuse_emphasis_overlay` directly for project `fba52b6d-9c1a-44dd-bb95-5b03ba18eb8f` at 720x1280 / 30fps / 359 frames with three hand-built cues and no planner: a `stamp` "2025" at `treatment="dark"`, a `counter` (`value=200000, unit="+"`, kicker "SOLD IN A YEAR", `treatment="slab"`) on the OLD 420 band, and the same counter on the derived band. Both counters in ONE render, so the only difference between them is the rectangle Python resolved. Script and artifacts in `tmp/k11_fix/`.
- measured: `ffprobe` gives **prores / yuva444p12le / 720x1280 / 359 frames**. Alpha intact — the check is not optional, a lost alpha paints a black rectangle over the plate and raises nothing.
- did: composited over `tmp/suv_test/plate_nocaptions.mp4` with the production `emphasis_overlay_filter_fragment` (`[0:v][1:v]overlay=0:0:format=auto[out]`) and measured frames with PIL, on the overlay's own alpha so the plate cannot confuse the reading.
- measured, counter **before** (band x 150..570): slab drawn x 150..569, type drawn x **171..687**. 118px outside the slab — the `+` and the last digit on the bare plate. Composite agrees: amber to x=635, scrim ending at 570.
- measured, counter **after** (band x 17..703): slab drawn x 17..702, type drawn x 100..617, INSIDE with 83px left and 85px right margin. Asserted, not eyeballed. A composite row scan at y=372 confirms the scrim runs to x=702 and the plate resumes at x=703.
- measured, the halo (`treatment="dark"` stamp, overlay alpha): ink x 136..459, near-white partial-alpha pixels x 117..478, 28,761 of them — 19px beyond the ink on both sides. Pre-fix that count is zero by construction, since a `dark` stamp draws ink type on transparency and nothing else white.
- did: **looked at the frames.** `counter_before_composite.png` shows the clipped last digit and the orphaned `+` outside the scrim with the kicker wrapped to two lines; `counter_after_composite.png` has number, unit, meter and kicker all on the scrim; `stamp_dark_composite.png` has black `202` (the 4th cluster still staggering in at that frame) with a visible light separation from the luma-236 plate, and the plate visible everywhere outside — not a black rectangle.
- measured: K4 follows the band with no extra wiring. `k_4.30.png` through the old counter box (150,300,570,448) is 185.75 luma; through the derived box (17,300,703,448) it is 197.61.
- files: `tmp/k11_fix/verify_k11_fixes.py` plus its PNGs and composite (throwaway, gitignored); `backend/storage/fba52b6d-.../overlays/e4a3fea1....mov` and its props sidecar (a real cached artifact of the new contract; nothing pre-existing under `overlays/` was touched)
- next: tests, ruff

### 18:56 — tests and the two stale assertions

- did: seven new tests — the derived width and the preserved 420 floor; a lower bound built from the REAL `hmtx` advances (a target/unit table asserting the content box covers the true width, and that a clamped band is genuinely at the canvas limit rather than crying wolf); a wider target moving `box_on`, both hashes and the props; `format_counter_value` against `Intl` grouping; the clamp warning; and the collector wiring a target into its own band — the one test that would have failed before the pixels did.
- found: two existing assertions pinned the hardcoded 420 and had to change, which is the fix having teeth. `test_collect_emits_stamp_and_counter_not_only_pivot`'s counter (`value=200000, unit="lakh"`) now resolves to a full-bleed (0, 300, 720) band with the clamp warning: a four-letter unit at half of font 116 is estimated wider than the canvas. Recorded rather than tuned away — the estimate is deliberately the wide side, and the alternative is 59px of amber on the bare plate.
- found, and it contradicts nothing in the plan but is worth writing down: my own new lower-bound test found `9,99,99,999%` needs ~803px of a 688px content box at font 116. No rectangle inside a 720 canvas can cover that. It is a planner-side problem, the warning is the only honest response, and the test now asserts that branch instead of pretending geometry can fix it.
- tests: `cd backend`; `python -m pytest tests/unit/renderer tests/unit/timeline -q` → **598 passed** in 41.6s (450 in `tests/unit/renderer` alone). Did NOT run the whole suite, `make test`, or `PYTEST_TRUNCATE_DB=1` — the Postgres is shared and holds real projects. The 5 known failures in `tests/unit/workflow/test_sfx_overlays_diegetic.py` were not run and not touched.
- ruff: `ruff check backend/app/renderer/compositor.py backend/tests/unit/renderer/test_compositor.py` — all checks passed. Did NOT run `ruff format`; this project uses black.
- next: this work-log entry, then stop

### 19:04 — finish / summary

Both defects were pixel facts and both are now numbers. The counter band is content-derived, so the rectangle K4 measures, the rectangle both caches key on and the rectangle the TSX draws still agree — and now they also agree with the type.

**Files changed**

- Content-derived counter band, `Intl`-compatible grouping in Python, the advance ratios and their measured basis, canvas clamp + warning, collector wiring: `backend/app/renderer/compositor.py`
- `dark` treatment gains `HALO`; `light` keeps `SHADOW` untouched: `compositor/src/Stamp.tsx`, `compositor/src/Counter.tsx` (the latter also gains the "do not compensate for the band here" note)
- Tests: `backend/tests/unit/renderer/test_compositor.py`
- This plan (K11 status row, the new K11 defects subsection, this work log)

**Decisions (also in the entries above)**

- Band width derives from content in PYTHON. No layout arithmetic went back into the TSX; the `SPIKE_*` constants stay the labelled standalone-spike fallback.
- 420 is a floor, not a width. Values that fit keep the spike look exactly.
- Sized to the final value. A per-frame band is not expressible (one band, measured once, hashed twice) and right-padding would change a watched look.
- Advance ratios 0.70 / 0.40 / 1.10 em, measured from the stack's own `hmtx` tables, biased wide, with the spring overshoot accounted for in the comment.
- Over-canvas is clamped AND logged, with the log naming its number an estimate.
- `dark` gets a light halo with no offset ledge; `SHADOW` unchanged; `slab` unchanged.

**Deviations / contradictions found**

- **A 7-digit target with a unit now goes full-bleed.** `17,28,140+` estimates 767px against a 720 canvas while the true worst-face width is ~687 of a 688px content box — it fits by a pixel, and the conservative estimate rounds it up to the whole canvas with a warning. Reported rather than tuned: the brief's own rule is that erring wide is harmless and erring narrow reproduces the bug.
- **The estimate runs ~26% wide on the reference case.** Band 686, of which the type measured 518px. That is the price of having no shaper in Python, and it is the direction that cannot regress into the bug.
- The verification script had to pass `values=`/`kicker=` to `counter_band`, so its shape differs from the worked example in the brief (`counter_band(720, 1280)`) — that call still exists and is exactly the "before" case it renders.
- Could not typecheck the TSX (no `typescript` in `compositor/node_modules`; Remotion bundles with esbuild, which strips types without checking them). The real render plus the pixel measurement stands in for it, as in the K4 review.

**Not done (out of slice):** K3 density, K5 palette, K8 charts, K9 LLM authoring, the other four devices, any change to the pivot, `SuvRetention.tsx` / `DirectedHook.tsx` (labelled spike proofs), stamp band content-derivation (`stamp_band` is full width already, so a stamp cannot overflow it horizontally).

No commit, no `git add`, no push. Working tree left for review.

---

## Work log — K3 enforcement pass (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 17:33 — starting

- read / opened: this plan (K3 task, the graphic-asset blocker, sequencing note that K9 removes the one-cue guarantee, `_cap_text_cards` precedent, done-criteria); `backend/app/timeline/pivot.py` (inline `text_card` skip in `detect_pivot` + re-check in `attach_pivot_cue`); `backend/app/workflow/steps/emphasis_pass.py`; `Shot` / `EmphasisCue` / `_emphasis_cue_and_text_card_are_mutually_exclusive` in `backend/app/schemas/timeline.py`; `StylePacingBand` + `resolve_emphasis_slab_default` / `resolve_sfx_whoosh_enabled` in `backend/app/script/styles.py`; `_cap_text_cards` in `backend/app/planners/shot/planner.py`; `split_narration_fragments`; `compute_timeline_duration`; existing tests (`test_pivot.py`, `test_emphasis_cue.py`, `test_emphasis_pass_step.py`, `test_styles.py`).
- decided: take the plan's recommended option 1 for the graphic rule — planner-authored `Shot.picture_is_graphic: bool = False`. Not a prompt grep, not vision. Additive default False so existing shots are not graphics and a missing field cannot start dropping cues. Shot-level so enforcement does not depend on `asset_plan`. K8 will reuse this signal; this slice only enforces it. Do not wire the Shot Planner prompt (K9 is not this task).
- decided: do not invent per-shot safe-zone geometry here. Pictures do not exist at `EmphasisPassStep` (documented from the first real run: approval requires every shot filled BEFORE approval). Safe zones are a render-time / K4-adjacent problem. The Python-authoritative `band` already places type.
- decided: K3's first job is a MOVE of the `text_card` rule out of `pivot.py` into a shared helper, keeping "first match is THE turn; a text_card on that shot means the reel has no pivot." Do not search for a later `but`.
- files: this plan (status row + this log)
- tests: none yet
- next: schema field, shared module, MOVE, band knobs, step wiring, tests

### 17:45 — MOVE of the text_card rule

- decided: `shot_blocks_emphasis_cue(shot) -> str | None` is the one shot-level door. `detect_pivot` and `attach_pivot_cue` call it instead of `if shot.text_card`. First match is still THE turn; a blocked covering shot still means the reel has no pivot; do not search for a later `but`.
- decided: the helper also returns `"graphic"` when `picture_is_graphic` is True. Same "the skipped match is THE turn" shape as text_card — a graphic on the covering shot means the reel has no pivot. Outcome matches attach-then-enforce-drop; doing it in the helper means attach never writes a cue the pass would immediately clear. Schema still allows graphic+cue (unlike text_card) because a stored timeline with the flag unset must not become unloadable; the pass is what drops it.
- files: `backend/app/timeline/emphasis_rules.py` (`shot_blocks_emphasis_cue`), `backend/app/timeline/pivot.py`
- tests: not yet
- next: values citation, density, graphic field, step wiring

### 17:48 — values citation

- decided: empty `values` is not a failure (pivot/stamp). Any one `values[]` miss drops the whole cue. `cited_fragment` is 1-based via `split_narration_fragments` on the owning scene. Digits of `value` must appear, allowing comma/space grouping (`200000`, `2,00,000`). Scale words reconstruct the integer the digits do not spell: `2 lakh` == 200000 (also `lac`/`लाख`/`crore`/`करोड़`/`thousand`). An out-of-range `cited_fragment` is a miss.
- files: `backend/app/timeline/emphasis_rules.py`
- tests: not yet
- next: density / min-gap

### 17:50 — density / min-gap and rate cap

- decided: `emphasis_min_shot_gap=3` on `retention_fast`. Arithmetic: 1.75s/shot × 3 = 5.25s between cues → 60/5.25 ≈ 11.4/min, inside the plan's 8–12/min band. `emphasis_max_cues_per_minute=12.0` is the top of that band, the ceiling when shots run shorter than the 1.75s target (the 0.8s floor would otherwise allow ~25/min at gap 3). Other styles leave both None so density is a no-op.
- decided: min-gap mirrors `_cap_text_cards` with pivot in the chapter-card role: never drop a pivot; a non-pivot already kept yields to a later pivot inside the gap; two pivots inside the gap are both kept. Rate cap reserves a slot for every remaining pivot so a late pivot cannot push the reel back over after earlier stamps were kept; extras drop in film order (later non-pivots first, i.e. keep earliest that still fit). A lone pivot is always kept even if the hypothetical rate is exhausted.
- decided: knobs resolved in `EmphasisPassStep` (RV2 / R1), not inside the pure function.
- files: `backend/app/script/styles.py`, `backend/app/timeline/emphasis_rules.py`
- tests: not yet
- next: graphic field on Shot

### 17:52 — graphic field (option 1)

- decided: unblocked the graphic rule by taking the plan's recommended option 1; not a prompt grep, not vision. Field is `Shot.picture_is_graphic: bool = False` — shot-level so enforcement does not depend on `asset_plan`. Docstring says K8 reuses this signal and that the planner (K9 / shot planner) is what should set it; this slice only enforces. Did not wire the Shot Planner prompt.
- decided: existing `_emphasis_cue_and_text_card_are_mutually_exclusive` validator stays. Did not add `treatment` or colours to EmphasisCue.
- files: `backend/app/schemas/timeline.py`
- tests: not yet
- next: wire into EmphasisPassStep

### 17:54 — wiring into EmphasisPassStep

- decided: after `attach_pivot_cue`, run `enforce_emphasis_rules` with the resolved knobs, then stamp `emphasis_pass_attempted`. Same `append_version`. No new step, no pipeline-position change. Attach still refuses to write onto a blocked shot (shared helper) so a text_card collision cannot reach schema validation on append.
- decided: per-shot safe-zone geometry is a deliberate deferral, not an accident. Pictures do not exist at EmphasisPassStep (approval requires every shot filled BEFORE approval). The Python-authoritative `band` already places type; a second layout system would drift. Safe zones are render-time / K4-adjacent.
- files: `backend/app/workflow/steps/emphasis_pass.py`
- tests: not yet
- next: tests

### 17:42 — tests

- did: `backend/tests/unit/timeline/test_emphasis_rules.py` (new, pure); updated `test_pivot.py` not needed (imports unchanged, existing text_card test still passes); `test_emphasis_cue.py` pins `picture_is_graphic` default False; `test_styles.py` pins retention_fast knobs and the byte-for-byte band row; `test_emphasis_pass_step.py` pins a graphic covering the pivot word ends with no cue and still stamps the attempt.
- found: wrapping a poked `text_card`+cue Shot in `Scene(...)` re-runs the mutual-exclusion validator, so the enforce test pokes the cue onto a shot that is *already* in a constructed Timeline. That is the path the pass actually has to correct (in-place assignment), not a construction the schema already refuses.
- found: first rate-cap "keep one stamp + pivot" fixture was 4×1s = 4s, so 20/min allowed only 1.33 and every stamp dropped. Added two empty shots to make the 6s the comment claimed.
- tests: `cd backend`; `.venv\Scripts\python.exe -m pytest tests/unit/timeline/test_emphasis_rules.py tests/unit/timeline/test_pivot.py tests/unit/timeline/test_emphasis_cue.py tests/unit/workflow/test_emphasis_pass_step.py tests/unit/script/test_styles.py -q` → **104 passed** in 2.36s.
- ruff: clean on the K3 files. Pre-existing B905 in `test_styles.py` (unrelated `zip` without `strict=`) not touched.
- next: finish / summary

### 17:43 — finish / summary

K3 is the shared door. `pivot.py` no longer owns the `text_card` rule inline. Graphic rule is option 1. Values citation drops uncitable counters. Density is on the `retention_fast` band with the pivot guaranteed. Safe zones deferred.

**Files changed**

- New shared pass: `backend/app/timeline/emphasis_rules.py`
- MOVE: `backend/app/timeline/pivot.py` (`shot_blocks_emphasis_cue` instead of inline `text_card`)
- Schema: `backend/app/schemas/timeline.py` (`Shot.picture_is_graphic: bool = False`)
- Band knobs + resolvers: `backend/app/script/styles.py`
- Step wiring: `backend/app/workflow/steps/emphasis_pass.py` (attach, then enforce, then stamp)
- Tests: `backend/tests/unit/timeline/test_emphasis_rules.py` (new), `test_emphasis_cue.py`, `test_emphasis_pass_step.py`, `test_styles.py`
- This plan (K3 status row, K3 heading one-liner, this work log)

**Decisions (also in the entries above)**

- Unblocked the graphic rule by taking the plan's recommended option 1; not a prompt grep, not vision.
- `shot_blocks_emphasis_cue` is the one shot-level door (text_card AND graphic). Detect/attach call it. First match is still THE turn; do not search for a later `but`.
- Gap 3 at 1.75s/shot ≈ 11.4/min; cap 12.0/min is the ceiling. Other styles None.
- Rate cap reserves a slot for every remaining pivot and keeps the earliest non-pivots that still fit. A lone pivot is never dropped for density.
- Safe-zone pixel geometry is a deliberate deferral: no plate at authoring time.

**Deviations / contradictions found**

- Helper covers graphic, not only `text_card`. Same "skipped match is THE turn" shape; a graphic on the covering shot means the reel has no pivot. Did not start searching for a second pivot.
- Rate cap does not drop earliest-non-pivot-until-under as a post-pass strip. It walks film order once, keeping a non-pivot only when it plus remaining pivots still fit — same "keep earliest, important beats outrank" shape as `_cap_text_cards`. A post-pass strip of the earliest stamps would delete the hook to save a later one.
- Nested `Scene(...)` re-validates, so a colliding plan used as *construct* input cannot reach the pass; a colliding plan used as *assignment* input can, and that is what the test pokes.
- Did not wire the Shot Planner prompt (K9). Did not implement vision, prompt-grep, safe-zone geometry, compositor changes, SFX, pacing, K5, K8, or K9 LLM.

**Not done (out of slice):** K9 LLM authoring, K5 palette, K8 charts, per-shot safe-zone geometry, setting `picture_is_graphic` from the planner.

No commit, no `git add`, no push. Working tree left dirty for review. Stopping.

### 18:07 — review finding 1: `min_shot_gap` was off by one

- decided: the gap is an INDEX DISTANCE in film order — a cue is kept when `i - last_kept_index >= min_shot_gap` — not a count of shots seen since the keeper. `_apply_min_gap` set `shots_since_kept = 0` ON the kept shot and incremented only afterwards, so a candidate `d` shots away read `d - 1` and `shots_since_kept < min_shot_gap` dropped the boundary case. Effective gap was 4, not 3.
- decided: fix the code, not the docs, and the reason is arithmetic that is already written down in two places. Index distance is what the module docstring's rule 5 already said ("fewer than `min_shot_gap` shots after the last KEPT cue"), it makes `styles.py`'s own `1.75 × 3 = 5.25s → 60/5.25 ≈ 11.4/min` true as written (under the off-by-one the real interval was 4 shots = 7.0s → 8.57/min, below the plan's 8–12/min band), and it makes the `12.0/min` cap the binding ceiling, which is the only job that comment gives the cap. Rewording the docs to match the code would have left the band knob describing a density the pass could never produce.
- decided: pivot guarantees are unchanged and are not negotiable — never drop a `device=pivot` cue; a non-pivot already kept still yields to a later pivot GENUINELY inside the gap; two pivots inside the gap are both kept; a lone pivot is always kept. A dropped cue is not a keeper, so the gap keeps running from the last KEPT index and three colliding cues do not ratchet.
- measured: `tmp/k3_min_gap_probe.py` (throwaway, gitignored) drives the real `enforce_emphasis_rules` with the real `resolve_emphasis_min_shot_gap("retention_fast")` = 3 / `resolve_emphasis_max_cues_per_minute("retention_fast")` = 12.0, on reels with a cue authored on EVERY shot. 20 shots × 1.75s = 35.00s → 7 cues kept = **12.00 cues/min**; 26 × 1.35s = 35.10s → 7 = **11.97/min**; 17 × 2.05s = 34.85s → 6 = **10.33/min**. Kept indices are 0, 3, 6, 9, 12, 15, 18 — the gap 3 the comment claims.
- measured: the pre-fix numbers, by running the same probe at index gap 4 (which reproduces the old counter exactly on an all-stamp reel): 8.57/min, 11.97/min, 8.61/min. So the 20-shot reel moved 8.57 → 12.00, the 26-shot reel is unchanged because the RATE CAP binds there (gap alone would keep 9, the cap allows 7.02), and the 17-shot reel moved 8.61 → 10.33. Every number matches the review's expected list; nothing was tuned to fit.
- found: the 26-shot row is the one that proves the cap is doing work rather than decorating the band — it is the only row where min-gap and cap disagree.
- files: `backend/app/timeline/emphasis_rules.py` (`_apply_min_gap` + rule-5 docstring), `backend/app/script/styles.py` (`retention_fast` density comment now carries the three measured rows and says the cap, not the interval, is the ceiling)
- tests: `tests/unit/timeline/test_emphasis_rules.py` — the boundary that was missing (every pre-review min_gap test used two ADJACENT shots, so nothing pinned it): distance 1 and 2 drop, distance 3 and 4 keep, `stamp@0 + pivot@3` at gap 3 keeps BOTH, two pivots inside the gap are both kept, a dropped cue does not restart the gap, and the 20-shot reel's 7 cues / 12.00 per minute is pinned through the real resolvers.
- next: finding 2 — the citation matcher only reads digits

### 18:07 — review finding 2: the narration spells its numbers out

- found: an existing helper already owns this problem, so no new Hindi table was written. `app/planners/caption_romanizer/numerals.py` (§11 of caption_romanization.md) carries Hindi 0–99 plus the four multipliers `सौ`/`हजार`/`लाख`/`करोड़` with nukta variants, and `find_numeral_runs` / `word_value` / `is_multiplier` are public. It exists because §11 needed a value COMPUTED from a closed table instead of guessed by an LLM — exactly this rule's need. `_fragment_contains_value` now calls it; only the English words (one–twenty, round tens, hundred, thousand, lakh/lac, crore, million, billion) are new here.
- decided: read the fragment as tokens rather than by regex alternation. A number word or numeral immediately followed by a scale word is one value and the pair is CONSUMED (`दो लाख` states 200000 — not 2, and not 100000), decimal coefficients are allowed (`2.5 lakh` == 250000) and non-integral products are ignored rather than rounded, and multi-word Hindi runs are handed to `numerals.find_numeral_runs` first with their words withheld from the pair reader, so `दो हजार छब्बीस` states 2026 and not also 2000 or 26. Citing a coefficient or a scale word alone therefore still drops: the rule keeps its teeth.
- found: tokenising with the usual word classes is wrong for this text and silently so — Devanagari matras and the nukta are Unicode categories Mc/Mn, which those classes exclude, so `पाँच` shreds into two single letters and never matches the table. Measured, then replaced with a negative separator class (the full stop is not a separator; it carries `2.5`, and is stripped off token ends instead).
- measured: `tmp/k3_citation_probe.py` (throwaway, gitignored) prints before/after with the pre-review matcher copied in verbatim. Unchanged CITED: `2,00,000 SUVs bikin`, `2 lakh SUVs sold`, `2 लाख SUVs bik`, `साल 2025 में`. DROPPED → CITED: 200000 in `दो लाख SUVs bik`, 200000 in `two lakh SUVs sold`, 500000 in `पाँच लाख गाड़ियाँ`, 250000 in `2.5 lakh cars`, 5 in `पाँच stars`, and both numbers of the user's own test line — 5 in `Safety rating में पाँच stars` and 1000000 in `price भी दस लाख से कम`. Still DROPPED: 200000 in `nice car, no figure here.`, 300000 and 2 in `दो लाख SUVs bik`, 100000 in `two lakh SUVs sold`.
- decided: correct the honesty documentation in both places it was too narrow, because `rule=values_citation` in a log reads as "the model invented a number". The module docstring's rule 3 and the plan's §"permissive, with provenance" guardrail 1 (plus the verification checklist line) now say what the check proves: a KEPT value is FINDABLE in the cited fragment under the readings this module implements — not that the sentence is about it, not that it is true; a DROPPED value means only that this matcher could not find it. The matcher stays deliberately lenient and is still incomplete (English compounds, ordinals, fractions, ranges, percentages-of), so widen it on a measured miss.
- files: `backend/app/timeline/emphasis_rules.py`, `docs/plans/retention_fast_kinetic_text.md`
- tests: `tests/unit/timeline/test_emphasis_rules.py` — every DROPPED row above as a CITED case (plus `five crore views`, `ten thousand bookings`, `दो हजार छब्बीस` == 2026), and the teeth kept: a value stated nowhere drops, the coefficient alone drops, the scale word alone drops, 2000 / 26 against `दो हजार छब्बीस` drop, an out-of-range `cited_fragment` drops, and one miss among several values still drops the whole cue.
- next: finding 3 — the silent argument swap

### 18:07 — review finding 3: the call site's two knobs

- decided: pin the values as actually passed, not a fixture whose outcome merely differs. `min_shot_gap` and `max_cues_per_minute` are both plain numbers, `min_shot_gap > 0` accepts `12.0`, and `3 == 3.0` / `12.0 == 12`, so a swap raises nothing and equality alone would not catch a swap of two numerically equal knobs. The test spies on `enforce_emphasis_rules` in the step's own module namespace and asserts `{"min_shot_gap": 3, "max_cues_per_minute": 12.0}` plus the two TYPES (`int` / `float`).
- did: proved the test has teeth by swapping the two arguments at the call site, watching it fail (`{'min_shot_gap': 12.0} != {'min_shot_gap': 3}`), and restoring the call site — `git diff` on `emphasis_pass.py` is back to the K3 wiring, byte for byte.
- files: `backend/tests/unit/workflow/test_emphasis_pass_step.py`
- tests: `python -m pytest tests/unit/timeline tests/unit/workflow tests/unit/script -q` → **373 passed, 5 failed** in 16.76s. Baseline before this review was 347 passed / 5 failed; the same 5 failures are all in `tests/unit/workflow/test_sfx_overlays_diegetic.py`, are PRE-EXISTING (confirmed by the reviewer against a stashed K3), and were not touched. +26 tests, no new failure.
- ruff: `python -m ruff check app/timeline/emphasis_rules.py app/script/styles.py tests/unit/timeline/test_emphasis_rules.py tests/unit/workflow/test_emphasis_pass_step.py` → **All checks passed!** No formatter was run (the Makefile is `ruff check` only; a `black` / `ruff format` pass reformats unrelated lines).
- found: nothing in the plan contradicts these three fixes. The gap-3 arithmetic recorded at 17:50 (`1.75 × 3 = 5.25s ≈ 11.4/min`) described the INTENDED index distance all along — the code, not the record, was wrong; the one number that needed correcting is the implication that a fully-authored reel sits at ~11.4/min, when it sits AT the 12.0/min cap (a reel carries the cue at t=0 on top of the intervals).
- next: report the three measured rates and the before/after rows to the reviewer. No commit, no `git add`, no push; tree left dirty. Probes live in `tmp/` (gitignored) and are throwaway.

---

## Work log — K12 planner authors picture_is_graphic (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 18:36 — starting

- read / opened: K12 (~line 915) + K3 graphic-blocker option 1; `planners/shot/schemas.py` (module docstring: OpenAI strict mode, every field required and default-free; `text_card`/`sfx_cue` as the pattern); `planner.py::_to_domain_shot` (~1026); `prompts/shot_planner/v1.md` (`sfx_cue` silent-objects list + Output field list); `prompts/shot_planner_styles/retention_fast.md` (pacing/camera only — no data-moment language); `schemas/timeline.py` `Shot.picture_is_graphic`; every `ShotPlanOutput(` constructor (`test_shot_planner.py` `_shot`, `test_shot_planner_context.py`, `test_shot_planner_parallax_layers.py` `_shot_output`, `test_shot_planner_element_reveal.py` `_shot_output`, `test_shot_text_cards.py` `_shot_output`, `test_generate_timeline_real.py`); threading tests in `test_shot_text_cards.py`.
- decided: this slice is only the wiring. K3 already owns enforcement. Do not implement K8/K9/vision. Do not invent a second picture taxonomy — keep the flag aligned with the existing `sfx_cue` silent-objects list. Domain `Shot.picture_is_graphic` keeps `= False` (isolation); planner output is a required bool with **no Python default** (a default would drop it from JSON-schema `required` and the model would never be asked).
- decided: leave `retention_fast.md` alone. The style fragment does not talk about data moments; putting the rule in the base prompt means every style gets the signal (K3/K8 are not retention-only even if kinetic text is).
- decided: no True+text_card validator. A title card over a chart is a K3 collision on the cue, not on this flag; the plan said not to invent that.
- files: this plan (this work log)
- tests: none yet
- next: schema, then mapping, then prompt, then fixtures + tests

### 18:40 — schema

- decided: `ShotPlanOutput.picture_is_graphic: bool` is required and default-free. The plan's phrase "additive default False" refers to the domain `Shot` field (already `= False` in `timeline.py`); putting a default on the planner output model would drop it from JSON-schema `required` and the model would never emit it.
- did: added the field after `sfx_cue` (same "required extra field" block as `text_card`/`sfx_cue`; layers/reveal stay the illustrated_faceless block). Updated the domain `Shot.picture_is_graphic` docstring so it no longer says "the Shot Planner / K9 is what should set it" — K12 is that wiring. Noted the Pexels/override limitation on the domain field: the flag describes planner intent, not the acquired still.
- files: `backend/app/planners/shot/schemas.py`, `backend/app/schemas/timeline.py`
- tests: not yet
- next: mapping

### 18:41 — mapping

- decided: `_to_domain_shot` passes `picture_is_graphic=s.picture_is_graphic` as-is, between `text_card` and `sfx_cue`. Do not empty-string-normalise a bool; do not default in the mapper (that would hide a missing planner value). Isolation is the domain default: a stored timeline without the key still loads as False.
- files: `backend/app/planners/shot/planner.py`
- tests: not yet
- next: prompt

### 18:42 — prompt

- decided: one creative bullet + one Output-list bullet in the BASE prompt (`v1.md`), not a style fragment. K3/K8 are not retention-only. `retention_fast.md` has no data-moment language, so adding a graphic-flag note there would be a second taxonomy for one style.
- decided: keep the `sfx_cue` silent-objects list as the taxonomy. True: chart/graph/diagram/infographic/dashboard/table/document-of-figures/map-that-is-the-data. False: scene/person/product/place/photograph-of-an-object, and the named false-positive (a chart in the background of a scene). A diagram/document that IS the picture is True; a portrait is False.
- files: `backend/app/prompts/shot_planner/v1.md`
- tests: not yet
- next: fixtures + unit tests

### 18:43 — fixtures + tests written

- did: added `picture_is_graphic=False` to every existing `ShotPlanOutput(` constructor so they still construct under the required field. New `test_shot_planner_picture_is_graphic.py`: True threads, False threads, domain Shot without the kwarg is False, stored JSON without the key loads as False, JSON schema has the field in `required` with no default, FakePlanningProvider through `ShotPlanner.plan` namespaces `sc_01_sh_01` True / `sc_01_sh_02` False.
- files: `backend/tests/unit/planners/test_shot_planner.py`, `test_shot_planner_context.py`, `test_shot_planner_parallax_layers.py`, `test_shot_planner_element_reveal.py`, `test_shot_text_cards.py`, `backend/tests/integration/test_generate_timeline_real.py`, `backend/tests/unit/planners/test_shot_planner_picture_is_graphic.py` (new)
- tests: running next
- next: run the shot-planner unit suite, then attempt a live re-plan

### 18:44 — unit tests

- tests: `cd backend`; `..\.venv\Scripts\python.exe -m pytest tests/unit/planners/test_shot_planner.py tests/unit/planners/test_shot_text_cards.py tests/unit/planners/test_shot_planner_parallax_layers.py tests/unit/planners/test_shot_planner_element_reveal.py tests/unit/planners/test_shot_planner_context.py tests/unit/timeline/test_emphasis_cue.py tests/unit/planners/test_shot_planner_picture_is_graphic.py -q` → **70 passed** in 16.51s. (venv lives at repo root, not `backend/.venv`; PowerShell needs `..\.venv\Scripts\python.exe` after `cd backend`.)
- ruff: `python -m ruff check` on the K12 Python files → **All checks passed.** Pre-existing I001 on `planner.py` import block not touched. Did not ruff the markdown prompt.
- found: first collection of the new test file failed on a stray trailing `)` — syntax, not logic; removed and re-ran.
- next: live re-plan

### 18:44 — live re-plan

- checked: `settings.dry_run=False`, `has_openai_key=True`, `planning_model=gpt-5.6-terra`, postgres on localhost (unit tests that create projects already passed). Not printing the key.
- did: one Shot Planner call, one scene, `render_style=retention_fast`. Script `tmp/k12_replan.py` (gitignored, throwaway). Narration three fragments: (1) `Hyundai Creta dikhti hai har gali mein.` (2) `2025 mein 2 lakh models bikhe.` (3) `But is it actually the safest?`
- result: **the data shot came back True; the ordinary ones False.** Project `8b09ae2a-59c0-41ca-8e38-fea4c98c0ddd`, scene `sc_01`:
  - `sc_01_sh_01` `picture_is_graphic=False` prompt: "India 2025 residential street, white Hyundai Creta moving through everyday neighborhood traffic..." covering fragment 1
  - `sc_01_sh_02` `picture_is_graphic=True` prompt: "clean contemporary automotive sales infographic, single tall bar representing 200,000 Hyundai Creta models sold in India during 2025..." covering fragment 2 (the data line)
  - `sc_01_sh_03` `picture_is_graphic=False` prompt: "front-facing Hyundai Creta in a dim urban parking setting..." covering fragment 3
- decided: this is the slice's done-criterion. A green suite alone would not have been evidence.
- CORRECTED IN REVIEW 2026-09-09: the durable evidence is the two `llm_call` rows on that project, NOT the project row itself. The script calls `ShotPlanner.plan` directly and never persists a timeline, so `timeline_version` for `8b09ae2a` is EMPTY — anyone following the original pointer finds an empty project and concludes the re-plan never ran. Both recorded calls classify `sh_02` (the infographic) True and the two scene shots False.
- next: finish / summary

### 18:45 — finish / summary

K12 is the wiring. `ShotPlanOutput.picture_is_graphic` is a required bool with no Python default (OpenAI strict mode). `_to_domain_shot` maps it onto `Shot`. The base Shot Planner prompt teaches True vs False against the existing `sfx_cue` silent-objects list. K3 already enforces the flag; this slice only authors it. Live re-plan confirmed the data shot is True and the scene-setting shots are False.

**Limitation (written down, not designed around).** The flag describes what the planner INTENDED to acquire. A Pexels result or a human upload via override was never described by the planner, so the flag cannot speak for those. Vision classification stays the only complete answer if that ever matters.

**Files changed**

- Schema: `backend/app/planners/shot/schemas.py` (`ShotPlanOutput.picture_is_graphic: bool`, required, no default)
- Mapping: `backend/app/planners/shot/planner.py` (`_to_domain_shot`)
- Domain docstring: `backend/app/schemas/timeline.py` (`Shot.picture_is_graphic` — K12 is the wiring; Pexels/override limitation noted)
- Prompt: `backend/app/prompts/shot_planner/v1.md` (creative rule + Output bullet)
- Fixtures: every existing `ShotPlanOutput(` constructor (`test_shot_planner.py`, `test_shot_planner_context.py`, `test_shot_planner_parallax_layers.py`, `test_shot_planner_element_reveal.py`, `test_shot_text_cards.py`, `test_generate_timeline_real.py`)
- Tests: `backend/tests/unit/planners/test_shot_planner_picture_is_graphic.py` (new)
- This plan (K12 status row + this work log)

**Decisions (also in the entries above)**

- Planner output has no default; domain Shot keeps `= False` for isolation.
- Rule lives in the base prompt, not `retention_fast.md`, so every style gets the signal.
- No True+text_card validator — a title card over a chart is a K3 cue collision, not this flag.
- Did not invent a second picture taxonomy.

**Deviations / contradictions found**

- Plan phrase "additive default False" on `ShotPlanOutput` would have dropped the field from JSON-schema `required`. Followed the schema module's own OpenAI strict-mode rule instead; the additive default stays on domain `Shot`.
- Prompt names "a document of figures" so the `sfx_cue` silent-objects list (`document`) has a True case; not a second taxonomy.
- venv is at repo root, not `backend/.venv`.
- Live re-plan left project `8b09ae2a-59c0-41ca-8e38-fea4c98c0ddd` in the local DB as evidence. Throwaway script in `tmp/k12_replan.py` (gitignored).

**Not done (out of slice):** K8 (drawing the chart), K9 LLM emphasis pass, K5 palette, vision classification, Pexels/override reclassification.

No commit, no `git add`, no push. Working tree left dirty for review. Stopping.

---

## Work log — K5 palette resolution (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 19:12 — starting

- read / opened: this plan (K5 task ~688, decision 7 ~1125, architecture table "colour is decided once and written down", fingerprint warning `palette_hash`, file map); `timeline.py` `TimelineMetadata.voice_id`; `styles.py` `StylePacingBand` + `resolve_emphasis_slab_default`; `compositor.py` (`overlay_input_hash`, `_overlay_props`, `render_or_reuse_emphasis_overlay`); `render.py` (overlay collect ~396, fingerprint ~449, compositor call ~612); `fingerprint.py` (emphasis docstring still says palette is not in this slice); compositor `Stamp.tsx` / `Counter.tsx` / `Pivot.tsx` / `Emphasis.tsx` (four hexes: `#FFC300` accent, `#FF2E2E` pivot ground, `#FFFFFF` white, `#0A0A0B` ink); K11 live-render pattern in `tmp/k11_fix/verify_k11_fixes.py`.
- decided: scenario A as recorded. Palette is a pair (accent + pivot_ground). White/ink stay K4 literals. Precedence `override > planner > channel > band`; last-last fallback for a non-retention band is the spike pair so the compositor never invents hexes — same pair `retention_fast` records, not a second colour-choosing system. No K9 LLM call. Resolve once in RenderStep (RV2). Hash the resolved pair, not the raw metadata field. Strip the raw metadata fields from the timeline dump (like `approved_scenes`) so unset vs explicit-band-pair collide on the render fingerprint.
- files: this plan (K5 status line + this work log)
- tests: none yet
- next: schema + band + resolver

### 19:20 — schema, resolver, seam, compositor

- files: `backend/app/schemas/timeline.py` (`EmphasisPalette`, `emphasis_palette` + `emphasis_palette_override` on `TimelineMetadata`, hex `#RRGGBB` validator, empty string rejected); `backend/app/script/styles.py` (`emphasis_accent` / `emphasis_pivot_ground` on the band, spike pair on `retention_fast`, `resolve_emphasis_palette`); `backend/app/core/config.py` (channel defaults, None); `backend/app/renderer/compositor.py` (`emphasis_palette_as_props`, `emphasis_palette_hash`, palette in `overlay_input_hash` / `_overlay_props` / `render_or_reuse_emphasis_overlay`); `backend/app/renderer/fingerprint.py` (`palette_hash` kwarg, raw palette fields stripped from the timeline dump); `backend/app/workflow/steps/render.py` (resolve once, same object to fingerprint and compositor); compositor `Emphasis.tsx` / `Stamp.tsx` / `Counter.tsx` / `Pivot.tsx` (props in, WHITE/INK stay literals, leftover hexes labelled spike-only fallbacks). Spike compositions untouched.
- decided: last-last fallback for a non-retention band is the spike pair (compositor never invents hexes). Channel/band may mix per role; override/planner are a pair. Hash the resolved pair. Strip raw metadata fields so unset vs explicit-band-pair collide.
- tests: 193 passed (`test_emphasis_palette` schema + resolver, `test_styles`, `test_compositor`, `test_fingerprint` + parallax/reveal helpers). Ruff clean on the K5 Python files (pre-existing B905 in `test_styles.py` not touched).
- next: live Remotion renders + pixel sampling

### 19:26 — live Remotion renders + measured RGB

- did: `tmp/k5_palette/verify_k5.py` drove `render_or_reuse_emphasis_overlay` (real Chromium, ProRes 4444) with a stamp + counter + pivot overlay at 720×1280 / 30fps / 130 frames. Palette resolved through `resolve_emphasis_palette` from a timeline, not hardcoded at the compositor. Frames extracted as RGBA PNG. `tmp/` is gitignored.
- Node 22.15.1, npx 11.5.2, ffmpeg 9.0. Four Chromium invokes (unset, authored, amber-off, amber-on). Second render of unset: **0 invokes**, same path — cache hit.
- **Watch 1 — unset fallback.** `render_style=retention_fast`, no palette fields. Resolver returned `#FFC300` / `#FF2E2E`. Overlay `tmp/k5_palette/storage/k5-palette/overlays/28e26880….mov`.

  | site | frame | (x,y) | hex | expect |
  |---|---|---|---|---|
  | stamp rule | `tmp/k5_palette/unset_stamp.png` | (215, 530) | `#FFC300` | amber accent |
  | counter digits | `tmp/k5_palette/unset_counter.png` | (128, 339) | `#FFC300` | amber accent |
  | pivot band fill | `tmp/k5_palette/unset_pivot.png` | (171, 385) | `#FF2E2E` | red ground |
  | pivot type | same | (238, 400) | `#FFFFFF` | K4 light, not palette |
  | stamp point | same stamp | (360, 535) | `#FFC300` | |
  | pivot point | same pivot | (80, 389) | `#FF2E2E` | |

  Zero drift from the authored hexes on the overlay RGBA. (360, 374) on the counter frame is slab ink `#0A0A0B` — the digits sit left of centre; the closest-accent search is the one that finds type.

- **Watch 2 — authored palette.** Same cues, `emphasis_palette={accent: "#00C8FF", pivot_ground: "#5A00A8"}`. Overlay `tmp/k5_palette/storage/k5-palette/overlays/fdefec72….mov`.

  | site | frame | (x,y) | hex |
  |---|---|---|---|
  | stamp rule | `tmp/k5_palette/authored_stamp.png` | (216, 530) | `#00C8FF` |
  | counter digits | `tmp/k5_palette/authored_counter.png` | (128, 339) | `#00C8FF` |
  | pivot band fill | `tmp/k5_palette/authored_pivot.png` | (174, 385) | `#5A00A8` |
  | pivot type | same | (238, 400) | `#FFFFFF` |

  Accent sites are **not** still amber. Pivot ground is **not** still `#FF2E2E`. Pivot type stayed white.

- **Watch 3 — amber-on-amber.** Plate `tmp/k5_palette/amber_plate.png` filled `#FFC300`. Counter, accent `#FFC300`. Measured luma through the counter band: **190.71** (Rec.601 theoretical 190.71). `DARK_MIN_LUMA=180`, `LIGHT_MAX_LUMA=105`.

  | policy | treatment | type colour | sits on | frames |
  |---|---|---|---|---|
  | `slab_default=False` | `dark` | ink `#0A0A0B` at (128, 323) and (128, 339) on overlay **and** composite | the amber plate | `amber_off_overlay.png` / `amber_off_composite.png` |
  | `slab_default=True` (production retention_fast) | `slab` | accent `#FFC300` at (128, 339) and (200, 360) | the ink slab (composite slab `#27200A` = 0.88 ink over amber), **not** the plate | `amber_on_overlay.png` / `amber_on_composite.png` |

  Plate itself at (40, 40) stayed `#FFC300` on both composites.

  **Does K4 save it, or does accent type sit on an amber plate?** K4 saves it. With the policy off the chooser picks `dark` and the digits render as ink, not accent — accent type does not sit on the amber plate. With the policy on, digits stay accent but they sit on the designed slab, not on the plate. The `#FFCD2C` at composite (360, 374) under `dark` is the light halo (overlay white @ alpha 44) mixed over `#FFC300`, not the accent hue.

- files: `tmp/k5_palette/` (script, PNGs, `report.json`, overlay `.mov`s). Not committed.
- next: finish / summary

### 19:26 — finish / summary

K5 is the recording mechanism. A palette is a pair (accent + pivot_ground) on `TimelineMetadata`, resolved once in RenderStep, passed through `--props`, hashed as `palette_hash` and into `overlay_input_hash`. Unset `retention_fast` renders the spike pair; an authored pair changes the pixels; K4's chooser, not a second colour system, is what keeps amber type off an amber plate.

**Files changed**

- Schema: `backend/app/schemas/timeline.py` (`EmphasisPalette`, `emphasis_palette`, `emphasis_palette_override`)
- Band + resolver: `backend/app/script/styles.py` (`emphasis_accent` / `emphasis_pivot_ground`, `resolve_emphasis_palette`); channel knobs on `backend/app/core/config.py`
- Render seam: `backend/app/workflow/steps/render.py` (resolve once → fingerprint + compositor)
- Overlay hash / props: `backend/app/renderer/compositor.py`
- Fingerprint: `backend/app/renderer/fingerprint.py` (`palette_hash`; raw palette fields stripped from the timeline dump)
- Compositor: `compositor/src/Emphasis.tsx`, `Stamp.tsx`, `Counter.tsx`, `Pivot.tsx`
- Tests: `backend/tests/unit/timeline/test_emphasis_palette.py` (new), `backend/tests/unit/script/test_emphasis_palette.py` (new), `test_styles.py`, `test_compositor.py`, `test_fingerprint.py`
- This plan (K5 status row + this work log)
- Live evidence (gitignored): `tmp/k5_palette/`

**Decisions (also in the entries above)**

- Scenario A as recorded. No K9 LLM call this slice.
- Last-last fallback for a non-retention band is the spike pair, so the compositor never invents hexes. Same pair `retention_fast` records, not a second colour-choosing system.
- Override / planner are a pair; channel / band may mix per role.
- Hash the resolved pair. Strip the raw metadata fields from the fingerprint dump so unset vs explicit-band-pair collide.

**Deviations / contradictions found**

- Plan phrase "roles, not hues" / `accent` / `alert` / `neutral` on the band is older than decision 7. This slice implements the pair in the K5 task table (accent + pivot_ground), not a three-role system.
- `LIGHT_MAX_LUMA` 105 / `DARK_MIN_LUMA` 180 meant the amber plate (luma 190.71) could never be `light`; the fight K4 actually fights here is `dark` (ink type) vs `slab` (accent on ink), not white-on-amber.
- venv is at repo root, not `backend/.venv`.
- Pre-existing ruff B905 in `test_styles.py` not touched.

**Not done (out of slice):** K9 LLM authoring of the palette, K8, vision, sampling dominant hue at render, any change to white/ink, pivot type as accent, spike file hardcoded colours.

No commit, no `git add`, no push. Working tree left dirty for review. Stopping.

---

## Work log — K9 LLM emphasis pass (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 20:02 — read / assemble

- read / opened: Decision 8 (~1175, v1 authors only pivot/stamp/counter; drop correction/meter/comparison/question in code, do not fail); K9 task (~804, one whole-film call after shot plan before narration, never seconds); device set (~380); Decision 4 register table (~1063, derive in code); K3 density 8–12/min pivot guaranteed (~1087); honesty/cited_fragment (~321); K12 strict-mode lesson; K5 leftover (`emphasis_palette` is K9's job); existing `emphasis_pass.py` (lexical stub); shot/director schemas; `run_structured_with_repair`; `romanize_captions.py` dry_run landmine; `pivot.py`; `emphasis_rules.py`; `EmphasisCue`/`EmphasisDevice` (do not narrow); `test_emphasis_pass_step.py`; `split_narration_fragments`; `EmphasisPalette` + `PIVOT_GROUND_MAX_LUMA` (schema already rejects near-white pivot_ground).
- decided: planner output is a default-free pydantic model (`device` is a plain str, not the wide domain enum). Quantity checks in `validate()`: duplicate/unknown shot_id, fragment out of range. Unknown devices are NOT validate-failures (Decision 8: drop, do not fail the run) — mapper logs and skips. Register derived in code (pivot→hi, counter→en, stamp→script of `text`). Palette written via `EmphasisPalette(...)` so hex + luma guards apply; invalid → leave unset. `is_satisfied` keys off `emphasis_pass_attempted` / `narration_locked` / style / no timeline — not "no pivot word" and not "already has a pivot cue". Dry-run stays lexical attach + enforce + stamp, no LLM. Cheap-vs-terra: use the default planning model (creative authoring, not mechanical transliteration).
- files: this plan (status row + this log header)
- next: schema, prompt, planner, step, tests

### 20:15 — schema / prompt / planner / step / tests

- decided: planner schema is default-free (`device` is a plain str). `validate()` rejects duplicate/unknown shot_id and out-of-range fragments (repair). Unknown devices are mapper-drops, not validate-failures (Decision 8: do not fail the run). Register derived in code. Palette via `EmphasisPalette(...)` so hex + `PIVOT_GROUND_MAX_LUMA` apply; invalid → leave unset. `is_satisfied` no longer treats "no pivot word" or "already has a pivot cue" as done. Dry-run = lexical pivot + K3 + stamp, no LLM (this env's `DRY_RUN` is False, so step tests autouse-patch it True). Planner uses the default planning model.
- files: `backend/app/planners/emphasis/schemas.py`, `planner.py`, `backend/app/prompts/emphasis/v1.md`, `backend/app/workflow/steps/emphasis_pass.py`, `backend/app/schemas/timeline.py` (docstrings only; `EmphasisDevice` not narrowed), `backend/tests/unit/planners/test_emphasis_planner.py`, `backend/tests/unit/workflow/test_emphasis_pass_step.py`
- tests: 24 passed (`test_emphasis_planner.py` + `test_emphasis_pass_step.py`). Related pivot/rules/palette/render_only: 91 passed. Ruff clean on the K9 Python files.
- next: live reel — real LLM, K3 before/after, overlay frames

### 20:35 — live reel (real LLM + Remotion overlay)

- did: `tmp/k9_emphasis/verify_k9.py` built a 19-shot timeline from a 694-char Hinglish script (one shot per fragment, durations clamped 0.8–3.5s off ~19 chars/s), created project `5be28b79-f986-4b3c-9553-37e744991c04` (`k9-emphasis-live`, `retention_fast`), called `run_structured_with_repair` through `OpenAIPlanningProvider` (not dry_run, real key), mapped, enforced K3, rendered via `render_or_reuse_emphasis_overlay` (real Chromium, ProRes 4444), extracted one RGBA frame per landed device. `tmp/` is gitignored.
- project: `5be28b79-f986-4b3c-9553-37e744991c04`
- duration: **35.24s**, 694 chars, 19 shots, 7 scenes
- palette authored: `accent=#00D9FF` `pivot_ground=#4A145E` (cyan against a street/SUV world; purple ground luma 44.6, well under 140)

**Cues BEFORE K3 (6)** — mapper output, registers derived in code, `offset_s=0.0`

| device | shot_id | text | register | anchor_fragment | values |
|---|---|---|---|---|---|
| counter | sc_02_sh_01 | SOLD IN 2025 | en | 1 | 200000 cited 1 |
| stamp | sc_03_sh_01 | king | en | 1 | — |
| counter | sc_04_sh_01 | SAFETY RATING | en | 1 | 5 cited 1 |
| pivot | sc_05_sh_01 | लेकिन | hi | 1 | — |
| stamp | sc_06_sh_01 | best | en | 1 | — |
| stamp | sc_07_sh_01 | skip | en | 1 | — |

**Cues AFTER K3 (5)** — `min_gap` dropped `sc_06_sh_01` stamp "best" (film index 13, one shot after the pivot at 12). Citation kept both counters (`2 lakh` → 200000, `five stars` → 5). Pivot kept.

Rate after K3: **8.51/min**. Floor of the 8–12 band; 5 cues in 35s is the bottom of "roughly 5–9 in a 35s reel". Not a miss. Pivot guaranteed.

**Frames (watched)**

| device | frame | path | what it shows |
|---|---|---|---|
| counter | 131 | `tmp/k9_emphasis/counter_0131.png` | cyan `1,76,874` counting toward 2,00,000, kicker `SOLD IN 2025`, slab ink. Band pixels `#00D9FF` (23622) / `#0A0A0B` |
| stamp | 271 | `tmp/k9_emphasis/stamp_0271.png` | white `king` on slab, cyan rule. Band pixels `#FFFFFF` (30741) / `#00D9FF` (2316) / `#0A0A0B` |
| pivot | 656 | `tmp/k9_emphasis/pivot_0656.png` | white `लेकिन` on purple full-bleed band. Band pixels `#4A145E` (79995, luma 44.6) / `#FFFFFF` (16364) |

Overlay: `tmp/k9_emphasis/storage/5be28b79-f986-4b3c-9553-37e744991c04/overlays/fa388a20c4da5dad9bbef0e1e16104363071550fe23c8273584364d92b96f5dd.mov`

Centre-pixel samples were transparent (bands are not at 360,640). Numbers above are opaque pixels inside each device band.

### 20:40 — finish / summary

K9 replaces the lexical-only stub: `EmphasisPassStep` runs one whole-film LLM call for `retention_fast`, maps v1 devices with Decision-4 registers derived in code, writes `metadata.emphasis_palette`, then K3. Lexical `attach_pivot_cue` remains the pivot backstop. Dry-run stays lexical + stamp.

**Files changed (this slice)**

- Schema (docstrings only; enum not narrowed): `backend/app/schemas/timeline.py`
- Planner: `backend/app/planners/emphasis/schemas.py`, `planner.py`
- Prompt: `backend/app/prompts/emphasis/v1.md`
- Step: `backend/app/workflow/steps/emphasis_pass.py`
- Tests: `backend/tests/unit/planners/test_emphasis_planner.py` (new), `backend/tests/unit/workflow/test_emphasis_pass_step.py`
- This plan (K9 status row + this work log)
- Live evidence (gitignored): `tmp/k9_emphasis/`

**Decisions (also in the entries above)**

- v1 authors `stamp`/`counter`/`pivot` only. `EmphasisDevice` stays wide. Unknown devices are mapper-drops, not validate-failures / not a failed run.
- `text_register` is not on the LLM schema. Derived: pivot→hi, counter→en, stamp→script of `text`.
- `validate()` repairs duplicate/unknown shot_id and out-of-range fragments. Density is K3, not the schema.
- Palette written through `EmphasisPalette(...)` so hex + `PIVOT_GROUND_MAX_LUMA` apply; invalid → leave unset (band fallback).
- `is_satisfied` keys off `emphasis_pass_attempted` / `narration_locked` / style / no timeline. Not "no pivot word". Not "already has a pivot cue".
- Dry-run = lexical pivot + K3 + stamp, no LLM. The stamp locks a later real run out of the LLM pass on that project (romanize RV-R3 shape). Documented: dry-run timelines are fixtures.

**Deviations / contradictions found**

- Live shots were created one-per-fragment, not a Shot Planner LLM call. Allowed by the brief ("can reuse/create shots"); the emphasis call was real.
- Overlay only, no plate composite. Devices are visible on transparent ProRes; that is enough to watch them.
- The model did not stamp the brand (`Hyundai`/`Creta`); it stamped `king` / `best` / `skip`. Brand was in the script. Taste, not a drop.
- After K3, 8.51/min is the floor of 8–12. Six authored, one `min_gap` drop next to the pivot. Pivot present.
- This env's `DRY_RUN` is False; step tests autouse-patch it True so the lexical path still runs without a session.
- HEAD moved to `598c4b3` (K5 Rec.601 extract) during the slice. Uncommitted K5 `PIVOT_GROUND_MAX_LUMA` + palette tests are also in the tree; K9's mapper relies on `EmphasisPalette`'s validator (near-white → leave unset) but did not author that guard.
- venv is at repo root, not `backend/.venv`.

**Not done (out of slice):** correction/meter/comparison/question renderers, K8 charts, inferred extra years, SFX, pacing/camera/transitions, narrowing `EmphasisDevice`, guessing seconds.

No commit, no `git add`, no push. Working tree left dirty for review. Stopping.

### 21:05 — review findings 1 & 2, measured A/B on the identical script

- decided: prove both findings with live re-runs of `tmp/k9_emphasis/verify_k9.py`'s exact 694-char script and 19-shot timeline (new driver `tmp/k9_prompt_fix/verify_prompt.py`, which takes the prompt file as an argument so the committed prompt and the edited one meet the same input). No Remotion — the question is which words get chosen, and K9 already proved the devices draw. All calls on one throwaway project per pass, `-test` suffixed, deleted afterwards. Baseline re-measured rather than trusted: the recorded 20:35 numbers are one sample and this model varies.
- did: seven live calls. Baseline on the committed `d2f468b` prompt, then two prompt states, then a one-line code probe, then two calls on the state actually left in the tree. K3 drop rules captured off the `emphasis_rules.dropped` log records, not inferred from the diff.
- projects: `60713a39-ea61-47f0-8838-305fcf6a85a1` (5 calls) and `e64d3c71-cfa0-4fd8-ac74-d43e90d67780` (2 calls), both `k9-prompt-fix-test` / `retention_fast`. Both deleted (project row + 7 and 2 `llm_call` rows; no `timeline_version` / `narration` rows were ever written — the driver never persists the timeline).
- constant across every run: 694 chars, **35.24s**, 19 shots, 7 scenes, `min_shot_gap=3`, `emphasis_max_cues_per_minute=12.0`, `accent=#00D9FF` every single time, `pivot_ground` a deep purple every single time (luma always well under 140). The pivot landed on `sc_05_sh_01` in all seven.

**Baseline — committed prompt (`old_a`)**

| film idx | device | shot_id | text | anchor | values |
|---|---|---|---|---|---|
| 2 | counter | sc_02_sh_01 | `UNITS SOLD` | 1 | 200000 cited 1 |
| 5 | stamp | sc_03_sh_01 | `king` | 1 | — |
| 9 | counter | sc_04_sh_01 | `SAFETY RATING` | 1 | 5 cited 1 |
| 12 | pivot | sc_05_sh_01 | `लेकिन` | 1 | — |
| 15 | stamp | sc_06_sh_03 | `sawaal` | 3 | — |
| 17 | stamp | sc_06_sh_05 | `dikhai` | 5 | — |

Authored **6 = 10.22/min**; K3 dropped `sc_06_sh_05` (`min_gap`, idx 17 is 2 after 15); delivered **5 = 8.51/min**. No brand stamp. **The 20:35 figures reproduce to the digit** — 10.22 authored, 8.51 delivered, one `min_gap` drop, brand unstamped. Both findings' premises confirmed on fresh evidence, not just the recorded run.

**Finding 1 (stamps are evaluative, not concrete) — REAL, and the fix holds**

The stamp bullet gained a stated preference order (proper noun / brand / model name / the thing itself, with an evaluative adjective as the explicit fallback) — still one bullet, no banned-word list, prompt 73 → 76 lines. Both runs of the state now in the tree:

| run | authored stamps | brand stamped? | survived K3? |
|---|---|---|---|
| `final_a` | `Creta` (idx 1), `SUV` (5), `safest` (16) | **yes** | **yes** |
| `final_b` | `king` (5), `Creta` (14), `safest` (16) | **yes** | no — `min_gap`, idx 14 is 2 after the pivot at 12 |

Brand stamped in **2 of 2** runs of the shipped prompt, and in 3 of 5 runs across every edited state tried, against **0 of 2** on the committed prompt (this baseline plus 20:35). `HYUNDAI CRETA` is on screen where `king` used to be. Not a clean sweep: `king` came back once and `safest` in both, and the counter kickers improved on their own (`SOLD IN 2025`, `SAFETY STARS`).

**Finding 2 (K3 trims to the floor, so aim higher) — premise real, the prescribed fix is NOT. Reverted.**

The observation is right: delivered sits on 8.51/min, the floor. The prescribed cause is not. Three prompt/code states, five runs:

| state | authored | authored/min | delivered | delivered/min | K3 drops |
|---|---|---|---|---|---|
| committed (baseline) | 6 | 10.22 | 5 | **8.51** | `min_gap` ×1 |
| + "Author at the TOP of it… the middle lands on the floor" (`new_a`) | 6 | 10.22 | 4 | **6.81** | `min_gap` ×2 |
| same (`new_b`) | 6 | 10.22 | 4 | **6.81** | `values_citation`, `min_gap` |
| + "**three or more shots between consecutive cues**" (`new_c`) | 5 | 8.51 | 5 | **8.51** | none |
| same (`new_d`) | 6 | 10.22 | 4 | **6.81** | `values_citation`, `min_gap` |
| same + `Target cue count` multiplier 10.0 → 12.0 (`new_e`) | 5 | 8.51 | 5 | **8.51** | none |

Every state was worse than or equal to the baseline. Best case was 8.51 — the floor the finding was written to escape. Both edits reverted; the density section and `planner.py` are byte-identical to `d2f468b`.

- found: **the model does not read the density instruction from the prompt. It reads a number from the user content.** `_build_user_content` states `Target cue count: 6` (`planner.py`, `round(duration_s / 60.0 * 10.0)` — the middle of the band), and the model authored exactly that count in every run where the number said 6, prose to the contrary in the same call notwithstanding. Prose cannot raise a count that code states as an integer.
- found: raising that integer does not work either. At 12.0 the user content asked for **7** and the model authored **5** (`new_e`, and `new_c` at the old multiplier did the same). Told "three or more shots between cues" it picks 0/4/8/12/16 — spaced by 4, five cues, zero K3 drops — satisfying spacing over count. The count is not what the model is optimising.
- found: **telling the model the spacing rule costs counters.** The two zero-drop runs (`new_c`, `new_e`) are also the only two runs with **no counter at all** and no brand — all-stamp reels of `traffic` / `city` / `family` / `safest`. Spacing freedom appears to be what lets it reach the shots where the numbers are.
- found: **the shot after the pivot is structurally doomed on this timeline, and that is what eats the rate.** `sc_05` (the `Lekin` beat) is a single shot at film idx 12 and `sc_06` starts at 13, so with `min_shot_gap=3` any cue on idx 13/14 dies — 20:35's `best` at 13, `final_b`'s `Creta` at 14, `new_b`'s at 14. The model anchors one cue per scene head; on this timeline one scene head is always inside the pivot's gap. That is the pivot-rescue path working as designed, and no wording fixes it. Real headroom is there — 19 shots at gap 3 hold 7 cues (0/3/6/9/12/15/18 = 11.92/min) — but reaching it needs the authoring pass to know where the gap boundaries fall, which is placement information, not exhortation.
- found: a second `values_citation` gap, not mine and not a hallucination. `new_d` cited `Do lakh.` for 200000 and was dropped: `_stated_numbers` reads Devanagari `दो लाख` and English `two lakh`, but not **romanised** Hindi number words (`do`, `das`). `new_b` lost `PRICE`/10 the same way — the narration says `das lakh` (= 1000000), so citing 10 was also the model's error there. Widen the matcher when it is worth measuring; the module docstring already says a drop is not evidence of invention.
- tests: `python -m pytest tests/unit -q` → **1429 passed, 6 failed** in 125.51s. Identical to the recorded baseline: 5 in `test_sfx_overlays_diegetic.py`, 1 in `test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`. No new failure. No test asserts on this prompt's text (checked), so nothing green went red and nothing was deleted to keep it green. `ruff check` clean on `app/planners/emphasis/`, `app/prompts/`, and the throwaway driver.
- files: `backend/app/prompts/emphasis/v1.md` (stamp bullet only), this plan (K9 status row + this log). Live evidence, gitignored: `tmp/k9_prompt_fix/` (driver, `v1_old.md` snapshot, seven `report_*.json`).
- next: finish / summary

### 21:20 — finish / summary

One of the two review findings is fixed and proved; the other is a real symptom with a misattributed cause, measured five times and reverted rather than forced.

**Files changed (this pass)**

- Prompt: `backend/app/prompts/emphasis/v1.md` — the `stamp` bullet, and nothing else. 73 → 76 lines.
- This plan (K9 status row + the 21:05 and 21:20 entries)
- Live evidence (gitignored): `tmp/k9_prompt_fix/`

**Reverted after measurement, deliberately left out of the tree**

- The density section's "author at the TOP" rewrite. Delivered 6.81/min twice, against a 8.51 baseline.
- A follow-on "three or more shots between consecutive cues" line. Delivered 8.51 / 6.81, and both of its zero-drop runs authored no counter and no brand.
- `planner.py`'s `Target cue count` multiplier at 12.0 instead of 10.0. Out of the brief's scope (it is code, not the prompt) and it did not work: the model authored 5 when asked for 7.

**Deviations / contradictions found**

- The brief located both findings in `v1.md`. Finding 2 does not live there. The number the model obeys is `Target cue count` in `_build_user_content`, and raising it did not help either — so finding 2 is not a wording problem at all. It is a placement problem: the authoring pass cannot see where `min_shot_gap`'s boundaries fall, and the shot after a one-shot pivot scene is unreachable by construction.
- Finding 1's brand claim needed a caveat: the brand now reaches the screen every run, but K3 drops it when the model puts it on the shot right after the pivot (1 of 2 shipped-prompt runs).
- The first version of this pass measured the brand improvement on a prompt that ALSO carried the density edit, so the state left in the tree had never itself been run. Re-run twice (`final_a`, `final_b`) before writing any of this down.
- Console is cp1252 here; `PYTHONIOENCODING=utf-8` is required or printing `लेकिन` kills the driver after the LLM call has already been paid for. The driver writes its JSON before printing, so nothing was lost.
- `verify_k9.py` names its project `k9-emphasis-live`, with no `-test` suffix, so it does not match the standing purge convention. The new driver uses `k9-prompt-fix-test`. Unrelated leaked `*-test` rows (many `shot-planner-test`, `asset-planner-test`, one `k7-pivot-test`) are still in the shared DB; not touched here.
- Cost: seven live planning calls, roughly 7 cents.

**Not done (out of slice):** any change to K3, the `retention_fast` band knobs, `emphasis_max_cues_per_minute`, `EmphasisDevice`, or the planner schema. No Remotion render (no stamp came close to overflowing its band — longest was `Hyundai Creta`, and the counter band is content-derived since K11). No widening of the `values_citation` matcher to romanised Hindi numerals — done at 22:10 below.

No commit, no `git add`, no push. Working tree left dirty for review. Stopping.

---

## Work log — K3 citation matcher reads romanised Hindi (2026-09-09)

This section is an implementation diary, not a design change. Earlier sections above stay authoritative. Append only; never rewrite prior log entries.

### 22:10 — romanised Hindi in the values-citation matcher

- decided: close the gap the 21:05 entry recorded. `_fragment_contains_value` read a cited number as digits, as Devanagari words and as English words, but not as **romanised** Hindi — and this pipeline's narration is Hinglish written in Latin script, so romanised is the most likely of the three. The live K9 script says `2025 mein 2 lakh models bikhe` and `Safety rating mein paanch stars`; `do lakh` / `Do lakh.` / `das lakh` / `paanch stars` all dropped with `rule=values_citation`, which reads in the log as "the model invented a number". Same failure mode as the original finding, one transliteration layer deeper. Scope: the matcher only — no density change, no band knobs, no prompt, nothing under `app/planners/emphasis/`.
- found: **no romanised numeral table exists anywhere in the backend to reuse.** `caption_romanizer/numerals.py` is Devanagari-keyed (0–99 plus `सौ`/`हजार`/`लाख`/`करोड़`, nukta variants), and the Latin side of that pass is produced per scene by the LLM as plain 1:1 transliteration (`prompts/caption_romanizer/v1.md`) and never stored as a table — grep for `paanch|panch|hazaar|karod|pachaas` across `backend/` hits only that module's own comments, its two test files and rendered `.ass` captions in `storage/`. So the spellings had to be new. The VALUES did not: `_ROMAN_TO_DEVANAGARI` maps each Latin spelling to the Devanagari word it transliterates, and `_roman_tables()` derives the integer and the is-it-a-scale answer from `numerals.word_value` / `numerals.is_multiplier`, raising at import if a spelling's Devanagari side is not in `numerals.TABLE`. That module stays the single source of truth for what a Hindi number word means, and a respelling there cannot silently narrow this matcher.
- decided: **the collision guard, which is the whole risk of this change.** Several natural transliterations are ordinary words: `do`/`so`/`char`/`tin`/`teen`/`bees`/`tees`/`sat` are English, `sath` is साथ ("with"), `chah` is चाह ("desire"). Reading "I do think" as 2 would CERTIFY a number the narration never said — strictly worse than the drop being removed, because `rule=values_citation` is only ever logged on a DROP, so a forged match is invisible. Guard: a colliding spelling is read ONLY as the coefficient of an immediately following scale word (`do lakh` == 200000; a bare `do` states nothing). That costs nothing that works today — every romanised reading dropped before this change — and it is the form reels actually use. Unambiguous spellings (`paanch`, `chaar`, `das`, `dus`, `saat`, `aath`, `nau`, `pachaas`) are read bare.
- decided: `so` for `सौ` is **not in the table at all**, and must not be added. The guard above is "a scale word must sit next to it", and `do so` satisfies it — "I do so think" would forge 200. `sau` is spelled unambiguously when a reel means 100.
- found: **the first draft was wrong and the probe caught it.** It also mapped `sau`/`hazaar` and ran `numerals.find_numeral_runs` a second time over a Devanagari shadow of the words, to read `do hazaar chhabbis` == 2026. Measured result: `do hazaar chhabbis` cited **2000** — Hindi puts a numeral's remainder AFTER those two tiers, and `chhabbis` was not in the table, so the run parsed short and forged a number the narration did not state. Devanagari is safe there only because §11's parser consumes a whole run and refuses a partial merge; a Latin table cannot be closed the same way (`chhabbis`/`chhabis`/`chabbis` are all plausible), so ANY missing spelling fails open. Both the `sau`/`hazaar` tier and the shadow-run reading were removed. `do hazaar chhabbis` == 2026, `unnis sau ikatees` == 1931 and `das hazaar` == 10000 are therefore UNCOVERED and drop, which is the fail-safe direction — and 2000 / 1900 / 43000 are now pinned as drops so nothing re-opens it. The `lakh`/`crore` tier keeps its pair reading: a reel says "do lakh", and that reading is the same lenience the English side has shipped since the first review.
- found: two pre-existing leaks in the shipped matcher, both closed by one tightening. A scale word with no coefficient stated its own value, so `lakh ka sawaal hai.` CITED 100000 — and worse, `do lakh SUVs bik gayi.` also CITED 100000, because the reader fell through the then-unknown `do` and read `lakh` alone. A bare unit is not the number, so `_Reading` now carries `is_scale` and a scale word states a value only as part of a pair (`hundred thousand` == 100000 still reads; `2.5 lakh` unchanged).
- measured: `tmp/k3_roman_citation_probe.py` (throwaway, gitignored) runs the real `_fragment_contains_value` beside a verbatim copy of the `c1ee501` matcher. 34 rows, **0 negative leaks, 0 unmet positives**. DROPPED → CITED: `do lakh SUVs bik gayi.`/200000, `Do lakh. Yeh number bada hai.`/200000, `das lakh se kam price.`/1000000, `paanch stars mila.`/5, `paanch karod views.`/50000000, and both live K9 sentences — `Safety rating mein paanch stars`/5 (`2025 mein 2 lakh models bikhe`/200000 already worked). Unchanged CITED: `2 lakh`, `दो लाख`, `two lakh`, `five stars`, `पाँच stars`. Still DROPPED: `I do think so, it is fine.` against 2 AND against 100, `Woh do so ka matlab samjha.`/200, `The char marks…`/4, `The bees were loud…`/20, `Woh mere sath thi.`/7, `nice car, no figure here.`/200000, `do SUVs bik gayi.`/200000, `do lakh`/2, `das lakh`/10, `paanch stars`/500000, `saal 2025 mein.`/202, `do hazaar chhabbis`/2000 and /26, `unnis sau ikatees`/1900, `43 hazaar 391 rupaye.`/43000. TIGHTENED (cited before, drops now): `lakh ka sawaal hai.`/100000 and `do lakh SUVs bik gayi.`/100000.
- did: updated the module docstring's rule 3 and this plan's guardrail 1 (plus the K3 status row and section one-liner) to list the readings now implemented AND what stays uncovered, with the reason each thing is withheld — every gap is on the side of dropping rather than forging.
- tests: `tests/unit/timeline/test_emphasis_rules.py` — the newly-cited rows (including both live K9 sentences and `chaar jobs karni padin.`/4) plus every negative above, in a dedicated `test_romanised_collisions_with_ordinary_words_are_never_cited` whose docstring says why it must not be weakened, and a table-integrity test that every romanised spelling resolves through `caption_romanizer.numerals` and that `so`/`sau`/`hazaar` are absent on purpose. Existing behaviour kept: empty `values`, one miss dropping the whole cue, an out-of-range `cited_fragment`, and a value stated nowhere. `python -m pytest tests/unit -q` → **1456 passed, 6 failed** in 111.83s. Baseline was 1429 passed / 6 failed; the same 6 are pre-existing (5 in `test_sfx_overlays_diegetic.py`, 1 in `test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`) and were not touched. +27 tests, no new failure.
- ruff: `python -m ruff check app/timeline/emphasis_rules.py tests/unit/timeline/test_emphasis_rules.py ../tmp/k3_roman_citation_probe.py` → **All checks passed!** No formatter run.
- files: `backend/app/timeline/emphasis_rules.py`, `backend/tests/unit/timeline/test_emphasis_rules.py`, this plan (K3 status row, K3 section one-liner, guardrail 1, the 21:20 "not done" line, this entry). Probe in `tmp/` (gitignored, throwaway).
- next: nothing. No commit, no `git add`, no push. Working tree left dirty for review. Stopping.

---

## Work log — first real end-to-end reel (2026-09-09)

### 18:05 — the reel that found K13

- did: ran the FULL `DEFAULT_PIPELINE` on a fresh `retention_fast`
  project for the first time with K9 in it. Everything before this was
  component-level: pixel samples, cue tables, luma figures, overlays on
  transparency. Nobody had watched a finished reel, and the original
  complaint this whole plan answers was "the video is boring".
- setup: dedicated backend on 127.0.0.1:8001 started with
  `BURN_CAPTIONS=false` (env vars beat `.env`; verified
  `settings.burn_captions` False with the override and True without),
  so `.env` and the user's own server were untouched. Not dry-run --
  a dry-run pass stamps `emphasis_pass_attempted` and would lock the
  project out of the LLM pass permanently.
- found: **three consecutive failures at `generate_timeline`**, all
  identical: `shot durations sum to 3.5s, expected close to the
  scene's 6.0s (tolerance 1.2s)`. Root cause is upstream of this whole
  plan and worth recording: `retention_fast` caps a shot at 3.5s, the
  tolerance is 1.2s, and the Shot Planner anchors one shot per
  fragment -- so **a single-sentence scene longer than 4.7s cannot be
  planned.** It emits one 3.5s shot and fails. The Scene Planner has
  no knowledge of that constraint and produces impossible scenes some
  fraction of the time.
- found: retrying is USELESS and I wasted two attempts learning it.
  The scene plan is PERSISTED, so a re-trigger re-runs the Shot
  Planner against the same impossible scene and fails identically,
  forever. A user hitting this in the app has a permanently stuck
  project and a retry button that cannot ever work. Not this plan's
  bug; worth its own writeup.
- did: rewrote the same script as 12 short sentences (longest 53
  chars) instead of 6 long ones, so no scene can be a long
  single-fragment block. Planned first time: 7 scenes, 12 shots,
  24.63s.
- measured, and this is the reel:

  | | |
  |---|---|
  | cues authored by K9 | 4 = 9.74/min |
  | cues after K3 | 3 = **7.31/min** (below the 8-12 band) |
  | K3 drop | `service centre` stamp, `min_gap` |
  | cues | `Tata Nexon` stamp / `लेकिन` pivot (reg hi, on the real turn) / `Parts` stamp |
  | counters | **ZERO**, from three spoken numbers -- see K13 |
  | palette authored | `#B6FF00` accent, `#003F46` pivot ground |
  | graphic shots flagged | 4 of 12 |
  | spend | 4c planning; generation NOT run |

- worked, on a script nothing had been tuned against: the brand got
  stamped (`c1ee501`'s stamp-preference fix, third fresh confirmation);
  the pivot landed on the real turn with register `hi`; K12 flagged
  four graphic shots sensibly; and the authored `#003F46` passed
  `PIVOT_GROUND_MAX_LUMA` silently in production, which is the
  guardrail doing its job hours after it landed.
- `offset_s` is 0.0 on all three cues and that is CORRECT, not
  unresolved: each cue's anchor word is the first word of its shot.
- decided: STOP before generation (user's call, and right). The reel
  cannot contain its strongest device, so $1.06 of image generation
  would buy a known-degraded artifact. K13 first.
- next: K13 option B -- and it needs the user's confirmation before an
  agent executes, because A and B are not equivalent and the choice is
  editorial, not mechanical.

---

## K14 - The hook is empty, and the density rules are why  **(ADDED 2026-09-10, the next slice)**

Found by watching `nexon-reel3-test` (`34dd1ee1`), the first finished
`retention_fast` reel with kinetic text on real plates. The devices
render correctly. The reel still feels flat, and the reason is
measurable rather than aesthetic.

### What the finished reel actually did

24.70s, 12 shots, 3 cues = **7.29 cues/min**, below the 8-12 band.

| when | what is on screen |
|---|---|
| 0.00 - 7.15s | **nothing** (29% of the reel, and the retention-critical part) |
| 7.15s | counter `SAFETY RATING` counting to 5 |
| 12.75s | pivot (the best frame in the reel) |
| 15.17 - 22.92s | **nothing** (7.75s) |
| 22.92s | stamp `centre` |

### Two different problems

**1. The hook is empty because the rules forbid a dense hook.**
`min_shot_gap = 3`, and this reel's shots average ~1.9s, so the earliest
a second cue may legally appear after a first is ~5.7s later. The hook
is shots 0-2, i.e. 0.00-5.54s. **Two cues inside the first five seconds
is not unlikely under K3, it is impossible.** K9 could not have fixed
this by trying harder - `enforce_emphasis_rules` would have stripped it.

**2. The body dead stretch is ordinary under-authoring.** 15.17-22.92s
spans about 4 shots and could legally have held one or two more cues.
Nothing blocked them. `_build_user_content` states
`Target cue count: round(duration_s / 60 * 10.0)` = 4 for this reel, and
K9 authored 3. That is the integer identified in the 21:20 work log,
still unfixed.

### The contradiction this exposes

The spike is the only artifact anyone has watched and liked. Its own
measured onsets, from the "What the spike proved" table earlier in this
document:

`EVERY/3rd/SUV` 0.69 - `HYUNDAI CRETA` 1.49 - `2025` 2.69 -
`2,00,000+` 3.60 - the pivot 4.94 - `REALLY?` 5.42

**Six beats in the first 5.42 seconds, about 66 cues/minute.** Four of
the six were judged to work; the two number beats failed on CONTRAST,
which is what K4 fixed, not on density. Even counting only the four,
the spike's hook runs at roughly 44/min.

The band this plan ships is **8-12/min**, and it was never derived from
that measurement - it came from a recommendation and sounded reasonable.
The one thing known to work exceeds it by 4-5x in the hook.

**So density cannot be a single uniform rate.** It has to be a hook
budget plus a body rate.

### The parts

**K14.1 - a hook window with its own budget and its own gap.** Define
the hook as the first N seconds of the reel (start at 5.0s), resolved
per style like every other knob (RV2 / R1). Inside it: require at least
2-3 cues, with the first landing inside roughly the first 1.5s, and
relax `min_shot_gap` to 0 or 1 so consecutive shots may both carry a
cue. Outside it: gap 3 as today. Shot membership comes from
`compute_shot_start_times` (D5-correct), not from shot index - the hook
is a duration, not a count.

**K14.2 - the rate cap must change with it, or it will undo K14.1.**
A 5s hook holding 3 cues, plus a body at 12/min across the remaining
25s, is about 8 cues in 30s = **16/min average**, which the current
12.0 ceiling rejects. Either compute the cap over the body only, or
raise it. Decide which and record why; do not leave the cap silently
strangling the hook.

**K14.3 - tell K9 that position matters.** The prompt says "8-12 per
minute, pivot guaranteed", which is a uniform instruction, and the model
placed cues by narrative logic: the number, the turn, the conclusion.
That is what a writer does. A retention editor front-loads. The prompt
and `_build_user_content` must name the hook explicitly and say the
first seconds are worth more than the last. Even with a larger budget
the model will keep spreading evenly if nothing tells it otherwise.

**K14.4 - raise the body target count.** `round(duration_s/60 * 10.0)`
in `planners/emphasis/planner.py`. Prose cannot move it; this integer is
what the model obeys. Measured 2026-09-09: raising the multiplier to
12.0 alone did NOT help (asked 7, authored 5), so treat this as
necessary-but-not-sufficient and pair it with K14.1/K14.3 rather than
shipping it alone.

**K14.5 - word-level entry for a multi-word hook cue. CORRECTION: this
is NOT already built.** The spike's `EVERY / 3rd / SUV` at
0.69/0.83/1.17 was ONE cue whose three words dropped in at separate
onsets - three felt hits, one cue, no rule violated. That is the
cheapest density available. But it lived in `EmphasisOverlay.tsx`, a
throwaway spike file. What production `Stamp.tsx` has is **per-GRAPHEME
CLUSTER** stagger via `Intl.Segmenter` - letters, not words. Feeding it
`"EVERY 3rd SUV"` would type the phrase out character by character,
which is a different look entirely. Word-level onsets are new renderer
work, and the K9 prompt currently defines a stamp as "one stressed
spoken word", so the authoring side must also allow a short phrase.

**K14.6 - re-derive the band, after watching.** Once a reel exists with
a dense hook, replace 8-12 with numbers taken from something watched.
Do this LAST: a number derived from another guess is not an improvement.

### BLOCKING dependency - do not ship captions-off before this

`retention_fast` captions-off is decided (decision 1) and already
briefed, and it must NOT land first. Those first 7 empty seconds used to
carry burned captions. They were removed on the promise that dense
kinetic text replaces them, and at 3 cues in 24.70s it does not - the
reel measured above is **less** filled than the version that was called
boring. Shipping captions-off now makes reels emptier, and it will look
like the captions decision was wrong when the cause is density.

### Verification - watched, not asserted

A green suite proves nothing here. Re-render a real `retention_fast`
reel and report: the onset of the FIRST cue (target: under about 1.5s),
the cue count and rate inside the hook window, the cue count and rate
across the body, the longest stretch anywhere with nothing on screen,
and the before/after against this reel's 7.15s first cue, 7.29 per
minute, and 7.75s dead stretch. A NEW project is required - `34dd1ee1`
is `narration_locked` with `emphasis_pass_attempted=True` and can never
be re-authored.

Do not tune knobs until the numbers look nice. If a change measures
worse, report it and revert, the way the 21:20 density attempt was.

### Do not change

The pivot look - white type on the authored band, full-bleed, decaying
shake - was the best frame in the reel and the spike's own strongest
beat. K4's contrast thresholds, K3's citation matcher, K13's option-B
prompt rule, and `EmphasisDevice` staying wide are all settled and out
of scope.

---

## Work log — K14 hook density (2026-09-10)

This section is an implementation diary, not a design change. Append only.

### 00:21 — K14.1

- read: full K14 section (measurements on 34dd1ee1, six parts, do-not-change, verification). Uniform gap 3 makes two cues in the first 5s impossible; spike ran ~66/min in the hook.
- decided: hook = first `emphasis_hook_s` seconds (5.0 on `retention_fast`). Shot membership is **start time < hook_s** via `compute_shot_start_times` (D5-correct), not shot index and not overlap of [0, hook_s). A long first shot of 6s is in the hook (starts at 0); its successor at 6.0 is body. Hook gap = 1 so `i - last < 1` never fires for two different indices — consecutive hook cues survive. Gap 0 would skip the rule under `if gap > 0`. Body keeps gap 3.
- files: `backend/app/script/styles.py` (band fields + resolvers), `backend/app/timeline/emphasis_rules.py` (`hook_s` / `hook_min_shot_gap` on `enforce_emphasis_rules`), `backend/app/workflow/steps/emphasis_pass.py` (RV2 resolve-once into enforce).
- tests: pinned three consecutive stamps on shots 0/1/2 (starts 0/1.75/3.5) survive at hook_gap=1 and drop under uniform gap 3; short vs long first-shot membership; body adjacent after hook still drops.
- next: K14.2 body-only rate cap (without it this slice is a measured no-op).

### 00:22 — K14.2

- decided: **compute the rate cap over the BODY only** (cues whose shots start >= hook_s; allowed = `12.0 * (duration_s - hook_s) / 60`). Hook cues are extra and never dropped by `rate_cap`. Do NOT raise the whole-reel cap to ~16 — that would let the body pack 16/min too. Do NOT leave 12.0 on the whole reel — a 5s/3-cue hook + body at 12/min ≈ 16/min average and would strip the hook back out. Pivot still never dropped. Recorded in the band field comment and in `_apply_rate_cap`.
- files: `emphasis_rules.py` (`_apply_rate_cap`), `styles.py` (comment on `emphasis_max_cues_per_minute`).
- tests: `test_body_only_rate_cap_does_not_strip_a_dense_hook` — 8 authored cues survive body-only; the same set under whole-reel 12/min keeps only 6. Full-reel resolver test updated: 20×1.75s keeps `0,1,2,5,8,11,14,17` (8), not the old 7.
- next: K14.3 prompt / user-content front-load.

### 00:23 — K14.3

- decided: Density section in `emphasis/v1.md` no longer says uniform 8–12/min / "space them". Names hook, front-load, first cue ~1.5s, 2–3 cues in the window, consecutive OK in hook, body may rest. `_build_user_content` names the hook explicitly (window length, min cues, first-cue deadline, consecutive OK, body remainder with gap 3) when `resolve_emphasis_hook_s` is set.
- files: `backend/app/prompts/emphasis/v1.md`, `backend/app/planners/emphasis/planner.py` (`_density_target_line`).
- tests: `test_build_user_content_names_the_hook_and_uses_12_multiplier`; non-hook style keeps the old uniform band line.
- next: K14.4 multiplier + split target.

### 00:24 — K14.4

- decided: authoring multiplier `10.0` → **12.0**. Split target = hook_min (3, clipped to total) + body remainder, not one uniform number. Necessary-but-not-sufficient; shipped with K14.3 wording, not alone. Stamp prompt also allows a 2–4 word spoken phrase as one cue (feeds K14.5).
- files: `planner.py` (`_TARGET_CUES_PER_MINUTE`, `_HOOK_MIN_CUES`, `_HOOK_FIRST_CUE_DEADLINE_S`), `emphasis/v1.md` stamp device line.
- tests: asserts `multiplier 12.0/min` and split `at least N in the first 5.0s hook + M in the body`.
- next: K14.5 word stagger in Stamp.tsx.

### 00:25 — K14.5

- decided: production `Stamp.tsx` was grapheme-cluster only. Multi-word `text` (whitespace) now splits on whitespace and staggers WORDS at spike-like delays 0 / 4 / 14 / 24 frames (4th extends +10); each word still grapheme-staggers internally (never `.split("")`). Single word unchanged. One cue, one `anchor_fragment`. Left `SuvRetention.tsx` / `EmphasisOverlay.tsx` alone. No second timing path of seconds in the planner.
- files: `compositor/src/Stamp.tsx`.
- tests: Python compositor suite still green (Stamp is TS; no new Remotion unit harness). K14.6 not done — re-derive 8–12 after a watched reel.
- next: deviations + handoff. User will render a NEW project; `34dd1ee1` cannot be re-authored.

### 00:25 — deviations / handoff

- deviations: none material. Hook membership chose **start < hook_s** (documented + tested). Hook authoring floor is 3 (clipped when total target is smaller). Fourth-word delay 24 frames (spike only measured three).
- K14.6 not implemented (out of scope for this slice).
- did not touch `backend/app/prompts/shot_planner/v1.md` (dirty K13 option B).
- tests run: `pytest tests/unit/timeline/test_emphasis_rules.py tests/unit/script/test_styles.py tests/unit/workflow/test_emphasis_pass_step.py tests/unit/planners/test_emphasis_planner.py tests/unit/renderer/test_compositor.py -q` → **173 passed**.
- no commit, no git add. No project created, no OpenAI call.

### 00:26 — review (Grok 4.6)

- K14.1–14.5 match the section. K14.2 choice is body-only cap, tested (`test_body_only_rate_cap_does_not_strip_a_dense_hook`: 8 survive vs 6 under whole-reel 12/min). Do-not-touch list held (`SuvRetention` / `EmphasisOverlay` / pivot look / K4 / citation / `EmphasisDevice` / K13 `shot_planner/v1.md` left as the pre-existing dirty option-B prompt).
- `python -m pytest tests/unit -q` from `backend`: **1462 passed, 6 failed**. Baseline was 1456/6; the six failures are the pre-existing director-planner + sfx-diegetic set. No new failure.
- Observations, not reverts: (1) first-cue ~1.5s is prompt-only — K3 cannot invent a cue; (2) authoring still splits a *whole-reel* 12/min total (24.7s → 5 = 3 hook + 2 body) while enforcement would keep more body; (3) 4th stamp word at +24 frames vs `STAMP_HOLD_S` 0.86s (~26 frames, 3-frame exit) — 3-word phrases are fine, a 4-word stamp’s last word barely lands. Watch before retuning.
- K14.6 not done. No project created. User renders a NEW `retention_fast` reel and reports first-cue onset, hook rate, body rate, longest empty stretch vs 7.15s / 7.29 per min / 7.75s.

### 01:10 — review findings 1-4 (the geometry the slice did not check)

- read: the four findings, `emphasis_rules._apply_min_gap` / `_apply_rate_cap` / `_shot_in_hook` / `_gap_for_shot`, `planners/emphasis/planner` density lines, the `styles.py` emphasis band, `compositor/src/Stamp.tsx`. All four reproduce with the real functions on the watched reel's shot shape (12 shots, 24.68s, starts 0.00 / 2.82 / 5.54 / 7.15 / 8.84 / 10.65 / 12.75 / 15.16 / 17.09 / 19.13 / 21.09 / 22.92).
- decided (finding 1): **adaptive hook floor, NOT a wider window.** The hook is a duration; how many cues it can hold is geometry, because one cue per shot is structural. `_hook_capacity` counts shots whose start < `hook_s` through the SAME `compute_shot_start_times` helper `_shot_in_hook` uses (no second start-time formula, RV2 / R1), and the request is `min(_HOOK_MIN_CUES, capacity, total)` — 2 on this shape, 3 when the cutting is fast enough to put a third start inside 5.0s. The user-content line now also states the capacity, so the model is told what the window can hold. The arithmetic for the other option, recorded and NOT taken: widening `hook_s` to 5.6s would put shot 2 (5.54s) inside and buy a third hook cue, but it also hands three shots to hook gap 1 and shortens the body-only cap's denominator (19.68s → 19.08s, allowed body cues 3.94 → 3.82), i.e. it trades a body cue for a hook cue. That is a K14.6 decision to make from a watched reel, not from arithmetic, and doing both at once would leave neither measurable. `hook_s` stays 5.0.
- decided (finding 2): the min-gap distance is now measured from the last kept cue **in the same regime** (`_Keeper` per hook / body). Hook membership is `start < hook_s` and starts are non-decreasing, so hook shots are a prefix of film order and the split keeper is well defined. Pivot guarantees re-read through the split and all still hold: never dropped; a non-pivot yields only to a pivot inside its OWN regime's gap (so a body pivot no longer eats a hook cue — `authored [0,1,2] + pivot on 2` kept `sh00, sh02` before, keeps `sh00, sh01, sh02` now); two pivots in one gap both kept; a lone pivot kept even at cap 0.1. Reasoning is written at `_apply_min_gap`.
- decided (finding 3): **scale the word delays to the window the renderer actually resolved** (`compositor/src/stampWordTiming.ts`, `wordDelaySchedule(words, endFrame - startFrame)`). Nominal 0/4/14/24 (+10/word) is kept whenever it fits and compressed proportionally when it does not, so at the pinned hold a 3-word phrase is still exactly **0 / 4 / 14** — the spike rhythm survives untouched — a 4-word becomes 0/3/11/19, and 5/6-word stamps (nominal 34 / 44, which never rendered) land inside. Rejected: clamping the authored word count (silently truncates copy the writer chose, and does nothing for a hold clamped short near the end of a shot), and extending `STAMP_HOLD_S` (spike-pinned, read by the render fingerprint and the overlay cache key in `renderer/compositor.py`, and lingering contradicts "exits are snaps"). `STAMP_HOLD_S` is unchanged, so no fingerprint or cache-key churn.
- did (finding 4): `SIM102` at `_gap_for_shot` gone — it now takes `in_hook: bool` (the caller needs the regime anyway, so membership is computed once per cue) and has one `if`.
- found: **the longest empty stretch did NOT improve — it got worse, and the cause is the rate cap, not the gap.** Probe (`tmp/probe_k14_review.py`, real `enforce_emphasis_rules` + real resolvers, HEAD's module loaded side by side for the BEFORE column), cue authored on every shot: BEFORE 5 cues at 0.00 / 2.82 / 8.84 / 15.16 / 21.09, 12.16/min, hook 2 at 24/min, body 3 at 9.15/min, longest hole 6.32s onset-to-onset (5.46s hold-aware). AFTER 5 cues at 0.00 / 2.82 / 5.54 / 10.65 / 17.09, 12.16/min, hook 2 at 24/min, body 3 at 9.15/min, longest hole **7.59s** onset-to-onset (**6.73s** hold-aware). The post-hook hole is what the finding said it was and it closes (6.02s → 2.72s onset-to-onset, 5.16s → 1.86s hold-aware), but the regime-scoped gap yields a FOURTH body candidate (sh11 at 22.92s), the body-only cap allows 12.0 × 19.68/60 = 3.94, and `_apply_rate_cap` drops in film order — so the cue it removes is the reel's LAST one and the reel now ends on 7.59s of nothing. With the cap disabled the fix's own shape is 6 cues, 14.59/min, tail 1.76s, longest hole 6.44s (5.58s hold-aware) — still no better than 6.32s / 5.46s, because the binding constraint on the longest hole is body gap 3 over 1.9-2.4s shots (sh05 → sh08 is 10.65 → 17.09 = 6.44s), and gap 3 plus the 12.0 ceiling are both outside these four findings. Not tuned: two candidate remedies for the user to pick from are (a) make `_apply_rate_cap` trim the cue that leaves the most even spacing instead of the last one in film order, and (b) reconcile the 12.0 body ceiling with gap 3, which on this shape produces 12.2/min and therefore always loses one cue to the cap. Both are K14.6-shaped and want a watched reel first.
- found: the two exposing cases are fixed — `authored [0,1,2] -> kept sh00, sh01, sh02` (was `sh00, sh01`) and `authored [0,2] -> kept sh00, sh02` (was `sh00`). No authored hook cue dies silently now, and authoring asks for 2 rather than 3 on this shape.
- files: `backend/app/timeline/emphasis_rules.py`, `backend/app/planners/emphasis/planner.py`, `backend/app/script/styles.py` (knob comment only — no knob value changed), `compositor/src/stampWordTiming.ts` (new), `compositor/src/Stamp.tsx`, plus tests.
- tests: `python -m pytest tests/unit -q` from `backend` → **1474 passed, 6 failed**, the same six pre-existing failures (5 `test_sfx_overlays_diegetic.py`, 1 `test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`). New: `test_first_body_cue_survives_a_hook_cue`, `test_hook_cue_is_not_evicted_by_a_pivot_in_the_body`, `test_body_stamp_still_yields_to_a_body_pivot_inside_the_gap`, `test_two_body_pivots_inside_the_gap_are_both_kept`, `test_lone_late_pivot_survives_hook_and_cap_across_the_boundary`, `test_hook_capacity_bounds_what_enforcement_can_keep_in_the_hook`, `test_hook_request_never_exceeds_hook_capacity`, `test_hook_request_keeps_the_floor_when_the_hook_holds_enough_shots`, and `tests/unit/renderer/test_stamp_word_timing.py` (4 tests, which EXECUTE the real TS module through node's type stripping rather than re-implementing the arithmetic, and skip if node is missing). Updated, with the teeth kept: `test_retention_fast_knobs_measure_hook_plus_body_on_a_full_reel` (now 9 kept — the first body shot is no longer pushed away, and the body-only cap allows exactly 6 body cues), `test_body_adjacent_stamps_after_the_hook_still_drop` → `..._after_the_first_body_cue_still_drop` (adjacency still drops, one shot further along), `test_hook_membership_is_by_start_time_not_index` (a third shot now carries the membership difference, since the second is kept either way). `python -m ruff check` clean on every touched file.
- next: nothing tunable left without a watched reel. Render a NEW `retention_fast` reel and report first-cue onset, hook rate, body rate and longest empty stretch. Then K14.6, and with it the two rate-cap questions above — the longest empty stretch is currently limited by body gap 3 and the film-order cap trim, not by the hook.

---

## K15 - A multi-word stamp has no band to live in  **(ADDED 2026-09-10, BLOCKING K14.5)**

Found by watching `nexon-reel4-test` (`8c8ed7ff`), the 40.12s reel that
proved K14's density work. The hook is fixed; **half the cues render
broken.**

### What the render showed

Four of the eight stamps are multi-word, and every one of them wrapped
mid-word:

| authored | drawn | |
|---|---|---|
| `लाखों लोग` | `लाखों लो` / `ग` | splits a syllable, not just a word |
| `Tata Nexon` | `Tata N` / `e` | |
| `बिकने वाली SUV` | a tall, mostly-empty slab | mixed script, worst case |
| `service centre` | wraps | |

The pivot and both counters render correctly. So the reel is arguably
LESS watchable than the 3-cue `nexon-reel3-test` before it: that one's
three cues were clean, this one's eight are half mangled.

### Root cause

`stamp_band(canvas_width, canvas_height)` in `renderer/compositor.py`
**takes no text.** The font is pinned at `_STAMP_REF_FONT = 190` scaled
by canvas width, sized for the one short word a stamp used to be. K14.5
then let the planner author a 2-4 word phrase and added word-level
onsets, and nothing resized the band or the font. The overflow is
wrapped by CSS, which breaks wherever it likes.

K11 hit the same class of bug on the counter and fixed it with
`_counter_content_width` - a content-derived width from per-face
glyph-advance estimates, with `_COUNTER_MIN_BAND_WIDTH = 420` surviving
as a floor. That is the precedent to follow. Nobody did it for the
stamp because pre-K14 a stamp was always one word.

**The stamp is harder than the counter in one way and easier in
another.** Harder: the content is arbitrary words in two scripts, not
digits and a separator, so glyph widths vary far more. Easier:
**the Devanagari face is vendored on disk** -
`backend/vendor/fonts/NotoSansDevanagari-Regular.ttf` and
`compositor/public/NotoSansDevanagari-Regular.ttf` - so for Devanagari
Python can read real `hmtx` advances instead of estimating, which is
strictly better than the position K11 was in. Only the Latin stack
(`Segoe UI Black` / `Arial Black` / Impact, resolved by Chromium, no
file vendored) still needs estimates, and K11 already measured those.

### The fix: fit the type to one line, and budget the phrase

**Shrink to fit, never wrap.** Measure the phrase's width at the
reference font size; if it exceeds the usable band width, scale the font
down until it fits on ONE line. No wrapping, so no mid-word break and no
split syllable, ever. The spike already did this by hand - its amber
`3rd` sat at 168px against a single word's 190px.

**Plus a character budget in the prompt**, so the type never shrinks far
enough to stop being a punch. K14.5 widened the stamp device to "a 2-4
word spoken phrase"; word count is the wrong unit, because `SUV` and
`ज़्यादा` are not the same width. Give the model a character budget and
say what happens past it.

**Rejected, with reasons.** *Multi-line with explicit word breaks*: the
band grows by line count and a 3-line stamp is a block of text rather
than one hit, which is the opposite of what this device is for.
*Truncating the phrase at authoring*: silently discards copy the model
chose, and the writer never learns the limit. *Leaving CSS to wrap*: the
bug.

### Two things that will bite whoever builds it

**The vendored Devanagari file is a VARIABLE font.** `compositor/src/font.ts`
declares `{ weight: "100 900" }` and the stamp draws bold, so the
advances that matter are the wght=700 instance - NOT the `hmtx` defaults
a naive `fontTools` read returns. Instance the font (or read `HVAR`)
before trusting a number, and say in the code which instance the
measurement came from.

**The band is what K4 measures.** `apply_emphasis_treatments` reads
plate luma inside the band to choose light/dark/slab, so a band that no
longer matches the drawn ink measures the wrong region. The plan already
records a deliberate ~8% residue between the nominal band height and the
drawn height (`PivotBand.as_props`, the 2d41298 decision); shrinking the
font widens that gap. Decide explicitly whether the band tracks the
fitted font size or stays the nominal strip, and record which - do not
let it drift silently.

### Verification - render and look at the frames

Unit tests cannot catch this. K14.5's tests exercised the word-timing
arithmetic through the real TypeScript module, which was the right
instinct, and they were all green while every phrase on screen was
broken. Timing is not layout.

Render all four cases the reel actually produced and look at them:

- 2-word Latin (`Tata Nexon`)
- 2-word Devanagari (`लाखों लोग`)
- 3-word mixed script (`बिकने वाली SUV`)
- 1-word control (`Parts`), which must be BYTE-IDENTICAL to today

Then measure, the way the K11 fix was measured: the drawn ink's
bounding box against the band's own box, and report both. "Looks right"
is not a result; `ink x A..B, band x C..D` is.

### If it cannot be made to work

Back out the phrase: return the stamp device in `prompts/emphasis/v1.md`
to one stressed spoken word and drop the word stagger. **The density win
is independent of K14.5** - the hook came from K14.1-14.4, and reel4's
first cue at 0.00s, 8 cues and 11.96/min all survive without multi-word
stamps. Losing the phrase costs the spike's `EVERY 3rd SUV` look and
nothing else measured.

---

## Work log — K15 the stamp fits its phrase (2026-09-10)

This section is an implementation diary, not a design change. Append only.

### 02:05 — reproduce first, on real frames

- read: the whole K15 section, `renderer/compositor.py` (`stamp_band`, `_STAMP_REF_*`, `_counter_content_width` + the glyph-advance block, `_COUNTER_MIN_BAND_WIDTH`, `PivotBand.as_props`), `compositor/src/Stamp.tsx`, `stampWordTiming.ts`, `font.ts`, `emphasis_contrast.apply_emphasis_treatments`.
- did: built `tmp/k15/verify_k15_stamp_fit.py` on the `tmp/k11_fix` pattern — hand-built `OverlayCue`s straight into `render_or_reuse_emphasis_overlay` at 720x1280/30fps through real Chromium, RGBA frames out, ink box measured against band box. No planner, no DB, no LLM. Ran it BEFORE touching anything, so the defect and the control are measured on the same harness as the fix.
- found: the wrap is not between words at all — it is between GRAPHEME CLUSTERS. Every cluster is its own `display:inline-block` span, and CSS may break a line between inline-blocks, so the ` ` that joins the words was never protection: `Tata Nexon` broke as `Tata N` / `exon`, `लाखों लोग` as two lines, `बिकने वाली SUV` as three (`S` orphaned from `UV`) running y 320..933 against a band of y 320..538. That is why the authored text and the drawn text disagreed inside a word.
- found: the drawn slab is CLIPPED to its own box (`clipPath: inset(0 X% 0 0)` at X=0 clips to the border box), so vertical overflow is a hard cut, not a loose one. This matters for Devanagari — see 02:35.
- next: fit the font in Python; make a wrap impossible in the TSX.

### 02:20 — the width model, and which instance it came from

- decided: **fit the type to one line and never wrap.** `stamp_band(w, h, *, text, text_register)` measures the phrase at the reference font and solves for the largest size that fits `band width - 4*pad` (the slab's own content box, 664px on the reference canvas): `F <= (usable - tracking*n) / em`, solved rather than iterated because `letterSpacing` is in pixels and does not scale with the font. `Stamp.tsx` gains `whiteSpace: "nowrap"`, so a wrap is impossible even when the measurement is wrong — the surviving failure is "the slab grows past the band", not "an orphaned syllable".
- decided: the estimate is biased the OPPOSITE way from `_counter_content_width`, and the reason is written where the numbers are. The counter erred wide because extra slab is margin; here the derived number is a font size, so overestimating the text costs a little size and underestimating puts the wrap back. Every advance is a ceiling: the measured value rounded UP onto a 0.05 em grid. Measured error against the real wght=700 sums: +3.4% `लाखों लोग`, +4.8% `बिकने वाली SUV`, +3.1% `ज़्यादा`.
- did: Devanagari advances are REAL metrics, taken from the vendored file at the **wght=700 / wdth=100 instance** (`fontTools.varLib.instancer.instantiateVariableFont`, unitsPerEm 1000) because `font.ts` declares `{ weight: "100 900" }` and `Stamp.tsx` draws `fontWeight: 700`. The `hmtx` defaults are the wght=400 master and are 8-10% NARROW (`लाखों लोग` 3.514 em at 400 vs 3.851 at 700, +9.6%; `बिकने वाली SUV` +8.2%) — i.e. exactly the error that reintroduces the wrap. fontTools is not in `requirements.txt`, so the numbers are baked as constants and a dev-only test (`pytest.importorskip`) re-measures the file and fails if any ceiling has fallen below the real advance.
- did: Latin is still estimated (no file vendored; Chromium resolves `Segoe UI Black` / `Arial Black` / Impact) but it is K11's own measurement extended per character, not a new basis — re-read off the same host faces and reproducing the recorded numbers to the digit (Segoe W 1.053 / % .898, Arial Black W 1.000 / % 1.000, Arial digits .667). Each entry is the MAX of the two Black faces so the line fits whichever the host resolves; Impact is narrower at every glyph and never binds. The `hi` register's Latin comes from the Noto file instead, because a `hi` stamp is set in the bundled face and its cmap covers Basic Latin — charging the heavy stack for the `SUV` in `बिकने वाली SUV` is a ~25% width error on the plan's worst case.
- found: **the first version of the table was wrong by 38% and only the render caught the shape of it.** The nukta (U+093C) is a canonical composition exclusion, so `ज़`/`ख़` stay decomposed as base + mark, which put a nukta inside a consonant bucket where it silently overwrote its own 0.00 — `ज़्यादा` measured 3.55 em against a real 2.57 and shrank a word that fits at 190. Fixed structurally, not by retyping: non-spacing marks (Unicode `Mn`) are charged 0 by rule, which is exactly true of this font (every zero-advance character in the block is `Mn`, every `Mc` has a real advance), and `_advance_lookup` now raises at import if two buckets claim one character with different widths.
- next: decide the band, then look at frames.

### 02:35 — the band tracks the fitted font (decided, not drifted)

- decided: **the band tracks the fitted font size**; `height = font_size + 2*pad` as always, only the input changed. Keeping the nominal 190-strip would leave a 218px measured box over ~120px of drawn type, so K4 would read bare plate the type does not cover — the inversion `Emphasis.tsx` warns about — and the gap would grow with every character the writer adds. Tracking the fitted size instead preserves the property `PivotBand.as_props` defends: the measured slice stays INSIDE the drawn band, short by the same ~8% pad-and-rule residue at any size. Accepted consequence: two cues on one plate can now resolve different treatments, which is correct — they cover different amounts of it.
- found: K4's thresholds need no change and got none. Every existing threshold test resolves its band from a single word or from no text, so it still measures (0, 320, 720, 538); `test_emphasis_contrast.py` and `test_compositor.py` pass unchanged, and `apply_emphasis_treatments` reads the band only through `box_on`, so the shorter strip follows automatically.
- found: a pre-existing defect this fix REDUCES but does not remove, reported rather than fixed. Devanagari ink overflows the `lineHeight: 1` line box upward by a consistent 0.15 em (matras above the shirorekha) and the slab's `clipPath` cuts it: measured on bare-type renders, `लेकिन` at 190 loses 15px of matra TODAY, `लाखों लोग` at 156 loses 9px, `बिकने वाली SUV` at 93 loses 0. So shrinking helps, and the residue at 156 is visible as flat-topped `ों` marks meeting the slab edge. The fix would be the stamp's `lineHeight` (Pivot.tsx already uses 1.1 for exactly this reason) or more `pad`, and both change the single-word look this slice is required to keep byte-identical. K16-shaped.
- next: render five cases and look at them.

### 02:50 — rendered, measured, looked at

- did: rendered nine stamps in one overlay through real Chromium and measured each (`tmp/k15/after/`, ink = opaque white, slab = opaque near-ink, whole canvas searched so a second line cannot hide). All ONE LINE, ink inside slab and inside band in every case:

| case | font | band x / y | ink x / y | slab x | lines |
|---|---|---|---|---|---|
| `Tata Nexon` en | 94 | 0..720 / 320..442 | 73..639 / 353..419 | 44..675 | 1 |
| `लाखों लोग` hi | 156 | 0..720 / 320..504 | 39..682 / 320..453 | 12..707 | 1 |
| `बिकने वाली SUV` hi | 93 | 0..720 / 320..441 | 45..674 / 320..404 | 17..702 | 1 |
| `EVERY 3rd SUV` en | 69 | 0..720 / 320..417 | 84..635 / 346..397 | 52..667 | 1 |
| `service centre` en | 73 | 0..720 / 320..421 | 87..630 / 347..401 | 56..663 | 1 |
| `सबसे ज़्यादा` hi | 130 | 0..720 / 320..478 | 56..665 / 320..446 | 28..691 | 1 |
| `CRETA` en | 165 | 0..720 / 320..513 | 87..631 / 368..486 | 54..665 | 1 |
| `Parts` en (control) | 190 | 0..720 / 320..538 | 120..603 / 374..508 | 80..639 | 1 |

  Before the fix, on the same harness: `Tata Nexon` ink y 374..698 in two runs of 135/99 rows, `लाखों लोग` two runs, `बिकने वाली SUV` three runs of 155/174/138 spanning y 320..856, `EVERY 3rd SUV` three runs — and `Parts` one run, unchanged.
- found: **the control is byte-identical, proven at the pixel level.** `Parts` renders to md5 `f12b10f0934439e96a9e95b461d034f6` both before and after, from two independent Chromium runs, at the 60-frame window and again at the real 26-frame `STAMP_HOLD_S` hold. `emphasis_cue_content_hash` and `overlay_input_hash` for a single-word stamp are equal across the change, so no existing project re-renders its overlay.
- found (looked at the PNGs): `Tata Nexon` at 94 reads as a deliberate brand lockup — complete, nothing clipped, 29/36px of slab margin. `बिकने वाली SUV` at 93 is the best of the set: one confident line across 88% of the width, matras intact, `SUV` set in Noto beside the Devanagari. `लाखों लोग` at 156 is strong but its `ों`/`ं` marks meet the slab's top edge (the 02:35 finding, 9px). `सबसे ज़्यादा` at 130 is clean with the nukta visible. `EVERY 3rd SUV` at 69 and `service centre` at 73 are perfectly legible — cap height ~50px against a 58px caption — but they read as a caption in a black bar, NOT as a punch: that is the boundary, and it is where the budget comes from.
- decided: **character budget = 10 Latin / 14 Devanagari, spaces included**, stated in `prompts/emphasis/v1.md` with what happens past it (the type shrinks, it never wraps, and it stops hitting). Derived from a floor of 90px (`_STAMP_MIN_PUNCH_FONT`, ~1.55x the 58px caption `captions.py` draws), which the rendered frames bracket: everything measured at or under 10 Latin characters fits at 92+ and every 13-14 character Latin phrase lands at 63-79. Devanagari earns the wider budget honestly — ~0.5 em per character and no tracking, against ~0.7 em plus 4px for the heavy Latin face. Two numbers rather than one because word count is not the only wrong unit; one number would either ban `बिकने वाली SUV` at 93px or wave through `HYUNDAI CRETA` at 63px. Nothing is clamped to the floor (clamping the font restores the wrap, truncating the text discards authored copy — both rejected in the section); a stamp under it logs `compositor.stamp_font_below_punch_floor`.
- did: replaced the two over-budget examples in the prompt's own stamp line so it no longer advertises what it forbids — `EVERY 3rd SUV` → `EVERY 3rd` (9 chars, 102px), `HYUNDAI CRETA` → `Tata Nexon` / `CRETA`. The preference order (proper noun / brand / model name first, evaluative adjective as fallback) is untouched.
- found: the spike's `EVERY 3rd SUV` was never one line. `SuvRetention.tsx` Beat 1 stacks it as three lines at 62 / 168 / 138 with the hero word biggest. As a single line at 720 wide it can only be ~70px, so K15's one-line rule and that look are different devices. The section rejected multi-line with reasons and I did not reopen it; recording it because "keep the spike look" and "one line" cannot both be had for a 3-word Latin phrase.
- found: `CRETA` at 190 fits Segoe UI Black (638px of 664) and overflows Arial Black (738px), and Python cannot know which Chromium will resolve. Taking the max sets it at 165 — 13% smaller than needed on this host, against a slab 74px wider than the canvas on an Arial Black one, where the canvas itself would cut the outer letters. Rendered both side by side in one overlay (the K11 old-band/new-band trick) to be sure the 190 version is a real, if host-dependent, fit. So: not every single word was unchanged, only every single word that fitted — `2025`, `Parts`, `Year`, `3rd`, `लेकिन`, `ज़्यादा`, `गाड़ी`, `दो लाख` all keep 190 and identical props.
- tests: `python -m pytest tests/unit -q` from `backend` → **1580 passed, 6 failed** — the same six pre-existing failures (5 `test_sfx_overlays_diegetic.py`, 1 `test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`), untouched. Baseline was 1474/6, so the 106 new tests are the whole delta and **no existing test needed changing** — the single-word path is byte-identical, which is what made that possible. New file `tests/unit/renderer/test_stamp_fit.py`: the control (props AND both hashes unchanged, per historical single word), the width model (estimate never below what Chromium drew, measured numbers baked in, and a 1.25x upper bound so a wildly pessimistic model fails too), the wght=700 re-measure guard, the mark rule, `hi`-register Latin, the fit invariant across three canvases and six phrase shapes including a 200-character one, the band-height decision, the collect wiring, and a cross-language pin that `Stamp.tsx` still says `whiteSpace: "nowrap"` and still insets the slab by `4*pad`. `python -m ruff check` clean on both touched Python files.
- files: `backend/app/renderer/compositor.py`, `compositor/src/Stamp.tsx`, `backend/app/prompts/emphasis/v1.md`, `backend/tests/unit/renderer/test_stamp_fit.py` (new), this section. Throwaway: `tmp/k15/verify_k15_stamp_fit.py`, `tmp/k15/probe_matra_clip.py`, frames under `tmp/k15/{before,after,matra}/`.
- next: watch a NEW `retention_fast` reel — `8c8ed7ff` is narration-locked and cannot be re-authored. Report per stamp what it drew and at what size. Two things to judge from it, both deliberately left alone: whether the 10-character Latin budget is too tight for the hook (it forbids the spike's own 3-word phrase), and the Devanagari matra clip at 02:35, which is pre-existing, now smaller, and needs a `lineHeight`/`pad` change that would move the single-word look.
- did NOT: touch the pivot look, K4's thresholds, K3's citation matcher, `EmphasisDevice`, the K14.1-14.4 density rules, `STAMP_HOLD_S`, or `stampWordTiming.ts`. No commit, no `git add`. No project, no LLM call, nothing deleted under `storage/`.

---

## K16 - The reference reel: captions carry the text, emphasis lives inside them, and the middle stays empty  **(ADDED 2026-09-10, REVERSES decision 1)**

The user supplied a reel they want `retention_fast` to look like
(`tmp/WhatsApp Video 2026-09-10 at 11.27.34.mp4`, 77.64s, 480x854,
25fps; frames extracted to `tmp/ref/`). It is a Hindi political-speech
edit with English inserts, and it is built on a different architecture
from the one this plan has been implementing.

### What it actually does

**Four text devices, and captions are the spine.**

1. **Continuous captions.** Small, white, BARE - no box, no bar - stacked
   in one to three short lines, low in the frame.
2. **Inline emphasis inside the caption.** The stressed word gets
   BIGGER, bolder and coloured, sitting in the reading order of the
   sentence. Observed:
   - `और जो` / **`Structural Reforms`** (cream) / `बीते वर्षों में किए हैं`
   - `भारत की` / **`Sovereign Ratings`** (mint) / `को`
   - `साफ-साफ` (large) / `देख रहा हूं` (small)
3. **A standalone big word near the TOP.** `Conflicts` in heavy red,
   bare, roughly 18-25% down, over the speaker's shoulder.
4. **A big translucent figure low in frame.** `7.8%`, ghosted white at
   partial opacity, ~70-78% down, arriving with a scanline glitch on the
   cut.

Also present, and explicitly OUT of scope here: one shot inset in a
rounded card on a light ground, and glitch/scanline cut treatments.

**There is no slab, no box and no bar anywhere in the reference.** All
type is bare, with an edge treatment for legibility.

### Placement, measured

| | where text sits |
|---|---|
| reference, captions | **~70-88% down** (the aerial frame measures 73-87% cleanly) |
| reference, the standalone word | **~18-25% down** |
| reference, the middle 30-70% | **empty** - that is the subject |
| **ours: stamp** | 25-39% down |
| **ours: counter** | 23-35% down |
| **ours: pivot** | 30-43% down |

So the reference keeps two zones and leaves the centre alone, and every
one of our three devices lands in the zone it deliberately protects.
That is why `लाखों लोग` sat across the showroom family's heads and
`Parts` covered the car in `nexon-reel4-test`: our type competes with
the picture instead of framing it.

**Measurement caveat, recorded rather than hidden.** Only the aerial
frame gave a clean automated read; the stage-lit frames defeated a
brightness-threshold row detector, so the others were read by eye. The
70-88% figure must be re-measured properly before it becomes a
constant.

### What this reverses

**1. Decision 1 - `retention_fast` ships with no burned captions - is
WRONG for this look, and is reversed.** That decision assumed dense
kinetic text replaces captions. In the reference the captions ARE the
text, continuously, and emphasis is a STYLE APPLIED TO A CAPTION WORD
rather than a separate object placed on the frame. The K14 work log
already recorded that captions-off made the hook emptier than before;
this is the reason why.

**2. The forced slab.** `emphasis_slab_default=True` on the
`retention_fast` band makes every cue draw a ground. The reference uses
none. This also settles the open slab question from 2026-09-10 (opaque
vs 0.70 vs palette-tinted): the answer is no slab at all for the caption
layer, and bare type for the standalone word.

**3. Device placement.** `_STAMP_REF_TOP = 320`, the counter's 300 and
the pivot's 380 are all mid-frame on a 1280 canvas.

### What already exists, which is more than expected

- `CaptionStyle` is documented as "white text, heavy black outline, no
  background box, raised clear of the bottom ~12-15% platform-UI band" -
  already the reference's look.
- **Feature A (`style_extensions.md` §3.3) already does per-word
  highlight COLOUR**: `CaptionWord`, `Scene.caption_word_groups`, and an
  ASS override per word in `renderer/captions.py`.
- The `stamp` device is already "one big word" - it just draws a slab and
  sits mid-frame.

### The parts

**K16.1 - captions back ON for `retention_fast`.** Reverse decision 1 in
the plan, and make sure the style resolves to captions-on. Whoever holds
the captions-off brief must be told it is cancelled, not deferred.
**CANCELLED 2026-09-10:** the captions-off brief (decision 1 / K14
blocking note / one-off `BURN_CAPTIONS=false` on the dedicated backend)
is cancelled. Captions stay on for this style; do not implement a
captions-off path.

**K16.2 - Feature A gains SIZE and WEIGHT, not just colour.** This is
the heart of the look: the stressed word is bigger. Today the highlight
is one hardcoded constant (`_HIGHLIGHT_OVERRIDE_ASS =
"{\c&H00FFFF&}"`). ASS supports per-span font size and weight
overrides, so this is an extension of an existing mechanism rather than
a new renderer.

**K16.3 - the highlight colour comes from the palette.** That constant
is applied to ALL styles today, with a comment saying it is "the one
constant to make style-keyed" if a style ever needs a different one.
That time is now: the reference varies it (cream, mint, red), and K5
already resolves a per-project `accent`. Feed the accent in.

**K16.4 - placement zones.** Captions in the bottom quarter, the
standalone word in the top fifth, the middle never. Resolved per style
like every other knob (RV2 / R1), not hardcoded per device.

**K16.5 - the standalone word goes BARE.** No slab. This is where K4
earns its keep rather than being short-circuited: bare type needs the
light/dark decision to be real, so `emphasis_slab_default` should come
off for this style and `choose_treatment`'s measurement should actually
be used. Note the risk already recorded on 2026-09-10: this reel's plate
lumas cluster 101-121 straddling `LIGHT_MAX_LUMA = 105`, so the
bare/slab choice would flicker shot to shot. Widening the bare range,
or leaning on a stronger edge treatment, is the thing to measure.

**K16.6 - the translucent figure (lower priority).** Close to our
`counter` but ghosted at partial opacity and placed low. Sequence after
16.1-16.5.

### What this does to the work already done

Not invalidated, but re-weighted, and this should be said plainly:

- **K14's density work still applies.** Cues still need to be early and
  frequent; the hook window and the regime-scoped gap are about WHEN, not
  WHAT, and the reference front-loads too.
- **K15's fit-to-one-line still applies** to the standalone word.
- **K12, K13 are unaffected.**
- **K3, K4, K5, K9, K11 become punctuation on top of a caption spine**
  rather than the only text layer. The cue devices stop carrying the reel
  on their own. That is a reduction in their importance, not a deletion:
  the pivot band was the best frame in `nexon-reel4-test` and the
  reference has no equivalent, so it stays as OUR device.

### Verification

Render a `retention_fast` reel and compare against the reference frames
at matched moments. Report the text-zone percentages measured the same
way as the table above, the caption line count and lengths, and which
word in each caption took the emphasis style. A green suite proves
nothing about a look.

---

## Work log — K16.1 + K16.4 captions on + placement zones (2026-09-10)

This section is an implementation diary, not a design change. Append only.

### — K16.1 captions-on + K16.4 placement (this slice)

- decided (K16.1): `StylePacingBand.burn_captions: bool | None = None` —
  None falls through to `settings.burn_captions`; `retention_fast` sets
  `True`. `resolve_burn_captions(style)` returns the band value when not
  None, else settings; unknown style → settings. `RenderStep` puts the
  resolved bool on `RenderSettings` (fingerprint already hashes it).
  Drafts still omit the field (`RenderSettings.burn_captions` defaults
  False). **Captions-off brief cancelled** — not deferred; no
  captions-off path was implemented. Decision 1's superseded reasoning
  is kept under the REVERSED marker.
- decided (K16.4 captions): `caption_margin_v_fraction=0.16` on
  `retention_fast`. Arithmetic: MarginV = round(1280 * 0.16) = **205px**;
  last-line bottom at 84% down; font 58px; 3-line block ≈ 174px ≈ 13.6%
  of height → three lines occupy ~70–84%, inside the reference ~70–88%
  band. Landscape still overrides to 4% in `serialize_ass` (§19.3).
  Outline / colour / Alignment / Feature A highlight untouched.
- decided (K16.4 stamp): `emphasis_stamp_top_fraction=0.18` →
  `top = round(0.18 * 1280) = **230**`. `stamp_band(..., top_fraction=)`
  keeps today's `_STAMP_REF_TOP` scale when None so
  `stamp_band(720, 1280)` stays top 320 (K15 control). Collect resolves
  once from `timeline.metadata.render_style` and passes through
  `_band_for_device`. Slab still extends ~17% below the top (font 190 +
  2*14 pad ≈ 218px → box reaches ~35%) until K16.5 drops the slab —
  expected in this slice.
- recorded: pivot (30–43%) and counter (23–35%) still occupy the middle
  until later K16 parts; "middle never" is not fully true yet. Counter
  low translucent placement is K16.6.
- did NOT: K16.2, K16.3, K16.5, K16.6; no pivot/counter retune; no
  `Stamp.tsx` edit; no captions-off feature; no project / OpenAI /
  watched reel.
- tests: targeted styles/captions/stamp_fit/compositor → **202 passed**.
  Full `tests/unit -q`: Postgres was down (Docker Desktop not running;
  `docker compose up -d postgres` failed on the engine pipe), so 67
  planner/asset setup fixtures errored with ConnectionRefused — those
  are not regressions. Non-DB slice (`--ignore=tests/unit/planners`
  plus the two asset LLM-repo fixtures) → **1336 passed, 5 failed**,
  the same five pre-existing `test_sfx_overlays_diegetic.py` failures.
  The sixth baseline failure
  (`test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`)
  lives under planners and was among the ConnectionRefused errors.
  +9 new pins in this slice; no new failure among runnable tests.
  With Postgres up the expected shape is ≥1581 passed / same 6 failed.
- ruff: `ruff check` on touched Python files — no new issues in
  `styles.py` / `render.py` / `compositor.py` (pre-existing I001/F401/
  B905 noise in the two test files only).
- files: `backend/app/script/styles.py`, `backend/app/workflow/steps/render.py`,
  `backend/app/renderer/compositor.py`, `backend/tests/unit/script/test_styles.py`,
  `backend/tests/unit/renderer/test_captions.py`,
  `backend/tests/unit/renderer/test_stamp_fit.py`, this plan (K16 status
  row + this entry). Decision 1 superseded reasoning kept.
- next: watched reel verification (orchestrator/user). Then K16.2–16.6.

### — review (Grok 4.6)

- K16.1 and K16.4 match the section. Captions-off brief cancelled in
  code (`retention_fast` forces `burn_captions=True` onto
  `RenderSettings`) and in the plan. Decision 1 superseded reasoning
  kept. Stamp.tsx not edited. Pivot/counter geometry not retuned.
- Reviewer re-ran targeted files **223 passed**. Full `tests/unit`:
  **1524 passed, 5 failed, 67 errors** (Postgres down). Same 5
  sfx-diegetic failures; director-planner is among the 67 errors.
  Arithmetic with DB up: 1524+66 = **1590 passed / 6 failed** (1581+9
  pins). No new failure.
- Look this slice actually changes: captions ON, stamp top 320→230
  (18%). Caption MarginV 0.16 is today's default, now a style knob —
  not a placement move. Stamp slab still reaches ~35% until K16.5.
  Middle is not empty yet.
- Observation, not a revert: the RenderSettings construction test
  rebuilds the dataclass; it would not catch `RenderStep` swapping
  back to `settings.burn_captions`. Weaker than the K14 call-site spy.
- No project created. User renders a NEW `retention_fast` reel and
  compares `tmp/ref/` frames: caption zone, stamp zone, middle empty?
  K16.2 is not in, so inline emphasis is still colour-only.

### — review (orchestrator, 2026-09-10)

- verified: **1590 passed, 6 failed** with Postgres UP — exactly the
  number the agent's own reviewer projected by arithmetic while the DB
  was down (1524 + 66). Same six pre-existing failures. `ruff check`
  clean on `styles.py` / `render.py` / `compositor.py`.
- verified: captions resolve to **~70–84% down** (3-line block at
  MarginV 0.16) against the reference's 70–88%. `burn_captions=True` on
  the band genuinely overrides a backend started with
  `BURN_CAPTIONS=false`. It is resolved onto `RenderSettings`, so the
  fingerprint hashes the same bool the burn path reads — the trap K5 hit
  with the palette, handled here. `top_fraction=None` keeps 320, so
  K15's byte-identical single-word control survives.
- credited: the agent said plainly that MarginV 0.16 was ALREADY the
  default, so K16.4's caption half is a knob and not a placement move.
  That is the honest reading and it is what the numbers show.

**FINDING 1 (real, fix before anything else) — the captions-on wiring is
not pinned.** The agent's own reviewer suspected this; measured, it is
true. Reverting the call site to `burn_captions=settings.burn_captions`
and running the caption / styles / workflow / fingerprint suites gives
**5 failed, 232 passed** — the same five pre-existing sfx failures, and
NOTHING new fails. So `RenderStep` can be put back on the env toggle
with the suite fully green, captions silently return to env control, and
a `retention_fast` reel rendered on a `BURN_CAPTIONS=false` backend
comes out with no captions at all — the exact regression K16.1 exists to
prevent. The K16.1 test rebuilds the `RenderSettings` dataclass rather
than watching the call site. Fix with the pattern K14 already
established: a call-site spy, as in
`test_the_resolved_band_knobs_arrive_in_the_right_parameters`.

**FINDING 2 (sequencing, not a defect) — do not render between here and
K16.5.** Only K16.1 and K16.4 landed. K16.2 is not in, so the highlight
is still colour-only and still the one global yellow — and K16.2 is the
part this section calls the heart of the look, because the stressed word
being BIGGER is what makes it read as emphasis rather than as a
highlighter pen. K16.5 is not in either, so the slab remains and the
stamp still spans **18%→35%**, crossing the 30–70% zone the reference
protects. That overrun is the slab's height and not the type's: with the
slab gone, a single word at font 190 occupies roughly 18–28% and sits
inside the zone. A render taken now therefore has captions at the bottom
AND black slabs across the middle — two competing text layers, arguably
worse to watch than either the old look or the target. Ship K16.2 and
K16.5 as a pair, then render.

**FINDING 3 (minor, consistency) — the new knob resolves in a different
layer from its siblings.** `resolve_emphasis_stamp_top_fraction` is
called inside `collect_emphasis_overlay_cues`
(`renderer/compositor.py`), while `resolve_emphasis_slab_default` and
`resolve_emphasis_palette` are called in `workflow/steps/render.py` and
passed down. Same class of style knob, two layers, plus a new
`compositor → styles` import that did not exist before. There is no
import cycle and the collector does resolve it exactly once, so it
works — but every other emphasis knob follows "resolve once in the
render caller", and this is the drift RV2 / R1 exists to catch.

- next: pin the wiring (finding 1), then K16.2 + K16.5 together, then a
  watched reel against `tmp/ref/`.

### — finding 1 + K16.2 + K16.5 + finding 3 (this slice, 2026-09-10)

- decided (finding 1): replaced the weak
  `test_retention_fast_final_render_settings_get_burn_captions_from_resolver`
  (rebuilds `RenderSettings`) with a DB-free call-site spy in
  `tests/unit/workflow/test_render_step.py` that stubs
  `timeline_service` / `repo`, forces `settings.burn_captions=False`,
  spies `app.workflow.steps.render.render_video`, and asserts the
  `render_settings.burn_captions` that `RenderStep.run` actually
  passes. Fallthrough pin: documentary_archival → False when env is
  off. Draft default-False kept as a small styles test.
- **teeth proof (required):** temporarily set
  `burn_captions=settings.burn_captions` in `RenderStep.run`, ran
  `pytest tests/unit/workflow/test_render_step.py::test_render_step_puts_resolved_burn_captions_on_render_video -q`
  → **FAILED** with `assert False is True` (captured burn_captions was
  False under env OFF). Restored
  `burn_captions=resolve_burn_captions(...)`; same test **PASSED**.
  Revert not left in the tree.
- decided (K16.2): `CaptionStyle.highlight_size_fraction` /
  `highlight_bold`; band knobs
  `caption_highlight_size_fraction=0.08` /
  `caption_highlight_bold=True` on retention_fast only; resolvers
  return None/False for other styles. Override built in captions.py
  from the style (never reads the band). Defaults emit exactly
  `{\c&H00FFFF&}` (byte-identical). retention_fast on 720×1280:
  **`{\fs102\b1\c&H00FFFF&}`** — tag order `\fs` then `\b1` then `\c`;
  `round(1280 * 0.08) = 102` (~1.76× base 58px). Colour still global
  yellow. Resolved once where CaptionStyle is built in `render_video`.
- decided (K16.5): `emphasis_slab_default=False` on retention_fast so
  `choose_treatment` uses measurement. Stamp.tsx already skips the
  slab for light/dark — not edited. Pivot still draws its band (OUR
  device). **Did NOT retune** `LIGHT_MAX_LUMA=105` /
  `DARK_MIN_LUMA=180`: plates clustering 101–121 may flicker
  light↔slab shot to shot; measure on a watched reel before widening.
  K4's measured-luma + policy-off counterfactual log still runs.
- decided (finding 3): `collect_emphasis_overlay_cues(...,
  stamp_top_fraction=None)` — None keeps top 320. `render_video`
  resolves once via `resolve_emphasis_stamp_top_fraction` and passes
  it in (beside slab_default / palette). Removed
  `compositor → styles` import. Call-site pin: spy collect from
  `render_video` with binding/narration stubs, abort after collect;
  retention_fast → 0.18, documentary_archival → None. Collect unit
  tests pass the fraction explicitly.
- did NOT: K16.3, K16.6; no pivot/counter retune; no Stamp.tsx edit;
  no K4 threshold change; no project / OpenAI / watched reel / render.
- tests: targeted workflow/styles/caption_highlight/captions/
  stamp_fit/emphasis_contrast/compositor → **248 passed**. Full
  `tests/unit -q` with Postgres up → **1598 passed, 6 failed** (same
  six pre-existing: 5 sfx-diegetic + 1 director_planner
  every_attempt). Baseline was 1590/6; +8 pins, no new failure.
  `ruff check` on touched production files clean (pre-existing B905
  in test_styles.py only).
- next: watched reel against `tmp/ref/` (captions zone, bare stamp
  zone, middle empty?, highlight size). Then K16.3 / K16.6.

### — review (Grok 4.6, finding 1 + K16.2 + K16.5)

- finding 1: spy is a real call site (`RenderStep.run` → `render_video`).
  Re-ran `test_render_step.py` green. Implementer's teeth proof
  (`assert False is True` under `settings.burn_captions`) is the
  failure that test is built to produce; revert is not in the tree.
- K16.2 + K16.5 shipped together. Override pin
  `{\fs102\b1\c&H00FFFF&}`; other styles colour-only. Slab policy off;
  thresholds un-retuned. Finding 3: compositor no longer imports
  styles; `stamp_top_fraction` passed from `render_video`; spy pins
  0.18 vs None.
- Reviewer `tests/unit -q`: **1598 passed, 6 failed** (same six).
  Targeted 248 passed.
- Observation, not a revert: highlight size/bold are not fingerprint
  inputs (`cue_list_hash` is cue text/timing, not the ASS override).
  A NEW project is fine. Retuning 0.08 later, or re-rendering an
  already-captioned retention_fast with nothing else changed, can
  cache-hit the colour-only burn. Same shape as the K5 palette trap;
  burn_captions itself IS hashed so K16.1 does not have this hole.
- No project, no render. User watches a NEW reel vs `tmp/ref/`.

### — review (orchestrator, finding 1 + K16.2 + K16.5)

- verified: **1598 passed, 6 failed** (same pre-existing six), `ruff
  check` clean on all five production files. Matches the implementer's
  and reviewer's numbers exactly.
- **finding 1 is genuinely fixed, proven by teeth.** Reverting the call
  site to `burn_captions=settings.burn_captions` now turns
  `test_render_step_puts_resolved_burn_captions_on_render_video` RED
  (1 failed, 3 passed). The same revert left the whole suite green
  before this slice. It is a real call-site pin, not a dataclass
  rebuild.
- **finding 3 is fixed.** `renderer/compositor.py` no longer imports
  `app.script.styles` at all (grep count 0); `stamp_top_fraction` is
  passed down from `render_video` beside `slab_default` and `palette`,
  so the knob resolves in one layer like its siblings.
- verified K16.2 / K16.5: the highlighted word resolves to **102px
  against a 58px base — 1.8x** — plus bold, and other styles stay
  colour-only (`documentary_archival` resolves `None`).
  `resolve_emphasis_slab_default("retention_fast")` is now `False`, so
  no slab is drawn.

**OPEN FINDING (Grok flagged it, orchestrator confirmed, NOT fixed) —
highlight size and weight are not fingerprint inputs.** Verified by
signature: `compute_render_fingerprint` takes `burn_captions`,
`caption_font_hash`, `cue_list_hash`, `emphasis_cue_hash` and nothing
else caption-shaped; `cue_list_content_hash` is a function of cue text
and timing only; and `render.py` passes the highlight size/bold into
`CaptionStyle`, which is hashed nowhere. So **retuning
`highlight_size_fraction` away from 0.08 and re-rendering the same
project returns the OLD burn** — identical fingerprint, cache hit, no
visible change, indistinguishable from "the code did not work".

The precedent is in that same module: `caption_font_hash` exists
BECAUSE the font changes pixels and is read from config (fingerprint.py
§52-62). Highlight size and weight are the same shape.
`burn_captions` IS hashed, so K16.1 has no such hole — only K16.2 does.
It matters immediately rather than later, because 0.08 was reasoned and
not watched, so retuning it is the very next operation and it is the one
the hole breaks.

**To check with eyes, not tests.** The stamp BAND still reads
18%..35%, so on paper it crosses the protected middle. With the slab off
only the type is drawn — roughly 18%..28% for a single word at font
190 — so the middle should be visually clear. Band and drawn ink are
different rectangles and no assertion can say which one a viewer sees.

- next: hash the highlight params, then a watched reel against
  `tmp/ref/`.

### — the fingerprint hole from the open finding (2026-09-10)

- decided: `caption_highlight_size_fraction: float | None` /
  `caption_highlight_bold: bool | None` become two more unconditional
  `compute_render_fingerprint` payload keys, following the exact
  `caption_font_hash`/`cue_list_hash` shape (R2 - always present, `None`
  only when `burn_captions` is `False`, i.e. moot). Named after the
  `StylePacingBand` fields they mirror
  (`caption_highlight_size_fraction`/`caption_highlight_bold`), not after
  `caption_font_hash`'s `_hash` suffix — there is no file to hash, these
  are the same plain config values `music_bed_gain_db` already is.
- did (RV2): resolved ONCE in `RenderStep.render_video`
  (`backend/app/workflow/steps/render.py`), right next to
  `caption_font_hash`'s own resolution and before the cache-hit check —
  `resolve_caption_highlight_size_fraction`/`resolve_caption_highlight_bold`
  gated on `render_settings.burn_captions`, same `if ... else None` shape
  as `caption_font_hash`. The `CaptionStyle` built later in the same
  function (the actual ASS `\fs`/`\b1` override) now reuses those two
  resolved locals instead of re-resolving from the style band — one
  value reaches both the fingerprint and the burn, so they cannot drift.
  `compute_render_fingerprint`'s docstring gained one paragraph next to
  the existing Captions paragraph explaining why (fingerprint.py
  §51-78ish); the payload gained the two keys right after
  `cue_list_hash`.
- did NOT: touch `captions.py` (`CaptionStyle`/`cue_list_content_hash`
  are unchanged — confirmed `cue_list_content_hash` really is text/timing
  only, so the premise held); touch any highlight VALUE, the caption
  look, `slab_default`, or a K4 threshold; add a project or render.
- found (premise check, as instructed): before this change,
  `compute_render_fingerprint` genuinely had no parameter shaped like
  these two — `burn_captions`/`caption_font_hash`/`cue_list_hash` and
  nothing else caption-shaped, exactly as the open finding said. Premise
  confirmed, not a duplicate of existing coverage.
- **probe (required, `tmp/k16_fingerprint_probe.py`, gitignored,
  throwaway — deleted after this entry lands):** loaded HEAD (`93928ac`)
  `fingerprint.py` under a private module name via `importlib` (git
  history, not a revert in the tree) to get a real BEFORE alongside the
  working tree's AFTER, same otherwise-identical payload both times.
  Output:
  - BEFORE (93928ac): old `compute_render_fingerprint` has no highlight
    parameters at all, so a 0.08-vs-0.14 (or bold on/off) retune is not
    even expressible — calling it twice with the identical remaining
    payload necessarily collides. `differ = False` (both hashes
    `8f3bf88b2d6bdc7476c6ffa50c83889e17bbb0741fbe6a7258e5b85f782ee081`).
  - AFTER, `burn_captions=True`, size 0.08 vs 0.14 (bold held constant):
    `differ = True`
    (`41ffd4495a0c3561b7e6f596f1ffb5a6e1327e8cba217c9f292c3f4d74066190`
    vs
    `abfff0bcc5361da0ee801b4752779dffd2f5822adb5ddb4c7b7e8ac3568250e0`).
  - AFTER, `burn_captions=True`, bold True vs False (size held constant):
    `differ = True`
    (`41ffd4495a0c3561b7e6f596f1ffb5a6e1327e8cba217c9f292c3f4d74066190`
    vs
    `78574da9203a847cd6ddf6d847fac32e742966c28d512d4d4339d5ed176a879a`).
  - AFTER, `burn_captions=False`: ran the SAME conditional resolution
    `render.py` uses for two styles whose highlight knobs genuinely
    differ (`retention_fast` → 0.08/True, `documentary_archival` →
    None/False); both resolve to `size=None bold=None` once captions are
    off, and the two fingerprints collide — `differ = False` (moot,
    correct; `burn_captions` itself is a separate always-hashed field,
    so this collision cannot be mistaken for a caption-off/caption-on
    collision).
- tests: added
  `test_caption_highlight_size_changes_the_fingerprint` and
  `test_caption_highlight_bold_changes_the_fingerprint` to
  `backend/tests/unit/renderer/test_fingerprint.py`, each a
  `..._changes_the_fingerprint` test per new input, same shape as
  `test_different_caption_font_changes_the_fingerprint`. Extended
  `test_emphasis_keys_are_in_the_fingerprint_payload` (the payload-shape
  test) with `'"caption_highlight_size_fraction"'` /
  `'"caption_highlight_bold"'` source-string assertions. Updated the
  three other `compute_render_fingerprint` call sites that build a full
  kwargs dict and would otherwise TypeError on the two new required
  kwargs: `backend/tests/unit/renderer/test_fingerprint_reveal.py`,
  `backend/tests/unit/renderer/test_fingerprint_parallax.py`,
  `backend/scripts/c8_probe.py` — all three get
  `caption_highlight_size_fraction=None` / `caption_highlight_bold=None`
  beside their existing `caption_font_hash=None` / `cue_list_hash=None`,
  same "off" baseline. `pytest tests/unit -q` → **1600 passed, 6 failed**
  — the same six pre-existing failures (5 `test_sfx_overlays_diegetic.py`
  + 1 `test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`),
  no new failure; +2 over the 1598 baseline is exactly the two new tests.
  `ruff check` clean on every touched file.
- **consequence, stated plainly (accepted, same as every prior R2
  addition — `test_emphasis_keys_are_in_the_fingerprint_payload`'s own
  docstring says so):** adding two unconditional keys to the payload
  changes every historical fingerprint. Every project re-renders once on
  its next render. No attempt was made to avoid this with a conditional
  key.
- files: `backend/app/renderer/fingerprint.py`,
  `backend/app/workflow/steps/render.py`,
  `backend/tests/unit/renderer/test_fingerprint.py`,
  `backend/tests/unit/renderer/test_fingerprint_reveal.py`,
  `backend/tests/unit/renderer/test_fingerprint_parallax.py`,
  `backend/scripts/c8_probe.py`, this plan (K16 status row + this log).
  Probe in `tmp/` (gitignored, throwaway):
  `tmp/k16_fingerprint_probe.py` + `tmp/_old_fingerprint_93928ac.py`.
- next: the still-open items on the K16 status row — K16.3 (palette
  highlight colour), K16.6 (translucent figure) — then the watched reel
  against `tmp/ref/` that every slice so far has been deferring.

---

## K16.7 / K16.8 - What the first captioned reel showed  **(ADDED 2026-09-10)**

`nexon-reel4-test` (`8c8ed7ff`) re-rendered on the SAME 18 plates, the
same 8 cues and the same audio, with K16.1/16.2/16.4/16.5 in. Saved as
`tmp/reel4/AFTER_k16.mp4`, with `BEFORE_k16.mp4` beside it.

**What landed and is visible.** Captions are on, and the highlight is
real: `Bharat mein har` / **`mahine`** / `laakhon log nai car kharidte
hain.` with `mahine` plainly larger and bold. The bare counter reads
far better than the bar it replaced - cyan `17,281+` counting toward
20,000 with `SOLD EVERY MONTH` beneath it, over the mechanic, no
ground.

### K16.7 - bare type needs the OUTLINE, not a looser threshold

`slab_default` is off and K4 is genuinely measuring. Treatments from
that render's own log:

| shot | device | plate luma | chosen |
|---|---|---|---|
| sc_01_sh_01 | stamp | 174.98 | slab |
| sc_01_sh_02 | stamp | 88.48 | **light (bare)** |
| sc_01_sh_03 | stamp | 157.49 | slab |
| sc_02_sh_03 | counter | 101.40 | **light (bare)** |
| sc_03_sh_01 | pivot | 121.36 | slab |
| sc_04_sh_02 | stamp | 139.62 | slab |
| sc_06_sh_01 | counter | 116.69 | slab |
| sc_07_sh_02 | stamp | 166.16 | slab |

**Six of eight are still slabbed**, because the plate lumas run 88 to
175 and the 105-180 middle band is exactly where neither white nor ink
is safe bare. So turning the policy off did not remove slabs - it made
them INCONSISTENT shot to shot, which is arguably worse to watch than
uniform, and it is the flicker risk this plan already recorded on
2026-09-10.

**The reference's mechanism is already in this codebase, on the other
text layer.** `CaptionStyle` is documented as "white text, heavy black
outline, no background box" - and those captions are legible over every
plate in this reel INCLUDING the luma-175 showroom, in the same frame
as a slabbed stamp. The emphasis devices instead use a drop SHADOW
(`light`) and a HALO (`dark`), and neither is strong enough for K4 to
permit bare type at 140-175.

So the requirement is not a wider bare range on its own. It is: **give
the emphasis devices the caption's outline treatment, and THEN widen
the range, with the outline as the reason the wider range is safe.**
Doing it in the other order is loosening a threshold and hoping.

Measure it the way K4 was measured: render the same cue over the
luma-175 plate with outline vs shadow, and report whether the type
survives. `LIGHT_MAX_LUMA` / `DARK_MIN_LUMA` are K4's and must not move
until the outline exists to justify it.

### K16.8 - a styling change does not trigger a re-render

Found while producing the reel above, and it is a pipeline bug rather
than a kinetic-text one, but it BLOCKS iterating on this plan.

`RenderStep.is_satisfied` returns satisfied when the project has a
`video_path`, the file exists, and no `ShotBinding` was updated after
it. **It never consults the render fingerprint.** So the first
re-render attempt after K16 reported `workflow.completed` in three
seconds and left a `final.mp4` from before any of K16 existed. The
reel only got made because the stale file was moved aside by hand.

Consequences worth stating plainly:

- Every careful fingerprint input - including the highlight size and
  weight just added - only decides whether the render PATH reuses
  cached bytes. It cannot cause the step to run.
- Both gates must open. Nothing today opens the first one on a code or
  style change.
- In the app this is the experience "I changed the style, re-rendered,
  nothing happened", with no error and no signal.

The obvious shape is for `is_satisfied` to compare the stored render's
fingerprint against the one the current inputs produce, which is what
the fingerprint is for. That is a bigger change than it sounds
(`compute_render_fingerprint` needs most of `render_video`'s resolved
inputs), so it wants its own slice rather than being bolted on here.

### Still open from K16 itself

- **K16.3 - DONE 2026-09-10** (same slice as K16.7): highlight colour
  comes from the resolved K5 accent (`CaptionStyle.highlight_colour`,
  fingerprinted as `caption_highlight_colour`). `#00D9FF` →
  `{\c&HFFD900&}`. Default / unset stays yellow byte-identical.
- **K16.6** - the translucent low figure. Unstarted, lowest priority.
- **K16.8 - DONE 2026-09-10** (awaiting review): `RenderStep.is_satisfied`
  compares stored vs current fingerprint via shared `resolve_render_inputs`.
- **The tuned numbers are reasoned, not watched.** `0.08` for the
  highlight size (1.8x the 58px base) and `0.18` for the stamp top were
  both derived rather than seen. Expect to change them after watching,
  which is exactly what the fingerprint fix above makes possible.

---

## Work log — K16.7 outline-then-widen + K16.3 palette highlight (2026-09-10)

This section is an implementation diary, not a design change. Append only.

### — K16.7 Step A (outline) then Step B (105→175) + K16.3 (this slice)

- decided (K16.7 order): outline FIRST on stamp/counter bare paths, THEN
  raise `LIGHT_MAX_LUMA` 105→**175.0**. The outline is
  `CaptionStyle.outline_fraction` 0.006 → `Math.max(1, round(max(w,h)*0.006))`
  = **8px** on 720×1280, via `-webkit-text-stroke` + `paintOrder: "stroke fill"`.
  Bare light AND bare dark both use white type (stamp) / accent digits +
  white kicker (counter) with black outline — no SHADOW/HALO, no
  `onDark ? INK`. Slab path unchanged (device ground, no outline).
  **Pivot.tsx not edited** (full-bleed band + white type stays).
  `DARK_MIN_LUMA` stays **180.0**. Unmeasured stays slab.
- decided (K16.3): `CaptionStyle.highlight_colour: str | None = None`
  (`#RRGGBB`). None → today's yellow `{\c&H00FFFF&}` byte-identical.
  Helper `highlight_colour_to_ass`: `#00D9FF` → `\c&HFFD900&`;
  invalid/missing → yellow. Tag order still `\fs` then `\b1` then `\c`.
  `render_video` resolves palette when overlays OR `burn_captions`,
  passes `resolved_palette.accent` into CaptionStyle when burning;
  `palette_hash` still None when no overlay cues. Fingerprint adds
  `caption_highlight_colour` unconditionally (`None` when captions off).
- did NOT: K16.8 (`is_satisfied` fingerprint); K16.6; no Pivot.tsx /
  SuvRetention / EmphasisOverlay edits; no project / OpenAI / full reel;
  no commit.
- tests: targeted emphasis_contrast/caption_highlight/fingerprint/
  stamp_fit/captions/styles/compositor → **323 passed**. Full
  `tests/unit -q` → **1605 passed, 6 failed** — same six baseline
  failures (5 `test_sfx_overlays_diegetic.py` + 1
  `test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`);
  +5 over the 1600 baseline (outline TSX pin, reel4 light pins,
  hex→ASS conversion, cyan override string, fingerprint colour miss).
  No new failure.
- files: `compositor/src/Stamp.tsx`, `compositor/src/Counter.tsx`,
  `backend/app/renderer/emphasis_contrast.py`,
  `backend/app/renderer/captions.py`,
  `backend/app/renderer/fingerprint.py`,
  `backend/app/workflow/steps/render.py`,
  `backend/app/script/styles.py`,
  `backend/app/schemas/timeline.py`,
  `backend/tests/unit/renderer/test_emphasis_contrast.py`,
  `backend/tests/unit/renderer/test_caption_highlight.py`,
  `backend/tests/unit/renderer/test_fingerprint.py`,
  `backend/tests/unit/renderer/test_fingerprint_reveal.py`,
  `backend/tests/unit/renderer/test_fingerprint_parallax.py`,
  `backend/tests/unit/renderer/test_stamp_fit.py`,
  `backend/scripts/c8_probe.py`, this plan (status rows + this entry).
- next: K16.8 (is_satisfied vs fingerprint), then watched reel; K16.6
  lowest priority.

### — review (Grok 4.6)

- Order is correct: outline on stamp/counter bare paths, then
  LIGHT_MAX_LUMA 105→175 with the luma-175 caption plate as the reason.
  DARK_MIN 180 untouched. Pivot.tsx diff empty. K16.8 not in.
- K16.3: `#00D9FF` → `{\fs102\b1\c&HFFD900&}`; fingerprint colour miss
  pinned. Yellow default byte-identical.
- Reviewer `tests/unit -q`: **1605 passed, 6 failed** (same six).
- Watch notes, not reverts: (1) CSS stroke is not libass outline — the
  luma-175 stamp still has to be *seen*; (2) 176–179 remains a 4-unit
  slab gap; (3) K16.8 still means an existing project's `final.mp4`
  will not rebuild unless moved aside. New project is the clean verify.
- No project created. No commit.

---

## Work log — K16.8 is_satisfied vs fingerprint (2026-09-10)

This section is an implementation diary, not a design change. Append only.
K16.7 + K16.3 dirty tree left in place; no revert, no commit.

### — K16.8 RenderStep.is_satisfied consults the fingerprint (this slice)

- decided: `is_satisfied` keeps the cheap gates (no project / no
  video_path / file missing / no timeline → False; ShotBinding newer
  than video mtime → False). Then compares stored completed-render
  fingerprint for `project.video_path` (`is_draft=False`) against the
  fingerprint current inputs produce. **Missing render row or empty
  fingerprint → unsatisfied** (forces a run so a row is written — the
  pre-K16 `final.mp4` 3-second skip). Mismatch → unsatisfied. Match →
  satisfied.
- decided: extract `resolve_render_inputs` in the same module; BOTH
  `is_satisfied` and `render_video` call it (RV2). `_final_render_settings`
  shared by `run` and `is_satisfied`. Repo method
  `get_latest_completed_for_output(project_id, *, output_path, is_draft=False)`
  so a draft row cannot satisfy a final.
- decided (placeholders): helper never writes work-dir files. Missing
  shot media is absent from `shot_images`; treatments fall through to
  unmeasured→slab for the fingerprint. `render_video` writes
  placeholders only on a real encode after a fingerprint miss. Finished
  projects have every shot filled so this path is idle for is_satisfied.
- did NOT: K16.6; Pivot.tsx; K16.7 threshold retune; no project /
  OpenAI / reel; no commit; no `git add`.
- tests: `tests/unit/workflow/test_render_step.py` — missing/stale
  fingerprint → False; match → True; binding mtime still wins; helper
  call wired; is_satisfied and render_video share the same function
  identity. Full `tests/unit -q` → **1611 passed, 6 failed** — same six
  baseline failures; +6 over the 1605 K16.7 baseline (the new K16.8
  pins). No new failure. No integration/e2e run; comments in
  `test_render_only_api.py` / `test_fixture_round_trip.py` /
  `test_thumbnails.py` do not assert RenderStep.is_satisfied True on a
  file-only fixture, so no test edits there.
- files: `backend/app/workflow/steps/render.py`,
  `backend/app/repositories/render_repository.py`,
  `backend/tests/unit/workflow/test_render_step.py`, this plan
  (status rows + this entry).
- next: review; then watched reel; K16.6 lowest priority.

### — review (Grok 4.6)

- K16.8 matches the section: `is_satisfied` compares stored vs current
  fingerprint via shared `resolve_render_inputs`; missing row → False
  (the 3-second skip). Binding mtime kept. Drafts cannot satisfy final.
  Helper writes no placeholders.
- Reviewer `tests/unit -q`: **1611 passed, 6 failed** (same six).
  Targeted render_step + fingerprint: 85 passed.
- Watch notes, not reverts: (1) fingerprint for *unfilled* shots no
  longer includes placeholder-plate luma — finished reels are
  unaffected; (2) `is_satisfied` now does the full resolve (ffmpeg
  version, plate treatments). That is the cost of this slice.
- No project created. No commit. An existing `final.mp4` with no
  matching render row should now re-run instead of reporting done.

