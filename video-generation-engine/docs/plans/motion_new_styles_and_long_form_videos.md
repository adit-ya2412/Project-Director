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

**Confirmed by direct test, 2026-08-17 (implementation start — see §12):**

- **Q1 is answered.** A synthetic 3.0s/24fps/640×360 h264 clip (`ffmpeg testsrc`, standing in for a real Kling output) was run through the real `needs_normalising()` and `ensure_still_image()` — not mocked, the actual functions `render.py:208` calls. `needs_normalising` returned `True` (an mp4 is not Pillow-openable, hitting the exact fallback branch `still.py`'s own docstring names). `ensure_still_image` wrote a single 640×360 PNG and discarded the other 71 frames and all 3.0s of motion. **The frozen-frame failure is now measured, not inferred**, and it happens at `ensure_still_image`, before the shot ever reaches `_render_run`'s compositing. This is the confirmation the whole motion-clip premise (§1) rested on.

**Estimates, not measurements:**

- Every day-figure. They assume the pace of M5–M9 with AI assistance. Time that requires a human watching output or real API spend is called out separately in §7 and does not compress.

---

## 1. Track A — the motion clip input path

### A1. Renderer accepts motion (2–3 d) — the keystone

A shot is currently a still. It must become **a still or a clip**, decided per shot.

**Path:** classify by probing with ffprobe, not by asking Pillow whether it can open the file; add a third input branch in `_render_run` (normalise fps/SAR/resolution, scale-and-crop to canvas, fit to shot duration); gate `ensure_still_image` on that classification so it only touches genuine stills. Leave its GIF handling alone — that behaviour is correct and load-bearing.

**Pitfalls:**

- ⚠ **Ken Burns must not run on a clip.** Moving the camera over already-moving footage looks like a bug and will be read as one. Decide this in one place.
- ⚠ **Generated clips may carry audio.** Narration is the only voice (D1). **Fix at the source**, not just at input: pass `generate_audio: false` in the fal request (confirmed live field, A3) rather than relying only on ffmpeg to discard an audio track that shouldn't have been generated — and paid for — in the first place.
- ⚠ **The single-decoded-frame trick does not apply.** `ken_burns.py`'s whole docstring is about feeding `zoompan` exactly one frame; a motion clip is the opposite case. Do not merge the two paths "for symmetry" — the jitter bug returns.
- ⚠ **`xfade` offsets assume durations D5 already governs.** Any fitting rule from A2 must feed the same duration function the crossfade offsets come from, or audio drifts against picture progressively — presenting as a mystery, not as a transition bug.

### A2. Duration reconciliation (0.5 d)

Narration is the master clock. Kling returns a fixed length. The shot needs 3.2s. One rule, one function, beside the existing D5 arithmetic. Clip longer → trim. Clip shorter → **recommendation: hold the last frame.** Looping reads as a glitch; slowing changes the motion's character and fights fps normalisation.

**Caution:** this is a creative decision wearing an arithmetic costume. Document the choice in the function, as D5 is documented, or it will be "fixed" later.

### A3. Verify the Kling duration contract — **DONE, 2026-08-17: the code is already correct**

`fal_video.py:38` clamps to 3–15s and sends `duration` as a stringified int. This plan originally worried Kling's standard tier might accept only a small enum (e.g. `"5"`/`"10"`), which would have broken the cost model in A4.

**Checked against fal's own live API docs** (`fal.ai/models/fal-ai/kling-video/o3/standard/image-to-video/api`): `duration` is a `DurationEnum` accepting **every integer second from 3 to 15**, default `"5"`. `fal_video.py`'s existing `max(3, min(15, round(duration)))` → `str(duration)` already matches this exactly. **No code change needed here.**

⚠ **New finding from the same schema check, not previously known:** the model also exposes a `generate_audio` boolean, which `fal_video.py` never sets — so it rides the model's undocumented default rather than an explicit choice. This sharpens A1's "generated clips may carry audio" pitfall below: the correct fix is passing `generate_audio: false` in the request, not only discarding an audio track in ffmpeg after the clip is already downloaded.

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

### 3.4 The shot-cap failure this prevents — **corrected twice, 2026-08-17; the original "silent degradation" claim was simply false**

**This section originally claimed that exceeding `max_shots_per_project` causes the repair loop to merge fragments, silently producing a slower video than the style promised. That is wrong, and so was the first correction to it. Verified against the real code:**

Fast-cut on a well-punctuated 90s script gives `N` ≈ 55 fragments → one-per-shot → 55 shots → exceeds `max_shots_per_project`. What actually happens:

- **`max_shots_per_project` is not in the repair-loop validator at all.** `app/planners/shot/planner.py::_make_validator` (line 126) takes only `scene, fragments, min_shot_duration_s, max_shot_duration_s`. The cap is checked *after* `run_structured_with_repair` returns (line 288) and raises `PermanentError` **directly** — no re-prompt, no second attempt, no opportunity for the model to merge.
- **The second check behaves identically.** `app/workflow/steps/generate_timeline.py:108` runs `Timeline.validate_constraints` and returns `StepResult(outcome="failed")` on any violation.

**There is therefore no silent-degradation path for the shot-count cap.** Both routes are loud, explicit failures. The model is never asked to reduce shot count, so it never quietly complies.

**What is actually true, and is still worth preventing:** the check sits inside the Shot Planner's *per-scene loop*, accumulating `total_shots` across scenes — so it dies **partway through planning**, after paying for the Director, the Scene Planner, and however many scene-level Shot Planner calls completed before the cap was crossed. The user sees `PermanentError: shot planner exceeded max_shots_per_project (40) after scene sc_006`.

**Revised justification for the pre-flight `N`-vs-shot-cap check — weaker than this section originally claimed:**

- ❌ *Not* "prevents a silently wrong video" — that failure mode does not exist.
- ✅ Prevents a dead run after most of a planning pass has been paid for (cents-scale, but wasted).
- ✅ Replaces a mid-loop internal error with an actionable up-front message naming the actual fix (more punctuation, or a different style).

This drops the check from **urgent** to **good ergonomics**. It should still ship — it is nearly free once `N` is being computed anyway — but it is no longer a safety feature, and §11's ordering need not privilege it.

### 3.5 Provenance and freezing — **revised 2026-08-17: use the existing script versioning, don't duplicate it**

**Correction to the original design.** `app/models/script.py::ScriptModel` already versions every script change immutably — `_append_script_if_changed` appends a new row whenever content differs, the same discipline as `TimelineService.append_version` (I3). This was found while checking the persistence layer before building, and it makes the originally-planned `script_original`/`script_source` columns on `Project` redundant: they would duplicate, in a weaker form (one-level-back instead of full history), a mechanism that already exists.

**Decided: use the existing mechanism.**

- A rewrite is a **new `ScriptModel` row**, via the same `_append_script_if_changed` path `upload_script` already calls — no new persistence path.
- Add one column: `ScriptModel.source: str` (`"user"` | `"rewritten"`), nullable-default `"user"` for existing rows. Small, additive migration.
- **"The original" is simply version 1** — already queryable via the existing `project_id, version` unique constraint, no new field needed.
- Every intermediate rewrite survives too, which the original two-field design would have lost on a second rewrite — a strict improvement, not just a simplification.

**The script freezes once planning starts.** `upload_script` today has **no such check** — verified directly, it will overwrite at any time. New enforcement: reject `POST /{project_id}/script` once the project has an active timeline (mirrors the check pattern `TimelineService` itself uses for its own immutability). Re-running the pre-flight against a project that already has a timeline would otherwise silently invalidate every version built on the old text.

### 3.5.1 The splitter's clause-pass is conditional — verified directly, changes what "suggest punctuation" must do

**Checked against the real code, not assumed:** `split_narration_fragments`'s clause pass (`,;:—`) only runs **inside a primary (sentence) fragment already over `_LONG_FRAGMENT_THRESHOLD_CHARS` = 80 characters**. Below that threshold, clause punctuation is inert:

```
"Germany faced a shortage, and it hurt badly."          44 chars → 1 fragment (comma ignored)
"Germany faced a severe...hurt it badly indeed."        91 chars → 2 fragments (comma honored)
"Germany faced a shortage. It hurt badly."              → 2 fragments (period always splits, any length)
```

⚠ **"Suggest a comma" is only correct advice above the 80-char threshold.** A script of many short, already-punctuated sentences — a plausible shape for someone *already* attempting punchy writing — would get zero benefit from comma suggestions. Level 2's suggestion engine must pick the punctuation type from the target fragment's current length: **period** (always splits) below ~80 chars, **clause punctuation** above it. This is an implementation correction, not a product decision, so it proceeds without needing sign-off — flagged here so the "same words, one comma" framing from earlier in this plan isn't read as the general case.

### 3.5.2 Style bands are a small standalone config, not a Track B dependency — decided 2026-08-17

Track B's `metadata.render_style` field and full preset system do not exist yet. Track D needs a pacing floor/ceiling per style regardless, so it owns a **small local config** — just the 2–3 styles' `D/N` floor and `max(fragment)` ceiling (§2.5.1, §3.1) — independent of any Timeline field or planner prompt. Track B, when built, reads or extends this same config rather than duplicating it. This unblocks Track D immediately and keeps the two tracks' schedules independent.

### 3.5.3 Endpoint shape — stateless, decided 2026-08-17

Pre-flight is **`POST /{project_id}/script/preflight`**, taking script text and style directly in the request body and returning feasibility + suitability **without persisting anything**. This is what makes live re-measurement on every edit or style change (Q9) cheap and safe — a keystroke-driven check must never create a new `ScriptModel` version, which would fight that table's own "append only on a real, deliberate change" discipline. `POST /{project_id}/script` (persistence) is called separately, once, when the user is done — that endpoint gains the freeze check from §3.5, not the pre-flight logic itself.

### 3.5.4 Suitability verdict — recomputed, not cached — decided 2026-08-17

No existing table shape fits `(script_hash, style) → verdict` in this codebase, and inventing one for a single feature was judged not worth it: the check only fires when the user actively requests it (not on every keystroke — that's the free arithmetic check), so the cost is one cheap LLM call per genuine request. Recompute each time; add persistence later only if the gate screen needs to explain a past verdict without re-asking.

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
| **C3** | **Render blows up — measured, and the crash is sharper than the slow-encode concern this row originally named.** See §12, 2026-08-17: a continuous (no-hard-cut) run of ~90+ shots hits a hard OS argv-length crash on the current Windows dev target, well before single-threaded encode time becomes the bottleneck | Per-scene segment render + concat, with **per-segment fingerprints** — also fixes this crash as a side effect, since segments are short runs | 3–4 d |
| **C4** | Asset reuse is a soft ranking penalty — already repeats a photo twice inside 41s | The Backlog's temporal reuse rule stops being optional | 1 d |
| **C5** | One gate showing 200 shots is not reviewable | Scene-grouped review, bulk actions; the 480p draft becomes the primary review artifact | 2–3 d |
| **C6** | $10 budget cap; runs of tens of minutes | Re-derive the cap per minute of output; **fix the orphan-run bug first** | 1 d |
| **C7** | A 3-minute bed looped 4× under 10 minutes | Per-scene scoring — see §5.4 | 0.5–2 d |

**C3 is the architectural one, and it is the good kind.** Per-segment fingerprinting means editing scene 7 re-renders scene 7 — which makes the existing I5 cache dramatically more valuable *even at 90 seconds*, so it pays for itself before long-form ships.

⚠ **C6 has a blocking dependency that is easy to under-rate.** The Backlog's *"a hard-killed process leaves a project permanently unresumable"* (`trigger.py::_claim_or_join`) is survivable at four-minute runs. At forty minutes a Ctrl-C or reboot mid-run becomes **routine**, and recovery is hand-editing Postgres. The preferred fix is already written down — reclaim orphans in `main.py`'s `lifespan`, where a `"running"` row observed at startup is provably orphaned under the single-instance assumption. Half a day. **Land it before the first long run, not after the first loss.**

⚠ **C4 is a quality cliff, not a nit** — and fast-cut makes it worse, since it triples shot count for the same runtime.

⚠ **The new crash in C3 is about continuous non-cut runs, not raw shot count — fast-cut is structurally immune to it.** `group_into_runs` starts a new run at every hard cut, and §2.4/§2.5 already commit fast-cut to cuts-only, zero dissolve. So every fast-cut shot is its own one-shot "run", and the whole argv-length failure mode in C3 cannot occur under that style regardless of total shot count. It is specifically a risk for long, heavily-dissolved spans — archival montage stretched to long-form is the case that actually exposes it.

⚠ **Not a currently-live bug.** `max_shots_per_project = 40` today is nowhere near the ~85-shot threshold measured in §12 — no existing project can hit this. It is a risk that only appears once Track C raises shot counts, combined with a non-cuts-only style.

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

**Q1. Does a real motion clip actually render as a frozen frame?** **CONFIRMED 2026-08-17** — see §0 and §12. A real video input collapses to one PNG at `ensure_still_image`, before compositing. Closed.

**Q2. What duration values does the configured Kling model accept?** **CONFIRMED 2026-08-17** — every integer 3–15s; `fal_video.py`'s existing clamp is already correct. See A3 and §12.

**Q3. Where does the render actually fall over on length?** **PARTIALLY ANSWERED, 2026-08-17** — see §12. A Windows-specific argv-length crash was found and bracketed at ~85–90 dissolve-joined shots in one continuous run; single-threaded encode time (C3's original framing) measured smaller than expected (12.8s wall-clock for 40 shots / 104.4s of output). **Open remainder:** the equivalent threshold on the actual Linux production target (`backend/Dockerfile`) — not measured, likely far higher, worth 20 minutes in a container before C3 is built.

**Q4. Trim-or-hold for a short clip in a long shot?** Recommendation is hold-last-frame; needs agreement, not a default.

**Q5. Target pacing bands per style.** Blocked on calibration data, not on a decision.

**Q6. Preset seeds the Director, or overrides it?** (§4.1.) Cheapest honest answer is "seeds", with the preset winning on conflict.

**Q7. What happens if a rewrite fails code validation?** Retry budget, or fall back to the style-change path?

**Q8. Hinglish calibration** — a single chars/sec constant may not hold for a script mixing Devanagari and Latin. `hinglish_final_project` is the fixture.

**Q9. Does the diagnosis screen re-measure live as the user edits?** **DECIDED 2026-08-17** — yes, via the stateless `POST /{project_id}/script/preflight` (§3.5.3), which persists nothing, so every keystroke is a free re-check.

**Q10. Does the parallax provider justify a GPU dependency?** Deferred until after A1 and Q1. The only item here that changes the deployment story.

---

## 11. Sequencing

0. ~~**Look at one render first (~0.5 d).**~~ **DONE 2026-08-17 — verdict: holds good.** `build_punch_in_expression` added to `ken_burns.py`, verified pixel-correct against a real archival photo, watched by the user against real production output. See §12. Proceeding on Track B/D with this validated rather than assumed.
1. **Q1, Q2, Q3** — a day of cheap information that could reshape everything below. *(Q1 and Q2 closed 2026-08-17; Q3 partially.)*
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

---

## 12. Implementation log

Appended to as work happens, in sequencing order (§11). Each entry states what was done, what was found, and what changed as a result — not a restatement of the plan.

### 2026-08-17 — Q1 confirmed: the frozen-frame failure, directly observed

**Method.** Generated a synthetic clip standing in for a real Kling output — `ffmpeg -f lavfi -i testsrc=duration=3:size=640x360:rate=24`, h264, 72 frames — and ran it through the actual production functions `render.py:208` calls, unmocked: `app.renderer.still.needs_normalising()` then `ensure_still_image()`.

**Result.**
- `needs_normalising()` → `True`. An mp4 fails `Image.open()`, hitting the `except (OSError, ValueError): return True` branch — the exact fallback path `still.py`'s own docstring names ("a video clip from a stock provider").
- `ensure_still_image()` → wrote one 640×360 PNG (`ffprobe`-confirmed: `codec_name=png`) from a 3.0s/24fps source. All 71 other frames and the full 3.0s of motion are discarded.

**What this settles.** The frozen-frame failure described in the Verdict and §0 is no longer inferred from reading code — it is measured. It also locates the failure precisely: media is discarded at `ensure_still_image`, **before** the shot ever reaches `_render_run`'s compositing stage, not somewhere inside the filter graph. That sharpens A1's actual task: the fix is a classification-and-branch decision made *before* this function runs, not a change to `_render_run` first — `ensure_still_image` must never be called on a genuine motion asset at all, rather than being taught to handle one.

**No architecture question was open here** — A1 already specified ffprobe-based classification ahead of `ensure_still_image`. This test confirms that plan is aimed at the right target and finds no surprise in how the failure occurs.

**Housekeeping note, not a plan change:** the synthetic-clip test script used an ffmpeg path lacking a `.exe` extension and Windows' `CreateProcess` rejected it (`FileNotFoundError`, WinError 2); an absolute path needs the extension on this platform, or the bare command name (`settings.ffmpeg_binary` default is `"ffmpeg"`, PATH-resolved via `PATHEXT`, which is unaffected). This is a property of the test harness, not of `run_ffmpeg` or of production config, and required no code change.

### 2026-08-17 — Q2 confirmed: Kling's duration schema, and a related finding it wasn't looking for

**Method.** Checked fal's own live API docs, `fal.ai/models/fal-ai/kling-video/o3/standard/image-to-video/api` — the exact model string in `settings.fal_video_model`.

**Result.** `duration` is a `DurationEnum` accepting **every integer second from 3 to 15**, default `"5"`. `fal_video.py:38`'s existing `max(3, min(15, round(duration)))` → `str(duration)` already matches this exactly. **No code change needed** — A3 closes as "verified correct," not "found broken."

**Unplanned finding from the same page:** the schema also exposes a `generate_audio` boolean that `fal_video.py` never sets, so it rides the model's undocumented default rather than an explicit choice. Folded into A1's audio pitfall (§1): the correct fix is `generate_audio: false` in the request, not only stripping an audio track from the download afterward, which would mean paying for audio generation that's then thrown away.

### 2026-08-17 — Q3 (long-form probe): two real findings, in opposite directions from what §6 assumed

**Method.** Per the chosen approach (DRY_RUN-equivalent — no DB, no API keys, no pytest, no Postgres touched at all): built a synthetic `Timeline` directly in Python — 480×854 placeholder stills, `STATIC` camera, every shot `DISSOLVE`-joined except the last (one continuous "run" under `group_into_runs`, which is exactly the shape C3 describes: every shot a simultaneous `-i` input in one `filter_complex`) — and called the real `render_timeline()` directly. No mocks inside the render path itself.

**Finding 1 — a hard crash, sharper and earlier than the "slow encode" framing in C3, on this platform.** 100 dissolve-joined shots (~260s of output) failed **immediately** (0.0s) with `FileNotFoundError: [WinError 206] The filename or extension is too long`. Instrumented precisely by capturing the real argv before the subprocess call: **621 arguments, a 38,375-character command line**, against Windows' `CreateProcess` `lpCommandLine` limit of 32,767 characters. Bracketed the threshold on this exact harness: N=85 → 32,660 chars (passes, 107 chars of margin) · N=100 → 38,375 chars (fails). Growth is linear at ~380 chars/shot at these path lengths.

⚠ **This number is dev-environment-specific and must not be read as a production figure.** `backend/Dockerfile` is `python:3.12-slim` — **production is Linux**, and Linux's analogous limit (`ARG_MAX`, typically ~2MB) is roughly 60× more permissive than Windows' 32,767 chars. The crash is real and reproducible on the Windows dev/test machine today; the equivalent Linux threshold was **not measured** and remains an open unknown, likely in the low thousands of shots at these path lengths rather than ~85 — comfortably past anything Track C plans. Flagging honestly rather than either dismissing the finding or overclaiming it as a production blocker.

**Finding 2 — the wall-clock encode-time concern in C3 looks smaller than assumed, not larger.** A real (unmocked) run of 40 dissolve-joined shots (~104.4s of output, today's actual `max_shots_per_project`) completed in **12.8s wall-clock**, single-threaded x264, at draft-ish settings and trivial solid-colour placeholder stills. That is a *floor*, not a ceiling — real archival photos decode/scale more expensively and full render resolution (720×1280 vs this test's 480×854) costs more — but it does not support C3's original framing of single-threaded encoding as the dominant risk at ten minutes. The crash in Finding 1 is the more urgent and more abrupt failure mode of the two.

**What this changes in the plan:**
- C3's table row and cautions (§6) rewritten to lead with the crash, not the encode-time concern, and to state plainly that the crash is Windows-specific and unmeasured on the actual Linux deployment target.
- **New, useful cross-reference:** `group_into_runs` starts a new run at every hard cut, and fast-cut is already committed to cuts-only, zero dissolve (§2.4/§2.5). So every fast-cut shot is its own one-shot run — **fast-cut is structurally immune to this exact crash**, regardless of total shot count. Only long, heavily-dissolved spans are exposed, which is specifically an archival-montage-at-long-form risk.
- **Not a currently-live bug.** Today's `max_shots_per_project = 40` sits nowhere near the ~85-shot Windows threshold measured here — no existing project is at risk. This is a risk Track C introduces, not one already present.
- C3's own fix (per-scene segment rendering) already resolves this as a side effect, since a segment is a short run — worth noting explicitly rather than leaving it as a coincidence.

**Residual unknown, not closed here:** the real Linux/production argv threshold. Cheap to close later with the same script inside the actual `backend/Dockerfile` container rather than on Windows — flagged for whoever picks up C3, not blocking anything before then.

**Next in sequence (§11):** Track D levels 1–2 (script pre-flight), since Q1–Q3 are now closed.

### 2026-08-17 — Track D design check, before writing code

Checked the actual persistence layer, the splitter's byte-level behavior, and the existing LLM-verdict pattern before building anything, per the standing instruction to verify before recommending. Four decisions, all confirmed with the user:

1. **Script provenance uses the existing `ScriptModel` versioning**, not new `Project` columns — `ScriptModel` already immutably versions every script change (`_append_script_if_changed`), a mechanism the original §3.5 design didn't know about and would have duplicated in a weaker form. New: one `source` column (`"user"`|`"rewritten"`) on that table. "The original" is version 1, already queryable. §3.5 rewritten accordingly.
2. **The splitter's clause-pass is conditional on an 80-char threshold** (`_LONG_FRAGMENT_THRESHOLD_CHARS`), verified directly against real strings — a comma below that length does nothing; only a period always splits. §2.5.1 corrects the "suggest a comma" framing used earlier in this plan to the general rule: pick punctuation type by the target fragment's current length.
3. **Style pacing bands are a small standalone config** in Track D's own module, not a dependency on Track B's (unbuilt) `metadata.render_style` field — unblocks Track D immediately; Track B extends the same config later rather than duplicating it.
4. **Pre-flight is a stateless endpoint**, `POST /{project_id}/script/preflight` (script + style in the body, nothing persisted) — required for live re-measurement (Q9) without fighting `ScriptModel`'s append-on-real-change discipline. The suitability verdict is recomputed each call, not cached — no existing table shape fits it and the cost is one cheap call per genuine user-initiated check.

**Also found and will fix in the same pass:** `upload_script` has no freeze check today — it will silently overwrite the script even after a timeline exists. New enforcement added per §3.5.

Proceeding to implement Track D levels 1–2 against these four decisions.

### 2026-08-17 — Track D levels 1–2 built

**New files:** `app/script/__init__.py`, `styles.py` (pacing-band registry, §3.5.2), `preflight.py` (feasibility check, §3.1), `suggestions.py` (punctuation suggestions, §3.2/§3.5.1), `suitability.py` (LLM verdict, §3.7); `app/schemas/script_preflight.py`; `app/prompts/script_suitability/v1.md`; `backend/tests/unit/script/test_preflight.py`, `test_suggestions.py`; `backend/alembic/versions/d3f8a1b6c9e2_...py`.

**Changed:** `app/models/script.py` (+`source` column), `app/providers/base.py` (+`StyleSuitabilityVerdict`), `app/api/projects.py` (+`POST /{project_id}/script/preflight`; freeze check added to `upload_script`), `app/core/config.py` (+calibration constants), `app/planners/fragments.py` (four identifiers promoted from private to public — see below).

**A design correction made mid-build, worth recording:** `suggestions.py` needed `fragments.py`'s split-point logic and its 80-char threshold as a second legitimate consumer. The first draft imported the underscore-prefixed names directly with `# noqa` comments — checked the actual ruff config (`pyproject.toml`, `select = ["E","F","I","UP","B","SIM"]`) before shipping that and found `PLC` rules aren't even enabled, so the noqa comments suppressed nothing real. Fixed properly, matching S2's own precedent ("the splitter moved, not duplicated"): `SENTENCE_END_CHARS`, `CLAUSE_SPLIT_CHARS`, `LONG_FRAGMENT_THRESHOLD_CHARS`, `find_split_points` promoted to public in `fragments.py` itself. Checked every existing reference first (`grep` across `app/` and `tests/`) — only `fragments.py` itself imported them; one docstring-only mention in `test_fragments.py` needed no change. Clean rename, nothing broken.

**Verified, not merely written:**
- `check_feasibility`/`estimate_duration_s` run against the real `m8_test_project` script: `documentary_archival` passes (13 fragments, no floor to check); `retention_fast` fails both checks with the exact numbers discussed throughout this plan (D/N≈3.54s vs a 1.75s target; longest fragment ≈8.0s vs a 3.5s ceiling — matching the earlier hand-measured 7.9s closely, the small gap being estimate-vs-real-measured-duration, expected).
- `suggest_breaks` verified end-to-end, not just asserted: applied all 7 suggested commas to the real script and re-ran the REAL `split_narration_fragments` — **N genuinely went 13 → 20**, confirming the mechanism works, not merely that its own `reason` string claims it does.
- Every suggestion lands on a word boundary (checked in the test), and the comma-vs-period choice is verified against the real per-sentence length, not asserted.
- `python -c "import app.main"` succeeds with every new module wired in.
- `ruff check .`, `black --check`, `mypy backend/app` (128 files) all clean — repo-wide, not just the changed files.
- New unit tests (`test_preflight.py`, `test_suggestions.py`) run directly as plain Python functions (bypassing `pytest` entirely) — **`pytest` itself was NOT run**, per the standing rule that its `clean_database` autouse fixture truncates the shared Postgres the dev server uses. The tests exist in the repo, correctly located and named, for a normal `pytest` run whenever that's safe to do.

**Two honest limitations, documented in the code, not glossed over:**
- `preflight.py`'s own module docstring: `retention_fast`'s shot-cap override (58) is not yet enforced anywhere real — `generate_timeline.py` and `shot/planner.py` still read the flat `settings.max_shots_per_project` (40), not style-aware. A "feasible for retention_fast" verdict for a 41–58-shot script would still fail real planning until Track B threads style into those two call sites. Flagged in the code so it isn't silently forgotten, and this must close before `retention_fast` reaches a real user.
- `suggestions.py`'s placement heuristic (midpoint + nearest word boundary) produces mechanically correct but occasionally grammatically awkward breaks (e.g., splitting immediately after "because"). Works, verified, not polished — a reasonable v1 given the point was proving the mechanism, not optimizing prose quality.

**Not run, needs the user or a safe session:** `alembic upgrade head` (the new migration is written, not applied) and the actual `pytest` suite. Both are reversible/inspectable before running — flagging rather than doing either without confirmation, matching this session's standing DB-safety rule for the migration too, since it touches the same shared Postgres.

### 2026-08-17 — migration applied, full suite run: 468/468 green

User confirmed both, checked before acting on either:

- **No real project existed in the live DB** (`SELECT id FROM project` → 0 rows) before running anything - the risk the shared-DB warning exists for (losing a real project to a truncate) did not apply this time, verified rather than assumed.
- `alembic upgrade head` applied cleanly (`c7d2a8e91f3b -> d3f8a1b6c9e2`); confirmed directly against Postgres (`\d script`) that `source` exists, `NOT NULL`, `DEFAULT 'user'`.
- Full suite: **468/468 passed, 18m06s** (real ffmpeg integration/e2e tests dominate the runtime). Confirms three things at once: the 10 new tests pass for real under `pytest` (not just as standalone functions, which was the workaround used earlier to avoid touching the DB); the `fragments.py` rename (private → public) broke nothing anywhere in the suite, including `test_fragments.py`'s own 13 tests; and the step-0 `build_punch_in_expression` addition to `ken_burns.py` didn't disturb any of `test_ken_burns.py`'s existing 13 tests.

Track D levels 1–2 are now built, verified standalone, verified under the real test runner, and the schema change is live. Ready for review/next track.

### 2026-08-17 — Track B: a real style, wired end-to-end, closing the flagged gap

Minimal viable slice: one real style (`retention_fast`) selectable at project creation, affecting the Shot Planner's own decisions and the render's camera motion for real - not only checked by Track D's pre-flight. Scoped deliberately narrow (no grade/transitions/caption-treatment yet - that is Tier 1's other half, a separate slice) to keep this reviewable as one coherent change.

**The architecture question was already settled, not reopened.** §2.2 already decided camera is a per-shot creative decision written into the Timeline by the planner, never applied by the renderer from a style override alone. `PUNCH_IN` was built as a real `CameraMovement` enum value the Shot Planner can choose, promoted from step 0's spike rather than kept as a renderer-only bypass.

**New/changed, in dependency order:**
1. `app/schemas/timeline.py`: `CameraMovement.PUNCH_IN`; `TimelineMetadata.render_style: str | None`.
2. `app/renderer/ken_burns.py`: `build_zoompan_expression` dispatches `PUNCH_IN` to the already-verified `build_punch_in_expression` - one line, since the function itself needed no change. Docstrings updated to drop the "experimental spike" framing now that it is real.
3. `app/script/styles.py`: `StylePacingBand.min_shot_duration_s_override`; `resolve_constraint_bundle(style) -> (min_shot_duration_s, max_shot_duration_s, max_shots_per_project)` - the function both real enforcement points now call.
4. `app/models/project.py` + migration `e5a2c8d4f1b7`: `ProjectModel.render_style`, pre-planning staging only, nullable.
5. `app/schemas/project.py`, `app/repositories/project_repository.py`: `Project.render_style` threaded through `create`/`update`/`_to_schema` (`ProjectRepository.create` gained an optional keyword param - checked every call site first, all pass `name` alone, fully backward compatible).
6. `app/api/projects.py`: `CreateProjectRequest.render_style` (validated against `STYLE_PACING_BANDS`); new `POST /{project_id}/style` with the identical freeze-check pattern `upload_script` already has, for changing style after creation but before planning.
7. `app/timeline/service.py::create_initial`: new `render_style` keyword param, copied into `metadata` exactly once - checked every call site first (24 across the test suite), all keyword-only on `script=`, fully backward compatible.
8. `app/workflow/steps/generate_timeline.py`: `_is_fully_planned` and the real `ShotPlanner.plan()` call site both now call `resolve_constraint_bundle(timeline.metadata.render_style)` instead of reading `settings.*` directly - **this is the actual gap closure**.
9. `app/prompts/loader.py::load_style_fragment`: `None` (not `FileNotFoundError`) when a style has no planner-specific wording - most style×planner pairs, by design (plan §2.8).
10. `app/prompts/shot_planner_styles/retention_fast.md`: finest fragment granularity, prefer `punch_in`, cuts only - overriding the base prompt's dissolve-for-continuity guidance specifically for this style.
11. `app/planners/shot/planner.py::plan()`: new `render_style` keyword param, composes `base_prompt + fragment` only when a fragment exists.

**Verified, not merely written:**
- `resolve_constraint_bundle(None)` / `("documentary_archival")` / `("stillness")` all resolve **byte-identical** to the flat `settings.*` values every existing project already used - checked directly, not assumed, since this is what makes the change backward-compatible rather than a silent behaviour shift for every project that never picks a style.
- `resolve_constraint_bundle("retention_fast")` → `(0.8, 3.5, 58)`, matching §2.5/§4.2 exactly.
- `load_style_fragment` returns `None` for `documentary_archival`/`stillness`/`None`, and the real 1560-character fragment for `retention_fast` - confirmed the base Shot Planner prompt is untouched (byte-for-byte) for every style that isn't `retention_fast`.
- `build_zoompan_expression(camera_with_punch_in, ...)` produces the exact same expression as calling `build_punch_in_expression` directly, across three `camera.direction` values (confirming direction is correctly ignored, matching `SLOW_PUSH`/`PULL_BACK`'s own pattern) - both the dispatch itself and all 14 `test_ken_burns.py` tests (13 existing + 1 new) pass directly.
- Every existing call site for `ProjectRepository.create` (20 across the test suite) and `TimelineService.create_initial` (24 across the test suite) checked by direct grep before either signature changed - all compatible with the new optional keyword params.
- `ruff`, `black`, `mypy` (128 files) all clean across every file touched.
- New migration `e5a2c8d4f1b7` applied cleanly (`d3f8a1b6c9e2 -> e5a2c8d4f1b7`) against the same live Postgres Track D's migration already touched; still 0 real projects in it, checked again before applying.
- New tests (`test_styles.py`, 6 cases; `test_ken_burns.py`'s new dispatch test) run directly as plain functions, all passing.

**Known, documented, deliberately deferred (not silently missing):**
- Only `retention_fast` gets a real Shot Planner fragment. `documentary_archival` needed none (it already IS the unstyled default); `stillness` has no fragment yet and would need one to actually change planner behaviour, not just its (currently identical) constraint bundle.
- Grade, transitions, caption treatment per style (Tier 1's other half, §2.4) - not touched this pass. A `retention_fast` render today gets real punch-in camera and real cuts-only transitions (via the prompt fragment) but the SAME colour grade/caption look as every other style.
- Scene Planner is untouched (§4.1: "barely changes... leave alone in v1" - followed as specified).
- The full pytest suite run to confirm none of this broke the 14 existing planner/timeline-service/generate-timeline integration tests is IN PROGRESS as this entry is written - result to follow in the next log entry, not assumed here.

**Full suite: 467/468 passed, one flaky failure investigated and confirmed unrelated.** `test_fixture_round_trip.py::test_restored_project_is_renderable_without_rebuying_anything` failed on a subprocess `TimeoutExpired` (120s) spawning `scripts/seed_test_project.py` - not an assertion or logic failure, and nothing in this pass touches that script or its call path. Re-ran the file in isolation: both its tests passed, 150.14s total - close enough to the 120s single-call timeout that running it immediately after a 20-minute full suite (this session's second that day) plausibly pushed one subprocess call over the edge. Confirmed environmental, not a regression, by evidence (isolated re-run passing) rather than by assumption. Every test touching what Track B actually changed - `test_shot_planner.py` (10), `test_timeline_service.py` (17), `test_generate_timeline_real.py` (2), `test_render_ken_burns.py` (4), `test_ken_burns.py` (14, including the new dispatch test) - passed in the same full run.

Track B's minimal slice (`retention_fast`, real end-to-end) is built, verified standalone, verified under the real test runner, migrated, and live.

### 2026-08-17 — Track B Tier 1: per-style colour grade

The plan's own highest-value pick (§2.4: "costs no extra encode... highest visual-impact-per-day item in the document"). Scoped to grade alone - contrast/saturation/brightness via ffmpeg's `eq` filter - leaving gamma/tint/grain/vignette (the rest of §2.4's single Tier-1 item) as a documented follow-up on the same fragment-composition point, to keep this reviewable as one coherent change.

**New:** `app/renderer/grading.py` - `STYLE_GRADES` registry (one `StyleGrade` per style, keyed identically to `STYLE_PACING_BANDS`) and `grade_filter_fragment(render_style, input_label, output_label) -> str | None`.

**Changed:** `app/workflow/steps/render.py` - the grade fragment joins the SAME video-filter pass captions/watermark already share, FIRST in the chain (text and the logo sit crisp on top of the graded image, not graded themselves).

**The fingerprint question, resolved by checking rather than assuming.** R2's own lesson (a render input read live but never hashed silently serves stale output) is the exact failure mode a new render input risks. Verified directly before writing any grading code: `metadata` (which holds `render_style`) is **not** in `_TIMELINE_BOOKKEEPING_FIELDS`, so `compute_render_fingerprint`'s existing whole-timeline-document dump already changes whenever `render_style` differs - confirmed empirically (three Timelines differing only in `render_style` produced three different fingerprints, same style twice matched). Because `STYLE_GRADES` is a fixed code-level lookup rather than a `Settings` value, no new fingerprint parameter was needed - documented explicitly in `grading.py`'s own docstring, including the exact condition under which that would stop being true (grade parameters becoming independently tunable via `Settings`, the way `music_bed_gain_db` is).

**Verified, not merely written:**
- Applied each style's exact `eq` parameters directly to a real archival photo (the same Sasol/Secunda image used throughout this session) and visually inspected all three: `retention_fast` reads visibly punchier (deeper darks, more saturated flame colour) than the unmodified original; `stillness` reads visibly flatter and more muted. Directionally correct, not merely "different."
- `grade_filter_fragment` returns `None` (not an identity filter) for `render_style=None` and for an unrecognised style name - confirmed by direct call, matching `resolve_constraint_bundle`'s own "fall back rather than raise" reasoning for the same reason (this runs past every API-boundary validation point).
- `ruff`, `black`, `mypy` (129 files - one more than Track B's own count, this module) clean.
- New `test_grading.py` (7 cases, including a direct check that `metadata` is absent from `_TIMELINE_BOOKKEEPING_FIELDS` - so a future change to that exclusion set would fail this test rather than silently reopening the exact gap this module was designed around).

**Full suite: 475/475 passed, 16m01s** - but a real timing bug in how this was verified, worth recording precisely because it repeats a shape of mistake already made once this session. `test_grading.py` was written and verified standalone WHILE this full-run was already executing in the background (launched, then used the wait to write the test file) - pytest collects its test set once, at startup, from whatever is on disk at THAT moment. The arithmetic proves it: 468 (prior run) + 6 (`test_styles.py`) + 1 (`test_ken_burns.py`'s new dispatch test, itself added mid-run during the PREVIOUS suite launch for the identical reason) = 475 exactly, with nothing left over for `test_grading.py`'s 7 cases - confirmed directly, `grep -c "test_grading"` on the raw output returns 0. **The production code (`grading.py`, `render.py`) genuinely was validated** (both existed on disk before launch), but the claim "verified under the real test runner" for `test_grading.py` itself would have been false had it shipped in this entry unchecked. Caught before reporting to the user, not after - re-ran `test_grading.py` + `test_styles.py` + `test_ken_burns.py` together for real (DB confirmed still at 0 real projects first): **27/27 passed, 7.13s**, this time genuinely collected and executed.

**Lesson for any future session:** writing a new test file while a background suite is already running gives a false sense of coverage - the file exists and even passes standalone, but the pytest run in flight will never see it. Write new test files BEFORE launching the verification run they belong to, or explicitly re-run afterward and check the count arithmetic, not just the exit code.

(One real project row was found in the live DB before the 475-test run: `b0969377-...`, named "Hinglish v3 - fragments + whitespace merge" - traced to the fixture name in `hinglish_final_project.json`, confirming it was a leftover from this session's own earlier isolated re-run of `test_fixture_round_trip.py` rather than user data; `clean_database`'s own truncation cleared it regardless.)

### 2026-08-17 — Track B Tier 2: extra transitions (`wipeleft`, `fadeblack`)

The cheapest, best-specified item in Tier 2 (plan §2.6: "an enum entry plus validation... restraint is the feature"). Applied the lesson from the grading entry above immediately: wrote the test BEFORE launching any background suite this time, not during a wait.

**Verified before writing any code, not trusted from memory:** ran `ffmpeg -h filter=xfade` directly against this build to confirm `wipeleft`/`fadeblack` are real, exact transition names (0-57 enumerated, both present) - the same discipline as every other ffmpeg-adjacent claim this session, after the Pixabay-shaped lesson of trusting an unverified API claim. Then rendered both as real `xfade` transitions on two real archival photos and visually inspected mid-transition frames: a genuine directional wipe, a genuine dip through black - not merely "ffmpeg exits 0."

**New:** `TransitionType.WIPE_LEFT = "wipeleft"`, `TransitionType.DIP_TO_BLACK = "fadeblack"` (`app/schemas/timeline.py`). No renderer code changed - `slideshow.py`'s xfade call site already passes `transition_out.type.value` straight through, exactly like `DISSOLVE`/`FADE`. Checked first that nothing else exhaustively enumerates `TransitionType` members (`_is_hard_cut` checks only `== CUT`; grepped every test file referencing the enum) - safe to add with zero other code changes.

**Prompt updated with restraint framing, not just the new options listed:** `app/prompts/shot_planner/v1.md` tells the Shot Planner to reserve both for "a genuinely deliberate structural beat... never as everyday variety," matching the plan's own concern that overuse stops reading as documentary. Caught and fixed one real mistake while writing this: the first draft used friendlier prompt aliases (`wipe_left`, `dip_to_black`) that don't match the schema's actual enum values (`wipeleft`, `fadeblack`) - since the Shot Planner's structured output is validated character-for-character against the enum, that draft would have made the model unable to ever actually select either transition. Fixed before it shipped.

**Verified against the full pipeline, not just raw ffmpeg:** built a real 3-shot Timeline (`WIPE_LEFT` then `DIP_TO_BLACK` then a hard `CUT`, real archival photos) and ran it through the actual, unmodified `render_timeline()`. `group_into_runs` correctly placed all three shots in one continuous run (both new transitions are non-cut); `compute_timeline_duration` predicted 5.0s (6.0s raw minus 0.5s + 0.5s overlap, D5's arithmetic); the real rendered file's ffprobed duration was `5.000000` - exact match.

**New test** (`test_duration.py`, +1 case) written and run for real BEFORE any background suite this time - 7/7 passed, 2.01s, confirmed via the DB-safety check (0 real projects) beforehand.

### 2026-08-18 — Track B Tier 2: text cards (design decisions locked in, then built)

Bigger design surface than transitions - genuine new schema, not just an enum entry - so three scoping questions were put to the user before any code: (1) `Shot.text_card: str | None` (a field on the existing shot, not a standalone card-only shot type), (2) timed fade in/out within the shot's own duration (not instant reveal-and-hold), (3) minimal scope - static text, simple fade, explicitly not attempting kinetic typography.

**New module**, deliberately separate from `captions.py` rather than folded in: `app/renderer/text_cards.py`. The two overlays answer different questions (which shot is on screen vs. what is being said right now), need different escaping (a card preserves the author's own line breaks via ASS `\N`; a caption collapses them, since a caption is a fragment of continuous speech - a real, deliberate divergence from `_escape_ass_text`, not an oversight), and a different ASS style (centered, `Alignment=5`, larger, fading vs. captions' bottom-center `Alignment=2`, plain). `format_ass_time` alone was promoted to public and shared (pure time formatting, no caption-specific logic to duplicate - the S2 precedent again).

**Timing clock, a real design choice, not a default:** cues come from `compute_shot_start_times` (the RENDERED-timeline clock, D5-overlap-aware), never narration alignment - a title card is tied to which shot is on screen, not to spoken words. This also means text cards work on a silent render (DRY_RUN, or no narration yet), which captions structurally cannot claim.

**A real path-escaping bug caught in my own manual verification, not in the shipped code.** My first standalone ffmpeg smoke test built a raw Windows path directly into the filter string and hit exactly the drive-letter colon trap `escape_ffmpeg_filter_path` exists to prevent - a bug in the *test*, not in `text_cards.py` (which correctly calls that helper). Redid the verification through the actual function and it worked; recorded here so the near-miss isn't invisible.

**Verified visually, the same rigor as every other render-affecting change this session:** generated a real two-line ASS cue, burned it onto the same real archival photo used throughout, extracted frames at fade-in (t=0.2s), hold (t=2.0s), and fade-out. Confirmed: correctly centered two-line text with `\N` preserved, heavy outline, no background box at the hold frame; visibly, genuinely more translucent at the fade-in frame than the hold frame - not merely "ffmpeg exited 0."

**Fingerprint reasoning made explicit, and it's asymmetric with captions on purpose.** `burn_text_cards` (a config toggle) and `text_card_font_hash` (the vendored font file) both had to be added to `compute_render_fingerprint` - the R2 shape, a toggle that can change output bytes with nowhere to be caught. But **no separate cue-list hash** was added, unlike captions' own `cue_list_hash`: a text card's cue text, start, and end are ALL already fully determined by data already inside the fingerprinted Timeline (`shot.text_card`, `duration_s`, `transition_out`) - hashing a second, derived copy would be redundant, not merely harmless. Documented directly in `fingerprint.py` so a future reader sees a reasoned choice, not an inconsistency to "fix."

**Config:** `settings.burn_text_cards: bool = True` (a global kill switch, mirroring `watermark_enabled`'s shape, for the rare case a bug surfaces after real shots already carry cards) plus `RenderSettings.burn_text_cards` with the same draft carve-out captions/watermark already have (drafts are for spotting wrong-asset bugs fast, not reviewing a title card's look).

**Chain ordering:** grade → text cards → captions → watermark. Text cards sit before captions specifically for the rare-overlap case (a title card is centered, a caption is bottom-band - they occupy different screen regions in the normal case), not the common one: if they ever do collide on one frame, spoken captions stay legible on top.

**Applying the lesson from the grading entry, deliberately:** every test file (`test_text_cards.py`, 9 cases; two additions to `test_fingerprint.py`) was written and run for real under pytest - twice, actually: first a scoped run (99/99, this module's own tests plus every render/timeline/script test that could plausibly regress), confirming everything passed BEFORE the full suite was even launched. A full-suite run then followed to catch integration-level composition (the actual `render_video()` call site threading grade+cards+captions+watermark into one real filter graph, which only `test_render_determinism.py`/`test_render_captions_determinism.py`/`test_render_watermark_determinism.py` can exercise) - result to follow, not assumed here.

One small, incidental bug caught along the way while verifying scoped tests: `tail -100` on a combined multi-file run appeared to be missing one test (`test_no_cues_when_no_shot_has_a_text_card`) from the visible output. Re-ran that file alone before assuming anything was wrong - 9/9 passed; the "missing" test was a terminal-truncation artifact of `tail`, not a real gap. Checked rather than either alarmed or assumed.

**Full suite: 494/494 passed, 16m48s.** Count verified by arithmetic before trusting the green result, applying the exact lesson from the grading entry above: 475 (previous full run) + 7 (`test_grading.py`, missing from that previous run for the same reason described there, now genuinely collected) + 1 (`test_duration.py`'s transition test) + 9 (`test_text_cards.py`) + 2 (`test_fingerprint.py`'s two text-card additions) = 494 exactly, no gap. This run is the real proof the three Tier-2 changes compose correctly, not just that each works alone: `test_render_determinism.py`, `test_render_captions_determinism.py`, `test_render_watermark_determinism.py`, and `test_render_ken_burns.py` all exercise the actual `render_video()` call site with grade + text cards + captions + watermark all present in one real filter graph, and all passed.

Transitions and text cards (Tier 2, partial - split-screen not yet built) are done: built, visually verified against real archival photos, fully tested under real pytest, and confirmed not to regress anything across two full-suite runs.

### 2026-08-17 — Plan review: one error corrected, and the plan's real weak point named

Asked to assess the plan as a whole. Findings, including against this document itself:

**Corrected an error in §3.4 — twice, and the second correction is the load-bearing one.** The section claimed exceeding `max_shots_per_project` makes the repair loop merge fragments, silently yielding a slower video than the style promised. A first pass at fixing it (reading `repair.py` alone) concluded the model is re-prompted and may comply by merging. **Both were wrong.** Reading the actual call site settles it: `max_shots_per_project` is **not in the repair-loop validator** (`shot/planner.py::_make_validator`, line 126, takes only the duration bounds); the cap is checked after the loop returns (line 288) and raises `PermanentError` outright, and `generate_timeline.py:108` fails the step the same way. **No silent-degradation path exists for the shot cap** — the model is never asked to reduce shot count, so it cannot quietly comply. §3.4 rewritten to state the real behaviour: a loud mid-loop failure after part of a planning pass has been paid for. The pre-flight check drops from *urgent safety feature* to *good ergonomics* — still worth shipping (nearly free once `N` is computed), but it no longer justifies special ordering.

**Method note worth carrying:** the first correction failed because it read the shared helper (`repair.py`) without reading the call site that supplies its validator. Verifying "what does this loop do" required both. Same class of mistake the guide's own S1/S2 sections warn about — reasoning about a mechanism instead of tracing the actual data flow.

**Q3 produced less than its effort suggests.** The argv-length crash is Windows-only and production is Linux (`python:3.12-slim`); the production threshold remains unmeasured. Recorded honestly at the time, restated here so the finding is not over-weighted when C3 is picked up.

**Effort estimates in §9 are low against this codebase's own documentation standard.** Every module here carries multi-paragraph rationale docstrings (`still.py` spends three paragraphs on why GIFs break `-loop`). Building to that standard is materially slower than the estimates assume — expect roughly 1.5× the §9 figures, i.e. ~50 days rather than ~35 for the full plan.

**⚠ The plan's real weak point is not technical — it is that nothing has been looked at.** Three presets, a grade, punch-ins, and pacing bands are all designed from reasoning; **not one render exists in any of these styles.** That inverts how the rest of this project has worked — A30a's recalibration, the Pixabay correction, and the Ken Burns jitter fix were all found by examining real output, not by reasoning about it.

**Recommendation, added to §11's ordering as step 0:** before building any of Track B or D, change `build_zoompan_expression` to emit a step (punch-in) expression instead of a ramp — one function, no schema, no migration, no endpoint — and render `m8_test_project` both ways. Roughly half a day. It answers the one question this plan cannot answer by design: *does fast-cut on archival stills actually look good?* A negative answer invalidates most of Track B Tier 1 and much of Track D's premise, and it is far cheaper to learn now than at step 7.

### 2026-08-17 — Step 0 built: punch-in mechanism verified correct; one real side-finding, one open question left to human judgement

**Method.** Added `build_punch_in_expression()` to `app/renderer/ken_burns.py` — deliberately a new, separate function (not a new `CameraMovement` enum value, not a branch on the existing one), producing a piecewise-CONSTANT `zoom(on)` expression (hold, snap, hold, snap, hold) instead of `build_zoompan_expression`'s continuous ramp. `camera.movement`/`direction` are not consulted, matching plan §2.2's "global look settings are a style/render decision" — a punch-in style punches every shot the same way regardless of that shot's own planned movement.

Rendered `m8_test_project`'s real 13 shots through the real, unmodified `render_timeline()` twice — real archival Wikimedia photos already on disk at `storage/58f0a5e6-.../assets/`, real per-shot durations from the fixture, no mocks in the render path itself:
- **Baseline**: exactly today's production camera/transitions from the fixture (unchanged).
- **Punch-in**: every shot's camera forced to the new expression (2 punches), transitions forced to `CUT`/0s (matching §2.4/§2.5's "fast-cut is cuts-only" design) — shot durations and order otherwise untouched, isolating the camera-style variable alone.

**A bug was caught before it reached ffmpeg.** The first draft of the nested-if construction reused the first punch threshold twice, making the first punch level mathematically unreachable. Caught by symbolically evaluating the generated expression frame-by-frame in Python (no ffmpeg, no render) before ever running it — the same "verify the arithmetic before trusting the string" discipline this codebase already applies elsewhere (D5, the fingerprint). Fixed and re-verified: holds at 1.0 for frames 0–29, snaps to 1.225 at frame 30, holds, snaps to 1.45 at frame 59, holds to the shot's end, exactly as designed.

**Both renders succeeded** (baseline 41.5s, punch-in 46.0s — the difference is `CUT`'s zero overlap vs the baseline's dissolve/fade overlap subtracting time per D5's own arithmetic, not a bug). Extracted and visually inspected the exact frame pair spanning a real punch on a real archival photo (a WWII aerial reconnaissance image, `sc_01_sh_01`): frame 33 shows the full wide crop; frame 34 — one frame, 1/30th of a second later — shows a visibly tighter crop. **The mechanism is confirmed correct at the pixel level, not merely asserted from the expression string.**

**⚠ One thing this method cannot verify, stated plainly rather than glossed over: whether the snap READS AS a deliberate punch versus a jarring glitch is a motion-perception judgement, not a framing one, and cannot be assessed from extracted still frames.** The mechanism producing the correct crop at the correct frame is confirmed; whether it *looks good in motion* on real archival material requires a human watching the rendered video play, not reading about it. Both files are left in the scratchpad for that purpose — this is the one open item step 0 cannot close by itself.

**Unplanned finding, real and worth carrying forward: any camera movement crops more of the frame than a static shot does, independent of punch-in specifically.** Comparing the STATIC baseline frame against the punch-in's own pre-punch (`zoom=1.0`) hold frame on the SAME source photo revealed they are not the same crop — `_normalize_filter` (the `STATIC` path) pads-to-fit letterboxed, showing the whole image; `_ken_burns_filter` pre-scales to `WORKING_CANVAS_SCALE = 1.6` and crops to fill, discarding the outer margin **even while sitting at zoom=1.0, before any motion has happened.** On this real WWII reconnaissance photo, that crop cuts off the printed legend box (title, compass rose, lettered target key) that the static baseline shows in full. ⚠ **This affects every existing Ken Burns movement already in production, not only the new punch-in spike** — any archival photo with printed captions or legends near its edges loses that content the moment it's assigned anything but `STATIC`. Not a regression (this is how `build_zoompan_expression` has always behaved), but a real, previously undocumented cost of applying camera movement broadly to archival material, worth weighing in Track B's Tier 1 Ken Burns work and in whatever eventually decides which shots get motion at all.

**Status: mechanism verified, aesthetic verdict pending human review of the actual rendered video.** Not yet marked done in §11 — the outstanding step is watching, not building.

**Verdict, 2026-08-17: holds good.** User watched both files (copied to Desktop for access — the scratchpad path under `AppData\Local\Temp` is hidden by Explorer by default, worth remembering for any future review artifact). Punch-in reads as a deliberate stylistic choice on real archival stills, not a glitch. **Step 0 closes green** — proceeding into Track B/D as planned, with `build_punch_in_expression` as a proven building block rather than an open question.

**Scope note on what was actually validated:** this implementation is zoom-only, centered (`x`/`y` unchanged from the existing zoom movements) — it snaps zoom level, it does not re-frame to a different part of the image. Real punch-in editing sometimes also re-centers; that variant is untested and would need its own check before being assumed to work as well.
