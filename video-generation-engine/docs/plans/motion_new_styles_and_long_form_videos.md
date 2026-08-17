# Motion, New Styles, Script Pre-flight, and Long-Form Video — Implementation Plan

> **Status:** Plan only. Nothing here is built. No code was written to produce this document — it is the result of reading the existing implementation, running the real fragment splitter against a real fixture, and the frozen docs. 2026-08-17.
> **Scope:** four tracks — **A** (motion clip input), **B** (style catalogue), **C** (long-form), **D** (script pre-flight). A is the keystone for the motion half of B; D is independent and could ship first.
> **Related:** [`13_Implementation_Guide.md`](../13_Implementation_Guide.md) §M7/M8/M9 and its Backlog, [`14_Captions_Plan.md`](../14_Captions_Plan.md), [`watermark_implementation_plan.md`](watermark_implementation_plan.md).
> **Fixture:** project `58f0a5e6-008d-468e-862a-e365e463878e` / `backend/tests/fixtures/m8_test_project.json` — real Fischer-Tropsch timeline, 13 shots. Reuse it; do not plan a fresh one.

---

## Verdict up front

**Two findings drive this document.**

**1. AI video generation is already built, already integration-tested, and is thrown away at the last step.** `FalVideoProvider` submits, polls, persists its job handle before anything else, resumes across crashes, respects the budget cap, and caches on `prompt_hash`. Then `RenderStep` passes every resolved path through `ensure_still_image`, and a Kling clip becomes **one frozen frame**. That single gap blocks AI video, 2.5D parallax, stock footage, and half the style catalogue. It is not four features — it is **one boundary, integrated once and reused four times.**

**2. A video's pace is set by the punctuation of the script, and this is exactly measurable before anything runs.** The fragment splitter breaks on `.!?…।` then `,;:—`. A shot is at minimum one fragment. So `D/N` — estimated duration over fragment count — is the fastest average shot duration a script can physically produce. On the real fixture this predicts **3.54s**, which is exactly the measured average. That turns "does this script suit this style" from a vague question into arithmetic, and it means a style can be checked against a script for free, before a single API call.

| Track | What | Estimate | Blocked by |
|---|---|---|---|
| **A** | Motion clip input path | ~7–9 d | — |
| **B** | Style catalogue | ~5–8 d (Tier 1) → ~20 d (all) | Tier 3 needs A |
| **C** | Long-form (90 s → 10 min) | ~10–14 d | orphan-run fix |
| **D** | Script pre-flight | ~5 d | — |

**Do D and A first**, in either order. D is independent and prevents wasted planning runs; A unlocks everything else.

---

## 0. What is verified, what is inferred, what is guessed

Marking this so nobody downstream has to reverse-engineer my confidence.

**Verified by reading code and running it, 2026-08-17:**

- `slideshow.py::_render_run` has exactly two input shapes — `-loop 1 -t` for a static still, one decoded frame for a `zoompan` shot. **No motion-clip branch.**
- `render.py:208` routes **every** resolved path through `ensure_still_image`; `still.py::needs_normalising` treats an unreadable-by-Pillow file as "not a loopable still" and takes frame one. Its own docstring names a stock video clip as the example.
- `pexels.py` reads `data["photos"]` only. Rung 4 is stills-only.
- `CameraMovement` declares six values; `build_zoompan_expression` implements four, no-ops `STATIC` correctly, no-ops `SPLIT_FRAME` as a documented gap.
- **The user writes the script.** `POST /{project_id}/script` → `project.script`; the Scene Planner does `narration_text = script[start:end]`. **No planner writes prose.**
- `split_narration_fragments` is two-pass: `_SENTENCE_END_CHARS = ".!?…।"`, then `_CLAUSE_SPLIT_CHARS = ",;:—"` (not hyphen). **The granularity floor is the clause, not the sentence.**
- **Measured on `m8_test_project`:** 662 chars → **N = 13 fragments**, and the project has exactly **13 shots** — the Shot Planner already ran at maximum granularity. `D` = 46.0s → **14.4 chars/sec (English)**. `D/N` = **3.54s**, matching the measured average shot duration exactly. Individual fragments range **0.4s to 7.9s**.
- `Timeline.validate_constraints` takes all five bounds as **keyword arguments**; the only call sites pass `settings.*`. Making them style-derived is a call-site change, not a rewrite.
- The A26 split is real: `_validate_structural_invariants` (total duration, shot count, scene count) always applies; `_validate_planning_time_shot_bounds` (min/max shot duration) is skipped once `metadata.narration_locked` is set.
- **No `local_music.py` exists.** The curated-library decision (M4–M10) is adopted but **not built**; `MUSIC_PROVIDER` is still `openverse`.
- `music_bed_gain_db` / `music_duck_gain_db` are global config and already in the render fingerprint (R2).
- `music.py` loops the bed with `-stream_loop -1` and trims to the ffprobe-measured duration.

**Searched for and did not find:**

- Any validation that a transition's `duration_s` is less than its shot's `duration_s`. See §5 — this is a *risk to confirm*, not a claimed bug.

**Inferred, not observed:**

- That a real Kling clip renders as a frozen frame end to end. This follows necessarily from the code above, but **no run has demonstrated it** — neither live run resolved a shot to `generate_video`. ⚠ Confirm before building on it (§8, Q1). One hour, and it either validates this plan's premise or corrects it.

**Estimates, not measurements:**

- Every day-figure. They assume the pace of M5–M9 with AI assistance. Time that requires a human watching output or real API spend is called out separately in §7 and does not compress.

---

## 1. Track A — the motion clip input path

### A1. Renderer accepts motion (2–3 d) — the keystone

A shot is currently a still. It must become **a still or a clip**, decided per shot.

**Path:** classify by probing with ffprobe, not by asking Pillow whether it can open the file; add a third input branch in `_render_run` (normalise fps/SAR/resolution, scale-and-crop to canvas, fit to shot duration); gate `ensure_still_image` on that classification so it only touches genuine stills. Leave its GIF handling alone — that behaviour is correct and load-bearing.

**Pitfalls:**

- ⚠ **Ken Burns must not run on a clip.** Moving the camera over already-moving footage looks like a bug and will be read as one. Decide this in one place.
- ⚠ **Generated clips may carry audio.** Narration is the only voice (D1). Drop clip audio explicitly at input.
- ⚠ **The single-decoded-frame trick does not apply.** `ken_burns.py`'s whole docstring is about feeding `zoompan` exactly one frame; a motion clip is the opposite case. Do not merge the two paths "for symmetry" — the jitter bug returns.
- ⚠ **`xfade` offsets assume durations D5 already governs.** Any fitting rule from A2 must feed the same duration function the crossfade offsets come from, or audio drifts against picture progressively — presenting as a mystery, not as a transition bug.

### A2. Duration reconciliation (0.5 d)

Narration is the master clock. Kling returns a fixed length. The shot needs 3.2s. One rule, one function, beside the existing D5 arithmetic. Clip longer → trim. Clip shorter → **recommendation: hold the last frame.** Looping reads as a glitch; slowing changes the motion's character and fights fps normalisation.

**Caution:** this is a creative decision wearing an arithmetic costume. Document the choice in the function, as D5 is documented, or it will be "fixed" later.

### A3. Verify the Kling duration contract (0.5 d)

`fal_video.py:38` clamps to 3–15s and sends `duration` as a stringified int. Kling's standard tier commonly accepts a small enum. ⚠ **Same class of assumption that made Pixabay's music API a phantom.** Check the live schema. If the real values are `"5"`/`"10"`, shots of 1.5–8s pay for 5s and use part of it, which changes A4's cost model.

### A4. Motion-vs-still becomes a real decision (1 d)

`asset_plan.preferred_type == VIDEO` is planner output today; nothing calibrates when it should be chosen and nothing prices it. At ~50¢ per motion shot vs ~1–3¢ per image, an uncalibrated planner is a budget event. Prompt guidance for when motion earns its cost, plus a per-project cap.

### A5. Bring the video path onto the one-gate model (0.5 d)

Already in the Backlog, already deferred once. `_generate_video_real`/`_generate_checked_keyframe` still run the old constraint-check and bounded-retry loop the image path shed on 2026-08-16 — so a video shot can still be killed outright by a constraint violation, the exact failure that destroyed the German-tank shots. ⚠ **Apply the identical treatment, rather than inventing a third behaviour.**

### A6. Gate UX for motion (1–2 d)

The review screen must play a clip. Regeneration takes minutes, so `POST /shots/{id}/generate` cannot stay a blocking round-trip for video. The Backlog's missing batch endpoint stops being an ergonomic nit here.

### A7. Pexels video rung (1 d)

The cheapest motion in the system, and it sits *below* paid generation on the ladder — "reuse before generate". **Build immediately after A1:** it exercises the new motion path at zero spend, which is the right way to prove A1 before pointing it at a paid API.

### A8. The bake-off, now unavoidable (1 d + spend)

Defensible to skip while generation was a rare fallback. Not once synthetic motion sits beside a 1936 photograph — "does this blend" becomes the whole question. ⚠ **Requires a human watching output.** Budget as calendar time. Keep the losing renders.

---

## 2. Track B — the style catalogue

### 2.1 A style binds at three levels, not two

This is the correction that matters most. A style preset is **not** one bundle of render flags:

| Level | What it sets | Mutability |
|---|---|---|
| **Render settings** | grade, grain, vignette, letterbox, caption treatment, bed/duck gains | changeable any time; re-render is cheap |
| **Planner prompt fragments** | Director's `creative_context`; Shot Planner's fragments-per-shot and camera/transition vocabulary | changeable up to the gate; requires re-planning (cents) |
| **Constraint bundle** | `max_shots_per_project`, `min_shot_duration_s`, `max_shot_duration_s` | same as above |
| **The user's script** | sentence and clause structure — the pacing floor | **not settable by any preset** (see Track D) |

**The freeze line is the approval gate**, and it falls out of I6 rather than being invented:

- Re-planning costs **cents** (four LLM calls)
- Narration is cached on content hash, and **style does not change the words** → cache hit → **free**
- Asset search is free
- Generation costs **dollars**

So **style is freely changeable right up to the gate and frozen after it.** The frontend should present the picker at project creation and keep it live on the progress screen until approval; read-only afterwards.

**Narration speed IS part of the preset — decided 2026-08-17, in v1.** It is the one style parameter that changes an input to narration rather than to the render, so it is called out separately here.

**Why it is in, stated precisely, because the obvious reason is the wrong one.** Speed is *not* primarily a pacing lever — on the `m8` fixture (`N`=13) it cannot fix fast-cut pacing at all, since max shots is fixed at 13 and reaching a 1.75s average would need `D` down to 22.75s, i.e. **2.0× speed**, which is unlistenable. Punctuation (§3.2 level 2) is what solves pacing.

**Speed is what makes the delivery match the cutting.** Punctuation alone yields ~1.85s shots spoken in a measured documentary voice — exactly the mismatch §2.5 warns about. Speed is the piece that fixes it. It is a *voice* lever that helps pacing, not a pacing lever that changes the voice.

| Setup | `D` | `N` | `D/N` | vs 1.75s target |
|---|---|---|---|---|
| Baseline | 46.0s | 13 | 3.54s | 2× too slow |
| Speed 1.2× only | 38.3s | 13 | 2.95s | still 1.7× too slow |
| Punctuation only (`N`→26) | ~48s | 26 | 1.85s | passes |
| **Punctuation + 1.2×** | ~40s | 26 | **1.54s** | passes comfortably |

**What it costs, and what must not be missed:**

- ⚠ **`compute_narration_content_hash` must include speed.** It currently keys on `(text, voice_id, model, output_format)`. Without speed in the key the cache **silently serves wrong-speed audio** on the second run. `voice_id` is already there, so this is an existing pattern, not new machinery. The render fingerprint inherits it transitively via the narration content hashes.
- **Re-synthesis cost is cents**, not dollars — 662 characters on the fixture. Style freezes at the gate, so you synthesise once at the chosen speed; changing style pre-gate costs the same cents as any other style change.
- ⚠ **Speed support on the configured ElevenLabs model is unverified.** Live schema check, ~10 minutes, same class of assumption as Pixabay. Do it before building.
- ⚠ **Speed and punctuation partially cancel.** Commas add TTS pauses (`D` grows); speed removes them (`D` shrinks). Do not tune the two independently.
- ⚠ **Practical quality ceiling ~1.15–1.25×.** Past that ElevenLabs prosody degrades, and Hinglish will likely degrade earlier and differently than English — `hinglish_final_project` is the fixture for that.

`narration_locked` already exempts measured durations from the planner's shot-duration floor, so shorter measured shots need no constraint change — the fixture's own 0.6s and 1.33s shots prove that path works in production.

### 2.2 The I1 line — where a style decision is allowed to live

⚠ **Do not let the renderer apply style-based camera behaviour.** If the renderer decides camera moves from a preset, the Timeline no longer describes what the video looks like and `Shot.camera` becomes dead config — the exact trap flagged twice already in the guide.

- **Per-shot creative decisions** (camera, transitions) → written into the Timeline **by the planner**, with the style constraining the prompt's vocabulary. Timeline stays the source of truth (I1).
- **Global look settings** (grade, caption style, watermark, gains) → render settings, selected by the style, fingerprinted.

### 2.3 Style is chosen by a human, not by a planner

Two precedents exist in the codebase: `creative_context.visual_style` is **AI-written free text**; `metadata.voice_id` is **human-set, structured, nullable → config default**.

Style belongs to the `voice_id` family. It is a taste decision about the channel, not a fact about the script; free text cannot drive a `filter_complex`; and it must be known *before* the Shot Planner runs, so a planner choosing it would be choosing it during the stage it needs to influence. A planner may *suggest*; it never decides.

Field: `metadata.render_style`.

### 2.4 Tier 1 — no new infrastructure

| Style | What it is | Effort |
|---|---|---|
| **Ken Burns refinements** | easing, combined zoom+pan, vertical pan (needs `UP`/`DOWN` on `CameraDirection`), saliency-anchored zoom | 1–2 d |
| **Fast-cut / retention** | punch-in step zooms at phrase boundaries, word-by-word caption highlight | 2–3 d |
| **Archival montage** | harder cutting, full-frame text cards, music more present | ~2 d |
| **Static / letterbox** | long holds, no motion, bars — a deliberate register, not a fallback | 0.5 d |
| **Colour grade / grain / vignette** | where a channel's look actually lives | 1–2 d |

Two things make Tier 1 cheaper than it looks:

- **The grade costs no extra encode.** `render.py` already runs exactly one video re-encode that captions and the watermark share, composed as chained filter fragments. A grade fragment joins that chain. Highest visual-impact-per-day item in the document.
- **Fast-cut's hard problem is already solved.** The style normally needs speech-to-text alignment; ElevenLabs hands you character-level timings and D2 already builds captions on them. The punch happens *within* a shot on the same image, so the timeline never changes and the planners need no change at all.

⚠ **Ken Burns saliency and the vertical-crop backlog item are one problem.** "Landscape source in a vertical render" and "zoom always targets frame centre" both resolve with one anchor point. Fix together.

### 2.5 Fast-cut has two routes, and they stack

**Can this system produce a fast-paced style? Yes — by two independent routes that should ship together.**

**Route 1 — punch-ins. Renderer-only. Works on any script, including today's timelines.**
The shot boundaries never change. A hard step-zoom at a phrase boundary *inside* a shot is read by the eye as a cut — it is the same technique invented for talking-head footage that has no cuts to work with. On the real fixture (3.54s average) two punches per shot gives a visual event every ~1.2s, which is genuine fast-cut rhythm.

- Nothing upstream changes: no planner, no timeline, no script.
- Driven by the character-level alignment D2 already uses for captions.
- ⚠ **Ceiling: ~2–3 punches per image.** A punch re-frames, it does not reveal — the eye works out it is the same photograph. The fixture's 7.9s fragment would need four, which is past the edge.

**Route 2 — genuinely shorter shots. Needs the script to cooperate.**
This is what fixes the long-fragment dead stops Route 1 cannot. Four pieces, all specced elsewhere in this document and assembled here:

| Piece | Where | Change |
|---|---|---|
| More fragments | §3.2 level 2 | punctuation suggestions — **same words**, more `,;:—` |
| Shot Planner instruction | §4.1, §4.3 | style fragment instructing one fragment per shot at the finest setting |
| Shot-count cap | §4.2 | `max_shots_per_project` ~55–60 for fast-cut (90s ÷ 1.75s ≈ 51 + headroom) |
| Duration floor | §4.2 | `min_shot_duration_s` **~0.8s** for fast-cut — a planning heuristic only, and A26 already exempts measured durations, so the risk is low. The fixture's own 0.6s and 1.33s shots prove sub-floor shots already exist in production |
| **Narration speed** | §2.1 | **~1.2×**, in v1. Contributes ~17% to pacing but its real job is making the *delivery* match the cutting — the piece that resolves the mismatch warned about below. Requires speed in the narration content-hash key |

⚠ **Ship both routes together.** Route 1 alone gives a fast-*looking* video over documentary-paced narration, which reads as mismatched rather than fast — and the punch-ins get blamed when the problem is the voice. Route 2's speed component is what closes that specifically.

### 2.5.1 What actually constrains Route 2: variance, not average

On the real fixture, fragments run **0.4s to 7.9s**. Even at one-fragment-per-shot, fast-cut would place a 7.9s shot beside a 0.4s one, and a single 7.9s shot in a fast-cut video is a dead stop.

**So the binding metric for fast styles is `max(fragment)`, not `D/N`.** Track D must report both — the fixture fails `D/N` by 2× and `max(fragment)` by 4.5×, and the second is the one that would ruin the result.

⚠ **`min_shot_duration_s` at 0.8s interacts with the transition risk in §7.** A 0.4s default dissolve on a 0.8s shot is half the shot, and no validation of transition-vs-shot duration appears to exist. Fast-cut is cuts-only so the style itself avoids it — but confirm the check before any style goes near sub-1.5s shots.

### 2.6 Tier 2 — real work, no new dependency

- **Text cards with motion** (~2 d). ⚠ Scope honestly: ASS and `drawtext` give timed reveals and animated cards, **not** a *True Detective* title sequence — that wants a real compositor. Name it "text cards with motion" in config and docs.
- **Extra transitions** (0.5 d). `xfade` exposes ~50 and the type passes straight through. ⚠ Restraint is the feature — add a slow wipe and a dip-to-black; leave the other forty-eight. D5's overlap arithmetic must hold exactly.
- **Split-screen** (3–5 d). The one the schema already promises. Needs a second asset per shot, reaching into the Shot Planner and asset resolution — genuinely a pipeline change, which is why `SPLIT_FRAME` renders static today rather than pretending.

### 2.7 Tier 3 — behind Track A

- **2.5D parallax.** [DepthFlow](https://github.com/BrokenSource/DepthFlow) is open source, Python, CLI, ffmpeg-piping. ⚠ **It is a GPU/shader render; inline in the renderer it would break I5.** Treat parallax as **a provider, not a filter**: still in, clip out, cached by content hash exactly like `generated_clip`. The renderer only ever sees an mp4, so determinism holds on the cached artifact. Requires A1 — and is the clearest illustration of why A1 is a boundary rather than a feature.
- **AI image-to-video** — Track A.
- **Stock footage** — A7.

### 2.8 Ship three presets, not eight

Every style × planner pair is a behaviour that can regress, and there are four planners. Three styles is 12 behaviours to keep working; eight is 32. **Recommendation: `documentary_archival` (today's behaviour, named), `retention_fast`, `stillness`.** Enough to prove the architecture, few enough to tune properly.

⚠ **Format caution.** The render is 9:16. Fast-cut and text-driven styles were born vertical and will feel native. Ken Burns and archival montage were born in 16:9 and fight the frame — the same tension already in the Backlog. A preset should declare which format it was designed for.

---

## 3. Track D — script pre-flight

Runs at **project setup, before the pipeline starts.** Not a workflow step — the run keeps exactly one gate, and the 2026-08-16 one-gate redesign is not reopened.

### 3.1 Two checks, deliberately different in kind

**Check 1 — Feasibility (code, deterministic) → BLOCKS**

- `D / N` vs the style's pacing band — the hard floor, since a shot is at minimum one fragment
- `max(fragment)` vs a ceiling — the dead-stop check from §2.5
- `N` vs the style's shot cap — see §3.4
- `D` vs `max_video_duration_s`

**Check 2 — Suitability (LLM, cached on `(script_hash, style)`) → WARNS, never blocks**

- subject matter vs the style's native domain
- register and tone
- whether visual material plausibly exists — the check that predicts a script will generate every shot because nothing archival covers it

⚠ **It must not return a boolean.** A yes/no from a model on an ambiguous question is confidently wrong often enough to be dangerous. Return a verdict **plus reasoning** — a user can disagree with a reason; they cannot argue with a bare "no".

**Why block on one and warn on the other:** feasibility is arithmetic, and hard-stopping someone on a fact is defensible. Suitability is a model's taste, and hard-stopping someone's own script on taste will eventually be wrong with no argument available. Blocking on the first, warning on the second, is a deliberate split — not an inconsistency.

**Feasibility only ever fails in one direction, and this simplifies the whole check.** A shot is at minimum one fragment, so a script imposes a *floor* on pace — you cannot go faster than `D/N`. But you can always go slower, because the Shot Planner can merge any number of adjacent fragments into one longer shot. Therefore:

- **Fast styles can genuinely be impossible** on a given script, and are the only thing feasibility ever blocks.
- **Slow styles hit soft walls at worst.** Archival montage and stillness are reachable on any script; they need no blocking feasibility check.

**Worked on the real fixture (`N`=13, `D`=46.0s):**

- *Archival montage, 4–8s target* — merge to `[1,2]`=7.0 · `[3,4,5]`=3.5 · `[6]`=6.7 · `[7,8]`=8.4 · `[9]`=2.0 · `[10]`=7.9 · `[11,12]`=3.2 · `[13]`=6.5. **8 shots, 5.75s average.** Reachable, and merging further is always available.
- *Fast-cut, ~1.75s target* — needs ~26 shots; the script can produce at most **13**. **Impossible**, and no prompt or config change reaches it. The only fix is more fragments, i.e. Track D level 2.

**The per-shot wall is sharper than the average one.** Fragment 10 is 7.9s and atomic, so under fast-cut it stays a 7.9s shot regardless of any planner decision — 4.5× the target, and a single dead stop that would ruin the style. The fixture therefore fails fast-cut on `D/N` by 2× and on `max(fragment)` by 4.5×; the second is the one that matters.

⚠ **"Slow always works" is true in aggregate, not per shot.** Fragments are lumpy: in the archival grouping above, `[3,4,5]`=3.5s and `[9]`=2.0s fall under a strict 4s floor and `[7,8]`=8.4s exceeds 8s. This is not blocking — under A26 the shot-duration bounds are planning heuristics skipped once `narration_locked` is set, so lumpiness at planning time is already tolerated by design. But a slow style's band should be treated as a target, not a gate.

A style's preset should declare whether it has a pacing floor to check. For the slow half of the catalogue the answer is "none", and the check is skipped rather than trivially passed.

### 3.2 The three intervention levels — all in v1

| Level | What it does | The user's words |
|---|---|---|
| **1. Diagnose** | Shows the fragment table with predicted durations; highlights spans that are too long | untouched |
| **2. Suggest breaks** | Proposes punctuation insertion points; accepted per-span | untouched |
| **3. Rewrite phrasing** | Splits sentences by rephrasing, where punctuation cannot | changed |

**The insight that makes levels 1–2 powerful:** the splitter breaks on **punctuation**, not meaning. So

> "Germany faced a severe oil shortage because it had very little natural petroleum."
> "Germany faced a severe oil shortage, because it had very little natural petroleum."

is **the same words, one comma, two shots instead of one.** For a large share of cases, fast pacing needs the script *re-punctuated*, not rewritten.

⚠ A comma makes the TTS pause, so `D` grows slightly and delivery gets more clipped. For fast-cut that is the intended sound, but it is not free and the calibration must account for it.

**Level 2 also shrinks the LLM's job to something safe.** It stops being *"rewrite my script"* and becomes *"where can this sentence naturally break?"* — one span at a time, each one accepted or rejected by the user. A wrong suggestion is a rejected checkbox rather than a corrupted script, and the model is never holding the whole text at once. That is the entire reason levels 1–2 carry the fear-reduction work that level 3 cannot: **the user's words are never in the model's output.**

### 3.3 The rewrite, and how it is validated in code

Scope: **phrasing only** — same facts, same order, same claims; only sentence length and rhythm change.

⚠ **Your content is historical and there is no fact-check step anywhere in this pipeline.** A model rewriting Fischer-Tropsch narration can silently introduce a wrong date, plant, or name, and nothing downstream would catch it. The Director's `constraints` are about imagery, not facts. This risk scales with rewrite freedom, which is why the scope is the tightest of the three considered.

Deterministic backstops, in the S1/S2 spirit:

- **Numeric tokens preserved** as a multiset
- **Capitalised entities preserved** — `Leuna-Werke`, `Sasol`, `Fischer-Tropsch`
- **Fragment count actually increased** — else the rewrite was a no-op; reject it
- **Feasibility re-run** on the result

⚠ These are backstops, not proof — a rewrite can preserve every number and name and still shift meaning. **The side-by-side diff shown to the user is the real safeguard.**

### 3.4 The silent-degradation failure this prevents

Fast-cut on a well-punctuated 90s script gives `N` ≈ 55 fragments. The Shot Planner goes one-per-shot → 55 shots → exceeds `max_shots_per_project` → `validate_constraints` fails → **the repair loop merges fragments to get under the cap** → shots lengthen → **the video comes out slower than the style promised and nobody is told.**

That is the worst failure shape available here: the user picked fast-cut, got medium-cut, and no error appears anywhere. The pre-flight's `N`-vs-shot-cap check converts it into an early, explicit choice.

### 3.5 Provenance and freezing

- `project.script` — current, what planning reads
- `project.script_original` — nullable, set on first rewrite only
- `project.script_source` — `user` | `rewritten`

Rewriting twice loses the intermediate, which is acceptable: the original always survives, so any known state is recoverable and rewrites cost cents.

**The script freezes once planning starts.** Re-running the pre-flight against a project that already has a timeline would silently invalidate every version built on the old text.

### 3.6 Calibration

`662 chars / 46.0s` = **14.4 chars/sec (English)**, from a real measured run. `hinglish_final_project` gives the Devanagari constant the same way. ⚠ **Calibrate before you block** — you would be hard-stopping a user on the basis of an estimate. Record the error band and set thresholds to fire only on unambiguous mismatch.

### 3.7 Architectural placement

The suitability check is **not a fifth planner** — it never writes to the Timeline. Its closest relative is `app/assets/depiction_check.py`: an LLM-backed check returning a verdict without touching creative state. Following that pattern keeps it clear of the four-planner chain and clear of I4, since the verdict only ever informs a human.

---

## 4. Style and the planners

### 4.1 Which planners change

| Planner | Changes? | What the style controls |
|---|---|---|
| **Director** | yes | `creative_context` — `visual_style`, `camera_language`, `colour_palette`, `tone` — plus `music_plan` |
| **Scene Planner** | barely | fragment ranges per scene; **leave alone in v1** |
| **Shot Planner** | **most** | fragments-per-shot (pacing), `camera` vocabulary, `transition_out` |
| **Asset Planner** | **yes, and it costs money** | `preferred_type` IMAGE vs VIDEO, `strategy`, `search_queries` |

⚠ **Director vs preset is a two-sources-of-truth risk.** If the preset dictates a desaturated grade and the Director writes `colour_palette: ["warm amber"]`, which wins? Decide explicitly — preset seeds the Director, or preset overrides — and write it down.

### 4.2 The constraint bundle

| Bound | Enforced | Style-derived? |
|---|---|---|
| `max_video_duration_s` | always (structural) | no |
| `max_scenes` | always (structural) | no |
| `max_shots_per_project` | **always (structural)** | **yes — the one that actually gates fast-cut** |
| `min_shot_duration_s` | planning-time only | yes — low risk |
| `max_shot_duration_s` | planning-time only | yes — low risk |

The two shot-duration bounds are already exempted once `narration_locked` is set, so lowering the floor for fast-cut affects only planner *estimates* — measured reality was never bound by them. Proven by the fixture's own 0.6s shot.

Fast-cut at 90s and ~1.75s/shot needs ~51 shots; budget ~55–60. **Decided: fast-cut is allowed to lean harder on paid generation** — which walks into the reuse-repetition problem in §6.

### 4.3 Prompt organisation

`app/prompts/` already has a directory per planner. ⚠ **Do not create a prompt file per style per planner** — 4 × 5 is 20 files that drift apart. **One base prompt per planner plus one style fragment per style**: 4 + 5 = 9, and a style is readable in one place.

---

## 5. Music, audio, and sound effects under styles

**Timing is lucky here: the curated local music library (M4–M10) is adopted but not built.** There is no `local_music.py` and `MUSIC_PROVIDER` is still `openverse`. Style can be folded into the library's *design* rather than retrofitted.

### 5.1 The taxonomy has no axis for style

The planned six categories — `documentary_dark`, `documentary_mystery`, `documentary_ambient`, `industrial`, `historical_epic`, `emotional` — all describe **what the video is about**. None describes **how it is cut**. There is no category a fast-cut video could use: `documentary_dark` is sombre and slow by construction, and a fast-cut WWII piece needs dark subject matter with driving energy.

Two axes are needed:

- **Content mood** → Director picks (it sees the whole script)
- **Style energy** → the preset picks (bedded/ambient vs driving/rhythmic)

⚠ **Do not build the full cross-product.** 6 moods × 3 energies × 2–3 tracks is 36–54 tracks to source and verify **by ear** — human time that does not compress. Add a small number of energy-specific categories instead.

**This decision is free today and expensive after a library has been curated on the old taxonomy.**

### 5.2 Free and near-free wins

- **Per-style bed/duck gains.** `music_bed_gain_db`/`music_duck_gain_db` are global config already in the render fingerprint. Making them per-style is ~0.5 d and genuinely differentiating: archival wants the bed present, fast-cut wants it driving and barely ducked, stillness wants it near-absent.
- **Silence as a legitimate style value**, not a failure. `_resolve_music_track` already returns `None` cleanly and the render proceeds silent-but-narrated. Costs nothing.
- **BPM as a manifest field.** With a curated library a human types it in — **no beat-detection code, no new dependency.** Free now, awkward later.

### 5.3 Tempo matching without breaking D1

⚠ Cuts landing on beats is not directly available — narration is the master clock, so shot boundaries are fixed by speech. **Invert it: rank tracks by how well their BPM fits the measured shot pacing.** 1.75s shots ≈ 137 BPM on a 4-beat bar. A ranking criterion fitting the existing `music_ranking.py` shape, touching D1 not at all. ~1 d, after the library exists.

### 5.4 The one-bed decision reopens itself under long-form

M8 chose one bed per video, and its own reasoning was that *"at D7's 90-second ceiling, swapping tracks reads as choppy rather than dynamic… Per-scene scoring becomes right somewhere past two or three minutes, and the input for it is already present (`scene.emotion`), so this is a deferral, not a dead end."*

**Track C takes you to ten minutes. By that decision's own terms, long-form is the trigger to revisit it** — and `energy_arc`, which the Director writes today and which a single flat bed structurally cannot express, becomes meaningful for the first time. At 90 seconds it is close to decorative.

### 5.5 Sound effects — genuinely missing

No SFX layer exists. For fast-cut that is a real gap: a punch-in without a whoosh reads as flat, and text cards want stingers.

The irony is that the guide flagged the solution as a problem — *"Freesound skews to sound effects"* was a complaint about music search. For SFX it is the entire point: same Openverse provider, same licence gate, different query.

**Placement follows D6/21.2 exactly:** choosing the palette is creative → `sfx_plan` in the Timeline; placing and mixing is deterministic → the renderer, driven by events already in the Timeline (punch-ins from `camera`, text cards, transitions). No new per-SFX creative decisions.

⚠ **The mixing is the real cost.** `music.py` builds a static volume envelope over one track. Adding N short overlays at computed offsets alongside narration and a ducked bed is a materially larger filter graph that must stay bit-exact for I5. This sounds small and is not. **3–4 d plus curation, in its own batch, after fast-cut ships.**

---

## 6. Track C — long-form (90 s → ~10 min)

Three config lines change in under a minute. Everything behind them is the work.

| # | What breaks at ~200 shots | Path | Effort |
|---|---|---|---|
| **C1** | **Scene planning is one LLM call over the whole script** — output ceiling, then quality collapse, then validator-rejection loops | Hierarchical pass: script → acts → scenes. Shot planning is already per-scene and needs only bounded concurrency | 2–3 d |
| **C2** | Narration is a serial per-scene loop | Bounded concurrency; the per-scene content-hash cache already makes it safe and resumable | 0.5 d |
| **C3** | **Render blows up.** Every shot in a run is a simultaneous `-i` input in one `filter_complex`, and `-threads 1` (required for determinism) means single-threaded x264 across ten minutes | Per-scene segment render + concat, with **per-segment fingerprints** | 3–4 d |
| **C4** | Asset reuse is a soft ranking penalty — already repeats a photo twice inside 41s | The Backlog's temporal reuse rule stops being optional | 1 d |
| **C5** | One gate showing 200 shots is not reviewable | Scene-grouped review, bulk actions; the 480p draft becomes the primary review artifact | 2–3 d |
| **C6** | $10 budget cap; runs of tens of minutes | Re-derive the cap per minute of output; **fix the orphan-run bug first** | 1 d |
| **C7** | A 3-minute bed looped 4× under 10 minutes | Per-scene scoring — see §5.4 | 0.5–2 d |

**C3 is the architectural one, and it is the good kind.** Per-segment fingerprinting means editing scene 7 re-renders scene 7 — which makes the existing I5 cache dramatically more valuable *even at 90 seconds*, so it pays for itself before long-form ships.

⚠ **C6 has a blocking dependency that is easy to under-rate.** The Backlog's *"a hard-killed process leaves a project permanently unresumable"* (`trigger.py::_claim_or_join`) is survivable at four-minute runs. At forty minutes a Ctrl-C or reboot mid-run becomes **routine**, and recovery is hand-editing Postgres. The preferred fix is already written down — reclaim orphans in `main.py`'s `lifespan`, where a `"running"` row observed at startup is provably orphaned under the single-instance assumption. Half a day. **Land it before the first long run, not after the first loss.**

⚠ **C4 is a quality cliff, not a nit** — and fast-cut makes it worse, since it triples shot count for the same runtime.

---

## 7. Cross-cutting cautions

**Determinism (I5) decides which tier a style lands in.** Anything model-based or GPU-based sits behind a cached provider boundary, never inline in the render path. That is what puts parallax in Tier 3 rather than Tier 1, and it is not negotiable without reopening I5.

**The fingerprint is the third repeat of one lesson.** Music gain (R2), then captions, then the watermark. Every new render input — style preset, grade parameters, motion fitting rule, segment boundaries, SFX — enters `compute_render_fingerprint` or the cache silently serves stale output. ⚠ Assume this will be forgotten once and add a test that fails when it is.

**⚠ A transition-duration risk to confirm.** `default_transition_duration_s = 0.4`. On a 0.8s fast-cut shot that is half the shot, and D5 says transitions *overlap* — `cumulative = cumulative + duration - overlap`. I searched and **found no validation that a transition's duration is less than its shot's duration**. Not a claimed bug; a check that appears to be absent. Confirm before any style goes near sub-1.5s shots. The style itself mitigates it (fast-cut is cuts-only), but nothing structurally stops a planner emitting a dissolve on a short shot.

**⚠ `pytest` truncates the shared Postgres — the same database the dev server uses.** Export any real fixture project (`backend/scripts/export_test_project.py`) before running the suite, and never run two `pytest` processes at once. A live project was lost to exactly this once. This plan leans on `58f0a5e6` throughout.

**Cost discipline gets harder in every direction.** Motion is ~50¢/shot; fast-cut triples shot count; long-form multiplies it again; parallax adds compute. The Backlog's *"LLM calls are never costed"* also grows more visible as planning fans out in C1.

**Scope honesty.** Two features are known to under-deliver against their common names: text cards are not kinetic typography, and `SPLIT_FRAME` is declared but unbuilt. Both are currently documented as gaps rather than mis-implemented. ⚠ Keep it that way.

---

## 8. Where the edge is

**Nothing in this section blocks any style planned above.** Every style in Track B — Ken Burns, fast-cut, archival montage, static/letterbox, text cards, 2.5D parallax, AI video — sits inside this architecture. This section exists so a *future* request isn't assumed to be a preset away. It is a map, not a warning.

The design generalises well within one shape: **a narrated sequence of visual shots.**

### Animated video — mostly yes, with one real distinction

"Animated" splits two ways, and only one is out of reach:

- **Animated *aesthetic* — supported today, no changes needed.** `creative_context.visual_style` already feeds every generation prompt. Set it to flat vector illustration, cel-shaded anime, or paper-cutout and every generated image adopts that look; Track A's image-to-video path then animates it. This is the existing pipeline with a different string in one field.
- **Controlled animation — out of reach.** A specific arrow travelling a specific path, a diagram assembling step by step, a character acting and lip-syncing. That needs an animation engine that can be directed frame by frame, and generative video cannot be directed at that precision.

The distinction is not "cartoon vs photo" — it is **"a look" vs "precise control over what moves where."** The first is a prompt; the second is a different product.

### Out of reach without new architecture

| Style family | Why |
|---|---|
| Multi-layer compositing (PiP, layered collage) | one image per shot is the contract; split-screen is already a 3–5 d pipeline change for *two* |
| Motion graphics / explainer animation | needs a vector asset system and an animation engine |
| Animated data visualisation, maps, charts | same, plus a data-binding layer |
| Talking head / presenter | no camera, no person, no capture path |
| Avatar or lip-sync driven | different pipeline entirely |
| Interview / multi-voice | narration is a single voice and a single master clock |
| Screen recording / tutorial | needs capture |

**And one architectural boundary rather than a missing feature:** any style where **music, not narration, is the master clock** — music videos, beat-driven montage, purely visual pieces — is out of reach *by design*, because D1 makes narration the clock everything else is fitted to. That is not a gap to fill later; it is a decision, and reaching those styles means reopening D1.

**A useful test for any future style:** if it can be expressed as *(shot boundaries derived from narration) × (per-shot media) × (per-shot camera) × (global look)*, it fits this architecture. If it needs anything else, it is a new pipeline.

---

## 9. Effort

| Track | Engineering | Not compressible |
|---|---|---|
| A — motion path | ~7–9 d | bake-off (human viewing), live fal spend |
| B — Tier 1 | ~5–8 d | grade tuning is eyes-on |
| B — Tier 2 | ~5 d | — |
| B — Tier 3 | ~3–4 d after A | depth-model evaluation |
| C — long-form | ~10–14 d | one real long run to find the true wall |
| D — pre-flight | ~5 d | calibration needs real measured runs |
| Music/SFX | ~5–6 d | track curation **by ear** |

⚠ **The coding is not the bottleneck.** The bake-off needs a human comparing outputs. The grade needs someone with taste iterating on real renders. Music curation needs someone listening to every track. C5 needs someone genuinely attempting to review a 200-shot project. None of that parallelises.

---

## 10. Open questions

**Q1. Does a real motion clip actually render as a frozen frame?** The premise of this document, inferred and never observed (§0). One hour to settle.

**Q2. What duration values does the configured Kling model accept?** Live schema check (A3).

**Q3. Where does the render actually fall over on length?** Raise the cap to ~5 minutes, change nothing else, run one 480p draft. *Where* it fails first is worth more than §11's ordering.

**Q4. Trim-or-hold for a short clip in a long shot?** Recommendation is hold-last-frame; needs agreement, not a default.

**Q5. Target pacing bands per style.** Blocked on calibration data, not on a decision.

**Q6. Preset seeds the Director, or overrides it?** (§4.1.) Cheapest honest answer is "seeds", with the preset winning on conflict.

**Q7. What happens if a rewrite fails code validation?** Retry budget, or fall back to the style-change path?

**Q8. Hinglish calibration** — a single chars/sec constant may not hold for a script mixing Devanagari and Latin. `hinglish_final_project` is the fixture.

**Q9. Does the diagnosis screen re-measure live as the user edits?** It is pure arithmetic — it can run on every keystroke with no API call, and the style picker can show `fast-cut ✗ · archival ✓ · stillness ✓` for the user's own script instantly.

**Q10. Does the parallax provider justify a GPU dependency?** Deferred until after A1 and Q1. The only item here that changes the deployment story.

---

## 11. Sequencing

1. **Q1, Q2, Q3** — a day of cheap information that could reshape everything below.
2. **Track D levels 1–2** — pre-flight measurement, diagnosis, punctuation suggestions. Independent, prevents wasted planning runs, and removes the "the system rewrites my script" fear before it is earned.
3. **A1 + A7** — the motion path, proven against free Pexels footage before any paid API.
4. **A2–A6, then A8** — the rest of Track A, ending with the bake-off.
5. **Orphan-run fix** — half a day, before anything long runs.
6. **Music taxonomy + BPM decision** — design only, but **before any track is curated**.
7. **B Tier 1** — grade and fast-cut first; highest visible payoff per day.
8. **Track D level 3** — rewriting, once levels 1–2 have shown whether it is even needed.
9. **C3 + C1** — segment rendering and hierarchical planning, the two that actually bend the architecture.
10. **C4, C5, C6, C7** — quality and reviewability, without which long-form ships but is not usable.
11. **B Tier 2/3, SFX** — split-screen, parallax, sound effects, once the motion boundary has been load-bearing for a while.

Steps 1–5 are all either information-gathering or repairs to things already known to be broken. **No new capability ships until the ground under it is verified.** Given this plan's central claim is that a paid feature has been silently discarded since M7, that is the right instinct to encode.
