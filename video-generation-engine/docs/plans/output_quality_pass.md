# Output Quality Pass — Audio Finishing, Subject-Aware Camera, Edit Rhythm, and the Review Harness

**Status:** OQ-0a + OQ-0b + OQ-1d built; OQ-1a + OQ-1b + OQ-1c built awaiting listen; OQ-2 built awaiting watch. §12 review findings RV-Q1–Q8 **fixed 2026-08-29** (see P-OQ-RV). RV-Q10 **built 2026-08-29** (P-OQ-RV-Q10) and **reviewed — see §16: RV-Q11 is blocking, the sliced audio is 8-20 ms longer per scene than its own alignment says. Do NOT re-narrate for the listen until it is fixed.** OQ-3 / remaining OQ-4 design-only.
⚠ **§14 re-cuts OQ-2: the focal question was being asked of a model that cannot answer it (gpt-4o-mini), and a schema default hid that. Now its own call on gpt-5.5.**
⚠ **§13 is the first measurement against a REAL project — it overturns three conclusions and adds RV-Q10, the only audible defect a human has actually reported. Read it before §12.**
⚠ **§2.3 and §4.1 were corrected 2026-08-29 against measured ffmpeg behaviour — the original text was wrong. See §12.6.**
Written 2026-08-28, after the `retention_fast` camera-vocabulary work, the
three style extensions (word-highlight captions, `archival_montage`, glitch
transitions) and the prompt/planner-coordination fixes all landed and the
user asked "the quality has improved — what else can we do?"

**What this plan is.** The four remaining places where output quality can
still move materially, plus the residual known-open items from the older
plans, in one document with one sequencing decision. It is deliberately
NOT a style plan — no new `render_style`, no new transition, no new preset.
Every previous quality plan added a *treatment*. This one improves the
three layers underneath the treatments (audio, camera geometry, edit
rhythm) and builds the instrument that tells you whether any of it worked.

**Read §0.2 before doing anything.** The starting point is not item 1.

---

## 0. Navigation — read this before writing any code

This plan stands on four existing documents. **Do not re-derive their
findings; read the cited sections first.** Every one of them records a bug
this codebase already paid for once.

| # | Read | Section(s) | Why it matters here |
|---|---|---|---|
| 1 | `docs/plans/motion_new_styles_and_long_form_videos.md` | §7 "Cross-cutting cautions" (whole), §10 Q1–Q10 | §7 is the condensed list of repeated defects — the fingerprint rule above all. Q1–Q10 are the measured answers to this project's hardest questions; several are cited directly below, and **§7's transition-duration caution is an OQ-4 item in this plan**. |
| 2 | same doc | §8 "Where the edge is" | The architectural boundary test: *(shot boundaries from narration) × (per-shot media) × (per-shot camera) × (global look)*. Everything in this plan passes that test on purpose. §8 of this document restates what does not. |
| 3 | same doc | §12 implementation-log entries, and §13–§19 review sections | The house shape for logging work and for reviewing it (dated entry; R-numbered findings; measured, not asserted). |
| 4 | `docs/plans/analysis.md` | Part A / Part B (whole), P1–P6 log entries, RV1–RV11 | The most recent worked example of "measure the audio problem, find the root cause, fix it per-style". **RV11 in particular** — a normalization target shipped as a gain instead of a peak target and made every SFX clip louder. OQ-1 is the same class of work and can fail the same way. |
| 5 | `docs/plans/style_extensions.md` | §2 (whole), §6 (whole) | §2 is the condensed invariant list. §6 is the DB-safety rule, restated in §11 of this document and **binding on this plan too**. |
| 6 | `docs/plans/prompt_fixes.md` | §2.1 | *"A prompt instruction cannot enforce what the caller cannot see."* This is the entire justification for OQ-3 being code and not a prompt edit. |

**Do not start by reading code.** Read items 1–6, then §0.2, §1 and §2 of
this document, then the one feature section you are building, then the code.

### 0.1 Where a subagent picks this up, and how it reports

This plan is written to be executed by more than one agent, in sequence,
across sessions. The pickup protocol:

1. **Find the next unstarted task** by reading §9 (Sequencing) top to bottom
   and stopping at the first row without a ✅ and without a corresponding
   entry in §10 (Implementation log). §9 is the authority on order — not
   this list, and not the section numbering.
2. **Check the gate.** Every task in §9 states a gate — a measurement or a
   prior task that must be complete first. If the gate is unmet, do the
   gate, not the task. Gates here are not ceremony: two of the items are
   *dead* if their gate measurement comes back a certain way, and finding
   that out costs under an hour.
3. **Do exactly one lettered task.** Do not bundle. Do not "while I was in
   there". The review sections of the older plans (§13–§19 of the motion
   doc, RV1–RV11 of `analysis.md`) exist because bundled changes are where
   the R2 fingerprint misses hid.
4. **Write an entry in §10 before finishing**, in the established shape:
   dated heading, **Scope executed**, **Changes** with `file:line`,
   **Measured** (real numbers, not "looks right"), **Verification** (the
   exact test command run), **Effects / notes for the reviewer**, **What is
   NOT done**. Update the ✅ marker in §9 in the same edit.
5. **If a finding contradicts this plan, say so in the log entry and change
   the plan text in the same commit.** Every older plan in this directory
   has corrections written into it by the agent that found them (see the
   motion doc's §13.3, §19.8, and Q6's struck-through original). A plan
   that silently disagrees with the code is worse than no plan. This
   document inherits that rule.
6. **Never mark a task done on unit tests alone** where its own section
   says a human must watch or listen. Say "built, awaiting human pass" and
   stop. §9's ⚠ markers say which ones those are.

### 0.2 ⚠ START HERE — and why it is not item 1

The user's read on this was "do audio and camera, then only human review is
left." That is nearly right, and inverted in one place.

**OQ-0, the measurement harness, comes first — as a thin slice, not a
project.** Not because it improves the video (it does not), but because:

- **OQ-1, OQ-2 and OQ-3 are all calibration work.** A loudness target, a
  crop that lands on the subject, a cut that feels intentional — none of
  those are verified by an assertion. They are verified by a human ear or
  eye, exactly like the punch-in spike (§11 step 0 of the motion doc), the
  Q5 pacing bands, the Q10 parallax evaluation and the glitch variants
  were. This repo's own §9 says it in bold: **"The coding is not the
  bottleneck."**
- **The one thing that has repeatedly gone unmeasured got skipped for
  exactly this reason.** A8, the motion-vs-still bake-off, is still
  unanswered — so motion clips are being paid for at ~50¢/shot with no
  evidence a viewer can tell. It was not skipped because it was hard. It
  was skipped because comparing two renders by hand is tedious and nothing
  made it cheap.
- **Three of OQ-1's four sub-items need a "before" number** (current LUFS,
  current per-scene narration level spread, current narration attenuation
  under music). Taking those measurements *is* most of OQ-0a. Doing OQ-0a
  first costs almost nothing extra and leaves the numbers reusable.

So: **OQ-0a (metrics) → OQ-1 (audio) → OQ-0b (contact sheet) → OQ-2
(camera) → OQ-3 (rhythm), with OQ-4 items dropped in where they block.**
Full order and gates in §9.

**And to answer the question directly: no, human review is not all that is
left after 1 and 2.** After OQ-1, OQ-2 and OQ-3 there remains: this plan's
OQ-0b, the whole of §7 (five code items — a missing render-time validation,
an unmeasured platform limit, a data backfill, LLM cost accounting, and an
unanswered bake-off), and two features parked by explicit user decision
(§1.3). Human review is not the residue. Human review is the *gate on each
step*, and OQ-0 is what makes it affordable.

---

## 1. Origin and scope

### 1.1 What prompted this

A conversation on 2026-08-28. The user's framing: the styles work has
visibly improved output, and they wanted the next tier of improvement
rather than another preset. A pass over the pipeline found that the
*sourcing* layer — the one that looked most likely to be weak — is in fact
the strongest part of the system:

- `app/assets/ranking.py` — explicit weighted ranking, component scores
  logged, reuse decay as a window not a set (C4), quality measured as
  adequacy-for-render rather than raw pixels, corrected after a real
  measured wrong pick.
- `app/assets/relevance.py` — a hard relevance gate ahead of ranking.
- `app/assets/depiction_check.py` — a vision plausibility check, calibrated
  twice against a real fixture (A30 → A30a), with a deliberately asymmetric
  false-accept/false-reject bias and the reasoning written down.

**So "better asset selection" is not the lever.** The four items below are
what is actually left inside the current architecture.

### 1.2 In scope

| # | Feature | One line | Effort | Human pass |
|---|---|---|---|---|
| OQ-0 | **Measurement harness** (a: render metrics report; b: contact sheet) | Turn "watch the whole video" into "read one page, then watch the three flagged shots" | ~1 d (a) + ~1–1.5 d (b) | no |
| OQ-1 | **Audio finishing** (a: loudness; b: speech-accurate ducking; c: narration chain; d: mix safety) | The mix is raw — no loudness target, no level matching between scenes, and the bed is pinned down for whole scenes | ~3–4 d | ⚠ ears |
| OQ-2 | **Subject-aware camera** | Ken Burns and punch-in move toward the geometric centre of the frame, not toward what is in the picture | ~2–3 d | ⚠ eyes |
| OQ-3 | **Edit rhythm** (a: beat-aligned cuts; b: global variance; c: hook & end card) | Things the shot planner structurally cannot do, because it sees one scene and never the whole timeline | ~1 d (a, if its gate passes) + ~1.5 d (b) + ~1–2 d (c) | ⚠ a and c |
| OQ-4 | **Residual known items** — see §7 | Five carried-over items from the older plans, all code, none human review | ~2.5–3 d |  no |

### 1.3 Explicitly OUT of scope

| Item | Why parked | Where it lives |
|---|---|---|
| 2.5D parallax (DepthFlow) | User: "leave parallax for now" (2026-08-25), reaffirmed by omission since. Verdict was already BUILD IT with a 6-step plan written. | motion doc §10/Q10 |
| Re-enabling WHOOSH on `retention_fast` | Needs C3a (rotation across ≥3 clips) + C3b (first-punch-only + min-gap) first, or it reproduces the ~100-events-per-reel bug that got it disabled. User: "leave it". | `analysis.md` decisions 3/5/5a/5b |
| Any new `render_style`, transition, or caption style | §2.8 of the motion doc: "ship three presets, not eight" — there are now four. A fifth is a product decision, not a quality improvement. | motion doc §2.8, `style_extensions.md` §2.4 |
| A live sidechain compressor for music ducking | **Already considered and correctly rejected.** Raised in the 2026-08-28 conversation, then found to be answered in `app/renderer/music.py`'s own docstring on I5 grounds. Recorded so it is not proposed a third time — and see §4.2 for what to do instead. | `app/renderer/music.py:1-9` |
| Motion graphics, animated data-viz, controlled animation, multi-voice, music-as-master-clock | Not incremental — a different pipeline. §8 restates the boundary. | motion doc §8 |

If an agent working from this document finds itself touching `DepthFlow`,
`whoosh_enabled`, `STYLE_GRADES`, `TransitionType`, or adding a value to
`render_style`, it has left this plan's scope. Stop and check.

---

## 2. Lessons carried forward — non-negotiable invariants

Everything here has already caused a real bug in this codebase, or is a
written architectural decision.

### 2.1 The render fingerprint rule (R2 — hit six times and counting)

**Any value that changes render output bytes but is read live at render
time must enter `compute_render_fingerprint`
(`app/renderer/fingerprint.py:155`), or a cache HIT silently serves stale
output.** Read that function in full before adding to it — it documents its
own conventions inline, and two of them bind this plan:

- **Unconditional presence.** Entries are present even on renders where
  they happen not to matter (see the `music_bed_gain_db` comment). Follow
  it; do not add a conditional entry.
- **Assignment, not a bag (R16).** Per-shot data is keyed by `shot_id` in
  timeline order — a flat sorted list cannot tell shot A from shot B. This
  is the exact shape **OQ-2's focal points must use**.

⚠ **`shot_media` hashes only each asset's content hash.** So anything
*derived from* an image by a model — a focal point (OQ-2) — is **not**
transitively covered and needs its own explicit entry. The precedent to
copy is `cue_list_hash`: a derived, model-influenced artifact with its own
hash line. The same applies to OQ-1b's ducking envelope.

**Every task here that touches render bytes must add a test that fails when
its fingerprint entry is removed.** Motion doc §7: *"Assume this will be
forgotten once and add a test that fails when it is."* Model after
`backend/tests/unit/renderer/test_fingerprint.py`.

### 2.2 Determinism (I5) — and what it does *not* forbid

Rendering is a pure function of its inputs. Anything model-based sits
behind a cached provider boundary, never inline in the render path. This is
why `app/renderer/music.py` uses a precomputed static volume envelope
instead of a live compressor, and it is not negotiable.

⚠ **But "deterministic" is not the same as "coarse".** The envelope can be
computed from far better data than it currently uses and stay exactly as
deterministic (§4.2). Do not read I5 as a licence to leave a crude
approximation in place — read it as a constraint on *where* the
intelligence lives (in a precomputed, hashable input), not on how good it
is allowed to be.

### 2.3 D1: narration is the master clock — and its audio corollary

Narration keeps its full true length; picture is fitted to it
(`app/renderer/audio.py:67-80` refuses `-shortest` for this reason, over a
measured ~20 ms). Two consequences:

- **⚠ NEW INVARIANT, and the one most likely to be violated by OQ-1: every
  audio filter added must be duration-preserving.** A filter that adds
  latency, pads, or resamples the narration track by even a few
  milliseconds breaks the picture/audio relationship D1 exists to protect,
  and it presents as progressive drift, not as an obvious bug — the exact
  failure mode `audio.py`'s docstring already documents for MP3
  concatenation (+145 ms over five boundaries, ~36 ms per join). Any
  candidate filter must be **proven** duration-preserving by measurement
  (ffprobe before and after, on a real multi-scene render) before it ships.
  ~~Two-pass/linear `loudnorm` qualifies; single-pass dynamic mode and
  anything involving `atempo` or `apad` do not.~~
  ⚠ **CORRECTED 2026-08-29, measured (§12.6): the linear/dynamic
  distinction is NOT a duration distinction.** Both modes were measured
  sample-exact (0-sample delta, `12.000000 → 12.000000`, six files,
  ffmpeg 9.0). `loudnorm` in either mode is duration-preserving; `atempo`
  and `apad` still are not. The invariant above stands — it is the
  *example* that was wrong. **The real objection to dynamic loudnorm is
  creative, not arithmetic:** it applies time-varying gain to the finished
  mix, i.e. a compressor that partially squashes the bed swells OQ-1b
  exists to create. Reject it on that basis, and detect it (RV-Q6) rather
  than assuming a filter flag enforces it.
- **Shot boundaries are onsets, and they telescope.**
  `app/timeline/narration_fit.py` defines shot *j*'s window as its own
  first character's onset to the *next* shot's first character's onset, so
  `sum(spoken) == total` **by construction**, regardless of pause
  structure. OQ-3a's entire safety argument rests on this (§6.1).

### 2.4 "Resolve once, thread explicitly" (RV2)

A value needed at render time is resolved in one place and passed down
explicitly, never re-derived at the point of use, and never justified with
"it cannot drift" — `analysis.md`'s RV2 records that justification being
false. OQ-1b and OQ-2 both thread new data into the renderer; both must do
it this way.

### 2.5 Camera authorship (canon 3.1)

Camera decisions are written into the Timeline by the planner, never
applied by the renderer from a style alone. `PUNCH_IN` was promoted from a
renderer-only spike to a planner-choosable value for exactly this reason.

⚠ **OQ-2 must not violate this, and how it avoids doing so is a design
decision, not an accident:** a focal point is a property of *the image*,
not of the camera. The same photograph has the same subject under every
style, and the value is *derived*, not authored. So it belongs on the asset
binding, resolved where the image is already being inspected — not on
`Camera` (`app/schemas/timeline.py:168`), which is planner territory.
See §5.2.

### 2.6 Fail loudly vs. correct silently

`analysis.md`'s R13 (`mux_sfx` failing a render in a subsystem whose
contract is "never fail the run") and R18 (the split-screen bottom panel's
failure discarded entirely — no state, no error, no log) are the two poles.
For this plan: **OQ-1's loudness pass must never fail a render** (audio
that cannot be measured plays unnormalized, and says so in the log), while
**OQ-2's focal-point resolution must record its failures** — an image the
vision pass could not read falls back to centre, which is exactly today's
behaviour, so a systematic failure would otherwise be invisible *because
it looks correct*.

### 2.7 Prompt files are `@lru_cache`'d

A prompt edit needs a process restart to take effect. Relevant only if
OQ-3c touches a planner fragment.

---

## 3. OQ-0 — the measurement harness

**Goal.** Make it cheap to answer "did that change help?" and "what is
wrong with this render?" without watching the whole video. This is the
instrument every other item in this plan is calibrated with.

### 3.1 OQ-0a — the render metrics report (~1 d) — **START HERE**

One function over a finished render (timeline + output file) emitting a
JSON blob, plus a CLI wrapper in `backend/scripts/` alongside the existing
`export_test_project.py`. No DB writes, no new tables, no endpoint — a file
next to the render.

What it reports, and why each one earns its place:

| Metric | Why |
|---|---|
| Shot count; shot-duration mean, median, min, max, stddev | The pacing bands (Q5) are stated in these terms and have never been checked against a real render automatically. |
| Camera-movement distribution | The 67%/26%/4%/2% measurement that started the style-extensions plan was taken **by hand**. It should be one command. This is OQ-3b's before/after number. |
| Transition type distribution, **and any transition whose duration ≥ its shot's duration** | ⚠ Motion doc §7: *"I searched and found no validation that a transition's duration is less than its shot's duration"* — still unconfirmed, on a style with a 0.8 s shot floor against a 0.4 s default transition. §7.1 makes the fix a task; **this metric is how you find out whether it is already happening in real renders**, which nobody knows today. |
| Asset reuse: distinct assets / shots, and the minimum gap between reuses | `ranking.py`'s reuse window is a 60 s / 20 s decay; whether it delivers is unverified end to end. |
| Audio: integrated LUFS, true peak, LRA of the final mux | OQ-1a's before/after number, and the single most useful number in the report. |
| Audio: per-scene narration integrated loudness, and the spread across scenes | OQ-1c's before/after number. Levels jump at scene boundaries today and nobody has measured by how much. |
| Silence/gap map: intervals over ~0.5 s with no narration | Feeds OQ-1b (where the bed should swell) and OQ-3a (where the cut slack is). |
| Near-black and frozen-frame detection | Q1's original failure was a motion clip collapsing to one PNG. A cheap regression net for that whole class. |
| Caption cue overflow: cues over the line-length / duration budget | Feature A shipped word highlighting; nothing checks the cues fit. |

**Implementation notes.** `ebur128`, `blackdetect` and `freezedetect` are
ffmpeg filters — one analysis pass, no new dependency, and per
`style_extensions.md` §6.2 rule 3, **ffmpeg is not the database**: running
it is safe. Everything else is arithmetic over the Timeline document. Read
`app/workflow/render_only.py` for how to get a timeline and a rendered file
in hand without driving a full run.

⚠ **This is a read-only reporting tool. It must not write to the DB, must
not mutate a timeline, and must not be wired into the render path.** If it
ever becomes tempting to fail a render on a bad metric, that is a separate
decision and a separate task.

**Shipped shape (P-OQ0a, 2026-08-28).** Entry point
`app.renderer.metrics.build_render_metrics_report` + CLI
`backend/scripts/render_metrics.py`. Stable top-level keys: `shots`,
`camera_movements`, `transitions`, `asset_reuse`, `audio`, `silence_gaps`,
`video_defects`, `caption_overflow` — missing optionals are `null` with an
`unavailable_reason`, never omitted. Shot-duration `stddev` is **sample**
(n−1). Silence gaps come from alignment on the audio-concat clock (scene i
starts at the sum of prior scenes' last `character_end`); reported gaps are
leading silence before the first character and holes between
`character_end`→next `character_start` when duration > 0.5 s — trailing
after the last character is omitted because the concat clock ends there.
One ffmpeg pass covers mux `ebur128` + `blackdetect` + `freezedetect`
(`d=0.5:pix_th=0.10` / `n=0.003:d=2`); open-ended `freeze_start` without
end/duration is closed at container duration from stderr. Frozen and
near-black intervals are annotated with overlapping `shot_id` +
`camera_movement` (D5 start times) so a STATIC still hold is separable
from Q1's collapsed motion clip. `duration_gte_shot` flags a non-cut
transition whose duration is ≥ the outgoing shot **or** the incoming
next shot (xfade overlap is taken from both). `source` records
timeline_id / project_id / version / video_path. ffmpeg/ffprobe
subprocess decoding is UTF-8 with replacement (Windows).

### 3.2 OQ-0b — the contact sheet (~1–1.5 d)

One HTML page (or a single montage image) per render: one thumbnail per
shot at its midpoint, annotated with shot id, duration, camera
movement/direction/intensity, transition in/out, asset provider and whether
it was reused, and the narration line. Frames come from one ffmpeg pass;
the page is a static file.

**Why it is worth a day and a half.** Track C's C5 problem is *"someone
genuinely attempting to review a 200-shot project"* — at 3 s a shot that is
ten minutes of playback to find one bad crop. As a scrollable sheet it is
under a minute, and the bad crop is obvious in a thumbnail. It is also what
makes **OQ-2 reviewable at all** (a focal-point change is a per-shot
framing judgement across every shot) and what makes the **A8 bake-off
finally answerable** (two sheets, side by side, one question).

**Gate:** do OQ-0a first and use it once, for real, on OQ-1's before/after.
If OQ-0a turns out not to get used, OQ-0b will not either, and §9 should be
revisited rather than pushed through.

**Shipped shape (P-OQ0b, 2026-08-28).** Entry point
`app.renderer.contact_sheet.build_contact_sheet(timeline, video_path,
output_html, *, asset_ids=None) -> Path` + CLI
`backend/scripts/render_contact_sheet.py`. Midpoints via
`_shot_midpoints` = `compute_shot_start_times` (D5) + `duration_s/2` —
never a naive duration sum. One JPEG per shot under a sibling folder
(`<video>.contact/` next to `<video>.contact.html`); HTML is a static
CSS grid (no JS) with relative `<img>` hrefs. Each cell: shot id,
rendered midpoint + duration, `movement / direction / intensity`,
`transition_out` type + duration, optional asset identity + reused?,
narration excerpt (~80 chars from `scene.narration_text` sliced by
`shot.narration_span`). Cells whose `transition_out` trips the same
OQ-0a `duration_gte_shot` rule (outgoing or shorter incoming) get CSS
class `cell-flagged`. Frames: per-shot ffmpeg `-ss` before `-i` +
`-frames:v 1` (argument lists, UTF-8 errors=replace) — a modest loop
rather than one select-filter graph, for Windows reliability. Not
imported from the render path; no DB; timeline not mutated.

### 3.3 What OQ-0 is NOT

Not a dashboard, not a UI feature, not an endpoint, not a golden-render
regression suite in CI. A regression suite over these metrics is the
obvious next step and is deliberately deferred until the metrics have been
looked at enough times to know which ones are stable. Do not build the
suite first.

---

## 4. OQ-1 — audio finishing

**Goal.** Perceived production value is disproportionately audio, and this
is the largest unimproved layer in the system. Grepping the whole renderer
for audio filters returns `volume`, `amix`, `afade`, `adelay`, `atempo` —
and nothing else. There is no `loudnorm`, no `ebur128`, no limiter, no
compressor and no EQ anywhere in `app/renderer/`.

⚠ **Read `analysis.md`'s RV11 before starting.** A normalization target
shipped as a gain rather than a peak target and made every SFX clip louder.
Same subsystem, same class of work, same failure mode available.

### 4.1 OQ-1a — a loudness target (~1 d) — the highest payoff per hour in this plan

**Current state.** `mux_narration` (`app/renderer/audio.py:49`) encodes the
concatenated narration to AAC; `mux_music` amixes it with the bed; nothing
measures or normalizes the result. Every render lands wherever ElevenLabs
happened to land that day.

**Why it matters.** Platforms normalize on playback (roughly −14 LUFS for
YouTube, −16 for short-form). Under target and the platform turns the whole
mix up, noise floor included; over target and it clamps. Either way the mix
is being altered after you ship it, by an amount nobody has measured.

**Shape.** A final measure-then-apply pass on the muxed output — two-pass
`loudnorm` with `linear=true`, or measure with `ebur128` and apply a
computed static gain plus a true-peak ceiling around −1 dBTP.

⚠ **Three constraints, all load-bearing:**
1. **Duration-preserving (§2.3).** Prove it by ffprobe before/after on a
   real multi-scene render, and put the numbers in the log entry.
   *(Measured 2026-08-29: satisfied, sample-exact, on both the linear and
   the dynamic path — see §12.6.)*
2. **The measured values are a render input (§2.1).** Recomputed in-pass
   from the same bytes, it is deterministic and rides in free; stored or
   configured, it needs a fingerprint entry. State which one you built and
   why, in the log.
3. **Never fail the render (§2.6).** Unmeasurable audio plays
   unnormalized and logs loudly.

⚠ **Three more, added 2026-08-29 after measuring what ffmpeg actually
does (§12.6). None were anticipated when this section was written:**

4. **`linear=true` is a request, not a guarantee, and ffmpeg is silent
   when it is refused.** Pass 2 must carry `print_format=json` too and log
   the reported `normalization_type`. Do not infer the mode from the flag
   you passed (RV-Q6).
5. **Pin the output sample rate.** Dynamic mode resamples internally to
   192 kHz and lands the AAC track at 96 kHz; linear mode does not
   resample at all. Without `-ar`, the mode silently decides the output
   format (RV-Q7).
6. **A mix measuring ≥ 0 LUFS cannot be normalized at all** —
   `measured_I` is constrained to [−99, 0] and pass 2 aborts. That is
   handled (copy-through), but it must be logged as its own distinct
   condition, because it means the loudest renders are exactly the ones
   that opt out (RV-Q8).

**Open question — human call.** Which target, and one value or per-format
(landscape vs the 9:16 reel)? Do not guess: OQ-0a gives the current number
first, then this is a short listening decision.

**Shipped shape (P-OQ1a, 2026-08-28).** Final pass on the finished mux
(after music and after SFX) via `app/renderer/loudness.py::apply_loudness_target`:
two-pass `loudnorm` with `linear=true`, video `-c:v copy`. Starting
defaults (config, awaiting human listen — **not** an ear-signed target,
and **not** a per-format split): `loudness_target_lufs=-16.0`,
`loudness_true_peak_db=-1.0`, kill switch `loudness_normalize=True`.
Fingerprint keys (R2, unconditional): `loudness_normalize`,
`loudness_target_lufs`, `loudness_true_peak_db`, plus constant
`loudness_lra` (11.0, not a Settings knob — orchestrator review). Measured pass-1 values
are recomputed from the same bytes (deterministic, ride in free) — only
the config targets are hashed. Never fails the render: no audio / missing
JSON / ffmpeg non-zero copies through unnormalized and logs a warning.

### 4.2 OQ-1b — duck on speech, not on scenes (~1–1.5 d) — the most audible single change

**Current state, exactly.** `_volume_chain` (`app/renderer/music.py:182`)
builds one `volume` filter per *speaking interval*, and the module's own
docstring defines that as **per-scene**: each scene's narration is one
continuous interval, and sub-scene pauses are not subdivided. Its stated
reason: *"avoids needing character-level timing data this module has no
access to in the first place (it only ever sees per-scene audio files)."*

**⚠ That reason is now obsolete, and this is the finding that makes OQ-1b
worth doing.** Per-character alignment is stored on the narration row
(`app/models/narration.py:55` — the raw ElevenLabs `/with-timestamps`
object) and is already threaded to the renderer for captions:
`derive_caption_cues` reads `character_start_times_seconds` /
`character_end_times_seconds` directly
(`app/renderer/captions.py:180-181`). The word-highlight caption work
shipped exactly the data `music.py` says it cannot have. **The blocker is a
caller that does not pass it, not missing data** — an RV2-shaped fix
(§2.4).

**Why it is audible.** On `stillness` the bed sits at −22 dB and ducks to
−28 dB. Today it is pinned at −28 for the *entire duration of a scene*,
including every pause. That is why the music reads as absent rather than
quiet: it never gets a moment to be heard. Ducking on real speech windows
lets the bed come back up between lines, which is what a mixed piece sounds
like — and it costs nothing in loudness, spend, or render time.

**Shape.** Derive speaking intervals from the alignment arrays instead of
from scene boundaries, merging gaps below a threshold (a breath is not a
release), and add a short ramp in/out of each duck rather than a step.
Everything stays a precomputed static envelope built from an ordered Python
list — **I5 is untouched** (§2.2), and the deliberate rejection of a live
sidechain compressor stands.

⚠ **Fingerprint (§2.1):** the envelope is now derived from alignment data
rather than from scene structure already in the timeline dump. Add an
explicit `duck_envelope_hash`, following `cue_list_hash`'s precedent.

**Open questions.** The merge threshold and the ramp length are ear
decisions. Start from the values `captions.py` already uses for cue merging
so the two subsystems agree about what a pause is.

**Shipped shape (P-OQ1b, 2026-08-28; detector fix P-OQ1b-char, 2026-08-29).**
Speaking intervals from alignment on the audio-concat clock. A run
splits when a character's **own duration** exceeds `DUCK_CHAR_PAUSE_S`
(**0.30 s**, the §13.4 counting cutoff) — ElevenLabs never leaves an
inter-character gap, so splitting on `next_start - this_end` was inert
(one duck window, 100% of every measured timeline). The pause character
itself is not ducked. When the `characters` array is present, only
whitespace that long counts (a slow phoneme is not a swell).
Inter-character gaps, if they ever appear, still merge below 0.8 s.
⚠ **Plan correction:** §15.1 said keep `DUCK_MERGE_THRESHOLD_S` (0.8 s)
as the split threshold. Every measured pause on F1 is ≤ 0.584 s, so
0.8 s would have left the detector inert. 0.8 s is captions' min cue
duration, the wrong quantity for "this newline is a pause."

**80 ms / 4-step** ramps as extra `between()` windows. `duck_envelope_hash`
includes `char_pause_s`. RV2 unchanged. **Re-listen required** (§13.4).

### 4.3 OQ-1c — the narration chain (~1 d)

**Current state (pre-ship).** Per-scene MP3s were decoded, concatenated and
encoded to AAC with no level matching between scenes. No high-pass, no
compression.

**The measurable defect: scene-boundary level jumps.** Each scene is a
separate TTS call. Levels vary between calls, and the concat filter joins
them at whatever level they arrived at, so the voice can step up or down
mid-video at a scene boundary. Q8 already measured that **voice swings
chars/sec by 36% versus ~8% for language** — if voice varies that much in
timing, it varies in level too, and nothing compensates. OQ-0a's per-scene
loudness spread is the number that sizes this.

**Shape, cheapest first.** Per-scene gain matching to a common target
before the concat (arithmetic, duration-preserving, trivially
deterministic) → then, only if a listening pass says it is needed, a gentle
high-pass around 80 Hz and light compression for consistency.

⚠ **Order matters: gain-match scenes BEFORE the concat, and normalize the
full mix (OQ-1a) AFTER it.** Doing the second without the first hides the
jumps inside a correct integrated number.

**Shipped shape (P-OQ1c, 2026-08-28).** Mean-match only: each measurable
scene gets `gain_db = mean_lufs − scene_lufs` via ffmpeg `volume=`
(linear from dB) into a temp wav under the mux work dir, **before** the
existing concat FILTER (still decoded PCM — D1 unchanged). Flag
`narration_level_match` (default True) + fingerprint key of the same
name; measured LUFS are **not** hashed (derive from narration bytes).
Unmeasurable scenes stay unadjusted; never fails the render. **No**
high-pass or compressor (listening pass has not asked). ebur128 parsing
lives in `app/renderer/ebur128.py` so mux_narration does not import
`metrics.build_render_metrics_report` (orchestrator review of P-OQ1c).

### 4.4 OQ-1d — mix safety (~0.5 d, measurement first)

**CONFIRMED and fixed (P-OQ1d, 2026-08-28).** Experiment A measured
narration-only vs `mux_music` with a −60 dB near-silent bed: integrated
LUFS **−22.2 → −28.2** (Δ **−6.0 dB**), mean_volume the same. Root cause
was ffmpeg `amix` default `normalize=1` (scale by 1/n). Fix matches SFX:
`amix=...:normalize=0`. Fingerprint key **`music_amix_normalize`**
(unconditional int, `0` after the fix). After fix, Δ LUFS = **0.0 dB**;
audio/video durations unchanged at 4.0 s. No compressor, no ducking or
loudnorm change.

---

## 5. OQ-2 — subject-aware camera

**Goal.** Make Ken Burns and punch-in move toward what is in the picture.

### 5.1 Current state, exactly

`Camera` (`app/schemas/timeline.py:168`) is `movement` + `direction` +
`intensity`. **There is no focal point anywhere in the schema.**
`build_zoompan_expression` (`app/renderer/ken_burns.py:78`) and
`build_punch_in_expression` (`:166`) derive geometry from movement,
direction and intensity alone, over a 1.6× working canvas
(`WORKING_CANVAS_SCALE`, `:63`).

So a punch-in on an archival photograph pushes toward the **geometric
centre**, whatever happens to be there. And the framing problem is not
hypothetical: §19.8 of the motion doc measured this project's real archival
pool at **11 portrait to 3 landscape**, against two landscape styles — so
most stills are already being cropped by a rule with no knowledge of their
content, and §19.12 closes by calling that *"the largest open question in
the plan"*, needing a render watched.

**OQ-2 is the answer to that open question**, not a separate feature: a
crop and a push that know where the subject is dissolve most of the
portrait-into-landscape problem, and what remains is a taste decision
rather than a geometry accident.

### 5.2 Design — DECIDED: focal point is an asset property, not a camera property

Per §2.5, `Camera` is planner-authored and canon 3.1 keeps it that way. A
focal point is neither authored nor style-dependent: **the same image has
the same subject under every style**, and the value is derived from pixels.
So it lives with the asset binding, resolved once where the image is
already being opened and inspected, and threaded explicitly to the renderer
(§2.4). The planner contract does not change at all.

**Where the value comes from — cheapest viable first.**
`depiction_check.py` already sends every searched asset to a vision model
and already has a calibrated instinct for what such a model can and cannot
answer. "Where in this frame is the main subject" is squarely a *visible,
checkable* question of the kind A30a concluded these models answer well —
unlike the specific-identity question A30 wrongly asked. Adding it to a
call that already happens is close to free. A classical saliency/face
heuristic is the fallback if that proves unreliable; do not build both.

⚠ **Fingerprint (§2.1):** focal points are model-derived, so `shot_media`'s
asset content hash does **not** cover them. Add an explicit per-shot entry
in the **R16 assignment shape** — keyed by `shot_id` in timeline order,
empty for a shot with no focal point, so a later resolve cannot cache-HIT
the gap.

⚠ **Failure must leave a trace (§2.6).** Fall back to centre — which is
exactly today's behaviour, so a systematic failure would be invisible
precisely because it looks correct. Record the fallback.

### 5.3 What NOT to change

- **Do not touch `_MAX_ZOOM_DELTA`, `_MAX_PAN_ZOOM_DELTA` or
  `_MAX_PUNCH_ZOOM_DELTA`** (`ken_burns.py:54`, `:58`, `:144`). Those are
  tuned restraint values with a written rationale ("documentary motion, not
  a music-video zoom"), and one was verified pixel-correct against a real
  archival photo and watched by a human. OQ-2 changes *where* the motion is
  aimed, never how much of it there is.
- **Do not change the zoompan single-decoded-frame contract.** The module
  docstring's jitter explanation is why it is written that way.
- **`STATIC` and `SPLIT_FRAME` stay out of it** — the first has nothing to
  animate, the second is a separate composite path
  (`app/renderer/split_screen.py`).
- **Do not add a focal point to `Camera`** — see §5.2.

### 5.4 ⚠ This one cannot be signed off by tests

Unit tests can prove the expression aims where it was told to. Only a human
looking at a contact sheet can say whether it aims at the right thing. That
is why OQ-2 sits after OQ-0b in §9, and why its log entry should say
"built, awaiting human pass" until someone has actually looked.

### 5.5 Shipped shape (2026-08-28)

| Piece | Where |
|---|---|
| Storage | JSON sidecar `{assets_dir}/{content_hash}.focal.json` — **no DB migration**, not on `Camera` / Timeline Shot |
| Vision hook | `DepictionVerdict.focal_x` / `focal_y` (default 0.5); prompt asks for subject location on the existing `check_depiction` call; `persist_vision_focal` after a non-reject in `resolve_assets` |
| Fallback logging | `focal.fallback` warning when sidecar missing / no content hash / invalid vision coords (§2.6) |
| Fingerprint key | `shot_focal`: `[{shot_id, focal}]` in timeline order; `""` when unresolved; also hashed into run + shot-stream caches |
| Movements | `SLOW_ZOOM`, `SLOW_PUSH`, `PULL_BACK`, `PUNCH_IN` only — PAN x untouched; STATIC / SPLIT_FRAME out |
| Threading (RV2) | `resolve_shot_focals` once in `render_video` → fingerprint + `render_timeline(..., shot_focals=)` → ken_burns |
| Pre-zoompan crop (RV-Q1, 2026-08-29) | `compute_aimed_crop` aims `crop=cw:ch:x:y` at the original-image focal; zoompan consumes the **residual** in crop space. Centre/None focals keep today's centred `crop=w:h` + centre zoompan strings. |

---

## 6. OQ-3 — edit rhythm

**Goal.** The three things the shot planner structurally cannot do, because
it sees one scene and never the finished timeline — `prompt_fixes.md` §2.1:
*"A prompt instruction cannot enforce what the caller cannot see."* All
three are deterministic passes over a completed shot list, in the shape of
`app/planners/repair.py`.

### 6.1 OQ-3a — beat-aligned cuts (~1 d **if the gate passes**)

**Why it is available at all.** Real BPM is already sourced and used —
`candidate.bpm` and `target_bpm_for_mean_shot_duration`
(`app/assets/music_ranking.py:106`), with tempo-fit ranking shipped
2026-08-20. The data exists; nothing uses it after selection.

**Why it is safe** — and this argument is the whole feature.
`narration_fit.py` defines a shot boundary as the *onset of the next shot's
first character*, and the sum of shot durations telescopes to the scene's
real narrated total **by construction**. So nudging a picture cut inside
the pause between two lines is a **zero-sum redistribution of duration
between two adjacent shots**: the telescoping identity holds, the total is
unchanged, no narration audio moves, and **D1 is untouched** — narration is
still the clock; the picture is only using slack that already exists.

**⚠ GATE, and it can kill the feature: measure the real pause distribution
first.** If inter-line pauses on the `58f0a5e6` fixture are near zero,
there is no slack and OQ-3a is dead — say so and move on. This is one query
against alignment data, or one field in OQ-0a's silence map. **Do not build
first.** Q3, Q5, Q8 and Q10 were all answered this way, and Q6 turned out
to be asking about a collision that did not exist.

If the gate passes: snap boundaries to the nearest beat within the
available slack, and prefer placing a transition or glitch on a beat rather
than wherever the boundary fell. Bounded, deterministic, fingerprinted.

### 6.2 OQ-3b — global variance constraints (~1.5 d)

The measured 67% `punch_in` is not a prompt failure — it is a visibility
failure. A pass over the finished shot list can enforce what no single
planner call can see:

- cap any one movement's share of the timeline;
- no two same-direction pans adjacent;
- break runs of near-identical shot durations.

⚠ **Two hard rules.** (1) Adjust, never invent: only ever swap to a
movement the style's own fragment permits, or the pass will emit camera
values a style forbids — `style_extensions.md` §2.6's "camera vocabulary
must reference values that actually exist", one level up. (2) `SPLIT_FRAME`
is not interchangeable with the others — it needs a second bound asset.
Skip it.

OQ-0a's distribution metric is the before/after number, and the target
distribution is a taste call to be made *after* seeing one adjusted render,
not specified up front.

### 6.3 OQ-3c — the hook and the end card (~1–2 d)

Nothing in the pipeline treats the opening differently from shot 40, and
for short-form the first three seconds are most of the outcome. Pre-flight
measures the script; it never shapes its opening. Similarly there is no end
card or CTA, and long-form has no chapter cards — text cards exist and
could carry them (`style_extensions.md` §4.4: reuse, don't rebuild).

⚠ **This is the one item in this plan that is partly a product decision,
not an engineering one**, and it is last for that reason. It also runs
closest to §2.8's restraint principle. Bring one concrete proposal to the
user before building; do not scope it from this document alone.

---

## 7. OQ-4 — residual known items (all code, none of it human review)

Carried over from the older plans, still open, small, and each one blocks
or endangers something above.

| # | Item | Source | Why it still matters | Est. |
|---|---|---|---|---|
| 7.1 | **No validation that a transition's duration < its shot's duration.** `retention_fast` has a 0.8 s shot floor against a 0.4 s default transition, and D5 makes transitions *overlap*. | motion doc §7 (⚠ "a check that appears to be absent") | The style itself mitigates it (fast-cut is cuts-only), but nothing structurally prevents a planner emitting a dissolve on a short shot. OQ-0a's report tells you whether it is already happening; then add the validation. | ~0.5 d |
| 7.2 | **Q3's remainder: the argv-length ceiling on the real Linux target is unmeasured.** A Windows-specific crash was bracketed at ~85–90 dissolve-joined shots. | motion doc §10/Q3 | It gates long-form, which is otherwise complete. The plan's own estimate: 20 minutes in a container. | ~0.5 d |
| 7.3 | **Backfill pre-§19 timelines carrying `resolution = (1080, 1920)`.** | motion doc §19.11 residual 2 | The frontend computes warnings against 2.25× the real target area for every project created before §19. The schema default is fixed; existing rows are not. | ~0.5 d |
| 7.4 | **LLM calls are never costed.** | Backlog, cited in motion doc §7 | Every plan has made planning fan out further (long-form, hierarchical planning, rewrites, vision checks). Nobody can currently answer what a run costs — and OQ-2 adds a vision question to every asset. | ~1 d |
| 7.5 | **A8, the motion-vs-still bake-off, is still unanswered.** | motion doc §1/A8 | Motion is ~50¢/shot with no evidence a viewer prefers it. Not a build task — it becomes nearly free once OQ-0b exists (two contact sheets, one question), which is the main reason OQ-0b is in this plan. | ~0.5 d after OQ-0b |

---

## 8. The ceiling — what no item in this plan moves

Restated from motion doc §8 so it is not rediscovered as a disappointment:
motion graphics and explainer animation, animated data visualisation,
controlled animation (a specific arrow along a specific path, lip-sync),
talking head, multi-voice interview, screen recording — and anything where
**music, not narration, is the master clock** (music videos, beat-driven
montage), which is out by the D1 decision rather than by a missing feature.

**The test for any future request:** if it is *(shot boundaries derived
from narration) × (per-shot media) × (per-shot camera) × (global look)*, it
fits this architecture. Everything in §3–§7 fits deliberately. Anything
that does not is a new pipeline, not a preset.

---

## 9. Sequencing — the authority on what to do next

Mark ✅ as each completes, and add the matching §10 entry in the same edit.

| Order | Task | Gate | Human pass |
|---|---|---|---|
| 1 | **OQ-0a** ✅ — metrics report (§3.1) | none — **this is the entry point** | no |
| 2 | **OQ-1d** ✅ — measure the `amix` question (§4.4) | OQ-0a | no |
| 3 | **OQ-1a** ✅ **DONE, ear-confirmed 2026-08-29 (§13.2)** — loudness target (§4.1) | OQ-0a's before numbers | ⚠ listen |
| 4 | **OQ-1c** ⚠ built, awaiting listen — per-scene gain matching (§4.3) | OQ-0a's per-scene spread | ⚠ listen |
| 5 | **OQ-1b** ✅ **DONE — detector fixed (P-OQ1b-char) and depth ear-signed at 8 dB (P-OQ1b-depth)** — speech-accurate ducking (§4.2 / §15.1) | OQ-1a and OQ-1c settled, so the bed is judged against a stable voice level | ⚠ listen |
| 6 | **OQ-4.1** ✅ **measured corpus-wide, 0 violations (§13.6)** — transition-vs-shot validation (§7.1) | OQ-0a's report says whether it is already occurring | no |
| 7 | **OQ-0b** ✅ — contact sheet (§3.2) | OQ-0a used in anger at least once | no |
| 8 | **OQ-2** ⚠ **re-cut 2026-08-29 (§14) — focal now its own call on `gpt-5.5`; re-backfill then watch** — subject-aware camera (§5) | OQ-0b, plus `backfill_focal.py --apply` | ⚠ watch |
| 9 | **OQ-4.5** — the A8 bake-off, finally (§7.5) | OQ-0b | ⚠ watch |
| 10 | **OQ-3a gate measurement** — pause distribution (§6.1) | none; may be done any time, and may kill OQ-3a | no |
| 11 | **OQ-3a** — beat-aligned cuts | its gate passing | ⚠ watch |
| 12 | **OQ-3b** — global variance (§6.2) | OQ-0a's distribution metric | ⚠ watch |
| 13 | **OQ-4.2, 4.3, 4.4** — Linux ceiling, backfill, cost | independent; slot into any gap | no |
| 14 | **OQ-3c** — hook and end card (§6.3) | a product conversation with the user first | ⚠ watch |

⚠ **READ §12 BEFORE PICKING UP THE NEXT ROW (added 2026-08-29).** The
review of the seven built tasks found one blocking defect and eight
smaller ones. **§12.7's order takes precedence over this table** until its
items are closed — in particular, row 8's human watch is not worth doing
until RV-Q1 and RV-Q4 are fixed (it would produce a null result and read
as "the feature doesn't help"), and rows 3–5's listens should wait on
RV-Q3.

**Do not parallelize OQ-1a/1b/1c/1d.** All four touch the same two-pass mux
graph and the same fingerprint function; four agents editing that graph
concurrently is how R2 gets missed a seventh time. One line of reasoning,
in order.

**OQ-2 may run in parallel with the OQ-1 chain** — different subsystem,
different fingerprint entries, no shared files — provided OQ-0b is done.

---

## 10. Implementation log

Append one entry per completed task, newest last, in this shape (the shape
used by `analysis.md` P1–P6 and the motion doc §12):

```
### P-OQ<task> — <title> (YYYY-MM-DD)

**Scope executed:** which lettered task, and what was deliberately left.
**Changes:** file:line for each, with the reason, not just the edit.
**Measured:** real numbers, before and after. Not "sounds better".
**Verification:** the exact command run (see §11 — no full suite, no
  PYTEST_TRUNCATE_DB).
**Effects / notes for the reviewer:** what a reviewer should be
  suspicious of.
**What is NOT done:** the residue, so the next agent does not assume it.
```

### P-OQ0a — metrics report (2026-08-28)

**Scope executed:** OQ-0a only — library + CLI + unit/ffmpeg tests. No
OQ-0b, no audio finishing, no fingerprint/render-path wiring, no DB, no
endpoint.

**Changes:**
- `backend/app/renderer/metrics.py:1-6` — module docstring locks
  read-only / not-on-render-path / ffmpeg-analysis-only.
- `backend/app/renderer/metrics.py:63` — `build_render_metrics_report`
  public API; stable key set with null + `unavailable_reason` for
  missing optionals.
- `backend/app/renderer/metrics.py:120-173` — shot duration stats (sample
  stddev, line 138), camera-movement counts/shares for every
  `CameraMovement`, transition counts for every `TransitionType` plus
  `duration_gte_shot`.
- `backend/app/renderer/metrics.py:176` — asset reuse via
  `compute_shot_start_times` (D5 overlap; dissolves not naive-summed).
- `backend/app/renderer/metrics.py:264` — single ffmpeg analysis pass
  for mux loudness + black/freeze.
- `backend/app/renderer/metrics.py:314` — silence gaps from alignment
  (leading + inter-character > 0.5 s; no trailing).
- `backend/app/renderer/metrics.py:382` — caption overflow against
  `MAX_CHARS_PER_CUE` / `MAX_CUE_DURATION_S` from `captions.py` (no
  `derive_caption_cues`).
- `backend/app/renderer/metrics.py:553-579` — tolerant ebur128 /
  blackdetect / freezedetect stderr parsers (Peak vs True peak;
  open-ended freeze closed at container duration).
- `backend/scripts/render_metrics.py:51` — CLI; default output
  `<video>.metrics.json` or `<timeline>.metrics.json`.
- `backend/tests/unit/renderer/test_metrics.py` — arithmetic + parser
  fixtures + lavfi ffmpeg cases (skip if binary missing).
- This plan: §3.1 shipped-shape paragraph; §9 row 1 ✅; status line
  updated (was "Design-only, nothing built").

**Measured:**
- Fabricated 4-shot timeline (durations 1/2/3/4): mean=2.5, median=2.5,
  min=1.0, max=4.0, sample stddev≈1.291; static share=0.5; asset reuse
  of the same identity on a 3.0 s shot dissolve-0.4 into the next →
  `min_reuse_gap_s`=**2.6** (naive sum would be 3.0). Reviewer correction:
  the first draft of this entry wrote 0.6 / 1.0 s — that was the start
  time of a 1.0 s dissolve-joined shot, not this test's reuse gap.
- Real mux `storage/b0969377-ebea-4b74-82ed-b6139d7f2511/renders/final.mp4`
  (ffmpeg 9.0 Summary block, `I: -26.2 LUFS` / `Peak: -8.0 dBFS`):
  integrated LUFS **−26.2**, true peak **−8.0 dB**, LRA **2.5 LU**;
  near_black=0; frozen=5 (first segment start=0.0 end≈2.57 s). Mux is
  ~12 LU under a typical −14 LUFS platform target — OQ-1a's before number.
- Synth lavfi testsrc+sine (~2 s): ebur128 parse returns a finite
  `integrated_lufs` (asserted in test, not pinned to a LUFS target).

**Verification:**
```
cd backend
python -m pytest tests/unit/renderer/test_metrics.py --noconftest -q
```
Orchestrator re-ran after review fixes: 16 passed. `ruff check` clean on
the three Python files.

**Effects / notes for the reviewer:**
- Report never raises on ffmpeg failure — leaves null + reason.
- Must not be imported from `slideshow.py` / audio / music / fingerprint
  / workflow steps.
- Freezedetect `d=2` flags any hold ≥2 s, including intended STATIC
  stills. Intervals carry overlapping `shots[]` so Q1 is "frozen on a
  non-static / motion shot", not "frozen exists".
- Per-scene narration LUFS needs `--narration` files; mux LUFS alone is
  contaminated by music for OQ-1c's before number.
- Orchestrator review (same day) added: `source` block; defect shot
  annotation; `duration_gte_shot` also vs the incoming shot; UTF-8
  subprocess decoding. Plan §3.1 shipped-shape updated to match.

**What is NOT done:** OQ-0b contact sheet; OQ-1a/b/c/d; wiring into
render; DB/endpoint/dashboard; golden-metric CI suite; analysing a full
project timeline JSON with real alignment/cues (CLI was probed with a
minimal Timeline + real `final.mp4` only).

### P-OQ1d — mix safety / amix normalize (2026-08-28)

**Scope executed:** OQ-1d only — measure first, then `normalize=0` +
fingerprint. No OQ-1a/1b/1c, no loudnorm, no ducking change, no
compressor, no gain matching.

**Changes:**
- `backend/app/renderer/music.py` — `mux_music` amix line now
  `amix=inputs=2:duration=longest:dropout_transition=0:normalize=0`
  (matches `mux_sfx`).
- `backend/app/renderer/fingerprint.py` — new unconditional payload /
  kwarg `music_amix_normalize: int`.
- `backend/app/workflow/steps/render.py` — resolve `music_amix_normalize = 0`
  once beside `music_gains`; thread into **both** the fingerprint and
  `mux_music(..., amix_normalize=)` (RV2 — orchestrator review: the first
  draft hashed the constant but hard-coded the filter).
- `backend/tests/unit/renderer/test_fingerprint.py` — `_fingerprint`
  default kwargs; tests that 0 vs 1 changes the hash and that
  `inspect.getsource` still contains `"music_amix_normalize"`.
- `backend/tests/integration/test_render_music_mix.py` — real-ffmpeg
  narration-only vs silent-bed: `|Δ mean_volume| < 1.5`; duration still
  covers video.
- `backend/scripts/c8_probe.py` — added missing `music_gain_offset_db`
  and new `music_amix_normalize=0` so the probe still compiles.
- This plan: §4.4 outcome sentence; §9 row 2 ✅; status line.

**Measured:**
- **Experiment A (before fix, real `mux_music`):** narration-only
  integrated LUFS **−22.2**, mean_volume **−21.5 dB**; narration +
  −60 dB near-silent bed (bed=−6 / duck=−20): LUFS **−28.2**,
  mean_volume **−27.5 dB**; **Δ = −6.0 dB**. Audio and video durations
  both **4.0 s** on narr-only and mixed. **CONFIRMED** (|Δ| > 3 dB).
- **Experiment A (after `normalize=0`):** LUFS **−22.2 → −22.2**
  (Δ **0.0 dB**); mean_volume **−21.5 → −21.5** (Δ **0.0 dB**);
  durations still **4.0 s** audio / **4.0 s** video.
- **Experiment B (direct ffmpeg, unequal short quiet + long loud):**
  default normalize: overlap mean **−27.1 dB**, after dropout **−23.0 dB**,
  jump **+4.1 dB** (approaches +6 as the short input → silence).
  `normalize=0`: overlap = after = **−21.1 dB**, jump **0.0 dB**
  (matches long-alone). Identical coherent sines under default normalize
  show no jump (half+half = full) — logged so nobody expects that case
  to demonstrate the discontinuity.

**Verification:**
```
cd backend
C:\director-project\video-generation-engine\.venv\Scripts\python.exe -m pytest tests/unit/renderer/test_fingerprint.py tests/integration/test_render_music_mix.py --noconftest -q
```
(plus ruff on touched Python files).

**Effects / notes for the reviewer:**
- Pre-fix cached renders with music will MISS (fingerprint key new /
  value differs from absent). Correct and harmless.
- Narration in music-on renders will be ~6 dB louder than before this
  fix; OQ-1a's loudness target must be judged against post-fix mixes.
- Ducking envelope and bed/duck gains are unchanged — only the amix
  scale factor.

**What is NOT done:** OQ-1a loudness target; OQ-1b speech-accurate
ducking; OQ-1c per-scene narration gain matching; any live compressor;
loudnorm.

### P-OQ1a — loudness target (2026-08-28)

**Scope executed:** OQ-1a only — final two-pass linear loudnorm on the
finished mux (after music + SFX). No OQ-1b ducking change, no OQ-1c
per-scene gain matching, no per-format LUFS split, no ear sign-off.

**Target decision (starting default, not an ear-signed target):**
**−16 LUFS** integrated / **−1.0 dBTP** true-peak ceiling — typical
short-form starting point. One config default only; do not invent a
per-format split until a human listen says otherwise.

**Changes:**
- `backend/app/renderer/loudness.py` — new module;
  `parse_loudnorm_measurement`, `apply_loudness_target`. Pass 1
  `print_format=json` → parse `input_*` / `target_offset`; pass 2
  `measured_*=…:linear=true` with `-c:v copy`. Never calls
  `run_ffmpeg` (would raise PermanentError). No-audio / missing JSON /
  ffmpeg non-zero → warning + byte copy-through.
- `backend/app/core/config.py` — Rendering:
  `loudness_normalize=True`, `loudness_target_lufs=-16.0`,
  `loudness_true_peak_db=-1.0` (comments mark awaiting listen).
- `backend/app/workflow/steps/render.py` — resolve the three knobs once
  beside `music_gains`; fingerprint + `apply_loudness_target` share
  them (RV2). Pre-loudness staged in `work_dir` when normalize is on
  (same staging rule as `pre_sfx`).
- `backend/app/renderer/fingerprint.py` — unconditional keys
  `loudness_normalize`, `loudness_target_lufs`, `loudness_true_peak_db`,
  and constant `loudness_lra` (orchestrator review: a loudnorm LRA
  change must miss cache, same shape as `split_panel_fit`).
  Measured pass-1 values are **not** hashed (recomputed from bytes;
  deterministic; ride in free — §4.1 constraint 2).
- `backend/tests/unit/renderer/test_fingerprint.py` —
  `_fingerprint` kwargs + hash-change + `inspect.getsource` key check.
- `backend/tests/unit/renderer/test_loudness.py` — parser fixture;
  no-audio copy-through; real-ffmpeg 4 s + two-scene concat duration /
  LUFS proofs.
- `backend/scripts/c8_probe.py` — three new fingerprint kwargs.
- This plan: §4.1 Shipped shape; §9 row 3 ⚠ built, awaiting listen;
  status line.

**Measured** (synth, real ffmpeg, volume=+8 dB sine+video):
- **4 s single:** before integrated LUFS **−13.80**, audio/video
  **4.000000 s**; after LUFS **−15.90**, audio/video **4.000000 s**;
  Δ duration **+0.000000 s** (well inside ±20 ms).
- **Two-scene concat** (2 s + 2 s sines joined, then loudnorm): before
  LUFS **−13.70**, audio/video **4.000000 s**; after LUFS **−16.00**,
  audio/video **4.000000 s**; Δ duration **+0.000000 s**.
- Both after values within ±1.5 LU of −16. §2.3 duration-preserving
  proof satisfied on a multi-scene mux.

**Verification:**
```
cd backend
C:\director-project\video-generation-engine\.venv\Scripts\python.exe -m pytest tests/unit/renderer/test_loudness.py tests/unit/renderer/test_fingerprint.py --noconftest -q
```
→ **55 passed**. Ruff clean on touched application/test files
(`c8_probe.py` still has a pre-existing I001 import-sort warning
unrelated to this change).

**Effects / notes for the reviewer:**
- Pre-OQ-1a cached renders MISS (three new fingerprint keys). Correct.
- Post-OQ-1d music-on mixes will now be pulled toward −16 LUFS; judge
  ears against that, not the old −26 LUFS pre-1d world.
- Kill switch: `loudness_normalize=false` skips the pass but the three
  keys remain in the fingerprint.

**What is NOT done:** OQ-1b speech-accurate ducking; OQ-1c per-scene
narration gain matching; per-format LUFS targets; human listen /
ear sign-off on the −16 / −1.0 starting default.

### P-OQ1c — per-scene narration gain matching (2026-08-28)

**Scope executed:** OQ-1c only — mean-of-measurable integrated-LUFS gain
match on per-scene narration **before** concat. No high-pass, no
compressor, no OQ-1b ducking, no loudnorm / amix / ken_burns changes,
no ear sign-off.

**Changes:**
- `backend/app/renderer/audio.py` — `measure_integrated_lufs`,
  `gain_match_narration_scenes`, `mux_narration(..., level_match=)`.
  Match target is the mean of measurable scenes (not −16). Temp PCM
  wavs in `output_path.parent`; concat FILTER unchanged. Unmeasurable
  → warning + leave that scene; none measurable → concat as today.
- `backend/app/core/config.py` — Rendering: `narration_level_match=True`
  (OQ-1c comment).
- `backend/app/workflow/steps/render.py` — resolve flag once; pass the
  same value to fingerprint and `mux_narration` (RV2).
- `backend/app/renderer/fingerprint.py` — unconditional
  `narration_level_match: bool` (R2). Per-scene gains ride in free via
  `narration_content_hashes` — do not hash measured LUFS.
- `backend/tests/unit/renderer/test_fingerprint.py` — kwargs + toggle +
  `inspect.getsource` key check.
- `backend/tests/unit/renderer/test_audio_level_match.py` — unequal-sine
  spread < 1.5 LU; mux duration within 20 ms; flag-off skips temps;
  unmeasurable does not raise.
- `backend/scripts/c8_probe.py` — new fingerprint kwarg.
- This plan: §4.3 Shipped shape; §9 row 4 ⚠ built, awaiting listen;
  status line.

**Measured** (real ffmpeg ebur128 on
`tests/fixtures/hinglish_final_project_media/narration/*.mp3`, 6 files):

| Scene file (prefix) | Before I (LUFS) | After I (LUFS) |
|---|---|---|
| 23788387… | −20.1 | −19.9 |
| 2b3542e1… | −19.7 | −19.8 |
| 45566a04… | −19.3 | −19.8 |
| 74f33484… | −21.3 | −19.8 |
| 832d932d… | −20.3 | −19.9 |
| e8096a27… | −18.3 | −19.8 |

- **Before spread (max−min): 3.0 LU** (mean −19.83).
- **After spread: 0.1 LU** (mean −19.83) — well under the ~1.5 LU test
  band.
- **Sum of per-scene decoded durations:** 48.715465 s before and after
  matching (Δ **0.000000 s**). Synth two-scene mux (1.013 s + 0.877 s
  at 0 dB / −6 dB) also preserves concat duration within 20 ms
  (pytest).

**Verification:**
```
cd backend
C:\director-project\video-generation-engine\.venv\Scripts\python.exe -m pytest tests/unit/renderer/test_fingerprint.py tests/integration/test_narration_audio_concat.py tests/unit/renderer/test_audio_level_match.py --noconftest -q
```
→ **59 passed**.

**Effects / notes for the reviewer:**
- Pre-OQ-1c cached renders MISS (`narration_level_match` key). Correct.
- Kill switch: `narration_level_match=false` skips matching; key stays
  in the fingerprint.
- Judge ears on scene-boundary voice continuity against a post-1a
  loudnorm mix — matching alone does not retarget the finished file
  to −16.

**What is NOT done:** OQ-1b speech-accurate ducking; high-pass /
compressor (only if a listening pass says needed — it has not); human
listen / ear sign-off on OQ-1c (and OQ-1a).

### P-OQ1b — speech-accurate ducking (2026-08-28)

**Scope executed:** OQ-1b only — duck on alignment speech windows, not
per-scene file durations. No loudnorm change (OQ-1a), no per-scene
mean-match change (OQ-1c), no amix normalize change (OQ-1d), no
ken_burns, no OQ-0b, no live sidechain compressor (I5 stands).

**Changes:**
- `backend/app/renderer/music.py` — `speaking_intervals_from_alignment`
  (concat clock = sum of prior scenes' last `character_end`; merge ≤
  `DUCK_MERGE_THRESHOLD_S` = `MIN_CUE_DURATION_S` 0.8 s; leading/trailing
  scene silence not ducked; malformed scene skipped + logged);
  `duck_ramp_windows` (4 steps / 80 ms, logged as ear default);
  `duck_envelope_content_hash`; `_volume_chain` emits stepped relative
  windows; `mux_music(..., alignment_by_scene=)` uses speaking intervals
  when provided else `compute_narration_intervals`. Module docstring
  updated (per-scene-only claim obsolete).
- `backend/app/workflow/steps/render.py` — resolve `alignment_by_scene`
  once; derive intervals + `duck_envelope_hash` before cache check;
  pass the same list to fingerprint and `mux_music` (RV2).
- `backend/app/renderer/fingerprint.py` — unconditional
  `duck_envelope_hash: str | None` (R2). Absent alignment → `None`
  (fallback covered by `narration_content_hashes`).
- `backend/scripts/c8_probe.py` — new fingerprint kwarg.
- `backend/tests/unit/renderer/test_music.py` — merge/split, concat
  clock, ramp step times, envelope hash.
- `backend/tests/unit/renderer/test_fingerprint.py` — hash change +
  `inspect.getsource` contains `"duck_envelope_hash"`.
- `backend/tests/integration/test_render_music_mix.py` — gap-between-
  ducks louder than duck; `_mean_volume_db` seeks with `-ss` before `-i`
  (ffmpeg 9 + post-input `-ss` was mis-measuring mid-timeline windows).
- This plan: §4.2 Shipped shape; §9 row 5 ⚠ built, awaiting listen;
  status line.

**Measured** (synth sine bed, real ffmpeg, bed −6 dB / duck −20 dB,
intervals `[1.5,2.5]` + `[3.7,4.7]` = 1.2 s gap; `_mean_volume_db`
0.4 s windows):

| Region | mean_volume (dB) |
|---|---|
| duck_a @1.8 | **−41.5** |
| gap @2.85 | **−27.5** |
| duck_b @4.0 | **−41.5** |

- **gap − duck_a = 14.0 dB**; **gap − duck_b = 14.0 dB** (matches the
  configured 14 dB bed/duck depth). Bed recovers in the pause.

**Verification:**
```
cd backend
C:\director-project\video-generation-engine\.venv\Scripts\python.exe -m pytest tests/unit/renderer/test_fingerprint.py tests/unit/renderer/test_music.py tests/integration/test_render_music_mix.py --noconftest -q
```
→ **73 passed**. Ruff clean on touched files (`--line-length 100`).

**Effects / notes for the reviewer:**
- Pre-OQ-1b cached music renders MISS (`duck_envelope_hash` key). Correct.
- On `stillness` (−22 / −28) the bed should become audible between lines;
  judge ears against post-1a loudnorm mixes.
- When alignment is missing, behaviour is unchanged (file-duration
  intervals) and the fingerprint stores `None` for the envelope hash.
- Orchestrator review: touching speech runs across a scene join merge
  into one window (avoids overlapping ramp filters compounding the
  relative duck); alignment that yields zero windows falls back to
  file-duration intervals rather than leaving the bed unducked.

**What is NOT done:** ear sign-off on merge 0.8 s / ramp 80 ms; OQ-0b
contact sheet; OQ-2 subject-aware camera; live sidechain compressor
(rejected, I5).

### P-OQ0b — contact sheet (2026-08-28)

**Scope executed:** OQ-0b only — library + CLI + unit/ffmpeg tests. No
OQ-2, no A8 bake-off, no dashboard/endpoint, no render-path wiring, no
DB, no loudness/ducking/amix changes.

**Changes:**
- `backend/app/renderer/contact_sheet.py:1-6` — module docstring locks
  read-only / not-on-render-path / no DB / no Timeline mutation.
- `backend/app/renderer/contact_sheet.py:27` — `_shot_midpoints` (D5
  start + `duration_s/2`); public for pure arithmetic tests.
- `backend/app/renderer/contact_sheet.py:39` — `_duration_gte_shot_ids`
  duplicates the OQ-0a outgoing-or-incoming hazard check without
  importing `metrics.py`.
- `backend/app/renderer/contact_sheet.py:64` — narration excerpt from
  `scene.narration_text` × `shot.narration_span`, ~80 chars.
- `backend/app/renderer/contact_sheet.py:287` —
  `build_contact_sheet(...)` → sibling JPEG folder + static HTML grid;
  per-shot ffmpeg frame extract (`-ss` before `-i`).
- `backend/scripts/render_contact_sheet.py` — CLI matching
  `render_metrics.py` bootstrap (`sys.path` insert backend);
  `--timeline` `--video` `--asset-hashes` optional `--output`
  (default `<video>.contact.html`).
- `backend/tests/unit/renderer/test_contact_sheet.py` — dissolve
  midpoint arithmetic + duration_gte flags + lavfi 2-shot HTML
  (skip if ffmpeg missing).
- This plan: §3.2 shipped-shape; §9 row 7 ✅; status line.

**Measured:**
- Dissolve-joined pair (3.0 s dissolve 0.4 into 2.0 s): midpoints
  **sh_01=1.5**, **sh_02=3.6** (naive sum would put sh_02 midpoint at
  **4.0**).
- Synth lavfi 4 s `testsrc` + 2-shot timeline: contact sheet HTML
  contains both shot ids + `<img>`; **2** JPEG thumbs written under
  `clip.contact/`; shared `asset_ids` marks second shot `reused: yes`.

**Verification:**
```
cd C:\director-project\video-generation-engine\backend
C:\director-project\video-generation-engine\.venv\Scripts\python.exe -m pytest tests/unit/renderer/test_contact_sheet.py --noconftest -q
```
4 passed. `ruff check` clean on the three Python files.

**Effects / notes for the reviewer:**
- Must not be imported from `slideshow.py` / audio / music / fingerprint
  / workflow steps (same isolation rule as OQ-0a).
- Aspect-ratio CSS on thumbs is 9:16 object-fit cover — landscape
  lavfi test frames still render; real vertical reels fill the cell.
- Flagged border is CSS-only; open the page and jump to
  `.cell-flagged` before watching those shots in the mux.

**What is NOT done:** A8 motion-vs-still bake-off; dashboard/UI/endpoint;
wiring contact sheet into `render.py`; running the sheet against a full
exported project timeline JSON (synth 2-shot + pure midpoint proof only).
OQ-2 subject-aware camera — see P-OQ2.

### P-OQ2 — subject-aware camera (2026-08-28)

**Scope executed:** OQ-2 only — vision focal on depiction check, JSON
sidecar persistence, ken_burns aim + clamp, RV2 threading through
render, R16 `shot_focal` fingerprint (also run/shot-stream caches).
No `Camera` field, no zoom-delta changes, no classical saliency, no
PAN retarget, no live vision on the render path.

**Changes:**
- `backend/app/assets/focal.py` — sidecar I/O keyed by content hash;
  `persist_vision_focal` / `resolve_shot_focals` / fingerprint format;
  `focal.fallback` logging.
- `backend/app/providers/base.py` — `DepictionVerdict.focal_x` /
  `focal_y` (default 0.5).
- `backend/app/providers/openai_provider.py` — prompt asks for subject
  location on the existing depiction call.
- `backend/app/assets/depiction_check.py` — prompt version `v3`.
- `backend/app/workflow/steps/resolve_assets.py` — after a non-reject
  depiction check, write `{hash}.focal.json` beside the asset.
- `backend/app/renderer/ken_burns.py` — optional `focal=` on
  `build_zoompan_expression` / `build_punch_in_expression`; None /
  (0.5, 0.5) keep centre strings byte-identical; else
  `min(max(fx*iw-iw/zoom/2,0),iw-iw/zoom)`.
- `backend/app/renderer/slideshow.py` — `shot_focals` threaded through
  `render_timeline` → run / shot-stream encode paths.
- `backend/app/workflow/steps/render.py` — resolve once; pass to
  fingerprint + `render_timeline` (RV2).
- `backend/app/renderer/fingerprint.py` — unconditional `shot_focal`
  assignment; `focal` on run + shot-stream fingerprints too (otherwise
  those caches would HIT a centre crop after a sidecar appears).
- `backend/scripts/c8_probe.py` — new kwarg.
- Tests: `test_ken_burns.py` (focal aim/clamp + PAN untouched),
  `test_fingerprint.py` (swap + empty≠centre + `inspect.getsource`),
  `test_focal.py` (sidecar + verdict defaults).
- This plan: §5.5 shipped-shape; §9 row 8 ⚠; status line.

**Measured** (SLOW_PUSH intensity 0.3, 90 frames):

| | x_expr | y_expr |
|---|---|---|
| centre (None) | `iw/2-(iw/zoom/2)` | `ih/2-(ih/zoom/2)` |
| focal (0.2, 0.8) | `min(max(0.200000*iw-iw/zoom/2,0),iw-iw/zoom)` | `min(max(0.800000*ih-ih/zoom/2,0),ih-ih/zoom)` |

Same focal strings on `PUNCH_IN`. PAN x unchanged with focal set.

**Verification:**
```
cd C:\director-project\video-generation-engine\backend
C:\director-project\video-generation-engine\.venv\Scripts\python.exe -m pytest tests/unit/renderer/test_ken_burns.py tests/unit/renderer/test_fingerprint.py tests/unit/assets/test_focal.py --noconftest -q
```
→ **83 passed**. Ruff clean on touched files (`--line-length 100`).

**Effects / notes for the reviewer:**
- Pre-OQ-2 cached renders MISS (`shot_focal` key). Correct.
- Coverage incomplete by design: only searched top candidates that pass
  depiction get a sidecar. Generated / entity-curated / skipped → centre
  + `focal.fallback` log.
- Watch via OQ-0b contact sheet: does the punch land on the subject?

**What is NOT done:** human watch / contact-sheet sign-off (§5.4);
classical saliency/face heuristic; PAN x retarget. Backfill: see
`backend/scripts/backfill_focal.py` (P-OQ-RV / RV-Q4) — run **after**
the RV-Q1 crop-space fix, never before.

### P-OQ-RV — §12 review fixes (2026-08-29)

**Scope executed:** RV-Q1 (blocking crop-space), RV-Q2, RV-Q3, RV-Q4
(backfill script), RV-Q6, RV-Q7, RV-Q8, plus RV-Q5 NaN + `shutil.copyfile`.
Did not implement an `alimiter` after amix (RV-Q9 is a consideration, not
a required fix). Did not run OQ-4.1 on a live project (still one command).

**Changes:**
- `backend/app/renderer/ken_burns.py` — `scale_increase_size`,
  `compute_aimed_crop`, `ken_burns_crop_and_zoompan_focal`. Zoompan
  consumes residual crop-space coords, not original-image focals.
- `backend/app/renderer/slideshow.py` — `_ken_burns_filter` optional
  `crop_x`/`crop_y`; `_ken_burns_aim` maps through scale+crop. Centre
  focals omit x:y (today's `crop=w:h`).
- `backend/app/renderer/motion.py` — still `MediaProbe` records
  width/height so the crop can be aimed.
- `backend/tests/unit/renderer/test_ken_burns_focal_crop.py` — 600×800
  portrait into 2048×1152 canvas; banded-image fy=0.20 lands on green
  (band 1), not yellow (band 3).
- `backend/app/renderer/music.py` — unusable scene alignment **abandons**
  the alignment path (empty list → file-duration fallback, RV-Q2);
  `_merge_touching_intervals` merges gaps ≤ `2*DUCK_RAMP_S` (RV-Q3);
  ramp windows sorted chronologically.
- `backend/app/renderer/loudness.py` — pass-2 `print_format=json` + log
  `normalization_type` (RV-Q6); pin `-ar` to input rate (RV-Q7);
  distinct log when `measured_I >= 0` (RV-Q8); `shutil.copyfile` (RV-Q5).
- `backend/app/assets/focal.py` — reject non-finite coords (NaN was
  clamping to 1.0).
- `backend/scripts/backfill_focal.py` — preview / `--apply` vision
  backfill keyed by content hash (RV-Q4). Run only after RV-Q1.

**Measured:** banded-image test (RV-Q1) — fy=0.20, PULL_BACK intensity 1.0
(first frame zoom=1.5), centre pixel nearest band 1 (green). Geometry:
600×800 → scale-increase 2048×2731 (matches ffmpeg 9.0).

**Verification:**
```
cd backend
python -m pytest tests/unit/renderer/test_ken_burns_focal_crop.py tests/unit/renderer/test_ken_burns.py tests/unit/renderer/test_music.py tests/unit/renderer/test_loudness.py tests/unit/assets/test_focal.py tests/unit/renderer/test_fingerprint.py --noconftest -q
```
→ **110 passed.** Ruff clean.

**What is NOT done:** human listen (OQ-1a/b/c) and watch (OQ-2, after
`backfill_focal.py --apply` on a real project); RV-Q9 alimiter; OQ-4.1
live measurement; OQ-3.

---

### P-OQ-RV2 — RV-Q3 reopened and re-fixed (2026-08-29)

**Scope executed:** RV-Q3 only. Verification pass over P-OQ-RV re-measured
every finding rather than reading its log; seven confirmed fixed, RV-Q3
found half fixed.

**Changes:**
- `backend/app/renderer/music.py` — the `2*ramp_s` merge guard moved INTO
  `duck_ramp_windows`, so the no-overlap invariant holds for every caller
  rather than only for `speaking_intervals_from_alignment`. Docstring
  records why, with the measured number.
- `backend/tests/unit/renderer/test_music.py` —
  `test_ramp_windows_never_overlap_on_back_to_back_intervals` (asserts no
  overlapping pairs AND that the envelope never dips below the duck floor
  across the boundary) and
  `test_ramp_guard_is_idempotent_for_already_merged_intervals` (proves the
  guard cannot move `duck_envelope_hash` for already-correct input).

**Measured:**

| path | before this fix | after |
|---|---|---|
| fallback, back-to-back `[(0,2),(2,4)]` | 14 overlapping windows; worst gain 0.078 vs floor 0.5 = **−16.1 dB** | 0 overlaps; worst gain 0.5000 = **0.00 dB** |
| alignment, 50 ms scene gap | 0 overlaps | 0 overlaps, unchanged |
| alignment, 200 ms scene gap | 0 overlaps | 0 overlaps, unchanged |

**Verification:**
```
cd backend
../.venv/Scripts/python.exe -m pytest tests/unit/renderer/test_music.py tests/unit/renderer/test_fingerprint.py --noconftest -q
```
→ **75 passed** (music 15 → 17). Ruff clean (`--line-length 100`).
Independently, the full `tests/unit/renderer/` (242) and
`tests/unit/assets/` (143) directories were run green before this change;
the 3 errors in the latter are Postgres-unreachable fixture setup, not
regressions.

**Effects / notes for the reviewer:** the guard is now enforced by the
consumer, not the producer. If a third interval source is ever added it
inherits the invariant for free — which is the point, since the first fix
was correct code in the wrong place.

**What is NOT done:** unchanged from P-OQ-RV — human listen (OQ-1a/b/c)
and watch (OQ-2, which additionally requires `backfill_focal.py --apply`
first); RV-Q9 alimiter; OQ-4.1 live measurement; OQ-3. Also still open
from the verification pass: `loudness.py`'s docstring says dynamic "is
rejected" where the code detects, warns and accepts — accurate behaviour,
inaccurate word.

### P-OQ1b-char — duck on character duration, not inter-character gaps (2026-08-29)

**Scope executed:** §15.1 / §13.4 detector fix only. No RV-Q10 TTS
batching, no OQ-1c/1a changes, no compressor.

**Changes:**
- `backend/app/renderer/music.py` — `_runs_from_characters` splits when
  `end - start > DUCK_CHAR_PAUSE_S` (0.30 s); that character is a hole
  in the duck envelope. Inter-character gaps still merge below 0.8 s.
  If `characters` is present and aligned, only `isspace()` characters
  that long are pauses. `duck_envelope_content_hash` includes
  `char_pause_s`.
- `backend/tests/unit/renderer/test_music.py` — zero-gap newline split;
  long letter is not a pause; duration-only fallback; ramp non-overlap
  across a 0.40 s newline.
- This plan: §4.2 shipped-shape correction; §9 row 5 re-listen; §15.1
  threshold correction.

**Measured (unit, F1-shaped):** `h i \\n b y` with zero inter-char gaps
and a 0.40 s newline → duck windows `[(0.00, 0.10), (0.50, 0.60)]` — the
bed is released for the newline. A 0.50 s letter `"b"` stays one window.
Ramp windows on a 0.40 s hole do not overlap (gap 0.40 > 2×0.08).

**Verification:**
```
cd backend
python -m pytest tests/unit/renderer/test_music.py tests/integration/test_render_music_mix.py tests/unit/renderer/test_fingerprint.py --noconftest -q
```
→ **85 passed.**

**Effects / notes for the reviewer:** fingerprint MISS on music renders
(`char_pause_s` in the envelope hash). 0.30 s is the listen's counting
cutoff, not an ear-signed value — too low and a slow phoneme without a
`characters` array would swell the bed.

**What is NOT done:** re-render + listen on `1cdf55ac`; RV-Q10 scene-batch
TTS; changing bed/duck dB.

---

### P-OQ1b-depth — duck depth 4 dB -> 8 dB, ear-signed (2026-08-29)

**Scope executed:** `retention_fast`'s `music_duck_gain_db` only, after a
listening pass on the fixed envelope. No detector change, no other style.

**Why:** with §15.1's detector working, the user's verdict at the shipped
gains was *"yup works, but yeah not much noticeable change"*. The
mechanism was provably correct (+4.0 dB in all 17 gaps) — the limit was
that a 4 dB duck depth leaves the bed almost nothing to swell back into.
⚠ **The fix was NOT in the detector.** Anyone hitting "the music still
does not breathe" should check the depth before re-tuning
`DUCK_CHAR_PAUSE_S`.

**Method:** four depths rendered on the real narration + real bed of
`1cdf55ac` via `mux_music` directly (Postgres was down; no full render
needed), cut to one 18 s window covering four real swells (13.7, 19.9,
26.1, 27.9 s) so the candidates could be A/B'd:

| candidate | bed / duck | depth | verdict |
|---|---|---|---|
| A | −10 / −14 | 4 dB | shipped value — "not much noticeable change" |
| **B** | **−10 / −18** | **8 dB** | **chosen** |
| C | −10 / −22 | 12 dB | "starts to feel weird" |
| D | −8 / −22 | 14 dB | not preferred |

⚠ A/B/C share a bed of −10, so the level the music RETURNS to is
identical in all three. What the ear was judging is how far the music
drops under the voice — worth knowing before someone reads the table as
"louder music".

**Changes:**
- `app/script/styles.py` — `retention_fast.music_duck_gain_db` −14 → −18,
  with the listening evidence in the comment.
- `tests/unit/script/test_styles.py` — the assertion that retention_fast
  is LESS ducked than archival is **removed deliberately**. It encoded
  §5.2's "driving, barely ducked" intent, which §5.2 itself flagged as an
  arithmetic offset and "not a new listening pass". retention_fast is now
  more ducked than archival (8 dB vs 6 dB) because an ear said so.

**Verification:** `pytest tests/unit/script/ tests/unit/renderer/
--noconftest -q` → 310 passed; the 4 failures are the pre-existing
`test_suggestions` / `test_preflight` ones confirmed failing at `b9aaf69`.

**Effects / notes for the reviewer:** `music_duck_gain_db` is already in
`compute_render_fingerprint`, so every `retention_fast` render with music
correctly misses cache.

**What is NOT done:** the other three styles keep their gains — only
`retention_fast` was listened to. ⚠ `stillness` is the one to check next
(bed −22 / duck −28, 6 dB): §4.2 described its music as reading
"near-absent", and that diagnosis predates both the detector fix and this
depth finding.

### P-OQ-RV-Q10 — batch contiguous scenes into one TTS request (2026-08-29)

**Scope executed:** §15.2 / §13.5 RV-Q10 only. No voice-settings pin, no
join crossfade, no cache invalidation of already-synthesised rows, no
OQ-3, no `cost_cents` work.

**Changes:**
- `backend/app/timeline/narration_batch.py` — `plan_tts_batches` packs
  contiguous unique-hash misses up to the model character cap; a cached
  hash in the middle flushes (never overwrite a request-keyed row);
  duplicate texts in the same timeline are unique-by-hash and do not
  break the run. `split_batched_alignment` requires the raw alignment to
  equal the joined request text, drops the `\n` joiner from each scene's
  arrays (so `Shot.narration_span` still indexes `narration_text`), and
  stretches the previous scene's last-character end to the next scene's
  first-character start so the newline pause is in both the sliced mp3
  and `narration_fit`'s last-shot duration.
- `backend/app/renderer/narration_slice.py` — `atrim` on decoded
  samples, re-encode `libmp3lame` 44100/128k. Same concat-filter lesson
  as `audio.py`: never byte-concat framed MP3.
- `backend/app/workflow/steps/narration.py` — jobs are batches, not
  single hashes. Tempo is applied to the whole batch, then split. Every
  slice is cut before any row is inserted, so a mid-batch ffmpeg failure
  cannot cache a half-join. Per-scene `{content_hash}.mp3` + sidecar +
  DB row stay the render/fit contract.
- `backend/app/providers/elevenlabs.py` — `tts_request_character_limit`
  (eleven_v3 = 5000, the published cap); request timeout 60s → 300s
  because a v3 batch can be ~5 min of audio.
- `backend/app/providers/base.py` — `NarrationRequest.text` may be
  several scenes joined by a newline; `scene_id` is the first scene
  (tracing), not a cache key.
- Tests: `tests/unit/workflow/test_narration_batch.py` (pure pack/split
  + real-ffmpeg slice + FakeNarrationProvider round-trip);
  `tests/unit/providers/test_elevenlabs.py` (published caps).
  `tests/integration/test_narration_step.py` concurrency / sibling-
  failure cases monkeypatch the cap to 1 so they still measure gather
  behaviour, not the new default of one call per timeline.

**Measured:**

| case | before | after |
|---|---|---|
| 2 unique misses, cap 5000 | 2 TTS calls | 1 call, text `Hello\nWorld` |
| cached hash between two misses | 2 calls (unchanged) | 2 calls — cache is not overwritten |
| duplicate text A, A, C | 2 calls (A unique-by-hash, then C) | 1 call `Hello\nWorld`; second A reuses the first slice |
| cap 10 on `Hello` / `World` / `!!` | 3 calls | 2 calls (`Hello`, then `World\n!!`) |
| joined `Hi\nYo` at 10 chars/s | n/a | scene 1 audio `[0.00, 0.30)`, last-char end 0.30 (pause absorbed); scene 2 rebased to start at 0 |
| ffmpeg `atrim` 0.500–1.500 of a 2.017 s sine | n/a | decoded slice ≈ 1.00 s (±80 ms MP3 padding) |
| eleven_v3 published cap | per-scene, 44–305 chars | batches pack until **5000**; a 10-min Track C script (~8640 chars) is two requests, not 65 |

**Verification:**
```
cd backend
python -m pytest tests/unit/workflow/test_narration_batch.py tests/unit/workflow/test_narration_sidecar.py tests/unit/providers/test_elevenlabs.py tests/unit/timeline/test_narration_fit.py --noconftest -q
```
→ **51 passed.** Ruff clean (`--line-length 100`).

**Effects / notes for the reviewer:** the content hash is still the
per-scene *request*, not the audio bytes, so this does not fingerprint-
MISS existing renders and does **not** re-narrate cached projects. The
voice-switch on `1cdf55ac` stays until an N1 retry (or a new project).
A cache hit in the middle of a timeline is a remaining join that can
still switch — that is the cost of not overwriting another project's
row. Track C's "per-scene is what makes long-form fit under the
character cap" still holds: we pack *until* the cap, we do not send a
whole 10-minute script as one v3 request.

**What is NOT done:** re-narrate + listen on `1cdf55ac` (the only proof
the timbre join is gone); pinning voice settings as a partial fix;
crossfade at joins; invalidating existing narration rows.

---

## 11. Testing & DB safety — mandatory, binding on this plan

**Restated from `style_extensions.md` §6 and `analysis.md`'s TEST-DB
HAZARD. Not optional, and not summarised away.**

`backend/tests/conftest.py` has an **autouse** `clean_database` fixture
that runs `TRUNCATE TABLE ... RESTART IDENTITY CASCADE` across every
application table before every test — including pure unit tests. **There is
no separate test database.** The same Postgres backs the dev server and the
suite. A live project was lost to exactly this once. Since 2026-08-24 the
truncation is gated behind `PYTEST_TRUNCATE_DB=1`, which `make test` sets.

Rules for this plan:

1. **Do not set `PYTEST_TRUNCATE_DB` and do not run `make test`** for any
   verification under this plan.
2. **Every test written here must run under `pytest <path> --noconftest`**,
   or avoid the DB by construction — pure functions, fake providers,
   fabricated alignment/timing data instead of real ElevenLabs calls.
3. **Real ffmpeg is fine and is an established pattern**
   (`test_grading.py`, and `analysis.md` P3's real encodes). ffmpeg is not
   the database. Confirm any new test does not import
   `async_session_factory`, uses no `*Repository`, and does not reach
   `conftest.py`'s fixtures. **OQ-0a is essentially all ffmpeg and
   arithmetic, which is part of why it is safe to start with.**
4. **Never run the full suite during development here.** Scoped paths,
   `--noconftest`, one at a time.
5. **If a test seems to require the DB, stop and report** rather than
   running it against the shared instance.
6. **⚠ Before any session that will run tests at all, export the fixture:**
   `backend/scripts/export_test_project.py`. This plan leans on `58f0a5e6`
   (the real Fischer-Tropsch timeline with real assets) throughout — for
   the pause distribution, the loudness baselines and the contact sheet.

### 11.1 Which existing test files to model after

| New test area | Model after | Why |
|---|---|---|
| OQ-0a metrics arithmetic | `backend/tests/unit/renderer/test_fingerprint.py` | Pure functions over a fabricated Timeline, no DB |
| OQ-1 filter-string composition | `backend/tests/unit/renderer/test_grading.py` | Pure string-composition of render fragments |
| OQ-1 real encode / duration preservation | that file's real-ffmpeg cases, and `tests/integration/test_narration_audio_concat.py` | The second is the existing numeric proof that a join preserves duration — the exact shape §2.3 demands |
| OQ-1b speaking intervals from alignment | wherever `derive_caption_cues` is tested (grep `caption` under `tests/unit/renderer/`) | Same alignment arrays, same fabricated-alignment pattern |
| OQ-2 focal geometry | the Ken Burns tests under `backend/tests/unit/renderer/` (grep `zoompan` / `punch_in`) | Direct precedent for asserting on a generated expression |
| Any new fingerprint entry | `backend/tests/unit/renderer/test_fingerprint.py` | **Required** by §2.1 — a test that fails when the entry is removed |
| OQ-3a / 3b timeline passes | `backend/tests/unit/planners/` (`repair.py`'s tests) | Same shape: a deterministic pass over a finished shot list |

---

## 12. Review of P-OQ0a … P-OQ2 — 2026-08-29

Review of the seven tasks built 2026-08-28 (OQ-0a, OQ-0b, OQ-1a, OQ-1b,
OQ-1c, OQ-1d, OQ-2). Findings are numbered `RV-Q*` to stay distinct from
`analysis.md`'s `RV*` and the motion doc's `R*`.

**Method.** Diffs read in full; the two central claims were not taken on
trust but measured — a banded test image pushed through the real
`_ken_burns_filter` chain (§12.1), and six synthetic mp4s through the real
two-pass `loudnorm` command (§12.6). Test suite: **136 passed, 0 failed**
across the eleven new/changed unit + integration files, `--noconftest`,
`PYTEST_TRUNCATE_DB` unset, Postgres unreachable throughout (three
DB-dependent integration tests errored at TCP connect — no rows read,
written or truncated).

### 12.0 Verified good — re-checked, not taken on trust

- **The R2 discipline holds.** This is the first slice in this repo's
  history with no missing fingerprint entry. `music_amix_normalize`,
  `loudness_normalize` / `_target_lufs` / `_true_peak_db`, `loudness_lra`,
  `narration_level_match`, `duck_envelope_hash`, `shot_focal` — all
  unconditional, R16 assignment shape where per-shot.
- **Focal reaches all three fingerprints** (render, run, shot-stream).
  Missing the latter two would have cache-HIT a centre-aimed encode after
  a sidecar appeared. It was caught.
- **The `duck_envelope_hash` gate is correct on the long-form path.**
  Suspected R2 miss, checked, absent: `render.py:267` sets
  `music_content_hash` non-None exactly when `music_segments` is non-None,
  so the hash condition and the mux condition cannot diverge on act beds.
- **Loudness output routing is correct in all four branches**
  (sfx × loudness), and a failed pass copies through — §2.6 honoured.
- **`_focal_xy_exprs` arithmetic is right in its own frame**:
  `min(max(fx*iw-iw/zoom/2,0),iw-iw/zoom)` is the correct clamped top-left
  for an `iw/zoom`-wide crop. The defect (RV-Q1) is the frame, not the
  algebra.
- **OQ-1d was measured before being changed**, per §4.4. Confirmed, fixed,
  logged.
- **Process:** built in §9's exact order, log entries in the §10 shape,
  `⚠ awaiting listen/watch` used instead of ✅ on the five items that need
  a human. That convention did its job — this review found the OQ-2 bug
  *before* anyone spent an hour watching a render to discover it.

### 12.1 🔴 RV-Q1 — BLOCKING: the focal point is consumed in the wrong coordinate space, and the subject is often cropped away before zoompan ever sees it

`openai_provider.py` asks for `focal_x`/`focal_y` normalised to **the
original image** ("origin at the top-left"). But `_ken_burns_filter`
(`app/renderer/slideshow.py:319-340`) runs, *before* zoompan:

```
scale=2048:1152:force_original_aspect_ratio=increase, crop=2048:1152, setsar=1, zoompan=…
```

`crop=w:h` with no x/y is **centred**. zoompan's `iw`/`ih` are therefore
the post-crop canvas, not the original image. The value is measured in one
frame and applied in another.

**Measured, not argued.** A 600×800 portrait (3:4 — the shape §19.8 of the
motion doc measured 11 of 14 archival assets to be) with eight labelled
colour bands, pushed through the exact production chain at `zoom=1.5`:

| focal_y given | band it should aim at | band the output centre actually shows |
|---|---|---|
| 0.20 | 1 (green) | **3 (yellow)** — green absent from the frame entirely |
| 0.35 | 2 (blue) | **3 (yellow)** |
| 0.50 | 3/4 boundary | 4 (magenta) — ≈ correct |

The centre crop keeps only original `fy ∈ [0.289, 0.711]`, 42 % of a 3:4
image. Two distinct consequences:

1. **A subject in the upper or lower third is destroyed before the aim is
   applied**, and the clamp absorbs it silently — `fy=0.20` and `fy=0.35`
   produce *identical* framing, so the focal is inert across the whole
   upper half of a portrait asset.
2. **Even inside the surviving band the aim is wrong**, by the inverse of
   the kept fraction (≈2.4× here). `fy=0.5` is the only fixed point, so
   error grows with distance from centre — precisely where the feature was
   supposed to earn its keep.

⚠ This is worse than centre-aiming, not merely neutral: it moves the camera
confidently to the wrong place. And it is worst on exactly the case §5.1
used to justify the feature.

**Fix — it has to touch the crop, not just zoompan.** Aim the pre-zoompan
`crop` at the focal (`crop=cw:ch:x=clamp(fx*in_w-cw/2,0,in_w-cw):y=…`),
which both preserves the subject and makes the two stages agree; then map
the residual offset into zoompan's `x`/`y` rather than passing the raw
original-space value. No new fingerprint entry — the focal string already
covers it.

⚠ **And add a test that would have caught this.** Every existing OQ-2 test
asserts the expression *given* a focal; none asserts where the subject
lands. The banded-image method above is cheap, deterministic, and needs no
DB — it belongs in `tests/unit/renderer/`.

### 12.2 🟡 RV-Q2 — one unusable scene alignment desyncs every duck window after it

`music.py::speaking_intervals_from_alignment`: the `alignment is None` and
`non_numeric_times` branches `continue` **without advancing
`scene_offset`**, while the length-mismatch branch *does* advance it from
`ends_raw[-1]`. Three failure paths, two behaviours.

Measured against the real function:

```
S([scene1, scene2])  -> [(0.0, 4.0)]
S([None,   scene2])  -> [(0.0, 2.0)]   # scene 2's speech is really at 2.0-4.0
```

A two-second desync that compounds per skipped scene — the bed would duck
under silence and swell under speech.

Reachability is low today (`Narration.alignment` is `nullable=False` and
the list is built as `[row.alignment for row in narration_rows]`), so this
is defensive code that is wrong rather than a live bug. It becomes live the
moment a partial-narration path exists. **Either advance the offset in all
three branches, or refuse the alignment path wholesale and fall back to
file durations** — the way `derive_caption_cues` refuses (`raise
ValueError`) on a row/scene count mismatch. Consistency with captions is
the point (§4.2 chose the shared threshold for the same reason).

### 12.3 🟡 RV-Q3 — duck ramps collide at scene boundaries and multiply below the intended floor — **fixed in P-OQ-RV, REOPENED and re-fixed 2026-08-29 (P-OQ-RV2)**

⚠ **The first fix put the guard in the wrong place and left the worse half
open.** `_merge_touching_intervals(min_gap_s=2*DUCK_RAMP_S)` was called
only from `speaking_intervals_from_alignment`. `compute_narration_intervals`
— the fallback that **RV-Q2's own refusal routes into** — returns per-scene
intervals explicitly "back to back with no gap" and never passed through
it. Re-measured on that path: 14 overlapping windows on three scenes, and
at a scene join both full ducks plus both ramp sets are live at once,
multiplying to **0.078 against an intended floor of 0.5 — 16.1 dB below
the duck floor** for ~80 ms. On a bed already at −28 dB that is an audible
hole at every boundary. Worse than the desync RV-Q2 was fixed to prevent.

**Re-fixed by moving the guard into `duck_ramp_windows` itself**, which is
the function whose output is wrong when the invariant is violated, so it
no longer depends on which caller feeds it. Idempotent for the alignment
path (already merged at the same threshold) — no output change, no
fingerprint change. Two regression tests added, including one that asserts
the envelope never dips below the floor anywhere on back-to-back input.

⚠ **Lesson worth keeping:** the original finding was correct and the fix
was applied to the path the *repro* used rather than to every path the
*defect* covered. The full suite passed throughout, because no test
exercised the fallback route at all.

`duck_ramp_windows` emits ramp-in windows starting `ramp_s` *before* each
interval and ramp-out windows *after* it. These are chained `volume`
filters, so overlapping windows **multiply**. Measured on `(0.0, 2.0)` and
`(2.05, 4.0)` — a 50 ms gap:

```
[2.00, 2.02] 0.625   ramp-out of #1
[1.97, 1.99] 0.875   ramp-in  of #2   -> 0.5 x 0.875 = 0.4375 at t≈1.98
                                          0.625 x 0.75 = 0.469  at t≈2.005
```

Both are *below* the intended full duck of 0.5.

Inside a scene this cannot happen (runs are ≥ `DUCK_MERGE_THRESHOLD_S`
= 0.8 s apart, ramps are 0.08 s). **Across scene boundaries there is no
such guarantee:** `_merge_touching_intervals` merges only gaps ≤ 1e-6, so
any boundary gap in (0, 2·`DUCK_RAMP_S`) collides, and 20–80 ms of leading
TTS silence is ordinary. Merge intervals closer than `2*ramp_s`, or clamp
each ramp to the gap actually available.

⚪ Minor, same function: the docstring claims windows are returned "in
chronological order" and they are not (`2.00, 2.02, 2.04, 1.97, 1.99, …`).
Harmless for a multiply chain; the claim is still false.

### 12.4 🟡 RV-Q4 — nothing backfills focals, so the designated fixture will show OQ-2 doing nothing

Sidecars are written only in `ResolveAssetsStep` at bind time. Every asset
in `58f0a5e6` — the fixture §11 names for exactly this purpose — predates
the change, so `resolve_shot_focals` returns `None` for all of them and
every shot renders centre-aimed.

§9 row 8's sign-off is "watch via the OQ-0b contact sheet". On that project
the watch produces a **null result**, which reads as "focal doesn't help"
rather than "focal never ran". There is no `backfill_focal.py` in
`backend/scripts/`.

**Before the human watch, not after:** either add a backfill (re-run the
vision question over bound assets, keyed by content hash) or state in §5.5
that the watch requires a freshly-resolved project. This must be resolved
together with RV-Q1 — backfilling focals that are then consumed in the
wrong coordinate space would bake the wrong aim into sidecars.

### 12.5 ⚪ RV-Q5 — smaller items, verified, none blocking

- `loudness._copy_through` uses `read_bytes()` / `write_bytes()` — a whole
  10-minute 720p mp4 through RAM on every fallback. `shutil.copyfile`.
- `focal.normalize_focal` does not reject NaN. Python's `json.loads`
  accepts a bare `NaN` literal and `max(0.0, min(1.0, nan))` returns
  `1.0`, so a corrupt sidecar aims at the frame corner instead of falling
  back to centre.
- **Sequencing deviation:** §9 row 6 (OQ-4.1, transition-vs-shot
  validation) was skipped; rows 7 and 8 were built instead. Its gate —
  "OQ-0a's report says whether it is already occurring" — appears never to
  have been checked, though `metrics._transition_metrics` implements the
  check. One command on a real render, and it is the motion doc §7 caution
  that has been open longest.
- Ken Burns stills are **crop-to-fill**; static stills are **scale+pad**
  (`_normalize_filter`). Pre-existing, not introduced here — but it means
  one asset is framed two different ways depending on whether the planner
  gave it a camera move, and RV-Q1's fix puts someone in that code anyway.
  Decide it there.
- The narration clock convention (`scene_offset += char_ends[-1]`) is now
  load-bearing for **two** subsystems, captions and ducking, and it ignores
  any trailing silence in a scene's MP3. Captions visibly sync, so the
  error is empirically small — but it is now worth proving rather than
  inferring: compare `sum(char_ends[-1])` against the ffprobe duration of
  the concatenated narration and add it to the OQ-0a report.

### 12.6 The loudnorm measurements — what ffmpeg actually does

Measured 2026-08-29 on **ffmpeg 9.0** (Gyan build, the binary on PATH,
which is what `config.py:246-247`'s `"ffmpeg"` default resolves to). Six
synthetic 12 s mp4s (320×240 h264 + 48 kHz stereo AAC) through the exact
`apply_loudness_target` command pair. **These numbers supersede §2.3's and
§4.1's original assumptions.**

**Duration: exactly preserved, on both paths.** Decoded PCM sample counts
identical in every case (`576000 → 576000`; `12.000000 → 12.000000`).
`duration_ts`/`nb_frames` change only because the timebase follows the
sample rate. §2.3's invariant is satisfied — and satisfied by dynamic mode
too, which is why §2.3's stated reason for rejecting dynamic was wrong.

#### 🟡 RV-Q6 — `linear=true` is unenforced, and ffmpeg is silent when it refuses

Dynamic fallback fired on 3 of 6 files, by two different routes:

- **`measured_LRA=0.00` forces dynamic** regardless of headroom —
  confirmed by flipping only that field from `0.00` to `1.0`, which
  restored `"normalization_type" : "linear"`. Not the true-peak path: that
  file's linear TP would have been −7.62, far under −1.
- **True-peak breach forces dynamic** (input_i −34.71, input_tp −20.09 →
  linear TP −0.62 > −1).

Grepping the full pass-2 stderr for `dynamic|linear|normalization|warn|
clip|limit|Parsed_loudnorm` returns **zero matches on all four files
tested**. No warning, no log line, no exit-code difference between
honoured-linear and silently-dynamic. `-v verbose` adds nothing.

⚠ So `loudness.py`'s docstring claim — *"Single-pass / dynamic loudnorm is
rejected"* — is not enforced by anything, and the reason it gives is false
(see duration above). **Fix:** add `print_format=json` to pass 2 as well;
loudnorm then prints the authoritative `"normalization_type" : "linear" |
"dynamic"` at filter uninit. Log it. Correct the docstring to the creative
objection (§2.3 as amended).

#### 🟡 RV-Q7 — the output silently becomes 96 kHz AAC whenever that fallback fires

Linear mode does not resample (48000 → 48000). Dynamic mode requests
192 kHz internally and lands at **96000 Hz** AAC-LC via an auto-inserted
`aresample`.

| file | mode | out rate | size delta |
|---|---|---|---|
| A (dense) | dynamic | 96000 | +0.58 % |
| C, D | linear | 48000 | +0.003 % |
| E (sparse) | dynamic | 96000 | **+13.3 %** |

Sparse audio pays most, because the doubled rate lifts the AAC bitrate
floor (28 → 68 kb/s). **Fix:** pin `-ar` to the input rate in pass 2.
Until then, output sample rate is a usable side-channel for which mode ran.

⚪ Related, worth a deliberate decision: pass 2 specifies no `-b:a`, so it
re-encodes at ffmpeg's AAC default (one test file went 192k → 128k). With
`mux_narration`, `mux_music`, `mux_sfx` and now `apply_loudness_target`
each encoding to AAC, the loudness pass adds a **fourth** lossy generation
to the final mix. For a feature whose purpose is audio quality that should
be chosen, not defaulted.

#### 🟡 RV-Q8 — the loudest mixes silently skip normalization entirely

`loudnorm` constrains `measured_I` (and `measured_thresh`) to **[−99, 0]**.
A mix measuring ≥ 0 LUFS aborts pass 2:

```
Value 0.070000 for parameter 'measured_I' out of range [-99 - 0]
Error opening output files: Result too large
```

`loudness.py:215-224` handles this correctly — non-zero exit → warn → copy
through, render never fails. But the consequence is that **the mixes most
in need of a loudness target are the ones that do not get one**, and the
only trace is the generic pass-2 failure message. Give it its own
greppable log line ("mix measured ≥ 0 LUFS; loudness skipped").

#### ⚪ RV-Q9 — `normalize=0` is exactly +6.02 dB, with no headroom guard

OQ-1d's fix is precisely the removal of amix's divide-by-N: **+6.02 dB,
verified in five configurations** (coherent and incoherent, verified
against an `asplit` self-mix). It overflows 0 dBFS once sources exceed
roughly −6 dBFS each: −6 + −3 → **+1.65 dBFS**; −3 + −3 → **+3.02 dBFS**;
−6 + −6 → **+0.02 dBFS**.

With the current gains this is probably unreachable — the bed sits at
−22/−28 dB, so the sum is narration plus very little. But there is no
guard, and the consequence if it is ever reached was measured: **clipping
is baked into the samples and the later loudnorm cannot undo it.** On a
hard-clipped mix, loudnorm pulled signal and harmonics down by an identical
10.58 dB — harmonic-to-signal ratio unchanged to 0.01 dB, still 15 dB worse
than a clean reference — while comfortably "meeting" the −1 dBTP target.
Gain reduction, not repair. And a hot mix is exactly what trips RV-Q8.

Two cheap actions: run the OQ-0a report's `true_peak` on a real render with
music to see where this project actually sits, and consider an `alimiter`
at −1 dBFS after the amix (a fixed-algorithm filter — deterministic given
the same input bytes, so I5 is untouched).

⚠ **Caveat for anyone writing a clipping detector later:**
`Flat_factor`/`Peak_count` do **not** work on an encoded mp4 — a single AAC
round-trip rounds the flat tops off and both clipped and clean files report
`0.000000` / `2.000000`. On raw PCM they are unambiguous (flat factor 31.57
vs 0.000). Use the harmonic-residual ratio on encoded material.

### 12.7 Recommended order

1. **RV-Q1** — blocking, and it invalidates the OQ-2 human watch. Fix the
   crop + coordinate transform, add the banded-image test.
2. **RV-Q4** — only after RV-Q1, or the backfill bakes in the wrong aim.
   Then the watch (§9 row 8) is finally meaningful.
3. **RV-Q6 + RV-Q7** — one edit each to the same pass-2 command
   (`print_format=json`, `-ar`), plus the docstring correction. Do them
   together; both are one-liners.
4. **RV-Q8** — distinct log line. Trivial, and it is what will tell you
   whether RV-Q9 is theoretical or real on this project.
5. **RV-Q2 + RV-Q3** — the two ducking edge cases. Both before the OQ-1b
   listen (§9 row 5), since RV-Q3 is audible at scene boundaries.
6. **RV-Q5** items, opportunistically. The transition-vs-shot gate
   (§9 row 6) is one command and should stop being skipped.

⚠ **Do not bundle 1 with 3–5.** RV-Q1 is a render-geometry change and the
loudnorm items are mix changes; §9's own "do not parallelize" reasoning
applies to reviewing them too.

### 12.8 What was checked and holds up

Read in full and found correct, beyond §12.0: the four-branch loudness path
routing; `speaking_intervals_from_alignment`'s within-scene run merging;
`duck_envelope_content_hash`'s canonical rounding matching the filter's own
`%.3f` formatting; `format_focal_fingerprint`'s `""`-for-unresolved
contract (an explicit centre and an unresolved focal fingerprint
differently and render identically — a wasted cache miss in the safe
direction, deliberate per R16); `persist_vision_focal`'s pairing of the
verdict with `rank_result.content_hash` in the same loop iteration;
`metrics.py`'s coverage of all nine metrics §3.1 specified, including the
transition hazard.

### 12.9 Resolution of RV-Q* (2026-08-29)

| Finding | State |
|---|---|
| RV-Q1 crop-space (blocking) | ✅ aimed pre-zoompan crop + residual zoompan; banded-image test |
| RV-Q2 duck clock desync | ✅ unusable scene abandons alignment path |
| RV-Q3 ramp multiply at scene joins | ✅ merge gaps ≤ 2×ramp_s |
| RV-Q4 no focal backfill | ✅ `scripts/backfill_focal.py` (run after Q1) |
| RV-Q5 NaN / copyfile | ✅ `math.isfinite`; `shutil.copyfile` |
| RV-Q6 linear unenforced | ✅ pass-2 `print_format=json`, log type |
| RV-Q7 96 kHz on dynamic | ✅ pin `-ar` to input |
| RV-Q8 ≥ 0 LUFS silent skip | ✅ distinct `RV-Q8` log line |
| RV-Q9 amix clip / alimiter | not built — still a consideration after a real music-on peak |

OQ-2 human watch is unblocked **once** `backfill_focal.py --apply` has
run on the project being watched. Centre-only contact sheets on
pre-OQ-2 assets are still a null result.

---

## 13. First real render + human listen — 2026-08-29

⚠ **Everything in §12 and earlier was measured on synthetic material** —
banded test images, lavfi sine waves, fabricated alignment dicts. This
section is the first time any of this work was pointed at a real project.
It overturns three conclusions and finds one defect nobody was looking for.

**Subject:** project `1cdf55ac` "The Rich mans F1" — `retention_fast`,
Hindi/Hinglish, 9 scenes, 45 shots, 76.2 s, 720×1280 @ 30 fps.
**Method:** metrics on the shipped render (before), then a real re-render
via `render_video` directly (the engine path skips `RenderStep` entirely —
`is_satisfied` returns True whenever `project.video_path` exists, so it
never reaches the fingerprint), written to `oq_after.mp4` so `final.mp4`
and `project.video_path` stayed untouched. Then a human listened.

### 13.1 Measured: before vs after

| | before | after |
|---|---|---|
| integrated loudness | −22.3 LUFS | **−16.0 LUFS** (target −16.0) |
| true peak | −5.9 dBFS | **+0.1 dBFS** (ceiling −1.0) |
| LRA | 2.3 | 2.0 |
| sample rate | 44100 | 44100 (RV-Q7's `-ar` pin held) |
| audio samples | 3665617 | 3665617 — **identical**, §2.3 holds |
| `normalization_type` | — | **dynamic** (RV-Q6 fired on the first real render) |
| focal fallbacks | — | **45 of 45 shots** (RV-Q4 confirmed) |

Peak trace through the chain, old vs new:

| stage | old | new |
|---|---|---|
| `narrated_*` (narration muxed) | −0.5 | **+0.2** |
| `pre_sfx_*` (after music amix) | **−6.0** | +0.3 |
| `pre_loudness_*` | — | −0.1 |
| final | **−5.9** | **+0.1** |

### 13.2 ✅ OQ-1a — CONFIRMED BY EAR. The one unambiguous win.

−22.3 → −16.0 LUFS, exactly on target, and the listener confirmed the
new render is clearly louder against the old `final.mp4`. **§9 row 3 can
be marked done.** The `-16.0 / -1.0` defaults are hereby ear-validated
for `retention_fast` short-form; still unvalidated for landscape styles.

### 13.3 ⚪ The +0.1 dBFS overshoot is REAL ON PAPER AND INAUDIBLE

Three defensible changes compose into it: OQ-1c boosts quiet scenes with
no peak constraint (−0.5 → +0.2 at the narration stage — **RV11's exact
shape**, a normalization target applied as a gain rather than against a
peak); OQ-1d removed the `amix normalize=1` halving that had been
accidentally protecting the master at −6.0; and `loudnorm` overshot its
own −1.0 dBTP ceiling by 1.1 dB (dynamic mode + an AAC re-encode after
the limiter).

⚠ **But the listener heard no harshness or crackle, and that is the
verdict that counts.** Downgraded from the "regression" framing this was
first reported under. Worth a cheap guard — cap OQ-1c's per-scene boost
against a peak ceiling, and give `loudnorm` real headroom (−1.5/−2.0) —
so it cannot get worse with a louder bed or a hotter voice. Not urgent.

### 13.4 ❌ OQ-1b is INERT — confirmed by ear and by measurement on six projects

The listener: *"no, the music does not come up."* Correct, and it is not
a tuning problem.

`speaking_intervals_from_alignment` splits runs on the gap **between**
consecutive characters. **ElevenLabs never leaves one.** Measured:

| project | scenes | duck intervals | % ducked | inter-char gaps | chars ≥0.30 s |
|---|---|---|---|---|---|
| The Rich mans F1 | 9 | **1** | 100% | **0** | 17 |
| the whey economics | 8 | **1** | 100% | **0** | 12 |
| OSHO the legend | 7 | **1** | 100% | **0** | 19 |
| The deep state part 1 | 10 | **1** | 100% | **0** | 8 |
| Radar and WW2 | 8 | **1** | 100% | **0** | 30 |
| Automatic transmissions | 6 | **1** | 100% | **0** | 1 |

One interval spanning the whole timeline, every time — **coarser than the
per-scene behaviour it replaced.** The pauses are real but live *inside*
a single character's duration: on F1, 17 characters ≥0.30 s, all `'\n'`,
6.56 s total, longest 0.584 s.

**Fix:** split a run when a character's OWN duration exceeds the
threshold, not when the gap between characters does. Small, and it is the
difference between this feature existing and not.

### 13.5 🔴 RV-Q10 — NEW, user-identified: the voice changes character at scene starts

The listener, unprompted: *"that `training` sounds like some other voice
switched"* — and noted it is present in the OLD render too, so not a
regression from any of this work.

Located exactly: **"Training" is character 0 of scene 2, t = 8.80 s — the
scene 1 → scene 2 boundary.** All nine scenes share one `voice_id`, but
narration is **nine separate TTS requests**. Each starts fresh, so the
voice can open a scene with different character/energy; the first word
carries it. Compounded here by an English loanword opening a Hindi
sentence with no preceding context to settle the accent.

⚠ **This reframes OQ-1c.** §4.3 built scene-boundary matching for a
LEVEL jump. The measured level spread is **0.9 LUFS** (−15.8 … −16.7) —
inaudible, and OQ-1c is a near-no-op on this project. The audible
scene-boundary defect is **timbre**, which gain-matching cannot touch.
The feature solved the wrong half of a real problem, and only a human ear
found the right half. Q8's finding (voice varies 36% vs 8% for language)
was pointing at this all along.

**Fix, in order of honesty about cost:**
1. **Synthesize several contiguous scenes in ONE request**, then split on
   the returned alignment. One request = one continuous performance =
   nothing to switch between. Also cheaper (fewer calls). ⚠ Real work:
   narration is cached per scene by content hash, and `narration_fit.py`
   assumes one alignment per scene.
2. Pin voice settings per project so each request starts identically —
   reduces drift, does not remove it.
3. A short crossfade at joins hides a level step and does nothing for
   timbre. Not a fix.

### 13.6 ✅ OQ-4.1 CLOSED — measured across the whole corpus, 15 projects

`duration_gte_shot` is empty for **every completed project**, including
the two `archival_montage` ones that actually emit dissolves (3 and 6).
The motion doc §7 caution — *"I searched and found no validation…"* —
open since 2026-08-18, is answered: the hazard is real in principle and
**does not occur in practice**. Adding the validation is now a guard, not
a fix. §9 row 6 can be closed on that basis.

### 13.7 New finding the report surfaced unprompted: sub-frame shots

633 shots across 15 projects. Two are **0.023 s** — under one frame at
30 fps — both in "Airports and money"; that project also has 6 shots
under 0.30 s, and two others have one each. `retention_fast`'s stated
floor is 0.8 s. Narrow (0.3% of shots) but a shot that renders as a
single flashed frame is a defect. Wants a floor assertion at planning
time. **This is the first thing OQ-0a found that nobody was looking for,
which is the argument for having built it.**

### 13.8 ⚠ OQ-3a's gate was measured wrong — the feature is NOT dead

First pass concluded "zero inter-character gaps → no slack → OQ-3a dead."
That was premature, and wrong for the same reason §13.4 is: the pauses
exist, they are inside character durations. On F1 that is 17 candidate
boundaries up to 0.584 s in 76 s — ample slack for a ≤160 ms beat nudge.
**Re-measure the gate against character durations before judging OQ-3a.**

### 13.9 Status after the listen

| item | verdict |
|---|---|
| OQ-1a loudness | ✅ done, ear-confirmed |
| OQ-1c level match | ⚪ near-no-op here (0.9 LUFS); keep as insurance, add a peak cap |
| OQ-1b speech ducking | ❌ inert — fix §13.4 then re-listen |
| OQ-2 focal | ❌ never ran (45/45 fallback) — backfill required before any watch |
| peak overshoot | ⚪ inaudible, guard it cheaply |
| RV-Q10 voice switch | 🔴 the real audible defect, unscoped until now |
| OQ-4.1 | ✅ closed, corpus-wide |
| OQ-3a | gate needs re-measuring, not dead |

**Suggested order:** §13.4 (ducking detector) → re-render → listen again →
then scope RV-Q10 properly. Peak guard and focal backfill ride along.

---

## 14. OQ-2 re-cut: the focal feature was asking the wrong model — 2026-08-29

§13.9 recorded OQ-2 as "never ran (45/45 fallback)". Running the backfill
turned that into a worse finding: it does run, and it returns nothing
usable. This section is the diagnosis, the bake-off that settled it, and
the re-cut.

⚠ **Read §12.1 (RV-Q1) first.** That fix — mapping the focal through the
pre-zoompan crop — is correct and verified. It was simply sitting
downstream of a feature that produces no data, which is why it looked
like it "did nothing".

### 14.1 What the backfill actually produced

34 stills, 12 written before an unretried 429 killed the script:

```
(0.50, 0.50)  x 11        <- exactly the schema default
(0.40, 0.50)  x  1
focal_source: {"vision": 12}
```

**11 of 12 were the geometric centre, every one labelled `vision`.** And
`_focal_xy_exprs` treats `(0.5, 0.5)` as *no focal given*, emitting the
historical centre strings — so those shots render byte-identically to
before. A completed backfill of all 34 would have changed nothing on
screen.

### 14.2 Two independent causes, either sufficient

**Cause 1 — a default that is indistinguishable from an answer.**
`DepictionVerdict.focal_x: float = 0.5` meant a model that answered the
plausibility question and ignored the location one produced a confident
centre, which `persist_vision_focal` wrote out as a vision answer. There
was no way, from the sidecar or the logs, to tell "the model said centre"
from "the model said nothing".

**Cause 2 — and this is the real one: `gpt-4o-mini` cannot localise.**
Verified by reading the raw stored response: the model *is* answering,
explicitly emitting `"focal_x":0.5,"focal_y":0.5`. So making the field
required would have changed nothing. Prompt shape does not rescue it
either — measured, on the same 5 assets:

| prompt variant (all on gpt-4o-mini) | result |
|---|---|
| current: plausibility gate + focal tacked on | 3 of 5 exactly (0.50, 0.50) |
| name the subject → describe in words → then numbers | 4 of 5 moved off centre |
| 3×3 grid cell as an enum | **worse** — 4 of 5 picked `middle-centre` |

⚠ The grid variant is worth recording as a rejected idea: an enum was
supposed to make the task easier for a small model and instead handed it
a safer place to hide.

⚠ **And "moved off centre" is not "correct".** Rendering the name-first
variant's answers as crosshairs on the photographs showed roughly half
landing on nothing — the empty gap between two cars, empty track beside
the kart pack. That is *worse than centre*, per §12.1's own logic: the
camera then moves decisively to the wrong place. **Numbers said the
prompt fix worked; the picture said it didn't.**

### 14.3 The bake-off — same prompt, same images, five models

Prompt held constant (name → words → numbers) so this isolates model
capability. Crosshairs drawn on the photographs and judged by eye; the
decisive images were the ones with an unambiguous subject.

| model | verdict |
|---|---|
| **gpt-5.5** | **6/6 sensible, correct on all three decisive images.** Winner |
| gpt-5.6-terra | right on the drivers/cars; called a kart seat an *"industrial sewing machine"*, missed the kart pack |
| gpt-4.1 | right on the cars, wrong on both people shots |
| gpt-4o | middling |
| gpt-4o-mini | worst — wrong car of two, wrong side of the pack, plus the centre default |

The three decisive images:

- **Kart driver** — gpt-5.5 and 5.6-terra land on the blue helmet ("the
  driver's face, upper middle"). 4o-mini, 4o and 4.1 all land on the
  kart's bodywork: they found the *vehicle*, not the *person*.
- **Two racing cars** — 4.1, terra and 5.5 land on the foreground car's
  cockpit. 4o-mini lands on the **wrong car**.
- **Karts racing** — 5.5 lands on the lead kart. 4o-mini, 4o and 4.1 all
  land on empty track to the left of the pack.

### 14.4 Decision: a separate call, on a separate model

⚠ **The depiction gate must not move.** A30/A30a calibrated its
false-accept / false-reject balance twice against `gpt-4o-mini`, on a real
Hindi fixture. Swapping the model underneath it to get a better focal
answer would silently re-open that calibration — the same class of
mistake as §13.3's composite regression.

So the two questions are split:

| | model | why |
|---|---|---|
| plausibility gate (`check_depiction`) | `openai_vision_model` = gpt-4o-mini | unchanged, still calibrated |
| subject location (`locate_subject`) | **`openai_focal_model` = gpt-5.5** | new setting, new call |

Cost: one extra call **per bound shot**, not per candidate — the focal
call sits behind the same `checked_top_candidate` guard the gate does.

### 14.5 What changed

- `app/providers/base.py` — `focal_x`/`focal_y` **removed** from
  `DepictionVerdict`; new `SubjectFocal` (fields `subject`,
  `subject_location_words`, `focal_x`, `focal_y`, **no defaults**,
  coords bounded 0..1) and `SubjectFocalRequest`; `locate_subject` added
  to the `VisionConstraintProvider` protocol.
- `app/core/config.py` — `openai_focal_model: str = "gpt-5.5"`.
- `app/providers/openai_provider.py` — the focal paragraph removed from
  the depiction prompt (it is a v2-shaped prompt again); new
  `locate_subject` using the name→words→numbers ordering.
- `app/assets/focal_check.py` — **new**, mirrors `depiction_check.py`:
  one call, one `llm_call` audit row, and every failure returns `None`
  rather than a fabricated centre. ⚠ This also closes a gap the first
  backfill exposed — its 12 real calls were recorded in **zero**
  `llm_call` rows, so they were invisible to any cost accounting
  (§7/OQ-4.4).
- `app/workflow/steps/resolve_assets.py` — calls `locate_subject_focal`
  after a non-reject verdict; `None` means no sidecar rather than a
  centre one.
- `scripts/backfill_focal.py` — uses the new call; `_locate_with_retry`
  adds exponential backoff (2s → 30s, 5 attempts), because the first run
  died at 12 of 34 on a 429 with no retry; an exhausted retry writes an
  explicit `source="fallback"` sidecar rather than a fake vision answer.
- `tests/unit/assets/test_focal.py` — the old
  `test_depiction_verdict_defaults_focal_to_centre` is **inverted**: it
  now asserts the fields are gone, that `SubjectFocal` rejects a missing
  coordinate, and that it rejects an out-of-range one.

### 14.6 The rule this leaves behind

⚠ **A default value on a model-answered field is a silent failure
generator.** It converted "the model ignored the question" into "the
model said centre", survived a code review, a full unit suite, and a
completed backfill, and was only visible when someone drew the answers on
the photographs. Any future field a model fills should either be required
or be distinguishable from its default at read time.

And the session's recurring lesson, now three for three: **the numbers
agreed with the code at every step, and the picture disagreed.**

### 14.7 Cost: the focal call was 44% of the whole video, and 97% of it was wasted pixels

⚠ **Correcting §14.4's own framing.** That section noted the focal call
uses 8× FEWER input tokens than the depiction gate it sits beside (4,402
vs 35,035 — gpt-4o-mini bills images at a much higher token multiplier).
True, and misleading: gpt-5.5 is 33× the input price, so 8× fewer tokens
still lands at **4.4× the cost per call**. Measured with real rates
(gpt-5.5 $5/$30 per 1M, gpt-4o-mini $0.15/$0.60, gpt-5.6-terra $2/$12):

| agent | model | calls | cost | share of LLM |
|---|---|---|---|---|
| **subject_focal** | gpt-5.5 | 34 | **$0.798** | **64%** |
| depiction_check | gpt-4o-mini | 29 | $0.153 | 12% |
| shot_planner | gpt-5.6-terra | 9 | $0.139 | 11% |
| asset_planner | gpt-5.6-terra | 9 | $0.124 | 10% |
| everything else | — | 14 | $0.036 | 3% |
| **LLM total** | | 95 | **$1.250** | |

Against the rest of the video: generated images $0.44, narration $0.14.
So **one camera-aiming feature cost more than image generation and
narration combined**, and ~44% of the video's entire tracked cost, for a
76-second reel.

#### The waste, measured

**97% of a focal call's input was the image** (~4,282 of 4,402 tokens;
the prompt is ~120). And the source stills are far larger than anything
the render can use: median longest edge **1,376 px**, largest **8,009 px**,
with **21 of 34 above the 1,280 px render target**. An 8,000-pixel image
was being uploaded in full to answer "roughly where is the subject".

Five sizes, six assets, drift measured against the full-size answer:

| max edge | avg input tokens | vs full | $/34 shots | mean drift |
|---|---|---|---|---|
| full | 4,944 | 100% | $0.89 | — |
| 1024 | 1,116 | 23% | $0.24 | 0.077 |
| 768 | 767 | 16% | $0.18 | 0.074 |
| **512** | **482** | **10%** | **$0.13** | 0.084 |
| 384 | 378 | 8% | $0.11 | **0.133** |

Drift is flat from 1024 to 512 and only degrades at 384.

#### ⚠ The control that the first read was missing

Full-res→512 across all 34 assets measured 0.131 mean drift, which looks
worse than the 6-asset probe. But that number has no baseline: **the
model is not deterministic.** Running the SAME 512 px images twice:

| comparison | mean | median | max | within 0.20 |
|---|---|---|---|---|
| full-res vs 512 px (test) | 0.131 | 0.110 | 0.518 | 29/34 |
| 512 px run A vs run B (**control**) | **0.081** | 0.051 | 0.483 | 31/34 |

So ~62% of the observed movement is the model disagreeing with itself,
and downscaling adds **+0.05** on top — 5% of frame width, ~36 px on a
720 px frame, comfortably inside the tolerance for aiming a slow push.
Confirmed visually: the 512 px sheet still lands on faces (the
celebrating driver, Hamilton, the kid in the 44 kart, Senna, both helmet
portraits), and the one full-res outlier that had pinned to `0.00, 0.53`
self-corrected to `0.55, 0.64`, on the person.

⚠ **Record the noise floor, because it bounds what this feature can ever
be:** a focal point from this model carries ~0.08 of inherent jitter.
That is fine for aiming a gentle push and rules out any design that
needs the point to be stable frame-to-frame or repeatable across runs.

#### Shipped

`settings.focal_image_max_px = 512`, applied in
`_downscale_for_focal` inside `openai_provider.py` — resize on the
longest edge, re-encode JPEG q88, pass through untouched when already
small, never raise (an unreadable image is not worth failing a resolve
over).

⚠ **Deliberately NOT applied to `check_depiction`.** That gate consumes
83% of all input tokens and would save more, but its accept/reject
balance was calibrated twice (A30/A30a) against full-size images on
gpt-4o-mini. Shrinking what it sees re-opens that calibration. Worth
doing as its own measured task, with the A30a benchmark re-run.

Measured on the real 34-asset backfill, before and after:

| | full-res | 512 px | change |
|---|---|---|---|
| avg input tokens/call | 4,402 | **697** | −84% |
| focal cost per video | $0.798 | **$0.211** | −74% |
| per shot | 2.35¢ | 0.62¢ | |
| LLM total per video | $1.250 | **$0.663** | −47% |
| whole video tracked cost | $1.83 | **$1.24** | −32% |

Across the 15 completed projects in the DB (633 shots): ~$14.9 → ~$3.9.

#### Still open

- **`cost_cents` is 0 on every `llm_call` row.** Every figure in this
  section came from a hand-written price table in a throwaway script.
  A `{model: (in_per_1m, out_per_1m)}` map passed at the `insert` sites
  would make this self-reporting — OQ-4.4, and now clearly worth the hour.
- Downscaling the depiction gate (above), which is the larger prize.
- A global focal store keyed by content hash: sidecars live per project,
  so the same stock photo is paid for again in every project that uses it.

---

## 15. What to pick up next — 2026-08-29

Ordered by "does a viewer notice" first, cost second. Everything here is
scoped from measured evidence in §13/§14, not from the original plan's
guesses.

### 15.1 🔴 Fix the ducking detector (OQ-1b) — the feature that is shipped and inert

**The one-line cause (§13.4):** `speaking_intervals_from_alignment`
splits speech runs on the gap BETWEEN consecutive characters, and
ElevenLabs never leaves one. Measured across six projects: zero
inter-character gaps, one duck interval spanning 100% of every timeline.
The pauses are real but live INSIDE a single character's duration — on
`1cdf55ac`, 17 characters ≥0.30 s (all `'\n'`), 6.56 s total, longest
0.584 s.

**Fix:** split a run when a character's OWN duration exceeds the
threshold, not when the gap between characters does.

⚠ **Correction (P-OQ1b-char):** do **not** use `DUCK_MERGE_THRESHOLD_S`
(0.8 s, captions' min cue) as that split. F1's pauses max at 0.584 s;
0.8 s would still duck 100% of the timeline. Shipped threshold is
`DUCK_CHAR_PAUSE_S = 0.30` (the cutoff §13.4 counted with). When
`characters` is present, only whitespace that long is a pause.

⚠ Re-check §12.3's ramp invariant afterwards: real splits mean real
inter-interval gaps for the first time, so `duck_ramp_windows`' merge
guard finally has something to do.

**Then re-render and listen.** The user has already confirmed by ear that
the bed never comes up; this is the change that would make it.

### 15.2 🔴 RV-Q10 — the voice changes character at scene starts

The only audible defect a human has actually reported (§13.5). Located:
"Training" is character 0 of scene 2 at t=8.80 s, the scene 1→2 join.
Nine scenes, one `voice_id`, **nine separate TTS requests**.

**Fix (real one):** synthesise several contiguous scenes in ONE request,
split on the returned alignment. ⚠ Narration is cached per scene by
content hash and `narration_fit.py` assumes one alignment per scene —
this is real work, not a flag.
**Fix (partial):** pin voice settings so each request starts identically.

⚠ This also retires §4.3's premise: OQ-1c was built for a scene-boundary
LEVEL jump, measured at 0.9 LUFS (inaudible). The audible defect is
timbre, which gain-matching cannot touch.

**Shipped shape (P-OQ-RV-Q10, 2026-08-29).** Contiguous uncached
unique-hash scenes share one `/with-timestamps` call, joined by `\n`,
packed until `tts_request_character_limit` (5000 on `eleven_v3`). The
step still writes one `{content_hash}.mp3` + sidecar + DB row per
scene; `narration_fit` is unchanged. Cached hashes are never
overwritten — a hit in the middle of a timeline breaks the batch.
Existing projects keep their old per-scene audio until N1 retry.
⚠ Listen on a re-narrated `1cdf55ac` is still required; this is the
mechanism, not the ear-sign-off.

### 15.3 🟡 Populate `cost_cents` — every LLM call reports 0

`LlmCallRepository.insert` takes `cost_cents: int = 0` and **no caller
ever passes it**. The repo prices fal images (4¢), fal video (50¢) and
ElevenLabs (per character) but has no LLM pricing at all — so when asked
"what does gpt-5.5 cost us", the system could not answer and §14.7's
whole table had to be produced by a throwaway script with hand-typed
rates.

**Shape:** a `{model: (input_per_1m, output_per_1m)}` map beside the
existing `*_cost_cents_estimate` settings, and `cost_cents=` passed at
the four `insert` call sites (`depiction_check`, `focal_check`,
`constraint_check`, and the planner path). Known rates as of 2026-08-29:

| model | in / out per 1M |
|---|---|
| gpt-5.5 | $5 / $30 |
| gpt-5.6-terra | $2 / $12 |
| gpt-4o-mini | $0.15 / $0.60 |

⚠ Store the rate used ALONGSIDE the cost, or a later price change
silently rewrites history. And treat an unknown model as `None`, never
0 — a missing price must not look like a free call, which is exactly the
failure mode §14.6's rule is about.

This is OQ-4.4, and it is the difference between answering cost
questions in an hour and answering them in a session.

### 15.4 🟡 Downscale the depiction gate — the larger cost prize, gated on re-calibration

`check_depiction` burns **83% of all input tokens** (35,035 per call on
gpt-4o-mini, which bills images at a high token multiplier). §14.7's
512 px change cut the focal call by 84%; the same change here would save
more in tokens.

⚠ **Do not just do it.** A30/A30a calibrated that gate's false-accept /
false-reject balance twice, against full-size images, on that model. Its
whole design is an asymmetric bias that a resolution change could move.
This is its own task: shrink, re-run the A30a benchmark, compare the
rejection table, and only then keep it.

### 15.5 ⚪ Smaller, all measured

- **Global focal store.** Sidecars are keyed by content hash but live in
  each project's assets folder, so the same stock photo is paid for again
  in every project that uses it.
- **Peak guard (§13.3).** Inaudible today, but cap OQ-1c's per-scene
  boost against a peak ceiling and give `loudnorm` real headroom
  (−1.5/−2.0 dBTP) so it cannot get worse with a hotter voice or bed.
- **Sub-frame shots (§13.7).** Two shots at 0.023 s — under one frame —
  against `retention_fast`'s stated 0.8 s floor. Wants an assertion at
  planning time.
- **OQ-3a's gate needs re-measuring (§13.8)** against character
  durations, for the same reason as §15.1. The feature is not dead; the
  measurement looked in the wrong field.

### 15.6 Parked: should we add a non-OpenAI provider?

Asked 2026-08-29 (DeepSeek / Grok / GLM). **Not now**, and the reasoning
is worth recording so it is not re-litigated:

- The focal call is already down to **$0.21/video** after §14.7. What
  remains of the whole LLM bill is $0.66/video; a provider switch cannot
  save more than that, and it costs a new key, a new provider class, and
  — the expensive part — **re-running the full evidence pipeline**
  (bake-off sheet + same-size drift control) before the result can be
  trusted.
- The genuinely interesting technical argument is not price but **native
  grounding**: model families trained to emit bounding boxes / points
  (the Qwen-VL and GLM-V lineages) target exactly "where is X in this
  image", which is the task gpt-4o-mini failed at. That is worth a probe
  IF the focal answer's ~0.08 jitter (§14.7) ever becomes a problem.
- The real blocker on the biggest line item (§15.4) is not the vendor,
  it is the A30a calibration. Provider choice is downstream of deciding
  to re-open that.

⚠ **The harness already exists** (`model_bakeoff.py`): point it at a new
model and it produces a comparable crosshair sheet. Once a key exists,
evaluating a candidate is ~30 minutes. That is the cheap path if volume
ever makes $0.66/video material.

---

## 16. Review of P-OQ-RV-Q10 (batched TTS) — 2026-08-29

Review of the scene-batching work built against §15.2. Findings numbered
`RV-Q11+`, continuing §12's sequence.

**Method.** Diffs read in full; the duration claim was not taken on trust
but measured, by slicing a real narration mp3 from `1cdf55ac` into four
pieces through the production `slice_mp3` and decoding each to PCM.
All 29 new tests pass — which is part of RV-Q12.

### 16.0 Verified good

- **The slices tile the batch exactly.** `audio_end_i ==
  audio_start_{i+1}` by construction (each non-last scene ends where the
  next scene's first character starts), so concatenating every slice
  reproduces the batch with no gap and no overlap. The first slice keeps
  its leading silence (`audio_start = 0.0`), the last absorbs the
  trailing padding via `audio_duration_s`.
- **`char_ends[-1]` now equals the slice's own duration exactly.** This
  incidentally *strengthens* §12.5's open concern: captions and ducking
  both advance their concat clock by `char_ends[-1]` and assume it
  matches real file duration. For batched scenes that is now true by
  construction rather than by luck.
- Guards in the right places: joined-text mismatch, parallel-array length
  mismatch, scene overlap (`next_first < last_abs`), empty text,
  non-positive audio window.
- Cache-flush and duplicate-hash semantics are documented in the module
  docstring rather than left implicit.

### 16.1 🔴 RV-Q11 — BLOCKING: the MP3 re-encode makes every sliced scene the wrong length

`slice_mp3` cuts with `atrim` (sample-exact on decoded PCM) and then
**re-encodes to MP3**, which re-quantises to 1152-sample frames.
Measured on a real narration file, cut into four pieces:

| slice | MP3 (as built) | PCM/WAV |
|---|---|---|
| 0 | **+20.11 ms** | +0.01 ms |
| 1 | **+10.18 ms** | +0.01 ms |
| 2 | **+7.62 ms** | −0.01 ms |
| **total across 4** | **+29.35 ms** | ~0 |

⚠ **The alignment is exact and the audio is not.** The split rebases from
the batch perfectly, so `narration_fit` derives shot durations saying
scene *i* is X seconds while the file on disk is X + 8–20 ms.
`mux_narration` concatenates the real files, so the voice **progressively
falls behind the picture** — ~10 ms per batched scene, ~90 ms on this
9-scene project, several hundred ms on long-form. Captions ride the
alignment clock, so they drift against the audio too.

This is exactly the failure `app/renderer/audio.py`'s docstring exists to
prevent (it records +145 ms over five boundaries and the same "the voice
slowly falls behind" symptom), and exactly the invariant §2.3 states.

**Fix, measured not theorised:** write the slices as PCM/WAV. Sample-exact
at ±0.01 ms. Costs ~5× the bytes (759 kB vs 139 kB for 8.8 s) and two
path literals (`narration.py:387`, `:514`). Nothing downstream cares
about the container — `mux_narration`'s concat filter decodes to PCM
anyway, which is the whole reason it uses the filter and not the demuxer.

*(The last slice showed −24 ms in both codecs, but that is an artifact of
the test asking for `end = whole-file decode duration`; production clamps
the last slice to the probed duration.)*

### 16.2 🔴 RV-Q12 — the test was written to tolerate the defect

```python
# MP3 padding is a fraction of a frame; the cut is 1.000s of PCM.
assert _ffprobe_duration(out) == pytest.approx(1.0, abs=0.08)
```

An **80 ms** tolerance on a defect that measures 20 ms, and only ONE
slice is asserted when the entire failure mode is accumulation across
several. The comment shows the padding was known and absorbed rather
than measured.

⚠ Same shape as this repo's own recorded lesson — `test_music.py`'s
header: *"a new input got a fingerprint test but not a behaviour test"*.

**The test that catches it:** slice a file into N pieces and assert the
**sum** equals the original within ~1 ms.

### 16.3 🟡 RV-Q13 — editing one scene un-does the feature for that scene

`plan_tts_batches` flushing on a cached hash is correct. But
`scripts/edit_narration_text.py` exists: change one scene's words, its
hash changes, and it becomes the ONLY miss in the timeline — so it is
synthesised **alone**, with a fresh performance, while its neighbours
keep their batched one.

That reproduces the exact voice-character discontinuity RV-Q10 exists to
remove, precisely when a human edits a line. At minimum it belongs in the
docstring; the honest fix is re-batching the edited scene with its
neighbours, which means discarding their cached audio.

### 16.4 🟡 RV-Q14 — this change and §15.1's ducking detector now share a field

The joiner pause is absorbed into the previous scene's **last character**
(`rebased_ends[-1] = next_first - audio_start`), so a scene's final
character — normally `.` or `।` — now carries the inter-scene pause and
becomes long.

But §15.1's detector only releases the bed for characters that are
`isspace()`. A stretched `.` is not whitespace, so **the longest pauses
in the video — the scene joins — will never swell.**

Not a regression (they did not swell before either), but this change
creates the data that would make them the best swells available, and it
introduces a long-non-whitespace character shape the detector was never
designed against. Worth a test either way now that two features read the
same field for different purposes.

### 16.5 Recommended order

1. **RV-Q11** — blocking. One codec change plus two path literals.
2. **RV-Q12** — the sum-of-slices test, which is what proves RV-Q11 fixed.
3. **RV-Q14** — decide whether scene joins should swell, and test the
   stretched-last-character shape either way.
4. **RV-Q13** — docstring now, re-batching later if it bites.

⚠ **Do not re-narrate `1cdf55ac` for the listen until RV-Q11 is fixed** —
the audio would be measurably out of sync with the picture, and the
listen would be judging the wrong thing.
