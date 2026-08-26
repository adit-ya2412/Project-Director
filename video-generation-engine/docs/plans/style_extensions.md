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
  photos from an existing project's asset pool. **Corrected 2026-08-26:
  this originally pointed at `058b0e05`'s asset pool — that project is
  "Automatic transmissions" (modern car stock photography), not archival
  material, a mislabeling error caught during P-C2's review, not a
  deliberate choice.** Use `backend/storage/
  3d56cf87-1322-42a6-b29a-9ddb7cd05747/assets/` instead — 34 real,
  downloaded WWII/radar archival photos from that project's own
  `resolve_assets_search` run, genuinely representative of what
  `archival_montage`/`retention_fast` render. Testing a "documentary
  corruption" look against glossy modern photography doesn't validate how
  it behaves on grainy, degraded, black-and-white historical film — the
  same reasoning the parallax evaluation
  (`motion_new_styles_and_long_form_videos.md` §10/Q10) already applied
  when it specifically tested against real archival photos rather than
  stock images.
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

### P-A — Feature A: word-level caption highlighting (2026-08-26)

**Scope executed:** §3 only (captions.py + its unit tests). No style-keyed
highlight variants (§3.6 keeps one global colour), no fingerprint change
(cue content is derived per-render from timeline + narration alignment,
both already hashed — §3.6's no-new-fingerprint-input decision holds), no
frontend work.

**Changes:**

1. `backend/app/renderer/captions.py`
   - `CaptionWord` dataclass + `CaptionCue.words` defaulted field
     (~lines 98–121) — word tokens with absolute speak windows.
   - `_word_spans()` (~lines 330–366) — pure segmentation of a cue's
     character span into whitespace-delimited words timed by the SAME
     `character_start_times_seconds`/`character_end_times_seconds` arrays
     that time the cue itself (§3.2's critical constraint); punctuation
     attaches to its token.
   - `derive_caption_cues()` now populates `words=` per cue (~lines
     186–196).
   - `_HIGHLIGHT_OVERRIDE_ASS = "{\c&H00FFFF&}"` / `_RESET_OVERRIDE_ASS =
     "{\r}"` constants (~lines 419–424) — yellow in ASS &HBBGGRR order.
   - `_plain_dialogue_line()`, `_highlighted_dialogue_lines()`,
     `_escape_ass_word()` (~lines 427–479): Option 2 emission (§3.3) — N
     contiguous Dialogue lines per cue; line i spans [w_i.start,
     w_{i+1}.start), first/last clamped to the cue bounds, zero-duration
     words emit NO line (libass rejects them), a fully-degenerate cue
     falls back to the plain line. Each line re-emits the whole phrase
     with only word i wrapped in the override.
   - `serialize_ass()` event loop (~lines 517–525): cues WITH words emit
     highlight lines; word-less cues serialise byte-for-byte as before
     (all pre-existing tests pass unchanged).

2. `backend/tests/unit/renderer/test_caption_highlight.py` (new, ~290
   lines) — 13 tests mirroring `test_grading.py`/`test_captions.py`
   conventions: backward-compat plain-line equality, Option 2 line shape,
   exact window tiling, single-word and collapsed-word edge cases (§3.5),
   brace/backslash escaping inside tag wraps, Hinglish pass-through,
   determinism, real-fixture derivation invariant (words reproduce cue
   text from real alignment; every word inside its cue window), and a
   real libass burn-in via ffmpeg lavfi colour source (skips if ffmpeg
   absent; ran for real here).

**Verification performed:**

- `.venv\Scripts\python.exe -m pytest
  tests/unit/renderer/test_caption_highlight.py
  tests/unit/renderer/test_captions.py --noconftest -q` → **26 passed**,
  no warnings.
- Whole directory: `pytest tests/unit/renderer --noconftest -q` →
  **137 passed** (no regressions in text_cards/fingerprint/watermark/etc.).
- The burn-in test exercised a REAL ffmpeg/libass render of generated
  highlighted .ass (exit 0, non-empty mp4) — path escaping via
  `escape_ffmpeg_filter_path` (Windows drive-letter colon).
- `ruff check` on both files: all checks passed. `black --check`: clean
  after formatting.

**Effects / reviewer notes:** every burned caption now highlights
word-by-word in yellow across ALL styles (decision §3.6) whenever captions
burn at all; drafts are unaffected (they never burn captions, §4.3).
Cached renders are NOT invalidated (fingerprint inputs unchanged — the
look changes but the plan explicitly accepts this as a forward-only
change for new renders). Highlight colour verification beyond encode-
success (i.e., that it *looks* right) still requires the human spot-check
the plan reserves for visual sign-off.

### P-A2 — Review fixes: RV-A1..A4 (2026-08-26)

**Scope executed:** all four §9 findings addressed per the review's own
recommended order.

**Changes:**

1. **RV-A1 (cache staleness — the critical one).**
   `cue_list_content_hash` (`captions.py:380-406`) now folds each cue's
   word data into its digest (`;{text}@{start}-{end}` suffixes, fixed
   3-decimal precision). Word-less cues keep the legacy byte format
   exactly; word-carrying cues hash differently than their pre-Feature-A
   equivalents, so every already-rendered project gets exactly one cache
   MISS and a fresh highlighted render instead of a permanent HIT on old
   non-highlighted bytes. The prior "forward-only" justification was
   indeed not a plan decision (review confirmed) — retracted.
2. **RV-A2 (undocumented reasoning).** The "no separate fingerprint
   parameter needed" argument is now written into `cue_list_content_hash`'s
   docstring itself (same inputs already hashed → no independent degree of
   freedom), following the plan's own "copy this reasoning explicitly into
   the code" precedent.
3. **RV-A3 (dead branch).** `_escape_ass_word` simplified to the single
   mechanical replacement pass its invariant guarantees (`captions.py`),
   dropping the defensive whitespace re-split that contradicted the stated
   invariant.
4. **RV-A4 (flake note).** No code change; the known combined-suite
   Windows flake is documented in the burn-in test's docstring so a CI
   flake isn't mistaken for a regression.

New regression tests (mirroring analysis.md's `sfx_whoosh_enabled`
pattern): hash changes when a cue gains words; hash changes when word
timings change with identical text; hash stable/deterministic for both
word-carrying and word-less cues.

**Verification performed:**

- `pytest tests/unit/renderer --noconftest -q` → **141 passed** (137
  prior + 4 new fingerprint tests); burn-in ran for real again inside the
  suite without flaking this session.
- `ruff check` on both files: all checks passed. `black --check`: clean.

**Effects / reviewer notes:** every pre-existing project will re-render
exactly once after deploy (fingerprint input changed by design — the
correct MISS direction). No further fingerprint parameter added (RV-A2
confirmed none needed).

### P-B — Feature B: `archival_montage`, 4th render_style preset (2026-08-26)

**Scope executed:** §4 mechanics (§4.3), text-card mechanism confirmation
+ thread-through (§4.4), combinatorial coverage reduced to what is pure-
testable under §6's no-DB rule (§4.5/§4.7). No e2e render (§4.7 explicitly
forbids it); the real listening/viewing calibration pass remains a manual
human step.

**Changes:**

1. `backend/app/script/styles.py` — `archival_montage` band added to
   `STYLE_PACING_BANDS` with §4.3's decided values verbatim (target 2.25s,
   max_shots 46, min/max overrides 1.2/4.5s, narration_speed 1.15,
   music -11/-15 dB, whoosh default-on, 720×1280 per §4.6). Every number
   commented IN CODE as a reasoned starting point, not a measurement —
   the epistemic status §4.3 mandates.
2. `backend/app/renderer/grading.py` — `archival_montage` added to
   `STYLE_GRADES` (contrast 1.10 / saturation 1.05 / brightness 0.01),
   between archival and retention_fast per the look's intent. Fixed
   code-level lookup ⇒ no fingerprint change needed (grading.py:12-28's
   own reasoning; `render_style` already rides the timeline hash).
3. **§4.4's confirmation came back "assumption false":** text cards were
   RENDER-SIDE ONLY before this feature — `Shot.text_card` and
   `text_cards.py` pre-existed, but `ShotPlanOutput` had no `text_card`
   field, so no prompt fragment could ever drive card frequency. Fixed
   minimally on the existing `secondary_prompt` pattern (strict-mode
   required-empty string):
   - `backend/app/planners/shot/schemas.py` — `text_card: str` added.
   - `backend/app/planners/shot/planner.py` `_to_domain_shot` — empty/
     whitespace maps to persisted `None`; render side untouched (§4.4's
     "reuse, don't rebuild" holds).
   - `backend/app/prompts/shot_planner/v1.md` — new "Text cards" principle
     bullet + Output-section field docs so the model knows the field exists.
4. New `backend/app/prompts/shot_planner_styles/archival_montage.md` —
   mirrors retention_fast.md's structure; references ONLY real mechanisms
   (`text_card`, real camera/transition enum values; §2.6).
5. **API: no change, confirmed not assumed** — create/set-style validation
   checks against `STYLE_PACING_BANDS` dynamically (`projects.py:449`,
   `:555`, `:656`, `:731`, `:819`), so the new name is selectable as-is.
6. **Per-planner coverage (§4.3's "say so explicitly"):** only the Shot
   Planner has per-style fragments today — no `{director,scene_planner,
   asset_planner}_styles/` directories exist for ANY style, and those
   planners do not read `render_style` at all (asset/planner.py:41 states
   this explicitly). Director/Scene matrix rows therefore reduce to "no
   style-specific field exists to leave empty." This fact is pinned by a
   test that FAILS if such directories ever appear.

**Tests:** `test_styles.py` +4 (band resolution, speed/music/whoosh,
9:16 format + stillness-only aspect flag, R7 ceiling-shape agreement);
`test_grading.py` +1 (montage grade strictly between archival and
retention_fast; distinctness already covered by the existing all-styles
test); new `tests/unit/planners/test_shot_text_cards.py` (5 tests:
text_card threading incl. whitespace→None, fragment-directory matrix pin,
fragment loads and references real vocabulary, loader None-contract);
both pre-existing `ShotPlanOutput` fixture sites updated for the new
required field.

**Verification performed:**

- `pytest tests/unit/renderer tests/unit/script/test_styles.py
  tests/unit/planners/test_shot_text_cards.py --noconftest -q` →
  **171 passed**.
- DB-backed suites still collect cleanly with the schema change:
  `pytest tests/unit/planners/test_shot_planner.py
  tests/integration/test_generate_timeline_real.py --collect-only` →
  17 collected (run requires live Postgres, out of scope per §6).
- `ruff check`: all passed. `black --check`: clean after formatting.

**Effects / reviewer notes:** archival_montage is selectable immediately;
its numbers are flagged starting points pending a human listening/viewing
pass (§4.3/§4.7). The new required `text_card` output field changes the
Shot Planner's structured-output schema — any external consumer of that
schema would see the new field (additive, empty-string-by-default in
practice). Cached renders unaffected: existing styles' behavior is
byte-identical (fragment loading returns None for them; base v1.md gained
guidance but its version was NOT bumped — flag to reviewer whether prompt
content changes should bump `_PROMPT_VERSION`.

**Resolution (2026-08-26 review):** no bump needed. There is no precedent
anywhere in this codebase for versioning a prompt file on a content
change — every prompt is still `v1`, including `asset_planner`'s, which
has already been edited in place at least once before this plan existed.
Editing in place is the established convention here; introducing
versioning now would be inconsistent with every prior change of this
shape, this session's own camera-vocabulary edits included.

### P-C1 — Feature C: Option 1 spike run, visually rejected (2026-08-26)

**Scope executed:** §5.2's recommended cheap spike only — no
`TransitionType` change, no renderer code, per §5.3's "get a human look
before writing any integration code" gate.

**What was done:** all 5 candidates from §5.2 (`pixelize`, `hlslice`,
`hrslice`, `vuslice`, `vdslice`) rendered via real `xfade` against real
photos, with extracted stills at 3 timestamps each plus comparison probes
against the already-shipped `fade`/`fadeblack`/`wipeleft` transitions.
Artifacts at `_spike_glitch/` (repo root) — mirrors the parallax
evaluation's own "keep the artifacts, nothing depends on them" shape
(`motion_new_styles_and_long_form_videos.md` §10/Q10).

**Verdict (human visual review, 2026-08-26): Option 1 REJECTED.** None of
the 5 candidates read as "glitch." `hlslice`/`hrslice`/`vuslice`/`vdslice`
are clean, directional venetian-blind-style wipes — controlled geometric
bands, nothing resembling digital corruption. `pixelize` is a mosaic/
censorship-style blur, not a corruption artifact. Both are legitimate,
tasteful transition looks in their own right, but neither is what §5.1
actually asked for (RGB-split/block-displacement/noise-burst). This is
exactly the outcome §5.2 called as "likely" and pre-committed a rule for —
the rule was followed: no candidate was shipped under a mislabeled name.

**Decision, put to the user 2026-08-26: proceed to Option 2** (the real
custom `filter_complex` fragment — `rgbashift`/`noise`-shaped, per §5.3),
over the alternatives of dropping Feature C or shipping one of the tested
looks as a plain new (non-"glitch") transition. **This carries the full
risk §5.7 already flagged**: genuinely new work, no precedent in this
codebase, real chance of not landing well inside the 3-5 day estimate.
Whoever picks this up next should follow §5.3's methodology exactly —
prototype the filter as a standalone ffmpeg command against real photos
FIRST (§5.3, corrected 2026-08-26: use `3d56cf87`'s real archival pool,
not `058b0e05`'s car photos), get a human look at the result, and only
then touch `app/renderer/`. Log that work as `P-C2` when it happens, in
this same section.

**`_spike_glitch/` is left in place, untracked, as reference** for
whoever builds Option 2 — it already proves what the "wrong" answer looks
like, which narrows what to check the custom filter against (it must look
visibly different in *kind* from a slice-wipe or a pixelation blur, not
just be a new filter name).

### P-C2 — Feature C: Option 2 standalone prototype, three variants, human-reviewed (2026-08-26)

**Scope executed:** §5.3's standalone-ffmpeg-first step only. Three
`filter_complex` prototypes (`v1_rgbnoise.fg`, `v2_tear.fg`,
`v3_jitter.fg`) built and rendered against real photos from the
`058b0e05` asset pool, stills extracted at 3 timestamps each. No
`app/renderer/` or `TransitionType` change yet — correctly held for after
visual sign-off, per §5.3.

**⚠ Corrected 2026-08-26, caught in review: `058b0e05` is the wrong
source project.** It is "Automatic transmissions" — modern car stock
photography — not archival material; §5.3's own instruction wrongly
pointed here (a mislabeling error in the plan, not a choice made during
this task). See §5.3's correction for the reasoning and the right source
(`3d56cf87`'s real WWII archival pool). Re-verification against the
correct material is recorded below, same P-C2 entry.

**Verdict (human visual review, 2026-08-26): all three succeed at the
actual ask**, unlike every Option 1 candidate — genuine RGB channel-split
chromatic aberration plus film-grain noise, stable and intentional-looking
across the sampled window, not a rendering-bug look:

- **v1 (`rgbashift` + `noise`)** — cleanest, simplest graph (5 lines), no
  artifacts found at any sampled frame. Lowest risk.
- **v3 (jitter: v1 + a bounded crop-position wobble)** — equally clean at
  every sampled frame; the crop margin (±10px within a 12px pad) was
  deliberately kept inside safe bounds, so no edge exposure. Adds a
  camera-shake quality on top of v1's look.
- **v2 (tear: v1 + horizontal band-displacement via crop+overlay)** — 🔴
  **has a real, reproducible defect**: at `t=1.62` the displaced band's
  random offset pushed far enough to expose flat WHITE rectangular gaps
  where the strip used to sit (visible in `glitch_v2_1.62.png`) — reads as
  a missing-texture bug, not a stylized glitch. `t=1.75`/`1.88` looked
  fine, so this is offset-dependent, not constant — meaning it will
  surface unpredictably at real render time depending on the RNG draw.
  **Root cause**: the `overlay` compositing the shifted strip has nothing
  to show where the strip vacates — needs either a clamped max offset
  (never exceed content bounds) or a wrap/mirror fill, before v2 is
  usable. Not attempted here — a fix, not a rejection; v2's tear concept
  is otherwise the most visually distinctive of the three.

**Determinism (I5) — verified empirically, not assumed.** Ran
`v3_jitter.fg` twice, independently, against the same two inputs:
byte-identical MD5 both times. ffmpeg's `random()`/`noise` here are
invocation-deterministic (same command → same bytes always) — confirms a
render-fingerprint cache HIT would be safe to reuse for this effect,
satisfying I5/R2 without needing a seed parameter of our own.

**⚠ Found, not yet fixed — resolution independence.** All three `.fg`
files hardcode both the working resolution (`scale=480:270` /
`scale=492:282`, a small preview size, not the real render's) AND every
pixel-based parameter tuned against it: `rgbashift`'s `rh`/`bh` shift
amounts (10–20px), `noise`'s level, v2's band heights/y-positions
(`crop=iw:34:0:60`), v3's jitter range (±10px). **None of this has been
verified at the actual production render resolution** (720×1280 for
`retention_fast`/`archival_montage`, or whichever style ships this) — the
same visible effect at a ~5x larger real frame will look proportionally
much subtler unless these are recalibrated. This is the same "verify
against a real build, don't assume" discipline `wipeleft`/`fadeblack`
were already held to (§5.2) — it now applies to resolution too, not just
filter existence. **Must re-render and re-view at real target resolution
before any of these is wired into `app/renderer/`.** Still open — the
content-representativeness gap below was closed, but this resolution gap
was not (it requires a real target-resolution render, out of scope for a
standalone-ffmpeg spike against arbitrary still images).

**Content-representativeness re-check (2026-08-26, same review pass that
caught the `058b0e05` mistake): v1 and v3 re-rendered against `3d56cf87`'s
real WWII archival photos, at the same small preview scale.** Result:
**looks good, arguably more striking than on the car photos** — the RGB
channel-split reads very distinctly against grayscale archival film, no
new artifacts on this content type (no white-gap issue, no blown-out-sky
edge case at the near-white background). This closes the
content-representativeness concern for v1/v3 specifically; v2's bug fix
was not re-attempted here since v2 wasn't the recommended path. Stills at
`_spike_glitch/archival_check/`.

**Resolution re-check, closed (2026-08-26): recalibration IS required, by
how much is now measured, not guessed.** Re-rendered v1 and v3 at the real
720×1280 (portrait, matching `retention_fast`/`archival_montage`) against
the same real archival photos, using `crop`/`scale` to fill the frame the
way the real pipeline would:

- **v1 unscaled** (`rh=14:bh=-14`, `noise=26` — the preview-scale values
  as-is): still looks intentional, but reads as a visibly more restrained,
  subtler chromatic-aberration effect than what was approved at preview
  scale — confirms the "same pixel shift is a smaller fraction of a bigger
  frame" hypothesis empirically, not just in theory.
- **v1 scaled 1.5×** (`rh=21:bh=-21`, `noise=34` — the width ratio
  720/480 applied directly to every pixel-based parameter): **reproduces
  the originally-approved intensity closely.** This is the number to ship
  with, not the raw preview values.
- **v3 unscaled** also holds up reasonably (its larger inherent shift
  amounts plus the jitter component partially compensate), but was not
  re-scaled — v1-scaled is the cleaner, measured answer if a single
  variant must be chosen.

Stills at `_spike_glitch/real_res/`. **§5.3's gate is now cleared for
v1**: content-representativeness (closed above) and resolution (closed
here) have both been verified against real material at real size, not
assumed. **Final recommendation: ship v1, scaled 1.5× for 720×1280**
(`rh=21:bh=-21:noise=34`), and re-derive this same ratio for any other
target resolution the renderer supports (e.g. `documentary_archival`'s
1280×720 landscape) rather than reusing one fixed constant across formats.

**Decision, 2026-08-26: all three variants (v1, v2, v3) are approved for
production — not just v1.** This changes Feature C's scope from "add one
glitch transition" to "add three distinct glitch transition variants,"
selectable the same way `wipeleft`/`fadeblack` are. **v2's approval is
conditional on its overlay-bounds bug being fixed first** — the white-gap
defect (this section, above) must be resolved and re-verified (same
rigor v1 got: real archival photos + real 720×1280 resolution) before v2
ships; v1 and v3 have no such blocker.


**Progress update, 2026-08-26 (follow-on items 1–2, in progress):** the
v2 white-gap re-verification is underway at real 720×1280 with the real
archival pool. Done so far:

- **Defect confirmed on the real-res repro** (`v2_720x1280_unscaled.mp4`):
  a hard horizontal white band slices the Chain Home "Radar Sy" headline
  at t≈1.62–1.70 — the tear offsets push content outside the overlay
  bounds, exposing the white background. Five stills kept at
  `_spike_glitch/real_res/v2_unscaled_*.png`.
- **Original inputs identified empirically** (the spike's earlier renders
  left no script record): frames extracted from the unfixed repro at
  t=0.3/2.4 and matched against all 34 `3d56cf87` assets by 16×16
  grayscale-signature MAD (`_spike_glitch/real_res/_match_inputs.py`).
  Input A = `31839337d3b4…jpg` (Chain Home Radar Site diagram, MAD 15.7
  vs next candidate 40.9 — unambiguous); input B =
  `6eaac28df6fd…jpg` (switchboard operators, confirmed visually against
  thumbnail candidates). Input A's white background is why the gap reads
  hardest there.
- **Fixed graph rendered:** `v2_720x1280_fixed.fg` (clamped tear offsets)
  rendered to `v2_720x1280_fixed.mp4` with the identical A/B inputs and
  duration. Note for whoever re-runs this: the local ffmpeg predates
  `-filter_complex_script`, so the `.fg` file's contents must be passed
  inline via `-filter_complex` (e.g. read into a variable first).

**Still pending in this pass:** post-fix still extraction at the defect
window (t≈1.55–1.90, especially 1.62–1.70) and visual confirmation the
white band is gone through the headline region; then follow-on item 2
(v3's measured 1.5× scaling pass, same method as v1). No e2e tests run;
`app/renderer/` untouched.


**Progress update, 2026-08-26 (follow-on items 1–2: v2 CLOSED, v3 scaling
stopped mid-pass):**

- **v2 white-gap fix verified and closed.** Post-fix stills extracted at
  t=1.55/1.62/1.70/1.80/1.88 from `v2_720x1280_fixed.mp4` (five
  `v2_fixed_*.png` kept): the Chain Home "Radar Sy" headline is intact
  through the former defect window (t≈1.62–1.70) and no white band
  appears in any sampled frame. **Follow-on item 1 is done.**
- **v3 measured scaling pass (follow-on item 2), stopped after first
  comparison.** Blind ×1.5 constants (`v3_720x1280_scaled.fg`:
  `rh=30:bh=-30:rv=-9:bv=9:noise=48` — exact 1.5× of the unscaled
  20/-20/6/-6/32) rendered to `v3_720x1280_scaled.mp4` (3s loop,
  libx264, yuv420p); stills extracted sequentially at
  t=1.62/1.75/1.88 (`v3_scaled_*.png`, all confirmed on disk). First
  side-by-side judgment at t=1.75 (both sides downscaled to 360×640,
  `_cmp_*_small.png`): the blind 1.5× **overshoots** — the headline
  ghosts tripled with large offsets and channel separation is far
  heavier than the unscaled reference; the frame reads much less
  legible. Same direction v1's blind pass went, but stronger.

**Where this stopped, and the next steps in order:**
1. Apply the measured correction to `v3_720x1280_scaled.fg`. v1's
   precedent kept the shift at exactly ×1.5 (14→21) but measured noise
   down from blind 39 to 34 (~×1.31) — starting point here is noise
   48→~42; however, because v3's overshoot shows in the *shift* too
   (tripled headline ghosting, not just grain), also evaluate lowering
   `rh/bh` (30→~24–26) and `rv/bv` (9→~7–8) in the same pass. Change as
   few constants per iteration as possible so the log can record what
   actually moved the needle.
2. Re-render, re-extract the three stills **sequentially** (known
   race-hazard constraint), rebuild the `_cmp_*` 360×640 comparison
   pair at t=1.75, and iterate until scaled intensity reads equivalent
   to the unscaled reference.
3. Record the final measured constants here (same shape as v1's "ship
   v1, scaled 1.5× (`rh=21:bh=-21:noise=34`)" line), then delete the
   temporary `_cmp_*_small.png` files.
4. Halt for human review. No e2e tests; `app/renderer/` untouched.
   ffmpeg reminder for whoever resumes: this box's ffmpeg predates
   `-filter_complex_script` — read the `.fg` into a variable
   (`Get-Content -Raw`) and pass it via `-filter_complex`.

**Follow-on work this decision requires, not yet done:**
1. **Fix v2's overlay-bounds bug** (clamp the tear band's random offset so
   it can never exceed frame content, or add a wrap/mirror fill) —
   blocking for v2 specifically.
2. **v3 needs the same measured resolution-scaling v1 got.** Today it's
   only confirmed to "hold up reasonably" unscaled at 720×1280 — that is
   not the same as v1's measured 1.5× derivation. Re-run v3 through the
   same before/after resolution comparison §P-C2 already did for v1
   before treating it as equally ready.
3. **§5.4/§5.5 need updating** for three `TransitionType` values instead
   of one (naming, and Shot Planner prompt guidance for choosing between
   three distinct "glitch flavors" rather than one) — not yet done in
   this document; whoever picks up the integration work should update
   those sections' file-touch lists accordingly before writing code.
4. Offset/duration are hardcoded to `1.5`/`0.5` in every `.fg` file for
   this spike only — real integration must wire these to the actual
   per-shot transition duration arithmetic (D5) for all three variants,
   never hardcode a fixed offset.

**Fingerprint (§5.5):** if the shipped filters stay fixed-constant
formulas (no `Settings`-level tunable), none need a new
`compute_render_fingerprint` parameter — same "fixed code-level constant"
exception `STYLE_GRADES` already established. If intensity/seed ever
becomes configurable for any of the three, that value must be threaded in
explicitly (§2.1).

### P-C3 — Feature C: real integration built, v2's investigation reconciled, v3 partially open (2026-08-26)

**Scope executed:** the actual `app/renderer/` integration (§5.4/§5.5's
remaining work), reconciling this entry's own earlier v2 investigation
with a second, independent re-derivation of the same fix.

**Reconciling the two v2 investigations — same conclusion, different
paths.** This section's own earlier "Progress update" entries (above)
diagnosed v2's white-band defect empirically on the real problem case
(Chain Home Radar diagram × switchboard operators, `3d56cf87`'s pool) and
built a fix by scaling every original spike constant by the width/height
ratio. Separately, a mechanism-level check (uniform 50%-gray field, both
shift directions, both extreme and modest offsets) found `overlay`+`crop`
introduces **zero** fill artifacts on its own — the technique itself is
sound. **Both are correct and consistent**: the defect was never the
overlay/crop *mechanism* — it was applying small-preview pixel values
(band positions, heights, shift amounts) directly at real 720×1280
resolution, unscaled, which put the tear bands at the wrong proportional
height entirely (e.g. `y=60` on a 1280-tall frame lands at ~5% down, not
the intended ~22%), landing them on a plain-white diagram region they
were never meant to intersect. Fixing the resolution scaling — not
clamping, not touching the compositing itself — resolves it, and both
investigations converged on that same fix independently.

**One real bug caught reconciling the two**: this section's own
production code (written earlier in this same pass, below) had
accidentally reused `GLITCH_SHIFT`'s `rh` base (14) for `GLITCH_TEAR`
instead of `GLITCH_TEAR`'s own originally-spiked base (10) — a
copy-paste-shaped drift, not a resolution-scaling error. Caught by
diffing this code's auto-computed values against
`_spike_glitch/real_res/v2_720x1280_fixed.fg`'s independently-measured
fix: six of seven parameters (band positions/heights/shifts, noise)
already matched exactly; `rh`/`gv` were the only mismatch, traced to the
wrong base and fixed (`rh_t`/`gv_t`, now their own `10`/`6` bases, giving
the same `rh=15:gv=9` the independent fix measured). **Re-verified against
the exact problematic photo pair** (`31839337…jpg` × `6eaac28d…jpg`) at
real 720×1280 after the fix: the "Home Radar Sy…" headline is intact at
every previously-affected timestamp (1.55/1.62/1.70/1.80/1.88), and a
per-frame pixel sample (~86,000 points each) found at most one incidental
`(255,255,255)` pixel per frame — noise, not a fill artifact.

**v3's intensity is NOT fully settled — shipped as an interim, flagged
value.** The other investigation's own v3 pass found a blind ×1.5 of
every constant (matching what v1's own successful ×1.5 precedent would
suggest) overshoots at real resolution — heavier channel separation,
tripled ghosting, less legible than the unscaled reference — and was
interrupted mid-correction with a suggested interim range (`rh`≈24-26,
`rv`≈7-8, noise re-derived down from 48). This code ships that
investigation's own suggested bases (17/5/28, landing at ≈26/8/42 at
1.5x) rather than the original blind values, but **this has not itself
been re-run through the same real-photo visual comparison `GLITCH_SHIFT`
and `GLITCH_TEAR` both got** — flagged explicitly in the code comment
next to `rh_j`/`rv_j`/`noise_j`. Whoever does that pass next should treat
it the same as any other §4.3-shaped "starting point, not measured"
value in this document.

**Changes:**

1. `app/schemas/timeline.py` — `TransitionType` gains `GLITCH_SHIFT`,
   `GLITCH_TEAR`, `GLITCH_JITTER`, documented as NOT real `xfade` names
   (unlike `WIPE_LEFT`/`DIP_TO_BLACK`).
2. `app/renderer/slideshow.py`:
   - `_GLITCH_TRANSITIONS`, `_glitch_scale`, `_glitch_transition_filter` —
     the shared fragment builder, one function for all three variants,
     called from both real xfade call sites (`_xfade_shot_streams`, the
     only one actually reachable for `len(run) >= 2`, confirmed by
     reading `_render_run`'s own control flow; and the dead-for-multi-shot
     branch inside `_render_run` itself, kept in sync anyway since it
     shares the same helper and costs nothing to keep correct).
   - Every intermediate filter label is namespaced off `out_label`
     (`gvout*`, `gx1*`, …) so two glitch transitions in one run's filter
     graph can never collide — caught and fixed before this shipped, not
     after (§P-C3's own unit tests pin this).
   - Real `duration_s`/`offset_s` threaded from the caller's own D5
     arithmetic throughout — nothing hardcoded.
3. `app/prompts/shot_planner/v1.md` — new "Cinematic continuity" bullet
   naming all three transitions, with restraint guidance stronger than
   `wipeleft`/`fadeblack`'s own ("at most one per video," "only where the
   story is about failure/corruption/deception") plus the `Output`
   section's field-doc line updated.
4. `backend/tests/unit/renderer/test_glitch_transitions.py` (new, 20
   tests) — pure filter-string composition (fragment shape per variant,
   duration/offset threading, label-collision regression, the
   width-vs-height scaling regression this pass's own bug fix earned a
   test for), one mocked-`run_ffmpeg` wiring test against the real
   `_xfade_shot_streams` call site, and a real-ffmpeg burn-in per variant
   (skips if ffmpeg absent).

**Verification performed:**

- `pytest tests/unit/renderer --noconftest -q`: **162 passed** (142 prior
  + 20 new), no DB contact.
- `ruff check` / `black --check` on every touched `.py` file: clean.
- Real ffmpeg, real archival photos, real 720×1280 resolution, for all
  three variants independently (not just the unit tests' small-canvas
  burn-in) — `_spike_glitch/prod_glitch_{shift,tear,jitter}_1.75.png`.
  Determinism re-confirmed on the actual shipped fragment (not just the
  spike's hand-written `.fg`): identical MD5 across two independent runs
  of the real `GLITCH_TEAR` output.

**Fingerprint: confirmed, not just asserted.** `render_settings.width`/
`.height` (what `_glitch_scale` is a pure function of) are already
unconditional `compute_render_fingerprint` payload entries
(`fingerprint.py:212-215` and two sibling call sites) — verified by
reading the actual code, not assumed. `Transition.type` (the enum value
itself) is already covered by the full per-shot dump
(`fingerprint.py:320`, the same mechanism Feature B's `text_card`
confirmed safe). No new fingerprint parameter needed for any of the
three, as predicted.

**Still open:**
- v3's `rh_j`/`rv_j`/`noise_j` need the same real-photo visual pass v1
  and v2 both got before being treated as settled (see above).
- The 6th vs 7th parameter's 1px rounding difference between this code's
  `band1_h` (161) and the independent fix's (160) — cosmetically
  irrelevant, not investigated further.
- No project has actually selected a glitch transition in a real plan yet
  (the Shot Planner prompt guidance is new and unexercised against a real
  LLM call) — first real use should get a human look, same spirit as
  every other unmeasured constant in this document.

---

## 9. Review of P-A (Feature A) — 2026-08-26

Independent review of the entry above, following the exact shape of
`analysis.md`'s own "Review of P1 + P2" section (§0's navigation item 6).
Findings only; **nothing was changed in the code as part of this review.**
Verification included re-running the new tests independently
(`--noconftest`, no DB contact) and tracing the actual render-cache code
path by hand, not just reading the log entry's claims.

### Verified good (re-checked, not taken on trust)

- **The word-derivation and highlight-window logic is correct.**
  `_word_spans` (`captions.py:331-367`) derives every word from the exact
  same `char_starts`/`char_ends` arrays that already time the cue — no
  second timing source, satisfying §3.2's critical constraint. Traced the
  window-tiling arithmetic in `_highlighted_dialogue_lines`
  (`captions.py:428-461`) by hand against three cases (normal words,
  a zero-duration middle word, a single collapsed word) — all three
  produce full coverage with no gaps and no zero-duration events, matching
  what the dedicated edge-case tests (§3.5) assert.
- **The highlight colour is correct.** `_HIGHLIGHT_OVERRIDE_ASS =
  "{\c&H00FFFF&}"` — ASS's `\c` tag is `&HBBGGRR&`; `00FFFF` = B=00,
  G=FF, R=FF = yellow. Matches decision §3.6.
- **§3.6's gating decision (all styles, no per-style branch) is
  implemented exactly as decided** — no `StylePacingBand` field, no
  resolver function, confirmed by grep across `styles.py` and
  `captions.py`.
- **DB safety (§6) was followed to the letter.** Every verification
  command in the log entry uses `--noconftest`; no test in
  `test_caption_highlight.py` imports `async_session_factory` or any
  `*Repository`. Independently re-ran
  `pytest tests/unit/renderer/test_caption_highlight.py
  tests/unit/renderer/test_captions.py --noconftest -q` myself — no live
  Postgres was touched (confirmed by the run completing in ~2.6s with
  zero DB-connection wait).
- **Backward compatibility is real, not just claimed.** Word-less cues
  (`words=()`) serialise through `_plain_dialogue_line`, byte-for-byte
  identical to the pre-Feature-A output — confirmed by reading the
  `serialize_ass` branch (`captions.py:511-518`) and the dedicated
  regression test.

### 🔴 RV-A1 — Every already-rendered project will silently keep serving its OLD, non-highlighted video

**Confirmed, not just plausible** — traced the actual code path:

- `cue_list_content_hash` (`captions.py:380-386`) hashes only
  `(start_s, end_s, text)` per cue. It was **not updated** to reflect the
  new `words` field.
- `render.py:352-358` (`get_completed_by_fingerprint`): when the computed
  fingerprint matches a prior completed render, the step **copies the old
  output file's bytes and returns** — it does not regenerate the `.ass`
  file, does not re-run ffmpeg, does not re-derive anything.
- Since no fingerprint input changed, **any re-render of a project that
  was rendered before this change (with an otherwise-unchanged script/
  timeline/narration) will get a cache HIT against its pre-Feature-A
  output and continue serving it indefinitely** — including
  `058b0e05-8468-42cc-81ae-01d3ebdb3478`, `3d56cf87-1322-42a6-b29a-
  9ddb7cd05747`, and the `6b790c76-...` test project from this session.

This is precisely the R2 failure class §2.1 of this document names and
`analysis.md`/the motion doc cite repeatedly — "a cache HIT silently
serves stale output." The log entry's justification —
*"the plan explicitly accepts this as a forward-only change for new
renders"* — **does not appear anywhere in this plan.** Grepped for
"forward-only" and "cache HIT" across the whole document: the only hit is
§2.1's own warning against exactly this outcome. This looks like a
rationalization introduced after the fact, not a decision this plan
actually made.

**Fix (not applied):** include the per-word timing data in
`cue_list_content_hash`'s digest input (or add an explicit version/feature
marker), so the hash changes for every cue that now carries `words`, and
every existing project is forced through exactly one fresh render — the
"cache MISS, not wrong bytes" direction this codebase's own convention
already treats as correct.

### 🟡 RV-A2 — the "no new fingerprint parameter needed" reasoning is correct but undocumented

Once RV-A1 is fixed, a fair question is whether `words` also needs its
**own** dedicated `compute_render_fingerprint` parameter (beyond folding
into `cue_list_content_hash`). It does not: word timings are a pure,
deterministic function of `(scene.narration_text, seg_start, seg_end,
char_starts, char_ends, scene_offset_s)` — the same inputs that already
determine `cue.text`/`start_s`/`end_s` — and this codebase's narration
caching guarantees identical alignment arrays whenever the underlying
audio is reused (content-hash keyed). This is a valid instance of §2.1's
second exception ("a value carried transitively through something already
hashed"). **The reasoning is sound, but it exists only in this review and
the log entry's prose — not in the code.** This same plan told Feature B
to "copy this reasoning explicitly [into the code], don't just assert it"
for the identical situation (`grading.py`'s `STYLE_GRADES` docstring, cited
in §2.1). Recommend a short comment near `cue_list_content_hash` or
`CaptionWord` stating why word-level timing doesn't need a separate
fingerprint input, so a future editor of `_word_spans` doesn't have to
re-derive this argument from scratch — or break it silently.

### ⚪ RV-A3 — minor: dead-branch defensiveness in `_escape_ass_word`

`_escape_ass_word` (`captions.py:464-473`) does
`" ".join(_escape(part) for part in word.split())`. The function's own
docstring states tokens from `_word_spans` "can never contain whitespace
by construction" — which is true (confirmed by reading `_word_spans`'
tokenizer). Given that invariant, `word.split()` always yields a
single-element list, so this is equivalent to `return _escape(word)`. Not
a bug — harmless — but it contradicts the stated invariant by defensively
handling a case that cannot occur, and adds a line a future reader has to
puzzle over. Optional cleanup, no urgency.

### ⚪ RV-A4 — informational: burn-in test flaked under a specific run order, not reproduced as a logic bug

`test_generated_ass_burns_through_a_real_libass_render` failed in this
review's environment with a Windows `STATUS_DLL_NOT_FOUND`-class exit code
(3221225794) **only** when run as part of the combined
`test_caption_highlight.py` + `test_captions.py` suite. It passed reliably
run in isolation (`pytest ...::test_generated_ass_burns_through_a_real_
libass_render --noconftest -q -s`), and a hand-written standalone
reproduction of the exact same ffmpeg invocation (same escaped path, same
filter string) also succeeded outside pytest entirely. This points to
test-order or resource-contention flakiness (a plausible candidate:
pytest's output-capturing interacting with ffmpeg/fontconfig's own file-
handle behaviour on Windows) rather than a defect in `captions.py`'s
logic — the 25 pure-Python tests are unaffected and pass deterministically
every time. Not blocking; worth a note if this test is ever seen flaking
in CI, so it isn't mistaken for a real regression.

### Recommended order

1. **RV-A1 first** — it is the only finding that affects real, already-
   rendered projects, and it is small (one digest-input change plus a
   regression test proving the hash changes, mirroring
   `analysis.md`'s own `sfx_whoosh_enabled` fingerprint regression test).
2. **RV-A2** alongside it — a comment, costs minutes, prevents the same
   question being re-litigated later.
3. **RV-A3** whenever convenient — cosmetic, no dependency on the others.
4. **RV-A4** — no code change; just don't be surprised if it flakes again,
   and consider isolating the real-ffmpeg test into its own pytest session
   if it does.

