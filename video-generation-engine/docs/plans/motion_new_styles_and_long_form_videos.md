# Motion, New Styles, Script Pre-flight, and Long-Form Video — Implementation Plan

> **Status:** Originally plan-only (2026-08-17). Since then, built and verified against real ffmpeg/real Postgres/real live APIs: Track D (script pre-flight, all levels except the phrasing-rewrite L3), Track B Tier 1–2 (grade, extra transitions, text cards, punch-in), and Track A's A1/A2/A3/A4/A5/A6/A7 (motion clip input, duration fitting, the video path's one-gate model, the on-demand video endpoint pair, the Pexels video rung, and video-vs-image planner calibration). **A8 (the bake-off) was attempted 2026-08-18 with real spend (~$1.86) and found a real, previously-unknown collage bug affecting every project with a rich `visual_style` — fixed and verified, but A8's own question ("does synthetic motion blend next to real archival photography") is still open**, by the user's own choice to stop before re-running the video half. **§11 step 5 (orphan-run fix) and step 6 (music taxonomy + a real 54-track curated library, §5.1) are also now built and verified**, 2026-08-18 — see §12 for both. See §12 for the full chronological log; unmarked sections below are still design-only. ✅ **2026-08-20: Track C is COMPLETE** and moved to [`track_c_long_form_video.md`](track_c_long_form_video.md). ⚠ **Six items remain in this document — see §14, audited against real code:** narration speed (R8, blocked on a 10-min live ElevenLabs check needing a tiny spend, and by §13.13's own rule `retention_fast` is not honest to offer until it closes), SFX (entirely unbuilt), split-screen, 2.5D parallax, per-style music gains, and BPM/tempo-fit ranking (9 of 54 tracks carry a BPM).
> **Scope:** four tracks — **A** (motion clip input), **B** (style catalogue), **C** (long-form), **D** (script pre-flight). A is the keystone for the motion half of B; D is independent and could ship first.
> **Related:** [`13_Implementation_Guide.md`](../13_Implementation_Guide.md) §M7/M8/M9 and its Backlog, [`14_Captions_Plan.md`](../14_Captions_Plan.md), [`watermark_implementation_plan.md`](watermark_implementation_plan.md).
> **Fixture:** project `58f0a5e6-008d-468e-862a-e365e463878e` / `backend/tests/fixtures/m8_test_project.json` — real Fischer-Tropsch timeline, 13 shots. Reuse it; do not plan a fresh one.
> ⚠ **Read §13 before trusting any "BUILT" marker in this document.** A code-vs-plan review on 2026-08-18 found ten open discrepancies between what §12 records as built and what the code does, two of them blocking — including that `retention_fast` could not complete a planning run. **Update, same day: 8 of 10 items (R1/R2's blocking half, R3, R4, R6, R7, R9, R10) are now fixed and verified, plus R5 (a user-confirmed architecture decision). Only R2's second half (a lowest-priority product decision) and R8 (needs a real, tiny ElevenLabs spend, not yet confirmed) remain open.** See §13's own status line for the current per-item state.

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

### A1. Renderer accepts motion (2–3 d) — the keystone — **BUILT 2026-08-18, see §12**

A shot is currently a still. It must become **a still or a clip**, decided per shot.

**Path:** add a third input branch in `_render_run` (today there are exactly two: `-loop 1 -t` for a static still, one decoded frame for `zoompan`) — normalise fps/SAR/resolution, scale-and-crop to canvas, fit to shot duration; gate `ensure_still_image` on the classification so it only touches genuine stills.

⚠ **Correction to this section's own original wording (2026-08-18, design pass).** It previously said "classify by probing with ffprobe, **not** by asking Pillow whether it can open the file." Taken literally that causes a regression: an animated GIF has multiple frames, so a purely frame-count/ffprobe-based rule classifies it as MOTION and it would start *playing* — but Commons serves plenty of GIF maps and process diagrams that `ensure_still_image` deliberately flattens, and this plan elsewhere says to leave that behaviour alone. The two statements contradict each other.

**The rule that satisfies both:** Pillow **opens** it → STILL (Pillow correctly identifies GIF/PNG/JPEG/BMP/TIFF as images; `ensure_still_image` keeps flattening animated ones exactly as today). Pillow **fails** → ffprobe must then *positively confirm* a real video stream with a duration → MOTION. The motion decision is still positively confirmed by ffprobe and never inferred from a failure — which is what the original wording was actually protecting — while every existing still/GIF behaviour is preserved bit-for-bit.

**Threading:** `render_timeline` probes once and passes the result down to `_render_run`. The external `shot_images: dict[str, Path]` contract stays **unchanged**, so no existing render test needs touching.

**Pitfalls:**

- ⚠ **Ken Burns must not run on a clip.** Moving the camera over already-moving footage looks like a bug and will be read as one. Decide this in one place.
- ⚠ **Generated clips may carry audio.** Narration is the only voice (D1). **Fix at the source**, not just at input: pass `generate_audio: false` in the fal request (confirmed live field, A3) rather than relying only on ffmpeg to discard an audio track that shouldn't have been generated — and paid for — in the first place.
- ⚠ **The single-decoded-frame trick does not apply.** `ken_burns.py`'s whole docstring is about feeding `zoompan` exactly one frame; a motion clip is the opposite case. Do not merge the two paths "for symmetry" — the jitter bug returns.
- ⚠ **`xfade` offsets assume durations D5 already governs.** Any fitting rule from A2 must feed the same duration function the crossfade offsets come from, or audio drifts against picture progressively — presenting as a mystery, not as a transition bug.

### A2. Duration reconciliation (0.5 d) — **BUILT 2026-08-18, see §12**

Narration is the master clock. Kling returns a fixed length. The shot needs 3.2s. One rule, one function, beside the existing D5 arithmetic. Clip longer → trim. Clip shorter → **recommendation: hold the last frame.** Looping reads as a glitch; slowing changes the motion's character and fights fps normalisation.

**Mechanism (2026-08-18 design pass):** `trim` for the too-long case, `tpad=stop_mode=clone:stop_duration=<gap>` for the too-short case. The clip's real duration comes free from A1's own probe, so no extra ffprobe call is needed to compute the gap. Either way the branch emits exactly `duration_s`, so D5's existing `xfade` offset arithmetic keeps working untouched — which is the property that matters most here (§1's own pitfall: getting this wrong desynchronises audio from picture progressively and presents as a mystery, not as a transition bug).

**Caution:** this is a creative decision wearing an arithmetic costume. Document the choice in the function, as D5 is documented, or it will be "fixed" later.

**DECIDED 2026-08-18 (Q4 closed): hold the last frame.** Put to the user with the real numbers rather than as an abstract preference, which is what made it decidable: because `fal_video.py` asks Kling for `round(shot.duration_s)`, **the HOLD direction is bounded at +0.5s** — measured across every shot in the real `m8_test_project`, the worst case is exactly `+0.50s`. More importantly, comparing each gap against that shot's own `transition_out`: **6 of the 8 shots needing a hold have the entire held tail fall inside their own outgoing dissolve** — the viewer sees a crossfade, never a frozen frame. The 2 exceptions are `+0.45s` (`sc_02_sh_01`, against a 0.35s dissolve) and `+0.10s` (`sc_03_sh_03`, against a 0.0s fade) — 3 frames at 30fps in the smaller case, still small in the larger one. Against that, a loop would snap a 3.0s clip back to frame 0 for 0.4s exactly as the shot dissolves out, and slow-motion would mean a 13% retime needing frame duplication.

⚠ **Corrected 2026-08-18 (§13.3, "R3") — the bound above is NOT symmetric, and this paragraph is the primary claim §13.3 was quoting.** The TRIM direction is unbounded below the 3s Kling API floor: any shot under 2.5s asks Kling for a flat 3s regardless of how short the shot actually is, so `retention_fast`'s 0.8s shot floor can see a gap of up to **-2.2s**, not ±0.5s. The HOLD-direction numbers and the dissolve-overlap argument above are correct and unaffected — only the "±0.5s" framing was wrong, and only for the direction this section doesn't actually need to bound (the `trim` branch already handles an arbitrarily large negative gap correctly, emitting exactly `target_duration_s` either way). See §4.2 for the resulting cost note: every `retention_fast` motion shot clamps up to a paid 3s Kling request.

⚠ **One assumption underneath this remains unverified:** that Kling returns *approximately* the duration requested. The implementation measures the clip's real duration via A1's probe, so it handles whatever actually arrives — but "asked for 3s, got ~3.0s" has never been checked against the live API.

### A3. Verify the Kling duration contract — **DONE, 2026-08-17: the code is already correct**

`fal_video.py:38` clamps to 3–15s and sends `duration` as a stringified int. This plan originally worried Kling's standard tier might accept only a small enum (e.g. `"5"`/`"10"`), which would have broken the cost model in A4.

**Checked against fal's own live API docs** (`fal.ai/models/fal-ai/kling-video/o3/standard/image-to-video/api`): `duration` is a `DurationEnum` accepting **every integer second from 3 to 15**, default `"5"`. `fal_video.py`'s existing `max(3, min(15, round(duration)))` → `str(duration)` already matches this exactly. **No code change needed here.**

**New finding from the same schema check, not previously known — FIXED 2026-08-18, see §12:** the model also exposes a `generate_audio` boolean, which `fal_video.py` never set — so it rode the model's undocumented default rather than an explicit choice. `submit()` now sends `"generate_audio": False` explicitly.

### A3a. Image-to-video vs text-to-video — surfaced and decided 2026-08-18

**The image-to-video choice was never a comparison.** M7's own notes record it as a *discovery*, not a decision: the model id was a "direct pick," and its image-to-video nature was "a fact only discovered by checking the live schema, and it reshapes the whole generation path." Combined with A8's bake-off being deliberately skipped, **nobody has ever compared the two variants on real output.** Raised when the user questioned whether Kling was text-to-video at all — a fair challenge, since nothing in the plan had ever justified the choice.

**A text-to-video variant exists at the identical tier:** `fal-ai/kling-video/o3/standard/text-to-video`, same family/version/tier, published at $0.084/sec audio-off (≈42¢ for 5s, close to the 50¢ already in `fal_video_cost_cents_estimate`).

| | image-to-video (current) | text-to-video |
|---|---|---|
| API calls per shot | 2 (Seedream keyframe → Kling) | 1 |
| Cost | ~4¢ keyframe + ~42¢ | ~42¢ |
| POST shape | must block for keyframe | pure submit, instant `202` |
| Style anchor | keyframe uses the same `visual_style` + per-project seed as every still in the project | prompt only, no anchor |
| Gate preview | keyframe viewable immediately | nothing until the video completes |

**DECIDED: keep image-to-video.** The deciding argument is the Creative Philosophy's own: generated media must sit convincingly beside 1936 archival photography, and the keyframe path anchors every clip to the same styled, same-seeded look as the project's stills. Text-to-video has no such anchor.

⚠ **"It's just a config line" is not quite true** — `FalVideoProvider.submit()` unconditionally sends `image_url`, which text-to-video would reject. Switching later means the config value *plus* shaping the request per mode and skipping the keyframe in `_generate_video_real`. Small, but not zero — worth knowing before A8's bake-off treats the two as freely swappable.

### A4. Motion-vs-still becomes a real decision (1 d) — **BUILT 2026-08-18, see §12**

`asset_plan.preferred_type == VIDEO` is planner output today; nothing calibrates when it should be chosen and nothing prices it. At ~50¢ per motion shot vs ~1–3¢ per image, an uncalibrated planner is a budget event. Prompt guidance for when motion earns its cost, plus a per-project cap.

⚠ **Found while answering an unrelated question, not while working this item directly: the Asset Planner's OWN prompt rule for `preferred_type` was unreachable.** `app/prompts/asset_planner/v1.md` says to judge by "the shot's camera movement and intent" — but `_build_user_content` (`app/planners/asset/planner.py`) never sent `camera` at all, only `intent`/`framing`/`prompt`, even though the Shot Planner (which sets `camera`) always runs first. The model was told to use a signal it could not see. **FIXED**: `camera={movement}` now included per shot line. This also answers a question worth recording precisely: **style has no path to influencing image-vs-video today, not even indirectly** — the Asset Planner never receives `render_style` or a style prompt fragment (unlike the Shot Planner), and the one channel that COULD have carried an indirect style effect (style-influenced camera movement reaching this decision) was the exact thing that was broken.

### A5. Bring the video path onto the one-gate model (0.5 d) — **BUILT 2026-08-18, see §12**

Already in the Backlog, already deferred once. `_generate_video_real`/`_generate_checked_keyframe` still run the old constraint-check and bounded-retry loop the image path shed on 2026-08-16 — so a video shot can still be killed outright by a constraint violation, the exact failure that destroyed the German-tank shots. ⚠ **Apply the identical treatment, rather than inventing a third behaviour.**

### A6. Gate UX for motion, and the on-demand video endpoint (1–2 d) — **BUILT 2026-08-18, see §12**

The review screen must play a clip. Regeneration takes minutes, so `POST /shots/{id}/generate` cannot stay a blocking round-trip for video. The Backlog's missing batch endpoint stops being an ergonomic nit here.

**Scope reduced by a finding, 2026-08-18: the submit/poll machinery already exists — this is wiring, not invention.** `ResolveAssetsStep._generate_video_real` (`resolve_assets.py:1201`) already implements the whole shape: fresh path generates a keyframe → submits to Kling → `insert_pending()` persists `job_id` **immediately, before anything else**; resume path calls `get_in_flight_for_shot()` → `poll(job_id)` **once** → `in_progress` (return, binding stays pending) / `failed` (`mark_failed`) / `completed` (download, `mark_completed`, bind). `GeneratedClipModel` already carries `job_id`/`status`/`error`, and the repository already has `insert_pending`/`mark_in_progress`/`mark_completed`/`mark_failed`. **That resume path is, structurally, the body of a poll endpoint.**

**Endpoint pair (user-requested, 2026-08-18 — explicitly polling, not synchronous):**

- `POST /{project_id}/shots/{shot_id}/generate/video` → keyframe, submit, persist `job_id`, return `202 {clip_id, job_id, status: "pending"}`
- `GET  /{project_id}/shots/{shot_id}/generate/video` → polls once; returns `pending` / `failed` / `completed` (downloading, recording and binding on completion)

⚠ **Deliberately NOT routed through the workflow engine**, unlike every other `202` trigger in `api/projects.py`. The reason is already written down in `generate_shot_image`'s own docstring and applies identically here: a human at the gate may click across several shots before approving anything, and resuming the engine on each click would race the pipeline forward mid-review. The image endpoint made exactly this call; the video pair follows it.

⚠ **A1 is a hard prerequisite, not a nicety.** Shipping this endpoint before A1 lets a user spend ~50¢ on a Kling clip and receive a **frozen frame** in the render — the failure this whole track exists to fix. Build A1 first, or ship both together; never this alone.

**DECIDED 2026-08-18: the `POST` blocks while the keyframe generates, then returns `202`.** Kling stays image-to-video (see A3), so a still must exist before the video job can be submitted. Two things settled this rather than preference:

- **The "~60s block" framing was wrong and was corrected before the decision was taken.** 60s is `FalImageProvider`'s give-up *ceiling*, not the expected time — M7's own notes say Seedream is "fast, typically seconds." A POST of a few seconds is unremarkable and matches what `generate_shot_image` already does.
- **Backgrounding the keyframe would break a real M7 invariant.** `get_in_flight_for_shot` filters on `status.in_(IN_FLIGHT_STATUSES)`, and today an in-flight row *always* has a pollable `job_id` — M7 was explicit that the handle is persisted "immediately on submit, before anything else." Creating a row before any job exists introduces an orphan state (looks in-flight, nothing to poll) needing a reaper or timeout, which is a new failure mode rather than a UX improvement.

### A7. Pexels video rung (1 d) — **BUILT AND VERIFIED LIVE, 2026-08-18, see §12**

The cheapest motion in the system, and it sits *below* paid generation on the ladder — "reuse before generate". **Build immediately after A1:** it exercises the new motion path at zero spend, which is the right way to prove A1 before pointing it at a paid API.

**Verified against a real live call, not just a mocked one** — a `PEXELS_API_KEY` turned out to be configured after all (see §12's correction). A real search, a real 6.3MB download, and real ffprobe validation all succeeded on the first try.

### A8. The bake-off, now unavoidable (1 d + spend) — **ATTEMPTED 2026-08-18: did not reach its own question, found and fixed a bigger bug instead, see §12**

Defensible to skip while generation was a rare fallback. Not once synthetic motion sits beside a 1936 photograph — "does this blend" becomes the whole question. ⚠ **Requires a human watching output.** Budget as calendar time. Keep the losing renders.

**What actually happened: the bake-off's own precondition failed before "does this blend" could even be asked.** All 3 real Seedream keyframes came back as garbled multi-panel collages, not single photographs - `_generate_video_real`/`generate_image_real`'s shared `_styled_prompt` function had a real, previously-unknown bug (now fixed) that this session had never exercised against a project with a real, rich, multi-era `visual_style` value before. See §12 for the full account, the fix, and its honest limits. **The real "does synthetic motion blend with 1936 photography" question A8 exists to answer is still open** - user chose to stop after the keyframe fix rather than spend more re-running the Kling half with corrected keyframes. Re-running it (3 Kling clips, ~$1.50, keyframes already exist and are already saved) is the natural next step whenever picked back up.

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

`narration_locked` already exempts measured durations from the planner's shot-duration floor, so shorter measured shots need no constraint change — lowering the planning-time floor affects only the planner's pre-narration estimate, because A26 exempts measured durations regardless. *(Corrected 2026-08-18, §13.4/"R4": the 0.6s/1.33s shots this line used to cite live in `hinglish_final_project`/`captions_test_project`, not `m8_test_project` — and both have `narration_locked: true`, so they only prove the A26 exemption itself, never in doubt, not that the Shot Planner can be trusted with a 0.8s floor at planning time. The argument above is the one that actually holds.)*

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
| Duration floor | §4.2 | `min_shot_duration_s` **~0.8s** for fast-cut — a planning heuristic only, and A26 already exempts measured durations, so the risk is low: lowering it affects only the planner's pre-narration estimate, never a real, reconciled shot length (corrected 2026-08-18, §13.4/"R4" — this no longer cites the misattributed 0.6s/1.33s fixture shots) |
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

## 3. Track D — script pre-flight — **levels 1–2 BUILT AND VERIFIED 2026-08-17, see §12; level 3 (§3.3, the actual rewrite) still open**

Runs at **project setup, before the pipeline starts.** Not a workflow step — the run keeps exactly one gate, and the 2026-08-16 one-gate redesign is not reopened.

### 3.1 Two checks, deliberately different in kind — **BUILT, `app/script/preflight.py` + `suitability.py`, see §12**

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

### 3.2 The three intervention levels — levels 1–2 **BUILT**, level 3 **NOT BUILT**, see §12

| Level | What it does | The user's words | Status |
|---|---|---|---|
| **1. Diagnose** | Shows the fragment table with predicted durations; highlights spans that are too long | untouched | **BUILT** (`preflight.py`) |
| **2. Suggest breaks** | Proposes punctuation insertion points; accepted per-span | untouched | **BUILT** (`suggestions.py`) |
| **3. Rewrite phrasing** | Splits sentences by rephrasing, where punctuation cannot | changed | **not built — §3.3 is still design-only** |

**The insight that makes levels 1–2 powerful:** the splitter breaks on **punctuation**, not meaning. So

> "Germany faced a severe oil shortage because it had very little natural petroleum."
> "Germany faced a severe oil shortage, because it had very little natural petroleum."

is **the same words, one comma, two shots instead of one.** For a large share of cases, fast pacing needs the script *re-punctuated*, not rewritten.

⚠ A comma makes the TTS pause, so `D` grows slightly and delivery gets more clipped. For fast-cut that is the intended sound, but it is not free and the calibration must account for it.

**Level 2 also shrinks the LLM's job to something safe.** It stops being *"rewrite my script"* and becomes *"where can this sentence naturally break?"* — one span at a time, each one accepted or rejected by the user. A wrong suggestion is a rejected checkbox rather than a corrupted script, and the model is never holding the whole text at once. That is the entire reason levels 1–2 carry the fear-reduction work that level 3 cannot: **the user's words are never in the model's output.**

### 3.3 The rewrite, and how it is validated in code — **NOT BUILT — this section is still design-only**

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

**Built as part of levels 1–2**, and its own honest limitation (flagged when levels 1–2 shipped, 2026-08-17 — `retention_fast`'s shot-cap override wasn't enforced anywhere real yet) was closed the same day by Track B's `resolve_constraint_bundle(style)`, which both `generate_timeline.py` and `shot/planner.py` now call instead of reading `settings.*` directly. See §12.

### 3.5 Provenance and freezing — **revised 2026-08-17: use the existing script versioning, don't duplicate it — BUILT, see §12**

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

### 3.5.2 Style bands are a small standalone config, not a Track B dependency — decided 2026-08-17, **BUILT** (`app/script/styles.py`)

Track B's `metadata.render_style` field and full preset system do not exist yet. Track D needs a pacing floor/ceiling per style regardless, so it owns a **small local config** — just the 2–3 styles' `D/N` floor and `max(fragment)` ceiling (§2.5.1, §3.1) — independent of any Timeline field or planner prompt. Track B, when built, reads or extends this same config rather than duplicating it. This unblocks Track D immediately and keeps the two tracks' schedules independent.

### 3.5.3 Endpoint shape — stateless, decided 2026-08-17, **BUILT** (`POST /{project_id}/script/preflight`)

Pre-flight is **`POST /{project_id}/script/preflight`**, taking script text and style directly in the request body and returning feasibility + suitability **without persisting anything**. This is what makes live re-measurement on every edit or style change (Q9) cheap and safe — a keystroke-driven check must never create a new `ScriptModel` version, which would fight that table's own "append only on a real, deliberate change" discipline. `POST /{project_id}/script` (persistence) is called separately, once, when the user is done — that endpoint gains the freeze check from §3.5, not the pre-flight logic itself.

### 3.5.4 Suitability verdict — recomputed, not cached — decided 2026-08-17

No existing table shape fits `(script_hash, style) → verdict` in this codebase, and inventing one for a single feature was judged not worth it: the check only fires when the user actively requests it (not on every keystroke — that's the free arithmetic check), so the cost is one cheap LLM call per genuine request. Recompute each time; add persistence later only if the gate screen needs to explain a past verdict without re-asking.

### 3.6 Calibration — **BUILT**, the English constant is live in `app/core/config.py`

`662 chars / 46.0s` = **14.4 chars/sec (English)**, from a real measured run. `hinglish_final_project` gives the Devanagari constant the same way. ⚠ **Calibrate before you block** — you would be hard-stopping a user on the basis of an estimate. Record the error band and set thresholds to fire only on unambiguous mismatch.

### 3.7 Architectural placement — **followed as written**, see `app/script/suitability.py`

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

The two shot-duration bounds are already exempted once `narration_locked` is set, so lowering the floor for fast-cut affects only planner *estimates* — measured reality was never bound by them. *(The claim that a real fixture shot proves this was corrected 2026-08-18, §13.4/"R4" — the cited 0.6s/1.33s shots belong to `narration_locked` fixtures, which only proves the A26 exemption itself, never in doubt. The argument above stands on its own without that citation.)*

Fast-cut at 90s and ~1.75s/shot needs ~51 shots; budget ~55–60. **Decided: fast-cut is allowed to lean harder on paid generation** — which walks into the reuse-repetition problem in §6.

⚠ **Cost note, added 2026-08-18 (§13.3/"R3"):** `fal_video.py` clamps Kling requests to a 3s floor (`max(3, min(15, round(shot.duration_s)))`), so with `retention_fast`'s 0.8–3.5s shots, **every** motion shot clamps up to a 3s request — you pay ~50¢ and discard up to 2.2s of the returned clip. This decision was taken without that cost in view. The real lever, if the economics matter enough to act on, is making A4's per-project video-shot cap style-aware: a `retention_fast` project should cap motion shots far lower than a `documentary_archival` one, because each one delivers less usable footage per dollar.

### 4.3 Prompt organisation

`app/prompts/` already has a directory per planner. ⚠ **Do not create a prompt file per style per planner** — 4 × 5 is 20 files that drift apart. **One base prompt per planner plus one style fragment per style**: 4 + 5 = 9, and a style is readable in one place.

---

## 5. Music, audio, and sound effects under styles — §5.1's taxonomy **BUILT 2026-08-18, see §12**

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

## 6. Track C — long-form (90 s → ~10 min) — ✅ **COMPLETE 2026-08-20, moved to [`track_c_long_form_video.md`](track_c_long_form_video.md)**

> ✅ **Track C is done and no longer lives here.** The seven rows below were the whole of its specification; they became a 1,556-line plan of its own covering C0–C8, a frontend contract (§13 there), and three review rounds that raised and fixed nine findings. ⚠ **Three of the premises in the table below did not survive contact with the code** — the orphan-run blocker was already fixed, the renderer already segmented and concatenated, and C3's encode cost was measured at **~18.6 min for a 10-minute video** against this table's guessed 2–9, which overturned the no-segment-cache decision. **Read the table below as the original specification, not as current status.** For what remains in THIS document, see §14.

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

**Q4. Trim-or-hold for a short clip in a long shot?** **DECIDED 2026-08-18 — hold the last frame.** Settled with measured numbers from the real fixture (the HOLD direction is bounded at +0.5s; 6 of 8 held tails fall entirely inside their own outgoing dissolve), not as an abstract preference. *(Corrected 2026-08-18, §13.3/"R3": the bound is not symmetric — the TRIM direction is unbounded below the 3s Kling API floor, up to -2.2s at `retention_fast`'s 0.8s shot floor. The hold decision itself is unaffected; only the stated bound was wrong.)* See A2.

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

### 2026-08-18 — Track A design pass (no code written), triggered by a request for an on-demand video endpoint

User asked for a video-generation endpoint at the approval gate, mirroring the existing image one, and specified it must be **polling-based rather than synchronous**. Read the relevant code before answering rather than designing from memory. Three findings, all folded into §1 above.

**1. The polling machinery already exists — A6 shrinks from "build" to "wire."** `_generate_video_real` already does submit → persist-`job_id`-immediately → poll-once-per-attempt → download/bind, and `GeneratedClipModel`/`GeneratedClipRepository` already carry every column and method that needs (`job_id`, `status`, `error`; `insert_pending`, `mark_in_progress`, `mark_completed`, `mark_failed`, `get_in_flight_for_shot`). The resume branch is structurally already a poll endpoint's body. See A6 above for the endpoint pair this becomes.

**2. §1's own A1 wording was subtly wrong and would have caused a regression.** It said to classify by ffprobe "**not** by asking Pillow whether it can open the file" — but an animated GIF passes a frame-count/ffprobe test as MOTION, and Commons GIF maps/diagrams are exactly what `ensure_still_image` deliberately flattens (behaviour this same plan says to leave alone). The two instructions contradicted each other. Corrected in A1: Pillow-opens → STILL, Pillow-fails → ffprobe must positively confirm a video stream → MOTION. Preserves the "never infer motion from a failure" intent the original wording was protecting, while keeping every existing still/GIF path bit-for-bit identical. **Caught by reasoning through the GIF case before writing code, not by a regression test after.**

**3. No external signature has to change.** `render_timeline` can probe once internally and pass the classification down to `_render_run`, leaving the public `shot_images: dict[str, Path]` contract alone — so none of the existing render tests (`test_render_determinism`, `test_render_ken_burns`, `test_render_draft`, `test_render_fingerprint_cache`, …) need touching to accommodate motion support.

**Agreed build order:** A1 + A2 (renderer motion input and the fitting rule, together — A1 cannot fit a clip to a shot without A2's rule) → A3's one-line `generate_audio: false` fix → A5 (strip the old constraint-check/bounded-retry from the video path, converging it on the one-gate model the image path already uses) → A6 (the endpoint pair). A1 first is non-negotiable for the reason recorded in A6.

**Two assumptions stated to the user and left open pending their answer — recorded so they are not silently absorbed as decisions:**

1. **Short clip → hold the last frame** (not loop, not slow-motion). This is Q4, which this document has recommended since it was written but which had **never actually been put to the user**; flagged as such rather than quietly treated as settled.
2. **The `POST` blocks while the keyframe generates** (Kling is image-to-video, so a still must exist before the video job can be submitted — up to ~60s). Only the *video* job is polled. Consistent with the existing image endpoint, which already blocks the same way — but if an instant `202` with the keyframe also backgrounded is wanted, that is a materially different shape and should be built that way from the start rather than retrofitted.

**Both assumptions were then put to the user with real numbers rather than as abstract preferences, and both are now closed:**

- **Q4 → hold the last frame.** What made it decidable was measuring instead of arguing: `round()` bounds the gap at ±0.5s, the real project's worst case is exactly +0.50s, and 6 of 8 held tails fall entirely inside their own outgoing dissolve. Recorded in A2.
- **POST shape → block on the keyframe, then `202`.** Two corrections surfaced while framing this, both of which changed the answer: the "~60s block" I had quoted was `FalImageProvider`'s give-up ceiling, not the expected time (M7: Seedream is "fast, typically seconds"); and backgrounding the keyframe would break M7's own invariant that an in-flight row always has a pollable `job_id`, introducing an orphan-row state. Recorded in A6.

**A third question surfaced that the plan had never asked, and it was the user who raised it: is Kling even image-to-video?** It is — but M7 recorded that as a *discovery*, never a comparison, and with A8 skipped nobody had ever weighed it against the text-to-video variant that exists at the identical tier. Investigated, tabled, and decided (keep image-to-video, for the style-anchor argument the Creative Philosophy itself makes). Recorded as new section A3a, including the correction that switching later is *not* purely a config line, since `submit()` unconditionally sends `image_url`.

**Nothing was implemented in this pass** — design and documentation only, at the user's explicit instruction. Track A is now fully specified with no open questions blocking A1.

### 2026-08-18 — Track A built: A1, A2, A3's `generate_audio` fix, A5, A6 — the agreed build order, end to end

User gave the explicit go-ahead to implement. Built in the agreed order, verifying against real ffmpeg/real Postgres at each step rather than trusting the diff alone (the same discipline used for Track B/D).

**A1 (`app/renderer/motion.py`, new).** `probe_media(path)` — Pillow-opens → `MediaKind.STILL`; Pillow-fails → ffprobe must positively confirm a real video stream with a positive duration → `MediaKind.MOTION`; neither signal fires → falls back to `STILL` (matches `still.py`'s own existing "not something Pillow reads" fallback). `render_timeline` (`app/renderer/slideshow.py`) probes every shot's media exactly once, before grouping into runs, and gates `ensure_still_image` on the result (STILL only — a GIF still gets flattened exactly as before; a real clip is left untouched). `ensure_still_image` had to be deferred-imported inside `render_timeline` to avoid a real circular import (`still.py` itself imports `RenderSettings`/`run_ffmpeg` from `slideshow.py`) — caught by running the import, not by inspection. `_render_run` gained a third input/filter branch (`_motion_filter`): a MOTION shot is fed `-i path` fully decoded (never `-loop`/`-t`, the same reason a Ken-Burns shot's input isn't looped either) and NEVER gets a `zoompan` expression regardless of what `shot.camera` says — forced at the `ken_burns_exprs` list-comprehension level, not by relying on every call site to remember the rule.

**A2, same module.** `build_duration_fit_fragment(actual_duration_s, target_duration_s)` — the one function this arithmetic lives in. Gap < 0.02s: no filter at all. Too long: `trim=duration=<target>,setpts=PTS-STARTPTS`. Too short: `tpad=stop_mode=clone:stop_duration=<gap>` (the DECIDED-2026-08-18 hold-last-frame choice). Inserted into the motion filter chain between `fps=` and `format=`, so the stream is exactly `shot.duration_s` seconds either way and D5's `xfade` offset arithmetic never has to know a clip's real length differed from what was asked for.

**Verified against real ffmpeg, not mocked (`tests/integration/test_motion_classification.py`, `tests/integration/test_render_motion_clips.py`, `tests/unit/renderer/test_motion.py`):** a real Pillow PNG classifies STILL; a real animated GIF classifies STILL (the A1 correction, checked directly, not just asserted from the rule); a real ffmpeg `testsrc` clip classifies MOTION with its real probed duration; garbage bytes fall back to STILL. End to end through `render_timeline`: a too-long clip trims to the shot duration; a too-short clip holds its last frame to the shot duration; a shot with `camera.movement=SLOW_ZOOM` whose media is a clip still renders at plain motion, never `zoompan`; a motion clip and a static still crossfade together at the correct total duration (the riskiest combination, mirroring `test_render_ken_burns.py`'s own equivalent proof for STATIC+Ken-Burns). All 46 pre-existing render/thumbnail/media-endpoint tests re-run green afterward — zero regressions from threading a new classification step through the one function every render call site already shares.

**A3's pending half.** `fal_video.py`'s `submit()` now sends `"generate_audio": False` alongside `duration`/`prompt`/`image_url` — the live schema field A3 found but the code never set. One line, one new unit test.

**A5 — the video path onto the one-gate model.** `_generate_checked_keyframe`'s bounded-retry constraint check (the exact mechanism the German-tank-shot failure motivated removing from images on 2026-08-16) is now unwired for video too — kept, not deleted, matching that same precedent. New `_generate_keyframe_once` (module-level, `app/workflow/steps/resolve_assets.py`) generates once, at the project seed, no retry, no vision call — the identical shape `_generate_image_once` already has. Rewrote `tests/integration/test_resolve_assets_generation_real.py::test_video_keyframe_is_checked_not_the_final_clip` (which asserted the OLD retry mechanism directly and would have failed honestly, not silently, against the new behaviour) into `test_video_keyframe_generation_never_checks_director_constraints_even_when_configured`, mirroring the image path's own equivalent proof exactly: a vision provider configured to object is never consulted, and the keyframe ships on the first attempt.

**A6 — the endpoint pair, and a design refinement found while building it.** The plan's own framing ("wiring, not invention") held, but the single existing `_generate_video_real` method conflated three branches — cache-hit, poll-if-in-flight, submit-if-fresh — that a POST and a GET need to split apart: a GET must never have the side effect of a fresh, paid submission, which the unified function could not guarantee if called from a route with nothing yet submitted. Split into two composable, module-level functions instead of duplicating logic per endpoint: `poll_video_job` (poll-in-flight-once, or `None` if nothing is in flight) and `submit_video_generation` (cache-hit / already-in-flight / fresh-submit, idempotent by construction). `generate_video_real` (the workflow step's own per-attempt entrypoint) composes them — poll first, submit only if nothing was polled — and is behaviourally identical to the old method (proven by re-running the full generation test file unchanged, 11/11 green).

`POST /{project_id}/shots/{shot_id}/generate/video` calls `submit_video_generation` directly (202, `{shot_id, clip_id, job_id, status}`, `status` one of `pending`/`completed`/`failed`); `GET` on the same URL calls `poll_video_job` directly and 404s if nothing is in flight ("call POST first"). Neither is routed through the workflow engine, for the identical reason `generate_shot_image` already isn't. **Real gap found and scoped out rather than silently worked around: there is no DRY_RUN fake for video generation anywhere in this codebase** (`_resolve_one_fake` generates a fake IMAGE for every shot regardless of `preferred_type` — video was never wired into the fake path at all). Both endpoints refuse with `400` under DRY_RUN rather than crashing three calls deep on a missing `hosted_url`. Proven end to end in `tests/e2e/test_generate_shot_video_api.py` by flipping `dry_run` to `False` for just the video calls (project setup itself still runs under DRY_RUN, matching every other e2e test) and monkeypatching `FalImageProvider`/`FalVideoProvider` to local fakes — the same pattern the integration test already used one layer down, exercised here through the real HTTP surface: POST rejects under DRY_RUN; GET 404s with nothing submitted; POST-then-GET submits and resolves a video, updating `GET /progress`; a second POST while a job is still in flight never resubmits; a failed job's error reaches the caller.

**Full suite, both before and after the refactor pass, green** — 46/46 pre-existing render tests untouched by A1/A2, 11/11 generation tests (one rewritten) after A5, 6/6 new e2e tests for A6. Static analysis (`ruff`, `black`, `mypy`) clean throughout.

**Track A is now built end to end** except A4 (motion-vs-still calibration/pricing in the planner prompt) and A7/A8 (the Pexels video rung and the bake-off) — neither was in the agreed build order for this pass.

**Full test suite re-run after all of the above, 513/513 green** (up from 494 before this session — 19 new tests: 4 motion classification, 4 render-motion-clip, 4 motion-fit unit, 6 video-endpoint e2e, 1 `generate_audio`). Zero regressions.

### 2026-08-18 — A4's own prompt rule found broken while answering a user question, and fixed on the spot

User asked whether image-vs-video selection is driven by the project's chosen render style. Verified against the actual code rather than answering from memory (an Explore agent confirmed `CreateProjectRequest` has no media-type field, and the Asset Planner — the thing that sets `preferred_type` per shot — never receives `render_style` or a style prompt fragment at all, unlike the Shot Planner). **Answer: no, style has zero connection to it.**

**But checking that surfaced a real, separate bug worth fixing immediately rather than filing away.** The Asset Planner's own prompt (`app/prompts/asset_planner/v1.md:78`) says `preferred_type` should be judged by "the shot's camera movement and intent" — but `_build_user_content` (`app/planners/asset/planner.py`) only ever sent `intent`/`framing`/`prompt` per shot line, never `camera`. Confirmed the Shot Planner (which sets `camera`) runs BEFORE the Asset Planner in `generate_timeline.py` (line 203 vs 231), so the data existed the whole time and was simply never plumbed through — the model was being told to use a signal it structurally could not see. **Fixed**: `camera={movement}` added to each shot line. New test (`test_asset_planner_prompt_includes_each_shots_camera_movement`) asserts the literal string reaches `FakePlanningProvider`'s recorded `user_content`, not just that the diff looks right. 30/30 relevant tests (asset planner, timeline generation, resolve-assets real and generation) green afterward.

**Filed under A4** rather than as a standalone item — it's the same "calibrate the motion-vs-still decision" surface, just the part of it that turned out to already be broken rather than merely uncalibrated. A4's own remaining scope (prompt guidance for when motion earns its cost, plus a per-project cap) is unchanged and still open.

### 2026-08-18 — A7 built: the Pexels video rung, proving A1 against a real downloaded clip at zero spend

**`AssetCandidate` gained one new field, `media_kind: str = "image"`** (`app/providers/base.py`) — defaults to `"image"` so every existing provider (Wikimedia, project uploads, entity retrieval, none of which serve video) needs no change at all. Deliberately set PER CANDIDATE by the provider that actually returned it, never inferred from the query's `preferred_type` at the call site: a video-preferred shot's `fallback_chain` can still legitimately reach an image-only rung first (reuse-before-generate applies regardless of media type), so a query-level flag would have mis-typed a perfectly good found image as a video and sent it into ffprobe validation to fail for no reason.

**`PexelsAssetProvider.search()`** (`app/providers/pexels.py`) now branches on `query.preferred_type`: `"video"` hits Pexels' separate `/videos/search` endpoint instead of `/v1/search`, picks the `hd` mp4 rendition when available (falling back through `sd`/`uhd`, skipping a video with no mp4 rendition at all rather than crashing the whole search), and builds each candidate's `title` from the descriptive slug embedded in Pexels' own video page URL (no `alt` text field exists for videos the way it does for photos). `fetch()` labels attribution "Video by X" vs "Photo by X" based on the candidate's own `media_kind`.

**Correction, same day: the "no API key configured" claim above was wrong.** Checking `backend/.env` (which doesn't exist) instead of the real config location — `app/core/config.py` resolves `env_file` against the REPO ROOT, not the backend directory, and `/.env` there has both `FAL_KEY` and `PEXELS_API_KEY` set. Once found, ran a genuinely live check rather than trusting the mocked tests alone: `search("aerial coastline", preferred_type="video")` returned 10 real candidates, `fetch()` downloaded a real 6.3MB mp4, and `validate_and_identify_video` confirmed it via real ffprobe (360x640, a real result, not fabricated). The parsing logic this section describes is now proven correct against Pexels' actual API, not merely plausible against documented shape. This also means `FAL_KEY` is real too - directly relevant to A8 below.

**New `validate_and_identify_video`** (`app/assets/validation.py`) — Pillow cannot open a video container at all, so this shells out to a real ffprobe (writing the downloaded bytes to a temp file first), applying the same "positively confirm a real video stream with a positive duration" discipline A1's `probe_media` established, extended here to also read width/height. Returns a hard-coded `"mp4"` extension (every video source this codebase downloads from - Pexels, Kling - serves mp4; getting this wrong would only affect the file extension on disk, never playback). Proven against a REAL ffmpeg-generated clip piped to stdout as fragmented mp4 bytes (`tests/integration/test_validate_video.py`) - garbage bytes, an oversized download, and a genuine audio-only mp4 (no video stream at all) are each rejected with a distinct, correct reason.

**`ResolveAssetsStep._resolve_one_real`** now branches its per-candidate validation on `candidate.media_kind` (video → the new ffprobe-based check; image → unchanged) and types the stored `Asset` row honestly (`type=candidate.media_kind`, was hard-coded `"image"`). **A deliberate scope decision, not an oversight:** a searched VIDEO candidate skips the plausibility/vision check entirely, rather than inventing a frame-extraction step to feed an image vision API. This is consistent with, not a lowering of, the current posture - A5 (this same session) already removed every automated content check from a GENERATED video's keyframe, so a searched video getting the identical "human at the gate is the check" treatment doesn't introduce a new gap.

**The renderer needed zero changes** - proof that building A1 first was the right call. `render_timeline` classifies by the FILE CONTENT it finds at `asset.local_path` (Pillow-then-ffprobe), never by this provider's `media_kind` field or the DB `asset.type` column - a real Pexels clip lands on disk and is automatically treated as MOTION, duration-fitted, and never Ken-Burns'd, with no code path aware that A7 even exists.

**Verified against real ffmpeg and a real Postgres, not mocked:** `tests/unit/providers/test_pexels.py` (video search parses a real-shaped response, picks the HD rendition, skips a webm-only video, falls back on a slug-less title, image search never touches `/videos/search`); `tests/integration/test_validate_video.py` (4 cases against genuine ffmpeg-generated clips); `tests/integration/test_resolve_assets_real.py::test_video_candidate_from_a_stock_search_rung_validates_and_binds_as_video` (a real generated clip, through the REAL `ResolveAssetsStep` search pass, ends up `resolved`/`stock_search`/`type="video"` on disk with a `.mp4` extension). 227/227 relevant tests green (assets, providers, resolve-assets real/generation, planners) - zero regressions.

**Track A is now built end to end except A8** (the bake-off - needs a human's eyes on real spend, can't be automated) and the calibration half of A4 (prompt guidance for when motion earns its cost, plus a per-project cap - the prompt-plumbing bug under that same heading is already fixed).

### 2026-08-18 — A4's calibration half built: sharper prompt guidance, a per-project video cap

**Prompt guidance** (`app/prompts/asset_planner/v1.md`) rewritten now that the Asset Planner can actually see `camera` (the earlier plumbing fix): the old rule ("image unless camera movement and intent clearly call for genuine motion") left "genuine motion" undefined and never mentioned that the renderer can ALREADY put a slow push/pan/zoom on a still photo (Ken Burns). Rewritten to say so explicitly - camera movement alone is never a reason to choose video, since a still gets the same movement for a fraction of the cost; video is for when the SUBJECT itself needs to move in a way no single photograph could show (flames spreading, smoke billowing, machinery operating), with a concrete cost ratio (~10x) and a worked contrast (a static subject with only a described camera direction is exactly the Ken-Burns case, not a video one).

**Per-project cap** (`settings.max_video_shots_per_project`, default 5) enforced in `AssetPlanner.plan()` - a running, cross-scene count of `preferred_type == VIDEO` shots, checked and failed loudly (`PermanentError`) the moment it's exceeded, mirroring `ShotPlanner.plan()`'s own `max_shots_per_project` check exactly (same file structure, same "the model is never asked to reduce its own count, this just stops the run before more of it gets planned" reasoning already established and validated for shot count). `AssetPlanner.plan()`'s signature gained a required `max_video_shots_per_project` kwarg (no default, matching `ShotPlanner.plan()`'s own style) - every call site, including five in the existing test file, updated to pass it explicitly.

**Verified:** a new test (`test_asset_plan_fails_loudly_once_the_video_shot_cap_is_exceeded`) proves the cap actually fires, with a cap of 1 and two video shots in one scene. 71/71 relevant tests green (planners, timeline generation, resolve-assets real/generation, fixture round-trip) - zero regressions.

**A4 is now fully built.** Track A's only remaining item is A8.

### 2026-08-18 — Correction: a real `PEXELS_API_KEY`/`FAL_KEY` ARE configured, found while double-checking A7's own caveat before starting A8

Re-verified A7's "not verified against a live call" claim before treating A8 as blocked on missing keys. It was wrong: `app/core/config.py` resolves its `env_file` against the REPO ROOT (`Path(__file__).resolve()` climbed to `_REPO_ROOT`), not `backend/`, which is the directory checked earlier. The real `.env` at the repo root has both `FAL_KEY` and `PEXELS_API_KEY` set, and `DRY_RUN=false` - this environment is wired to real, billable accounts, not a key-less sandbox.

**Ran the free half live rather than assuming the correction was enough on its own:** `PexelsAssetProvider.search("aerial coastline", preferred_type="video")` returned 10 real candidates; `fetch()` downloaded a genuine 6.3MB mp4; `validate_and_identify_video` confirmed it via real ffprobe (360x640). A7's parsing logic is now proven against Pexels' real API, not merely documented shape - the caveat is retired, not just softened (see A7's own section and its earlier §12 entry, both updated).

**Did NOT similarly test `FAL_KEY` against Kling** - unlike Pexels search, a Kling video generation call is real, billed spend (~54c per clip: ~4c Seedream keyframe + ~50c Kling video, per `settings.fal_*_cost_cents_estimate`). That is exactly what A8 is - stopping here to confirm scope and budget with the user before spending real money, rather than treating "the user said do A4 through A8" as authorization for an unspecified dollar amount against a real account.

### 2026-08-18 — A8 attempted: a real, previously-unknown collage bug found and fixed instead of the bake-off's own question getting answered

User approved 3 real clips (~$1.60) against real archival stills from `m8_test_project`. Picked 3 real shots spanning different types on purpose (a WWII map, a Fischer-Tropsch lab-equipment close-up, a Sasol plant wide shot) via a standalone script (`a8_bakeoff.py`, calls the SAME `FalImageProvider`/`FalVideoProvider`/`_styled_prompt` production code, no DB/workflow engine involved - a one-off comparison, not a project run) - styled with the project's own real `creative_context.visual_style`, submit-then-poll, resumable (mirrors A6's own resumability, since Kling can run long enough to outlast one shell command).

**All 3 keyframes came back as garbled multi-panel collages, not single photographs** - 2-4 stitched sub-images per keyframe, some with illegible AI-hallucinated fake captions ("Wartsne fuel maps"). Kling then faithfully animated the broken collage. **This is not a Kling motion-quality finding - it's upstream**, and it was systematic, not a fluke: all 3 shots failed identically.

**Root cause, found by reading the real prompt sent, not guessing:** `_styled_prompt()` concatenates a shot's own prompt with `creative_context.visual_style` VERBATIM - and a real Director-written `visual_style` describes the WHOLE VIDEO'S ARC across multiple eras as an explicit sequence ("black-and-white WWII coal mines... **then** muted-color South African refinery... **ending with** contemporary energy infrastructure"). Checking the other real fixtures in this repo (`captions_test_project`, `hindi_test_project`, `hinglish_test_project`, `hinglish_final_project`) found the SAME multi-era narrative shape in every one of them - this bug has been live since M7 for any project whose Director wrote a rich `visual_style`, not something this session introduced.

**Two fixes were tried and REJECTED, each verified against a real regeneration rather than assumed to work:**
1. An explicit "single photograph, no collage, no grid" instruction appended to the prompt. **Made it WORSE** - the retried keyframe came back as an even busier 3x3-style collage. Diffusion-family image models are known to handle negation poorly; naming the failure mode in the prompt adds "collage" as a concept the model can now draw on.
2. A positive reframing ("one photograph, one camera framing, one moment") without naming the failure mode. Better - the main scene became dominant - but a sidebar strip of extra panels still survived.

**What worked, verified against the same real prompt and then against the real production function:** mechanically capping how much of `visual_style` gets appended - `_MAX_VISUAL_STYLE_WORDS = 15`, a fixed word count, deliberately NOT a keyword search for connectives like "then"/"ending with" (English-specific, and would miss `hindi_test_project`'s own Hindi "फिर"). The NARRATIVE BREADTH is what triggers the collage, not any particular phrasing within it - truncating to one coherent style clause instead of the full multi-subject arc fixed 2 of 3 real shots completely (the map and the lab-equipment shots came back as single, clean, correctly-styled photographs) and substantially improved the third (one dominant well-composed image, down from a full 4-panel grid, though two small pasted-on document fragments still survived in the corner).

**Stated honestly, not oversold: this is a real, substantial, verified improvement - not a mathematical guarantee.** The third shot's residual artifact shows Seedream can still drift toward a collage even from a short, single-era prompt; this is model behaviour a prompt-construction fix bounds but does not eliminate outright. The human at the review gate (regenerate via the existing endpoints) remains the real safety net for whatever gets through.

**Fixed in `_styled_prompt()` (`app/workflow/steps/resolve_assets.py`)** - shared by both `generate_image_real` (standalone images) and the video keyframe path, so this fix protects both surfaces, not just video. New `tests/unit/workflow/test_styled_prompt.py` (4 tests) proves the cap as a pure string assertion - word-boundary, not character-boundary; the narrative's own sequencing words never survive into the capped output - so a future edit can't silently widen the cap back out without a test noticing. 33/33 relevant tests green (the new file, resolve-assets real/generation, timeline generation) - zero regressions.

**Real spend: ~$1.86 total** - the original 3 keyframes + 3 Kling clips (~$1.62, all still garbled-collage-derived, kept as evidence of the pre-fix failure) plus ~24c across 6 more image-only calls while diagnosing and verifying the fix (2 rejected attempts, 1 hand-tuned proof-of-concept, 3 real-function verifications post-fix).

**User's call, asked explicitly rather than assumed: stop here.** Given a choice between spending ~$1.50 more to re-run all 3 Kling clips against the now-mostly-fixed keyframes (the real comparison A8 exists to make) or stopping with the prompt fix as the deliverable, the user chose to stop. **A8's own question - does synthetic motion actually blend next to real 1936 archival photography - remains open.** Re-running the Kling half is cheap and immediate whenever picked back up (the fixed keyframes already exist, saved to `C:\Users\<user>\Desktop\a8_bakeoff\`, alongside the original failed ones and the rejected-attempt keyframes, kept as evidence).

### 2026-08-18 — Orphan-run fix built (§11 step 5), then the music library (§11 step 6, §5.1) built end to end

**Orphan-run fix.** `trigger.py::_claim_or_join`'s `state == "running"` check assumed "running" always means another caller is actively executing the pipeline right now - true until that caller's process is hard-killed (Ctrl-C, reboot, OOM), after which the row is stuck `"running"` forever with nothing left to ever resume it (the exact bug named in the Backlog, `docs/13_Implementation_Guide.md`, and flagged in §6 as blocking C6). Fixed with the preferred approach already written down there: `reclaim_orphaned_runs()` (`app/workflow/trigger.py`), called once from `main.py`'s `lifespan` before the app accepts requests - any row still `"running"` at that exact moment is provably orphaned under the single-instance assumption (the process that would be running it is the one just starting), so it's resumed the same way a normal trigger would (`_execute_in_background`, no special-casing needed since `WorkflowEngine.run()` already resumes a `"running"` row correctly via `is_satisfied()`). New `WorkflowRunRepository.list_running()` plus 2 new integration tests against the real DB (`test_workflow_trigger.py`) - one proving a genuinely orphaned row gets resumed, one proving completed/paused rows are left alone. 6/6 in that file, 336/336 full unit suite, ruff/black/mypy clean.

**Music taxonomy + BPM decision, then a real 54-track library.** §5.1 named the gap (six mood categories describe *what*, none describe *how it's cut* - no category a fast-cut style could use) and warned the full cross-product (6 moods × 3 energies × 2-3 tracks = 36-54, human-vetted **by ear**) is expensive. User chose the full matrix anyway, explicitly accepting that cost. Two axes: **mood** (`documentary_dark`, `documentary_mystery`, `documentary_ambient`, `industrial`, `historical_epic`, `emotional` - unchanged from §5.1) × **energy** (`ambient`/`mid`/`driving`, new - closes the fast-cut gap).

Sourcing was real research, not assumed: 6 parallel agents searched Pixabay Music, Free Music Archive, and Incompetech (YouTube Audio Library was checked and found to require an authenticated session neither WebFetch/WebSearch nor this agent can drive - skipped, not faked) and returned only link-verified real candidates, 3 per cell, 54 total. Downloading turned out to be genuinely uneven across sources, discovered by testing rather than assumed: **Pixabay has no download API at all** (`app/providers/pixabay_music.py` already documented this for search; verified here it's equally true for downloads - JS-gated, no static pattern, and that module's own docstring already concluded scraping around it is "fragile and likely against Pixabay's terms," a wall this work did not attempt to go around) and **FMA's classic API 404s on the current site** (ownership changed hands; no current public docs found). Only **Incompetech** serves files from a plain static path with no auth/JS needed - verified live before trusting it, then all 14 Incompetech tracks were downloaded programmatically this way. The remaining 40 (27 Pixabay + 13 FMA) were downloaded by the user by hand, batched 10 at a time, each batch verified with `ffprobe` (real MP3, duration matches source) before being filed into `storage/music_library/<mood>/<energy>/` and deleted from Downloads - nothing added to the library unverified.

**Licensing, recorded honestly rather than smoothed over:** 45 of 53 unique files are Pixabay Content License / CC0 / CC BY (commercial-safe); 8 are CC BY-NC or CC BY-NC-ND. Worth naming precisely, not just as a policy risk: `OpenverseMusicProvider`'s own docstring already excludes NC/ND from ITS result set for a concrete reason - this renderer's own bed/duck mix (`app/renderer/music.py`) creates a derivative of whatever track is chosen, which is exactly what ND forbids, not a grey area. Flagged twice; **user's explicit, informed decision: use all of them anyway.** `LocalMusicProvider` therefore does no licence filtering of its own (unlike Openverse) - it reports the whole library, licence included, and leaves gating to the EXISTING mechanism `SelectMusicStep._select` already has (`plan.licence_requirements`, empty/unused by default) rather than inventing a second one. Recorded in `MANIFEST.md` per track so the decision stays visible, not silently absorbed.

**Built:** `manifest.json` (54 entries: file/title/artist/source/licence/mood/energy/bpm/duration_s/tags, `duration_s` computed by real `ffprobe` against every file, not asserted) and `app/providers/local_music.py` (`LocalMusicProvider` - `search()` returns the whole library as the candidate pool since a fixed local catalogue has no "zero results" case the way a live search does, letting the existing term-overlap ranking in `app/assets/music_ranking.py` do the actual matching; `fetch()` reads local disk, never network). `settings.music_provider` default changed from `"openverse"` to `"local"` (Openverse's own docstring: "a narrow music_plan legitimately finds nothing on a real search" - this library is never empty). New `settings.music_library_root`. 6 new unit tests (fake manifest under `tmp_path`, never the real files) plus 3 new integration tests against the REAL library (`test_music_library_integrity.py` - all 54 slots present across all 18 cells, every file exists and is real decodable audio matching its recorded duration, no duplicate file paths). 342/342 unit suite, 27/27 targeted music tests, ruff/black/mypy clean. Verified once more end to end against the real library outside the test suite too: a real query ranked and picked a genuinely fitting track, `fetch()` returned real bytes with a correct attribution string.

**Not done:** per-style bed/duck gain (§5.2, ~0.5d), BPM-based tempo-fit ranking (§5.3, needs the library to exist first - it now does), SFX (§5.5, separate batch). BPM itself is only recorded where a source actually published it (mostly Incompetech) - not fabricated for the rest, per this document's own standing discipline.

### 2026-08-18 — §13's code-vs-plan review acted on: 8 of 10 findings fixed, 1 needs a spend decision, 1 is a deferred product call

Worked the review's own recommended order (§13.13), skipping nothing that didn't need a human decision.

**R1 (BLOCKING) + R2's first half (auto-closed).** `GenerateTimelineStep.run()`'s post-planning gate and `_is_fully_planned` (the resume check) used to resolve style bounds SEPARATELY and had drifted apart - `run()` read flat `settings.*` directly, so `retention_fast` (authorised by the Shot Planner to emit 0.8s shots / up to 58 of them) was rejected by its own project's final gate every time, after the Director/Scene Planner/every Shot Planner call had already been paid for. Fixed by extracting ONE shared function, `_validate_against_style`, that both call sites now use - structurally impossible to diverge again, not just corrected for today. 5 new pure unit tests (`test_generate_timeline_style_bounds.py`) build a real `retention_fast` Timeline with 50 shots at 0.9s and prove it passes the resolved bundle, fails the flat settings, and that both call sites' source code now contains the same function call.

**R9.** `preflight.py`'s shot-cap violation message was telling users planning "would have to merge fragments... or fail outright" - §3.4 (corrected twice, back on 2026-08-17) already established the merge half doesn't exist. Message rewritten to say what actually happens: planning fails outright, partway through, after the Director and Scene Planner already ran.

**R7.** `resolve_constraint_bundle` was reading `max_fragment_duration_s` - a pre-flight DIAGNOSTIC (§2.5.1's dead-stop ceiling, explicitly uncalibrated, Q5 still open) - as the Shot Planner's real validation bound. Fixed by giving `StylePacingBand` its own `max_shot_duration_s_override` field (3.5 for `retention_fast`, same number as before, now independent rather than borrowed). Also replaced three `x or y` reads with `x if x is not None else y` in the same function - the `or` form silently treated a legitimate `0`/`0.0` override as unset, unreachable today but a live trap for a future style. 2 new tests prove the fields are independent (moving one doesn't move the other) and that a `0.0` override is honoured.

**R3, R4 (documentation only, no code was wrong).** Both were wrong JUSTIFICATIONS, not bugs: `build_duration_fit_fragment`'s `trim` branch already handled the real numbers correctly. R3 - the "±0.5s gap" bound is only true in the HOLD direction; the TRIM direction is unbounded below the Kling API's 3s floor (up to -2.2s at `retention_fast`'s 0.8s shot floor) - corrected in `motion.py`'s docstring and in §2.5/Q4/§4.2, plus a new cost note added to §4.2 (every `retention_fast` motion shot clamps up to a paid 3s request regardless of the shot's real length). R4 - the "0.6s and 1.33s shots prove sub-floor shots work in production" claim, cited three times, pointed at the wrong fixtures (both cited shots are in OTHER projects with `narration_locked: true`, which only proves the already-uncontested A26 exemption) - all three citations replaced with the argument that actually holds (A26 exempts measured durations regardless of the planning-time floor).

**R6 (user-confirmed decision: `documentary_archival` becomes the real default look).** `render_style=None` and `render_style="documentary_archival"` produced identical planning constraints but different pixels - `resolve_constraint_bundle(None)` already resolved through `settings.default_render_style`, but `grade_filter_fragment(None)` returned no grade at all. Fixed by making the grade function resolve `None`/an unrecognised name through `settings.default_render_style` too, matching the constraint-bundle function exactly. **This changes the output bytes of every existing style-less project** - a deliberate, confirmed trade, correctly caught as a re-render by the fingerprint (I5), since `render_style` was already part of its payload. 2 existing tests updated to assert the new behaviour (`None` now equals an explicit `documentary_archival` call, not `None`).

**R5 (user-confirmed decision, chosen via a concrete scenario: split the field).** §2.1 promised the grade stays freely changeable ("re-render is cheap") separately from planner-facing levels that freeze at planning start - but there was only one field (`render_style`) and one freeze, so the grade was in practice the MOST locked knob, not the most flexible. Fixed with a new, independent `TimelineMetadata.grade_style: str | None` field and a new endpoint, `POST /{project_id}/grade` - deliberately NOT behind the freeze check `POST /style` has, since it never touches planning inputs, only which `eq` filter the renderer applies. `grade_style=None` (the default) falls through to `render_style`'s own grade unchanged; setting it overrides the grade at any time, including after a project has already rendered. `RenderStep` now reads `grade_style or render_style`. Persisted via `TimelineService.append_version` with `owns={"metadata.grade_style"}` - a dotted-path ownership grant the additive-only checker (`app/timeline/additive.py`) already supported, verified directly rather than assumed. 5 new pure unit tests exercise that mechanism directly: changing `grade_style` alone is allowed when owned, rejected without ownership (once a value is already set - filling a null field is always allowed regardless, which is a different, correctly separate rule), clearing it back to `None` is allowed, and owning `grade_style` grants no ownership over `render_style`.

**R10.** A1's own stated requirement - "the review screen must play a clip" - was never met; `GET /shots/{shot_id}/asset` only ever serves a still frame, even for a bound video. New `GET /{project_id}/shots/{shot_id}/clip` streams the real video bytes (`media_type="video/mp4"` - NOT `mime_type_for_extension`, which only knows image extensions and would have silently mislabelled this as `image/png`, a bug caught before it shipped, not after), 404 for a still or an unbound shot. `/asset`'s own frame-extraction behaviour is unchanged - the right thing for a thumbnail grid, the wrong thing for judging motion, which is exactly what A8's bake-off needs and R10 names.

**Verified throughout, not merely written:** every fix above landed with its own new unit test(s) alongside it (18 new tests total across `test_generate_timeline_style_bounds.py`, `test_styles.py`, `test_grading.py`, `test_grade_style_ownership.py`), `ruff`/`black`/`mypy` clean on every file touched, `python -c "import app.main"` clean after the new endpoint, and the full 367-test unit suite (up from 355) green with zero regressions. Per this session's standing instruction, the DB-backed integration/e2e suite was NOT run during this work - deferred to a single run once the currently-planned work is done, same discipline as Track D level 3.

**Left open, deliberately:**
- **R2's second half** (level 2's suggestions are iterative but presented as one-shot) - a product decision, explicitly the LOWEST-urgency item in §13.13's own order, not touched.
- **R8** (ElevenLabs speed support - unverified, 10-minute live API check) - needs a real, tiny spend against the configured ElevenLabs account; not yet asked for or approved, so not done. ⚠ Per §13.13's own warning, `retention_fast` should not reach a real user until R1 (done) AND R8 (open) both close - the style is safe to plan and render now, but its narration will not yet match its cutting speed.

### 2026-08-18 — Three follow-up findings on the §13 review, from a second reviewer

Found while re-reading §13.1/§13.7 against this environment's actual configured values (not the code's own defaults) - real, independently useful catches, none of them re-opening a closed item:

1. **§13.1 correction, not a re-open.** The "kills `retention_fast` even on a 13-shot script" claim is true of the code's *default* `min_shot_duration_s` (1.5s) but this environment's `.env` overrides `MIN_SHOT_DURATION_S=0.5`, below `retention_fast`'s own 0.8s floor - so the duration-based half of R1 could never have fired on this exact machine; only the 40-vs-58 shot-cap half was reachable here, and it alone was already sufficient to make R1 fully blocking. §13.1 corrected to say so precisely rather than imply the 13-shot failure was universal.
2. **A residual, narrower version of R1's own shape survives the fix, found and documented (not closed) - mechanism sharpened by a third reviewer pass the same day.** `script_preflight_margin_fraction=0.2` widens `check_feasibility`'s ceiling check (`3.5 x 1.2 = 4.2s` for `retention_fast`) but `generate_timeline.py::_validate_against_style` enforces the same `max_shot_duration_s_override` (3.5s) with no margin at all. The first pass under-stated the risk as "only a planner estimate, never a real narrated shot" - true of the FINISHED video, but not of whether the RUN survives. **The sharper mechanism, verified directly against the real code:** a fragment landing in 3.5-4.2s is ATOMIC (`fragments.py`: "a fragment is the finest unit a shot may own" - unsplittable, unmergeable by the Shot Planner), and the repair loop DOES check this bound (`shot/planner.py::_make_validator` takes `max_shot_duration_s` and retries on violation) - so the model has no legal move that shortens the shot. Two outcomes only: it under-estimates `duration_s` (passes planning, `narration_locked` corrects it later, no harm to the finished video) or it reports honestly (~3.6s), the repair loop cannot converge against a bound the shot can never satisfy, retries exhaust, and the run dies - exactly R1's own failure mode, reached a different way. Which branch happens depends on the model choosing to mis-estimate, not a property this code controls. Still deliberately left open (narrowing the margin reintroduces false pre-flight rejections; widening planning's real bound weakens an actual creative ceiling for an unrelated reason) - but `preflight.py`'s own comment now states the real two-branch mechanism, not the softer estimate-only framing.
3. **A second, untouched copy of R7's exact `or`-trap**, found in `preflight.py:179` (`shot_cap = band.max_shots_override or settings.max_shots_per_project`) - R7's fix only touched `styles.py`'s own copy of this read. Fixed the same way (`if ... is not None else`), with a new test (`test_a_zero_shot_cap_override_is_honoured_not_treated_as_unset`) proving a synthetic `max_shots_override=0` band is honoured rather than silently falling through to the flat default.
4. **R3's correction never reached its own primary source paragraph.** The first R3 pass fixed `motion.py`'s docstring, §4.2, and Q4 (§10) - but missed A2's own statement in §1 (the paragraph §13.3 actually quotes from), which still read "the gap is mathematically bounded at ±0.5s" and "the 2 exceptions are +0.10s each" verbatim. Both numbers were wrong there too: the bound is HOLD-direction only (TRIM is unbounded below the 3s Kling floor, down to -2.2s at `retention_fast`'s 0.8s floor), and the two dissolve/fade exceptions are `+0.45s` (`sc_02_sh_01`) and `+0.10s` (`sc_03_sh_03`), not `+0.10s` each. Fixed in place with a correction note, rather than rewriting the original paragraph's own voice.

**Verified:** 8 tests across `test_preflight.py` (1 new) all green, `ruff`/`black`/`mypy` clean. DB suite still not run, same standing deferral.

### 2026-08-18 — Track D level 3 built: the script rewrite, §3.3

**Built as designed, no scope changes from §3.2/§3.3.** `app/script/rewrite.py::rewrite_script` - same `None`-means-"nothing to show" convention `check_suitability` already established (DRY_RUN, no provider, or empty script all return `None`, never a fabricated result), one LLM call via `PlanningLLMProvider.structured_complete` against a new prompt (`app/prompts/script_rewrite/v1.md`), recorded through the same `LlmCallRepository.insert` audit path every other planning call uses.

**All three deterministic backstops from §3.3 implemented as designed:**
- Numeric tokens preserved as a multiset (`Counter` comparison) - a dropped or invented number rejects the whole rewrite outright, named specifically in the rejection reason (which numbers, not just "numbers changed").
- Capitalised entities preserved, but as a SET, not a multiset - deliberately allows a second mention to become a pronoun (a legitimate rephrase) while still catching an entity disappearing outright. A small stoplist of common sentence-initial words (`_COMMON_CAPITALIZED_WORDS`) excludes words like "The"/"It" that legitimately move around when sentences get re-split - without it, ordinary rephrasing would trip this check on words that were never real entities. Verified directly with a test for exactly this case.
- Fragment count actually increased, using the real `split_narration_fragments` - a rewrite that changes wording without increasing fragment count is rejected as a no-op, not accepted as a pointless diff.

**A rejected rewrite is never silently discarded** - `RewriteResult` always carries the attempted text plus every reason it failed, so a caller can show a human what the model tried and why it didn't stick, rather than a bare failure.

**Persistence wired per §3.5, not reopened:** new `ProjectRepository.append_rewritten_script` (both `InMemoryProjectRepository` and `PostgresProjectRepository`) appends a new `ScriptModel` row with `source="rewritten"` - the ONLY path that does; the existing `update()`/`upload_script` path still writes `source="user"` by default, unchanged. `_append_script_if_changed` gained an optional `source` kwarg, backward compatible (existing call site unaffected).

**Endpoint: `POST /{project_id}/script/rewrite`, stateless by default** - mirrors `POST /script/preflight`'s own design (§3.5.3): `script`/`style` travel in the request, so a rewrite can be tried against draft text before it's ever uploaded, and nothing persists unless `persist=True` is explicitly passed AND the rewrite was `accepted` - a rejected rewrite is never persisted regardless of the flag. `persist=True` goes through the same freeze check `upload_script`/`POST /style` already have (refuses once a timeline exists).

**Verified, not merely written:** 13 new pure unit tests (`tests/unit/script/test_rewrite.py`) - a fake `PlanningLLMProvider`/`LlmCallRepository` double, no DB - covering all three backstops individually (including the pronoun-swap and common-word-stoplist cases specifically, so a future edit can't silently make these checks stricter than intended without a test noticing), the three `None`-return cases, an accepted rewrite recording its LLM call and re-running feasibility on the result, and a rejected rewrite still returning its reasons. `tests/unit/script/` in full (29 tests, including the pre-existing preflight/suggestions/styles tests) green. `python -c "import app.main"` succeeds. `ruff`, `black`, `mypy` clean on every file touched.

**Not run yet, per the user's own standing instruction this session:** the DB-backed integration/e2e suite (an API-level test for the new endpoint against a real project/DB would belong in `tests/e2e/`, not yet written) - deferred until the rest of the currently-planned work is done, then run once, matching this session's established discipline for expensive full-suite runs.

**Track D is now fully built** - all three intervention levels (diagnose, suggest, rewrite) exist and are verified at the unit level; only a DB-backed end-to-end API test for the new endpoint remains, deliberately deferred.

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

---

## 13. Code-vs-plan review, 2026-08-18 — where the code does not match this document, and the fixes

> **Method.** Read this plan in full, then verified its claims against the actual code and the real fixture files rather than against §12's own log. Every number below was produced by *running* the real functions (`check_feasibility`, `suggest_breaks`, `split_narration_fragments`, `build_duration_fit_fragment`, `grade_filter_fragment`, and the real `_motion_filter`/`_ken_burns_filter`/`_normalize_filter`) or read directly out of the fixture JSON — none is inferred from reading code. Where a finding is a wrong *justification* rather than a wrong *behaviour*, it says so.
>
> ⚠ **Status, updated 2026-08-18: R1 (both blocking items, which auto-closes R2's first half), R9, R7, R3, R4, R6, R5, and R10 are all FIXED and verified (see §12's matching entry for each) — only R2's second half (transitive suggestions, a product decision, explicitly lowest urgency) and R8 (ElevenLabs speed - needs a real, tiny spend, not yet confirmed) remain OPEN.** This section remains the record of what was found; §12 records what was done about it.
>
> **The pattern behind R1, R2 and R4 is worth naming up front, because it is the same mistake three times and it is not a carelessness problem.** This project's verification standard is high *per unit* — §12 is full of "verified, not merely written," and it means it. All three of these slipped through because the check ran at the wrong **altitude**: the resolver was verified but not the run that calls it; the suggestion engine's mechanism was verified but not the user journey through it; two real sub-floor shot durations were found but not the fixture they were attributed to, nor the flag that made them legal. This is the same class of mistake §12's own 2026-08-17 method note already recorded once ("the first correction failed because it read the shared helper without reading the call site that supplies its validator") — recurring, so worth treating as a standing review rule rather than an incident.

### 13.1 R1 — BLOCKING: `retention_fast` cannot complete a run, and the "gap closure" closed the wrong call site — **FIXED 2026-08-18, see §12**

**`app/workflow/steps/generate_timeline.py:124-129` — `GenerateTimelineStep.run()`'s post-planning validation still reads the flat settings:**

```python
violations = timeline.validate_constraints(
    max_video_duration_s=settings.max_video_duration_s,
    max_shots_per_project=settings.max_shots_per_project,   # 40
    min_shot_duration_s=settings.min_shot_duration_s,       # 1.5
    max_shot_duration_s=settings.max_shot_duration_s,       # 8.0
    max_scenes=settings.max_scenes,
)
```

Twenty-five lines earlier, at `generate_timeline.py:199-210`, the Shot Planner was handed `resolve_constraint_bundle("retention_fast")` → `(0.8, 3.5, 58)`. And `app/prompts/shot_planner_styles/retention_fast.md` actively instructs the model to use it: *"You will be given a lower minimum shot duration than usual for this reason — use the room it gives you."*

**So the planner is authorised to emit exactly the timeline the next statement rejects.** Two failure modes, both loud, both after the Director, the Scene Planner and every Shot Planner call have been paid for:

- any shot under **`settings.min_shot_duration_s`** fails `_validate_planning_time_shot_bounds` (`narration_locked` is not set yet at planning time) — the *code default* is 1.5s, which is above `retention_fast`'s 0.8s floor and so kills it **even on a 13-shot script**, not only above the cap. **Correction, 2026-08-18:** this environment's own `.env` overrides `MIN_SHOT_DURATION_S=0.5`, *below* `retention_fast`'s floor — so on THIS machine the duration half of R1 could not fire on any script; only the cap half (below) was reachable here, and it alone was still fully blocking, since `retention_fast` needs ~51 shots for a 90s script regardless of the duration floor;
- more than **40** shots fails `_validate_structural_invariants`, which applies regardless of `narration_locked` and regardless of `min_shot_duration_s` - this half was reachable on this exact machine and is sufficient on its own to make R1 blocking here.

⚠ **§3.2 and §12 both record this gap as closed, and it is not.** The claim — *"closed the same day by Track B's `resolve_constraint_bundle(style)`, which both `generate_timeline.py` and `shot/planner.py` now call instead of reading `settings.*` directly"* — is true of `shot/planner.py`, and true of `generate_timeline.py:77`. But line 77 is inside **`_is_fully_planned`**, the resume/idempotency predicate. It is not the gate that fails the run. Two validators of the same invariant now disagree, and the comment at `generate_timeline.py:68-76` asserts the closure that did not happen.

**`app/script/preflight.py:14-29`'s own module docstring still warns that this gap is open — it is now the only accurate record of it in the repository, and it should not be deleted until the fix below lands.**

**Why 513/513 green never caught it:** nothing puts `retention_fast` through `GenerateTimelineStep` or `Timeline.validate_constraints`. Every `retention_fast` test is a unit test of the registry (`test_styles.py` asserts `resolve_constraint_bundle` returns `(0.8, 3.5, 58)` — which it correctly does) or of a pure function. The end-to-end path was never exercised.

**Fix (three lines, plus the test that is the actual deliverable):**

```python
# generate_timeline.py, inside run(), replacing lines 124-129
min_shot_duration_s, max_shot_duration_s, max_shots_per_project = resolve_constraint_bundle(
    timeline.metadata.render_style
)
violations = timeline.validate_constraints(
    max_video_duration_s=settings.max_video_duration_s,
    max_shots_per_project=max_shots_per_project,
    min_shot_duration_s=min_shot_duration_s,
    max_shot_duration_s=max_shot_duration_s,
    max_scenes=settings.max_scenes,
)
```

⚠ **The test matters more than the change.** A test that builds a `retention_fast` Timeline with 50 shots at 0.9s and asserts `validate_constraints` passes under the resolved bundle *and* fails under the flat settings is what stops this regressing a third time. Better still, one asserting that both call sites in this file resolve their bounds identically — the divergence, not the values, is the defect.

### 13.2 R2 — BLOCKING: pre-flight certifies scripts that planning then rejects — **first half FIXED (auto-closed by R1), second half (transitive suggestions) still OPEN as a product decision, see §12**

Reproduced against the real fixture script by iterating `suggest_breaks` → apply → `check_feasibility`:

| pass | `N` | avg | longest | pre-flight | real planning (today) |
|---|---|---|---|---|---|
| original | 13 | 3.54s | 8.0s | ❌ blocked | — |
| +7 suggestions | 20 | 2.32s | 4.3s | ❌ still blocked | — |
| +10 more | 30 | 1.57s | 2.64s | ✅ passes | ❌ dies (sub-1.5s shots) |
| +10 more | 40 | 1.20s | 2.15s | ✅ passes | ❌ dies |
| +3 more | 43 | 1.12s | 2.15s | ✅ passes | ❌ dies (43 > 40, **and** sub-1.5s) |

`preflight.py:179` checks `band.max_shots_override` (58); planning checks 40. **The pre-flight built to prevent a dead planning run now causes one** — and does so precisely on the scripts it has just certified, which is worse than not checking, because the user has been told it is safe. Closes automatically with R1's fix; recorded separately because the *reasoning* is separate (R1 is a mismatch between two call sites, R2 is a mismatch between a pre-flight promise and its enforcement).

⚠ **Second, independent finding in the same table: level 2 is iterative and §3.2 does not say so.** §3.2 presents level 2 as one pass of per-span accept/reject. Accepting **every** suggestion on the reference fixture leaves the script still infeasible (`N`=20, 2.32s/shot against a 1.75s target). It takes two further rounds to pass. Nothing in `ScriptPreflightResponse` or in this plan signals that re-running yields more suggestions — so the honest reading of the current UX is "accept everything, still rejected, no path forward offered."

**Fix:** either return the suggestions transitively (re-split after each proposed mark and keep proposing until the style's band is met, so one response carries the full set), or add a `further_suggestions_available: bool` to `ScriptPreflightResponse` and say so in §3.2. The first is better product for the same amount of code; the second is at least honest about a limitation. Silently requiring the user to guess is neither.

### 13.3 R3 — A2's "gap bounded at ±0.5s" is false, and it fails worst exactly where this plan needs it most — **FIXED (documentation), see §12**

`app/providers/fal_video.py:38` clamps with `max(3, min(15, round(duration)))`. **Any shot shorter than 2.5s therefore asks Kling for 3s**, and the ±0.5s bound A2 rests its whole hold-the-last-frame argument on does not hold. Measured across every shot in `m8_test_project` — the fixture A2 says it measured:

| shot | `duration_s` | requested | real gap |
|---|---|---|---|
| `sc_02_sh_03` | 2.20s | 3 | **−0.80s** |
| `sc_05_sh_02` | 2.30s | 3 | **−0.70s** |
| `sc_03_sh_02`, `sc_04_sh_01` | 4.50s | 4 | +0.50s (the true worst *hold*) |

Two corrections to A2's own numbers, both minor in themselves and both symptomatic:

- The **±0.5s** framing is right for the *hold* direction only. The *trim* direction is unbounded below — up to −2.2s at `retention_fast`'s 0.8s floor.
- *"The 2 exceptions are +0.10s each"* — they are **+0.45s** (`sc_02_sh_01`, dissolve 0.35s) and **+0.10s** (`sc_03_sh_03`, fade 0.0s). The "6 of 8 held tails fall inside their own outgoing dissolve" claim does check out exactly.

⚠ **This is a wrong justification, not a bug** — `build_duration_fit_fragment`'s `trim` branch handles a −2.2s gap correctly, and the emitted stream is still exactly `target_duration_s`, so D5's `xfade` arithmetic is safe. But `app/renderer/motion.py:150-158` repeats the wrong bound as its recorded rationale, and A2's own *"caution: this is a creative decision wearing an arithmetic costume — document the choice or it will be 'fixed' later"* applies to its own arithmetic here.

**The real consequence is economic, and it lands on `retention_fast`.** With shots of 0.8–3.5s, **every** motion shot clamps up to a 3s Kling request; you pay ~50¢ and discard up to 2.2s of the clip. §4.2's decision that *"fast-cut is allowed to lean harder on paid generation"* was taken without this. The style with the highest shot count is the one where paid motion is least economical per second delivered.

**Fix:** none required in `build_duration_fit_fragment`. Correct A2's and `motion.py`'s stated bound to *"−(clamp floor − duration) ≤ gap ≤ +0.5s; unbounded below only because of the 3s API floor"*, and add the cost note to §4.2. If the economics matter, the real lever is making A4's per-project cap style-aware — a `retention_fast` project should cap motion shots far lower than a `documentary_archival` one, because each one is worth less.

### 13.4 R4 — the "0.6s and 1.33s shots" evidence is misattributed, and proves the wrong thing — **FIXED (documentation), see §12**

Cited **three times** (§2.1, §2.5, §4.2) as the load-bearing evidence that lowering `min_shot_duration_s` to 0.8s is safe: *"the fixture's own 0.6s and 1.33s shots prove that path works in production."*

Checked directly against every fixture:

| fixture | shots | min duration | `narration_locked` |
|---|---|---|---|
| `m8_test_project` (**"the fixture"** per this doc's header) | 13 | **2.20s** | not set |
| `hinglish_final_project` | 19 | **0.615s** | **true** |
| `captions_test_project` | 19 | **1.333s** | **true** |
| `hinglish_test_project` | 14 | 1.696s | not set |
| `hindi_test_project` | 11 | 2.246s | not set |

Neither cited shot is in `m8_test_project`. They are in two *other* projects, and — the part that matters — **both of those have `narration_locked: true`**. Those durations exist only *after* narration, where `_validate_planning_time_shot_bounds` is skipped entirely. So they demonstrate that the A26 exemption works, which was never in doubt; they say nothing about whether the Shot Planner can be trusted with a 0.8s floor at planning time, which is the claim they are cited for.

**Fix:** documentation only. Replace the citation in all three places with the argument that actually holds — *"lowering the planning-time floor affects only the planner's pre-narration estimate, because A26 exempts measured durations regardless"* — which §4.2 already states correctly one line away from the bad citation. Delete the fixture claim; it adds no support and it is wrong.

### 13.5 R5 — the three-level mutability model collapsed into one frozen field — **FIXED 2026-08-18 (option 2, split the field — user-confirmed via scenario), see §12**

§2.1's table is explicit that a style binds at levels with **different mutability**: render settings are *"changeable any time; re-render is cheap"*, separately from planner prompts and the constraint bundle, which freeze when planning starts.

In the implementation there is one field and one freeze. The grade reads `timeline.metadata.render_style` (`app/renderer/grading.py:81`), copied from `ProjectModel.render_style` at `create_initial` and never re-read; `POST /{project_id}/style` refuses once a timeline exists (`app/api/projects.py:340`, check at `:379`). **So the grade — the cheapest, most eyes-on, most iterated knob in Tier 1 — cannot be changed at all after planning starts.** The level §2.1 calls freely changeable is in practice the most locked.

`set_render_style`'s docstring documents the divergence honestly and gives a real reason for it (style affects the Shot Planner before any Timeline exists to approve, so "the gate" for style is planning, not approval). That reasoning is sound for the *planner* levels. It was then applied to the render level as well, because they share one field.

⚠ **§2.1 has not been updated, so it still instructs the frontend to *"keep the picker live on the progress screen until approval; read-only afterwards."* A picker built to this plan as written will `400`.**

**Fix — pick one and write it down:**

1. **Accept the collapse.** Rewrite §2.1's table to say all three levels freeze at planning start, and correct the frontend guidance. Cheapest and honest; loses the "re-render in a different grade" capability the plan sold.
2. **Split the field.** `render_style` (frozen at planning) for planner-facing levels, plus a mutable grade-facing field on the Timeline. Restores §2.1's model. `render_style` is already in the render fingerprint via the timeline-document dump, so a mutable grade field inherits cache invalidation for free — genuinely cheap, and it is what makes "iterate on the grade against a real render" possible, which §9 says is where the non-compressible human time goes.

Recommendation: **(2)**, precisely because §9 identifies grade tuning as eyes-on work that does not parallelise. Making the one knob that needs iteration the one knob that cannot be changed post-planning is the wrong trade.

### 13.6 R6 — `documentary_archival` is no longer "today's behaviour, named", and `None` means two different things — **FIXED 2026-08-18 (option 1, `documentary_archival` is the real default — user-confirmed), see §12**

§2.8 defines `documentary_archival` as today's behaviour with a name attached. It now carries a real grade — `eq=contrast=1.05:saturation=0.85:brightness=0.0` — so it changes the picture.

Worse, the `None` sentinel diverges across two modules that each claim "one vocabulary, not two":

| call | result |
|---|---|
| `resolve_constraint_bundle(None)` | falls back via `settings.default_render_style` → **documentary_archival's bundle** |
| `grade_filter_fragment(None)` | **`None` — no grade at all** (`grading.py:81`) |

So `render_style=None` and `render_style="documentary_archival"` produce **identical constraints and different pixels**. §12's Track B entry verified the first half of that ("byte-identical to the flat `settings.*` values") and the grading entry verified the second half in isolation; neither compared them.

**Fix:** make `grade_filter_fragment` resolve `None` through `settings.default_render_style`, exactly as `resolve_constraint_bundle` already does, so one sentinel has one meaning. ⚠ **This changes the output bytes of every existing style-less project** — which the fingerprint will correctly notice, so it is a re-render, not a silent drift. That is the right trade *if* `documentary_archival` is meant to be the default look. If instead "no style" is meant to remain literally today's ungraded picture, then §2.8's claim that `documentary_archival` is today's behaviour is the thing to correct, and `STYLE_GRADES["documentary_archival"]` should be the identity. **Either is defensible; having both at once is not.**

### 13.7 R7 — the pre-flight dead-stop ceiling is being used as the planner's `max_shot_duration_s` — **FIXED 2026-08-18, see §12**

`app/script/styles.py:119-121`:

```python
min_shot_duration_s = band.min_shot_duration_s_override or settings.min_shot_duration_s
max_shot_duration_s = band.max_fragment_duration_s or settings.max_shot_duration_s   # <-- here
max_shots_per_project = band.max_shots_override or settings.max_shots_per_project
```

`max_fragment_duration_s` is a **pre-flight diagnostic** — the §2.5.1 dead-stop ceiling for a single *narration fragment*, derived as `target_shot_duration_s * _DEAD_STOP_CEILING_MULTIPLIER`, where that multiplier is labelled in its own comment as *"a starting point, not a measured constant… no real long fragment has been rendered against this ceiling yet."* It is now also the Shot Planner's **hard validation bound on a shot's duration**. Two different concepts share one number, so tuning a not-yet-calibrated diagnostic (Q5, explicitly still open) silently moves a planning constraint.

The `StylePacingBand` docstring's promise that the two numbers *"can never drift apart for one style"* is what hides this: it describes the tie between the average target and the fragment ceiling, and reads as if it also covers this reuse.

Also: **`x or y` on numerics** — a `0` or `0.0` override falls through to the settings value. Not reachable with today's three styles; a live trap for the fourth, and `stillness` is exactly the style that might legitimately want a `0.0` bound one day.

**Fix:** give `StylePacingBand` an explicit `max_shot_duration_s_override: float | None = None`, set it to `3.5` for `retention_fast`, and stop reading `max_fragment_duration_s` in `resolve_constraint_bundle`. The values do not change today; the coupling does. In the same pass, replace the three `or`s with `if … is not None else`.

### 13.8 R8 — Route 1 shipped without Route 2's speed component, which §2.5 forbids in bold — **OPEN, needs a real ElevenLabs API check (tiny real spend) — confirmation not yet requested**

Verified absent everywhere: no `speed` in `Settings`, none in `NarrationRequest`, and `compute_narration_content_hash` (`app/providers/elevenlabs.py:57`) is still `f"{text}|{voice_id}|{model}|{output_format}"`. The ⚠ *"speed support on the configured ElevenLabs model is unverified — do it before building"* was never done.

§2.1 records narration speed as **decided, in v1**. §2.5 says, in bold: *"⚠ Ship both routes together. Route 1 alone gives a fast-looking video over documentary-paced narration, which reads as mismatched rather than fast — and the punch-ins get blamed when the problem is the voice. Route 2's speed component is what closes that specifically."*

What has shipped is Route 1 in full (punch-in, cuts-only, grade) plus Route 2's *structural* half (finest granularity, lowered floor, higher cap — none of which works today, see R1) and **none of its voice half**. ⚠ **Track D level 3 makes this more pronounced, not less:** it is now the third mechanism for making the cutting faster, while the delivery stays untouched. Every pacing lever built so far acts on the script or the picture; the one that acts on the voice is the one still missing.

**Fix, in order:** (a) 10 minutes checking `speed` on the configured ElevenLabs model, as §2.1 already specifies; (b) `speed` into `compute_narration_content_hash` **in the same commit as the field itself** — a `speed` that reaches the API but not the key silently serves wrong-speed cached audio on the second run, which is exactly the failure §2.1 warned about; (c) `~1.2×` on `retention_fast`'s band. Until (a)–(c) land, `retention_fast` should not be offered to a real user even after R1 is fixed — it will be judged on a mismatch this plan predicted in writing.

### 13.9 R9 — the claim §3.4 retracted is shipping as a user-facing string — **FIXED 2026-08-18, see §12**

`app/script/preflight.py:181-184` emits:

> *"…exceed '{style}''s shot cap of {shot_cap} — planning would have to merge fragments, producing a slower cut than intended, or fail outright"*

§3.4 is an entire section, corrected twice, establishing that **this merge behaviour does not exist**: `max_shots_per_project` is not in `_make_validator` at all, the cap is checked after `run_structured_with_repair` returns and raises `PermanentError` directly, and *"the model is never asked to reduce shot count, so it never quietly complies."* The retracted claim is what users are being shown.

**Fix:** replace with what §3.4 established — *"…exceeds '{style}''s shot cap of {shot_cap}. Planning would fail partway through, after the Director and Scene Planner have already run. Add fewer breaks, or choose a slower style."* One string, and it names the actual fix, which was §3.4's own revised justification for keeping the check at all.

### 13.10 R10 — A6's stated requirement is unmet: the review screen still cannot play a clip — **FIXED 2026-08-18 (endpoint built, not yet e2e-tested against a real DB — deferred per this session's own standing rule), see §12**

§1's A6 opens with *"The review screen must play a clip."* There is no endpoint that streams one. `GET /{project_id}/shots/{shot_id}/asset` (`app/api/projects.py:1703`) detects a video at `:1754` and serves a **cached representative JPEG frame** via `cached_video_frame`.

So the human at the one gate — the gate that, since the 2026-08-16 one-gate redesign, *is* the quality check that replaced the automated constraint pass — approves ~50¢ of generated motion by looking at a single still frame of it. ⚠ **This specifically undermines A8's bake-off**, whose whole question is *"does synthetic motion blend beside a 1936 photograph"* — a motion-perception judgement §12 has already correctly noted twice cannot be made from extracted stills.

**Fix:** a `GET /{project_id}/shots/{shot_id}/clip` streaming the bound `generated_clip.local_path` when it is a video (`FileResponse`, `Cache-Control: no-cache`, matching `/asset`'s own reasoning for that header), 404 when the binding is a still. Small. The `/asset` frame extraction stays as-is — a thumbnail is the right thing for a grid, and the wrong thing for an approval decision.

### 13.11 Smaller items, all verified, none blocking

- **§9's arithmetic does not close.** Per-track figures sum to 40–51 days; the header table says B is *"~20 d (all)"* where Tier 1+2+3 is 13–17; §12's review entry concludes *"~50 rather than ~35"* and 35 appears in neither. The 1.5×-the-estimates recommendation is sound and is independently supported by the docstring standard it cites — but its base number is not in this document.
- **§2.5.1's "fails `max(fragment)` by 4.5×"** measures the 7.9s fragment against the **1.75s average target**; the shipped ceiling is **3.5s**, i.e. 2.3×. Same headline number, two denominators. And `script_preflight_margin_fraction = 0.2` stacks on the 2.0× multiplier, so the real gate is **4.2s — 2.4× the style's own target passes as feasible.** Not wrong, but Q5's calibration should be done against the effective number, not the nominal one.
- **A3a's cost table** quotes ~42¢ for both rows; `$0.084/sec` is the **text-to-video** published price. Image-to-video's own per-second rate was never checked, so the comparison that decided the variant used one side's number for both. The decision itself rests on the style-anchor argument, which is unaffected.
- **The music library is 54 tracks — 6 moods × 3 energies × 3.** §5.1 says in bold: *"⚠ Do not build the full cross-product. 6 moods × 3 energies × 2–3 tracks is 36–54 tracks to source and verify **by ear** — human time that does not compress. Add a small number of energy-specific categories instead."* 54 is the top of exactly that range. Either the caution was consciously overridden — defensible, but not recorded as a decision anywhere — or the cross-product was built by default. Worth one line in §12 stating which, since the reason it was cautioned against (human listening time) is a cost that has now either been paid or been skipped.
- **`bpm` is `null` for all 54 tracks.** §5.2's "BPM as a manifest field — a human types it in, free now, awkward later" was followed structurally: the field exists in `manifest.json`. It is unpopulated, so §5.3's tempo-matching ranking has nothing to rank on. Typing 54 integers by ear now is the cheap moment; after the library is in use it is the awkward one §5.2 warned about.
- **A5's superseded methods are kept unwired** (`_generate_checked_keyframe`, `_generate_checked_image`) — deliberate, and matching the 2026-08-16 image-path precedent, so not a defect. Noting only that there are now two dead constraint-check paths, and a third would be a smell.

### 13.12 What was checked and holds up

Recorded because a review section that lists only faults misrepresents the state of the code.

- **Track A's motion path is correct**, and it is the strongest work in the tracks reviewed. `probe_media`'s Pillow-then-positively-confirm-by-ffprobe rule genuinely preserves GIF flattening (verified against a real animated GIF, not just asserted from the rule). Ken Burns is suppressed on clips at `slideshow.py:174` — a MOTION shot gets no `zoompan` regardless of what `shot.camera` says. Clip audio never reaches the output (`-map [vout]` only, plus `generate_audio: False` at the source). Both fit branches emit exactly `target_duration_s`, so D5's `xfade` offsets are untouched — checked by generating the real fragments:
  - motion, 3.0s clip in a 3.40s shot → `…,fps=30,tpad=stop_mode=clone:stop_duration=0.400,format=yuv420p`
  - motion, 3.0s clip in a 2.20s shot → `…,fps=30,trim=duration=2.200,setpts=PTS-STARTPTS,format=yuv420p`
- **`grading.py`'s fingerprint reasoning is right**, and its test guarding `metadata`'s absence from `_TIMELINE_BOOKKEEPING_FIELDS` is the correct shape — it fails if a future change reopens the gap, rather than restating the assumption.
- **Budget enforcement covers the new video path** — `check_budget` runs before the keyframe (`_generate_keyframe_once`) and again before the Kling submit, and `insert_pending` persists `job_id` before anything else, so the M7 crash-recovery invariant holds through the new endpoint pair.
- **`GET .../generate/video` has no submit side effect** and 404s rather than starting a paid job — the property that makes it safe to poll from a browser.
- **The splitter's tiling is genuinely lossless**, so `check_feasibility`'s `sum(fragment durations)` equals `estimate_duration_s(script)` exactly; the two `D`s cannot drift. An empty script does not crash it either (`split_narration_fragments("")` returns one empty fragment, so the `max()` has something to consume) — checked, because a keystroke-driven endpoint meeting an empty textarea is the obvious way to 500.

### 13.13 Recommended order

1. **R1** — three lines plus the end-to-end test. Do this first and separately, because §3.2 and §12 both currently assert it is already done, which makes it the finding most likely to stay invisible. R2's blocking half closes with it.
2. **R9** — one string. Free, and it is currently telling users something this document proved false.
3. **R7** — decouple the diagnostic from the planning bound before Q5's calibration starts moving `_DEAD_STOP_CEILING_MULTIPLIER`, or that calibration will silently retune planning.
4. **R6** and **R5** — decide what `None` means, and whether the grade is mutable. Both are one-way doors on output bytes, and both get more expensive after the first real project ships in a style.
5. **R8** — the ElevenLabs speed check is 10 minutes and gates whether `retention_fast` is honest to offer. ⚠ `retention_fast` should not reach a real user until R1 and R8 are both closed.
6. **R3, R4, §13.11** — documentation and calibration corrections. No code depends on them, but R3's economics should reach §4.2 before A4's cap is tuned, and R4's bad citation should not be relied on by whoever next touches the floor.
7. **R10** — before A8's bake-off is attempted, not after. Judging motion from a still frame is the one thing that pass exists to avoid.
8. **R2's second half** (transitive suggestions) — product decision, lowest urgency, highest visible improvement to the pre-flight screen.

---

## 14. What remains in this plan — audit against real code, 2026-08-20

> **Why this section exists.** Track C is complete and lives in its own document ([`track_c_long_form_video.md`](track_c_long_form_video.md), 1,556 lines, C0–C8 + frontend contract, three review rounds). With it closed, "what is left in the parent plan" stopped being answerable by reading §12's log top to bottom. **Every status below was verified by probing the code on 2026-08-20, not by trusting a marker.**

### 14.1 The short answer

**Six things remain. One is blocked on you, one is a decision, four are unbuilt work.**

| # | item | § | status probe | effort |
|---|---|---|---|---|
| **1** | **Narration speed (Route 2's voice half)** | §2.1, §2.5, §13.8 | ⚠ `speed` **absent** from `Settings`, `NarrationRequest`, and `compute_narration_content_hash` | ~0.5 d **after** a 10-min live check |
| **2** | **Sound effects layer** | §5.5 | ⚠ `app/renderer/sfx.py` **absent** — nothing built | 3–4 d + curation |
| **3** | **Split-screen (`SPLIT_FRAME`)** | §2.6 Tier 2 | correctly still a documented no-op in `ken_burns.py:87` | 3–5 d |
| **4** | **2.5D parallax** | §2.7 Tier 3 | ⚠ no provider module exists | 3–4 d + Q10 |
| **5** | **Per-style music gains** | §5.2 | ⚠ **0** refs to `music_bed_gain_db` in `styles.py` | ~0.5 d |
| **6** | **BPM + tempo-fit ranking** | §5.2, §5.3 | ⚠ **9 of 54** tracks have `bpm`; **0** refs to `bpm` in `music_ranking.py` | ~0.5 d + ear time |

**Plus two carried-over decisions:** A8's bake-off verdict (human viewing) and R2's second half (iterative punctuation suggestions — a product call).

### 14.2 Item 1 — narration speed is the only thing gating a shipped style

⚠ **This is the most consequential remaining item and it is not a coding problem.**

§2.5 says, in bold: *"Ship both routes together. Route 1 alone gives a fast-looking video over documentary-paced narration, which reads as mismatched rather than fast — and the punch-ins get blamed when the problem is the voice."*

**What shipped is Route 1 in full** (punch-in, cuts-only, grade) **plus Route 2's structural half** (finest granularity, lowered floor, higher cap — all now working after §13.1's R1 fix) **and none of its voice half.** Probed 2026-08-20: no `speed` in `Settings`, none in `NarrationRequest`, and `compute_narration_content_hash` is still the four-value key.

⚠ **§13.13's own rule stands unmet:** *"`retention_fast` should not reach a real user until R1 and R8 are both closed."* R1 is closed. **R8 is not**, so by this document's own standard `retention_fast` is not yet honest to offer.

**Three steps, in order, and the first needs you:**

1. ⚠ **A live schema/behaviour check on `eleven_multilingual_v2` for `speed`** — ~10 minutes and a **tiny real spend** against the configured ElevenLabs account. **Not yet requested or approved**, which is the only reason this is still open. Track C's §11 Q4 established the target precisely: `ElevenLabsNarrationProvider` currently sends only `{"text", "model_id"}`, so `speed` is a change against that specific model's schema.
2. **`speed` into `compute_narration_content_hash` in the same commit as the field itself.** §2.1 flagged this and it is the real hazard: a `speed` that reaches the API but not the cache key **silently serves wrong-speed audio on the second run**. Track C's §3.3 disk-fallback makes this worse, not better — a wrong-speed mp3 plus sidecar on disk would now be *restored* rather than re-synthesised.
3. **`~1.2×` on `retention_fast`'s band**, with the ⚠ practical ceiling §2.1 records (~1.15–1.25×; Hinglish likely degrades earlier and differently — `hinglish_final_project` is the fixture).

⚠ **One quota consequence Track C measured that §2.1 could not have known:** ElevenLabs Starter is **60,000 characters/month** for Multilingual v2, a 10-minute video is ~8,640, and `speed` joining the hash **re-synthesises every scene**. So a single speed change on a long project costs ~14% of the monthly allowance. **Decide speed before synthesising a long project, not after** — see Track C §3.3.

### 14.3 Item 2 — SFX is the largest genuinely unbuilt feature in this plan

`app/renderer/sfx.py` does not exist; nothing in §5.5 is built. The design in §5.5 still holds and needs no revision:

- **Placement follows D6/21.2 exactly** — choosing the palette is creative → `sfx_plan` in the Timeline; placing and mixing is deterministic → the renderer, driven by events already there (`camera` punch-ins, `text_card`, transitions). No new per-SFX creative decisions.
- **Source is the same Openverse provider, same licence gate, different query** — §5.5's own irony (Freesound "skews to sound effects" was a complaint about music search; for SFX it is the point).

⚠ **§5.5's cost warning is now better evidenced than when written.** It says *"the mixing is the real cost… a materially larger filter graph that must stay bit-exact for I5. This sounds small and is not."* Track C's C7 built exactly this shape one axis over — `assemble_act_bed` loops, trims and concats per-act beds and rejoins the existing duck/mux — and it landed at 1–1.5 d for a *sequential, non-overlapping* set of segments. **SFX is N short overlays at computed offsets, overlapping narration and a ducked bed**, which is materially harder than concatenation. The 3–4 d estimate looks right, and Track C's music work is the closest available precedent to copy.

⚠ **Two Track C findings that SFX must not repeat:**
- Every new render input enters `compute_render_fingerprint` (this document's own §7 lesson, hit four times: music gain → captions → watermark → grade, then Track C's R-C6 in the other direction). An `sfx_plan` and its per-clip content hashes are render inputs.
- Track C's R-C7 found `run_ffmpeg` concurrency multiplying through nested gathers. SFX mixing adds filter-graph size, not process count — but the module-level ffmpeg semaphore now exists and SFX should route through `run_ffmpeg` rather than spawning directly.

### 14.4 Items 3–4 — the two Tier 2/3 pipeline changes, both correctly still absent

**Split-screen.** `ken_burns.py:87` still returns `None` for `SPLIT_FRAME` with the honest reason recorded in its docstring: *"a real split-screen composite needs a SECOND source image… building that is a materially different pipeline change, not a `zoompan` expression."* ⚠ **§7's "scope honesty" caution is being kept** — declared in the schema, documented as a gap, not mis-implemented. It reaches into the Shot Planner and asset resolution (two assets per shot), which is why it is 3–5 d and not a filter.

**2.5D parallax.** No provider module. §2.7's architecture is unchanged and is the right one: **treat parallax as a provider, not a filter** — still in, clip out, cached by content hash like `generated_clip`, so the renderer only ever sees an mp4 and I5 holds on the cached artifact. ⚠ Requires Track A's A1, which is built — so parallax is now unblocked technically and blocked only on **Q10** (does it justify a GPU dependency), the one item in this plan that changes the deployment story.

### 14.5 Items 5–6 — the music library's two unfinished halves

The library itself landed (54 tracks, `LocalMusicProvider`, `MUSIC_PROVIDER=local`) and Track C's C7 added per-act selection on top. Two §5.2/§5.3 items did not land:

**Per-style bed/duck gains (~0.5 d).** Probed: **0** references to `music_bed_gain_db` in `styles.py`. §5.2 calls this *"genuinely differentiating — archival wants the bed present, fast-cut wants it driving and barely ducked, stillness wants it near-absent."* ⚠ Both gains are already in `compute_render_fingerprint` (R2's own fix), so making them style-derived needs no new fingerprint work — it is a resolver change, and `resolve_constraint_bundle` is now the established place for exactly this.

**BPM and tempo-fit ranking.** Probed: **9 of 54** tracks carry a `bpm`; `music_ranking.py` has **0** references to it. §5.2 said *"a human types it in — free now, awkward later"*; §12's music entry recorded that BPM was only filled where a source published it, deliberately not fabricated. ⚠ **That was the right call and it means §5.3's tempo-fit ranking has almost nothing to rank on** — 45 tracks would score as unknown. **Populating 45 integers by ear is the cheap moment; it does not get cheaper.** And §5.3's insight is unaffected and still good: cuts cannot land on beats (D1 makes narration the clock), so **rank tracks by how well their BPM fits the measured shot pacing** — a ranking criterion, not a timing change.

### 14.6 The two carried-over decisions

**A8's bake-off.** §12 records the collage bug found *during* A8's bake-off, so it started. ⚠ **No verdict is recorded**, and §9 is explicit that this needs a human comparing outputs and does not compress. It is the question *"does synthetic motion blend beside a 1936 photograph"* — and Track C's R10 fix (`GET /shots/{id}/clip`, streaming real clip bytes) is what finally makes it answerable from the UI rather than from extracted stills.

**R2's second half.** §13.2's finding that level 2's punctuation suggestions are iterative but presented as one-shot — accepting all 7 leaves the reference fixture still infeasible; it takes two more rounds. Deliberately left as the lowest-urgency item. Still open, still a product call (return suggestions transitively, or add a `further_suggestions_available` flag and say so in §3.2).

### 14.7 What is done, so the remaining list can be trusted

| track | state |
|---|---|
| **A** — motion clip input | A1/A2/A3/A5/A6 built; A4's prompt fix + per-project video cap built; A7 (Pexels video rung) built. **Only A8's verdict outstanding.** |
| **B** — style catalogue | Tier 1 (grade, punch-in, `retention_fast` end-to-end) and Tier 2 (extra transitions, text cards) built. **Split-screen and Tier 3 outstanding; per-style gains outstanding.** |
| **C** — long-form | ✅ **complete and closed 2026-08-20** — 658 tests pass in 17m51s, R-C1…R-C10 all closed — see [`track_c_long_form_video.md`](track_c_long_form_video.md). C0–C8, frontend contract §13, and three review rounds (§14/§15) with nine findings raised and fixed. |
| **D** — script pre-flight | Levels 1–2 and level 3 (rewrite) all built. **Only R2's second half outstanding.** |
| **Music** | Library + `LocalMusicProvider` + per-act beds built. **Per-style gains and BPM/tempo-fit outstanding. SFX entirely unbuilt.** |
| **§13 review** | R1–R7, R9, R10 fixed and verified. **R8 (speed) open — see §14.2.** |

⚠ **Open questions still genuinely open:** **Q5** (pacing bands per style — blocked on calibration data, and Track C's `_DEAD_STOP_CEILING_MULTIPLIER` is still the uncalibrated 2.0), **Q8** (Hinglish chars/sec constant), **Q10** (parallax GPU dependency). Q1–Q4, Q6, Q7, Q9 are closed.

### 14.8 Suggested order for the remainder

1. **Item 1's live speed check** — ⚠ needs your approval for a tiny spend, gates a shipped style, and is 10 minutes.
2. **Items 5 and 6** — ~1 d together, and both are cheapest now: per-style gains reuse the existing resolver, and 45 BPM values by ear only get more awkward once the library is in use.
3. **A8's verdict** — human viewing, now actually possible via `GET /shots/{id}/clip`.
4. **SFX** — the largest remaining build, and §5.5's own advice is to do it *after* fast-cut ships, which it has. Copy C7's `assemble_act_bed` shape.
5. **Split-screen**, then **parallax** behind Q10.
6. **R2's second half** whenever the pre-flight screen gets attention.
