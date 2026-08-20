# Motion, New Styles, Script Pre-flight, and Long-Form Video — Implementation Plan

> **Status:** Originally plan-only (2026-08-17). Since then, built and verified against real ffmpeg/real Postgres/real live APIs: Track D (script pre-flight, all levels except the phrasing-rewrite L3), Track B Tier 1–2 (grade, extra transitions, text cards, punch-in), and Track A's A1/A2/A3/A4/A5/A6/A7 (motion clip input, duration fitting, the video path's one-gate model, the on-demand video endpoint pair, the Pexels video rung, and video-vs-image planner calibration). **A8 (the bake-off) was attempted 2026-08-18 with real spend (~$1.86) and found a real, previously-unknown collage bug affecting every project with a rich `visual_style` — fixed and verified, but A8's own question ("does synthetic motion blend next to real archival photography") is still open**, by the user's own choice to stop before re-running the video half. **§11 step 5 (orphan-run fix) and step 6 (music taxonomy + a real 54-track curated library, §5.1) are also now built and verified**, 2026-08-18 — see §12 for both. See §12 for the full chronological log; unmarked sections below are still design-only. ✅ **2026-08-20: Track C is COMPLETE** and moved to [`track_c_long_form_video.md`](track_c_long_form_video.md). ✅ **R8 (narration speed) closed 2026-08-20.** ✅ **Leftover items 5, 6, 2, and 3 (gains, BPM, SFX + 9-clip library, split-screen) closed 2026-08-20.** ⚠ **One leftover build remains — see §14.8:** R2's second half. **Split-screen closed 2026-08-20.** **Parallax is parked on Q10.** **A8 is last.**
> **Scope:** four tracks — **A** (motion clip input), **B** (style catalogue), **C** (long-form), **D** (script pre-flight). A is the keystone for the motion half of B; D is independent and could ship first.
> **Related:** [`13_Implementation_Guide.md`](../13_Implementation_Guide.md) §M7/M8/M9 and its Backlog, [`14_Captions_Plan.md`](../14_Captions_Plan.md), [`watermark_implementation_plan.md`](watermark_implementation_plan.md).
> **Fixture:** project `58f0a5e6-008d-468e-862a-e365e463878e` / `backend/tests/fixtures/m8_test_project.json` — real Fischer-Tropsch timeline, 13 shots. Reuse it; do not plan a fresh one.
> ⚠ **Read §13 before trusting any "BUILT" marker in this document.** A code-vs-plan review on 2026-08-18 found ten open discrepancies between what §12 records as built and what the code does, two of them blocking — including that `retention_fast` could not complete a planning run. **Update, 2026-08-20: 9 of 10 items are fixed and verified (R1–R10 except R2's second half). R8 closed the same day as Track C.** Only R2's second half (a lowest-priority product decision) remains open. See §13's own status line for the current per-item state.

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
- ✅ **Speed support on the configured ElevenLabs model is verified, 2026-08-20.** Live schema check against `/with-timestamps` on `eleven_multilingual_v2`: `voice_settings.speed` accepted, 1.2 in range, alignment timestamps scale. See §12.
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

### 5.5 Sound effects — **BUILT 2026-08-20, see §12**

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

**Q5. Target pacing bands per style.** **ANSWERED 2026-08-20 (§14.9) by watching real narrated renders — `_DEAD_STOP_CEILING_MULTIPLIER = 2.0` is VALIDATED, keep it.** The perceptual dead-stop boundary sits between 3.34 s (fine) and 4.97 s (stalls); the shipped 3.5 s ceiling lands correctly between them. ⚠ And **zero** fragments of the real script fall in 3.5–5.0 s, so narrowing further unlocks nothing — the 5 rejected fragments are 5.36–7.55 s and genuinely stall, meaning **the pre-flight's rejections are correct, not false positives.**

**Q6. Preset seeds the Director, or overrides it?** **ANSWERED 2026-08-20 (§14.9) — and the conflict this question named does not exist: `colour_palette` is written by the Director and read by NOTHING.** The real collision is `camera_language`, which lands in the same Shot Planner request as the style fragment with no stated precedence. Decision: suppress the Director's camera line when a style supplies camera instructions. *(Original text: cheapest honest answer is "seeds", with the preset winning on conflict.

**Q7. What happens if a rewrite fails code validation?** **DECIDED 2026-08-20 (§14.9): ONE attempt only — never a retry budget.** The backstops are fixed and mechanical, so more attempts select for a rewrite that EVADES them rather than a better one — a third attempt can keep every number and name and still say “converted synthetic fuel into coal”. Current behaviour (return the attempted text plus the reasons, persist nothing) is correct and is now recorded so nobody “improves” it into a loop. ⚠ **And a NEW finding from the same pass: the pre-flight has no minimum-length check** — all four blocking checks guard “too long / too many”, so a 400-character script passes everything and silently yields a ~27-second video. Decision: add a minimum-length **warning** (never a block, per §3.1's own arithmetic-vs-taste split).

**Q8. Hinglish calibration** — **ANSWERED 2026-08-20 (§14.9) against the live API: one constant DOES hold** (English 15.1, Hinglish 14.0, pure Hindi 14.9 chars/sec; `EN=14.4` within 5% of all three). ⚠ **`HI=12.9` is 15.5% too slow and causes false rejections — delete it.** And the real finding: **voice swings chars/sec by 36% versus ~8% for language**, so the config models the small variable and ignores the large one. *(Original text: a single chars/sec constant may not hold for a script mixing Devanagari and Latin.* `hinglish_final_project` is the fixture.

**Q9. Does the diagnosis screen re-measure live as the user edits?** **DECIDED 2026-08-17** — yes, via the stateless `POST /{project_id}/script/preflight` (§3.5.3), which persists nothing, so every keystroke is a free re-check.

**Q10. Does the parallax provider justify a GPU dependency?** **ANSWERED 2026-08-20 (§14.9) — tested on real archival photos, verdict: BUILD IT.** The effect works and does **not** break up on 1936 reconnaissance film (user verdict on 5 animated photos) — which was the whole risk, since depth models are trained on modern photography. ⚠ **And the question was framed wrongly: it needs no GPU in the render path.** §2.7's own "provider, not filter" design means the renderer only opens a finished mp4, so parallax generation can run OUTSIDE the render container entirely — the real question is *where the provider runs*, not whether the render service needs a GPU. Three maintenance findings (release crashes on first use; animation off by default; grayscale input crashes — all cheap to fix at the provider boundary) and a six-step build plan are in §14.9.

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
- **R8** (ElevenLabs speed support) — ✅ **closed 2026-08-20**, see the matching §12 entry. Live-checked on the real `/with-timestamps` endpoint; `speed` is now on `NarrationRequest`, in `compute_narration_content_hash`, and `retention_fast` synthesises at 1.2×.

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

### 2026-08-20 — R8 closed: narration speed, live-checked then wired

Parent plan §2.1 / §13.8 / §14.2. Three steps, in the order §14.2 required, one commit.

**Live schema/behaviour check** against the configured ElevenLabs account, `eleven_multilingual_v2`, `POST /v1/text-to-speech/{voice_id}/with-timestamps` — the endpoint this codebase actually uses, not the convert docs. One 57-character English sentence, three calls (~171 billed characters):

| body | HTTP | alignment chars | spoken duration |
|---|---|---|---|
| `{text, model_id}` (today's production) | 200 | 57 | 3.204 s |
| `voice_settings.speed = 1.0` | 200 | 57 | 3.344 s |
| `voice_settings.speed = 1.2` | 200 | 57 | 2.554 s |

`speed` is accepted under `voice_settings`, not top-level. 1.2 is in range. Alignment stays character-level and scales with speed (D2 captions keep working). 1.0/1.2 duration ratio was 1.31, not a time-stretch 1.20 — ElevenLabs treats speed as a speaking-rate hint. Omitting `voice_settings` vs sending `speed: 1.0` is the same request intent; TTS non-determinism accounts for the 3.204 vs 3.344 gap. Probe audio is in `tmp/r8-speed-probe/` (gitignored).

**Wiring, same change as the field itself:**

- `NarrationRequest.speed` (default 1.0). `ElevenLabsNarrationProvider` sends `voice_settings: {speed}` only when the canonical value is not 1.0, so `documentary_archival` / `stillness` bodies stay byte-identical to pre-R8.
- `compute_narration_content_hash` includes speed when it is not 1.0. Default 1.0 is omitted from the digest so every existing four-value cache row remains a hit at the API default. A 1.2 request cannot reuse 1.0 audio — the failure §2.1 named, and Track C's disk-fallback would have made worse.
- Speed is style-owned, not a global Settings knob: `StylePacingBand.narration_speed`, `resolve_narration_speed`, 1.2 on `retention_fast`, 1.0 everywhere else. `NarrationStep` and `RenderStep` resolve from `timeline.metadata.render_style` so the mux lookup cannot drift from the write.
- Clamped to the live-checked 0.7–1.2 band. `FakeNarrationProvider` scales its alignment rate so DRY_RUN `retention_fast` is actually faster.

49 related tests green (`test_elevenlabs`, `test_styles`, narration persistence/step/voice-retry, render mux).

**`retention_fast` is now honest to offer** by §13.13's own rule (R1 and R8 both closed). Hinglish quality at 1.2× was not part of this probe — `hinglish_final_project` is still the fixture if a listening pass is wanted.

### 2026-08-20 — leftover item 5 closed: per-style music bed/duck gains

Parent plan §5.2 / §14.5. One resolver, same shape as `resolve_narration_speed` — **not** stuffed into `ConstraintBundle`, which is planning bounds (R7's lesson: do not share one field across two jobs).

`StylePacingBand.music_bed_gain_db` / `music_duck_gain_db` default to `None` (use the measured `settings` mix of −14 / −20). `resolve_music_gains(style)` uses `is not None`, so `0.0` is unity gain, not "unset." `RenderStep` resolves once and passes the same pair into the fingerprint and `mux_music`, so they cannot drift (R2).

| style | bed | duck | vs archival |
|---|---|---|---|
| `documentary_archival` / unset | −14 | −20 | measured mix, unchanged |
| `retention_fast` | −10 | −14 | louder, 4 dB of duck instead of 6 — "driving, barely ducked" |
| `stillness` | −22 | −28 | 8 dB quieter — "near-absent" |

The fast/stillness numbers are **offsets from the measured archival mix**, not a new listening pass. A later listen can retune the two overrides without touching the fingerprint machinery.

46 related tests green (`test_styles`, `test_fingerprint`).

### 2026-08-20 — leftover item 6 closed: BPM sourced, not invented; tempo-fit ranking

Parent plan §5.2 / §5.3. **Did not invent 45 integers.** Looked up published tempos (Incompetech page `Tempo:`, ID3 `TBP`/`TBPM` on the files, Scott Holmes' own track page). Pixabay HTML does not publish BPM in a crawlable field; FMA drones have none; Incompetech lists Sad Trio as **0 bpm** (no pulse) so it stays `null`.

**18 of 54** now have `bpm` (was 9). The other 36 stay `null` honestly. Ranking treats unknown as the middle band: a drone with no number still beats a published-*wrong* march, and still loses to a published-*fit* bed.

`target_bpm = 240 / mean_shot_duration_s` (4-beat bar; 1.75 s → 137). `rank_music_candidates` is still lexicographic: duration floor, then tempo band (±20% of target), then term-overlap, then `source_id`. `SelectMusicStep` passes per-act (or whole-timeline) mean shot duration. Openverse/Pixabay candidates with no `bpm` keep working — the field defaults to `None`.

19 related tests green (`test_music_ranking`, `test_local_music`, `test_select_music`, `test_music_library_integrity`).

### 2026-08-20 — leftover item 2 closed: SFX layer + a 9-clip local library

Parent plan §5.5. D6 split as written: `SfxPlan` on the Timeline is the palette; `derive_sfx_events` places whooshes on punch-in snaps (same frame offsets as `ken_burns.punch_in_frame_offsets`), stingers on text cards, transition hits on non-cut overlaps; `mux_sfx` amixes delayed overlays through `run_ffmpeg` (R-C7). Fingerprint hashes clip content hashes + `sfx_gain_db` (R2 / §7). Missing clips skip those events, never fail the run. `sfx_plan is None` (every pre-existing Timeline) is a no-op so render-only of old projects is not blocked.

**Library, downloaded live from Openverse (Freesound), not invented:** 3 kinds × 3 short clips, CC0/CC-BY, `ffprobe`-measured durations, at `backend/storage/sfx_library/` with `LocalSfxProvider` as the default (`SFX_PROVIDER=local`; `openverse` still selectable). Ranking prefers clips ≤ 4 s. DRY_RUN uses `FakeMusicProvider` and skips the mux, same as music.

77 related tests green (events, ranking, local provider, fingerprint, mux, library integrity, pipeline names). **Stopped here for review.** Next leftover is split-screen. A8 remains last. Parallax remains parked on Q10.

### 2026-08-20 — leftover item 3 closed: split-screen (`SPLIT_FRAME`)

Parent plan §2.6. The schema already promised it; `ken_burns.py` correctly still returns `None` (a split is not a `zoompan`). The pipeline change is the second still.

**D6 split as written.** Creative: Shot Planner writes `prompt` (top) and `secondary_prompt` (bottom) when movement is `split_frame`; Asset Planner emits a matching `secondary_asset_plans` entry (same `shot_id`, stills only). Deterministic: `split_screen.py` letterboxes each still into half the 9:16 frame and `vstack`s them; `tpad` then holds duration the same way a static shot does. Xfade still sees one stream per shot — the extra input lives inside the per-shot encoder (C3 two-pass), so Track C's argv-length concern does not apply to the run graph.

**Layout is top/bottom, not left/right.** 9:16 side-by-side would be two ~540×1920 strips. Top = primary, bottom = secondary.

**Missing second still degrades to the pre-split static path**, never a fake split of one photograph. Motion on either panel is the same degrade (v1 is stills). Generation of a missing bottom panel still runs if the generation pass reaches the shot; a found top + missing bottom does not fail the run.

**I5.** Both content hashes go into `compute_render_fingerprint` (sorted list) and `compute_shot_stream_fingerprint` / `compute_run_fingerprint` (dedicated `secondary_*` field, empty string when absent). Swapping the bottom panel misses the shot-stream cache. A20/A25 treat `secondary_prompt` / `secondary_asset_plan` as acquisition fields, same as the primary pair.

**Binding.** One row per shot still. `secondary_asset_id` / `secondary_clip_id` on `shot_binding` (migration `b7e4c2a91d08`). Human override of the bottom panel is not in this slice — override still replaces the primary only.

**Known residuals, not closed here:** cost estimate is still per-shot (two generates still hit the live cap); no gutter; no side-by-side layout toggle; human override of the bottom panel; Q6/Q7's three remaining code changes; R15's short-stinger curation.

83 related tests green (filter arithmetic, fingerprint, shot/asset planner, real ffmpeg composite + degrade). Timeline-service and generate-timeline regressions also green. **Stopped here for review.** Next leftover is R2's second half. A8 last. Parallax parked on Q10.

⚠ **Reviewed — see [§16](#16-code-vs-plan-review-of-split-screen-leftover-item-3-2026-08-20). Five findings (R16–R20), none of them one of the five residuals this entry already disclosed. All five fixed 2026-08-20 — answers sit under each finding in §16.**

---

## 13. Code-vs-plan review, 2026-08-18 — where the code does not match this document, and the fixes

> **Method.** Read this plan in full, then verified its claims against the actual code and the real fixture files rather than against §12's own log. Every number below was produced by *running* the real functions (`check_feasibility`, `suggest_breaks`, `split_narration_fragments`, `build_duration_fit_fragment`, `grade_filter_fragment`, and the real `_motion_filter`/`_ken_burns_filter`/`_normalize_filter`) or read directly out of the fixture JSON — none is inferred from reading code. Where a finding is a wrong *justification* rather than a wrong *behaviour*, it says so.
>
> ⚠ **Status, updated 2026-08-20: R1 (both blocking items, which auto-closes R2's first half), R3, R4, R5, R6, R7, R8, R9, and R10 are all FIXED and verified (see §12's matching entry for each) — only R2's second half (transitive suggestions, a product decision, explicitly lowest urgency) remains OPEN.** This section remains the record of what was found; §12 records what was done about it.
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

### 13.8 R8 — Route 1 shipped without Route 2's speed component, which §2.5 forbids in bold — **FIXED 2026-08-20, see §12**

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
5. **R8** — ✅ closed 2026-08-20. `retention_fast` is now honest to offer (R1 and R8 both closed).
6. **R3, R4, §13.11** — documentation and calibration corrections. No code depends on them, but R3's economics should reach §4.2 before A4's cap is tuned, and R4's bad citation should not be relied on by whoever next touches the floor.
7. **R10** — before A8's bake-off is attempted, not after. Judging motion from a still frame is the one thing that pass exists to avoid.
8. **R2's second half** (transitive suggestions) — product decision, lowest urgency, highest visible improvement to the pre-flight screen.

---

## 14. What remains in this plan — audit against real code, 2026-08-20

> **Why this section exists.** Track C is complete and lives in its own document ([`track_c_long_form_video.md`](track_c_long_form_video.md), 1,556 lines, C0–C8 + frontend contract, three review rounds). With it closed, "what is left in the parent plan" stopped being answerable by reading §12's log top to bottom. **Every status below was verified by probing the code on 2026-08-20, not by trusting a marker.**
>
> **Standing process (2026-08-20):** implement **one leftover item**, record what landed and why in §12, update this section's status, **then stop for review**. Do not start the next leftover until asked. Do not commit unless asked.

### 14.1 The short answer

**One leftover build remains (R2's second half), plus A8 last.** Items 1, 2, 3, 5 and 6 closed 2026-08-20. Parallax is parked on Q10.

| # | item | § | status probe | effort |
|---|---|---|---|---|
| **1** | **Narration speed (Route 2's voice half)** | §2.1, §2.5, §13.8 | ✅ **closed 2026-08-20** — live-checked, hashed, 1.2× on `retention_fast` | done |
| **2** | **Sound effects layer** | §5.5 | ✅ **closed 2026-08-20** — `sfx.py` + 9-clip Openverse library + `SelectSfxStep` | done |
| **3** | **Split-screen (`SPLIT_FRAME`)** | §2.6 Tier 2 | ✅ **closed 2026-08-20** — two stills, top/bottom `vstack`, second `AssetPlan` | done |
| **4** | **2.5D parallax** | §2.7 Tier 3 | ⚠ no provider module exists | 3–4 d + Q10 |
| **5** | **Per-style music gains** | §5.2 | ✅ **closed 2026-08-20** — `resolve_music_gains`, −10/−14 fast, −22/−28 stillness | done |
| **6** | **BPM + tempo-fit ranking** | §5.2, §5.3 | ✅ **closed 2026-08-20** — 18/54 sourced BPM; ranking uses ±20% band; 36 stay null | done |

**Plus two carried-over decisions:** A8's bake-off verdict (human viewing) and R2's second half (iterative punctuation suggestions — a product call).

⚠ **All four items closed on 2026-08-20 were then reviewed against the code — see [§15](#15-code-vs-plan-review-of-the-four-items-closed-2026-08-20-r8-sfx-music-gains-bpm). Five findings (R11–R15), none of which reopened an item's design. All five fixed 2026-08-20 — answers sit under each finding in §15.**

### 14.2 Item 1 — narration speed is the only thing gating a shipped style — ✅ **CLOSED 2026-08-20**

§2.5 said, in bold: *"Ship both routes together. Route 1 alone gives a fast-looking video over documentary-paced narration, which reads as mismatched rather than fast — and the punch-ins get blamed when the problem is the voice."*

**What is now shipped is Route 1 in full** (punch-in, cuts-only, grade) **plus Route 2's structural half** (finest granularity, lowered floor, higher cap — R1) **and its voice half** (R8). Live-checked 2026-08-20 against `eleven_multilingual_v2` `/with-timestamps`: `voice_settings.speed` is accepted, 1.2 is in range, alignment timestamps scale. `NarrationRequest.speed` defaults to 1.0; `compute_narration_content_hash` includes speed when it is not 1.0 (so pre-R8 rows remain hits); `retention_fast` synthesises at 1.2× via `StylePacingBand.narration_speed`. See §12's 2026-08-20 entry.

⚠ **§13.13's own rule is now met:** R1 and R8 are both closed, so `retention_fast` is honest to offer. Hinglish at 1.2× was not part of the schema probe — still a listening pass on `hinglish_final_project` if wanted, not a blocker.

⚠ **Quota consequence still stands:** ElevenLabs Starter is **60,000 characters/month** for Multilingual v2, a 10-minute video is ~8,640, and a speed change **re-synthesises every scene** (~14% of the monthly allowance). **Decide speed before synthesising a long project, not after** — see Track C §3.3. Default 1.0 does not bust existing cache.

### 14.3 Item 2 — SFX is the largest genuinely unbuilt feature in this plan — ✅ **CLOSED 2026-08-20**

`app/renderer/sfx.py` exists; `SelectSfxStep` is in `DEFAULT_PIPELINE`; a 9-clip local library was downloaded from Openverse. The design in §5.5 held:

- **Placement follows D6/21.2 exactly** — choosing the palette is creative → `sfx_plan` in the Timeline; placing and mixing is deterministic → the renderer, driven by events already there (`camera` punch-ins, `text_card`, transitions). No new per-SFX creative decisions.
- **Source is the same Openverse provider, same licence gate, different query** — §5.5's own irony (Freesound "skews to sound effects" was a complaint about music search; for SFX it is the point).

⚠ **§5.5's cost warning is now better evidenced than when written.** It says *"the mixing is the real cost… a materially larger filter graph that must stay bit-exact for I5. This sounds small and is not."* Track C's C7 built exactly this shape one axis over — `assemble_act_bed` loops, trims and concats per-act beds and rejoins the existing duck/mux — and it landed at 1–1.5 d for a *sequential, non-overlapping* set of segments. **SFX is N short overlays at computed offsets, overlapping narration and a ducked bed**, which is materially harder than concatenation. The 3–4 d estimate looks right, and Track C's music work is the closest available precedent to copy.

⚠ **Two Track C findings that SFX must not repeat:**
- Every new render input enters `compute_render_fingerprint` (this document's own §7 lesson, hit four times: music gain → captions → watermark → grade, then Track C's R-C6 in the other direction). An `sfx_plan` and its per-clip content hashes are render inputs.
- Track C's R-C7 found `run_ffmpeg` concurrency multiplying through nested gathers. SFX mixing adds filter-graph size, not process count — but the module-level ffmpeg semaphore now exists and SFX should route through `run_ffmpeg` rather than spawning directly.

### 14.4 Items 3–4 — the two Tier 2/3 pipeline changes, both correctly still absent

**Split-screen — ✅ closed 2026-08-20.** `ken_burns.py` still returns `None` for `SPLIT_FRAME` (correct: not a `zoompan`). The second still is `Shot.secondary_prompt` / `secondary_asset_plan`, bound on `ShotBinding.secondary_asset_id`, composited in `split_screen.py` as a 9:16 top/bottom `vstack`. Missing second still is the old static path. See §12.

**2.5D parallax.** No provider module. §2.7's architecture is unchanged and is the right one: **treat parallax as a provider, not a filter** — still in, clip out, cached by content hash like `generated_clip`, so the renderer only ever sees an mp4 and I5 holds on the cached artifact. ⚠ Requires Track A's A1, which is built — so parallax is now unblocked technically and blocked only on **Q10** (does it justify a GPU dependency), the one item in this plan that changes the deployment story.

### 14.5 Items 5–6 — the music library's two unfinished halves

The library itself landed (54 tracks, `LocalMusicProvider`, `MUSIC_PROVIDER=local`) and Track C's C7 added per-act selection on top. Two §5.2/§5.3 items did not land:

**Per-style bed/duck gains — ✅ closed 2026-08-20.** `resolve_music_gains` on `StylePacingBand`, not `ConstraintBundle` (planning bounds stay planning bounds). Archival keeps the measured −14/−20; `retention_fast` −10/−14; `stillness` −22/−28. Fingerprint and mux share one resolved pair. See §12.

**BPM and tempo-fit ranking — ✅ closed 2026-08-20.** 18 of 54 tracks now carry a published `bpm`; the other 36 stay `null` (Pixabay/FMA did not publish a number; Sad Trio is Incompetech `0 bpm`). Ranking: duration floor, then ±20% of `240 / mean_shot_duration_s`, then term-overlap. Unknown sits between fit and known-mismatch. See §12.

### 14.6 The two carried-over decisions

**A8's bake-off.** §12 records the collage bug found *during* A8's bake-off, so it started. ⚠ **No verdict is recorded**, and §9 is explicit that this needs a human comparing outputs and does not compress. It is the question *"does synthetic motion blend beside a 1936 photograph"* — and Track C's R10 fix (`GET /shots/{id}/clip`, streaming real clip bytes) is what finally makes it answerable from the UI rather than from extracted stills. **Moved to last in §14.8** (user, 2026-08-20): regenerate the 3 Kling clips (~$1.50) only after the remaining builds.

**R2's second half.** §13.2's finding that level 2's punctuation suggestions are iterative but presented as one-shot — accepting all 7 leaves the reference fixture still infeasible; it takes two more rounds. Deliberately left as the lowest-urgency item. Still open, still a product call (return suggestions transitively, or add a `further_suggestions_available` flag and say so in §3.2).

### 14.7 What is done, so the remaining list can be trusted

| track | state |
|---|---|
| **A** — motion clip input | A1/A2/A3/A5/A6 built; A4's prompt fix + per-project video cap built; A7 (Pexels video rung) built. **Only A8's verdict outstanding.** |
| **B** — style catalogue | Tier 1 (grade, punch-in, `retention_fast` end-to-end including narration speed) and Tier 2 (extra transitions, text cards, **split-screen closed 2026-08-20**) built. **Per-style gains closed 2026-08-20.** Tier 3 outstanding. |
| **C** — long-form | ✅ **complete and closed 2026-08-20** — 658 tests pass in 17m51s, R-C1…R-C10 all closed — see [`track_c_long_form_video.md`](track_c_long_form_video.md). C0–C8, frontend contract §13, and three review rounds (§14/§15) with nine findings raised and fixed. |
| **D** — script pre-flight | Levels 1–2 and level 3 (rewrite) all built. **Only R2's second half outstanding.** |
| **Music** | Library + `LocalMusicProvider` + per-act beds + per-style gains + BPM/tempo-fit built. |
| **SFX** | ✅ 9-clip local library + `SelectSfxStep` + `mux_sfx`. |
| **§13 review** | R1–R10 except R2's second half fixed and verified. **R8 (speed) closed 2026-08-20 — see §14.2.** |

✅ **ALL OPEN QUESTIONS CLOSED 2026-08-20 — see §14.9 for each, with scenarios and decisions.** **Q5** pacing bands: `2.0` validated by watching real narrated renders. **Q6** style vs Director: the named conflict does not exist (`colour_palette` is read by nothing); the real collision is `camera_language`. **Q7** rewrite retry: one attempt only — plus a NEW finding, the pre-flight has no minimum-length check. **Q8** chars/sec: one constant holds; `HI=12.9` to be deleted; voice dominates language 5×. **Q10** parallax: **works on real archival film — build it**, and it needs no GPU in the render path. ⚠ **Five code changes are decided and NOT yet applied:** delete `script_chars_per_second_hi`; suppress the Director's `camera_language` under a style; make the rewrite entity check symmetric; add the minimum-length warning; resolve `colour_palette` (wire or drop). **Plus §15's five (R11–R15)** — and R11 (thread narration speed into the estimators) belongs in the *same pass* as the first and fourth of these: all three touch `preflight.py`'s rate function.

### 14.8 Suggested order for the remainder

A8 last (user, 2026-08-20). Parallax parked on Q10 (user, 2026-08-20). One leftover item, then stop for review.

1. ~~**Item 1 — narration speed (R8)**~~ — ✅ closed 2026-08-20.
2. ~~**Item 5 — per-style music gains**~~ — ✅ closed 2026-08-20.
3. ~~**Item 6 — BPM + tempo-fit ranking**~~ — ✅ closed 2026-08-20.
4. ~~**SFX**~~ — ✅ closed 2026-08-20. Review findings R11–R15 ✅ fixed 2026-08-20 (see §15 answers).
5. ~~**Split-screen** (`SPLIT_FRAME`)~~ — ✅ **closed 2026-08-20** (see §12). Review findings R16–R20 ✅ fixed and **re-verified 2026-08-20 — see [§16.9](#169-r16r20-confirmed-fixed--2026-08-20)** (483 tests, single alembic head, panel-swap and shot-swap both now caught by the render fingerprint). ⚠ **R16's fix removed the one sequencing constraint on the bottom-panel override**, so that residual is now free to be picked up whenever. The remaining split-screen item is the aesthetic call on padded panels, which needs a human watching real archival material.
6. **R2's second half** — iterative punctuation suggestions; product call, lowest urgency. **Next leftover after this review.**
7. **2.5D parallax** — parked on **Q10**. Not in the active queue.
8. **A8 last** — regenerate 3 Kling clips (~$1.50) and a human watching whether synthetic motion blends beside 1936 photography. Keyframes already exist. Not started.

### 14.9 Q6 and Q8 tested against real code and the real API, 2026-08-20

> **Method.** Q6 by tracing every consumer of the Director's output in `app/` and assembling the exact prompt a styled request produces — no API call needed. Q8 by synthesising three real fixture scripts through the **live ElevenLabs API** and measuring the audio with `ffprobe`. Total spend: **2,027 characters, ~3.4% of the Starter monthly allowance.** Voice `0muxiGNHAVvmM1qWRtyV`, model `eleven_multilingual_v2`.

#### Q8 — ANSWERED. One constant is right; the Hindi constant is wrong; **voice is the variable nobody modelled.**

**Measured, same voice, three scripts:**

| script | non-ASCII | real chars/sec | error using `EN=14.4` | error using `HI=12.9` |
|---|---|---|---|---|
| English (`captions_test_project`) | 1.4% | **15.1** | **+4.8%** | — |
| Hinglish (`hinglish_final_project`) | 38.9% | **14.0** | **−2.6%** | +8.7% |
| Pure Hindi (`hindi_test_project`) | 74.9% | **14.9** | **+3.5%** | **+15.5%** |

**Q8 as written is answered: a single constant DOES hold.** The language axis spans only 14.0–15.1 chars/sec — about 8% — and one constant near 14.4 lands within 5% of all three, including pure Devanagari.

⚠ **`script_chars_per_second_hi = 12.9` is wrong and should go.** It is 15.5% too slow on real Hindi — *most* wrong on the script it exists for — and 8.7% too slow on Hinglish. Because the pre-flight **over**-estimates duration, the effect is **false rejections**: a script gets refused as "too slow for this style" when it would have been fine, with a confident-looking number attached. The 15% non-ASCII threshold routes both Hindi and Hinglish into it, so today the routing rule makes the estimate worse for every script it fires on.

⚠ **The real finding, and it is not what Q8 asked: voice dominates language by ~5×.** `captions_test_project` stores 42.50 s of measured narration; re-synthesising the same text with the current voice gives **57.77 s**. Same text, same model, different voice:

| | chars/sec |
|---|---|
| English, the fixture's original voice | **20.5** |
| English, current voice | **15.1** |

**A 36% swing between voices, against ~8% across languages.** The config models the small variable and ignores the large one.

**Two consequences worth carrying:**

- ⚠ **`captions_test_project`'s stored `duration_s` values are stale** for the current voice (42.50 s vs a real 57.77 s). Anything asserting against them is asserting against a voice no longer in use. `hinglish_final_project` by contrast measured 48.20 s against a stored 48.00 s — **0.4% off, so that fixture's data is sound** and the discrepancy really is voice, not bad fixtures in general.
- ✅ **`script_preflight_margin_fraction = 0.2` is now evidence-backed rather than guessed.** Per-scene chars/sec varies 13.0–18.0 (English), 11.8–16.4 (Hinglish), 14.2–16.1 (Hindi) — roughly ±16–20% around each mean. No constant can be tighter than that per scene, so **the 20% margin is correctly sized and should not be tightened.**

**Decisions taken 2026-08-20:**

1. **Collapse to one constant.** Delete `script_chars_per_second_hi` and the `_NON_ASCII_HINDI_THRESHOLD` routing in `preflight.py`; keep `script_chars_per_second_en = 14.4` as the single figure. Chosen over raising the threshold above 75%, which would leave dead machinery pretending to be a safeguard. ✅ **Applied 2026-08-20 with R11.**
2. **Record the constant as voice-specific, not universal.** 14.4 is calibrated for `0muxiGNHAVvmM1qWRtyV`. The config comment should say so, so the next person does not read it as a property of English.
3. **Defer per-voice calibration.** ⚠ **User confirmed 2026-08-20 that this voice will be in use "for some time,"** so a single constant tuned to it is adequate and per-voice machinery is not worth building yet.
4. **Do it together with narration speed when that lands.** Speed scales chars/sec directly — at 1.2× this voice's 15.1 becomes ~18 — so the estimate has to be reopened for speed anyway (§14.2 item 1). **Per-voice and per-speed are one problem, and doing them in one pass is cheaper than twice.**

#### Q6 — ANSWERED, and the conflict the question named does not exist

**Q6 asked:** *"If the preset dictates a desaturated grade and the Director writes `colour_palette: ['warm amber']`, which wins?"*

**Neither. `colour_palette` is read by nothing.** Verified by grepping every consumer in `app/`: the Director writes it on every project and no code path reads it. The colour grade comes from `STYLE_GRADES`, a fixed table keyed on the style name. **The specific conflict Q6 was written about is impossible.**

**Where the Director's output actually goes:**

| field | consumed by | collides with a style setting? |
|---|---|---|
| `visual_style` | Act / Scene / Shot planners + image-generation prompts | no — style has no visual-look prompt input |
| **`camera_language`** | **Shot Planner only** | **YES — the real collision** |
| `tone` | Act, Scene planners | no |
| `historical_period` | Act, Scene, Shot planners | no |
| `audience` | Act, Scene planners | no |
| `constraints` | constraint/vision checks | no |
| **`colour_palette`** | **nothing** | **dead field** |

⚠ **The genuine defect is in camera, and it is a contradiction with no stated precedence.** For one `retention_fast` shot-planning request the model receives, in the system prompt:

> *"Camera: prefer `punch_in` for most shots… **not the slow drift described in the base camera table above**."*
> *"Transitions: `cut` only… **This overrides the base prompt's** dissolve-for-continuity guidance entirely."*

and in the user message of the same request:

> `camera_language: slow, deliberate pushes; let each image breathe`

**The fragment carefully overrides the base prompt and says nothing about the Director's line, because whoever wrote it did not know that line would be there.** The model resolves the contradiction however it likes, per request — which makes `retention_fast`'s camera behaviour non-deterministic in a way invisible from the code.

**And this is also the answer to the parent question of whether style reaches the Director at all: it does not.** `DirectorPlanner.plan(project_id, script)` takes the script only; its user content is literally `f"Script:\n\n{script}"`.

**Decisions taken 2026-08-20:**

1. **Suppress the Director's `camera_language` line when a style supplies camera instructions.** One conditional in the Shot Planner's prompt assembly. Chosen over §4.1's own suggestion of seeding the whole Director with the style, which is materially more machinery than the actual collision needs — camera is the *only* contested field.
2. **Resolve `colour_palette` one way or the other.** Either wire it to the grade or drop it from `CreativeContext`. ⚠ **As it stands the Director spends output tokens on every project describing a palette nothing honours** — a promise the system does not keep.
3. **Leave `visual_style`, `tone`, `historical_period`, `audience` and `constraints` alone.** They are uncontested, and the style has no competing input for any of them.

⚠ **One limit on the Q6 evidence:** the collision was demonstrated by assembling the real prompt with a hand-written but realistic Director output, not with a live Director call. **The plumbing is verified from code** (`camera_language` reaching the Shot Planner, `colour_palette` reaching nobody); what a real Director writes for a real script has not been observed. One cheap LLM call would close that if the fix is contested.

#### Still open after this pass

| question | status |
|---|---|
| **Q5** — pacing bands per style | open. Needs a human watching renders; `_DEAD_STOP_CEILING_MULTIPLIER = 2.0` is still uncalibrated |
| **Q7** — rewrite retry budget | open as a *decision*. Current behaviour (return the rejected text plus reasons, no retry) is probably right and should be written down before someone "improves" it into a retry loop, where more attempts against fixed checks means more chances for a bad rewrite to pass by luck |
| **Q10** — parallax GPU dependency | **newly testable.** The dev machine has an AMD Radeon 680M (RDNA2) integrated GPU, so the effect can be evaluated locally at zero cost. ⚠ The production container has `h264_vaapi` compiled in but **`/dev/dri` is absent — no GPU passthrough**, so "is it worth having" is now answerable while "is it worth GPU hardware in production" is not affected |

#### Q5 — ANSWERED 2026-08-20 by watching real renders: `_DEAD_STOP_CEILING_MULTIPLIER = 2.0` is VALIDATED

**Method.** Built four `retention_fast`-shaped renders from the real Fischer-Tropsch archival photos — 9 shots, punch-in camera, cuts only, real narration through the live API — where the eight surrounding shots are **byte-identical across all four** and only the 5th shot's length changes. Shot durations set from *measured* audio, so narration remains the master clock exactly as production has it. Shared lines synthesised once and reused; cost **461 characters (~0.8%)**.

| variant | middle shot | user verdict |
|---|---|---|
| `narrated_1_target` | 1.30 s | reads as rhythm |
| `narrated_2_ceiling` | **3.34 s** | **"does not seem like it stopped"** |
| `narrated_3_over` | **4.97 s** | **"from narrated 3 over it starts"** |
| `narrated_4_longest` | 7.34 s | (worse) |

**The perceptual boundary sits between 3.34 s and 4.97 s.** The shipped ceiling of 3.5 s is just above the last comfortable value and well below the first uncomfortable one. ✅ **2.0 is the right multiplier and should not be changed.**

⚠ **And a second measurement makes narrowing it pointless.** Every fragment of the real script, at the measured 15.1 chars/sec:

| band | fragments |
|---|---|
| under 3.5 s (accepted) | **8 of 13** — all in fact ≤ 2.72 s |
| **3.5–5.0 s (the unresolved zone)** | **0 of 13** |
| over 5.0 s (confirmed to stall) | **5 of 13** — 5.36 s to 7.55 s |

**Nothing lives in the zone the experiment left unresolved**, so pinning the boundary more precisely would unlock zero scripts. The distribution is bimodal — very short clauses ("aircraft," 0.40 s) alternating with long run-on sentences (7.55 s) — which is a property of how the script is written.

**Two conclusions that correct earlier framing in this document:**

1. ✅ **The pre-flight's rejections are CORRECT, not false positives.** §14.9 and earlier review passes raised the possibility that an uncalibrated ceiling was needlessly refusing scripts. It is not: those 5 fragments genuinely stall, confirmed by watching. **The remedy is Track D's re-punctuation / rewrite (which took this script's fragment count 13 → 43), not a looser ceiling.**
2. ⚠ **This reinforces §2.5.1: `max(fragment)` is the binding metric and the average is actively misleading.** `D/N` = 3.54 s suggests a script needing modest tightening. The real distribution has *no* typical fragment — it is 8 short and 5 far too long. An average over a bimodal distribution describes nothing that exists.

**Side result worth keeping.** The eight short declarative lines measured **1.35–2.32 s** without being tuned to hit anything — so sentences of that shape naturally produce target-pace shots. That is a useful thing to tell a user writing for `retention_fast`: short declaratives land on target by themselves.

⚠ **One limit.** Judged at normal narration speed. The ~1.2× speed setting (§14.2 item 1) is still unbuilt and will shorten every shot when it lands, so this ceiling wants a re-check then — the same "do it together with speed" note as Q8's constant. Also judged by one viewer on one script; a second opinion would cost only another few hundred characters.

**Decision: keep `_DEAD_STOP_CEILING_MULTIPLIER = 2.0`. Q5 closes.** Q5's own framing — *"blocked on calibration data, not on a decision"* — was right, and the calibration data now exists.

#### Q7 — DECIDED 2026-08-20: one attempt only, never a retry budget

**What the code does today, traced not assumed.** `rewrite_script` makes exactly **one** LLM call — `provider.structured_complete`, deliberately **not** the `run_structured_with_repair` loop every other planner uses. Then three mechanical backstops run (`_validate_rewrite`):

| backstop | comparison | catches |
|---|---|---|
| numeric tokens | `Counter` **both directions** | a changed, dropped **or invented** number |
| capitalised entities | **set difference, one direction** | a dropped name (`Leuna-Werke`, `Sasol`) |
| fragment count | must strictly increase | a rewrite that reworded without splitting anything |

On failure it returns `accepted=False` **plus the attempted text and the reasons** — it never silently discards the attempt. Nothing persists unless the caller passes `persist=True` **and** the rewrite was accepted. There is no retry anywhere.

**Decision: keep exactly this. Recorded as a decision rather than left as an accident**, because the obvious "improvement" is a downgrade and someone will propose it.

⚠ **Why a retry budget is the actively dangerous option — the scenario that decides it.** Suppose "retry up to 3 times, feeding the rejection reasons back":

| attempt | model returns | verdict |
|---|---|---|
| 1 | drops "1936" | rejected — numbers |
| 2 | keeps 1936, turns `Leuna-Werke` into "the Leuna works" | rejected — entity dropped |
| 3 | keeps every number and every name, but rephrases *"converted coal into synthetic fuel"* as *"converted synthetic fuel into coal"* | ✅ **ACCEPTED** |

**Attempt 3 passes all three checks and is factually backwards.** The backstops are fixed and mechanical, so more attempts do not select for a *better* rewrite — they select for one that **evades the checks**. §3.3 says exactly this about its own safeguards: *"These are backstops, not proof — a rewrite can preserve every number and name and still shift meaning. The side-by-side diff shown to the user is the real safeguard."* A retry loop moves the decision from a human reading a diff to a model iterating against a filter, on historical content with no fact-check step anywhere in the pipeline.

**Why the other option in Q7's own wording ("fall back to the style-change path") is not needed either.** The pre-flight *already* reports which styles a script suits, before any rewrite is attempted. Wiring that into the rewrite's failure path would just be the pre-flight talking twice.

**Two scenarios showing the current behaviour is what the user actually wants:**

- *No-op rejection.* The model returns genuinely nicer prose with the same sentence count → rejected: *"fragment count did not increase (13 → 13) — rewrite was a no-op for pacing purposes."* Correct: the request was faster cutting, not better writing, and accepting it would change the user's own words for zero pacing benefit — the worst trade available under this feature's "the user's words are never in the model's output" constraint (§3.2).
- *End to end today.* `POST /script/rewrite` → `accepted=false`, the reasons, and the attempted text. The user reads the diff and either edits by hand, rewords themselves, or picks a slower style. **Nothing was persisted and nothing was spent beyond one call.**

⚠ **One real asymmetry found while tracing, worth a small follow-up.** Numbers are compared **both ways** (a `Counter` equality catches missing *and* invented), but entities are a **one-way set difference** — a *dropped* name is caught, an *invented* one is not. So a rewrite that introduces "Sasol" into a sentence where it did not belong passes all three backstops. Less likely than dropping a name, and the diff would show it, but the asymmetry reads as unintentional rather than reasoned. **Making the entity check symmetric is a one-line change.**

#### ⚠ NEW, found while deciding Q7: the pre-flight has no minimum-length check at all

**The user's stated concern, 2026-08-20:** *"I don't want to be stuck with a script that fails later in production because it was too short."*

Traced against the code, and **every one of the pre-flight's four blocking checks guards the same direction:**

| check | guards against |
|---|---|
| total duration vs `bundle.max_video_duration_s` | too **long** |
| average shot duration vs the style's target | too **slow** |
| longest fragment vs the dead-stop ceiling | too **long** |
| fragment count vs the shot cap | too **many** |

⚠ **There is no minimum. Grepped for one — nothing exists.**

**The scenario nobody guarded:**

> A 400-character script, any style. Every check passes. Planning runs, narration is synthesised, assets resolve, the render completes — and the result is a **~27-second video** when three minutes were wanted. Nothing warned anyone, because "not enough script" is not a thing this system looks for.

**That is the same shape as the failure the whole pre-flight exists to prevent** — a late, expensive discovery of a length problem — in the one direction it was never pointed at.

**Decision: add a minimum-length check, and make it WARN, never block (user-confirmed 2026-08-20).**

- **Cheap to build.** `estimate_duration_s` already computes the predicted duration and the bundle already carries a target; the comparison is a few lines over data that is already present.
- **Needs no calibration.** Unlike Q5's pacing bands, nothing has to be watched or tuned — either the script reaches the requested length or it does not. And Q8 has now measured the chars/sec constant against the live API, so the estimate behind it is trustworthy to within ~5%.
- ⚠ **Warn, not block, and this follows §3.1's own split rather than being a new rule:** *"feasibility is arithmetic, and hard-stopping someone on a fact is defensible. Suitability is a model's taste."* A short script is an arithmetic fact — but whether it is *wrong* is the author's judgement. A 40-second piece may be exactly what was intended. So report *"this script will produce ~27s; you asked for 3 minutes"* and let the human decide. **Blocking here would refuse someone their own deliberate choice, which is the one thing §3.1 is careful never to do.**
- **Where it belongs:** alongside the existing checks in `check_feasibility`, but surfaced as a separate `warnings` list rather than appended to `violations` — `FeasibilityResult.passed` is `not self.violations`, so putting a warning in `violations` would block it by accident.

#### Q10 — ANSWERED 2026-08-20: the effect works on real archival material. Verdict: BUILD IT, and it needs no GPU in the render path.

**Method.** DepthFlow 1.0.0 installed into an **isolated throwaway venv** (`%TEMP%\depthflow-eval`, 5m39s) — deliberately *not* the project venv, which it would have polluted with `torch`, `transformers`, `moderngl`, `numpy`, `setuptools` and 55 more, making the venv diverge from what `backend/Dockerfile` builds. Ran against the real Fischer-Tropsch archival photos at 720×1280. Hardware: AMD Radeon 680M (RDNA2 integrated, Vulkan 1.4, AMD proprietary driver, 6 OpenCL compute units).

**User verdict, 2026-08-20, on 5 animated photos:** *"the parallax is working good"* — and specifically that it does **not** break up on the reactor photograph. ✅ **That was the whole risk this test existed to expose:** depth models are trained on modern photography, and 1936 reconnaissance film is out of distribution — grain, scratches and blown-out sky could all have been read as geometry. They were not.

**Measured cost:**

| step | cost | notes |
|---|---|---|
| depth estimation | **~13–50 s per photo, CPU** | one-off, **cached** per photo thereafter |
| parallax render | **~7–16 s per 4 s clip** | the shader step, on the iGPU |
| Ken Burns (today, for comparison) | 6.5–7.7 s per 4 s | the thing parallax has to beat |
| a 13-shot project | **~5 min of CPU once**, then normal | |

⚠ Depth ran on **CPU** — `torch` installs as `2.13.0+cpu` because Windows has no CUDA and no official ROCm for AMD, so only the shader touched the Radeon. **These are not production throughput figures**, but they do establish the effect is cheap enough to be practical even without GPU-accelerated depth.

#### ⚠ The deployment question was framed wrongly, and the plan's own architecture already answers it

§2.7 asked *"does the parallax provider justify a GPU dependency"* and §10 called it *"the only item here that changes the deployment story."* **That framing assumed parallax runs inside the render service. It does not have to.**

§2.7's own design — **"treat parallax as a provider, not a filter: still in, clip out, cached by content hash exactly like `generated_clip`"** — means the renderer only ever opens a finished mp4. So:

| where the provider runs | needs GPU passthrough in the render container? |
|---|---|
| inside the render container | yes — ⚠ and `/dev/dri` is **absent** there today (verified: the image has `h264_vaapi` compiled in, no device to talk to) |
| a separate worker | only that worker |
| **a batch step, anywhere — including a dev machine** | **no** |

**The real question is "where does the parallax provider run," not "does the render service need a GPU."** That is a materially lower bar than Q10 assumed, and it needs no architectural change — the caching boundary that makes it true is already specified and Track A's motion-clip input path (A1) that consumes the output is already built and reviewed.

**Decision: build it, and run the provider OUTSIDE the render container.** Depth maps and clips are content-hash cached, so generation is a separate concern from rendering, exactly as generated clips already are.

#### ⚠ Three maintenance findings — this needs a wrapper and a pin, not a bare `pip install`

Every one of these was hit on first use, and all three are cheap to handle at the provider boundary — which is an argument *for* the provider design rather than against the feature.

1. **The released version does not start.** `depthflow 1.0.0` calls `hasher.update()` with a `str` in `estimators/anything.py:37-38` and `estimators/__init__.py:27`; `hashlib`/`xxhash` require bytes. Three lines patched locally to proceed. ⚠ **A dependency whose current release crashes on import-to-first-use must be pinned and vendored-or-patched, not tracked loosely.**
2. **Animation is OFF by default.** The bare `DepthScene` produces a depth-mapped **still**. Motion lives in preset subclasses (`Orbital`, `Vertical`, `Dolly`, `Circle`, `Zoom`) that override `update()` to drive `state.offset` / `state.isometric` / `state.zoom` per frame. ⚠ **This wasted the first evaluation round** — the initial clips were static and the user correctly reported *"they look like a normal picture."* The provider must select a preset explicitly; there is no useful default.
3. **Single-channel grayscale input crashes it.** A `pix_fmt=gray` photo (5697×6134) raised `ValueError: Could not make a flat list of images` — the estimator's preprocessing got a 2-D array where it wanted 3-D. ⚠ **Grayscale is exactly what archival photography commonly is**, so this would have failed constantly in production: 1 of 4 photos on the first pass, reproducibly the same one. **Proven fix:** one `format=yuvj420p` conversion before handing the image over — re-ran and it rendered cleanly (5.5 MB output). **Normalise to 3-channel RGB at the provider boundary.**

#### Suggested build plan (Tier 3, unchanged in priority)

1. **`ParallaxProvider`, shaped exactly like `FalVideoProvider`'s cached half.** Still in → clip out, keyed on `(content_hash, preset, duration)`. The renderer stays untouched: it already accepts a motion clip (A1) and cannot tell how one was made.
2. **Normalise input to 3-channel RGB** before the estimator (finding 3). Non-negotiable given the source material.
3. **Pick the preset per style, not per shot.** `Orbital` and `Vertical` both read well; this is a style-level look decision (§2.2's line: global look → render settings, selected by the style), not a per-shot creative one, so it does **not** need a new Timeline field or a planner change.
4. **Pin `depthflow` exactly and carry the three-line patch** (finding 1) — or vendor the estimator wrapper.
5. **Run generation outside the render container**, so no GPU passthrough is needed where the video is assembled.
6. ⚠ **Fingerprint discipline (§7's four-times-learned lesson).** The clip is cached by content hash, so the render fingerprint changes via the asset hash automatically — **but the preset choice must reach it too**, or switching from `Orbital` to `Vertical` serves a stale render. It rides `metadata.render_style` if the preset is style-derived (step 3), which is another reason to prefer that over a per-shot field.

**Artifacts kept:** `~/Desktop/q10_parallax/` — `ANIM_orbital*.mp4`, `ANIM_vertical.mp4`, `ANIM_orbital_3_fixed.mp4` (the grayscale case, post-conversion), and `kenburns_*.mp4` for the A/B. The `parallax_0/1/2.mp4` files are the un-animated first round and should be ignored. Eval venv at `%TEMP%\depthflow-eval` (~1 GB), removable — nothing depends on it.

---

## 15. Code-vs-plan review of the four items closed 2026-08-20 (R8, SFX, music gains, BPM)

> **Method.** Same standard §13 set for itself: every claim in §12's four new entries was checked against the code that now exists, and every number below was produced by **running** the real functions (`rank_music_candidates` against the real 54-track manifest, `rank_sfx_candidates` against the real 9-clip library, `mux_sfx` against a real silent mp4, `compute_render_fingerprint`'s actual parameter list) or counted out of the manifest JSON. Nothing here is inferred from reading a docstring — where a finding is a wrong *justification* rather than a wrong *behaviour*, it says so (§13's R4 distinction).
>
> **Tests re-run, not trusted:** 82 unit tests (`test_sfx`, `test_sfx_ranking`, `test_local_sfx`, `test_music_ranking`, `test_styles`, `test_fingerprint`, `test_elevenlabs`) and 6 DB-free integration tests (`test_mux_sfx`, `test_sfx_library_integrity`, `test_music_library_integrity`) all pass. The DB-backed integration suite was deliberately **not** re-run — it truncates the same Postgres the dev server uses, and nothing in these findings needs it.
>
> ⚠ **The through-line behind R11 and R14 is one mistake, not two: a value landed in the code that DOES the work, and never reached the code that ESTIMATES the work.** `resolve_narration_speed` has exactly two consumers — narration synthesis and the render's hash lookup. No estimator anywhere knows speed exists. That is the same wrong-**altitude** failure §13's own method note named as a standing review rule ("the resolver was verified but not the run that calls it"), arriving for the fourth time.

### 15.1 R11 — BLOCKING for `retention_fast`'s pre-flight: R8 shipped speed into synthesis and into no estimator

`retention_fast` now synthesises at **1.2×**, so its real delivery is ~18 chars/sec on the calibrated voice. But `preflight.py::_chars_per_second` still divides by `script_chars_per_second_en = 14.4`, and `check_feasibility(script, style)` **already has the style in hand** — it simply never asks what speed that style speaks at. Every `retention_fast` estimate is now ~20% too long, in the false-rejection direction:

| pre-flight check | consequence of the 20% inflation |
|---|---|
| total duration vs `bundle.max_video_duration_s` | ⚠ **no margin at all.** `check_feasibility`'s own docstring says this check is deliberately *not* margin-widened, to mirror `Timeline._validate_structural_invariants`. So the whole 20% is pure false rejection — a script refused as "exceeds the project maximum" that would have fitted |
| average shot duration vs `band.target_shot_duration_s` | ⚠ **`script_preflight_margin_fraction = 0.2` is now entirely consumed by the speed error**, leaving nothing for the ±16–20% per-scene variance §14.9's Q8 measured. The margin that Q8 declared "correctly sized and should not be tightened" has been spent without being touched |
| longest fragment vs the dead-stop ceiling | false dead-stop violations on fragments that will not dead-stop |

**`suggestions.py` is the worse half.** [`suggestions.py:140-145`] receives `band` — it knows the style — and still uses the unscaled rate to decide which fragments are too long to leave alone. So level 2 now proposes breaking fragments that do not need breaking, which feeds directly into **R2's still-open iterative-suggestion problem**: more suggested breaks, each of which the user must accept, none of which were necessary.

⚠ **This is Q8's decision #4 not being kept.** That decision, recorded in §14.9 the same day, says per-voice and per-speed **are one problem** and "doing them in one pass is cheaper than twice." Speed landed alone. And the style affected is the one §13.13 declared *"now honest to offer"* on the strength of R1 and R8 both closing — so **`retention_fast`'s pre-flight is, as of R8, the least accurate it has ever been.**

**Fix (small).** Thread `resolve_narration_speed(style)` into the rate: `_chars_per_second(script) * resolve_narration_speed(style)`. `estimate_duration_s(script)` needs a style parameter it currently lacks (two call sites plus `suggestions.py`). **Do it with the `script_chars_per_second_hi` deletion already decided in Q8** — they are the same function and the same one-pass argument applies.

**Fixed 2026-08-20.** `_chars_per_second(style)` is now `script_chars_per_second_en * resolve_narration_speed(style)`. `estimate_duration_s` and `suggestions.suggest_breaks` take the style. Hindi/Hinglish routing and `script_chars_per_second_hi` are deleted (Q8). Short scripts get a `warnings` list, never a block (Q7). `retention_fast` estimates are 1.2× shorter; English and Hindi scripts of equal length now share one rate.

### 15.2 R12 — `sfx_max_clip_s` changes output bytes and is not in the render fingerprint. §7's lesson, fifth occurrence.

`render.py` passes `max_clip_s=settings.sfx_max_clip_s` into the mux, where it becomes a literal `atrim=0:1.500` in the filter graph. `compute_render_fingerprint` hashes `sfx_gain_db` and **not** this.

> Change `SFX_MAX_CLIP_S` from 1.5 to 3.0 → identical fingerprint → **cache hit → the old, shorter mix is served as if it were the new one.**

⚠ **This is the exact shape of R2** — a config value that changes output bytes with nowhere in the fingerprint to be caught — and it was introduced two paragraphs below §14.3's own written warning that *"every new render input enters `compute_render_fingerprint`… this document's own §7 lesson, hit four times."* Now five. **Fix: one more parameter, hashed unconditionally like `sfx_gain_db` beside it.**

**Fixed 2026-08-20.** `sfx_max_clip_s` is a required fingerprint field, passed from `RenderStep` next to `sfx_gain_db`. Changing 1.5 → 3.0 now misses the cache. Test: `test_different_sfx_max_clip_changes_the_fingerprint`.

### 15.3 R13 — `mux_sfx` fails the render on a silent video, in a subsystem whose contract is "never fail the run"

`mux_sfx`'s docstring says the overlay will *"become the audio if the video is silent."* **It does not.** The filter graph references `[0:a]` unconditionally.

**Verified by running it**, not by reading it: `mux_sfx` against a real silent 4 s mp4 with one overlay raises `PermanentError` (ffmpeg exit `4294967274`).

**Reachable when `sfx_plan` has clips and both narration and music are absent:** music selection returning no track (`_music_segments` → `None`) plus a run where `NarrationStep` did not produce the active version (`produced_by != NARRATION`) — which is exactly the shape `tests/integration/test_narration_pipeline_ordering.py` constructs deliberately. `RENDER_ONLY_STEPS` can reach it too.

⚠ **§12's own entry states the SFX contract as "Missing clips skip those events, never fail the run." This is the one path that fails the run** — and the single integration test muxes narration on first, so it never touches it. **Fix: either probe for an audio stream and drop `[0:a]` from the mix when there is none, or treat a silent input as the empty-overlay case and copy.**

**Fixed 2026-08-20.** `_has_audio_stream` via ffprobe. If `[0:a]` exists it is the mix bed (`duration=first`). If not, an `anullsrc` of the video's length is the bed and the overlays *become* the audio — matching the docstring rather than copying a silent file. `test_mux_sfx_on_a_silent_video_becomes_the_audio` covers the crash path.

### 15.4 R14 — tempo-fit outranks the creative brief, and a zero-relevance track wins. Measured on the real library.

`_tempo_band` sits **above** term-overlap relevance in `rank_music_candidates`'s sort key. And `LocalMusicProvider.search` ignores the query entirely — it returns **all 54 tracks** for every request — so with `MUSIC_PROVIDER=local` (the default) ranking *is* the whole selection mechanism.

**Real top picks, run against the shipped manifest at `video_duration_s=180`:**

| Director's brief | no tempo target | with a 137 BPM target (`retention_fast`, 1.75 s shots) |
|---|---|---|
| ambient / drone / quiet / reflective | `nightshift-master`, relevance **0.500** | **"Delightful D"**, relevance **0.250** |
| solemn / memorial / strings / mourning | `Dark Times` (48 BPM), relevance 0.250 | **"Delightful D"**, relevance **0.000** |

⚠ **A track with zero term overlap takes the top slot on a solemn memorial brief, because it published a number inside the band.** One place down the same list, a somber drone with no BPM loses to a 120 BPM "Delightful D" on an industrial-war brief.

**Why the module's own precedent does not justify this.** `music_ranking.py`'s docstring argues at length for lexicographic ordering over a soft blend — but it argues it for the **duration floor**, where the thing being excluded is a *defect*: a 2.5 s air horn is objectively unusable as a bed, so a hard guarantee is right. **Tempo is taste, not a defect.** Ranking a taste preference above the brief is a different decision than ranking a defect filter above it, and it was not separately argued.

**Two further reasons tempo cannot support that position:**

- `SelectMusicStep` runs **before** `NarrationStep`, so `mean_shot_duration_s` is a *pre-narration estimate*. Q8 measured per-scene chars/sec variance at ±16–20% — **the uncertainty in the target is as wide as the ±20% acceptance band itself.** A criterion cannot discriminate more finely than its own input error.
- **R11 compounds it in a known direction:** the estimate feeding `target_bpm` is 20% too long for `retention_fast`, so the target BPM is ~20% too low, and the band selects slower music than intended on the one style where cutting tempo actually matters.

**Fix: move `_tempo_band` below the relevance term.** Tempo becomes a tiebreaker among comparably-relevant tracks, which is what a ±20%-uncertain criterion over a 33%-populated field can actually support. The three properties §12 claimed for it (never discards; unknown beats a published mismatch; published-fit beats unknown) all survive — they just stop overriding mood.

**Fixed 2026-08-20.** Sort key is now `(duration_floor, -relevance, tempo_band, source_id)`. Equal-relevance in-band vs mismatch still prefers the fit; a solemn memorial brief no longer loses to a zero-overlap 140 BPM track. Test: `test_term_overlap_outranks_tempo_fit`.

### 15.5 R15 — two SFX length policies, 4.0 s and 1.5 s, neither aware of the other

`rank_sfx_candidates` prefers clips ≤ **`_SFX_CEILING_S = 4.0`**. `mux_sfx` hard-cuts at **`sfx_max_clip_s = 1.5`** with `atrim` and **no fade**. The ranking therefore cannot express a preference for clips that survive the mix intact.

**What the shipped library actually selects**, run through the real provider and ranker with the real `_DEFAULT_QUERIES`:

| kind | picked | duration | after `atrim=0:1.5` |
|---|---|---|---|
| `whoosh` | `swosh_swoosh_whoosh_air_sound…` | 0.490 s | intact |
| **`stinger`** | **`creepy_stinger_chuckle.mp3`** | **4.000 s** | ⚠ **cut off mid-sound at 1.5 s, no fade, on every text card** |
| `transition` | `space_swoosh_brighter.mp3` | 1.013 s | intact |

⚠ **The default stinger sits exactly on the ranking ceiling and is truncated by 62% of its length in the mix.** A hard `atrim` mid-waveform is an edge discontinuity, which is the standard way to produce an audible click.

**Secondary, and it decides an aesthetic by accident:** all three stingers tie on relevance (all tagged `stinger`, queried with `stinger` / `cinematic impact`), so `source_id` — the I5 determinism tiebreak — picks the winner **alphabetically**: `creepy…` < `horror…` < `stinger_3…`. The neutral clip (`stinger_3_wav`, 1.995 s) is last of three. **A horror chuckle plays under archival documentary title cards because of the letter it starts with.**

**Fix: tie `_SFX_CEILING_S` to `sfx_max_clip_s` so ranking and mixing share one length policy, and add a short `afade` out at the cut.** The tie-break exposure is separate and is a library-curation call, not a code one — three interchangeable clips per kind means alphabetical order will always decide.

**Fixed 2026-08-20.** Ranking reads `settings.sfx_max_clip_s` (1.5), not a private 4.0. Clips that survive the mix intact rank first; among those that do not, shorter wins (less truncation) so `stinger_3` (1.995 s) beats `creepy_stinger_chuckle` (4.0 s) instead of alphabetical horror. Each overlay gets `afade=t=out` over the last 80 ms of the trim. The remaining library-taste call (horror vs neutral stinger when both fit) is unchanged and still a curation pass.

### 15.6 Smaller items, all verified, none blocking

- **`sfx_content_hashes`'s justifying comment is wrong.** It says clip bytes "are not in the Timeline (I2), so the hashes of the files actually mixed must be here" — but the hashes *are* in the Timeline, as `SfxClipSelection.content_hash`, and the whole timeline document is already hashed. The entry is redundant, not harmful, and it matches `music_content_hash`'s own precedent — but the stated reason does not hold (an R4-shaped wrong-justification, recorded so nobody builds on it).
- **`sfx_gain_db` is hashed unconditionally, so every pre-SFX cached render misses exactly once.** Consistent with how the music gains, captions and watermark each landed; expect one re-render, not a bug.
- **`FakeNarrationProvider` uses `request.speed or 1.0` without `canonical_narration_speed`** — the fake is unclamped where the real provider clamps to 0.7–1.2. Only reachable via a code-level band value outside the band, so theoretical today.
- **`_pre_sfx_*.mp4` is written to `renders/`, not `work/`** — follows Track C's `_act_bed_` precedent, so consistent rather than wrong, but both are intermediates sitting in the output directory.
- **`SelectSfxStep`'s docstring says it runs before the approval gate "so a human hears the whooshes."** The placement is right and matters (see §15.7), but nothing renders SFX until `RenderStep`, so nothing is audible at approval. The reason is wrong; the position is not.

### 15.7 What was checked and holds up

| claim in §12 | verified how |
|---|---|
| speed shares one canonical value between the hash and the request | `canonical_narration_speed` is called by **both** `compute_narration_content_hash` and the provider's body assembly — the failure mode named in §2.1 (a speed that reaches the API but not the hash) is structurally closed, not just avoided |
| default 1.0 keeps pre-R8 cache rows as hits | 1.0 is omitted from the digest string entirely; the four-value key is byte-identical |
| `resolve_music_gains` treats `0.0` as a real value | `is not None` throughout, never `or` — as its own docstring insists |
| the fingerprint and `mux_music` cannot drift on gains | `render.py` resolves **one** `MusicGains` and passes the same pair to both. R2's lesson applied correctly this time |
| 18 of 54 tracks carry BPM, 36 stay null | counted from the manifest; values 40–180; `_TEMPO_FIT_FRACTION = 0.20` matches the documented ±20% |
| SFX placement reuses existing arithmetic rather than re-deriving it | `compute_shot_start_times` (D5-correct run/overlap math, explicitly not a naive running sum) and `punch_in_frame_offsets` — the transition event lands exactly on the next shot's start, which is the same number the crossfade uses |
| `sfx_plan is None` is a no-op for pre-existing Timelines | both `_sfx_content_hashes` and `_sfx_overlays` return empty; render-only of an old project is genuinely unblocked |
| the mux routes through `run_ffmpeg` | R-C7's semaphore is respected; no raw subprocess |

✅ **One thing done right that is not obvious and deserves naming: `SelectSfxStep` is placed BEFORE `NarrationStep` in `DEFAULT_PIPELINE`.** Had it landed after, its `produced_by=SFX_SELECTION` version would have become the active one, `_resolve_narration_rows` would have returned `None` on its `produced_by != NARRATION` check, and **every narrated render would have silently gone silent** — a whole-product regression with no error message, discoverable only by watching a video. The same is true of `SelectMusicStep`, which sits in the same window. This is a real invariant of the pipeline order that neither step's docstring states, and it is worth stating somewhere before someone reorders the list for a good-looking reason.

### 15.8 Recommended order

1. **R13** (silent-video crash) — ✅ fixed 2026-08-20.
2. **R12** (`sfx_max_clip_s` into the fingerprint) — ✅ fixed 2026-08-20.
3. **R11** (speed into the estimators) — ✅ fixed 2026-08-20, in one pass with Q8's `script_chars_per_second_hi` deletion and Q7's minimum-length warning.
4. **R15** (tie the SFX length policies, add the fade) — ✅ fixed 2026-08-20.
5. **R14** (demote tempo below relevance) — ✅ fixed 2026-08-20.

87 related tests green. **Stopped here for review.** Next leftover remains split-screen. A8 last.

### 15.9 R11–R15 confirmed fixed, and §15.6's five minors closed — 2026-08-20

> **Method: re-ran the experiment that produced each finding, not the docstring that now claims it is fixed.** Every confirmation below is the same call, on the same real data, that failed or mis-ranked when §15 was written. **463 tests pass** — the whole `tests/unit` tree plus the three DB-free integration suites (`test_mux_sfx`, `test_sfx_library_integrity`, `test_music_library_integrity`), re-run *after* the minor fixes below, not only after the five findings. `ruff check` clean. The DB-backed suite was again not re-run — it truncates the Postgres the dev server uses, and nothing here needs it.

#### The five findings

| | verified how | verdict |
|---|---|---|
| **R11** | `_chars_per_second(style)` now multiplies by `resolve_narration_speed(style)`. Same 2,200-char script: `retention_fast` **152.8 s → 127.3 s** (rate 14.40 → 17.28); `documentary_archival` and `stillness` **unchanged at 152.8 s**; a style-less legacy call still resolves 14.40 | ✅ **fixed.** The 20% inflation is gone and the two styles with no speed override are untouched, so no existing pre-flight verdict moved |
| **R12** | `sfx_max_clip_s` is now a `compute_render_fingerprint` parameter, hashed unconditionally beside `sfx_gain_db` — **plus a dedicated regression test** (`test_different_sfx_max_clip_changes_the_fingerprint`) | ✅ **fixed and locked.** §7's lesson finally has a test rather than a comment |
| **R13** | The exact call that raised `PermanentError` (ffmpeg exit `4294967274`) re-run: **succeeds, duration 4.000 s preserved, both streams present.** The fix probes for an audio stream and injects a duration-matched `anullsrc` as the mix base when there is none | ✅ **fixed.** The overlay now genuinely becomes the audio, which is what the docstring had been claiming all along |
| **R14** | Relevance moved above `_tempo_band` in the sort key. Re-ran the two briefs that flipped: `ambient/drone/quiet` and `somber/industrial/war` now give the **same top pick with and without a 137 BPM target**. "Delightful D" at relevance **0.000** wins nothing | ✅ **fixed.** The one brief that still shifts (`solemn/memorial`) shifts *within equal relevance* — a known-mismatched 48 BPM losing to a pulseless track — which is tempo working as the tiebreaker it was documented to be |
| **R15** | Ceiling now reads `settings.sfx_max_clip_s`; the trim gets an 80 ms `afade`; and — beyond what the review asked — clips that do **not** fit are ordered by **least truncation**. Default stinger pick: **4.000 s → 1.995 s** | ✅ **code fixed**, ⚠ **library residual, see below** |

⚠ **R15's fix also solved the alphabetical problem for free, which is worth noting because it was raised as a separate curation issue.** The three stingers tie on relevance, so `source_id` used to decide the aesthetic and `creepy_stinger_chuckle` won on the letter C. Ordering the non-fitting clips by duration puts the neutral `stinger_3_wav` first instead. **A defect-magnitude tiebreak beat a curation problem** — worth remembering next time an aesthetic complaint looks like it needs a library change.

#### ⚠ R15's one open residual: the library cannot satisfy the policy it can now express

The three stinger clips are **1.995 s, 3.024 s and 4.000 s**. `sfx_max_clip_s` is **1.5 s**. So no stinger fits, and every text-card stinger is still trimmed — now by 25% instead of 62%, and faded rather than clicking, but the tail is still lost.

**This is curation, not code.** The ranking can now express "prefer a clip that survives the mix"; there is simply nothing in the library that does. **One CC0 stinger under 1.5 s closes it** — the same `scripts/download_sfx_library.py` path the other nine came through. Deliberately left for a live-download pass rather than folded in here.

#### §15.6's five minors, all closed — and two turned out to be worth more than "minor"

1. **`FakeNarrationProvider` now clamps through `canonical_narration_speed`** rather than `request.speed or 1.0`. Verified: `speed=5.0` produces 18.0 chars/sec (15.0 × the clamped 1.2), not 75.0. The point is not tidiness — the real provider clamps, so an unclamped fake would make **DRY_RUN disagree with production about how long a scene takes**, which is the one thing this provider exists to get right.
2. **The `sfx_content_hashes` comment now states the true reason.** The entry is *redundant* — every clip hash is already inside `SfxClipSelection.content_hash` in the hashed timeline document — and is kept only for the same one-obvious-line-per-mux-input convention `music_content_hash` follows. `sfx_gain_db` is the entry that genuinely has nowhere else to live. Recorded so nobody builds a load-bearing argument on a redundant field.
3. **`SelectSfxStep`'s docstring no longer claims a human "hears the whooshes" at the approval gate.** Nothing renders SFX until `RenderStep`, well after approval. It runs early because the search is free (I6), and it must stay before `NarrationStep` — see 4.
4. ⚠ **The ordering invariant from §15.7 is now written down, above `DEFAULT_PIPELINE` where a reorder would happen.** `NarrationStep` must be the last pre-approval step that appends a version, because every appending step stamps its own `produced_by` and `_resolve_narration_rows` resolves audio only for `produced_by == NARRATION`. **Moving `SelectMusicStep` or `SelectSfxStep` after narration — for a reason as plausible as "select music once the real durations are known" — silently drops narration from every render: no exception, no failed step, no log line, discoverable only by watching the video.** The comment says that, and says where such work belongs instead (after the approval gate, or re-stamping `produced_by`).
5. **Both mux intermediates moved from `renders/` to `work_dir`** (`pre_sfx_*.mp4`, `music_bed_*.m4a` — the latter taking Track C's `_act_bed_` with it, since it had the same problem and set the precedent). `renders/` is the directory a human and `GET /projects/{id}/video` treat as the outputs; a half-mixed `_pre_sfx_final.mp4` sitting there is indistinguishable by name from a real render. Nothing globs either directory, so this is a rename with no other consumer.

#### Two of the five older decided-but-unapplied changes landed with this batch

- ✅ **`script_chars_per_second_hi` deleted** (Q8 decision #1) — folded into R11, which is exactly the one-pass argument that decision made.
- ✅ **Q7's minimum-length WARNING**, wired end to end: its own `warnings` field (never `violations`, so `passed` is untouched), `settings.script_preflight_min_duration_s = 60.0`, and surfaced through `app/schemas/script_preflight.py` and `app/api/projects.py`. Verified: a 2-second script warns and **still passes**.

⚠ **Three remain unapplied:** the Director's `camera_language` is still emitted unconditionally by the Shot Planner (Q6); the rewrite's entity check is still a one-way set difference, catching dropped names but not invented ones (Q7); and `colour_palette` is still *required* by the Director's own validator while being read by nothing (Q6) — so the Director still spends output tokens on every project describing a palette the system does not honour.

#### §15 closes here

R11–R15 fixed and re-verified, five minors closed, one library residual named. **Split-screen closed 2026-08-20.** Remaining: three Q6/Q7 code changes, R2's second half, parallax parked, A8 last.

---

## 16. Code-vs-plan review of split-screen (leftover item 3), 2026-08-20

> **Method.** Same standard as §13 and §15: read the slice against the plan, then probed the real code. The fingerprint claims were tested by **calling all three fingerprint functions with swapped panel assets** and comparing digests; the resolver findings were traced through `is_satisfied` / `run` / `_ScratchBinding` and cross-checked against the attribute surface the resolve path actually touches; the renderer was exercised by the slice's own real-ffmpeg tests. **The slice's own 38 tests pass** (split-screen filter arithmetic, the real-ffmpeg composite and degrade, shot planner, asset planner, fragments); and a full sweep — the whole `tests/unit` tree plus the four DB-free integration suites — is **474 passed**, up from 463 before this slice, with no regression in the SFX, music, narration-speed or fingerprint work reviewed in §15. The DB-backed suite was not re-run (it truncates the Postgres the dev server uses).
>
> ⚠ **This slice is the best-disclosed one so far, and the review reflects that.** §12's entry volunteers five residuals unprompted — per-shot cost estimate, no gutter, no layout toggle, no bottom-panel override, and the outstanding Q6/Q7/R15 items. **None of the findings below is one of those.** Every one is something the entry either does not mention or states more confidently than the code supports.
>
> **The through-line: the second panel is a first-class render input everywhere the RENDERER looks at it, and a second-class one everywhere the WORKFLOW does.** The two lower fingerprint layers, the migration, the carry-forward, and the timeline service all treat it properly. `is_satisfied`, the failure record, the reuse-gap ledger and the top-level fingerprint do not.

### 16.1 R16 — the render fingerprint cannot tell the top panel from the bottom one. Measured.

§12's entry says: *"Both content hashes go into `compute_render_fingerprint` (sorted list) and `compute_shot_stream_fingerprint` / `compute_run_fingerprint` (dedicated `secondary_*` field...). Swapping the bottom panel misses the shot-stream cache."* **Both halves are true. The consequence of the parenthetical is not stated, and it is the one that matters.**

**Measured — the same split shot, top and bottom assets exchanged:**

| layer | swap detected? |
|---|---|
| `compute_shot_stream_fingerprint` | ✅ yes — `asset_hash` and `secondary_asset_hash` are separate keys |
| `compute_run_fingerprint` | ✅ yes — separate `hash` / `secondary_hash` per shot |
| **`compute_render_fingerprint`** | ❌ **no — identical digest** |

⚠ **The render fingerprint is checked FIRST and short-circuits everything**, including both lower caches. So on a swap it returns a hit and the two correct layers are never consulted. The reason is `sorted(asset_content_hashes)` — a deliberate property, asserted by its own test (`test_asset_content_hash_order_does_not_matter`), whose stated purpose is *"two equivalent renders whose bindings merely got resolved in a different sequence must still fingerprint identically."* That reasoning is sound for resolution ORDER. It is not sound once the list contains two hashes whose **assignment** (top vs bottom) changes the pixels, because a flat sorted multiset cannot express assignment.

**Reachability, stated honestly: not reachable through any endpoint today.** `override_shot_asset` writes `binding.asset_id` only, so a human cannot set the bottom panel — which is §12's own disclosed residual. ⚠ **That is exactly why this needs recording now: closing the disclosed residual (a bottom-panel override) is what makes this one reachable.** The fix for one opens the other, and whoever adds the override will not naturally think about a sorted list two modules away.

**The same hole already exists one level up and IS reachable today**, pre-dating this slice: override shot A to shot B's image and shot B to shot A's, on two shots already carrying `asset_locked=True` (so the timeline document does not change either) — identical sorted multiset, identical fingerprint, stale render served. Narrow, but it means the class is real rather than theoretical.

**Fix: pass assignment, not a bag.** Either hash `{shot_id: (primary_hash, secondary_hash)}` instead of a flat sorted list, or add a separate `secondary_content_hashes` mapping alongside it. The first also closes the pre-existing shot↔shot case.

**Fixed 2026-08-20.** Replaced the sorted bag with `shot_media: [{shot_id, hash, secondary_hash}]` in timeline order. Swapping the two panels of one shot misses; swapping shot A and shot B's assets misses too (the locked-shot case). Tests: `test_swapping_top_and_bottom_panels_changes_the_fingerprint`, `test_swapping_two_shots_assets_changes_the_fingerprint`. Existing cache rows miss once, same as every prior R2-shaped field.

### 16.2 R17 — `is_satisfied` ignores secondaries, so the re-entry guard written for them cannot fire

`run()` carefully computes `needs_secondary` and re-enters a shot whose primary is already done but whose bottom panel is missing. **`is_satisfied` does not know secondaries exist:**

```
return all(bindings[s.id].state in self._done_states for s in shots)
```

The engine skips any step whose `is_satisfied` is true. So whenever every primary is done — the exact condition `needs_secondary` was written for — the step is skipped and `run()` is never called. **The re-entry guard is unreachable in its own scenario.**

⚠ **This makes one of §12's claims false in the common case.** The entry says *"Generation of a missing bottom panel still runs if the generation pass reaches the shot."* The generation pass reaches a shot only if that shot's **primary** is not yet done. So: top panel found by free search (the normal outcome), bottom panel's search failed → `resolve_assets_generate` sees every primary `resolved`, returns satisfied, and is skipped. **The bottom panel never gets its generation attempt.** It runs only by luck — when some unrelated shot in the project still needs generation and drags the step into `run()`.

**Fix: teach `is_satisfied` the same question `run()` asks** — a shot with a `secondary_asset_plan` and neither secondary id set is not done. One clause, and it makes the existing `needs_secondary` code do what it was written to do.

**Fixed 2026-08-20.** `secondary_panel_done(shot, binding, done_states=)` is the shared question. `is_satisfied` requires it of every shot; `run()` uses the negation as `needs_secondary`. A search miss stamps `secondary_state=awaiting_generation`, so the search pass is satisfied and the generation pass is not — the bottom panel now gets its generation attempt without depending on some other shot still being unfinished. A recorded `failed` is done, so it is not retried forever (R18).

### 16.3 R18 — the bottom panel's failure is discarded entirely: no state, no error, no log

```python
except Exception:  # noqa: BLE001 - missing bottom panel degrades
    pass
```

**Three things are lost, and this is the only place in this step where that is true.** Every primary failure records `binding.state`, `binding.last_error` and `binding.attempts` — Principle 10 is *isolate* the failure, not erase it. Here:

1. **No record.** The migration added `secondary_asset_id` / `secondary_clip_id` and **no `secondary_state`**, so "attempted and permanently failed" is indistinguishable from "never attempted". `scratch.last_error` is populated by the resolver and then thrown away.
2. **No log line.** Nothing is emitted. A split shot silently becomes a single-image static shot, and the renderer's degrade path — correct and tested — makes the result look deliberate. ⚠ **A systematically broken bottom panel (a bad secondary query pattern, a licence gate excluding everything) produces plausible-looking videos and leaves no trace anywhere to find it by.**
3. **Both error classes collapse.** `TransientError` is an `Exception`, so a network blip gets the same treatment as a permanent miss and never reaches the outer handler's retry semantics. So does the budget cap's `PermanentError` — **a run that stopped because it hit the spend cap is indistinguishable from one that could not find a photograph.** That is the one failure this codebase is most careful about elsewhere (`check_budget`'s own docstring: *"a retry storm against a paid API is the single most expensive failure mode this system has"*).

**Fix: catch `TransientError` and `Exception` separately, log the degrade with the shot id and the reason, and persist it** — either a `secondary_state`/`secondary_last_error` pair, or at minimum append to `binding.last_error`. With R17's fix this also becomes the thing that stops a permanently-unfindable panel being re-attempted on every future run.

**Fixed 2026-08-20.** `secondary_state` / `secondary_last_error` columns (migration `c8f5d3b02e19`), copied on carry-forward. `TransientError` logs `resolve_assets.secondary_transient` and leaves state unset so the step retries. Any other `Exception` (including the budget cap) logs `resolve_assets.secondary_failed` and stamps `failed`. The render still degrades to a single image; it is no longer silent.

### 16.4 R19 — `_ScratchBinding` is a duck-typed stand-in for an ORM row, and R18 hides the failure mode

The bottom panel reuses `_resolve_one_fake` / `_resolve_one_real` by passing a hand-written object with seven attributes instead of a `ShotBindingModel`. **The attribute surface the resolve path touches is:** `asset_id`, `clip_id`, `state`, `rung`, `last_error`, `attempts`, `cost_cents`, `secondary_asset_id`, `secondary_clip_id`, **`shot_id`**.

`_ScratchBinding` defines the first seven. **`shot_id` is not defined** — today it is only read inside `_prewarm_video_frames`, which iterates real DB rows, so nothing breaks. ⚠ **But this is a live coupling with no test and no type check:** the day a resolver reads `binding.shot_id` (for a log line, a cache path, a metric), the scratch object raises `AttributeError`, R18's bare `except` swallows it, and **every split shot in the project quietly loses its bottom panel with no error anywhere.** Python's duck typing means neither mypy nor a review of the resolver would flag it.

**Fix: construct an unattached `ShotBindingModel` instead** — same fields, real type, and a missing attribute becomes an error the type checker sees. Or give `_ScratchBinding` the full surface and a comment tying it to the resolver's contract.

**Fixed 2026-08-20.** Deleted `_ScratchBinding`. The bottom panel now resolves against an unattached `ShotBindingModel` (`project_id`, `timeline_version`, `shot_id` set, never `session.add`'d). A missing attribute is a real ORM error, not a silent degrade.

### 16.5 R20 — the reuse-gap ledger never learns about bottom panels

The primary's resolve feeds the duplicate-image guard:

```python
used_hash = await self._resolve_one_real(...)
if used_hash is not None:
    used_at_s.setdefault(used_hash, []).append(shot_start)
```

The secondary's identical call **discards the return value.** So `used_at_s` — and therefore `reuse_gap_s(...)`, the mechanism that stops the same photograph appearing twice within a short window — is blind to every bottom panel. Two concrete consequences:

- The **same still can be the top panel of one shot and the bottom panel of another** a couple of seconds later, and nothing notices.
- A **later shot's primary can reuse an image already on screen as a bottom panel**, because that use was never recorded.

⚠ Split-screen makes this worse than it sounds: a split shot shows **two** images at once, so it doubles the on-screen image count in exactly the region of the timeline where a repeat is most visible — both panels are simultaneously in frame with whatever the neighbouring shots show. **Fix: capture the secondary's `used_hash` and append it at the same `shot_start`.** Two lines.

**Fixed 2026-08-20.** The secondary `_resolve_one_real` return value is appended to `used_at_s` at the same `shot_start` as the primary. A still already on screen as a bottom panel now penalises a later shot that would reuse it.

### 16.6 Smaller items, all verified, none blocking

- ⚠ **`framing=split` is handed to the Asset Planner for both panels with no instruction that it describes the COMPOSITE.** `_build_user_content` sends `framing={s.framing.value}` on the shot line, and the same line now carries `secondary_prompt`. The prompt file explains the two-plan structure well but never says "each panel is a single subject; `framing: split` is about the frame, not this photograph." A model that takes `framing=split` literally per panel writes a "split screen …" search query — which finds nothing on Commons — or generates a split image *inside* a split panel. Same shape as §14.9's Q6 finding: two instructions in one request with no stated precedence. One sentence in the prompt, or omit `framing` for split shots. **Fixed 2026-08-20.** Prompt now says each panel is one photograph; `framing: split` is the composite, not the search query.
- **Nothing ties `framing` to `camera.movement`.** The shot-planner validator now enforces `split_frame ⇔ secondary_prompt` in both directions (good), but `framing: split` with `movement: static`, or `split_frame` with `framing: wide`, both validate. Two fields expressing one idea with no cross-check. **Fixed 2026-08-20.** `split_frame ⇔ framing=split` is now a validator pair, same symmetry as the prompt. Test: `test_split_frame_with_wide_framing_is_rejected`.
- **No test covers a split shot inside a MULTI-shot run.** Both integration tests use a single-shot timeline, which exercises the dedicated `len(run) == 1 and split_in_run` path. The `_render_run_two_pass` path with a split shot plus an xfade neighbour — the more complex integration, and the one that has to keep "one stream per shot" true — is untested. The naming (`{run_stem}_s{index:03d}_top/_bot`) is index-unique so a collision looks unlikely, but that is an argument from reading, not a test. **Fixed 2026-08-20.** `test_split_shot_crossfades_with_a_neighbour` — split then a static neighbour, dissolve, duration 2.7 s, first-shot frame still red-over-blue.
- **Panel letterboxing on real archival material is untested aesthetically.** Each 720×1280 frame gives two 720×640 panels (≈9:8). A 3:2 archival photo lands 720×480 inside that, so ~25% of each panel is padding. Correct behaviour, matching the plan's "never a fake split," but whether two heavily-padded halves read as a deliberate comparison on real 1936 photographs is the same kind of judgement Q5 and A8 needed a human for — and it has not been made.
- **DRY_RUN exercises the composite properly** (`_resolve_one_fake` sets `asset_id`/`state` on the scratch, so a fake bottom panel resolves and renders), which is worth noting because it means the path is not generation-only.

### 16.7 What was checked and holds up

| claim | verified how |
|---|---|
| `ken_burns.py` still returns `None` for `SPLIT_FRAME` | unchanged — a split is not a `zoompan` expression, and the slice did not pretend otherwise |
| the composite is real, top and bottom, at the pixel level | the slice's own integration test extracts a frame and asserts red at y=40 and blue at y=200. **This is the right standard** — the same frame-extraction standard §12's punch-in work set |
| the degrade is real, not a fake split of one photograph | second integration test: one green image, both halves green, no split. Explicit and tested |
| motion on either panel degrades rather than breaking | `render_timeline` skips a MOTION secondary before it can reach `should_composite_split`, so `bot_kind` is `None`; the asset planner and its validator additionally force `preferred_type=image` on both panels |
| xfade still sees one stream per shot | the second input lives inside the per-shot encoder (C3's two-pass), so the run graph is unchanged and Track C's argv-length work is not disturbed. A single-shot split run is routed through the shot-stream path deliberately (`len(run) == 1 and split_in_run`) |
| the GIF-flatten gate applies to the second still without colliding | `ensure_still_image(..., shot_id=f"{shot_id}__split")` — a distinct id, so the flattened bottom panel cannot overwrite the primary's |
| both lower cache layers see the second panel | measured: shot-stream and run fingerprints both change on a swap, and both use `""` (not absent) when there is no secondary, so a later resolve cannot cache-hit the single-image encode |
| the migration is correct | nullable, both FKs, a real `downgrade()`, correct `down_revision` chain |
| a binding's second panel survives a re-plan | `ShotBindingRepository`'s carry-forward copies both new columns — easy to miss, and it was not missed |
| A20/A25 treat the new fields as acquisition fields | `_acquisition_fields_changed` covers `secondary_prompt`/`secondary_asset_plan`, and the locked-shot drift rejection was extended with them. **This is the invariant that would have been silently wrong** if only the renderer had been updated |
| the planner validation is symmetric | `split_frame ⇒ secondary_prompt` AND `secondary_prompt ⇒ split_frame`, both directions, in the same pass — the exact symmetry lesson Q7 raised about the rewrite's entity check, applied here without being asked |
| the asset planner's per-plan rules were shared, not copied | `_plan_field_violations` was extracted so primary and secondary plans are validated by one function. A duplicated copy would have drifted |

✅ **And the §12 entry itself is the most honest one in this log:** it volunteers the per-shot cost estimate, the missing gutter, the absent layout toggle, the missing bottom-panel override, and the still-open Q6/Q7/R15 items — without being asked, and before review. Two of the five findings above (R16's reachability, R17's contradiction) are only *findable* because the entry stated its claims precisely enough to check.

### 16.8 Recommended order

1. **R17** (`is_satisfied` learns about secondaries) — ✅ fixed 2026-08-20.
2. **R18** (record and log the degrade) — ✅ fixed 2026-08-20.
3. **R20** (feed the secondary's hash to `used_at_s`) — ✅ fixed 2026-08-20.
4. **R16** (fingerprint by assignment, not a sorted bag) — ✅ fixed 2026-08-20. Bottom-panel override is now unblocked on the cache side.
5. **R19** (real `ShotBindingModel` instead of the duck type) and §16.6's prompt/validator/multi-shot-test items — ✅ fixed 2026-08-20. Panel letterboxing on real archival photos is still a human judgement, same class as Q5/A8.

102 related tests green (fingerprint assignment, `secondary_panel_done`, shot planner framing, split+xfade neighbour, timeline-service carry-forward). Fingerprint-cache and generate-timeline regressions also green. **Stopped here for review of these fixes.** Next leftover remains R2's second half. A8 last. Parallax parked.

### 16.9 R16–R20 confirmed fixed — 2026-08-20

> **Method: re-ran the experiment that produced each finding.** The fingerprint claims were re-tested by calling `compute_render_fingerprint` with the panels exchanged, with two shots' assets exchanged, and with the bottom panel absent; the resolver findings were re-traced through `is_satisfied` / `run` / the scratch object; the migration graph was parsed offline to confirm a single head. **483 tests pass** — the whole `tests/unit` tree plus the four DB-free integration suites, up from 474 before the fixes (the nine new tests are R16's two swap cases, the multi-shot crossfade, and the reinterpreted order test among them). `ruff check` clean.

| | verified how | verdict |
|---|---|---|
| **R16** | `asset_content_hashes` is now `dict[str, str]` keyed by shot id, with a parallel `secondary_content_hashes` map, emitted as a `shot_media` list built by iterating `timeline.all_shots()` — **timeline order, no dict iteration, so I5 holds.** Measured: top/bottom swap **differs**, shot↔shot swap **differs**, missing bottom panel **differs**, identical inputs still identical | ✅ **fixed, and the pre-existing hole closed with it** |
| **R17** | `secondary_panel_done(shot, binding, done_states=...)` is now a module-level predicate called by **both** `is_satisfied` and `run`'s `needs_secondary` | ✅ **fixed** — see below on why this shape matters |
| **R18** | Migration `c8f5d3b02e19` adds `secondary_state` / `secondary_last_error`. `TransientError` and `Exception` are caught **separately**, both `logger.warning` with the shot id, both persist the error; transient leaves `secondary_state` null (so it retries), permanent marks `"failed"`. Carry-forward copies both new columns | ✅ **fixed** |
| **R19** | The duck type is gone: an **unattached `ShotBindingModel`**, with a comment on why it is never `session.add`'d (a flush would collide with the unique constraint). Full attribute surface, `shot_id` included | ✅ **fixed** |
| **R20** | `used_hash` is captured from the secondary resolve and appended to `used_at_s` at the same `shot_start` | ✅ **fixed, and then some** — see below |

#### Two fixes that are better than what the review asked for

1. ⚠ **R17 was fixed by extracting the QUESTION, not by adding a clause.** The finding was that `is_satisfied` and `run` disagreed about what "done" means. Patching `is_satisfied` alone would have fixed today's symptom and left two independent copies of the same predicate to drift apart again — which is precisely how the bug arose. `secondary_panel_done` has one definition and two call sites, so **the two cannot disagree a second time.** This is the §13-method lesson ("the resolver was verified but not the run that calls it") answered structurally rather than locally.
2. ⚠ **R20's fix also closes a case the review did not raise.** `reuse_gaps_s(used_at_s, shot_start)` for the bottom panel is computed **after** the primary has appended its own hash — so the bottom panel now sees the top panel's use, and **a split shot can no longer pick the same photograph for both of its own panels.** That was reachable before (two panels, one query pool, no shared ledger) and would have been the most visible possible duplicate: the same image stacked on itself, in one frame.

#### §16.6's smaller items — all four addressed

- **The `framing=split` collision is resolved in the prompt**, and it names both failure modes the review described: *"`framing: split` describes the composite frame the renderer will build, not this panel — do not search for 'split screen' and do not ask an image model to generate a split image inside a panel."* Chosen over stripping `framing` from the user content, which would have lost real signal for every non-split shot.
- **`framing` ↔ `camera.movement` is now cross-checked, symmetrically** (`split_frame ⇒ framing=split` and `framing=split ⇒ split_frame`), matching the shape the `secondary_prompt` check already had.
- **`test_split_shot_crossfades_with_a_neighbour`** covers the multi-shot-run path — the `_render_run_two_pass` + xfade integration that was previously verified by reading only.
- **Two R16 regression tests** (`test_swapping_top_and_bottom_panels_changes_the_fingerprint`, `test_swapping_two_shots_assets_changes_the_fingerprint`), and the old `test_asset_content_hash_order_does_not_matter` was correctly **reinterpreted rather than deleted** — it now asserts that dict *construction* order is irrelevant, which is the property that genuinely still holds.

#### Three notes carried forward, none blocking

1. ⚠ **`secondary_panel_done` reads the column through `getattr(binding, "secondary_state", None)`.** Now that the scratch object is a real `ShotBindingModel`, nothing needs the defensiveness — and it has a cost: if `c8f5d3b02e19` were ever unapplied, the attribute would resolve to `None`, `None` is not in `done_states`, so every split shot would be judged "not done" and **re-attempted on every run, including the paid generation rung** — a silent repeated spend instead of a loud `UndefinedColumn`. Prefer direct attribute access.
2. **A budget-cap stop now marks the bottom panel terminally failed** (`PermanentError` → `secondary_state="failed"`), so raising the cap and re-running will not retry it. That matches exactly how a cap-stopped **primary** behaves, so it is consistent rather than wrong — and R18's real complaint is answered, because `secondary_last_error` now carries the cap message instead of the failure being erased.
3. **The render fingerprint's payload key changed** (`asset_content_hashes` → `shot_media`), so every fingerprint computed before this fix is invalidated. Correct and harmless — a miss only ever means "render for real" — and the rename guarantees no accidental collision with an old digest. One re-render per existing project, same as the R2, captions, watermark and SFX additions each cost.

#### Still outstanding on split-screen, unchanged by this pass

**The aesthetic judgement.** Each 720×1280 frame yields two 720×640 panels, so a 3:2 archival photograph sits with roughly a quarter of its panel as padding. The behaviour is correct and deliberate ("never a fake split of one photograph"), but **whether two heavily-padded halves read as a deliberate comparison on real 1936 material is a human call that has not been made** — the same class of open question as Q5's pacing bands and A8's bake-off, and it does not compress into a test. §12's other four disclosed residuals (per-shot cost estimate, no gutter, no layout toggle, no bottom-panel override) also stand.

⚠ **The R16/override pairing is now safe to unpick in either order.** With assignment in the fingerprint, building the bottom-panel override no longer risks serving a stale render on its first use — which was the one sequencing constraint §16.8 flagged.
