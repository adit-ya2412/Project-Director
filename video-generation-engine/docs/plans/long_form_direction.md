# Long-Form Direction — steering the 16:9 styles, and a vertical camera move

**Status:** DESIGN ONLY. Nothing built, nothing decided, no code touched.
**Written 2026-08-31** at the user's request, off the back of a read of
the style system prompted by two questions: *"I never saw the glitch"*
and *"if we move away from shorts, what more styles can be added?"*

This plan is small on purpose. Unlike `animated_explainer.md` it has no
gate, because there is nothing to measure first: every finding below is
a direct reading of shipped code, and every task is bounded.

---

## Verdict up front

**Long-form has a look system and no direction system.**

Four styles ship. Two are 16:9 — `documentary_archival` (the default)
and `stillness`. Those two are **planner-identical**: same base prompt,
no style fragment, no pacing target, same canvas, same narration speed,
same SFX gate. They differ *only* in colour grade and music gain.

The two styles that got real hand-tuned direction — `retention_fast` and
`archival_montage` — are both hard-coded 720×1280. **All of the
steering work went to vertical.** Moving away from shorts means moving
to the two styles nobody has directed.

Three consequences, each verified below:

1. `stillness`'s own suitability blurb promises *"long static holds, no
   camera motion, deliberate quiet"*. **Nothing implements that.** It is
   a grade and a music mix.
2. The Shot Planner cannot place a chapter card at an act boundary
   because **it is never told which act it is in** — and the act's
   `title` is generated and then discarded before the Timeline is
   written.
3. `PAN` is horizontal-only. `CameraDirection` has no `UP`/`DOWN`, and
   `y_expr` is a constant. On 16:9, over tall archival portraits and
   engravings, the natural move cannot be requested.

**None of this needs a new rendering engine.** Two markdown files, one
enum, one filter branch, and one persisted field.

---

## 0. Navigation — read before writing any code

### 0.1 Pickup protocol

Same rules as `output_quality_pass.md` §0.1 and `animated_explainer.md`
§0.1, restated because this plan will most likely be picked up cold:

1. **Do exactly one lettered task.** Do not bundle. Do not "while I was
   in there."
2. **Write a §7 log entry before finishing**: dated heading, *Scope
   executed*, *Changes* with `file:line`, *Measured* (real numbers, never
   "looks right"), *Verification* (the exact command run), *Effects /
   notes for the reviewer*, *What is NOT done*.
3. **If a finding contradicts this plan, change the plan text in the
   same commit** and say so in the log.
4. **Never mark a visual task done on unit tests alone.** A1, A4 and A5
   all end with a human watching a real render over real archival
   assets. Say *"built, awaiting human pass"* and stop.
5. **Read §2 before touching the renderer.** Those invariants are
   inherited and already paid for in bugs.
6. **Ordering:** **A9 is BLOCKING — a real long-form run failed on it
   (2026-09-01) and nothing else matters until it is fixed. A10 must
   come AFTER A9, never before.** A4 depends on A3. A5 depends on A2.
   A1–A7 are all
   BUILT as of 2026-08-31 — see §7. **A8 (diegetic SFX) is the
   highest-priority remaining slice and is OPEN — its GATE has now
   PASSED.** The first probe (Openverse search) returned 4/10 and
   recommended CLOSE; that verdict was retracted on 2026-09-01 because
   the kill condition measured our own query construction and
   stinger-tuned ranker rather than catalogue availability. The
   superseding approach — GENERATE the sound via ElevenLabs
   `/v1/sound-generation` rather than search for it — was gated
   2026-09-01 and PASSED 10/10 (plausible envelope match, exact
   duration control, ≈$0.70–$0.85 total spend). **Read A8's RESULT
   block before touching it, and do not re-run either probe** — the
   next step is a human listening pass on the files already generated
   in `tmp/sfx-gen-gate/`, then the build. A2 remains
   the highest-value slice already shipped, and is not
   long-form-specific: it fixes every style that uses `pan`, including
   all 19 shorts. Its numbers were measured, not reasoned — see A2's
   tables.

### 0.2 ⚠ START HERE

**A1 — the `stillness` fragment.** One markdown file, zero code, and it
is immediately watchable. It also tests this plan's whole thesis for the
cheapest possible price: *does adding a style fragment actually change
the output the planner produces?* If A1 lands and `stillness` renders
indistinguishably from before, **stop and reconsider §3 entirely** —
every other task here assumes fragments steer real behaviour.

---

## 1. Origin — six findings, all from shipped code

### 1.1 The two 16:9 styles are planner-identical

From `app/script/styles.py::STYLE_PACING_BANDS` and
`app/renderer/grading.py::STYLE_GRADES`:

| | `documentary_archival` | `stillness` |
|---|---|---|
| Canvas | 1280×720 | 1280×720 |
| `target_shot_duration_s` | `None` | `None` |
| min / max shot duration override | `None` | `None` |
| `max_shots_override` | `None` | `None` |
| `narration_speed` | 1.0 | 1.0 |
| `whoosh_enabled` | `True` | `True` |
| Style prompt fragment | **none** | **none** |
| `music_bed_gain_db` / duck | settings default | −22.0 / −28.0 |
| Grade (contrast/sat/bright) | 1.05 / 0.85 / 0.00 | 0.95 / 0.75 / −0.02 |

Note `target_shot_duration_s=None` is **not** a slow target. Per
`StylePacingBand`'s own docstring it means "no pacing FLOOR to check",
because only fast styles can be physically infeasible. Neither style
constrains pacing in either direction.

### 1.2 `stillness` is a look, not a behaviour

`app/script/suitability.py:49` describes it to the model as *"long
static holds, no camera motion, deliberate quiet."* That string is used
at the **script-suitability** stage — to help pick a style. Nothing
carries it into the Shot Planner.

`grep -rn "stillness" app --include=*.py` returns only: the band, the
grade, the `frame_aspect` opt-in, the suitability blurb, and comments
noting it has no pacing floor and no fragment. So a `stillness` project
reaches the Shot Planner with the generic base prompt and its intent→
camera table (`app/prompts/shot_planner/v1.md:21`) — `reveal`→
`pull_back`, `introduce`→`pan`, `emphasize`→`slow_zoom`. It will produce
the same movement mix as `documentary_archival`.

**Not verified by render.** This is a code reading; two outputs have not
been put side by side. A1's human pass is where that gets settled.

### 1.3 How fragments work — and the `camera_language` trapdoor

`app/planners/shot/planner.py:435`:

```python
style_fragment = load_style_fragment(self.name, render_style)
if style_fragment:
    system_prompt = f"{system_prompt}\n\n{style_fragment}"
```

and at `:456`, threaded into the per-scene user content:

```python
suppress_camera_language=style_fragment is not None,
```

So the two mechanisms are **mutually exclusive by design** (Q6: a
fragment that owns camera must not share the request with the Director's
`camera_language`, since the two contradict with no stated precedence).

Today `documentary_archival` and `stillness` have no fragment, which
means they *do* receive the Director's per-project `camera_language` —
a short free-text line like *"static and slow push, no whip pans"*
(`app/prompts/director/v1.md:41`). **Adding a fragment to either style
silently switches that off.** See §4.1.

### 1.4 `PAN` is horizontal-only

`app/renderer/ken_burns.py:232`:

```python
left_to_right = camera.direction != CameraDirection.LEFT
progress = f"(on/{last_frame})" if left_to_right else f"(1-on/{last_frame})"
x_expr = f"(iw-iw/{pan_zoom:.6f})*{progress}"
return ZoompanExpression(
    zoom_expr=f"{pan_zoom:.6f}",
    x_expr=x_expr,
    y_expr=f"ih/2-(ih/{pan_zoom:.6f}/2)",   # constant
)
```

`CameraDirection` (`app/schemas/timeline.py:93`) is `IN / OUT / LEFT /
RIGHT / NONE`. There is no vertical direction to ask for even if the
renderer could execute one.

### 1.5 The Shot Planner has no act context

`_build_user_content` (`app/planners/shot/planner.py:227`) sends: scene
title, narrative purpose, emotion, target duration, numbered narration
fragments, and the Director's period/visual_style/camera_language.

It does **not** send `act_id`, the scene's position in the video, or the
total scene count. The planner cannot know it is at a chapter boundary,
so it cannot deliberately place a chapter card there.

### 1.6 Act titles are generated and then thrown away

`ActPlanOutput` (`app/planners/act/schemas.py`) has `id`, `order`,
**`title`**, `fragment_start`, `fragment_end`.

`app/planners/scene/planner.py:380` carries only the id onto scenes:

```python
scene.model_copy(update={"id": f"{act.id}_{scene.id}", "act_id": act.id})
```

`Timeline` has no `acts` field. The act's title — the one string that
would make a real chapter card — never reaches the Timeline and is not
recoverable from it.

Acts exist only on Path B: `len(fragments) > settings.scene_planner_act_threshold`
(70), giving `min_acts=3`..`max_acts=7` and a 600 s ceiling
(`app/core/config.py:354-361`). **Act presence is therefore already a
reliable long-form signal in the data** — which is why §3 A4 self-gates
on it rather than introducing a fifth style. See §6 Q1.

---

## 2. Inherited invariants — binding, not up for renegotiation

Carried from `motion_new_styles_and_long_form_videos.md`,
`style_extensions.md`, `output_quality_pass.md` and
`animated_explainer.md`. Each was paid for in a real bug.

| | Invariant | What it means here |
|---|---|---|
| **canon 3.1** | Camera decisions are written by the planner, never applied by the renderer from style alone. | A style fragment may *instruct* the planner to prefer `static`; the renderer must never force a movement because the style is `stillness`. A1/A4 are prompt changes, not renderer changes. A deterministic post-gather pass inside `app/planners/shot/planner.py` is still the planner (precedent: `_cap_glitch_transitions`, `_cap_text_cards`) and is allowed. |
| **I5** | Rendering is a pure function of its inputs. | No wall-clock, no RNG, no style-derived motion invented at render time. A4's chapter cards are written into the Timeline, not computed in the renderer. |
| **R2** | Any value that changes render bytes enters `compute_render_fingerprint`. | `camera.direction` already reaches the fingerprint via the Shot payload, so A2's new enum values are covered — **verify this directly, do not assume it.** A3's new persisted act field must be checked the same way: if it can reach a chapter card, it changes bytes. |
| **D1** | Narration is the master clock; picture is fitted to it. | A vertical pan does not get to change a shot's duration, and a chapter card shows for its own shot's window off the rendered clock (`compute_shot_start_times`), never off narration timing. |
| **byte-identical discipline** | New behaviour takes a new branch; existing filter strings do not move. | Stated in `ken_burns.py`'s own comments ("Byte-identical strings so existing tests and cached expressions stay stable"). A2 and A5 must leave every horizontal pan's emitted string unchanged, or every cached render in the system is invalidated for nothing. |
| **§11 DB hazard** | `conftest.py`'s autouse `clean_database` truncates the shared dev Postgres. | Any inspection query against real project timelines runs **before** a pytest session, never after. |
| **style-count discipline** | "Three presets, not eight — every style is a behaviour four planners can regress against." | Four already ship. This plan deliberately adds **zero** new styles. See §6 Q1. |

---

## 3. The build, cheapest first

### A9 — The long-form duration cap applies SHORT-FORM density ⛔ BLOCKING

**Found 2026-09-01 when the first real long-form run died at the
narration step. This is what wrongly blocked a legitimate video.**

The failure, verbatim from `backend.log`:

```
workflow.failed  step=narration
narration-reconciled duration is 316.88s, exceeding
max_video_duration_s (275.80645161290323s)
 - shorten the script; narration is never trimmed to fit
```

**275.8s is not a setting anyone chose.** It is computed in
`resolve_constraint_bundle` (`app/script/styles.py:448`):

```python
implied_duration = (n_fragments / _N_AT_SHORT_CAP) * settings.max_video_duration_s
max_video_duration_s = min(
    settings.max_long_form_duration_s,
    max(settings.max_video_duration_s, implied_duration),
)
```

`_N_AT_SHORT_CAP = 31.0` encodes *"a 90-second short typically has 31
fragments"* — i.e. **~2.9 seconds of video per fragment**. The formula
takes that SHORT-FORM density and extrapolates it to any length. A
documentary runs slower per fragment by nature, so the proxy binds long
before anything real does.

**Measured, for the 95-fragment `documentary_archival` script that
failed:**

| Constraint | Limit | This script |
|---|---|---|
| Hard long-form ceiling (`max_long_form_duration_s`) | **600s** | nowhere near it |
| `max_shots_per_project` | 101 | 82 planned |
| Per-shot bound (`min`/`max_shot_duration_s`) | 0.5s – **8.0s** | **3.34s average** |
| **Real shot capacity** (95 x 8.0s) | **760s** | needed **316.88s** |
| **What actually blocked it** | **275.8s** | — |

Nothing structural prevented a 317-second video. There was room for more
than twice that, and 3.34s per fragment is ordinary documentary pacing
well inside the engine's own per-shot bound.

**The cap's legitimate purpose is already served elsewhere.** It exists
to stop a 10-sentence script being stretched into minutes of 20-second
dead holds — and `max_shot_duration_s = 8.0` prevents exactly that,
directly and precisely, at the level where it is real. The duration cap
is a second, blunter guard doing the same job badly.

### The fix

Bound long-form duration by what the shots can actually CARRY, not by
short-form density:

```python
shots_available = min(max_shots_per_project, n_fragments)
capacity_s = shots_available * max_shot_duration_s
max_video_duration_s = min(
    settings.max_long_form_duration_s,
    max(settings.max_video_duration_s, capacity_s),
)
```

Why this is the honest constraint: a shot may own a CONTIGUOUS RANGE of
fragments, so shots <= fragments, and each shot is bounded by
`max_shot_duration_s`. The product is therefore the true upper bound on
how much video this script's structure can support. Sanity-check the
shape before committing to it:

| Fragments | Capacity | Resulting cap | Sensible? |
|---|---|---|---|
| 20 | 160s | 160s | yes — 20 sentences is not a 5-minute film |
| 95 | 760s | **600s** (ceiling binds) | yes — the failed script now passes |
| 300 | 600s+ | 600s | yes — product ceiling binds |

**Preserve the existing behaviour that more fragments raise the cap** —
`suggestions.py:225` relies on it (*"more fragments raise that cap, which
is why the 196s R21 script starts over 116s and still passes after
suggestions"*). Capacity is linear in fragments, so this still holds.

**Do NOT touch:** the pacing FLOOR check (`target_shot_duration_s`, for
fast styles), the dead-stop ceiling, `max_shots_per_project`, or
`budget_cap_cents` — which is derived from `max_video_duration_s` and
will therefore move as a consequence. **Verify what happens to the
budget cap and report it**; a script now permitted 600s instead of 276s
also gets a proportionally larger spend ceiling, and that may or may not
be wanted.

**Ends in:** unit tests over the fragment/capacity table above, plus a
re-check that the previously-failing script's real numbers (95 fragments,
316.88s narration) now pass. No render needed — this is arithmetic.

---

### A10 — Recalibrate chars/sec: the constant is measured on a model we no longer use

**Do NOT do this before A9.** On its own it makes things WORSE for the
user: a correct estimate would have said 317s and the preflight would
have confidently rejected a script the engine is perfectly capable of
making. A9 first, then this.

`script_chars_per_second_en = 14.4`, and `config.py:374` says exactly
what it was calibrated against:

> Calibrated for the configured voice against live **Multilingual v2**
> (Q8, 2026-08-20): English 15.1, Hinglish 14.0, Hindi 14.9 — one
> constant near 14.4 lands within 5% of all three.

`settings.elevenlabs_model` is now **`eleven_v3`**. The constant was
measured on a model the pipeline no longer uses.

**Measured from the failed run** (one data point, one script, one voice):

| | |
|---|---|
| Script | 3,910 chars, 95 fragments |
| Estimated at 14.4 chars/s | 271.5s |
| **Measured narration** | **316.88s** |
| Overshoot | **+16.7%** |
| **Implied real rate** | **12.34 chars/s** |

Corroboration already in the tree: `styles.py` records that
`retention_fast`'s speed was bumped *"the same day v3 exposed how much
v3's own natural pacing varies call to call."* v3's different pacing was
already known; the preflight constant just never got re-measured.

**It fails in the worst direction.** The preflight exists to catch this
BEFORE money is spent. An over-optimistic estimate defeats its whole
purpose: this run paid for Director, Act Planner, Scene Planner, Shot
Planner, asset resolution across 82 shots AND full narration synthesis
before dying at reconciliation.

**Do not hard-code 12.34 from a single sample.** Measure across at least
two or three real scripts of different language mixes, and carry a margin
for v3's own call-to-call variance. Consider whether the honest fix is a
rate plus an explicit safety factor rather than a single tighter number —
an estimate that is slightly pessimistic costs an unnecessary edit; one
that is optimistic costs a full pipeline run.

**Ends in:** the measured numbers per script, a chosen constant with its
margin justified, and the `config.py` comment updated to name
`eleven_v3` and the date — so the next model switch has an obvious place
to look.

---

### A8 — Diegetic SFX: a sound placed against a narrative beat ⭐ HIGHEST PRIORITY

**Raised to the top of this plan by the user on 2026-08-31**, off the
back of writing the Project Chagan script and asking whether the engine
could execute its direction. Mapping that script's cues against the code
gave the answer: **~70% of its VISUAL direction is already achievable,
and ~20% of its AUDIO direction is.** The script's most distinctive
moments are the ones the engine cannot express:

- *"a faint sound of a Geiger counter clicking"* (opening)
- *"Complete silence for 2 seconds. Then a massive explosion SFX."*
- *"Faint heartbeat slowing down"* (closing)

### Why it cannot express them today

`SfxKind` has exactly three values, and all three are **structural** —
they fire off editing events, never off content
(`app/renderer/sfx.py::derive_sfx_events`):

| Kind | Fires when |
|---|---|
| `WHOOSH` | a `punch_in` snap happens |
| `STINGER` | a `text_card` starts |
| `TRANSITION` | a non-cut xfade overlaps |

Placement is derived entirely from `compute_shot_start_times` plus those
three shot properties. **There is no way for anything to say "play this
sound, here, because the story asks for it."** That is the whole gap.

### What already exists and is reusable — the reason this is tractable

Do not rebuild any of this:

- **A searchable, FREE provider.** `OpenverseMusicProvider` is wired for
  SFX behind `settings.sfx_provider` ("openverse"), described in
  `select_sfx.py` as *"Free Openverse search, same licence gate as music,
  different queries."* Free search means the gate below costs nothing but
  time.
- **Per-kind query lists.** `select_sfx.py::_DEFAULT_QUERIES` already
  maps kind -> search terms. Diegetic makes those terms planner-authored
  per cue instead of a fixed constant.
- **Ranking, licence gating, download, content hashing, loudness
  normalisation** — `app/assets/sfx_ranking.py`, `SfxClipSelection`.
- **N-overlay mixing.** `mux_sfx` already amixes an arbitrary number of
  delayed overlays with per-overlay `volume_factor` and `trim_start_s`.
- **Per-kind gain overrides.** `sfx_whoosh_gain_db` /
  `sfx_stinger_gain_db` / `sfx_transition_gain_db` already exist as
  `None`-means-use-the-flat-setting fields. A `sfx_diegetic_gain_db`
  drops straight into that pattern.

### Approach, revised 2026-09-01: GENERATE the sound, don't search for it

The user asked whether SFX could be generated the way images and clips
already are. **That is the right answer and it supersedes both earlier
approaches.** Compared side by side:

| | Openverse search | Curated local library | **Generated** |
|---|---|---|---|
| Returns the sound actually asked for | ✗ — gate scored 4/10 | ✓ but only what was stocked | **✓ anything** |
| Vocabulary ceiling | the catalogue | the manifest | **none** |
| Curation effort | none | user supplies every file | **none** |
| Duration control | whatever exists | whatever was supplied | **requested** |
| Licence gate | CC0/CC-BY filtering | source terms | **not applicable** |

The duration row is worth more than it looks: the 1.5s trim problem
(`sfx_max_clip_s`, baked into both `sfx_ranking.py` and `mux_sfx`) exists
because structural stingers are short and the library holds only short
clips. **Requesting a 15-second Geiger counter dissolves that problem at
the source** rather than needing a second duration policy.

**The provider already exists.** ElevenLabs is integrated at
`https://api.elevenlabs.io` for narration
(`/v1/text-to-speech/{voice_id}/with-timestamps`, `app/providers/
elevenlabs.py`), and `settings.elevenlabs_api_key` is configured. Its
sound-generation endpoint is the same host, same key, same auth — so
this is a new method on a working integration, not a new vendor.
fal.ai is the alternative (already used for images and Kling video) and
hosts text-to-audio models.

**I5 is satisfied by the CACHE, not by a seed.** Generated audio may not
be seedable, and that is fine: `generation_prompt_hash(prompt, model_id,
seed, …)` -> look up by hash -> reuse if present is exactly how generated
images and clips already hold I5 today
(`app/workflow/steps/resolve_assets.py:265`). Hash the cue phrase plus
model plus duration, store the bytes, and every re-render reuses them
byte for byte. **Caching is therefore mandatory, not an optimisation.**

Everything downstream is untouched: content-hash the clip, hand it to the
existing `SfxOverlay` / `mux_sfx` chain, which already amixes N delayed
overlays with per-overlay gain and trim.

---

### ⛔ GATE — generate the ten cues and listen

**⚠ This gate spends real money.** `dry_run` is `False` and the
ElevenLabs key is live. Ten short generations is a small spend, but it is
not zero — keep the volume to ten cues, report the measured cost, and do
not loop or retry beyond what is needed.

**Step 1 — verify the API contract from the vendor's own documentation,
not from memory.** Endpoint path, request shape, duration parameter and
its maximum, output format, whether a seed is accepted, and how cost is
billed. Nobody has confirmed these. If the endpoint does not exist as
expected, STOP and report rather than improvising.

**Step 2 — generate these ten cues**, taken from the Project Chagan
script and from what a documentary planner would plausibly write:

```
faint Geiger counter clicking, sparse and distant
distant underground nuclear explosion, deep boom, muffled
slow heavy heartbeat, quiet
desolate wind across an empty steppe
murmuring crowd in a large hall, 1960s
manual typewriter keys, single sentence
heavy industrial machinery hum, continuous
water lapping gently against a shore
radio static and tuning between stations
a single church bell toll, distant
```

Ask for a duration suited to each (ambience long, a bell toll short) so
the result also tests whether duration control works.

**Step 3 — report, per cue:** requested duration vs delivered, file size,
measured cost, and **whether it is plausibly the sound named**. You
cannot literally hear it: use ffprobe on the waveform for what it can
actually establish (a heartbeat is quiet with periodic peaks; static is
broadband and flat; a bell has a sharp onset and long decay), and say
explicitly what you verified versus inferred. **Never claim a clip "is"
the sound because the prompt said so — that is the exact error the
Openverse gate made in reverse.**

**Step 4 — put the files where the user can listen**, in
`tmp/sfx-gen-gate/`, alongside a `REPORT.md`. Where the earlier Openverse
gate downloaded a candidate for the same concept
(`tmp/sfx-gate/` — heartbeat, typewriter, radio static, water, geiger,
machinery), name the generated file so the two sit side by side for
comparison. **The user's own ears are the verdict, not the report.**

**Kill condition:** if generated audio is unusable for most cues, close
this approach and fall back to the curated-library path the user offered
(YouTube Audio Library files, `LocalSfxProvider` already supports it —
`settings.sfx_provider` already defaults to `"local"`). That fallback is
real and cheap, so failing this gate costs one afternoon, not the
feature.

---

### RESULT (2026-09-01) — PASS. Do not re-run this gate.

Full measurement in §7's `P-LF-A8-GEN-GATE` entry; generated files and
`REPORT.md` in `tmp/sfx-gen-gate/`. Summary for a reader who should not
need to open either:

- **API contract confirmed against ElevenLabs' own docs**, not memory:
  `POST /v1/sound-generation`, `duration_seconds` 0.1–30s (auto if
  omitted), no seed parameter, billed 40 credits/second when duration is
  specified. Matches what this section assumed above.
- **10/10 cues generated, 10/10 hit their exact requested duration**
  (`ffprobe`-verified to the millisecond). No retries needed.
- **10/10 envelope analyses at least plausible, 4/10 diagnostic-strength**
  (heartbeat's paired ~45–55 BPM onsets, machinery hum's near-zero
  variance, the bell's sharp-attack/clean-decay, Geiger's sparse
  irregular clicks). No cue produced an outright red flag. Verified:
  loudness, variance, onset timing, attack/decay shape. NOT verified:
  timbre, pitch, frequency content, or qualifiers like "muffled,"
  "distant," "1960s" — no spectrogram was taken.
- **Cost ≈$0.70–$0.85 total** for all 10 (4,160 credits at the
  documented rate; the account's exact debit could not be read — the API
  key lacks `user_read` — so this is a bounded estimate from ElevenLabs'
  published plan rates, not a measured figure).
- **Kill condition NOT triggered.** Generated audio is not "unusable for
  most cues" — it is at minimum plausible for all 10 and directly fixes
  the two motivating exotic cues (Geiger counter, nuclear explosion)
  that the Openverse probe scored 0/2 on.
- **Next step is a human listening pass**, not more measurement.
  `tmp/sfx-gen-gate/REPORT.md` names 3 A/B pairs to listen to first
  (Geiger counter, machinery hum, heartbeat) against the pre-existing
  `tmp/sfx-gate/` candidates. Only if the user's ears approve does the
  "If the gate passes — the build" section below start.

---

### GATE HISTORY — the Openverse probe (2026-08-31), kept for the record

The first A8 gate probed **Openverse search** and scored 4/10, and its
own kill condition said CLOSE. That verdict was retracted 2026-09-01:
the kill condition measured *our query construction and our
stinger-tuned ranker*, not catalogue availability. Verified against the
live provider — every "no content" cue returns a full page once the
phrase is shortened:

| Cue as written | Candidates | Shortened | Candidates |
|---|---|---|---|
| `nuclear explosion distant boom` | **0** | `explosion boom` | **10** |
| `wind across empty steppe` | **0** | `wind` | **10** |
| `crowd murmur 1960s` | **0** | `crowd murmur` | **10** |
| `church bell single toll` | **0** | `church bell` | **10** |

Openverse does near-AND matching, so a verbatim multi-word planner phrase
defeats itself. Two further "failures" (`geiger counter clicking`,
`factory machinery hum`) were ranking failures, not search failures — the
correct clip sat at #2 and #4 while `sfx_ranking.py` preferred something
short, because it prefers clips fitting `sfx_max_clip_s` (1.5s) and then
*"shorter among those"*.

**Generation makes both of those moot** — there is no query to construct
and no candidate to rank. The measurements are preserved in §7's
`P-LF-A8-GATE` entry and the downloaded audio in `tmp/sfx-gate/`.

**Lesson kept deliberately:** a gate can only measure what its kill
condition names. That one conflated catalogue availability with our own
retrieval quality, and would have closed a viable feature on the strength
of a bug in our query string.

---

### If the gate passes — the build

1. **A planner-authored cue on the Shot.** A field carrying the sound
   the story wants (e.g. `sfx_cue: str | None`), empty on the vast
   majority of shots. Canon 3.1: the planner decides WHAT sound and
   WHERE; the renderer only executes. Never derived from style.
2. **A generation provider method + mandatory prompt-hash cache**,
   following `generation_prompt_hash` exactly. Cache miss generates and
   stores; cache hit reuses bytes. This is what holds I5.
3. **`SfxKind.DIEGETIC`**, plus `sfx_diegetic_gain_db` following the
   existing `None`-means-flat-setting pattern
   (`sfx_whoosh_gain_db` etc. already do). It plays UNDER narration,
   unlike a stinger punctuating a card, so its level is a separate
   question needing its own listening pass.
4. **Its own duration ceiling.** `sfx_ranking.py`'s ≤1.5s preference and
   `mux_sfx`'s `atrim=0:{sfx_max_clip_s}` are correct for punctuation and
   wrong for ambience. Do NOT simply raise `sfx_max_clip_s` — that would
   lengthen every whoosh and stinger too.
5. **One branch in `derive_sfx_events`** — an event per cue-bearing shot.
   v1 places at the shot's start; see the open questions.
6. **R2**: the cue field and every generated clip's content hash must
   reach `compute_render_fingerprint`, or the cache serves audio from a
   previous cue set.
7. **Cost accounting and a per-project cap**, in the manner of
   `fal_video_cost_cents_estimate` and `max_video_shots_per_project`. An
   SFX under every shot is a sound bed, not direction, and it will bury
   the narration.
8. **Prompt wording** so the Shot Planner writes cues sparingly, and only
   where the story genuinely turns on a sound.
9. **Keep `LocalSfxProvider` as an override.** For any cue where a real
   recording beats a generated one — a specific period crowd, say — the
   library path already exists and should stay reachable rather than
   being deleted.

### Open questions — decide with a render, not a preference

1. **Placement precision.** Shot start is the honest v1 and is crude:
   the script wants the explosion on a specific WORD, not at a shot
   boundary. Narration-span-relative placement is the real answer
   (`narration_span` is already on the Shot) but it is a second
   mechanism. Ship shot-start first and listen before deciding.
2. **Ducking interaction.** Music already ducks under narration. A
   diegetic clip is a third layer — does it duck too, or sit above the
   bed and below the voice? Unmeasured.
3. **Scripted silence is NOT this slice.** *"Complete silence for two
   seconds"* is a narration/music gap, not an SFX one. Out of scope; do
   not let it expand this.
4. **Does `documentary_archival` want it more than `retention_fast`?**
   `retention_fast` already disables WHOOSH because density buried it. A
   diegetic layer may want to be style-gated from the start.
5. **Generated versus real, per cue.** Generation wins on availability
   and duration control. A real recording may still sound more authentic
   for period-specific material. The gate's side-by-side against
   `tmp/sfx-gate/` is the first evidence either way.

**Ends in:** the gate report and the generated files, alone. Then, only
if the user's ears approve, a real render with two or three cues on a
real project.

---

### A1 — A real `stillness` fragment (pure prompt, zero code)

New file: `app/prompts/shot_planner_styles/stillness.md`, in the same
shape as `retention_fast.md` — a "Style override" heading, an explicit
statement that it overrides the base where they conflict, and everything
else (one idea per shot, intent, historical grounding) still applying.

What it must say, to make the style match its own description:

- **`static` is the default movement, not one option among seven.** The
  base intent→camera table is overridden outright.
- **Exactly one permitted move:** `slow_push` at `intensity` ≤ 0.10,
  used sparingly on a shot the narration genuinely lingers on.
  `punch_in`, `pull_back`, `slow_zoom`, `pan` and `split_frame` are all
  off-limits — they are the vocabulary of a style with momentum.
- **Transitions: `cut` and `dissolve` only.** No `wipeleft`, no
  `fadeblack`, no glitch. Restraint is this style's whole thesis.
- **Prefer the coarsest fragment granularity** — combine fragments into
  longer shots wherever they hold as one idea. The inverse of
  `retention_fast`'s instruction, and the reason the band's lack of a
  pacing floor is finally usable.
- **Text cards: near-never.** This style says less, not more.

⚠ This switches off the Director's `camera_language` for `stillness`
(§1.3). That is *intended* here — a fixed, hand-tuned override is
exactly what "no camera motion" needs, and a per-project invented line
is what currently fails to deliver it. Say so in the log.

**Ends in:** one `stillness` render and one `documentary_archival` render
of the **same script**, watched side by side by a human. Report the
movement histogram of both timelines (counts per `camera.movement`) as
the *Measured* line — that is a real number, and it is the number that
proves or kills §1.2.

### A2 — Fix `PAN` travel (moving-crop mechanism, both axes)

**Measured 2026-08-31 against real assets from `Oil and War`, at both
canvases. The numbers are identical to the decimal on both axes:**

| | today | moving crop |
|---|---|---|
| Working canvas | output aspect x 1.6 | full scaled image |
| Source extent kept after crop | **31.6%** | 100% |
| Pan travel available | 150 px - **4.1%** | 1555 px - **68.4%** |

A landscape 2980x1676 archival photo on `retention_fast`'s 720x1280
canvas keeps 31.6% of its width and pans across 4.1% of it. A 720x1280
portrait on `documentary_archival`'s 1280x720 canvas keeps 31.6% of its
height and pans across 4.1%. Same arithmetic, because the working canvas
is always output-aspect x 1.6 and `pan_zoom` never changes.

**So this is not a long-form feature and never was.** Every horizontal
pan in every shipped short is crawling across 4% of a frame that already
discarded two thirds of the photograph. This slice fixes travel on the
axis that ALREADY EXISTS, which is where the entire value is.

**The mechanism - and why this plan's original approach cannot work.**
This plan first proposed "give a vertical-pan shot extra canvas height."
That is impossible: `zoompan` crops a region of `iw/z` x `ih/z`, so the
region always inherits the *canvas* aspect ratio - a taller canvas
squashes the output. The correct mechanism is to leave `zoompan` out of
`PAN` entirely and use a time-varying `crop`:

```
scale=-2:{out_h},crop={out_w}:{out_h}:'(iw-{out_w})*<progress>':0
```

Verified by real render (`tmp/pan-demo/5_SHORTS_movingcrop_horizontal.mp4`).

**GATE - travel MUST be a function of intensity AND shot duration.**
Full 68.4% travel is correct at 5 s and violent below 3 s - measured:

| shot length | full travel | reads as |
|---|---|---|
| 5.00 s (documentary) | 311 px/s - 43% of frame width per second | a camera |
| 2.25 s (`archival_montage`) | 691 px/s - 96% per second | a whip pan |
| 1.75 s (`retention_fast`) | 889 px/s - **123% per second** | unusable |

`retention_fast` and `archival_montage` carry the most pans and have the
shortest shots, so a naive "traverse everything" ships this feature
broken precisely where it is used most. Cap travel by a target
px/second rather than a fraction of the image, and let a short shot
simply travel less. Pick the ceiling from the viewing pass, not from
this table.

**Scope:**

1. `PAN` moves off `zoompan` onto the moving-crop chain, horizontal
   first - no new enum values, no prompt change, no style gating.
2. Travel scales with `camera.intensity` and is capped by a px/second
   ceiling derived from `duration_s`.
3. `intensity=0` must still degrade to no visible motion, never a crash
   - the existing contract.
4. Every NON-pan movement's emitted filter string stays byte-identical.
   `PAN`'s own string necessarily changes; that is this slice's point.

**The cache hazard, and it is not the obvious one.** R2 says any *value*
that changes render bytes enters the fingerprint. A code change is not a
value. So an unchanged timeline re-rendered after this ships matches its
old fingerprint, hits the cache, and serves the OLD pan. Confirm whether
`compute_render_fingerprint` carries any renderer version or code
identity; if it does not, decide deliberately whether this slice bumps
something. The user has said old projects do not matter - that is about
*content*, not about a cache silently serving stale bytes for new work.

**Open design question:** the pre-`zoompan` crop was where
`_ken_burns_aim` mapped the subject focal. With the whole image now
traversed, focal stops being "where to crop" and becomes "where to start
and end" - or is dropped for `PAN`, consistent with today's rule that a
pan does not retarget on its axis of travel. Decide with a render.

**Ends in:** the same landscape asset rendered at 1.75 s, 2.25 s and
5.00 s, plus the old behaviour, in `tmp/pan-demo/`. The *Measured* line
states px/second and travel percentage for each.

### A3 — Persist act titles into the Timeline (no visible change)

Prerequisite for A4, and worth doing on its own terms: an act's title is
a creative decision and currently vanishes (§1.6).

Add acts to the Timeline as a first-class list (`id`, `order`, `title`),
written by `_plan_hierarchical` alongside the `act_id` stamping it
already does. Prefer this over an `act_title` denormalised onto every
Scene — the title belongs to the act, and I1/I2's "immutable decision
record" argument applies to it exactly as it does to a locked asset.

Empty on every Path A project and every timeline that predates the
field, matching how `act_id` itself already behaves.

Check against R2: if the field can reach a chapter card it changes render
bytes. Verify whether it lands inside the fingerprint payload or in
`_TIMELINE_BOOKKEEPING_FIELDS`, and state which in the log.

**No user-visible change.** This slice ends in tests, not a viewing pass
— the one task here that legitimately can.

### A6 — Thread render context into the Shot Planner (needs A3)

Split out of A4 on 2026-08-31: A4 was two changes wearing one name — what
the planner KNOWS, and what it is TOLD TO DO. This slice is the first.
A4 and A5 both depend on it, which is why it is its own task.

`_build_user_content` (`app/planners/shot/planner.py:227`) currently
sends scene title, narrative purpose, emotion, target duration, the
numbered narration fragments, and the Director's
period/visual_style/camera_language. Add two families of context:

**Act context** (needs A3's persisted titles):

- the scene's `act_id` and its act title
- whether this scene **opens** an act
- optionally the act's ordinal (act 2 of 5) — a ten-minute plan reads
  differently at the start than three-quarters through

**Canvas context:**

- the resolved output resolution and aspect from
  `resolve_render_format(style, frame_aspect=...)` — the planner is
  choosing `framing` and `split_frame` today with no idea whether the
  frame is 720x1280 or 1280x720

Both are absent for the same reason and land in the same function, so
they are one slice. Path A projects (<=70 fragments) have no acts, so the
act fields must be omitted entirely rather than sent empty — an empty
`act_id:` line invites the model to invent structure that is not there.

**Do NOT change any prompt wording in this slice.** Adding context the
base prompt never mentions is inert by construction, which is exactly
what makes this safely separable from A4. Verify inertness: a Path A
project's user content must be byte-identical to today's.

**Ends in:** unit tests on `_build_user_content` for a Path A scene
(byte-identical) and a Path B scene (act + canvas lines present). No
render, no viewing pass — nothing visual changes.

---

### A4 — Long-form direction for `documentary_archival` (needs A3 + A6)

New file: `app/prompts/shot_planner_styles/documentary_archival.md`,
plus threading act context into `_build_user_content` (§1.5): the
scene's `act_id`, its act title, and whether this scene **opens** an act.

The fragment's long-form clauses must **self-gate on act presence** —
"if you are told this scene opens an act, …". A Path A project (≤70
fragments) is never told it is in an act, so short 16:9 work is
unaffected without needing a fifth style name (§6 Q1).

What it should say:

- **Chapter structure.** On a scene that opens an act, the first shot
  may carry a `text_card` naming the chapter. Elsewhere, text cards stay
  as rare as the base prompt already says.
- **`fadeblack` is the act boundary transition**, and only that. This
  gives the base prompt's "genuinely deliberate structural beat" an
  unambiguous referent instead of leaving the model to invent one.
- **Slower shot grammar at length.** Prefer longer holds and combined
  fragments; `punch_in` is off-limits; keep `intensity` at the base
  0.10–0.25 restraint band.
- **Vertical pan is available** (after A2) for tall subjects.
- **Visual variety across ten minutes is a real constraint** — do not
  let one movement dominate an act.

**Open sub-question, decide with a render, not a preference:** whether
chapter cards are better placed by the model (told it opens an act) or
deterministically in a post-gather pass keyed off act boundaries, in the
manner of `_cap_text_cards`. The deterministic route is more reliable
and needs the act title from A3; the model route can phrase a card that
fits the scene. Try the prompt route first — it is reversible — and note
that `_cap_text_cards`' `text_card_min_shot_gap` (4) may silently drop a
chapter card that lands too close to an ordinary one. **That
interaction is the likeliest way A4 ships looking fine and quietly
broken.**

⚠ Same `camera_language` suppression as A1, and here it is a much bigger
deal: `documentary_archival` is `settings.default_render_style`, so this
changes the default path for every landscape project. See §4.1.

**Ends in:** one full long-form render (>70 fragments, so acts actually
exist) watched end to end by a human, with the act-boundary cards and
`fadeblack` transitions checked against the act ranges from
`act_time_ranges`.

### A5 — The vertical axis, gated to landscape canvases (needs A2 + A6)

Deliberately AFTER and SEPARATE from A2. A2 delivers the entire measured
value on the existing axis; this slice adds a second axis, and its main
cost is not the arithmetic - it is knowing when the axis is legal.

1. `CameraDirection` (`app/schemas/timeline.py:93`) gains `UP` and
   `DOWN`. Mirror A2's moving-crop chain onto `y`.
2. State the convention in the code comment the way the `LEFT` comment
   already does, and choose it so an undirected vertical pan has a
   sensible default.

**The gating problem, which is the real work.** The enum is global, so
every style can request `UP`/`DOWN` the moment it exists. Vertical pan
only makes sense when the frame is wider than the subject - a landscape
canvas. Today:

| Style | Canvas | Pan stance | Would use vertical pan |
|---|---|---|---|
| `documentary_archival` | 16:9 | no fragment, base prompt governs | yes - correctly, the target |
| `stillness` | 16:9 | A1's fragment bars `pan` outright | never |
| `retention_fast` | 9:16 | `pan` allowed as an `introduce` variety beat | occasionally - wrong axis |
| `archival_montage` | 9:16 | "`pan` and `slow_push` carry most shots" | heavily - wrong axis |

And the Shot Planner **is never told the output aspect** -
`_build_user_content` sends scene, purpose, emotion, duration,
fragments, period and visual_style, and no resolution. So the base
prompt cannot say "vertical when the frame is wider than the subject"
and expect the model to reason about it; it does not know what shape
frame it is planning for. **A6 supplies this** — do not re-solve it
here. This slice only adds the prompt wording that consumes it, plus a
validator that rejects `UP`/`DOWN` on a portrait canvas so an
out-of-band planner choice fails loudly rather than rendering a pan with
nowhere to go.

⚠ **A6 gated canvas context on ACT presence, so Path A projects do not
receive it.** That was this plan's fault, not the implementer's — A6's
own "Ends in" line asked for act and canvas lines together, and it was
built to spec and flagged. Consequence for A5: a SHORT 16:9
`documentary_archival` project is Path A (≤70 fragments), so it never
learns it is landscape, and this slice's vertical-pan gate has nothing
to gate on there.

**A5 must decouple them**: emit the canvas line whenever a
`RenderFormat` is resolved, independent of `act`. Understand what that
costs before doing it — it breaks A6's byte-identity property, because
every existing Path A project (which is ALL 19 shipped shorts, at
~50–58 fragments each) would start receiving a canvas line it does not
get today. That is acceptable HERE and only here, because A5 is already
a prompt-wording change; it was not acceptable in A6, which was
deliberately inert. Update A6's byte-identity test rather than deleting
it: Path A output should become "today's string plus exactly one canvas
line", still asserted exactly.

**Ends in:** a human watching a vertical pan over a real tall archival
photograph on a 16:9 canvas, plus a check that no 9:16 style planned one.

---

### A7 — Chapter cards must outrank ordinary cards in `_cap_text_cards`

**A real bug, reproduced by A4's implementer on 2026-08-31 and confirmed
independently. It makes A4 look broken when A4 is correct.**

`_cap_text_cards` (`app/planners/shot/planner.py:122`) walks every shot
in project order, keeps the first `text_card` it sees, and clears any
card landing fewer than `settings.text_card_min_shot_gap` (4) shots after
the last kept one. It has no concept of a CHAPTER card versus an ORDINARY
card — `text_card` is a bare string to it, and the function was written
before act structure had any visual expression.

**The failure, exactly:**

1. Act 1's last scene puts an ordinary card on its final shot.
2. Act 2's first scene — an act-opening scene — puts A4's chapter card
   on its first shot. One shot later, `min_gap` is 4.
3. The chapter card is cleared. Only a generic
   `shot_planner.text_card_gap_*` warning is logged.

Reproduced directly with no DB and no LLM: the chapter card came back
`None`. So the visible payoff of A4 — a chapter title at each act
boundary — can silently vanish, and a human watching the render would
reasonably conclude the fragment does not work.

**The fix, and why it needs no schema change.** A6 already computes
`opening_scene_ids` inside `ShotPlanner.plan()`. Thread the act-opening
shot ids into `_cap_text_cards` and give them precedence:

- A chapter card is NEVER cleared.
- An ordinary card yields instead when the two collide — clear the
  ordinary one, keep the chapter one, and reset the gap counter from the
  chapter card.
- Two chapter cards cannot realistically collide (acts are minutes
  apart), but assert the behaviour rather than assuming it.

Keep the existing "silently correct + log" contract
(`style_extensions.md` §2.7): the model was structurally denied the
information needed to space cards across scenes, so a hard failure would
punish it for the architecture. Extend the log line to say WHICH kind of
card was dropped — the current message cannot distinguish the two, which
is why this went unnoticed.

**Scope is exactly one function plus its caller.** Do not touch the
fragment, the base prompt, `text_card_min_shot_gap`, or anything in
`app/renderer/`.

**Ends in:** unit tests — the collision above keeps the chapter card and
drops the ordinary one; ordinary-only spacing is unchanged from today;
a Path A project (no acts, so no chapter cards) behaves byte-identically.
No render, no viewing pass.

---

## 4. Cautions, in the order they will bite

### 4.1 `suppress_camera_language` is the sharp edge

Adding a fragment to a style that never had one is not additive. It
silently removes the Director's per-project `camera_language` from the
request (§1.3). For `documentary_archival` — the default style — that
changes the default path for every landscape project in the system.

Do not treat this as a side effect to be noted afterwards. For A4 it is
a **deliberate trade**: a fixed hand-tuned override in exchange for a
per-project invented line. The A4 log entry must state which one the
watched render actually preferred. If the Director's line was doing real
work, the honest outcome is to keep it and drop the fragment's camera
clauses instead.

### 4.2 The 9:16 styles carry the most pans and the shortest shots

`archival_montage` says "`pan` and `slow_push` carry most shots" and
`retention_fast` allows `pan` as a variety beat - and their shots are
2.25 s and 1.75 s. A2's travel ceiling therefore lands hardest exactly
where the feature is used most. Full travel at 1.75 s measured 123% of
frame width per second; anyone who ships A2 without the duration cap
will have turned every short's pans into whip pans and will not find out
from a unit test.

### 4.3 Two styles, one base table — do not fix this twice

A1 and A4 both override the same base intent→camera table from opposite
directions. Resist factoring the shared parts into a third file after
A1 lands; `retention_fast.md` and `archival_montage.md` already
duplicate freely, and the plan that introduced them chose "one base
prompt plus one optional style fragment" over per-style prompt files
deliberately. Four independent fragments is the intended shape.

### 4.4 Long-form CAPABILITY is already built — do not rebuild it

Checked directly on 2026-08-31 before scoping A3/A6/A4. Every renderer
layer is already aspect-aware, and none of it is a gap:

| Layer | 16:9 handling, verified |
|---|---|
| Captions | sized off the LONG side (`max(width, height)`), so 720x1280 and 1280x720 get the same 58 px caption, plus a landscape-specific `margin_v` — `captions.py:734` |
| Text cards | same long-side sizing — `text_cards.py:110` |
| Split-screen | 9:16 vstack, **16:9 flips to hstack** — `split_screen.py:3` |
| Watermark | scales by width percentage |
| Canvas | `resolve_render_format` returns 1280x720 for both 16:9 styles |
| Duration | length-aware, implied from fragment count, 600 s ceiling — `styles.py:448` |
| Structure | acts + per-act music beds wired end to end — `timeline/acts.py`, `select_music.py:132` |
| Generated assets | requested at the style's own canvas, and `generation_prompt_hash` includes width/height so a 16:9 project regenerates rather than reusing a 720-wide entry |
| Asset ranking | `rank_candidates` receives `target_width/height` from `resolve_render_format`, and scores BOTH resolution adequacy and orientation match against it — `resolve_assets.py:1302`, `ranking.py:130/199` |

Two consequences for anyone picking this up:

1. **The "56% of assets are under 1280 wide" figure is not a defect.**
   It is 461 generated assets sized for past 9:16 projects. New 16:9
   work generates at 1280x720, and searched archival is already
   resolution- and orientation-ranked against the real target. This was
   briefly mis-ranked above A3/A4 during planning; it is closed.
2. **What remains is DIRECTION, not capability.** A3/A6/A4 exist because
   `documentary_archival` is the least-steered thing in the system, not
   because the pipeline cannot render sixteen-by-nine.

Two numbers worth knowing before a real run: acts require **>70
narration fragments** (~3.4 min — below that there is no chapter
structure to direct), and the budget cap scales linearly with length, so
a 10-minute project caps at **~$67** (`styles.py`: 600 s x 1000¢ / 90 s).

---

### 4.5 Nothing here fixes the glitch, and that is correct

The glitch transitions are gated by a prompt trigger — *a signal
failing, a deception being exposed, technology glitching out* — that
archival/historical content almost never satisfies, then capped to one
per video by `_cap_glitch_transitions`. Both gates are working as
designed. **Do not widen either from inside this plan.** If glitch
should appear more often, that is a new style whose *content register*
calls for it (an investigative style), not a loosened cap on the
documentary styles. Out of scope; recorded here so the next reader does
not re-derive it.

---

### 4.6 Every `--noconftest` suite run leaks ~92 project rows

Not a product bug, but it will cost every implementer time, so budget
for it. `conftest.py`'s autouse `clean_database` is what normally removes
unit-test project rows; `--noconftest` — mandatory here to protect the
user's 21 real projects — skips that cleanup too. **The safety flag and
the leak are the same decision.**

Measured 2026-08-31: one `pytest --noconftest tests/unit/renderer/
tests/unit/planners/` run took the project table from 21 to 113. The
92 new rows were 42 `shot-planner-test`, 22 `scene-planner-test`, 16
`asset-planner-test`, 8 `director-planner-test`, 4 `act-planner-test`.

Purge recipe that works, and its non-obvious parts:

- Guard on `%-planner-test` / `%-check-test` / `%generation-test` /
  `%-real-test` **AND 0 renders AND 0 assets**. Never a blanket
  `LIKE '%test%'`: `Radar and WW2 (camera-vocab test)` is a real project
  with 1 render and 31 assets.
- A6's implementer hit a gap in exactly this guard — its fixture was
  named `shot-planner-context-test`, which does NOT match
  `%-planner-test` (that pattern needs the suffix). **Name new fixtures
  to match an existing pattern** rather than inventing a name the purge
  cannot see.
- Delete children before parents; every FK to `project` is
  `ON DELETE NO ACTION`. Leaf-first: `shot_binding`, `generated_clip`,
  `narration`, `llm_call`, `domain_event`, `workflow_run`, `render`,
  `asset`, `script`, `timeline_version`, then `project`.
- Verify by LEFT JOIN on each child table for orphans, not by eyeball.

**Known non-regression:**
`test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`
asserts exactly one `agent='director'` llm_call exists, counted across
the WHOLE shared database — so the user's own projects (Oil and War,
OSHO the legend, Beauty and Disease, Automatic transmissions) each
contribute a row and it can never pass under `--noconftest`. Do not
"fix" it by dropping the flag.

---

## 5. What would kill this plan

Any one of these is a legitimate close. Write it in §7 and stop.

- **A1 lands and the two renders are indistinguishable.** Then style
  fragments do not steer real behaviour, and A4 is built on sand. Stop
  and find out why before touching A3.
- **A1 lands and `stillness` becomes boring rather than restrained.**
  "No camera motion" may simply be a bad idea over still photographs, in
  which case the honest fix is to soften the style's own *description*
### 4.7 `PAN`'s scale must COVER the output — pinning one axis is a crash

**A2 shipped a hard render failure. Fixed 2026-08-31; recorded here so
nobody reintroduces it.**

A2 emitted `scale=-2:{out_h}` for a horizontal pan (and A5 mirrored it as
`scale={out_w}:-2`): pin one axis, let the other fall where the source
aspect puts it. When the source is NARROWER than the output aspect, the
scaled frame is narrower than the crop window, and `crop` does not
degrade — it refuses to configure:

```
[Parsed_crop_5] Invalid too big or non positive size for width '1280'
[Parsed_crop_5] Failed to configure input pad on Parsed_crop_5
EXIT=127 — nothing written
```

Not the shot failing. The whole render. Measured against this project's
own 648 on-disk assets:

| Canvas | Assets that kill a horizontal PAN |
|---|---|
| 720x1280 — **the SHIPPED shorts canvas** | **111 (17.1%)** |
| 1280x720 — long-form | 582 (89.8%) |

`ken_burns.py`'s `max(...,0)` guard cannot help: it clamps TRAVEL, and
the failure is the crop WINDOW not fitting, which is evaluated first.
The pre-A2 `zoompan` chain never had this problem because it scaled with
`force_original_aspect_ratio=increase` — it covered the canvas.

**The fix:** one shared cover-scale for both axes,
`scale={w}:{h}:force_original_aspect_ratio=increase`. It guarantees both
axes are >= the crop window, and yields travel on whichever axis has
excess pixels (zero on the other — degrading to a static hold, which is
what the guard intended all along).

**Pixel-identical wherever A2 worked**, verified by frame hash rather
than argument: the signed-off render (2980x1676 landscape at 720x1280,
intensity 0.15) is byte-identical frame for frame, because cover-scaling
pins height to the same 2276x1280 that `-2:{h}` produced for any source
wider than the output aspect.

**Lesson for A5's implementer and anyone after:** A5 found this failure
during verification and corrected only the code COMMENT describing it,
reading it as evidence that the vertical axis was needed. It was not —
it was a bug on the axis that had already shipped. A render that exits
127 is never an argument for a new feature.

---

  in `suitability.py` so it stops promising something nobody wants.
- **A4's watched render shows the Director's `camera_language` was
  carrying the long-form look.** Then the fragment is a regression; keep
  the camera clauses out and let A4 be chapter structure only.
- **A5's canvas change cannot be confined to vertical-pan shots.** If
  every shot's filter string has to move, the cache cost outweighs one
  camera move. Ship A2 and close A5.

---

## 6. Open questions — unanswered on purpose

1. **Fragment on `documentary_archival`, or a fifth
   `documentary_longform` style?** This plan chooses the fragment,
   because the style name is the only routing key
   `load_style_fragment` has, and act presence is already a reliable
   length signal in the data (§1.6) — so the long-form clauses can
   self-gate without a new name, avoiding the four-planner regression
   cost a new style carries. The counter-argument is real: a fifth style
   would let long-form have its own band, grade, and canvas rather than
   inheriting the default's. Revisit if A4's self-gating turns out to be
   fragile in practice.
2. **Should `stillness` get a pacing target?** It has none, and A1 asks
   the model for long holds in prose instead. A `target_shot_duration_s`
   would make it structural — but per `StylePacingBand`'s docstring the
   target also drives a feasibility *floor*, and a slow style has no
   floor to check. Needs a look at what else reads the field before
   setting it.
3. **Do chapter cards want their own visual treatment?** `text_cards.py`
   renders one kind of card. A chapter title at an act boundary and a
   fact stated mid-scene are arguably different objects. Not blocking
   A4; a card is a card for now.
4. **Is a vertical pan ever right on 9:16?** The whole motivation is
   tall subjects on a wide frame. On a vertical canvas the crop discards
   *width* instead, so the mirror-image problem exists for horizontal
   pans on 9:16 — which nobody has reported. Worth one look at whether
   A5's fix generalises rather than special-casing one axis.
5. **Does `stillness` need `whoosh_enabled=False`?** It is `True` today
   by default, and a whoosh under "deliberate quiet" sounds wrong on
   paper. One listening pass, not a guess. Cheap to fold into A1's
   viewing pass.

---

6. **Can `fadeblack` actually mark an act boundary?** A4 was told to
   reserve it for act boundaries and discovered the data model cannot
   express one: **no scene is ever told it CLOSES an act** (only whether
   it opens one), and `Shot` has `transition_out` but no transition-IN.
   So the incoming edge of a boundary is unreachable from any single
   scene's own view. A4 resolved it by marking the transition from the
   chapter-card shot into the chapter's first substantive shot, both
   inside the act-opening scene — a dip just INSIDE the new act rather
   than BETWEEN acts. Two ways forward, and this plan deliberately does
   not pick: accept A4's version (free, already built, may read fine),
   or extend the model with a "closes an act" signal or a transition-in
   field (bigger, schema-touching). **Decide from the first real
   long-form render, not from this paragraph.**

---

## 7. Implementation log

### P-LF-A1 — stillness style fragment (2026-08-31)

**Scope executed:** exactly A1 from §3 — a new style-fragment prompt
file for `stillness`, nothing else. A2 through A5 were not started; no
renderer, schema, or planner code was touched. No render was run.

**Changes:**
- `backend/app/prompts/shot_planner_styles/stillness.md` (new file, 9
  lines) — the fragment. `load_style_fragment("shot_planner", "stillness")`
  now resolves it by filesystem convention
  (`backend/app/prompts/loader.py:36`); no registration code exists to
  add. Content: `static` declared the default movement, overriding the
  base intent→camera table (`backend/app/prompts/shot_planner/v1.md:21`)
  outright; exactly one permitted move (`slow_push`, intensity ≤ 0.10,
  used sparingly); `punch_in`/`pull_back`/`slow_zoom`/`pan`/`split_frame`
  off-limits; transitions restricted to `cut`/`dissolve` only (no
  `wipeleft`/`fadeblack`/glitch, no structural-beat carve-out); coarsest
  fragment granularity preferred; text cards near-never.
- `backend/tests/unit/planners/test_shot_text_cards.py:118-149` — updated
  `test_styles_without_fragments_still_resolve_to_none` (removed its now-
  false `load_style_fragment("shot_planner", "stillness") is None`
  assertion — `stillness` no longer belongs on that list) and added
  `test_stillness_fragment_loads_and_the_other_styles_are_unaffected`
  (loader-level proof the new file is picked up, plus a regression check
  that `documentary_archival`/`retention_fast`/`archival_montage`
  resolution is unchanged).

**Measured:**
- `stillness.md`: 9 lines (`retention_fast.md`, the shape it was modeled
  on, is 8).
- `test_shot_text_cards.py`: 6 tests, 6 passed, 0 failed.
- Purge (see below, same working session): 0 real projects matched the
  test-name guard; 21 real projects and 0 orphaned child rows, both
  before and after (no delete ran).
- **Not measured — explicitly out of scope for this slice:** the
  movement-histogram comparison between a `stillness` and a
  `documentary_archival` render of the same script that §3 A1 and §5's
  kill condition call for. That needs a real render, which A1's own
  instructions (§0.1 rule 4) reserve for a human pass.

**Verification:**
```
cd backend
python -m pytest --noconftest tests/unit/planners/test_shot_text_cards.py -q
# 6 passed in 2.70s
```
No other pytest invocation was run. `--noconftest` was used per the
plan's DB-safety rule; the shared Postgres was never truncated.

**Effects / notes for the reviewer:**
- §1.3/§4.1's `suppress_camera_language` trapdoor is now live for
  `stillness`: any project on this style stops receiving the Director's
  per-project `camera_language` line the moment this file exists on
  disk, with no code change and no feature flag. This is the plan's own
  intended trade for A1 (§3: "That is *intended* here"), stated plainly
  per §4.1's instruction.
- This is a pure-prompt change; per canon 3.1 the renderer was not
  touched, and no camera decision is applied outside the planner.
- The plan's §5 kill conditions ("A1 lands and the two renders are
  indistinguishable" / "A1 lands and `stillness` becomes boring rather
  than restrained") and §6 Q5 (whether `stillness` needs
  `whoosh_enabled=False`) are all still open — none can be evaluated
  without the render pass.

**What is NOT done:**
- **The human viewing pass is not done.** No `stillness` render and no
  `documentary_archival` render of the same script were produced or
  compared; the movement-histogram *Measured* line §3 A1 asks for does
  not exist yet. A1 is **built, awaiting human pass** — do not read this
  entry as A1 being verified.
- A2–A5 not started (out of scope for this slice by the pickup
  protocol).
- §5/§6's open questions above remain open.

### P-LF-A2 — Fix `PAN` travel, moving-crop mechanism, horizontal only (2026-08-31)

**Scope executed:** exactly A2 from §3 — `PAN` moved off `zoompan` onto
a time-varying `crop` over the full scaled image, capped by a
px/second ceiling that is itself a function of `camera.intensity` AND
`duration_s`, horizontal axis only. **A5 (vertical axis) was NOT
started** — `CameraDirection` gained no `UP`/`DOWN`, and no `y`-axis
crop was built; `y` stays a literal `0`. No prompt/style/schema change;
no new enum values (canon 3.1 — a renderer concern only).

**Changes:**
- `backend/app/renderer/ken_burns.py:79-92` — new `_MAX_PAN_PX_PER_SEC =
  320.0` module constant (replaces the now-unused `_MAX_PAN_ZOOM_DELTA`,
  deleted — there is no zoom headroom left to bound), with the same
  epistemic-honesty comment shape as `_MAX_ZOOM_DELTA`: states it is
  picked just above the measured 5.00s "reads as a camera" figure and is
  UNMEASURED below 5s, a starting point for the viewing pass, not a
  validated number.
- `backend/app/renderer/ken_burns.py:102-120` — new `MovingCropExpression`
  dataclass (`x_expr: str` only — no `zoom`, the crop window translates,
  never resizes). Deliberately not a `ZoompanExpression`: `slideshow.py`
  now dispatches on the RETURN TYPE, not on `camera.movement`.
- `backend/app/renderer/ken_burns.py:231-256` — `build_zoompan_expression`
  gained two new keyword params, `canvas_w: int | None` and
  `duration_s: float | None`, PAN-only, ignored by every other branch.
  Return type widened to `ZoompanExpression | MovingCropExpression | None`.
- `backend/app/renderer/ken_burns.py:289-320` — the PAN branch rewritten:
  `intensity<=0` → `None` (unchanged contract); missing
  `canvas_w`/`duration_s` → `ValueError` (a caller-bug guard, deliberately
  distinct from the intensity=0 data case — both real call sites always
  supply both, so this should never fire in production); otherwise
  `x_expr = "max(min({intensity}*(iw-{canvas_w}),{cap_px}),0)*{progress}"`
  where `cap_px = _MAX_PAN_PX_PER_SEC * duration_s` and `progress` is
  `(n/{last_frame})` / `(1-n/{last_frame})` for LEFT — the same
  `on`→`n` swap crop needs in place of zoompan's frame variable, same
  `LEFT` reversal semantics as before. `iw` and the literal `canvas_w`
  are ffmpeg's own runtime variables/values, not Python-computed pixel
  counts, so the arithmetic needs no probed source dimensions.
- `backend/app/renderer/slideshow.py:65-70` — import `MovingCropExpression`.
- `backend/app/renderer/slideshow.py:365-403` — new `_ken_burns_pan_filter`:
  `scale=-2:{h}` (height-only, aspect-preserved, full image — NOT the
  `force_original_aspect_ratio=increase`+centred-crop pair every other
  movement uses, which is exactly what was throwing away the travel
  margin), then `setsar=1,fps=,tpad=stop_mode=clone:stop_duration=,fps=`
  (the same tpad-materialises-`frames`-frames-from-one-decode shape
  `_normalize_filter` uses for STATIC, since `crop` — unlike `zoompan` —
  has no `d=`/`fps=` pair to generate a stream from a single frame
  itself), then `crop={w}:{h}:'{x_expr}':0,format=`.
- `backend/app/renderer/slideshow.py:422-457` (`_per_shot_filter`) and
  `:949-995` (`_render_run`'s per-run loop) — both call sites now pass
  `canvas_w=settings.width, duration_s=shot.duration_s` into
  `build_zoompan_expression` unconditionally, and both branch
  `isinstance(expr, MovingCropExpression)` → `_ken_burns_pan_filter`
  before falling through to the untouched `_ken_burns_filter` path for
  `ZoompanExpression`.
- Tests extended, not just re-run: `backend/tests/unit/renderer/test_ken_burns.py`
  (PAN section rewritten for the new signature/mechanism, `on`→`n`
  updated in the direction tests, plus new tests: return-type check,
  missing-kwargs `ValueError`, travel-follows-`iw`/output-width not a
  zoompan canvas, the cap literally binding at 1.75s, intensity scaling
  the travel, intensity=0 still degrading to `None` with no kwargs, and
  — the byte-identical proof — every non-PAN movement producing an
  IDENTICAL expression with vs without the new unused kwargs) and
  `backend/tests/unit/renderer/test_slideshow_argv.py` (new
  `test_ken_burns_pan_filter_holds_via_tpad_then_crops_no_zoompan`,
  built from the real `build_zoompan_expression` output, pinning the
  scale→fps→tpad→crop ordering and confirming `"zoompan"` never appears).

**Measured** (real render, `ffmpeg 9.0-full_build-www.gyan.dev`, the real
`Oil and War` asset — `ffprobe` confirms 2980×1676 — driven through the
REAL new functions, `retention_fast`'s 720×1280 canvas, `intensity=1.0`,
`direction=RIGHT`, `fps=30`):

- `scale=-2:1280` on the real asset measures **2276px** wide (`ffprobe`
  after a real `-vf scale=-2:1280` render) → full available travel
  `2276-720 = 1556px = 68.4%` of the scaled width — matches the plan's
  own pre-A2 table (1555px/68.4%) to rounding.
- With `_MAX_PAN_PX_PER_SEC = 320.0`:

  | duration | `cap_px` (320×dur) | actual travel | % of scaled width | actual speed | cap bound? |
  |---|---|---|---|---|---|
  | 1.75s (52 frames) | 560px | 560px | 24.6% | **320.0 px/s** | yes |
  | 2.25s (68 frames) | 720px | 720px | 31.6% | **320.0 px/s** | yes |
  | 5.00s (150 frames) | 1600px | 1556px (full) | 68.4% | **311.2 px/s** | no |

  The 1.75s/2.25s shots — `retention_fast`/`archival_montage`'s own
  durations, §4.2's warning — both land exactly on the 320 px/s ceiling
  instead of their old uncapped 889/691 px/s whip-pan speeds; the 5.00s
  shot is untouched by the cap and keeps its full measured-good 311 px/s,
  confirming the constant comment's own claim ("picked just above the
  5.00s figure").
- Unit tests: `backend/tests/unit/renderer/test_ken_burns.py` +
  `test_slideshow_argv.py` — **33 passed, 0 failed**.
- Also ran (optional extra confidence, not required by this plan's
  verification rule, `--noconftest`, no DB access in the test itself):
  `backend/tests/integration/test_render_ken_burns.py` — **5 passed**,
  including the riskiest case, a STATIC `tpad` still crossfaded against
  a PAN shot in the SAME `xfade` chain, now that PAN's stream is ALSO
  `tpad`-shaped rather than `zoompan`-shaped.

**Verification:**
```
cd backend
python -m pytest --noconftest tests/unit/renderer/test_ken_burns.py tests/unit/renderer/test_slideshow_argv.py -q
# 33 passed in 0.94s
python -m pytest --noconftest tests/unit/renderer/test_ken_burns_focal_crop.py -q
# 5 passed in 0.89s (regression check — untouched by A2, PULL_BACK only)
python -m pytest --noconftest tests/integration/test_render_ken_burns.py -q
# 5 passed in 6.27s (optional; real ffmpeg, no DB)
```
Real renders, filter strings built from the actual new functions (script
at the session's scratchpad, not committed — see the runnable form
inline in `_ken_burns_pan_filter`'s own docstring for the shape), output
in `tmp/pan-a2/` (repo-root, gitignored):
- `1_pan_new_1.75s.mp4`, `2_pan_new_2.25s.mp4`, `3_pan_new_5.00s.mp4` —
  the new mechanism at the three gate durations, `intensity=1.0`.
- `4_pan_old_5.00s.mp4` — the OLD zoompan-based PAN at 5.00s, hand-
  reconstructed from the deleted pre-A2 formula (`pan_zoom = 1 +
  intensity*0.3`, `WORKING_CANVAS_SCALE=1.6`) run through the UNCHANGED
  `_ken_burns_filter` wrapper, for an apples-to-apples comparison.
- `0_pan_sidebyside_5.00s_new-left_old-right.mp4` — `hstack` of the two
  5.00s renders.
All five `ffmpeg` invocations exited 0; `ffprobe` confirms each stream's
duration/frame count matches `round(duration_s*fps)` exactly (52/68/150
frames at 30fps). **Not independently re-verified by me watching the
actual footage frame-by-frame beyond the pixel-shift check below** — see
*What is NOT done*.
- Correctness of the "no `eval` flag needed" claim was checked directly,
  not assumed: `ffmpeg -h filter=crop` on the installed 9.0 build lists
  no `eval` AVOption at all (a positional `:eval=frame` fifth crop
  argument actually ERRORED — `Option not found` — that is how this was
  caught), then a synthetic horizontal-gradient still run through the
  exact `scale,setsar,fps,tpad,fps,crop` chain with `x='100*(n/4)'`
  produced 5 frames whose sampled centre-pixel red value increased
  linearly (0, 23, 50, 74, 100) — proof `crop`'s `x` **is** evaluated
  per output frame by default on this ffmpeg build with no extra flag.

**Effects / notes for the reviewer:**
- **The cache hazard is real, confirmed by reading the code, not
  assumed.** `backend/app/renderer/fingerprint.py`'s three fingerprint
  functions (`compute_render_fingerprint`, `compute_run_fingerprint`,
  `compute_shot_stream_fingerprint`) carry NO renderer code version or
  code identity of any kind — only Timeline content (which already
  includes `shot.camera.movement`/`direction`/`intensity` unchanged by
  this slice), asset/focal hashes, `render_settings`
  (width/height/fps/pixel_format), config-time mix values, and
  `ffmpeg_version` (the INSTALLED BINARY's version — not this
  module's). None of those change because this slice shipped. So: a
  Timeline with an existing `PAN` shot, re-rendered after this change
  with no edit to the shot/asset/settings, will compute the SAME
  fingerprint as before and hit `compute_shot_stream_fingerprint`'s
  on-disk cache (`work_dir/shot_cache/<fingerprint>.mp4`), silently
  reusing the OLD ~4%-travel render — the code path that would produce
  the new, correct pan is never reached. **I did not add a version bump
  or any other fingerprint change** — the task instructions were
  explicit that this is a decision for a human, not something to do
  unilaterally. The user has said old PROJECTS' content does not matter,
  but this is a different thing: a cache silently serving stale bytes
  for a NEW render request with the NEW code installed. Flagging for a
  decision, not deciding it.
- **Focal decision: unused for PAN, unchanged from before.** The old
  rule ("a pan does not retarget on its axis of travel") is kept exactly
  — `MovingCropExpression` carries no focal-derived field, and
  `_ken_burns_pan_filter`'s signature doesn't even accept `crop_x`/
  `crop_y` (unlike `_ken_burns_filter`, which still does for the other
  five movements). `_ken_burns_aim` is still called for every shot
  including PAN ones (unconditionally, at both call sites) so a PAN
  shot's `crop_x`/`crop_y` are computed and then simply discarded — a
  small amount of wasted arithmetic, not a bug, and left alone rather
  than special-cased to avoid complicating the two call sites for a
  cost that only matters on very large batches. Not independently
  reverified by a focal-vs-no-focal render — the "acceptable answer if
  you state it" option from the plan was taken as-is.
- **No plan-text contradiction found.** The pre-A2 measured table (§3),
  the mechanism snippet, and the three gate durations all matched real
  renders to within rounding; nothing here required a correction to §0–§6.
  The one thing worth recording for the next reader: the plan's own
  mechanism snippet doesn't mention ffmpeg's `crop` `eval` option at all,
  and it turns out this ffmpeg build (9.0) doesn't have that option — the
  per-frame evaluation the mechanism needs happens by default, not via a
  flag. Not a contradiction (the plan never claimed otherwise), just a
  gap the plan text leaves for whoever implements A5 next.
- `PUNCH_IN`'s `on`-based zoom expression and every other movement's
  `zoompan` string are untouched — confirmed by `git diff` on both files
  (not merely by reasoning): the STATIC/SPLIT_FRAME/SLOW_ZOOM/SLOW_PUSH/
  PULL_BACK/PUNCH_IN branches show zero lines changed in
  `ken_burns.py`, and `_normalize_filter`/`_ken_burns_filter`/
  `_motion_filter` show zero lines changed in `slideshow.py` — only new
  code was added (constants, one dataclass, the PAN branch, one new
  filter-string function, two call-site call changes gated by
  `isinstance`).

**What is NOT done:**
- **A5 (vertical axis) — not started, per this plan's own ordering.**
  `CameraDirection` unchanged, no `y`-axis moving crop.
- ~~**The human viewing pass.**~~ **DONE — A2 PASSED, 2026-08-31.** See
  the addendum below.

#### Addendum — human viewing pass, 2026-08-31 (A2 PASSED)

The renders above were all made at `intensity=1.0`. The `Camera` default
is **0.15** and `shot_planner/v1.md:34` tells the planner to keep
intensity in **0.1–0.25**, so none of them showed what production
actually ships. Re-probed by driving the real
`build_zoompan_expression` / `_ken_burns_pan_filter` at production
intensities on the same asset (2980×1676 → scaled 2276×1280, output
720×1280, full range 1556 px, 5.00 s shot):

| intensity | travel | % of image | px/s | % frame width/s | |
|---|---|---|---|---|---|
| 0.10 | 156 px | 6.8% | 31.1 | 4.3% | prompt's low end |
| **0.15** | **233 px** | **10.3%** | **46.7** | **6.5%** | **`Camera` default — SHIPPED** |
| 0.25 | 389 px | 17.1% | 77.8 | 10.8% | prompt's high end |
| 0.50 | 778 px | 34.2% | 155.6 | 21.6% | |
| 1.00 | 1556 px | 68.4% | 311.2 | 43.2% | what the entry above rendered |

**Consequence for `_MAX_PAN_PX_PER_SEC = 320.0`: it is DORMANT in
production.** `intensity` binds first at every value inside the prompt's
band — the cap only engages above intensity ≈0.5. It is correct to keep
as a guard, but it is not what governs the shipped look, and the
1.75 s / 2.25 s whip-pan risk §4.2 warns about cannot occur while the
planner stays inside 0.1–0.25. Do not tune this constant expecting it to
change anything until intensity guidance changes.

**Verdict (user, watching `tmp/pan-a2/9_DECIDE_0p15_left_vs_1p0_right.mp4`,
intensity 0.15 left vs 1.0 right): _"left is fine its slow but not
static"._** So 0.15 → 10.3% travel is the accepted look and `intensity`
does NOT need rebasing for the moving-crop mechanism, even though its
meaning changed (it scaled a zoom amount under `zoompan`; it scales
travel distance directly now). For reference the old mechanism at
intensity 0.15 travelled **1.4%** of the image (`pan_zoom` 1.045 inside
the old 1152-wide working canvas = 49.6 px of a 3641-wide scaled image),
so the shipped improvement is **~7.5×**.

⚠ An earlier draft of this addendum said the intensity-1.0 renders
"implied ~50×". That figure was wrong and is retracted: it compared the
old mechanism at intensity 0.5 (4.1%) against the new one at intensity
1.0 (68.4%), which is not a like-for-like pair. Held at a FIXED
intensity the gain is ~7–8× at every point in the band (0.15: 1.4% →
10.3%; 0.5: 4.1% → 34.2%). One ratio, not two.

**A2 is DONE.** Remaining open items below are unchanged.
- **The cache hazard decision.** Reported above, not resolved. Whoever
  picks this up next should decide, with the user, whether re-rendering
  after this ships needs a forced cache bust for existing `PAN` shots.
- **`intensity=0` PAN with a MOTION-classified (not STILL) source** was
  not specifically re-tested — unaffected by this slice by construction
  (`_per_shot_filter`/`_render_run` only call `build_zoompan_expression`
  when `probe.kind is MediaKind.STILL`), but not separately verified.
- A source image narrower than the output canvas after PAN's
  height-only `scale=-2:{h}` (the case the `max(...,0)` guard in
  `x_expr` defends against) was not rendered against a real mismatched-
  aspect asset — only reasoned about and covered by the guard. This is
  squarely A5's territory (a landscape source on a portrait canvas is
  exactly when this can happen), not re-litigated here.

### P-LF-A3 — Persist act titles into the Timeline (2026-08-31)

**Scope executed:** exactly A3 from §3 — acts added to the Timeline as a
first-class list (`id`, `order`, `title`), written by `_plan_hierarchical`
alongside the `act_id` stamping it already does. **A6 was NOT started** —
`_build_user_content` (Shot Planner) is untouched, sends no act/canvas
context, and a Path A user-content byte-identity test was not written
(that is A6's own verification, not this slice's). A4/A5 were not
started either — no prompt file, no `CameraDirection` change. No render
was run; this slice is schema + persistence only, per §3's own "ends in
tests, not a viewing pass."

**Changes:**
- `backend/app/schemas/timeline.py:536-549` — new `Act` model (`id: str`,
  `order: int`, `title: str`), docstring states the I1/I2 "immutable
  decision record" reasoning for keeping it Timeline-level rather than
  denormalised onto `Scene`, per the plan's own design constraint.
- `backend/app/schemas/timeline.py:576` — `Timeline.acts: list[Act] =
  Field(default_factory=list)`, documented with the same "empty on Path A
  / predates this field" convention `Scene.act_id`'s own docstring uses.
- `backend/app/planners/scene/planner.py:63` — import `Act as
  TimelineAct` (aliased: `app.planners.act.planner.Act` is a different,
  in-memory class already flowing through this module via `ActPlanner`,
  used for `id`/`order`/`title`/`start`/`end`/`script_slice`; the alias
  keeps the two unambiguous at every call site).
- `backend/app/planners/scene/planner.py:306,364` — `ScenePlanner.plan`
  and `_plan_hierarchical` return type changed from `list[Scene]` to
  `tuple[list[Scene], list[TimelineAct]]`.
- `backend/app/planners/scene/planner.py:397-402` (`_plan_hierarchical`)
  — after the existing `act_id` stamping and scene re-ordering, builds
  `timeline_acts = [TimelineAct(id=a.id, order=a.order, title=a.title)
  for a in acts]` from the SAME `acts` list `ActPlanner.plan` already
  returned at the top of this method (line 362, unchanged) — the exact
  titles that were being generated and thrown away (§1.6) — and returns
  `(ordered_scenes, timeline_acts)`.
- `backend/app/planners/scene/planner.py:316-323` (`_plan_single`, Path
  A) — returns `(scenes, [])`; the empty second element is what keeps
  `Timeline.acts` empty on every Path A project, matching how `act_id`
  itself already stays `None` there.
- `backend/app/workflow/steps/generate_timeline.py:211,223,230` — the
  only caller of `ScenePlanner.plan`: unpacks `scenes, acts`, `_apply_scenes`
  now sets `base.acts = acts` alongside `base.scenes = scenes`, and
  `owns=frozenset({"scenes", "acts"})` (was `{"scenes"}`) so the
  additive-only check (`app/timeline/additive.py`) permits the write
  even though, per that module's own `_is_owned`/empty-list logic, it
  was not strictly required here (old `acts` is `[]`, so filling it is
  additive by default) — added anyway for the same explicit-declaration
  style `"scenes"` already uses at this call site, not because a bug was
  found without it.
- Tests updated: `backend/tests/unit/planners/test_scene_planner.py` —
  7 call sites unpacking `ScenePlanner.plan`'s new tuple return (5 as
  `scenes, _`, since those tests don't assert on acts);
  `test_path_a_leaves_act_id_none` gained `assert acts == []`;
  `test_path_b_rebases_indices_and_sets_act_id` gained three assertions
  tying `timeline_acts` ids/orders/titles back to the `ActPlanOutput`
  fixture (`["act_01","act_02","act_03"]` / `[0,1,2]` /
  `["Coal","Oil","War"]`) — the "Path B populated acts list whose ids
  match the act_ids stamped on scenes" check the plan's own Verification
  section asks for.
- New test: `backend/tests/unit/timeline/test_acts.py` —
  `test_old_timeline_document_without_acts_field_still_validates`,
  a bare dict (no `acts` key) run through `Timeline.model_validate`,
  asserting `timeline.acts == []` — the "old timeline document without
  the field still validates" check.

**Measured:**
- 1 new Timeline field (`acts`), 1 new schema class (`Act`, 3 fields).
- `ScenePlanner.plan`'s return type changed at both of its 2 real
  call sites in non-test code (`generate_timeline.py`'s one production
  caller); 7 call sites updated across
  `tests/unit/planners/test_scene_planner.py`, all other test/prod call
  sites unaffected (only `ScenePlannerOutput`/`ScenePlanOutput` — the LLM
  response schema, untouched by this slice — appear in
  `test_generate_timeline_real.py`/`test_caption_romanizer.py`).
- Empirically verified (not just read) that `acts` is NOT in
  `_TIMELINE_BOOKKEEPING_FIELDS` and DOES change
  `compute_render_fingerprint`'s output: a script constructing two
  otherwise-identical `Timeline`s differing only in `acts` (`[]` vs one
  `Act`) produced two different SHA-256 fingerprints
  (`0838c401ba...` vs `96e831b4ef...`, full hashes in the verification
  transcript below) — a real measurement, not a code-reading claim.
- Test count: 17 passed (6 in `test_acts.py`, 11 in
  `test_scene_planner.py`); 2 passed in the full real-planner-chain
  integration test; 58 passed in the fingerprint unit suite (regression
  check, this module was not touched).

**Verification:**
```
cd backend
python -m pytest --noconftest tests/unit/timeline/test_acts.py tests/unit/planners/test_scene_planner.py -q
# 17 passed in 5.03s
python -m pytest --noconftest tests/integration/test_generate_timeline_real.py -q
# 2 passed in 8.10s
python -m pytest --noconftest tests/unit/renderer/test_fingerprint.py -q
# 58 passed in 0.63s   (regression check - fingerprint.py itself was not edited)
python -m ruff check app/schemas/timeline.py app/planners/scene/planner.py \
  app/workflow/steps/generate_timeline.py tests/unit/planners/test_scene_planner.py \
  tests/unit/timeline/test_acts.py
# All checks passed!
```
Fingerprint measurement script (`python -c "..."`, not committed — ad
hoc, run from `backend/`): built two `Timeline`s via
`t2 = t1.model_copy(update={'acts': [Act(id='act_01', order=0,
title='Chapter One')]})`, called `compute_render_fingerprint` on both
with identical everything else. Output:
```
acts in bookkeeping fields: False
fp1 == fp2: False
fp1 0838c401baedab2bcb1fdcacbbfc340b6bd1af98536e385e3cfd87b571a15f75
fp2 96e831b4ef101d16db220ef3c444aa0d0bf38f255d25ab21bc55c94c0d54dc5c
```
`--noconftest` was used throughout per the plan's DB-safety rule.
`test_scene_planner.py` and `test_generate_timeline_real.py` both create
real project rows (`scene-planner-test`, `generate-timeline-real-test`)
via their existing `project_id` fixtures — pre-existing behaviour of
those test files, unchanged by this slice, not a new hazard introduced
here. The shared Postgres was never truncated (no `PYTEST_TRUNCATE_DB=1`
set, and `--noconftest` bypasses the autouse fixture regardless).

**Effects / notes for the reviewer:**
- **R2 / fingerprint answer: the new field lands inside the payload,
  not in bookkeeping — with ZERO changes to `fingerprint.py`.**
  `compute_render_fingerprint` builds `content_only` from
  `timeline.model_dump(mode="json")` filtered by
  `_TIMELINE_BOOKKEEPING_FIELDS` (`app/renderer/fingerprint.py:190-193`),
  and that frozenset only ever held the 8 version-bookkeeping fields
  (`schema_version`, `timeline_id`, `project_id`, `version`,
  `parent_version`, `produced_by`, `status`, `created_at`) — never a
  content field. Adding `Timeline.acts` therefore falls straight into
  the hashed payload automatically, the same way every other Timeline
  content field already does; there was no code path where it could have
  landed in bookkeeping without someone deliberately adding "acts" to
  that frozenset, which nothing in this change does. This is
  DELIBERATELY the conservative answer the plan itself allows ("An act
  title that currently reaches nothing does not [need fingerprinting]" —
  A4 has not shipped, so today no chapter card exists) but it is also
  the SAFE one per this module's own closing paragraph: a false MISS
  (an unrelated re-render skipping the cache because `acts` sits in the
  hash) is harmless, while the alternative — deliberately excluding a
  future-load-bearing field from the hash — is exactly the class of bug
  R2's own history section (`music_bed_gain_db`/`music_duck_gain_db`)
  describes as having cost real money. No action needed from a future
  A4 implementer here: the field is already covered.
- **Storage answer: JSONB document, no migration.**
  `TimelineVersionModel.document` (`backend/app/models/timeline_version.py:35`)
  is a single `JSONB` column holding `Timeline.model_dump(mode="json")`
  whole; `TimelineVersionRepository.insert` (`backend/app/repositories/timeline_repository.py:41-61`)
  takes that dict directly, no per-field columns anywhere in the schema.
  A new Pydantic field with `default_factory=list` needs no Alembic
  migration — confirmed by test, not assumed:
  `test_old_timeline_document_without_acts_field_still_validates` feeds
  `Timeline.model_validate` a raw dict with no `"acts"` key and gets
  `timeline.acts == []` back. Per the task's explicit instruction, no
  migration was written and none is needed — nothing to escalate.
- The `TimelineAct` import alias in `scene/planner.py` is a naming
  choice, not a functional necessity (Python would not have actually
  collided, since `app.planners.act.planner.Act` is never imported by
  name in that file) — kept anyway because the module already juggles
  one `Act`-shaped concept (the in-memory `ActPlanner` output with
  `script_slice`) and adding a second, differently-shaped `Act` under
  the same bare name would be a readability trap for the next person
  who greps this file, not a bug today.
- `group_scenes_by_act`/`uses_per_act_beds`/`act_time_ranges`
  (`backend/app/timeline/acts.py`) are untouched, per the plan's own
  constraint — they still derive everything from `Scene.act_id`, not
  from the new `Timeline.acts` list. Verified by `git diff` showing zero
  lines changed in that file, not merely by not having edited it.
- **Plan-text correction (§0.1 rule 3):** none needed. Every design
  constraint in §3 A3 (Timeline-level list over `act_title` denormalised
  onto Scene, empty-on-Path-A convention, R2 check, storage check) was
  followed exactly as written; nothing found during implementation
  contradicted the plan text.

**What is NOT done:**
- **A6 — not started, per this plan's own ordering** (A4 depends on A3,
  and A6 is what threads act context into the Shot Planner). What A6
  will need from this slice: `Timeline.acts` (id/order/title) and the
  existing `Scene.act_id` are both now real and populated on Path B —
  A6's own job is reading them into `_build_user_content`
  (`app/planners/shot/planner.py:227`), not producing them. Nothing
  further needs to be added to the Timeline schema for A6 to start.
- A4/A5 not started (out of scope for this slice by the pickup
  protocol).
- No render was produced or watched — correct for this slice per §3's
  own "No user-visible change... the one task here that legitimately
  can [end in tests]", not an omission.
- §5/§6's open questions are unaffected by this slice and remain open.

### P-LF-A6 — Thread render context into the Shot Planner (2026-08-31)

**Scope executed:** exactly A6 from §3 — act context (act title, ordinal
"act N of M", opens-act flag) and canvas context (resolved resolution +
aspect) added to `_build_user_content`. **A4 and A5 were NOT started** —
no `documentary_archival.md` style fragment, no chapter-card logic, no
`fadeblack` act-boundary rule, no `CameraDirection` vertical values, and
`app/prompts/shot_planner/v1.md`/every `shot_planner_styles/*.md`
fragment is byte-for-byte untouched (confirmed by `git diff` showing zero
lines changed under `app/prompts/`). No render was run and no LLM was
called, per the task's hard rule.

**Plan-text decision, not a correction (§0.1 rule 3):** the plan's own
A6 "Ends in" line pairs "act + canvas lines present" for a Path B scene
against bare "byte-identical" for Path A, with no separate canvas-only
case. Canvas resolution has nothing to do with act presence, but this
slice honours that pairing literally: **both context families are gated
on the SAME condition — whether the scene resolves to a real `Act`** —
rather than sending canvas context to every project unconditionally.
This is a deliberate, conservative scope choice for THIS slice, not a
plan defect, and it is flagged for A5 below since A5 ("gated to landscape
canvases") is not itself restricted to Path B.

**Changes:**
- `backend/app/planners/shot/planner.py:42-53` — imports `Act` from
  `app.schemas.timeline` and `RenderFormat`/`resolve_render_format` from
  `app.script.styles` (no circular import: `app/script/styles.py` only
  imports `app.core.config`, checked directly).
- `backend/app/planners/shot/planner.py:229-296` (`_build_user_content`)
  — four new keyword-only params: `act: Act | None = None`,
  `act_ordinal: tuple[int, int] | None = None`, `opens_act: bool =
  False`, `render_format: RenderFormat | None = None`. When `act is
  None` the function returns EXACTLY what it returned before this slice
  — no new branch touches the existing return expression's first six
  f-strings; a `long_form_context = ""` default is appended as a final,
  otherwise-inert extra piece. When `act is not None`, appends one new
  block:
  ```
  \nLong-form context:\n- act: {act.title}\n- act position: act {N} of {M}\n- opens this act: yes|no\n- canvas: {W}x{H} ({aspect})\n
  ```
  `act position` and `canvas` lines are each independently omitted (not
  emitted empty) if their own arg is `None` - only `act`/`opens_act`
  gate the whole block.
- `backend/app/planners/shot/planner.py:451-517` (`ShotPlanner.plan`) —
  two new params, `acts: list[Act] | None = None` and `frame_aspect: str
  | None = None`. Before the per-scene gather (RV2, "resolve once, thread
  explicitly"): builds `acts_by_id` (id → `Act`), `act_ordinals` (id →
  `(position, total)` from `acts` sorted by `Act.order`), and
  `opening_scene_ids` (walks `scenes` sorted by `Scene.order`, first
  scene seen per `act_id` is the opener) — all three ONCE, outside
  `_one_scene`. `render_format = resolve_render_format(render_style,
  frame_aspect=frame_aspect)` is also resolved once here, unconditionally
  (cheap and pure), then passed into `_build_user_content` only for
  scenes that also resolve an `act` (`render_format if act is not None
  else None`) — the canvas/act pairing decision above, implemented as a
  single conditional at the call site, not a second gate inside
  `_build_user_content`.
- `backend/app/workflow/steps/generate_timeline.py:248-249` — the one
  production call site (`GenerateTimelineStep._run_real`) now passes
  `acts=timeline.acts` and `frame_aspect=timeline.metadata.frame_aspect`
  alongside the existing `render_style=timeline.metadata.render_style`.
  `timeline.acts` is A3's field (`[]` on every Path A project and every
  timeline predating A3), so production Path A calls fall straight
  through to the `act is None` branch with no other change needed here.
- New test file `backend/tests/unit/planners/test_shot_planner_context.py`
  (431 lines, 12 tests): 8 pure tests calling `_build_user_content`
  directly (no DB, no LLM) covering byte-identity, act+ordinal+opens-act
  presence/absence, landscape vs portrait canvas lines, and
  `suppress_camera_language` combined with act context in both states;
  4 tests going through the real `ShotPlanner.plan()` entry point with a
  `FakePlanningProvider` (same double `test_shot_planner.py` uses) to
  prove `acts`/`frame_aspect` actually thread from `plan()`'s new params
  into the emitted `user_content`, including one act-opener/mid-act pair
  and one `stillness` + `frame_aspect="9:16"` portrait-canvas case.

**Measured:**
- `app/planners/shot/planner.py`: +61/-0 lines (`git diff --numstat`).
- `app/workflow/steps/generate_timeline.py`: +2 lines are this slice's
  own (`acts=timeline.acts,` / `frame_aspect=timeline.metadata.
  frame_aspect,` at lines 248-249); the file's other uncommitted delta
  is A3's, already logged in P-LF-A3 - not re-counted here.
- New test file: 431 lines, 12 tests, all new (0 existing tests modified
  by this slice).
- Regression: `test_shot_planner.py` + its 3 sibling files: 39 passed,
  unchanged from before this slice (proves the pre-existing Q6 camera-
  suppression tests, the fragment-snap tests, and the glitch/text-card
  cap tests all still pass byte-for-byte with the new optional params
  defaulting away).
- `test_generate_timeline_real.py` (the one production caller of
  `ShotPlanner.plan`, now passing `acts`/`frame_aspect`): 2 passed.
- Prompt files touched: 0 (`git diff --stat -- app/prompts` is empty).

**Verification:**
```
cd backend
python -m ruff check app/planners/shot/planner.py app/workflow/steps/generate_timeline.py tests/unit/planners/test_shot_planner_context.py
# All checks passed!
python -m pytest --noconftest tests/unit/planners/test_shot_planner_context.py -q
# 12 passed in 2.47s
python -m pytest --noconftest tests/unit/planners/test_shot_planner.py tests/unit/planners/test_shot_planner_glitch_cap.py tests/unit/planners/test_shot_planner_text_card_cap.py tests/unit/planners/test_shot_text_cards.py -q
# 39 passed in 5.38s
python -m pytest --noconftest tests/integration/test_generate_timeline_real.py -q
# 2 passed in 5.70s
```
`--noconftest` was used throughout per the plan's DB-safety rule; no
`PYTEST_TRUNCATE_DB=1` was ever set and the shared Postgres was never
truncated.

**Effects / notes for the reviewer:**
- **R2 fingerprint: not applicable to this slice.** A6 adds no field to
  `Timeline`, `Scene`, or `Shot` - it only changes what text the Shot
  Planner's LLM prompt contains. Nothing new reaches
  `compute_render_fingerprint`'s payload because nothing new is
  persisted. (A3's own `acts` field was already verified inside the
  fingerprint payload in P-LF-A3; this slice adds no second field to
  re-check.)
- **What A4 gets for free:** `_build_user_content` already emits, for
  every scene with a resolvable act, the exact three facts A4's fragment
  needs to self-gate ("if you are told this scene opens an act…") - the
  act title, the opens-act boolean, and the ordinal. A4's own job is
  purely prompt text (`documentary_archival.md`) plus, per its own open
  sub-question, possibly a deterministic post-gather chapter-card pass -
  neither needs new plumbing through `plan()`.
- **What A5 will need to decide, and does NOT get for free:** canvas
  context (`render_format`) is currently gated on `act is not None`
  alongside the act fields (this slice's plan-text decision above), so a
  Path A landscape project - which A5's own "gated to landscape canvases"
  language does not exclude - does NOT currently receive a canvas line
  at all. If A5 wants vertical-pan requests for short 16:9 projects too,
  it must decouple the two: pass `render_format` into
  `_build_user_content` unconditionally (drop the `if act is not None
  else None` at the `plan()` call site, and drop the `act is not None`
  guard around `canvas_line` inside `_build_user_content`), at the cost
  of Path A no longer being byte-identical to pre-A6 output. That is
  a real, deliberate trade this slice is flagging, not an oversight.
- **Ordinal is 1-indexed and derived from `Act.order`, not list
  position.** `act_ordinals` sorts `acts` by `.order` before enumerating,
  so a caller that ever passes `acts` out of order (not true of the one
  real caller today, `generate_timeline.py`, which passes
  `timeline.acts` verbatim) still gets a correct ordinal.
- **"Opens this act" is computed from `Scene.order`, not list
  position**, for the same defensiveness - `scenes` is sorted by
  `.order` before the first-occurrence-per-`act_id` walk, so it does not
  depend on `scenes` arriving in that order already (it does, per A3's
  `_plan_hierarchical`, but this does not assume it).
- **A test-fixture naming near-miss, caught and fixed before finishing:**
  this slice's own DB-cleanup pass (below) found that a project name of
  `shot-planner-context-test` does NOT match any of the four required
  purge-guard patterns (`%-planner-test` needs the string to literally
  END in `-planner-test`; `-context-test` does not). The test file's
  `project_id` fixture was changed to reuse the exact name
  `shot-planner-test` (`test_shot_planner.py`'s own convention) instead
  of inventing a new one, closing the gap for any future run rather than
  only cleaning up this run's rows. Flagging this pattern for the next
  slice: a new test file's fixture project name must be checked against
  the four purge patterns before first use, not after.

**What is NOT done:**
- **A4 — not started.** No `app/prompts/shot_planner_styles/
  documentary_archival.md`, no chapter-card logic (model-driven or
  deterministic post-gather pass), no `fadeblack` act-boundary rule.
- **A5 — not started.** No `CameraDirection.UP`/`DOWN`, no vertical
  `y_expr`, and per the note above, canvas context does not yet reach
  Path A scenes - A5's implementer must decide whether to decouple it
  from act presence.
- Canvas context is coupled to act presence in this slice (plan-text
  decision above), not sent to every project - see the A5 note.
- No render was produced or watched - correct per §3's own "no render,
  no viewing pass" acceptance line for A6, not an omission.
- §5/§6's open questions are unaffected by this slice and remain open.

**Database purge (required cleanup, per this task's own instructions):**
Real project total before this slice's tests: 21 (verified). Running
this slice's new test file (`test_shot_planner_context.py`) and the
`test_generate_timeline_real.py` regression check twice each (once
before, once after renaming the fixture project name above) left 25
leaked rows: 15 `shot-planner-test` + 8 `shot-planner-context-test`
(the pre-rename name) + 2 `generate-timeline-real-test`. All 25 matched
the required guard (name pattern AND 0 renders AND 0 assets); a
same-session `ILIKE '%test%'` sweep found exactly one test-named row
OUTSIDE the guard - `Radar and WW2 (camera-vocab test)` - which was left
untouched, matching the memory note that it is real, has assets, and
must survive. Backed up (project rows + all 10 child tables named in
the task, JSON) before deleting; deleted leaf-first (`llm_call`: 12
rows, `script`: 2 rows, `timeline_version`: 10 rows deleted across both
purge passes; the other 7 child tables had 0 rows for these projects),
then 25 `project` rows. A second, smaller purge (4 more
`shot-planner-test` rows, 0 children) followed the post-rename
verification test run. **Final state: 21 projects (back to the real
total), zero orphaned rows in all 10 child tables (`LEFT JOIN ... WHERE
p.id IS NULL` on each, verified directly).**

### P-LF-A4 — Long-form direction for `documentary_archival` (2026-08-31)

**Scope executed:** exactly A4 from §3 - a new style-fragment prompt file
for `documentary_archival`, nothing else. Per the task's hard boundary,
`_build_user_content`/`ShotPlanner.plan()` in `app/planners/shot/
planner.py` were NOT touched by this slice - A5 was concurrently editing
that same file for its own vertical-pan/canvas-decoupling work
(confirmed live during this session; see *Effects* below). No
`CameraDirection`/`ken_burns.py`/vertical-pan work was touched (A5's
territory - the fragment deliberately never mentions vertical pan,
`UP`, or `DOWN`). `_cap_text_cards` was investigated but not changed,
per the task's explicit instruction. No render was run, no LLM was
called, no project was seeded.

**Changes:**
- `backend/app/prompts/shot_planner_styles/documentary_archival.md` (new
  file, 9 lines) - the fragment. `load_style_fragment("shot_planner",
  "documentary_archival")` now resolves it by filesystem convention
  (`backend/app/prompts/loader.py:36`); no registration code exists to
  add. Content: an UNCONDITIONAL camera-restraint clause (replaces the
  Director's `camera_language` line the moment this file exists - see
  the trade below) keeping the base intent->camera table, banning whip
  pans/rapid or jarring moves, and holding `intensity` inside the base
  prompt's own 0.10-0.25 band on every shot including `emphasize` beats;
  three clauses self-gated on "if you are told this scene belongs to an
  act" / "if you are told this scene opens an act" (A6's exact signal) -
  coarser fragment granularity plus `punch_in` off-limits at length,
  visual variety across an act, and chapter-card placement on an
  act-opening scene's first shot naming the chapter from the block's own
  `act:` line; `fadeblack` reserved for "if you are told this scene
  opens an act", applied as that scene's own first shot's
  `transition_out` (see the architecture finding below for why it
  cannot mark the incoming edge from the other side).
- `backend/tests/unit/planners/test_shot_text_cards.py:118` -
  `test_styles_without_fragments_still_resolve_to_none` had its now-false
  `load_style_fragment("shot_planner", "documentary_archival") is None`
  assertion removed, docstring updated to explain both `stillness` (A1)
  and `documentary_archival` (A4) left this list. New test at :154,
  `test_documentary_archival_fragment_loads_and_the_other_styles_are_unaffected`
  - loader-level proof the file resolves, checks for the long-form
  vocabulary (`act:`, `opens this act: yes`, `text_card`, `fadeblack`,
  `punch_in`, the five permitted camera moves, `cut`/`dissolve`,
  `camera_language`), asserts `UP`/`DOWN`/`vertical` are absent (A5's
  vocabulary, not this slice's), and re-checks the other three styles
  are unaffected.
- `backend/tests/unit/planners/test_shot_planner.py:616` -
  `test_documentary_archival_still_receives_director_camera_language`
  renamed to
  `test_documentary_archival_no_longer_receives_director_camera_language`
  and inverted (now asserts the line is ABSENT), docstring citing the
  §4.1 trade and this log entry - the "update the existing assertion the
  way A1 did for stillness" case the task anticipated, here for
  `camera_language` rather than fragment-presence.
- `backend/tests/unit/planners/test_shot_planner_context.py` - one line
  changed by this slice (`suppress_camera_language=False` ->  `True` on
  the Path-A camera+canvas test, since `documentary_archival` now has a
  fragment too), superseded moments later by A5's own concurrent edit to
  the same file, which renamed and rewrote that test
  (`test_plan_gives_a_path_a_project_a_canvas_line_but_no_act_context`)
  folding in the same `suppress_camera_language=True` fact alongside its
  own canvas-decoupling change, with a docstring crediting both slices.
  Verified by re-reading the file after A5's edit landed: the fact this
  slice needed is preserved.

**Measured:**
- `documentary_archival.md`: 9 lines (`stillness.md`/`archival_montage.md`
  are both 9 too).
- `test_shot_text_cards.py`: 7 tests, 7 passed (was 6 before this slice).
- Full shot-planner regression set, run AFTER A5's concurrent edits to
  `app/planners/shot/planner.py` and `test_shot_planner_context.py` had
  landed: **54 passed, 0 failed**.
- **`_cap_text_cards` finding - reproduced, not just read.** A standalone
  script (no DB, no LLM) built two scenes: one ending an act with an
  ordinary card on its LAST shot, immediately followed by a scene that
  opens the next act with a chapter card on its FIRST shot (1 shot
  later, `min_gap=4`). Real output of `_cap_text_cards`:
  ```
  act01_sc03 sh_0 None
  act01_sc03 sh_1 None
  act01_sc03 sh_2 '1929: The Crash'
  act02_sc01 sh_0 None   <- the chapter card, silently cleared
  act02_sc01 sh_1 None
  act02_sc01 sh_2 None
  ```
  **Yes, a chapter card CAN be silently dropped.** `_cap_text_cards`
  (`app/planners/shot/planner.py:122-175`) walks every shot in the whole
  project in order and clears any `text_card` landing fewer than
  `min_gap` (4, `settings.text_card_min_shot_gap`) shots after the last
  KEPT one, with zero concept of "chapter card" vs "ordinary card" or of
  act boundaries. It runs post-gather, across the WHOLE project
  (`planner.py:551`), after every scene has already been planned
  independently. An ordinary card near the end of an act's last scene
  (rare but not impossible under this fragment's "text_card stays
  exactly as rare as the base prompt already asks for" rule) can consume
  the gap budget the very next scene's chapter card needed. The only
  trace is a `WARNING`-level `shot_planner.text_cards_too_dense_trimmed`
  log line with no field distinguishing which kind of card was cleared.
- Purge (see below): 259 leaked project rows found and removed; 21 real
  projects before and after.

**Verification:**
```
cd backend
python -m pytest --noconftest tests/unit/planners/test_shot_text_cards.py -q
# 7 passed in 1.47s
python -m pytest --noconftest tests/unit/planners/test_shot_planner.py tests/unit/planners/test_shot_planner_context.py tests/unit/planners/test_shot_planner_glitch_cap.py tests/unit/planners/test_shot_planner_text_card_cap.py tests/unit/planners/test_shot_text_cards.py -q
# 54 passed in 8.14s
python -m ruff check tests/unit/planners/test_shot_text_cards.py tests/unit/planners/test_shot_planner.py tests/unit/planners/test_shot_planner_context.py
# All checks passed!
```
`_cap_text_cards` reproduction: ad hoc `python -c "..."` script (not
committed), output pasted verbatim above. `--noconftest` was used
throughout per the plan's DB-safety rule; no `PYTEST_TRUNCATE_DB=1` was
ever set and the shared Postgres was never truncated by a bare `pytest`.

**Effects / notes for the reviewer:**
- **`camera_language` suppression - the deliberate trade, stated per
  §4.1's instruction.** `documentary_archival` is
  `settings.default_render_style`, so creating this fragment switches
  `suppress_camera_language` on (`style_fragment is not None`,
  `planner.py`) for the default path of every landscape project, short
  or long, not only long-form ones - the fragment's very first clause
  exists specifically to replace what that per-project line was doing
  (a fixed "no whip pans, no rapid or jarring moves" policy plus the
  base intent->camera table, in place of a per-project free-text hint
  like "static and slow push, no whip pans"). No render was made to
  compare the two, so which one a human actually prefers (§4.1: "the
  honest outcome is to keep [camera_language] and drop the fragment's
  camera clauses instead" if the Director's line was doing real work) is
  unverified - flagged explicitly for the human pass, the same way A1
  left this open for `stillness`.
- **`_cap_text_cards` finding, reported per the task's instruction - not
  fixed.** See *Measured* above for the reproduction. This is exactly
  the failure mode §3 A4 predicted ("the likeliest way A4 ships looking
  fine and quietly broken"), now confirmed rather than merely plausible.
  Not fixed in this slice (out of scope, explicitly reserved as "a
  separate slice"). A future fix would need either (a) `_cap_text_cards`
  to treat a chapter card as exempt from the spacing rule, or (b) the
  deterministic post-gather chapter-card placement the plan's own "Open
  sub-question" already floats as an alternative to the prompt route
  taken here.
- **Architecture finding on `fadeblack`, a clarification worth recording
  (§0.1 rule 3 spirit) rather than a plan-text contradiction.** `Shot`
  has only a `transition_out` field - there is no "transition into this
  shot" field - and A6 only tells a scene whether IT opens an act, never
  whether the PRECEDING scene closes one (and scenes are planned
  concurrently via `bounded_gather`, so no scene could see that even if
  the field existed). So an act boundary's incoming edge cannot be set
  by the act-opening scene's own prompt call - only its outgoing edges
  are ever controllable by it. The fragment resolves this by making
  `fadeblack` mark the transition from the chapter-card shot into the
  chapter's first substantive image (both within the act-opening scene's
  own shots) rather than the cut from the previous act's last shot,
  which is the only boundary-adjacent transition actually reachable from
  a single scene's own local information without touching `planner.py`.
  This is a real, load-bearing constraint the plan text doesn't mention;
  flagging it here rather than silently working around it, in case a
  future deterministic post-gather pass (the plan's own alternative) is
  preferred specifically because it CAN see both sides of the boundary.
- **Concurrent-edit collision with A5, resolved by A5, not by this
  slice.** `app/planners/shot/planner.py` and `tests/unit/planners/
  test_shot_planner_context.py` were edited live by A5 in the same
  working tree while this slice was in progress (no worktree isolation
  between the two). This transiently broke 2 pre-existing tests in
  `test_shot_planner_context.py` for a reason unrelated to this slice's
  own fragment (A5 decoupled canvas-context emission from act presence,
  per that task's own §3 instruction) plus one line that WAS this
  slice's responsibility (the `suppress_camera_language` truth value for
  `documentary_archival`). Per this task's hard instruction not to edit
  `_build_user_content`/`plan()`, only the one in-scope line was changed
  here, leaving the canvas-related assertions for A5; by the time this
  slice finished, A5 had already reconciled the whole file (renamed the
  affected tests, folded in the `suppress_camera_language=True` fact) -
  verified by re-reading the file and re-running the full suite (54
  passed). No action needed from a reviewer here, but recording it since
  both this entry and A5's own log entry touch the same file and either
  could look surprising in isolation.
- Per canon 3.1, this is a pure prompt change - no renderer, schema, or
  camera-decision code was touched.

**What is NOT done:**
- **The human viewing pass is not done**, per §0.1 rule 4. No long-form
  render (>70 fragments) was produced or watched; the act-boundary
  `fadeblack` cards, the chapter-card wording, and the camera_language
  trade (§4.1's "state which one the watched render actually preferred")
  are all unverified by eye. **A4 is built, awaiting human pass.**
- `_cap_text_cards`'s chapter-card-drop risk is reported, not fixed (see
  above) - reserved as its own slice.
- A5 (vertical pan, `CameraDirection.UP`/`DOWN`) not started by this
  slice; it was running concurrently as a separate effort and is not
  represented in this log entry beyond the collision note above.
- §5/§6's open questions are unaffected by this slice and remain open;
  in particular §5's kill condition ("A4's watched render shows the
  Director's `camera_language` was carrying the long-form look") cannot
  be evaluated without the render pass.

**Database purge (required cleanup, per this task's own instructions):**
Real project total at the start of this session: 21 (verified, matching
the memory note). Multiple `--noconftest` pytest runs of the
shot-planner test files during this slice's bisection of the A5
collision above (each run creates new `project_id`-fixture rows) left
259 leaked rows, overwhelmingly `shot-planner-test` (194) plus smaller
counts of `scene-planner-test` (11), `asset-planner-test` (8),
`director-planner-test` (4), `act-planner-test` (2),
`generate-timeline-real-test` (2) - all pre-existing fixture names from
earlier slices (A3/A6), not new names introduced here; this session's
own repeated re-runs of those same fixtures inflated the count well
beyond what a single run would leave (the earlier P-LF-A6 entry logged
25 for a comparable but smaller rerun count). All 259 matched the
required guard (name pattern AND 0 renders AND 0 assets); a same-session
`ILIKE '%test%'` sweep found exactly one test-named row OUTSIDE the
guard - `Radar and WW2 (camera-vocab test)` - left untouched, matching
the memory note that it is real, has 31 assets, and must survive. Backed
up (full project rows + all 10 named child tables, JSON, in this
session's scratchpad) before deleting; deleted leaf-first (`llm_call`:
13 rows, `script`: 2 rows, `timeline_version`: 10 rows; the other 7
child tables - `shot_binding`, `generated_clip`, `narration`,
`domain_event`, `workflow_run`, `render`, `asset` - had 0 rows for these
projects), then 259 `project` rows. **Final state: 21 projects (back to
the real total, names verified individually), zero orphaned rows in all
10 child tables (`LEFT JOIN ... WHERE p.id IS NULL` on each, verified
directly).**

**Addendum, same session, immediately after the above:** a `SELECT
count(*) FROM project` taken right after finishing this log entry read
42, not 21 - 21 more `shot-planner-test` rows (0 children, 0 renders, 0
assets) had appeared with no DB-touching command run by this slice in
between (the only command run in that window was the pure,
no-DB `test_shot_text_cards.py`). This is concurrent A5 activity in the
same shared Postgres, not a leak from this slice's own testing - flagged
rather than silently absorbed into the count above. Purged the same way
(backed up, guard-checked, leaf-first; all 10 child tables had 0 rows
for these 21). **Re-verified final state: 21 projects, zero orphans.**
A third party re-running `shot-planner-test`-fixtured tests after this
entry is committed will leak again; that is a pre-existing shared-fixture-name
risk (also called out in P-LF-A6's own log entry), not something this
slice introduced or can close from here.

### P-LF-A5 — The vertical axis, gated to landscape canvases (2026-08-31)

**Scope executed:** exactly A5 from §3, all three parts. (1) The
vertical axis: `CameraDirection` gained `UP`/`DOWN`, and A2's
moving-crop mechanism was mirrored onto `y` with the SAME
intensity-times-range/px-per-second-cap arithmetic (no second travel
policy). (2) Decoupled canvas context from act presence in
`_build_user_content` (§3's own instruction, ⚠ note) - the canvas line
now emits whenever a `RenderFormat` is resolved, independent of `act`;
A6's byte-identity test was updated, not deleted, per the plan's
instruction. (3) The gate: base-prompt wording for `up`/`down`
conditioned on the canvas line, and a hard-fail validator rule rejecting
`UP`/`DOWN` on a portrait canvas. **Nothing else was touched** - no
change to `documentary_archival.md` (A4's file, not read or written), no
act/A3/A6 schema changes, no LLM calls, no live render through the
planner/workflow.

**Changes:**
- `backend/app/schemas/timeline.py:93-111` (`CameraDirection`) - added
  `UP = "up"` / `DOWN = "down"` with a comment in the same shape as the
  existing `LEFT`/`RIGHT` values: states the landscape-only gate, points
  at the validator, and states the convention (`DOWN` reveals the frame
  moving downward - top of the image toward the bottom, the "reading
  order" default; `UP` is the reverse).
- `backend/app/renderer/ken_burns.py:1-60` (module docstring) - new
  bullet documenting the vertical mirror and where the landscape gate
  lives (the Shot Planner's validator, not this module - canon 3.1).
- `backend/app/renderer/ken_burns.py:66-80` (`_MAX_PAN_PX_PER_SEC`
  comment) - noted the cap is shared unchanged by A5's vertical mirror,
  not a second policy.
- `backend/app/renderer/ken_burns.py:113-141` (`MovingCropExpression`) -
  gained `y_expr: str | None = None` (default keeps every existing
  horizontal caller byte-identical - dataclass equality/field order for
  `x_expr` is unaffected). Docstring states the dispatch contract:
  `y_expr is None` -> horizontal (A2, unchanged), `y_expr` set -> vertical
  (A5), with `x_expr` pinned to the literal `"0"` in that case (the
  "centred literal" the plan asks for - after `scale={out_w}:-2` the
  scaled width already equals the output width, so `0` is the only, and
  therefore centred, valid offset).
- `backend/app/renderer/ken_burns.py:258-266` (`build_zoompan_expression`
  signature) - new `canvas_h: int | None = None` keyword param,
  documented as PAN-only and vertical-only (every other movement, and a
  horizontal pan, ignores it - verified by test, see Measured).
- `backend/app/renderer/ken_burns.py:319-404` (the `PAN` branch) -
  restructured: `cap_px` is now computed once and shared by both axes
  (`camera.direction in (UP, DOWN)` selects the new vertical branch,
  which mirrors `ih`/`canvas_h`/`top_to_bottom`/`y_expr` onto exactly the
  same formula shape the horizontal branch already used for
  `iw`/`canvas_w`/`left_to_right`/`x_expr`); the horizontal branch itself
  is textually unchanged except its own comment (see Effects). Missing
  `canvas_h` on a vertical pan raises `ValueError`, the same caller-bug
  contract as the existing missing-`canvas_w`/`duration_s` case.
- `backend/app/renderer/slideshow.py:365-408` (`_ken_burns_pan_filter`) -
  dispatches on `expr.y_expr`: `None` emits the EXACT pre-A5 string
  (`scale=-2:{h}`, literal `0` for `y`); set emits the mirror
  (`scale={w}:-2`, literal `0` for `x`, quoted `y_expr` for `y`).
- `backend/app/renderer/slideshow.py:451-459` (`_per_shot_filter`) and
  `:966-974` (`_render_run`'s per-run loop) - both call sites now also
  pass `canvas_h=settings.height` unconditionally, mirroring how
  `canvas_w`/`duration_s` were already passed unconditionally by A2.
- `backend/app/planners/shot/planner.py:42-53` - added `CameraDirection`
  to the existing `app.schemas.timeline` import.
- `backend/app/planners/shot/planner.py:230-291` (`_build_user_content`)
  - `canvas_line` is now built from `render_format` ALONE (moved out of
  the `if act is not None:` block); the act-bearing block still embeds
  it, and a new `elif canvas_line:` branch emits a standalone
  `"\nLong-form context:\n- canvas: ...\n"` block when there is a canvas
  but no act - Path A's new shape, "today's string plus exactly one
  canvas line". `act_ordinal`/`opens_act` are UNCHANGED - still act-only.
- `backend/app/planners/shot/planner.py:304-309` (`_make_validator`) -
  new required `render_format: RenderFormat` param.
- `backend/app/planners/shot/planner.py:405-422` (inside `_validate`'s
  per-shot loop) - new check: `s.camera.direction in (UP, DOWN) and not
  render_format.is_landscape` appends a violation naming the shot id,
  the direction, and the actual resolved canvas.
- `backend/app/planners/shot/planner.py:526-560` (`plan()`'s `_one_scene`
  closure) - `render_format=render_format` now passed to
  `_build_user_content` UNCONDITIONALLY (was `render_format if act is not
  None else None`, A6's original gate); `_make_validator` now also
  receives `render_format` (positionally, as its 5th argument).
- `backend/app/prompts/shot_planner/v1.md` (+9 lines, in "Motion has
  purpose") - new bullet: `up`/`down` exist for a tall subject on a wide
  frame, use ONLY when told via a `- canvas: WxH (16:9)` line under
  "Long-form context", otherwise stay horizontal or use another
  movement - a vertical pan elsewhere "has nowhere to travel and will be
  rejected".
- Tests extended: `backend/tests/unit/renderer/test_ken_burns.py` (+7
  tests: vertical returns `y_expr` set with `x_expr` pinned to `"0"`;
  horizontal keeps `y_expr is None`; `UP`/`DOWN` move the expected
  direction; missing `canvas_h` raises; vertical shares the exact same
  cap/intensity arithmetic as horizontal, modulo `iw`/`ih`; both new
  kwargs (`canvas_h` alone, and both together) leave every non-PAN
  movement AND a horizontal pan byte-identical);
  `backend/tests/unit/renderer/test_slideshow_argv.py` (+2 tests: the
  vertical filter's `scale={w}:-2`/`crop=...:0:'{y_expr}'` shape from the
  real function, and the horizontal filter's shape proven unchanged
  alongside it); `backend/tests/unit/planners/test_shot_planner_context.py`
  (module docstring rewritten to state the A5 decoupling; the two A6
  byte-identity tests touching `render_format` with `act=None` UPDATED
  in place, not deleted, to assert the new "one canvas line" exact
  string, per the plan's own instruction);
  `backend/tests/unit/planners/test_shot_planner.py` (+2 tests: a
  `direction=down` `pan` shot is hard-rejected on `retention_fast`
  (portrait) and accepted unchanged on `documentary_archival`
  (landscape), both driven through the real `ShotPlanner.plan()`, not
  the validator function directly).

**Measured** (real render, `ffmpeg 9.0-full_build-www.gyan.dev`, a real
project asset - `storage/4bf38cf4-.../543e8630...jpg`, a 936x2292 JPEG,
a standing portrait shot from below, ratio 2.4487, found by a read-only
DB query for `asset.local_path` joined to `project`, dimensions checked
with PIL, no seed/LLM/workflow run - driven through the REAL
`build_zoompan_expression`/`_ken_burns_pan_filter`,
`documentary_archival`'s 1280x720 canvas, `direction=DOWN`, 5.00s,
`fps=30`):

- `scale=1280:-2` on the real asset measures **3134px** tall (`ffprobe`
  after a real render) -> full available vertical travel
  `3134-720 = 2414px`.
- `cap_px = 320.0 * 5.0 = 1600.0` (A2's `_MAX_PAN_PX_PER_SEC`, shared
  unchanged, per the plan's "do not invent a second travel policy").

  | intensity | raw (`intensity*2414`) | capped? | travel | % of scaled image | px/s | % frame height/s |
  |---|---|---|---|---|---|---|
  | 0.10 | 241.4px | no | 241.4px | 7.7% | 48.28 | 6.7% |
  | **0.15** | 362.1px | no | **362.1px** | **11.55%** | **72.42** | **10.06%** |
  | 0.25 | 603.5px | no | 603.5px | 19.3% | 120.70 | 16.8% |
  | **1.00** | 2414.0px | **YES** | **1600.0px** | **51.05%** | **320.00** | **44.4%** |

  **Finding not in A2's own tables:** at intensity=1.0 and 5.00s, the
  vertical cap DOES engage on this asset (2414px of raw range > 1600px
  cap), unlike A2's own landscape example asset at the same duration
  (1556px raw range, 311.2 px/s, just under the 320 cap - A2's addendum
  table). The threshold where the cap starts to bind on THIS asset is
  `intensity > cap_px/full_range = 1600/2414 ≈ 0.663`; the shipped
  production band (0.1-0.25, per `v1.md`) stays well under it, so - same
  conclusion as A2's addendum - **the cap is dormant in production for
  the vertical axis too**, and 0.15 -> 11.55% travel / 72.4 px/s is what
  a real `documentary_archival` project would actually render for an
  undirected/`DOWN` vertical pan on a tall subject at this shot length.
- Real render confirms the mechanism visually, not just arithmetically:
  frame 0 of the intensity=1.0 clip frames the subject's face/cap (top of
  the image); frame 149 (5.00s later) frames his belt/shorts (near the
  bottom) - the camera visibly travelled top-to-bottom over the full
  shot. The `UP`-direction clip at intensity=0.15 shows the mirror-image,
  smaller effect: more headroom above the cap at frame 149 than frame 0.
- Unit tests: `backend/tests/unit/renderer/test_ken_burns.py` +
  `test_slideshow_argv.py` - **49 passed, 0 failed** (was 33+9=42 before
  this slice's own additions; +7 new in `test_ken_burns.py`, +2 new in
  `test_slideshow_argv.py`).
- `backend/tests/unit/planners/test_shot_planner_context.py` - **12
  passed** (2 updated in place, per the plan's instruction, not deleted).
- `backend/tests/unit/planners/test_shot_planner.py` - **17 passed** (2
  new: vertical-pan-rejected-on-portrait, vertical-pan-accepted-on-
  landscape).
- R2 (fingerprint): measured directly, not assumed - built two
  otherwise-identical `Shot`s differing ONLY in `camera.direction`
  (`RIGHT` vs `DOWN`) and ran both through the real
  `compute_shot_stream_fingerprint`: the two hashes differ
  (`70c8009b9e...` vs `d7059493c8...`). `CameraDirection`'s new values
  are covered by the existing "Camera and duration stay in" fingerprint
  contract with zero changes to `fingerprint.py`, the same conclusion
  A2's own entry reached for its new enum usage.

**Verification:**
```
cd backend
python -m pytest --noconftest tests/unit/renderer/test_ken_burns.py tests/unit/renderer/test_slideshow_argv.py -q
# 49 passed in ~1s
python -m pytest --noconftest tests/unit/planners/test_shot_planner_context.py -q
# 12 passed in 2.57s
python -m pytest --noconftest tests/unit/planners/test_shot_planner.py -q
# 17 passed in 7.16s
python -m pytest --noconftest tests/unit/renderer/ tests/unit/planners/ -q
# 392 passed, 1 failed (test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call -
# a PRE-EXISTING cross-test-run pollution bug: it queries llm_call by
# `agent == "director"` with NO project_id filter, so it counts rows left
# by every other director-planner test this session, including ones this
# task did not touch. Not a regression from this slice - confirmed by
# reading the test, which has this bug independent of any A5 change.)
python -m ruff check app/planners/shot/planner.py app/renderer/ken_burns.py app/renderer/slideshow.py \
  app/schemas/timeline.py tests/unit/planners/test_shot_planner.py tests/unit/planners/test_shot_planner_context.py \
  tests/unit/renderer/test_ken_burns.py tests/unit/renderer/test_slideshow_argv.py
# All checks passed!
```
Real renders, filter strings built from the actual new functions (script
at the session's scratchpad, not committed - see `_ken_burns_pan_filter`
and `build_zoompan_expression` for the runnable shape inline), output in
`tmp/pan-a5/` (repo-root, gitignored), numbered so the most useful sorts
first:
- `0_sidebyside_0p15_vertical-pan-left_static-right.mp4` - the decision
  video: vertical `DOWN` pan at the shipped intensity (0.15) next to a
  plain static hold of the SAME asset. See Effects for why the RIGHT
  panel is a static hold and not an actual horizontal pan.
- `1_vertical_down_0p15_5.00s.mp4` / `2_vertical_down_1p0_5.00s.mp4` -
  the two intensities in the Measured table above, standalone.
- `3_vertical_up_0p15_5.00s.mp4` - the direction mirror, standalone.
- `4_horizontal_pan_crop_error_on_this_asset.txt` - see Effects.
`ffprobe` on all four `.mp4` files confirms exactly 150 frames / 5.00s /
30fps / 1280x720 (2560x720 for the hstack), matching
`round(duration_s*fps)` exactly.

**Effects / notes for the reviewer:**
- **A real render surfaced a genuine A2-era finding, not an A5 bug: a
  horizontal PAN cannot render AT ALL on a real tall asset meeting this
  task's own "height/width >= 1.5" criterion, on a 1280-wide canvas.**
  Attempted it directly (unchanged A2 code, `direction=RIGHT`,
  intensity=0.15, same asset): ffmpeg's `crop` filter refuses to
  configure (`Invalid too big or non positive size for width '1280'`).
  This is not the `max(...,0)` offset guard failing to degrade
  gracefully to "no travel" as A2's original comment implied - that
  guard only clamps a negative OFFSET. `crop`'s own target size
  (`canvas_w`/`canvas_h`, a literal in the filter string) is independent
  of the offset expression, so when the scaled dimension is smaller than
  that literal, ffmpeg refuses outright. This is a MATHEMATICAL
  certainty for any qualifying asset on this canvas (scale=-2:720 on a
  source with height/width >= 1.5 always yields a scaled width <= 480,
  always < 1280), not a fluke of the one file chosen - so no substitute
  asset would have avoided it. **Corrected the misleading comments in
  `ken_burns.py`** (both the new vertical branch and the pre-existing
  horizontal branch, `app/renderer/ken_burns.py:359-378` and `:395-408`)
  to state what the guard actually does, rather than repeating A2's
  "degrades to no travel" claim. Per §0.1 rule 3, this is exactly the
  finding A2's own entry already flagged as future work ("A source image
  narrower than the output canvas after PAN's height-only scale ... was
  not rendered against a real mismatched-aspect asset ... squarely A5's
  territory") - A5 IS that render, and it found the guard is narrower
  than advertised. No plan-text change needed: the plan never claimed
  the guard was complete, only that A2 hadn't tested it; this closes
  that open item with a real, reproducible measurement (the `.txt` log
  above) rather than leaving it open again.
- **This finding is itself the strongest evidence for why A5 exists**:
  on a genuinely tall subject, the "wrong axis" pan (§3's own framing)
  is not merely aesthetically wrong, it is often not renderable at all -
  vertical is not just the better choice, it can be the only one that
  works.
- **Validator decision: HARD FAIL, not a silent downgrade** (the
  question the task asked to be justified). `_cap_glitch_transitions`'s
  own docstring reasoning for silently downgrading is explicit: "the
  model was never *able* to see the other scenes" it needs to
  self-correct against - a structural blindness, not a mistake it could
  have avoided. The vertical-pan-on-portrait case is the OPPOSITE: the
  canvas line is already IN this exact scene's own prompt (via this same
  slice's `_build_user_content` change), so the model had the
  information needed to get it right and chose `up`/`down` anyway. A
  hard failure feeds that violation back through
  `run_structured_with_repair`'s retry loop, giving the model a chance to
  correct itself with the SAME information it already had - silently
  rewriting its `camera.movement`/`direction` choice instead would be a
  larger, unrequested behavioural change (the same class of concern
  `_cap_glitch_transitions`'s docstring raises about NOT extending itself
  to wipeleft/fadeblack), and would violate canon 3.1 by letting the
  renderer/validator silently substitute a creative decision the
  planner never made. Confirmed by test: `retention_fast` (portrait)
  raises `PermanentError` after repair attempts are exhausted;
  `documentary_archival` (landscape) plans the identical shot through
  untouched.
- **The Path A canvas-line change and its cost, exactly as flagged in
  §3's ⚠ note:** every Path A project (<=70 fragments - all 19 shipped
  shorts, ~50-58 fragments each, per the plan's own count) now receives
  one extra `"\nLong-form context:\n- canvas: WxH (aspect)\n"` block it
  did not get before this slice, because `ShotPlanner.plan()` already
  resolves `render_format` unconditionally (A6 built this, this slice
  only stopped withholding it from `_build_user_content` when `act` is
  `None`). This is a real, deliberate prompt-content change for every
  existing project on every style, landscape or portrait - a 9:16 style
  now also learns its own canvas (e.g. `- canvas: 720x1280 (9:16)`),
  which is inert today (no prompt wording reads it except the new
  `up`/`down` bullet, which only ever asks for a vertical pan, never
  forbids anything else) but is a real token-cost and prompt-shape
  change on every call. Per §3's own instruction this is accepted HERE
  specifically because A5 is already a prompt-wording change; it would
  NOT have been acceptable inside A6, which was deliberately inert.
- **`suppress_camera_language` interaction: none found.** The canvas-line
  decoupling and the camera-language suppression gate are independent
  conditionals in `_build_user_content` (confirmed by reading the
  function - `canvas_line`/`long_form_context` never reference
  `suppress_camera_language`), so A4's `documentary_archival` fragment
  (which sets `suppress_camera_language=True`) is unaffected by this
  slice and vice versa.
- **No plan-text contradiction found beyond the guard-comment correction
  above.** The vertical mirror's arithmetic, the "centred literal `0`"
  choice, the DOWN-as-default convention, and the validator's existence
  all matched the plan's own §3 text exactly.

**Database purge (required cleanup, per this task's own instructions):**
Real project total before this slice's tests: 21 (verified before any
test ran). This slice ran `tests/unit/renderer/`/`tests/unit/planners/`
regression sweeps THREE times over the course of the work (mid-slice,
after the code edits, and once more after drafting this log entry to
confirm nothing regressed) - each run left leaked rows, purged after
each: 67 total at the first check (46 leaked - `shot-planner-test` plus
several OTHER planner fixtures, `act-planner-test`, `asset-planner-test`,
`director-planner-test`, `scene-planner-test`, all from running the
whole `tests/unit/planners/` directory for regression, not from a file
this slice edited), 42 at the second (21 more `shot-planner-test`, from
re-running `test_shot_planner.py`/`test_shot_planner_context.py`), and
42 again at the third (21 more of the same, from the final confirmation
run). All three matched the required guard (name pattern AND 0 renders
AND 0 assets) with no exceptions; a same-session sweep for other
test-named rows outside the guard found only `Radar and WW2
(camera-vocab test)`, left untouched, matching the memory note that it
is real, has assets, and must survive. Backed up (project rows + all 10
child tables named in the task, JSON, in this session's scratchpad, NOT
`tmp/pan-a5/` which the user opens) before each of the three deletes;
deleted leaf-first each time - first pass: `llm_call` 1 row, all other 9
child tables 0 rows for these 46 projects, then 46 `project` rows;
second and third passes: all 10 child tables 0 rows for the 21 projects
each time, then 21 `project` rows each time. **Final state, verified
after the third pass (the last DB-touching action this slice took): 21
projects (back to the real total), zero orphaned rows in all 10 child
tables (`LEFT JOIN ... WHERE p.id IS NULL` on each, checked directly,
not assumed).** Per P-LF-A4's own entry (and its own addendum, which
already flagged this slice's concurrent `shot-planner-test` leakage
during ITS session), this shared-fixture-name risk is pre-existing and
not something this slice introduces or can close from here - a third
party re-running these same fixtures will leak again.

**What is NOT done:**
- **The human viewing pass is not done** - per §0.1 rule 4, this is
  explicitly marked "built, awaiting human pass", not verified. The
  renders above are real and pixel-confirmed (frame 0 vs frame 149
  visibly show the camera moving top-to-bottom/bottom-to-top), but no
  human has watched them end to end or judged whether 0.15's ~11.6%
  vertical travel over 5.00s "reads as a camera" the way A2's addendum
  established for the horizontal axis - that judgment call is reserved
  for the human pass this entry marks as pending, matching how A2 itself
  stayed "awaiting human pass" until its own addendum.
- **A cross-canvas 9:16 check was not separately re-rendered.** The
  validator test proves `retention_fast` (portrait) rejects a vertical
  pan and `documentary_archival` (landscape) accepts one, but no full
  9:16 project was planned end-to-end to confirm no real
  `archival_montage`/`retention_fast` run would ever request `up`/`down`
  in practice (only that the gate rejects it IF requested) - out of
  scope per the task's "do not run the planner or workflow end to end"
  rule.
- **The mirror-image horizontal-on-9:16 question (§6 Q4)** - "is a
  vertical pan ever right on 9:16" / "does A5's fix generalise rather
  than special-casing one axis" - is unaffected by this slice and
  remains open; A5 answers "gate it, don't ship it either way" for
  9:16, not "fix the geometry".
- **The cache hazard from A2** (an unchanged Timeline re-rendering after
  code changes ships hits the on-disk shot-stream cache and silently
  serves the OLD render) is unresolved and now applies to `UP`/`DOWN`
  too - not re-decided here, per A2's own entry leaving it for a human
  decision.
- Not committed, per the task's explicit instruction.

---

### P-LF-A7 — Chapter cards must outrank ordinary cards in `_cap_text_cards` (2026-08-31)

**Scope executed:** exactly A7 from §3 — `_cap_text_cards` and its one
caller (`ShotPlanner.plan()`) in `app/planners/shot/planner.py`, nothing
else. No prompt file touched (`documentary_archival.md` untouched, `git
diff --stat -- app/prompts` empty), `settings.text_card_min_shot_gap`
untouched (still `4`), nothing under `app/renderer/` touched, no schema
field added to `Shot`. No render, no LLM call, no project seeded.

**Changes:**
- `backend/app/planners/shot/planner.py:123-256` — `_cap_text_cards`
  rewritten to accept a new keyword-only parameter,
  `chapter_shot_ids: frozenset[str] = frozenset()` (default empty, so
  every existing caller/test that doesn't pass it is unaffected). The
  function now flattens every shot across all scenes once, walks that
  flat list computing a `decisions` array (kept card / cleared to
  `None`) with the OLD algorithm as its base case, then rebuilds the
  per-scene `Scene`/`Shot` objects from `decisions` exactly as the old
  code did (`scene.model_copy(update={"shots": new_shots})`, `shot
  .model_copy(update={"text_card": ...})` only when a value actually
  changes). The flatten/decide/rebuild split (rather than mutating in
  place during a single scene-by-scene pass, the old shape) exists
  specifically so a chapter card encountered LATER in the walk can
  retroactively clear an ordinary card that was already kept EARLIER —
  see the precedence logic below; a single forward pass over live
  `Scene` objects cannot reach back into an already-`model_copy`'d
  scene already appended to the output list.
- `backend/app/planners/shot/planner.py:684-693` (`ShotPlanner.plan`,
  right after the existing `_cap_glitch_transitions` call) — new
  `chapter_shot_ids` local, built as `scene.shots[0].id` for every scene
  in A6's own `opening_scene_ids` that has at least one shot, then
  threaded into `_cap_text_cards`. Reuses `opening_scene_ids` — no
  second "does this scene open an act" computation.
- `backend/tests/unit/planners/test_shot_planner_text_card_cap.py` —
  `_shot`/`_scene` helpers changed to give every shot a scene-scoped
  unique id (`f"{scene_id}_sh_{idx:02d}"` instead of a bare
  `f"sh_{idx:02d}"` that collided across scenes) so a test can name one
  exact shot via `chapter_shot_ids`; no existing test asserted a literal
  id string, only id *equality* between input/output, so this is safe.
  Six new tests appended at the end of the file (listed under
  *Verification*).

**Measured:**
- New/changed test file: 19 tests total (13 pre-existing + 6 new), 19
  passed, 0 failed.
- Full shot-planner regression set (same 5-file set A4/A6 used): 60
  passed, 0 failed.
- Purge (see below): 42 → 21 real projects; 21 leaked `shot-planner-test`
  rows deleted, all leaf-first across the 10 named child tables, all
  0 orphans afterward.

**Verification:**
```
cd backend
python -m ruff check app/planners/shot/planner.py tests/unit/planners/test_shot_planner_text_card_cap.py
# All checks passed!
python -m pytest --noconftest tests/unit/planners/test_shot_planner_text_card_cap.py -q
# 19 passed in 1.56s
python -m pytest --noconftest tests/unit/planners/test_shot_planner.py tests/unit/planners/test_shot_planner_context.py tests/unit/planners/test_shot_planner_glitch_cap.py tests/unit/planners/test_shot_planner_text_card_cap.py tests/unit/planners/test_shot_text_cards.py -q
# 60 passed in 7.93s
```
New tests, by name (all in
`tests/unit/planners/test_shot_planner_text_card_cap.py`):
- `test_the_a7_collision_keeps_the_chapter_card_and_drops_the_ordinary_one`
  — reproduces §3 A7's exact scenario (P-LF-A4's own repro): act 1's
  last scene has an ordinary card on its final shot, act 2's first
  scene (an opener) has a chapter card on its own first shot one shot
  later at `min_gap=4`. Asserts the chapter card survives and the
  ordinary one is cleared — the inverse of the pre-fix behaviour P-LF-A4
  logged.
- `test_a_chapter_card_is_never_cleared_even_far_below_the_gap` — the
  tightest possible collision (adjacent shots, gap of 0); chapter still
  wins.
- `test_an_ordinary_card_shortly_after_a_chapter_card_still_yields_as_before`
  — the OTHER collision direction (ordinary arrives after an
  already-kept chapter card) needs no special-casing; pinned down as an
  asserted behaviour, not left as an assumption.
- `test_two_chapter_cards_within_the_gap_are_both_kept` — the "assert,
  don't assume" case for two colliding chapter cards; see *Effects*
  below for the decision.
- `test_ordinary_only_spacing_is_unchanged_when_there_are_no_chapter_cards`
  — regression guard, re-runs two of the pre-existing ordinary-only
  scenarios with the new (empty) `chapter_shot_ids` default.
- `test_path_a_project_with_no_acts_is_byte_identical_to_pre_a7_behaviour`
  — re-runs the real measured d3a4d00d distribution (the same fixture
  `test_the_real_d3a4d00d_distribution_lands_inside_the_intended_rate`
  uses) with `chapter_shot_ids` both omitted and passed explicitly as
  `frozenset()`, and pins the exact surviving card list
  (`["c0_0", "c1_1", "c2_3", "c3_1", "c5_0", "c6_1", "c8_0"]`, computed
  by actually running the function, not guessed) — the concrete
  "byte-identical" proof Path A needs, one level stronger than the
  pre-existing test's "count and ratio" assertions.

`--noconftest` was used throughout per the plan's DB-safety rule; no
bare `pytest` was ever run and the shared Postgres was never truncated.

**Effects / notes for the reviewer:**
- **How a chapter card is identified, and why this route.** By `Shot.id`
  membership in a caller-supplied `chapter_shot_ids` set, not a new field
  on `Shot`. Confirmed against A4's actual fragment
  (`documentary_archival.md:8`) before assuming anything: *"This scene's
  first shot may carry a `text_card` naming the chapter... use the exact
  wording from the block's `act:` line."* So the model is instructed to
  put a chapter card on the act-opening scene's FIRST shot specifically
  — the task's suggested route matched the real fragment text exactly,
  no schema change needed. `ShotPlanner.plan()` already has everything
  required to build this set (A6's `opening_scene_ids`) with zero new
  plumbing: `chapter_shot_ids = {scene.shots[0].id for scene in capped
  if scene.id in opening_scene_ids and scene.shots}`. This does NOT
  verify the model actually put a card there — a scene that opens an act
  but chose not to emit a chapter card just contributes a shot id that
  never matches a `text_card`, which is harmless (the id is only ever
  consulted where `has_card` is already true).
- **Precedence rule, as implemented, in two lines:** a chapter card
  (`shot.id in chapter_shot_ids`) is never cleared, ever. An ordinary
  card within `min_gap` of a chapter card is cleared instead — including
  retroactively, if the ordinary card was already kept before the
  chapter card was reached in the walk (the exact §3 A7 collision
  direction) — and the gap counter restarts counting from the chapter
  card.
- **Two adjacent chapter cards: both are kept, unconditionally.** Because
  the rule is simply "a chapter card is never cleared" with no
  exception for colliding with ANOTHER chapter card, two chapter cards
  within `min_gap` both survive rather than the later one losing to the
  earlier (see `test_two_chapter_cards_within_the_gap_are_both_kept`).
  This was a free consequence of the "never cleared" rule, not a
  separate branch — flagging it as the concrete answer to the task's
  "assert, don't assume" instruction, since §3 A7 itself declines to
  pick one.
- **Log line, extended as instructed.** The old single `cleared` count
  is now split into `kept_chapter`, `kept_ordinary`,
  `cleared_ordinary_spacing` (an ordinary card too close to another kept
  ordinary/chapter card, the pre-existing failure mode) and
  `cleared_ordinary_for_chapter` (an ordinary card retroactively cleared
  because a chapter card claimed its slot, the new A7 case) — so a
  future log line can finally distinguish which kind of card was
  dropped and why, which the task called out as the reason this bug went
  unnoticed. There is no `cleared_chapter` field: it would always read
  `0` by construction, since a chapter card is never cleared.
- **Silently-correct-and-log contract preserved, not converted to an
  exception.** `_cap_text_cards` still returns a corrected list and logs
  a `WARNING`; nothing here raises. The docstring now states explicitly
  why a chapter card losing to the old rule was the same structural
  blindness as the pre-existing ordinary case, only with a worse
  consequence (A4's entire visible payoff silently vanishing).
- **No schema change was needed or made**, confirmed against the task's
  own instruction to stop and report if one seemed necessary — it did
  not: `Shot.id` was already sufficient, and A6 already computes exactly
  the set (`opening_scene_ids`) this fix needed.
- Per canon 3.1, this is a planner-internal deterministic pass, the same
  class as the pre-existing `_cap_glitch_transitions`/`_cap_text_cards`
  — no renderer code touched, no camera/style decision applied outside
  the planner.
- **No plan-text contradiction found.** A4's fragment wording, A6's
  `opening_scene_ids`, and the `Shot.transition_out`-only architecture
  P-LF-A4 already flagged all matched what §3 A7 assumed; nothing here
  required a §0.1 rule 3 correction to the plan text.

**What is NOT done:**
- **No render, no viewing pass** — correct per A7's own "Ends in" line
  ("unit tests... No render, no viewing pass"), not an omission.
- The `fadeblack`-cannot-mark-the-incoming-edge architecture question
  P-LF-A4 raised (§7's own "closes an act" open question, also §6 item
  6) is unaffected by this slice and remains open.
- §5/§6's open questions are unaffected and remain open.
- A2/A5's vertical-pan/moving-crop work is unrelated to this slice and
  was not touched or re-verified here.

**Database purge (required cleanup, per this task's own instructions):**
Real project total at the start of this slice: 42 (verified) — already
elevated above the user's real 21 by concurrent/prior sessions' test
runs (A4's own log entry documents the same shared-fixture-name leak
risk recurring after its own purge). A name-pattern sweep (`%-planner-test`
/ `%-check-test` / `%generation-test` / `%-real-test`) found exactly 21
candidates, all named `shot-planner-test`; a per-row check confirmed all
21 had 0 renders and 0 assets, and a same-session `ILIKE '%test%'` sweep
found exactly one test-named row OUTSIDE the guard —
`Radar and WW2 (camera-vocab test)` — left untouched, matching the
memory note that it is real and must survive. All 10 named child tables
had 0 rows for these 21 projects (backed up as an empty set alongside
the 21 project rows, JSON, in this session's scratchpad, before
deleting). Deleted leaf-first (all 10 child tables, 0 rows each, then
the 21 `project` rows). **Final state, verified directly: 21 projects
(the real total), zero orphaned rows in all 10 child tables (`LEFT JOIN
... WHERE p.id IS NULL` on each).** This slice's own test runs (all
`--noconftest`, pure — no DB fixtures in
`test_shot_planner_text_card_cap.py`/`test_shot_text_cards.py` — but
`test_shot_planner.py`/`test_shot_planner_context.py` do use DB-backed
fixtures) were run exactly once each during verification above; a
re-run of those two files will leak `shot-planner-test`/
`shot-planner-context-test`-named rows again, the same pre-existing
shared-fixture-name risk P-LF-A6/P-LF-A4/P-LF-A5 already recorded and
none of them could close from inside their own slice.

---

### P-LF-A8-GATE — Openverse diegetic-SFX probe: gate FAILS, close the slice (2026-08-31)

**Scope executed:** exactly the ⛔ GATE portion of §3 A8, and nothing else.
Measurement only — **zero production code written.** No `SfxKind.DIEGETIC`,
no `sfx_cue` field, no change to `select_sfx.py`, `sfx.py`, `config.py`, or
any schema. No project created, no DB write, no LLM call, no paid provider
call. The in-progress live run on project `c872ebbd-acfe-42a4-9a13-907be9727610`
was not touched.

**Changes:**
- `docs/plans/long_form_direction.md:67-69` (§0.1 point 6) — the "gated on a
  free Openverse search probe; do that probe before writing any A8 code"
  sentence rewritten to record that the probe ran and the slice is closed
  (finding contradicts the plan's open/pending framing — fixed per §0.1
  rule 3).
- `docs/plans/long_form_direction.md:275-304` (§3 A8, "⛔ GATE" section) — a
  **RESULT** block added recording the outcome in place, so a future reader
  does not re-run this probe.
- `docs/plans/long_form_direction.md` (this entry).
- `C:\director-project\video-generation-engine\tmp\sfx-gate\` (new,
  gitignored, not committed) — `REPORT.md` (full per-cue table and
  reasoning), `raw_results.json` (machine-readable dump: candidate counts,
  licence-clean counts, top-5 ranked candidates per cue with
  tags/duration/URL), and the 6 top-candidate audio files actually
  downloaded (see *Measured* below for which cues these are).
- A throwaway probe script was written to the session scratchpad (outside
  the repo) to drive the REAL `OpenverseMusicProvider` and REAL
  `rank_sfx_candidates` — not part of this repo, not committed, listed here
  only for traceability: it made one `MusicSearchQuery(search_terms=[cue])`
  call per cue (the same shape `SelectSfxStep` sends for one planner-authored
  cue string), applied the same `{"cc0","by"}` licence gate
  `default_sfx_plan()` uses, ranked with the unmodified `rank_sfx_candidates`,
  and fetched+saved the top-ranked candidate for each cue that returned any.

**Measured** (full method: real `OpenverseMusicProvider.search`/`.fetch`,
real `rank_sfx_candidates`, live network, `settings.sfx_max_clip_s` = 1.5s
confirmed at run time, no env override):

| Cue | Candidates | Licence-clean | Top candidate (title / licence / duration) | Verdict |
|---|---|---|---|---|
| geiger counter clicking | 10 | 10 | "geiger1.wav" / by / 0.018s | FAIL — correct sound family (title+tags say geiger click) but 18ms is a single blip, not "clicking" (repeated); ranking's duration-fit-first rule chose it over a 13.48s cc0 "Geiger Counter Hotspot" that actually sounds like sustained clicking, ranked #2 only because it exceeds the 1.5s ceiling. |
| nuclear explosion distant boom | 0 | 0 | — | FAIL — zero candidates for the literal phrase. |
| heartbeat slow | 10 | 10 | "Horror Scary Human Heartbeat Slow #03" / by / 3.96s | PASS — exact title match; `ffmpeg astats` shows RMS-through −81.1 dBFS with a −6.6 dBFS peak and crest factor 12.3 — a discrete thump against near-silence, physically consistent with a heartbeat. |
| wind across empty steppe | 0 | 0 | — | FAIL — zero candidates. |
| crowd murmur 1960s | 0 | 0 | — | FAIL — zero candidates. |
| typewriter keys | 10 | 10 | "Typewriter.wav" / by / 1.00s | PASS — exact title match; `astats` crest factor 27.6, a sharp transient against near-silence — the shape of one key strike. |
| factory machinery hum | 10 | 10 | "Sewing machine" / by / 0.97s | FAIL — names a narrower, specific machine than "factory machinery" despite broad tags, and 0.97s is too short to read as a sustained hum; a much closer cc0 "Industrial Machine Cycle.wav" (57.8s) ranked 4th, again only because of the 1.5s ceiling. |
| water lapping shore | 10 | 10 | "Ocean Noise - Surf" / cc0 / 34.99s | PASS (soft) — tags directly include "lapping" and "shore"; `astats` crest factor 4.8, continuous low-dynamic-range waveform fits an ambient water bed. Caveat: title/tags ("Surf", "Crashing", "Droning") suggest a rougher wave register than gentle "lapping" — content unverified beyond metadata. |
| radio static tuning | 10 | 10 | "AM Tuning.wav" / cc0 / 5.87s | PASS — title+tags are essentially a direct match; `astats` crest factor 31.5 (periodic bursts, not flat noise) fits a tuning sweep across frequencies. |
| church bell single toll | 0 | 0 | — | FAIL — zero candidates. |

**Fraction: 4 / 10 PASS (40%).** Below the plan's own kill condition
("fewer than ~half ... closes the slice").

Diagnostic-only follow-up (outside the production code path, live API,
explaining *why* the four zero-candidate cues fail): the same concepts as
shorter 2-word phrases return plenty of results — `nuclear explosion` → 19,
`distant boom` → 78, `crowd murmur` → 127, `church bell` → 240, `bell toll`
→ 40, `wind steppe` → 1. Openverse's search behaves close to AND-of-all-terms
matching, so a full 3-4 word planner-authored phrase, searched verbatim (as
the "build" section's `sfx_cue` design would do), frequently returns nothing
even though the catalogue holds reachable, relevant content. The
zero-candidate failures are a query-construction problem as much as a
content-thinness one — noted for the record, not acted on (would still be
production code).

**Verification:**
```
cd backend
.venv/Scripts/python -c "from app.providers.openverse_music import OpenverseMusicProvider; from app.assets.sfx_ranking import rank_sfx_candidates; print('imports ok')"
# imports ok — confirms Openverse needs no API key/settings beyond defaults
.venv/Scripts/python -c "from app.core.config import settings; print(settings.sfx_max_clip_s, settings.sfx_provider, settings.dry_run)"
# 1.5 local False
# (probe script, run from the session scratchpad, not the repo)
python sfx_gate_probe.py   # -> tmp/sfx-gate/raw_results.json + 6 saved .mp3 files
cd ../tmp/sfx-gate
ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name,sample_rate,channels -of default=noprint_wrappers=1 <file>.mp3   # confirmed API-reported durations exact for all 6
ffmpeg -y -i <file>.mp3 -af astats -f null NUL 2>astats_out.txt   # waveform stats used in the Verdict column above
```
No pytest was run for this slice (nothing here touches test-covered code);
the shared Postgres was never opened, queried, or written to.

**Effects / notes for the reviewer:**
- **Recommendation: CLOSE A8.** 40% is below "~half," and the plan's own
  language is explicit that this is a successful gate outcome, not a
  shortfall in the work: *"A diegetic layer that fires the wrong sound is
  worse than no diegetic layer."*
- **Common vs. exotic split is not favourable even so.** Restricting to the
  8 cues a documentary planner would actually reach for (wind, crowd,
  machinery, water, bells, static, typewriter, heartbeat) still only clears
  **4/8 (50%)** — sitting exactly on the threshold, not comfortably above
  it. The 2 cues that motivated this slice in the first place (Geiger
  counter, the explosion — both quoted from the Chagan script in §3's own
  opening) score **0/2 (0%)**. This is the reverse of "only the exotic ones
  fail" — the plan's own motivating cases are the ones that fail hardest.
- **The ranking function is part of why 2 of the 4 failures happened.**
  `rank_sfx_candidates`'s duration-fit-first policy (§5.5's inverse-of-music
  logic, correct for its stated purpose) actively prefers a technically-
  short but wrong-kind clip (18ms geiger blip, 0.97s sewing machine) over a
  longer, correctly-shaped clip that exists in the SAME result set one rank
  down. This is a real, reproducible ranking-vs-correctness tension worth
  recording even though the gate already fails independently of it — it is
  not the reason to close, but it means "raise `sfx_max_clip_s`" alone would
  not fix these two even if the slice were revived.
- **No Openverse configuration was needed.** The search is genuinely keyless
  in this codebase's own usage; `settings` required no API key, and no
  workaround or local-library fallback was used per the task's constraint.
- Six of the ten top candidates were downloaded to
  `tmp\sfx-gate\*.mp3` for the user to listen to directly; the four
  zero-candidate cues have nothing to download.

**What is NOT done:**
- No production code for A8's "If the gate passes" build section — never
  attempted, per the gate's own outcome and this task's explicit
  instruction to write zero production code regardless of outcome.
- The query-construction finding above (short-phrase decomposition) is
  recorded but not implemented or further explored — would itself be
  production code, and does not change the 40% verdict since even a
  best-case recovery of all 4 zero-candidate cues to "some result" says
  nothing about whether their top-ranked candidate would pass the
  correctly-identified test (2 of the cues that DID return full result sets
  still failed identification).
- The open questions in §3 A8 (placement precision, ducking interaction,
  scripted silence) are unaffected and remain open — moot now that the
  slice is closed, kept in the doc as history.

---

### P-LF-A8-GEN-GATE — Generated-audio diegetic-SFX probe: gate PASSES (2026-09-01)

**Scope executed:** exactly the ⛔ GATE portion of §3 A8's revised
"GENERATE the sound" approach, and nothing else. Measurement only —
**zero production code written.** No `SfxKind.DIEGETIC`, no `sfx_cue`
field, no provider method on `ElevenLabsNarrationProvider`, no change to
`select_sfx.py`, `sfx.py`, `config.py`, `elevenlabs.py`, or any schema.
No project created, no DB write, no LLM call. The in-progress live run
on project `c872ebbd-acfe-42a4-9a13-907be9727610` was not touched (no
reads of it were even needed).

**Changes (docs + tmp only):**
- `docs/plans/long_form_direction.md:323-376` (§3 A8, "⛔ GATE" section) —
  RESULT block added in place, below.
- `docs/plans/long_form_direction.md` §7 — this entry.
- `tmp/sfx-gen-gate/generated-*.mp3` (10 files) — one generation per cue,
  real ElevenLabs API, real money spent.
- `tmp/sfx-gen-gate/generation_manifest.json` — raw per-cue request
  duration, byte size, HTTP outcome, retry count.
- `tmp/sfx-gen-gate/REPORT.md` — full per-cue table, API-contract
  citations, cost estimate, A/B listening guide against `tmp/sfx-gate/`.
- Throwaway probe scripts (NOT committed, NOT in the repo — scratchpad
  only): `sfx_gen_probe.py` (generation) and `analyze_sfx.py` (envelope
  measurement). Both hand-roll the one-off `/v1/sound-generation` call
  and reuse `app/providers/elevenlabs.py`'s conventions (`xi-api-key`
  header, `httpx`, same base URL) rather than adding a method to that
  module.

**Measured:**

*API contract*, verified against ElevenLabs' own docs (2026-09-01), not
memory:
- Endpoint: `POST https://api.elevenlabs.io/v1/sound-generation`
  (`elevenlabs.io/docs/api-reference/text-to-sound-effects`,
  `elevenlabs.io/docs/overview/capabilities/sound-effects`).
- Request body: `text` (required), `duration_seconds` (optional,
  **0.1–30s**, auto-detected if omitted), `loop` (bool, v2-model-only,
  for seamless loops past 30s), `prompt_influence` (0–1, default 0.3),
  `model_id` (default `eleven_text_to_sound_v2`).
- Query param: `output_format`, same convention as narration.
- Seed: **not documented for this endpoint anywhere.** Confirms the
  plan's own read — I5 must come from the content-hash cache, not a
  seed, exactly as `generation_prompt_hash`
  (`app/workflow/steps/resolve_assets.py:265`) already does for images
  and clips.
- Billing: documented as **40 credits/second when `duration_seconds` is
  explicitly specified** — not character-based like narration.
- `settings.fal_api_key` does not exist as a settings attribute at all
  (confirmed via `python -c "from app.core.config import settings;
  settings.fal_api_key"` → `AttributeError`), stronger than "unset in
  the shell." fal.ai was not tried; ElevenLabs matched the plan's
  assumption on the first check, so there was no reason to.

*Per-cue table* (full detail and reasoning in `tmp/sfx-gen-gate/REPORT.md`;
compressed here):

| Cue | Req/delivered duration | Size | Verdict |
|---|---|---|---|
| Geiger counter clicking | 12.0s / 12.000s | 193,141 B | Plausible — quiet, sparse irregular clicks |
| Nuclear explosion, distant, muffled | 8.0s / 8.000s | 129,193 B | Plausible boom+decay shape; "muffled" unverifiable from amplitude |
| Slow heavy heartbeat, quiet | 10.0s / 10.000s | 160,958 B | Plausible, diagnostic — paired onsets (lub-dub) at ~45–55 BPM |
| Wind across empty steppe | 15.0s / 15.000s | 241,206 B | Plausible — variable gusting, not constant tone |
| Murmuring crowd, 1960s hall | 12.0s / 12.000s | 193,141 B | Plausible broadband bed; "1960s"/"hall" entirely inferred |
| Typewriter keys, single sentence | 4.0s / 4.000s | 65,245 B | Plausible — 4 sparse discrete keystrokes |
| Industrial machinery hum, continuous | 15.0s / 15.000s | 241,206 B | Plausible, diagnostic — lowest variance (CV 0.122) of all 10, flattest/most sustained |
| Water lapping gently | 15.0s / 15.000s | 241,206 B | Plausible but weaker signal — moderate variance, no clean pattern |
| Radio static and tuning | 8.0s / 8.000s | 129,193 B | "Static" plausible (flat, broadband); "tuning between stations" unverifiable without spectral analysis |
| Church bell toll, distant | 5.0s / 5.000s | 81,128 B | Plausible, diagnostic — sharp onset, clean monotonic decay, single onset |

**10/10 delivered the exact requested duration to the millisecond**
(`ffprobe`) — duration control works precisely. All 10 succeeded on the
first HTTP attempt; no retries used.

Verdicts come from windowed-RMS envelope analysis only (100ms windows,
mono 8kHz PCM, stdlib `array`/`wave`, no numpy available in this
environment) — level, variance, onset timing, attack/decay shape. This
is genuinely diagnostic for 4 cues (heartbeat's paired periodicity,
hum's flatness, bell's decay, Geiger's sparse irregularity) and merely
consistent-not-diagnostic for the rest. Timbre, pitch, frequency
content, and qualifiers like "distant," "muffled," "1960s" were **not**
measured — no spectrogram was taken. Stated per-cue in the table and in
full in `REPORT.md`; no clip was asserted to "be" the named sound.

*Cost:* documented rate × total requested duration
(12+8+10+15+12+4+15+15+8+5 = 104s) = **4,160 credits**. The API key is
scoped and returned `401 missing_permissions: user_read` on both
`/v1/user` and `/v1/user/subscription`, so the actual account debit
could not be read directly — the `/v1/sound-generation` response body
itself carries no usage/cost field either. Estimated in USD from
ElevenLabs' published plan rates ($6/30,000 credits Starter through
$99/600,000 credits Pro): **≈$0.70–$0.85 for all 10 generations**. This
is a bounded estimate from a documented public rate, not a measured
account figure, and is reported as such rather than invented as a
single number.

**Verification (exact commands):**
- `python "<scratchpad>/sfx_gen_probe.py"` — the 10 live generations,
  writing `tmp/sfx-gen-gate/generated-*.mp3` and
  `generation_manifest.json`.
- `python "<scratchpad>/analyze_sfx.py"` — windowed-RMS analysis over
  all 10 generated files.
- `ffprobe -v error -show_entries format=duration -of
  default=noprint_wrappers=1:nokey=1 <file>` — per-file delivered
  duration, run against all 10 generated files and, for the A/B pairs,
  the 6 pre-existing `tmp/sfx-gate/*.mp3` files.
- `python -c "from app.core.config import settings; print(settings.dry_run,
  bool(settings.elevenlabs_api_key))"` → `False True`, confirming this
  was a real, non-dry-run, live-key run before spending anything.

**Effects / notes for the reviewer:**
- **Recommendation: PASS.** 10/10 cues generated successfully, 10/10 hit
  their exact requested duration, and every one of the 10 envelope
  analyses is at least plausible with no outright red flag (no cue
  produced silence, clipped noise, or an obviously wrong gross shape).
  4 of the 10 are diagnostic-strength matches (heartbeat, hum, bell,
  Geiger), not just "consistent with."
- This directly resolves the plan's two motivating exotic cues (Geiger
  counter, nuclear explosion) that Openverse scored 0/2 on — generation
  produces plausible, correctly-durationed candidates for both.
- Generated-versus-real, per cue, on the 6 concepts with an Openverse
  counterpart in `tmp/sfx-gate/`: the generated clip is longer and
  duration-correct in every one of the 6 pairs, and for 2 of them
  (Geiger counter at 18ms, machinery hum at 0.97s) the Openverse
  candidate is duration-disqualified on its own terms while the
  generated one is not. This is the "duration row is worth more than it
  looks" claim from §3 A8 holding up under an actual measurement, not
  just the table's own reasoning.
- **The user's ears are still the actual verdict**, not this report or
  the envelope statistics — `REPORT.md` names the 3 A/B pairs to listen
  to first (Geiger counter, machinery hum, heartbeat) and explains why.
- Cost is genuinely small (well under $1 for all 10) and does not by
  itself gate anything downstream; the per-project cap called for in
  §3 A8's build step 7 is about steady-state volume across many shots
  in production, not this one-time probe.

**What is NOT done:**
- No production code for A8's "If the gate passes" build section (the
  planner-authored `sfx_cue` field, the provider method + cache, the
  `DIEGETIC` kind, `derive_sfx_events` branch, R2 fingerprinting, cost
  cap, prompt wording) — per this task's explicit instruction, gate
  passing or not.
- No spectral/frequency-domain analysis of any generated clip — only
  amplitude-envelope statistics. "Muffled," "distant," "1960s," and
  "tuning between stations" remain unverified qualifiers.
- No actual human listening pass — that is the next step, not this one.
- The account's true credit/dollar debit is unmeasured (scoped API key);
  only a published-rate estimate is reported.
- The open questions in §3 A8 (placement precision, ducking interaction,
  scripted silence, style-gating) are unaffected and remain open.

---

### P-LF-A9 — The long-form duration cap applies SHORT-FORM density (2026-09-01)

**Scope executed:** exactly §3 A9 — replaced `resolve_constraint_bundle`'s
short-form-density duration formula with a shot-CAPACITY bound, updated
the tests and stale comments that depended on the old formula's exact
numbers, and purged leaked test-project rows (§4.6). **A10 was explicitly
NOT started** — `script_chars_per_second_en`, `_chars_per_second`, and
every other A10-scoped identifier are untouched; `git diff` touches only
`app/script/styles.py`, two test files, and this plan doc.

**Changes:**
- `backend/app/script/styles.py:452-496` — `resolve_constraint_bundle`:
  moved `max_shots_per_project`'s resolution (previously at what is now
  lines 464-471) ahead of the duration-cap block so the new formula
  reads the FINAL resolved shot cap, not `shots_base`; replaced
  `implied_duration = (n_fragments / _N_AT_SHORT_CAP) * settings.
  max_video_duration_s` with
  `shots_available = min(max_shots_per_project, n_fragments)` /
  `capacity_s = shots_available * max_shot_duration_s` (the style-aware
  bound already resolved above it, not the flat setting), feeding the
  same outer `min(max_long_form_duration_s, max(max_video_duration_s,
  capacity_s))`.
- `backend/app/script/styles.py:381-388` — removed the now-dead
  `_N_AT_SHORT_CAP = 31.0` constant; updated its neighbouring comment.
- `backend/app/script/styles.py:196-210` — `archival_montage`'s
  narration-speed comment (the "OSHO the legend" 606f393e history) now
  says the `(n_fragments/31)` rate limit it cites was the formula AT THE
  TIME, with a superseded-2026-09-01 note pointing here — the number is
  preserved as history, not restated as current behaviour.
- `backend/tests/unit/script/test_styles.py` — updated
  `test_short_n_keeps_todays_caps` (N 13→10, since 13×8.0s=104s now
  legitimately exceeds the flat 90s default — that premise changed) and
  added 6 new tests: `test_capacity_raises_the_cap_once_it_exceeds_the_
  flat_default`, `test_a9_sanity_table_documentary_archival`,
  `test_a9_previously_failing_95_fragment_run_now_fits`,
  `test_a9_budget_cap_moves_with_the_higher_duration_cap`,
  `test_a9_more_fragments_still_raises_the_cap`,
  `test_a9_retention_fast_50_fragment_reel_is_not_wildly_longer`.
- `backend/tests/unit/script/test_suggestions.py` — recalibrated 3 tests
  whose hard-coded scripts/numbers were tuned against the OLD formula
  and no longer reproduce their own intended edge case under the
  corrected one (below, under Measured): `test_a_length_blind_cap_of_
  40_is_not_enough_for_long_form` (40→60 sentences),
  `test_further_available_false_is_not_success_when_punctuation_cannot_
  pass` and `test_marks_that_would_push_over_the_ceiling_are_not_
  offered` (both: 120 sentences/10209 chars → 20 sentences/11894 chars,
  and the expected mark count / projected seconds updated to match).
- `backend/tests/integration/test_narration_step.py:352-368` —
  `test_reconciled_duration_exceeding_max_video_duration_fails_loudly_
  without_persisting` additionally pins `settings.max_long_form_
  duration_s = 1.0`. Its `_TEXT` ("Hello world") is one fragment, so
  under the new formula capacity alone (`1 * settings.max_shot_
  duration_s` = 8.0s) would have swallowed the artificial
  `max_video_duration_s = 1.0` monkeypatch and stopped the scene's real
  1.1s total from tripping the violation. **Not run** — integration
  test, DB-gated, verified by inspection and by direct computation of
  the same formula (below), not executed (§11 DB hazard, and this task's
  own hard DB rules).

**Measured — the fragment/capacity table** (`documentary_archival` /
`style=None`, `settings.max_shot_duration_s=8.0`,
`settings.max_video_duration_s=90.0`, `settings.max_long_form_
duration_s=600.0`, computed by calling the real, patched
`resolve_constraint_bundle`):

| n_fragments | max_shots_per_project | capacity | cap | budget_cap_cents |
|---|---|---|---|---|
| 10 | 40 | 80s | **90.0s** (floor) | 1000 |
| 13 | 40 | 104s | **104.0s** | 1156 |
| 20 | 40 | 160s | **160.0s** | 1778 |
| 50 | 54 | 400s | **400.0s** | 4445 |
| 95 | 101 | 760s | **600.0s** (ceiling binds) | 6667 |
| 206 | 219 | 1648s | **600.0s** (ceiling binds) | 6667 |
| 300 | 319 | 2400s | **600.0s** (ceiling binds) | 6667 |

This matches §3 A9's own sanity table exactly (20→160s, 95→600s,
300→600s) — no plan-text correction needed. `max_shots_per_project=101`
at N=95 also matches the real failed run's own measured value in the
plan's table, confirming `shots_base`'s arithmetic is untouched.

**The previously-failing 95-fragment case:** old formula
`(95/31)*90 = 275.80645161290323...s` (matches the real error message's
digit-for-digit `275.80645161290323`, confirming the diagnosis). New cap:
**600.0s** (shot capacity 760s exceeds the hard ceiling, so the ceiling
binds). Measured narration was **316.88s** — under the old 275.8s cap
(failed, real run) and now **comfortably under the new 600.0s cap**
(316.88 < 600.0, by 283.12s of headroom).

**Budget cap, before/after, flagged per the task's explicit instruction:**
old `budget_cap_cents = ceil(275.80645s * 1000 / 90) = 3065¢` (~$30.65);
new `budget_cap_cents = ceil(600.0s * 1000 / 90) = 6667¢` (~$66.67).
**Ratio 2.175× (~2.2×).** This is a direct, mechanical consequence of
`budget_cap_cents` being derived from `max_video_duration_s` (§4.4's own
"$67 at 10 minutes" note already implied this ceiling-bound number) — it
was not separately capped here per the task's instruction not to touch
`budget_cap_cents`'s own formula. **Flagging for the user's own decision,
not silently accepted:** a 95-fragment documentary script's spend
ceiling roughly doubles as a side effect of this fix. If a lower,
independent budget ceiling is wanted for long-form specifically, that is
a new, separate decision — not implied by A9's own scope (`budget_cap_
cents`'s formula is explicitly on the "Do NOT touch" list).

**`retention_fast` fast-style regression check (§3 A9 item 5):** a
*typical* 50-fragment reel (`"This happened next in the story. " * 50`,
via `check_feasibility`) estimates **81.8s**, average **1.636s/shot**,
passes cleanly — nowhere near either the old cap (145.16s) or the new
one (175.0s). The duration cap moved from 145.16s (old:
`(50/31)*90`) to 175.0s (new: `min(79,50)*3.5`), but this is inert in
practice: `preflight.check_feasibility`'s own pacing-floor check (only
run for fast styles) binds at `50 * 1.75 * 1.2 = 105.0s` — strictly
tighter than either duration cap — and a synthetic script engineered to
sit at 307.5s was rejected by the pace check (`~6.15s/shot` violation)
regardless of which duration-cap number was in force. **No practical
regression** — see `test_a9_retention_fast_50_fragment_reel_is_not_
wildly_longer`. The `retention_fast` `suggest_breaks` edge-case tests
(R23/R24) DID need recalibrating, though, for a related but distinct
reason: `retention_fast`'s real per-shot ceiling is 3.5s/fragment, which
is MORE generous than the old flat 2.903s/fragment proxy — so a script
that used to be provably unfixable by punctuation (adding marks could
never out-run the flat rate-limited cap before hitting the true 600s
ceiling) can now genuinely reach feasibility with enough marks, since
each added mark raises `n_fragments` and therefore the capacity-derived
cap at a real 3.5s/fragment rate. The two recalibrated tests
(`test_further_available_false_is_not_success_when_punctuation_cannot_
pass`, `test_marks_that_would_push_over_the_ceiling_are_not_offered`)
use a script with far fewer starting fragments for the same near-ceiling
duration (20 sentences / 11894 chars / ~590.0s, instead of 120
sentences / 10209 chars / ~506.4s) so satisfying pace still needs enough
extra characters to blow the literal, A9-untouched 600s hard ceiling —
the genuinely punctuation-proof case these tests exist to guard, now
verified against the corrected formula.

**`suggestions.py:225`'s "more fragments raise that cap" still holds:**
asserted directly in `test_a9_more_fragments_still_raises_the_cap` —
`max_video_duration_s` is non-decreasing in `n_fragments` across
`range(5, 120, 5)`, and demonstrably a REAL raise (15 fragments < 40
fragments, both short of the 600s ceiling). Expected: capacity is linear
in `min(max_shots_per_project, n_fragments)`, and `max_shots_per_project`
itself is non-decreasing in `n_fragments` (§Track C §2.3), so the
composition is non-decreasing.

**Verification (exact commands and output):**
- `python -m pytest --noconftest backend/tests/unit/script/
  backend/tests/unit/workflow/test_generate_timeline_style_bounds.py -q`
  → **76 passed, 1 failed** (`test_retention_fast_estimate_is_shorter_
  because_of_speed`) — **pre-existing, unrelated to A9**, confirmed by
  `git stash` + re-running the same test against the pre-A9 tree (same
  failure, same `1.4000000000000001 == 1.2` mismatch — `retention_fast`'s
  `narration_speed` was bumped 1.2→1.4 on 2026-08-24 per `styles.py`'s
  own docstring, and this one test's expectation was never updated to
  match; untouched by this change, `git stash pop` restored the working
  tree).
- `python -m pytest --noconftest backend/tests/unit -q` → **838 passed,
  2 failed**: the above pre-existing failure, plus `test_director_
  planner.py::test_every_attempt_is_recorded_as_an_llm_call` — the
  documented `--noconftest` artifact from §4.6 (counts `agent='director'`
  across the whole shared DB; known non-regression, not touched).
- `python -m py_compile backend/app/script/styles.py backend/tests/unit/
  script/test_styles.py backend/tests/unit/script/test_suggestions.py
  backend/tests/integration/test_narration_step.py` → clean (the
  integration test itself was not executed, per the DB hazard rules).
- Direct arithmetic checks against the live `resolve_constraint_bundle`
  and `check_feasibility` (via `python -c "..."`, shown inline above)
  for every number in this entry's Measured section — none were assumed.

**Effects / notes for the reviewer:**
- The fix is exactly the formula in §3 A9's own "The fix" block, with
  one implementation nuance the plan flagged and asked to be verified:
  `max_shots_per_project`'s resolution had to be moved earlier in the
  function (it used to be computed AFTER the duration-cap block) so
  `capacity_s` reads the final, style-multiplied shot cap rather than
  the pre-multiplier `shots_base`. No circular dependency — `max_shots_
  per_project` does not depend on `max_video_duration_s` in either
  direction.
- `preflight.py::check_feasibility` and `workflow/steps/narration.py::
  NarrationStep._reconcile_and_append` both needed **zero changes** —
  both already read `resolve_constraint_bundle(...).max_video_duration_s`
  directly (confirmed by reading both sites), so the fix at its one
  source location closes the real failure automatically.
- `budget_cap_cents` and `max_video_shots_per_project` both move as a
  consequence for any n_fragments where the duration cap changed — this
  is intentional per A9's own instruction not to touch their formulas,
  and the ~2.2× budget change for the 95-fragment case is called out
  above rather than silently absorbed.
- Purge (§4.6, done as part of finishing this task): 49 rows matched the
  guard (`%-planner-test` / `%-check-test` / `%generation-test` /
  `%-real-test`, 0 renders AND 0 assets) out of 71 total projects;
  backed up to `tmp/a9-project-purge-backup.json` (49 `project` rows +
  1 orphan `llm_call` row) before deleting children (only `llm_call` had
  any: 1 row) then parents. Post-purge: **22 projects**, zero orphans in
  any of `script`/`timeline_version`/`render`/`asset`/`workflow_run`/
  `workflow_step_attempt`/`domain_event`/`llm_call`/`narration`/
  `generated_clip`/`shot_binding`. `Radar and WW2 (camera-vocab test)`
  and `The nuclear lake` both verified present and untouched. **Flagging
  a discrepancy, not resolving it silently:** this is 22, not the 21
  this task's own instructions state as the real total. The 22nd is
  `The whey protein crisis` (0 renders, 0 assets) — it does NOT match
  any of the four guard patterns (no `test`-shaped suffix at all), so
  per the explicit "NEVER a blanket `LIKE '%test%'`" rule it was left
  alone. Either it is a genuinely real project that has not generated
  anything yet, or the memory-recorded "21" predates its creation — this
  was not investigated further since deleting a non-matching row was
  explicitly out of bounds for this task.

**What is NOT done:**
- A10 (chars/sec recalibration) — not started, per explicit instruction.
  `script_chars_per_second_en` and `_chars_per_second` are untouched.
- No render, no viewing pass — correctly so, per §3 A9's own "Ends in":
  this is arithmetic, verified by unit tests and direct computation.
- The integration test fix (`test_narration_step.py`) was not executed
  against the real DB, per the hard DB rules — verified by inspection
  and by reproducing the same arithmetic path outside the test.
- The `The whey protein crisis` naming discrepancy above was flagged,
  not investigated or resolved.
- No independent, lower budget ceiling was added for long-form despite
  the ~2.2× increase — flagged for the user's decision, deliberately not
  decided here (`budget_cap_cents`'s own formula was on the "Do NOT
  touch" list).

---

### P-LF-A10 — Recalibrate chars/sec: eleven_v3 re-measurement (2026-09-01)

**Scope executed:** exactly §3 A10 - re-measured `script_chars_per_second_en`
against the 461 real narration rows already on disk (212 `eleven_v3`,
249 `eleven_multilingual_v2`), updated the constant, `config.py`'s
comment, `preflight.py::_chars_per_second`'s docstring, the one stale
test the task named, and two more tests whose hard-coded fixtures moved
under the new constant. **No LLM call, no ElevenLabs call, no paid
provider of any kind** - every number below comes from `ffprobe` on
existing files and read-only SELECTs. `resolve_constraint_bundle`,
`resolve_narration_speed`, the style bands, and everything under
`app/renderer/` (`narration_tempo.py` was read, not edited) are
untouched, per the task's explicit "Do NOT touch" list.

**Changes:**
- `backend/app/core/config.py:374-416` - `script_chars_per_second_en`
  14.4 -> **12.0**; comment rewritten to name `eleven_v3`, 2026-09-01,
  the sample sizes (212/249 rows, 13/8 projects) and the measured
  mean/median/stdev for both models (below).
- `backend/app/script/preflight.py:79-87` - `_chars_per_second`'s
  docstring: the stale "`retention_fast` at 1.2x is ~17.3 chars/sec, not
  14.4" example (still citing `retention_fast`'s OLD 1.2x speed, never
  updated when that bumped to 1.4x on 2026-08-24) replaced with the
  current 1.4x / 16.8 chars/sec figures and a pointer to `config.py`'s
  now-authoritative A10 history.
- `backend/tests/unit/script/test_preflight.py:71-79` -
  `test_retention_fast_estimate_is_shorter_because_of_speed`: fixed the
  task's named pre-existing failure, `1.2` -> `pytest.approx(1.4)`. This
  ratio is `resolve_narration_speed("retention_fast") /
  resolve_narration_speed("documentary_archival")` = 1.4/1.0 and does
  not depend on the value of `script_chars_per_second_en` at all, so
  this fix is independent of the constant change above - confirmed by
  running it in isolation before touching the constant (see
  Verification).
- `backend/tests/unit/script/test_suggestions.py:155-231` - two tests
  recalibrated a SECOND time (both already carry one 2026-09-01 A9
  recalibration note in their own docstrings; this task's edit is
  additive, kept as a second dated note rather than overwriting the
  first, matching this plan's own "don't erase prior history" practice
  in `styles.py`):
  - `test_further_available_false_is_not_success_when_punctuation_cannot_pass`
    (line ~172): fixture `chars=11894` -> `chars=9912`. At the new
    16.8 chars/s effective rate for `retention_fast` (12.0 x 1.4),
    11894 chars now estimates ~708s - already past the 600s hard
    ceiling with ZERO marks added, which collapses this test into the
    OTHER shape (`test_a_script_over_the_hard_ceiling_is_not_padded_
    with_futile_marks`'s "cut words instead, no marks needed" message)
    and fails the `"would need" in result.unfixable[0]` assertion.
    9912 chars reproduces the original ~590.0s-then-marks-push-it-over
    shape at the new rate, by direct computation against the real
    `estimate_duration_s`/`suggest_breaks` functions (see Verification).
  - `test_marks_that_would_push_over_the_ceiling_are_not_offered`
    (line ~211): same `chars=9912` fixture; `"would need ~318 more
    marks"` is UNCHANGED (coincidence - `min_marks` depends on
    `ceil(duration/1.75) - n_fragments`, and the new duration/fragment
    combination happens to need the same 318 by direct computation);
    `"~606s against a 600s maximum"` -> `"~609s against a 600s
    maximum"` (the new projected total, computed the same way).

**Measured** (all from `SELECT ... FROM narration n JOIN project p ON
p.id = n.project_id`, `ffprobe -show_entries format=duration` on every
`local_path`, 461/461 files present and readable, zero missing):

*The atempo determination (narration_tempo.py, narration.py:380-484):*
`local_path` is **POST-atempo**. `apply_narration_tempo` runs on the
WHOLE batch's `content`/`alignment` (narration.py:428-433) BEFORE
`_persist_slice` writes anything to disk, for both the single-response
`.mp3` path (`len(job.members)==1`) and the batched `.wav`
`slice_wav`-cut path (slices are cut from the ALREADY-tempo-adjusted
`content` against the ALREADY-rescaled `alignment`, narration.py:448-468).
`factor == 1.0` (documentary_archival, stillness) is a documented no-op
passthrough, so those files are the one case that is genuinely
untouched. To recover the natural (pre-speed-up, 1.0x) duration for
calibrating the BASE constant: `natural_duration_s = stored_duration_s *
factor` (atempo speeds audio up by `factor`, shrinking its duration by
that same factor, so multiplying back out undoes it exactly).

*A second bug found and corrected while normalising*: `retention_fast`'s
`narration_speed` was bumped 1.2->1.4 on 2026-08-24 and
`archival_montage`'s 1.15->1.25 on 2026-08-27 (both dated in `styles.py`'s
own comments / the P-LF-A9 log). This dataset's narration rows span
2026-08-21 through 2026-08-31 - straddling BOTH bumps. Using TODAY's
speed value to normalise every row (the naive approach) silently
mis-normalises every row synthesised before its style's bump - all 249
`eleven_multilingual_v2` `retention_fast` rows, it turned out, predate
the 1.2->1.4 bump, and 10 of 40 `archival_montage` `eleven_v3` rows
predate 1.15->1.25. The naive normalisation understated `eleven_multilingual_v2`'s
true rate by ~15% (12.08 vs the era-corrected 14.10 chars/s) purely from
this artifact - caught by the task's own instruction to cross-check
against the known failure rather than trust one aggregate number. All
numbers below use the era-correct (synthesis-time) speed value per row.

*By model_id (era-corrected natural chars/sec, the core comparison):*

| model_id | n | mean | median | stdev | p10 | p90 | min | max |
|---|---|---|---|---|---|---|---|---|
| `eleven_v3` | 212 | 13.41 | 13.11 | 2.41 | 10.91 | 16.65 | 6.94 | 23.01 |
| `eleven_multilingual_v2` | 249 | 14.10 | 14.00 | 1.73 | 11.81 | 16.31 | 9.67 | 18.98 |

**Hypothesis CONFIRMED, modestly**: `eleven_v3` is slower (lower
chars/sec) than `eleven_multilingual_v2` on aggregate - mean 5.1% lower,
median 6.4% lower - AND has substantially more spread (stdev 2.41 vs
1.73, min 6.94 vs 9.67), directly corroborating `styles.py`'s own
"v3's own natural pacing varies call to call" note. The
`eleven_multilingual_v2` era-corrected mean (14.10) also lands within 2%
of Q8's original 2026-08-20 measurement (14.4) - Q8 was not wrong, it
was simply never re-taken after the model switch, exactly as this task's
own framing said.

*By render_style x model_id (era-corrected), and the same-style,
same-atempo-factor apples-to-apples comparison the task asked for:*

| style | model | n | mean | median | stdev |
|---|---|---|---|---|---|
| `retention_fast` | `eleven_multilingual_v2` | 249 | 14.10 | 14.00 | 1.73 |
| `retention_fast` | `eleven_v3` | 146 | 13.62 | 13.31 | 2.52 |
| `archival_montage` | `eleven_v3` | 40 | 13.40 | 12.89 | 2.21 |
| `documentary_archival` | `eleven_v3` | 26 | 12.21 | 12.29 | 1.57 |

Within `retention_fast` alone (both models normalised by the SAME style,
differing only in which era-correct factor applied, 1.2 vs 1.4) v3 is
13.62 vs v2's 14.10 - the cleanest single comparison in the dataset, and
it agrees with the aggregate.

*By voice_id (era-corrected, top 8 by n; full 19-voice table computed but
not reproduced here for length - every voice's spread is available in
the scratch analysis this entry summarises):*

| voice_id | n | mean | median | stdev |
|---|---|---|---|---|
| `0muxiGNHAVvmM1qWRtyV` | 107 | ~14-18 (model-dependent, see below) | | |
| `3AMU7jXQuQa3oRvRqUmb` | 99 | 12.71 | 12.63 | 1.44 |
| `FZkK3TvQ0pjyDmT8fzIW` | 58 | 13.44 | 13.43 | 1.46 |
| `SLa3GDQHUGaRpH5GNvFL` | 34 | 12.23 | 12.19 | 0.91 |
| `7b9mYhmnp0y2qSH1FnBL` | 22 | 11.81 | 12.06 | 2.58 |

**Voice dominates over model far more than the mean-level model
comparison suggests.** `0muxiGNHAVvmM1qWRtyV` (the voice `config.py`'s
old comment named as "the configured voice") runs anomalously FAST on
`eleven_v3` (17.80 chars/s in `retention_fast`, n=20; 15.46 in
`archival_montage`, n=17) versus its OWN `eleven_multilingual_v2` rate
(14.71, n=70, `retention_fast`) - the opposite of the aggregate
direction for this one voice. Meanwhile `3AMU7jXQuQa3oRvRqUmb` runs a
consistent ~12.2-12.9 chars/s across ALL THREE styles/models it
appears in (documentary_archival v3: 12.21; archival_montage v3: 12.80;
retention_fast v3: 12.90) - and this is the exact voice behind the real
failure (`documentary_archival`'s 26 rows are 100% this voice, 100% one
project - see below). This reproduces `preflight.py`'s own existing
claim (voice spans ~36% vs language's ~8%) under the new model.

*Language-mix proxy (Devanagari-vs-Latin ratio in `text`; a proxy, not a
verified language tag):*

| bucket | model | n | mean | median |
|---|---|---|---|---|
| hindi (>=50% Devanagari) | `eleven_v3` | 168 | 13.33 | 13.14 |
| hindi (>=50% Devanagari) | `eleven_multilingual_v2` | 211 | 14.22 | 14.08 |
| hinglish (1-50%) | `eleven_v3` | 36 | 12.45 | 12.77 |
| hinglish (1-50%) | `eleven_multilingual_v2` | 38 | 13.41 | 13.24 |
| english (<1%) | `eleven_v3` | 8 | 19.32 | 19.21 |

The english bucket (n=8, one voice, one project's short English asides)
is too small and too concentrated to trust on its own; within the two
well-populated buckets (hindi, hinglish) v3 is consistently ~6-7% slower
than v2 at the SAME language mix, reaffirming voice > language as the
dominant variable and that ONE constant (not a per-language split)
remains correct, matching `preflight.py`'s existing Q8/R11 reasoning.

**Cross-check against the known failure (316.88s / 3,910 chars =
12.34 chars/s implied):** the `documentary_archival` + `eleven_v3` subset
(n=26, mean 12.21, median 12.29) sits within 1% of 12.34 - the closest
possible confirmation, though it should be read with one caveat stated
plainly: **all 26 of these rows come from a single project, "The nuclear
lake"** (verified: `SELECT DISTINCT project_id` on that subset returns
exactly one id, and it is very likely the SAME script that produced the
plan's own 12.34 figure, not independent corroboration of it). The
`eleven_v3` AGGREGATE across all 13 distinct projects (mean 13.41,
median 13.11) is ~9% above 12.34, not "wildly different" but clearly
above it - investigated per the task's own instruction rather than
reported uncommented: the gap is fully explained by `retention_fast`/
`archival_montage` rows running faster in this dataset than
`documentary_archival`'s one project does, which is itself mostly a
voice effect (above), not evidence the cross-check or the method is
wrong. Chose the new constant closer to the `documentary_archival`-
specific number and the aggregate's LOW end (median, p10) rather than
its mean, precisely because this style is the one that actually failed
and is `settings.default_render_style`.

**Chosen constant: `script_chars_per_second_en = 12.0`** (was 14.4).
Verification against every population above: 12.0 sits ~2% below the
`documentary_archival`-specific mean/median (12.21/12.29 - the closest
real analog to the failure), ~2.8% below the failure's own exact implied
rate (12.34), and ~8-10% below the full `eleven_v3` aggregate mean/median
(13.41/13.11) - i.e. deliberately pessimistic relative to every
population measured, never optimistic relative to any of them.
**Argument for a single conservative number over a tighter mean-fitted
one** (per the task's framing): `check_feasibility`'s total-duration
check is the ONE check in this module NOT margin-widened by
`script_preflight_margin_fraction` (preflight.py's own docstring: it
mirrors `Timeline._validate_structural_invariants`, which is exact, so
widening it would let pre-flight pass a script real planning is
guaranteed to reject) - so this constant carries its ENTIRE safety
margin on its own, for exactly the style (`documentary_archival`,
`stillness`) that has no per-shot pacing floor to catch a slow outlier
either. The failure this task exists to prevent burned a full
Director + Act/Scene/Shot planners + 82 shots of asset resolution +
complete narration synthesis before dying at reconciliation; the cost of
this constant being too pessimistic is, at most, one unnecessary
pre-flight rejection the user can immediately fix by trimming a script
that was already close to a length ceiling. That asymmetry is the whole
argument for erring low rather than fitting the mean.

*Recomputed for the new constant, for the reviewer:* `retention_fast`
effective rate 12.0 x 1.4 = 16.8 chars/s (down from 20.16); this is
BELOW the real observed mean STORED (i.e. final, post-atempo, directly
comparable to what a listener hears) rate for `retention_fast`
`eleven_v3` (~19.07 chars/s) and `eleven_multilingual_v2` (~16.92) alike
- still conservative, and closer to real than the old 20.16 was (which
overestimated speed by ~19% against the real v2 mix). `archival_montage`
effective rate 12.0 x 1.25 = 15.0 (down from 18.0), same direction.

**Verification (exact commands and output):**
- `python -m pytest --noconftest backend/tests/unit/script/test_preflight.py -q`
  -> **9 passed** (confirms the task's named pre-existing failure is
  fixed).
- `python -m pytest --noconftest backend/tests/unit/script/ -q` ->
  **72 passed** (0 failures; before the `test_suggestions.py` fixture
  fixes this showed exactly the predicted 2 failures on the two tests
  whose char counts moved, with the exact new numbers - 708s/no-marks-
  needed and a ~609s-not-606s mismatch - confirming the diagnosis before
  fixing rather than guessing).
- `python -m pytest --noconftest backend/tests/unit -q` -> **839 passed,
  1 failed** - the SAME documented non-regression
  (`test_director_planner.py::test_every_attempt_is_recorded_as_an_llm_call`,
  §4.6) A9's own log entry recorded; not touched, and it is a DB-wide
  count assertion that cannot pass under `--noconftest` regardless of
  this task's changes.
- `python -m py_compile backend/app/core/config.py backend/app/script/preflight.py
  backend/tests/unit/script/test_preflight.py backend/tests/unit/script/test_suggestions.py`
  -> clean.
- Direct computation against the real `estimate_duration_s`/
  `suggest_breaks`/`_chars_per_second` functions (not hand-arithmetic)
  to derive the new `9912`-char fixture and its `~318 marks`/`~609s`
  figures before editing the test, then re-ran the edited test to
  confirm - shown inline in this entry's Changes section.
- The 461-row measurement itself: one-off script using
  `app.db.database.engine` for read-only `SELECT`s (narration JOIN
  project, and a second pass for `created_at` to derive the era-correct
  atempo factor) plus `ffprobe -show_entries format=duration` per
  `local_path` - not a pytest run, so it did not touch `clean_database`;
  confirmed 461/461 files present and readable, and that the raw
  per-model totals (212 rows / 37,455 chars `eleven_v3`; 249 rows /
  37,142 chars `eleven_multilingual_v2`) match this task's own stated
  numbers exactly, validating the join before trusting anything
  downstream of it.

**Effects / notes for the reviewer:**
- **The plan's hypothesis (v3 slower than v2) held, but only after
  fixing a second, unrelated normalisation bug** (the retention_fast/
  archival_montage speed-bump dates) discovered while satisfying the
  task's own instruction to cross-check against the known failure rather
  than accept an aggregate number uncommented. Flagging this
  prominently because it means the FIRST (naive) version of this
  measurement would have shipped a wrong conclusion (v3 apparently
  FASTER than v2) purely from an atempo-normalisation artifact, not from
  the model comparison itself - worth remembering for whoever next
  normalises anything through a style's own speaking-rate history.
- Voice choice explains more of the spread than model choice does, at
  the level this dataset can show (one voice ran faster on v3 than v2;
  another ran consistently slow on both) - consistent with, not a
  contradiction of, `preflight.py`'s existing "voice spans ~36%, language
  spans ~8%" finding, now re-confirmed under `eleven_v3` rather than
  assumed to still hold.
- `_chars_per_second`'s docstring is now internally consistent with
  `styles.py`'s real, current `retention_fast` speed (1.4x) - it was
  quietly citing the OLD 1.2x number for over a week before this task
  found it while reading the module the task explicitly asked to be
  read.
- No plan-text contradiction found (§0.1 rule 3 N/A this time): the
  hypothesis in §3 A10 held, and the aggregate v3 figure landed close
  enough to 12.34 (within investigated, explained bounds) that nothing
  in this plan's prose needed correcting.
- Purge (§4.6): run TWICE - once after the initial targeted test runs
  (98 rows: name-pattern-matched, 0 renders, 0 assets; backed up, then
  deleted children-before-parents), and again after the final full
  `tests/unit` sweep leaked 49 more (same guard, same order) - both
  runs verified zero orphans across every child table afterward and
  left `The nuclear lake`, `Radar and WW2 (camera-vocab test)`, and
  `The whey protein crisis` untouched and present. Post-purge count both
  times: **22 projects** (matches A9's own log entry, not the 21 the
  task text states - same `The whey protein crisis` discrepancy A9
  already flagged and left alone, not re-investigated here). **The
  backup JSON (`tmp/a10-project-purge-backup.json`) reflects only the
  SECOND purge's 49 rows** - the first run's 98-row backup was
  overwritten by reusing the same fixed filename; flagging this rather
  than silently leaving it look complete, since it is a real gap in this
  entry's own audit trail, not a data-loss risk (both purges only ever
  touched the 0-render/0-asset name-matched rows this task's own test
  runs created). Confirmed after both purges: all 461 real narration
  rows remained present throughout (`SELECT count(*) FROM narration`),
  since none of the purged projects had any narration rows of their own
  (backed-up `narration` table was empty both times).

**What is NOT done:**
- No render, no viewing pass - correctly so; this is a re-measurement of
  existing on-disk audio plus an arithmetic constant, not a rendering or
  planning change.
- The `archival_montage` v3 subset (n=40, 2 projects) and the
  `retention_fast` v3 subset (n=146, 11 projects) were measured and
  reported, but the SINGLE most failure-analogous subset
  (`documentary_archival` v3) is still only one project's worth of data
  (n=26) - the task's request for "at least two or three real scripts of
  different language mixes" is satisfied at the `eleven_v3` MODEL level
  (13 projects) but not at the `documentary_archival` STYLE level
  specifically, because only one such project exists in the current
  database. Not fixable without spending money to generate more
  `documentary_archival` narration, which this task's own "SPEND
  NOTHING" instruction forbids.
- The full 19-voice table was computed (referenced above) but not
  reproduced in full here for length; available by re-running the
  measurement script's `by voice_id` grouping if a future reviewer wants
  it.
- Did not touch `script_preflight_margin_fraction`, the per-shot pace
  checks, or anything in `resolve_constraint_bundle` - per the task's
  explicit scope and "Do NOT touch" list; the entire safety margin for
  this recalibration lives in the chosen constant's own distance from
  the measured means, not in a separate margin field.
- Did not re-investigate the `The whey protein crisis` 21-vs-22 project
  count discrepancy A9's log already flagged - out of scope for this
  slice, same as it was for A9.

---

Entry shape (from `output_quality_pass.md` §0.1):

```
### P-LF-<slice> — <title> (<date>)

**Scope executed:** exactly what, and explicitly what was NOT started.
**Changes:** file:line for each.
**Measured:** real numbers. Never "looks right".
**Verification:** the exact command run, and its output.
**Effects / notes for the reviewer:**
**What is NOT done:**
```
