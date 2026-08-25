# Style Extensions — Word-Highlight Captions, Archival Montage, Glitch Transitions

**Status:** Design-only, nothing built. Written 2026-08-25, following a live
camera-vocabulary test on `retention_fast` (see §1.1) and a short-form/reels
trend scan. Three features are in scope; two adjacent ones are deliberately
parked — see §1.3 before touching anything.

---

## 0. Navigation — read this before writing any code

This plan leans on two existing documents for house rules, prior findings,
and hazards that already bit this project once each. **Do not re-derive
these from scratch; read the cited sections first.**

| # | Read | Section(s) | Why it matters to this plan |
|---|---|---|---|
| 1 | `docs/plans/motion_new_styles_and_long_form_videos.md` | §2 (whole) — "Track B, the style catalogue" | This is the only prior art for adding a style. §2.1 (three-level binding), §2.3 (style is human-chosen), §2.8 ("ship three presets, not eight") are load-bearing constraints on Feature B (§4 below). |
| 2 | same doc | §2.4, §2.6 | Tier 1/Tier 2 catalogue of what "cheap" additions look like in this codebase, incl. the exact reasoning for why only two extra `xfade` transitions were added (restraint, not capability). Relevant to Feature C (§5). |
| 3 | same doc | §7 "Cross-cutting cautions" if present, and every ⚠ marked R-numbered finding under §13–§16 | These are the repeated, hard-won lessons (see §2 of *this* doc for the condensed list) — mostly about the render fingerprint (R2) and determinism (I5). |
| 4 | `docs/plans/analysis.md` | Part A (whole) | The whoosh SFX diagnosis. Read this even though whoosh is out of scope (§1.3) — it's the most recent, most concrete example in this codebase of "we measured a style's audio/visual density problem, found the root cause, and gated a feature per-style" (`whoosh_enabled` on `StylePacingBand`). Feature A's caption-highlight-per-style decision should follow this exact shape. |
| 5 | same doc | "⚠ TEST-DB HAZARD" (near the end of the file, search for that literal string) | **Mandatory reading before running anything.** Restated in full in §6 of this doc, but the source explanation of *why* is there. |
| 6 | same doc | The "Implementation progress" table and P1–P6 log entries | Shows the exact reporting shape expected of an agent that implements part of a plan in this repo: dated entry, scope executed, changes with file:line, verification performed, effects/reviewer notes. **Whoever picks up this plan should log entries in this same file, in this same shape**, under a new `## Implementation log` section this document does not yet have (add it when the first task starts). |

**Do not start implementation by reading code first.** Read items 1–6 above,
then §1–§2 of this document, then the feature section you're building, then
the code.

---

## 1. Origin and scope

### 1.1 What prompted this

During a live session on 2026-08-25, `retention_fast`'s shot-planner prompt
fragment was loosened so `punch_in` was no longer the *only* camera move —
`pull_back` on `reveal`-intent shots and `pan` on `introduce`-intent shots
were permitted as "variety beats" (see
`app/prompts/shot_planner_styles/retention_fast.md`, and the base table fix
in `app/prompts/shot_planner/v1.md:23-28` that pointed `pan` at a real
`ShotIntent` value instead of a phantom "discovery" one). A real render was
produced and measured: 67% `punch_in`, 26% `pull_back`, 4% `split_frame`, 2%
`pan` across 46 shots, with `pull_back` landing on 12/12 `reveal`-intent
shots and nowhere else. The user liked the result and asked what else could
be done to keep improving the short-form ("reels") styles.

A web scan of 2026 short-form editing trends (Hormozi-style captions,
kinetic typography, story-stacking/chapter cards, glitch transitions,
parallax) was compared against what this codebase already has. Two items
were already covered (text cards with motion = Tier 2, built; parallax =
scoped and evaluated, not built). Two were new. One existing gap (caption
styling) turned out to be the single most-cited retention mechanism in the
research and was **not** built at all.

### 1.2 In scope for this plan

| # | Feature | One-line description | Effort estimate |
|---|---|---|---|
| A | Word-by-word highlighted captions | The spoken word changes color as it's spoken, instead of one flat static caption style for the whole video | ~1–2 days |
| B | `archival_montage` — a 4th `render_style` preset | Harder cutting, full-frame text cards leaned on more, music more upfront | ~2 days |
| C | Glitch transitions | A brief digital-corruption beat at a cut, instead of a hard cut or dissolve | ~3–5 days, **spike first** — see §5 |

### 1.3 Explicitly OUT of scope — do not touch under this plan

| Feature | Status | Where it's tracked | Why it's parked |
|---|---|---|---|
| Re-enabling WHOOSH SFX on `retention_fast` | Deliberately disabled 2026-08-24 (`whoosh_enabled=False` on that style's `StylePacingBand`, `app/script/styles.py:156`) | `docs/plans/analysis.md`, decisions 3/5/5a/5b, and the P2 log entry | Re-enabling without first shipping C3a (rotation across up to 3 clips) + C3b (first-punch-only + min-gap restraint) — both explicitly deferred in that doc — reproduces the exact ~100-events-per-reel repetition bug that got it turned off. User has explicitly said "leave it" as of this session. If a future task *does* pick this up, it is C3a/C3b from `analysis.md`, not a task in this document. |
| 2.5D parallax (DepthFlow) | Evaluated live against real archival photos, verdict "build it," **not implemented** | `docs/plans/motion_new_styles_and_long_form_videos.md`, §10/Q10 ("ANSWERED 2026-08-20... Verdict: BUILD IT") | User has explicitly said "leave parallax too for now" as of this session. The 6-step build plan already exists in that doc's Q10 section if picked up later — do not re-scope it here. |

If an agent working from this document finds itself touching
`whoosh_enabled`, `SelectSfxStep`, `local_sfx.py`, `DepthFlow`, or any
`ParallaxProvider`-shaped code, it has wandered out of this plan's scope —
stop and check whether the user actually asked for that separately.

---

## 2. Lessons carried forward — non-negotiable invariants

Everything in this section has already caused a real bug once in this
codebase. Cited so a future agent doesn't have to rediscover them by
breaking something.

### 2.1 The render fingerprint rule (R2 — hit six times and counting)

**Any value that changes render output bytes but is read live at render
time must enter `compute_render_fingerprint`
(`app/renderer/fingerprint.py:155`), or a cache HIT silently serves stale
output.** This has been the single most repeated defect class in this
codebase's history (`docs/plans/motion_new_styles_and_long_form_videos.md`
and `analysis.md` both cite it multiple times — search either file for
"R2" or "§7"). The exceptions that do NOT need a new fingerprint parameter:

- A **fixed code-level lookup** keyed by something *already* in the
  fingerprint payload. Example: `STYLE_GRADES` in
  `app/renderer/grading.py:57-61` — the grade for a style can only change if
  the code changes (which invalidates fixtures anyway) or `render_style`
  changes, and `render_style` is already part of the timeline document dump
  that feeds the fingerprint. See that file's own docstring
  (`grading.py:12-28`) for the full argument — copy this reasoning
  explicitly in Feature B's grade addition, don't just assert it.
- A value carried transitively through something already hashed (e.g. an
  asset's own content hash already reflects anything baked into the asset
  file itself).

Concretely for this plan:

- **Feature A** (captions): DECIDED (§3.6) to be a single fixed global
  constant — not per-style, not `Settings`-tunable. This needs **zero**
  fingerprint work, an even simpler case than `STYLE_GRADES` (which at
  least varies by `render_style`; this doesn't vary by anything). If a
  later revision makes the highlight color configurable via `Settings` or
  per-project, that value MUST be threaded into
  `compute_render_fingerprint` explicitly at that point, exactly like
  `sfx_whoosh_enabled` was added in `analysis.md`'s P2 entry — new
  parameter, new payload key, tests in `test_fingerprint.py` proving the
  hash changes when the value flips.
- **Feature B** (archival montage): follows the `STYLE_GRADES` precedent
  automatically — no new fingerprint work needed if built the same shape as
  the existing 3 styles.
- **Feature C** (glitch transitions): if implemented as a real `xfade` type
  name added to `TransitionType`, it needs **zero** fingerprint changes —
  `Transition.type` is a per-shot Timeline field, and the timeline document
  is already fully hashed in (confirmed pattern: transition types
  `WIPE_LEFT`/`DIP_TO_BLACK` needed no fingerprint changes when added, see
  `motion_new_styles_and_long_form_videos.md` §2.6's implementation).
  **If implemented as a custom filter fragment with its own tunable
  parameters** (intensity, duration, RNG seed for a noise pattern), those
  parameters DO need fingerprint entries, and any RNG must be seeded
  deterministically (see §2.2, I5) — never `random.random()` unseeded.

### 2.2 Determinism (I5)

No unordered set/dict iteration where order affects output bytes, no
`datetime.now()`/unseeded randomness in anything that produces render
output. Sorted event lists, seeded picks (see `analysis.md`'s C2.2, the
`pick_seeded_top` function, for the canonical "seed from project_id, hash,
pick" pattern if Feature C ever needs a "randomized but deterministic"
glitch look per project).

### 2.3 "Resolve once, thread explicitly" (the RV2 lesson)

`analysis.md`'s own review (§ "RV2 — the 'cannot drift' justification is
false") found that `sfx_whoosh_enabled` was being resolved **twice**,
independently, in two different places that were supposed to agree by
construction — a comment claimed "resolved once" when the code didn't
actually do that. The fix: **the value must be computed once, at one call
site, and passed explicitly as a parameter into every function that needs
it** (the fingerprint call AND the render logic) — never re-derived
internally by a second function that trusts the first one stayed in sync.

Feature A itself no longer needs this pattern — §3.6 decided the highlight
is a fixed global constant, not something resolved from `render_style`, so
there is nothing to keep in sync. **This lesson remains directly relevant
to Feature C** if Option 2 (a custom filter fragment, §5.2) ends up with
any per-render-derived parameter (an intensity, a duration, a seed): resolve
it once in `render.py` beside where `music_gains`/`sfx_whoosh_enabled` are
already resolved, and pass it explicitly into both
`compute_render_fingerprint` and whatever function builds the filter
fragment — never let two call sites each independently re-derive the same
value from the timeline and trust that they'll always agree.

### 2.4 The style-catalogue caution (§2.8)

> "Every style × planner pair is a behaviour that can regress, and there are
> four planners. Three styles is 12 behaviours to keep working; eight is
> 32."

Feature B adds a 4th style = 4 more planner-pairs, permanently, not a
one-time cost. **Feature B's test plan (§4.7) must include a pass against
all four planners** (Director, Scene Planner, Shot Planner, Asset Planner)
with the new style selected, not just a visual/render check.

### 2.5 Prompt files are `@lru_cache`'d — a restart is required to see changes

`app/prompts/loader.py:13-39` — `load_prompt` and `load_style_fragment` are
both `@lru_cache`. Editing a `.md` prompt file on disk has **no effect** on
a running process that has already loaded that file once. This is not a
uvicorn `--reload` question (a `.md` file is not Python) — it's this
specific in-process memoization. Anyone testing Feature B's new
`archival_montage.md` prompt fragment must restart the backend process
after editing it, every time, or they will silently keep exercising the old
(often nonexistent, on first creation) version.

### 2.6 Camera/intent vocabulary must reference values that actually exist

This session found and fixed a real, pre-existing bug: the base Shot
Planner prompt's camera table (`app/prompts/shot_planner/v1.md`) mapped
camera moves against labels ("discovery", "tension") that are **not**
actual `ShotIntent` enum values (`app/schemas/timeline.py:51-58` — the real
7 are `introduce, explain, compare, reveal, contrast, emphasize,
transition`). Any new prompt fragment (Feature B's `archival_montage.md`)
must reference only real enum values when it talks about "on a
`reveal`-intent shot, do X" — grep the actual enum before writing the
fragment, don't copy old table entries on faith.

### 2.7 When to fail loudly vs. correct silently

Two precedents now exist in this codebase, deliberately opposite:

- **Fail loudly**: the original `AssetPlanner.plan()` video-shot cap raised
  `PermanentError` the instant the cross-scene count exceeded the project
  cap, specifically because "the model was never asked to reduce its own
  count" (`motion_new_styles_and_long_form_videos.md` §12, "A4's
  calibration half").
- **Correct silently (and log a warning)**: this session changed that exact
  behavior — the asset planner now downgrades excess video shots to image
  in scene/shot order instead of failing the whole run
  (`app/planners/asset/planner.py:198-231`), on the reasoning that a
  full-run failure over a per-scene blind-spot problem was worse than a
  bounded, deterministic, logged correction.

Neither is universally "correct" — pick per-feature, and **state the
reasoning explicitly in the code comment**, the way both of the above do.
For Feature C in particular: if a glitch effect's parameters ever produce
something that would break `xfade`'s own duration/overlap arithmetic
(D5, referenced throughout `motion_new_styles_and_long_form_videos.md`),
decide and document which precedent applies.

---

## 3. Feature A — Word-by-word highlighted captions

### 3.1 Goal

Replace the current single flat caption style (white text, black outline,
same for every cue in the whole video) with a per-word highlight: the
currently-spoken word changes color while the rest of the active caption
line stays the base color. This is the single most-cited retention
mechanism in the 2026 short-form research behind this plan (more so than
camera movement) and is completely unbuilt today.

### 3.2 Current state — exact code

- `app/renderer/captions.py:347-388` (`serialize_ass`) emits exactly **one**
  ASS `[V4+ Styles]` entry named `Caption`, used unconditionally for every
  `Dialogue` line:
  ```
  Style: Caption,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&HFF000000,...
  ```
  Both `PrimaryColour` and `SecondaryColour` are set to the same white
  (`&H00FFFFFF`) — there is no color differentiation infrastructure at all,
  and no karaoke (`\k`) timing tags anywhere in the file.
- Cues (`CaptionCue`, used by `serialize_ass`) are built at phrase/line
  granularity, not per-word — check `app/renderer/captions.py`'s cue
  construction (the code above line 340, not reproduced here — read it
  before starting) for exactly how a cue's `start_s`/`end_s`/`text` are
  currently derived from ElevenLabs' character-level alignment.
- The alignment data itself (character-level timestamps from ElevenLabs)
  already exists and is already used for cue splitting — this is the
  critical enabler that makes Feature A cheap. **Find the exact function
  that currently consumes the alignment and produces cue boundaries before
  writing anything new** — the per-word split should reuse that same
  alignment data, not fetch or derive it a second way.

### 3.3 Design — two implementation options

**Option 1 — real ASS karaoke tags (`\k`).** One `Dialogue` line per
phrase/cue (as today), with inline `{\k<centiseconds>}` tags before each
word and `\1c`/`\2c` (primary/secondary color) override tags timed to each
word's alignment window. This is the "correct" ASS-native way to do
word-highlight and is what most caption-burn tools use, but the tag syntax
is fiddly and libass's exact karaoke color-swap behavior should be
confirmed against **this specific ffmpeg build's libass** (per this
codebase's own stated principle in `TransitionType`'s docstring at
`timeline.py:101-104`: verify against the real ffmpeg build, don't assume
from memory or documentation).

**Option 2 — one `Dialogue` line per word.** Split each existing cue into
N sub-cues, one per word, each with its own `start_s`/`end_s` from the
alignment data and its own inline color override
(`{\c&H00FFFF&}word{\c&H00FFFFFF&}` or similar) wrapping just that word
while the rest of the phrase's words render in the base color via
overlapping, differently-timed Dialogue lines (ASS supports overlapping
events; the base-color full phrase can be one continuous-duration line
underneath, with a second, per-word, colored line overlaid — or the whole
phrase can be re-emitted per word with only that word's color changed,
i.e. N lines instead of N `\k` tags in 1 line).

**Recommendation: prototype Option 2 first.** It's mechanically simpler
(no karaoke-tag timing arithmetic, just N cues instead of 1, reusing
`serialize_ass`'s existing per-cue loop almost unchanged), easier to unit
test (each sub-cue's text/timing is independently assertable), and easier
to debug visually (open the `.ass` file, each word's own Dialogue line is
plainly readable). Fall back to Option 1 only if Option 2 produces visible
flicker/overlap artifacts in a real ffmpeg burn test.

### 3.4 Files touched

- `app/renderer/captions.py` — the cue-splitting function (find it; likely
  near where `CaptionCue`s are first constructed from alignment data) needs
  a per-word variant, or the existing one needs a mode/parameter.
  `serialize_ass` needs either a second `[V4+ Styles]` entry (highlight
  color) or per-line inline override tags.
- Possibly a new small pure module, e.g. `app/renderer/caption_highlight.py`
  or a function added to `captions.py` directly — **prefer adding to
  `captions.py`** unless the word-splitting logic is substantial enough to
  warrant its own file; don't create a new file for a 20-line function.
- `app/renderer/fingerprint.py` — **no change needed.** Per the decision in
  §3.6, the highlight is a single fixed global constant, not a
  `Settings`-tunable value or even a per-style lookup — there is nothing
  here for the fingerprint to need, by the same "fixed code-level constant"
  exception §2.1 describes for `STYLE_GRADES` (which at least varies by
  style; this doesn't even do that).
- `app/script/styles.py` — **no change needed** (decided in §3.6: this is
  not style-gated).

### 3.5 What NOT to change

- Do not touch `subtitles_filter_fragment` (`captions.py:391+`)'s
  composition with the grade/watermark filter chain — Feature A is purely
  about what goes *into* the `.ass` file, not how it's burned in.
- Do not touch the ElevenLabs alignment fetching/parsing itself — reuse
  whatever already exists.

### 3.6 Style gating and color — DECIDED 2026-08-25

**Word-highlight captions apply to all three styles** —
`documentary_archival`, `retention_fast`, and `stillness` alike. No
per-style gate, no `StylePacingBand` field, no `resolve_*_enabled`
resolver function. This was an explicit choice, made by the user
overriding this plan's own initial recommendation (which had argued for
gating it to `retention_fast` only, on the theory that the aggressive
color-pop look would undercut `documentary_archival`'s "restrained
documentary feel," `app/prompts/shot_planner/v1.md:29-30`) — the counter-
argument that won: word-highlight is a readability improvement independent
of pacing style, and a single code path is simpler than two. **If a future
visual check finds it genuinely looks wrong on `documentary_archival` or
`stillness`, that is new evidence and grounds to revisit this decision —
it is not grounds to silently re-gate it without saying so.**

**Highlight color: yellow**, on a white base (the Hormozi-style
convention this plan's research was built on) — e.g. base
`&H00FFFFFF` (white), highlight something like `&H0000FFFF` (ASS
`&HAABBGGRR` order — this is BGR, not RGB; double-check the exact hex
before hardcoding it, don't trust this document's arithmetic over a real
rendered test) for the active word. Implement as a single named constant
(e.g. `_HIGHLIGHT_COLOR_ASS = "&H0000FFFF"` beside the existing style
definition in `captions.py`), not a per-style dict — there is exactly one
value, a dict of one entry is a needless layer.

### 3.7 Test plan — pure unit tests only, no DB

All of this is testable as pure functions with zero database or ffmpeg
dependency for the ASS-generation logic itself:

- `serialize_ass` / the new per-word cue splitter: given a fixed list of
  `(word, start_s, end_s)` tuples (fabricated, not fetched from a real
  ElevenLabs call), assert the exact `.ass` text output — string equality
  or targeted regex/substring assertions on the `Dialogue:` lines and the
  `[V4+ Styles]` block. This is exactly the shape of testing
  `test_grading.py` already uses for `grade_filter_fragment` (per
  `analysis.md`/the motion doc's own citations of that test file) — **copy
  that file's structure**, don't invent a new testing shape.
- Edge cases to explicitly cover: a single-word cue, a cue with punctuation
  attached to a word (comma/period — must not break the color-override
  tag), a cue where two words share the exact same timestamp (zero-duration
  word — should not produce a zero-duration Dialogue line that some
  renderers choke on), non-ASCII text (Hindi/Hinglish — this codebase's
  real projects are frequently Hinglish, see `hinglish_final_project`
  fixture referenced throughout the motion doc) to confirm the
  `_escape_ass_text` escaping (`captions.py:339-344`) still holds under the
  new per-word splitting.
- **One integration-level test IS warranted and IS allowed**: an actual
  ffmpeg burn-in of a short synthetic `.ass` file against a test image,
  asserting the process exits 0 and produces a non-empty output file. This
  matches the existing pattern in `test_grading.py` ("the real
  fragment-composition point... real ffmpeg encodes" per `analysis.md`'s
  P3 verification log, "58 passed (incl. real ffmpeg encodes)"). This test
  needs **no database at all** — ffmpeg and a fixture image are the only
  dependencies. Confirm this before writing it: if it needs
  `async_session_factory` or any DB-backed fixture, it does not belong in
  this plan's test suite (see §6).
- Do **not** write a test that creates a real Project/Timeline through the
  API and renders it end-to-end to verify captions — that is an e2e test
  against the live shared Postgres, explicitly excluded by this plan's
  scope (§6).

### 3.8 Effort

~1–2 days: cue-splitting logic + ASS emission (~half a day), unit tests
(~half a day), one real ffmpeg burn-in verification (~a few hours). No
style-gating work — §3.6 decided against it, which is strictly less work
than this estimate originally assumed.

### 3.9 Open questions for the implementer

Style gating and highlight color are DECIDED (§3.6) — not open. What's
genuinely still open:

1. **Option 1 (`\k` karaoke tags) vs. Option 2 (one Dialogue line per
   word)** — §3.3 recommends prototyping Option 2 first for its mechanical
   simplicity, but this is a recommendation to try first, not a locked
   decision; if Option 2 produces visible flicker/overlap in a real ffmpeg
   burn test, fall back to Option 1 as designed.
2. The exact BGR hex value for the yellow highlight (§3.6 gives a
   starting guess, explicitly flagged as unverified) — confirm visually
   against a real ffmpeg burn-in before treating any specific hex string
   as final.

---

## 4. Feature B — `archival_montage`, a 4th `render_style` preset

### 4.1 Goal

A style described in the original plan (§2.4 of the motion doc) but never
shipped: harder cutting than `documentary_archival`, full-frame text cards
used more aggressively than today's occasional inter-shot cards, and music
sitting more upfront in the mix than the current "measured" archival bed.

### 4.2 Why this is well-understood, mechanically

Three styles already exist and follow one exact template. Adding a 4th is
almost entirely "fill in the same template again," not new architecture.
This is unlike Features A and C, which involve genuinely new render logic.

### 4.3 Files touched, with exact line anchors from the existing 3-style registry

- **`app/script/styles.py`** — add a new `StylePacingBand` entry to
  `STYLE_PACING_BANDS` (currently `documentary_archival` at line 126,
  `retention_fast` at line 134, `stillness` at line 160). Field values
  DECIDED 2026-08-25 (pace: "close to retention_fast," ~2-2.5s per the
  user's explicit choice; format: 9:16 per §4.6) — treat every number below
  as a **starting point for a real listening/viewing pass, not a measured
  constant**, exactly the epistemic status this codebase already gives
  `_DEAD_STOP_CEILING_MULTIPLIER` (`styles.py:25`) and
  `_SEED_RELEVANCE_EPSILON` (`analysis.md` P4 log) — state that explicitly
  in the code comment when this ships, don't present these as settled:
  ```python
  "archival_montage": StylePacingBand(
      name="archival_montage",
      # 90s / 2.25s ≈ 40 shots; budgeted to ~46 for headroom, same
      # ~1.14x ratio retention_fast used (58/51). Starting point, not
      # measured — recalibrate after a real listening/viewing pass.
      target_shot_duration_s=2.25,
      max_shots_override=46,
      min_shot_duration_s_override=1.2,
      max_shot_duration_s_override=4.5,  # target * 2.0, matches the
                                          # dead-stop ceiling (R7 shape)
      narration_speed=1.15,  # smaller bump than retention_fast's 1.4x —
                              # this style's cut pace is close to but not
                              # as extreme; within the "~1.15-1.25x
                              # practical ceiling" the parent plan cites
      music_bed_gain_db=-11.0,   # between archival's -14 (default,
      music_duck_gain_db=-15.0,  # config.py:192-193) and retention_fast's
                                  # -10/-14 — "more upfront than archival,"
                                  # leaning toward retention_fast's mix
                                  # since the pace decision also leans
                                  # that way
      # whoosh_enabled: omitted -> defaults True (§1.3, this plan does
      # not touch whoosh policy; archival_montage is not the dense-cut
      # style whoosh was disabled for).
      render_width=720,   # 9:16, decided 2026-08-25 — this whole plan
      render_height=1280, # originated from a "styles for reels" ask
  ),
  ```
  **All six numeric fields above must be revisited after a real render is
  watched/listened to** — they are reasoned starting points (interpolated
  from the two neighboring styles' shipped values), not measurements.
- **`app/renderer/grading.py`** — add an entry to `STYLE_GRADES`
  (`grading.py:57-61`, currently 3 entries) with contrast/saturation/
  brightness for the archival-montage look. Follow the module's own stated
  reasoning (`grading.py:12-28`) for why this needs **no** fingerprint
  change as long as it stays a fixed code-level lookup.
- **New file**: `app/prompts/shot_planner_styles/archival_montage.md` —
  follow `retention_fast.md`'s exact structure (a markdown override
  section, referencing only real `ShotIntent`/`CameraMovement`/
  `TransitionType` enum values — see §2.6's warning). "Harder cutting" at
  the Shot Planner level likely means: smaller `max_shot_duration_s`
  guidance, a stated preference toward `cut`/`dissolve` over long holds,
  and explicit instruction to use `text_card` shots (if that's a distinct
  shot mechanism — confirm by reading how `retention_fast.md` and the base
  `shot_planner/v1.md` currently handle text cards before writing new
  guidance) more frequently than the base prompt's default cadence.
- **Possibly `app/prompts/{director,scene_planner,asset_planner}_styles/`**
  if those planners have style-specific override directories analogous to
  `shot_planner_styles/` — check whether they exist; if
  `retention_fast`/`documentary_archival`/`stillness` have fragments for
  those planners too, `archival_montage` needs the same coverage per §2.4's
  "four planners" caution. If those planners currently have **no**
  per-style fragments at all (i.e. only the Shot Planner is styled today),
  say so explicitly in the implementation log rather than silently
  skipping them — a future reviewer needs to know it was checked, not
  assumed.
- **`app/api/projects.py`** — no code change needed for the style to become
  selectable; `body.render_style not in STYLE_PACING_BANDS` (referenced
  around the `create_project` handler) already validates against the
  registry dynamically. Confirm this by reading that check before assuming
  it "just works," though — don't take this document's word for it.

### 4.4 Text cards — reuse, don't rebuild

"Full-frame text cards leaned on more" should reuse the existing Tier 2
text-cards-with-motion feature (`app/renderer/text_cards.py`, built per the
motion doc's 2026-08-18 log entry) — this is a *frequency* change in the
Shot Planner's prompt guidance, not new render-side work. Confirm this
assumption by reading `text_cards.py` and how a shot currently signals "I
am a text card" (a `Shot` field? a special `asset_plan`? read
`text_cards.py`'s consumer in `render.py` to find out) before writing the
prompt fragment — the fragment needs to reference the *actual* mechanism
correctly, the same lesson as §2.6.

### 4.5 Combinatorial test requirement (§2.4's caution, made concrete)

Per §2.4, do not consider Feature B done after a single "does it render"
check. Minimum test matrix:

| Planner | What to verify with `render_style="archival_montage"` |
|---|---|
| Director | Produces a valid `creative_context` — no crash, no style-specific field left `None`/empty that a later planner assumes is populated |
| Scene Planner | Produces scenes respecting whatever `max_scenes`/duration bounds `resolve_constraint_bundle` derives from the new `StylePacingBand` |
| Shot Planner | Produces shots respecting the new duration overrides; camera/transition vocabulary matches what `archival_montage.md` actually asked for (spot-check, not just "did it crash") |
| Asset Planner | No style-specific behavior expected here today (asset planning isn't currently style-branched per the code read during this session) — confirm this is still true, don't assume |

This can be done with **unit tests using a fake/stub LLM provider**
(`FakePlanningProvider`, already used throughout
`backend/tests/unit/planners/`) — no live LLM calls, no database. See §6.

### 4.6 Format — DECIDED 2026-08-25: 9:16 vertical

`archival_montage` targets **9:16, `720×1280`** — identical to
`retention_fast`'s dimensions (§4.3's code block already has this set
explicitly, not left to inherit the dataclass default). Decided because
this whole plan originated from a "styles for reels" ask (§1.1) — a
landscape-first montage style would be off-brief. `stillness`'s
16:9-default-with-9:16-opt-in shape (`styles.py:167-168`) was considered
and rejected for this style specifically; it remains the right shape for
`stillness` itself, whose "long contemplative" framing is a real 16:9-first
use case that `archival_montage` doesn't share.

### 4.7 Test plan — pure unit tests, no DB, no live LLM

- `test_styles.py` (existing file, `backend/tests/unit/script/`) — add
  `archival_montage` cases mirroring the existing per-style assertions
  (band resolution, `max_fragment_duration_s` property, narration speed
  resolution) already there for the other 3 styles.
- `test_grading.py` — add an `archival_montage` grade-fragment case.
- Per-planner unit tests (§4.5's matrix) using `FakePlanningProvider` —
  mirror the structure already used in
  `backend/tests/unit/planners/test_asset_planner.py`,
  `test_shot_planner.py` (if that's the actual filename — confirm), etc.,
  for the other styles.
- **No e2e test that creates a real project via the HTTP API and drives it
  through a real render for this style** — that requires the live shared
  Postgres and violates §6. A real render for human visual review (as was
  done live in this session for the camera-vocabulary test, reusing an
  existing project's assets via `POST /shots/{shot_id}/override` to avoid
  spend) is a **manual verification step for a human to run**, not part of
  the automated test suite this plan specifies.

### 4.8 Effort

~2 days per the original plan's own estimate (motion doc §2.4) — 1 day for
the styles/grading/prompt-fragment mechanics (§4.3), ~half a day for the
combinatorial planner tests (§4.5), ~half a day for review/fixup.

---

## 5. Feature C — Glitch transitions

### 5.1 Goal

A transition where, for a few frames at a cut, the image briefly corrupts
(RGB channel split / chromatic aberration, horizontal block displacement,
or a noise burst) before the next shot resolves — distinct from the
existing hard cut, dissolve, or the two Tier 2 xfade additions
(`wipeleft`, `fadeblack`).

### 5.2 Why this needs a spike before a real build estimate

Unlike Feature B, there is **no existing pattern in this codebase to
copy**. `xfade`'s ~50 built-in transitions (already surveyed once by this
team when `wipeleft`/`fadeblack` were chosen, per the motion doc §2.6) do
not include a true RGB-split/datamosh glitch effect. This means Feature C
is either:

- **Option 1 (cheap, weaker resemblance)**: pick one more real `xfade`
  transition name that reads as "digital/glitchy" by association —
  candidates to actually test against a real ffmpeg build and a real
  archival photo (same verification discipline as `TransitionType`'s own
  docstring demands, `timeline.py:101-104`): `pixelize`, `hlslice`,
  `vuslice`, `hrslice`, `vdslice`. **None of these are confirmed to look
  like a "glitch" — this must be visually verified against this project's
  actual ffmpeg version before committing to it**, exactly like
  `wipeleft`/`fadeblack` were verified "against a real ffmpeg build and a
  real render against real archival photos," not assumed from ffmpeg
  documentation.
- **Option 2 (true glitch, genuinely new work)**: a custom
  `filter_complex` fragment — e.g. `rgbashift` (channel offset) layered
  with a short `noise` burst, cross-dissolved with the two source clips
  over ~0.15–0.3s. This has no precedent in `app/renderer/` to copy from
  and needs real experimentation against real ffmpeg to get looking right,
  not just to get syntactically valid.

**Recommendation: run Option 1 as a cheap spike first** (a few hours: try
each candidate xfade name against one real archival photo pair, using the
exact same throwaway-verification approach `wipeleft`/`fadeblack` used).
If none of them read as "glitch" to a human looking at the output — which
is likely, since they're not designed for that — **do not fake it by
mislabeling a slice-wipe as a glitch transition**. Escalate to Option 2 (or
report back that the feature isn't cheaply achievable and let the user
decide whether it's worth the larger investment) rather than shipping
something that doesn't match what was asked for.

### 5.3 If Option 2 is chosen — spike methodology, borrowed from the parallax evaluation

The DepthFlow/parallax evaluation
(`motion_new_styles_and_long_form_videos.md` §10/Q10) is the closest prior
art in this codebase for "evaluate a genuinely new visual technique before
committing to a build": it ran in an **isolated throwaway environment**,
tested against **real project material** (the user's own archival photos,
not stock test images), and reported measured cost/quality findings before
any production code was written. Apply the same shape to a glitch-effect
spike:

- Prototype the `filter_complex` fragment as a standalone ffmpeg command
  line first (not inside the Python renderer) against 2–3 real archival
  photos from an existing project's asset pool (e.g.
  `backend/storage/058b0e05-8468-42cc-81ae-01d3ebdb3478/assets/` has ~27
  real images already on disk from this session's own testing — reuse
  them, don't fetch new ones).
- Get a human look at the output before writing any renderer integration
  code — this is a "does it look like a glitch, or does it look broken"
  judgment call that cannot be verified by an automated test.
- Only after visual sign-off, integrate into `app/renderer/` following
  whichever existing fragment-composition pattern fits best (likely
  alongside the `xfade` call sites in `slideshow.py`, given transitions are
  already composed there — read `slideshow.py:485-530` and `:685-725`, the
  two `xfade` call sites found during this planning session, before
  deciding where the glitch fragment plugs in).

### 5.4 Files touched (Option 1)

- `app/schemas/timeline.py:93-108` (`TransitionType`) — add the new enum
  value, following the exact comment style already there for
  `WIPE_LEFT`/`DIP_TO_BLACK` (state which real ffmpeg filter name it maps
  to, and that it was verified against a real build/render, not assumed).
- No renderer code changes needed if it passes straight through to `xfade`
  exactly like the two existing Tier 2 transitions do (confirm this is
  still true by reading the `xfade` call sites in `slideshow.py` — if a
  transition-specific parameter (e.g. `pixelize`'s block-size) needs
  tuning, that's a small addition to the xfade options string, not a new
  code path).

### 5.5 Files touched (Option 2)

- A new function in `app/renderer/`, likely `slideshow.py` or a new sibling
  module if the fragment is substantial — decide based on how large the
  fragment ends up being after the spike (§5.3), don't pre-decide the file
  structure before the spike produces a working filter graph.
- `app/renderer/fingerprint.py` — any tunable parameter (intensity,
  duration, seed) needs a new fingerprint entry (§2.1). If genuinely
  parameter-free (fixed look, fixed duration), no fingerprint change is
  needed, following the same "fixed code-level constant" exception as
  `STYLE_GRADES`.

### 5.6 Test plan

- **Option 1**: essentially the same shape as whatever test exists for
  `wipeleft`/`fadeblack` today (find it — likely in
  `backend/tests/unit/renderer/` or an integration test that checks the
  xfade argv construction) — extend it with the new transition name. Pure
  unit test on the argv-building function, no DB, no real ffmpeg required
  for THIS test (a separate manual real-render check is how the visual
  spike itself is verified, per §5.3 — that is not part of the automated
  suite).
- **Option 2**: unit tests on the filter-graph-string construction (pure
  string composition, same shape as `test_grading.py` and
  `test_captions.py` if that exists) plus one real-ffmpeg-encode
  integration test proving the command actually runs and produces
  non-empty output (same "allowed, no-DB" shape described in §3.7's last
  bullet).

### 5.7 Effort

- Option 1 spike: a few hours. If it lands, total effort ~0.5 day
  (enum addition + test).
- Option 2 if Option 1 is rejected: ~3–5 days total, including the spike,
  and carries real risk of not landing well within that estimate — this is
  the least-derisked feature in this plan. **Do not commit to a fixed
  timeline for Option 2 before the spike (§5.3) produces something a human
  has actually looked at and approved.**

---

## 6. Testing & DB safety — mandatory, read in full before running any test

**This is a direct, non-negotiable instruction from the user for this
plan: no live-DB tests, no truncation, of any kind, at any point.** These
features "will be tested" separately (by a human, manually, against real
running projects) — automated tests written under this plan must not touch
the shared Postgres database at all.

### 6.1 The hazard, restated from `analysis.md`

`backend/tests/conftest.py` has an **autouse** `clean_database` fixture
that runs `TRUNCATE TABLE ... RESTART IDENTITY CASCADE` across every
application table — **before every single test**, including pure unit
tests that don't need a database, because the fixture is autouse at the
root conftest level. There is **no separate test database** — the same
Postgres instance backs both the dev server and the test suite. Running
`pytest` against `backend/tests/` without care destroys **every real
project** currently sitting in that database, silently, with no
confirmation prompt.

As of 2026-08-24 this is gated behind an environment variable:
`PYTEST_TRUNCATE_DB=1` must be explicitly set for the truncation to run;
unset, the fixture yields without touching the database. `make test` sets
this variable (so the documented "one full-suite run, alone, in the
foreground" workflow is unchanged) — **anyone running tests under this
plan must NOT set `PYTEST_TRUNCATE_DB` and must NOT run `make test`** for
incremental verification during development.

### 6.2 Rules for this plan specifically

1. **Every test written for Features A, B, and C must be runnable with
   `pytest <path> --noconftest` or by construction avoid needing the
   database at all** (pure functions, `FakePlanningProvider`/fake
   providers instead of real DB-backed repositories, fabricated
   alignment/timing data instead of a real ElevenLabs call). This mirrors
   exactly how `analysis.md`'s own P1/P2/P4 log entries verified their
   work: `pytest tests/unit/renderer/test_sfx.py
   tests/unit/renderer/test_fingerprint.py --noconftest`.
2. **Do not write, and do not run, any integration or e2e test that
   creates a real `Project` via the HTTP API, uploads a script, or drives
   a workflow run through the real engine against the real database**, for
   any of the three features in this plan. That category of testing is
   explicitly deferred to manual human verification, the same way this
   session's own camera-vocabulary test was done live by hand (create a
   throwaway project, dummy-fill assets via the existing
   `POST /shots/{shot_id}/override` endpoint to avoid real generation
   spend, inspect the render manually).
3. **If a test genuinely requires real ffmpeg** (the burn-in tests
   mentioned in §3.7 and §5.6), that is fine and already an established
   pattern in this codebase (`test_grading.py`, per `analysis.md`'s own
   citation of "real ffmpeg encodes" in its P3 verification) — ffmpeg is
   not the database, and running it does not touch Postgres. Confirm this
   is true for any new test by checking it does not import
   `async_session_factory`, does not use any `*Repository` class, and does
   not go through `backend/tests/conftest.py`'s fixtures at all if
   avoidable.
4. **Never run the full suite (`pytest` with no path, or `make test`)
   during development of this plan.** If a broader sweep is genuinely
   needed to check for regressions, run explicitly-scoped paths with
   `--noconftest`, one directory/file at a time, and confirm before running
   that none of the files in that path use `async_session_factory`.
5. **If a test cannot be written without the database** (this should not
   happen for any of the three features as scoped in §3/§4/§5 — flag it
   immediately if it seems to, rather than assuming it's unavoidable),
   stop and report back rather than running it against the live shared
   instance. There may be a fixture/mocking approach that was missed.

### 6.2a Reference: which existing test files to model new tests after

| New test area | Model after (existing file) | Why |
|---|---|---|
| Feature A, ASS output | `backend/tests/unit/renderer/test_grading.py` | Pure string-composition testing of a render-fragment function, no DB, no ffmpeg needed for most cases |
| Feature A, real ffmpeg burn-in | Same file, or wherever the "real ffmpeg encodes" tests referenced in `analysis.md`'s P3 log live | Confirms actual encode succeeds without needing a full project/DB |
| Feature B, style resolution | `backend/tests/unit/script/test_styles.py` | Already has per-style assertion patterns for all 3 existing styles |
| Feature B, per-planner behavior | `backend/tests/unit/planners/test_asset_planner.py` and siblings | `FakePlanningProvider` pattern — no real LLM call, no DB beyond a stubbed session if even that |
| Feature B, grade | `backend/tests/unit/renderer/test_grading.py` | Same file as Feature A's — add a case rather than a new file |
| Feature C, transition argv | Wherever `wipeleft`/`fadeblack` are currently tested (find via grep for `WIPE_LEFT` or `wipeleft` in `backend/tests/`) | Direct precedent for "add one more xfade transition name" |
| Feature C, fingerprint (if Option 2) | `backend/tests/unit/renderer/test_fingerprint.py` | Existing pattern for proving a new parameter changes the hash (see `sfx_whoosh_enabled`'s own regression test, `analysis.md` P2 log) |

---

## 7. Sequencing recommendation

1. **Feature A (captions)** first — cheapest, highest-confidence value per
   the trend research, zero architectural risk, no dependency on the other
   two.
2. **Feature B (archival_montage)** second — mechanically well-understood,
   but do not start until Feature A's fingerprint/style-gating pattern
   (§2.1, §2.3) has been exercised once, since Feature B's grade addition
   follows the identical "fixed code-level lookup" reasoning and it's
   useful to have just re-proven that pattern works before relying on it
   again.
3. **Feature C (glitch transitions)** last, and gate the Option 2 decision
   on Option 1's spike result (§5.2) — do not start the larger custom-filter
   work until the cheap xfade-name option has been visually tried and
   rejected.

Do not parallelize B and C against A — Feature A's caption work and
Feature B's prompt-fragment work both touch style-gating conventions
(`StylePacingBand`, `resolve_*_enabled` functions) and are easier to keep
consistent done in sequence by one line of reasoning than in parallel by
two.

---

## 8. Implementation log

*(Empty. When work on this plan begins, add dated entries here in the exact
shape `analysis.md`'s P1–P6 entries use: scope executed, changes with
file:line references, verification performed — explicitly including which
`--noconftest` command was run and its pass count — and effects/reviewer
notes. See navigation item 6 in §0 for the full rationale.)*
