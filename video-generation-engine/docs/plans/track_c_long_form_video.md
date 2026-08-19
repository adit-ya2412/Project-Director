# Track C — Long-Form Video (90 s → ~10 min) — Implementation Plan

> **Status:** Implementation started 2026-08-19. §12 steps 3 (helper), 4 (argv + tpad), 5 (C1 planning at length), and 6 (C2 narration concurrency + disk-fallback) landed — see §2.6 / §3.2a / §3.3 / §4.2a / §14.8. C3 remainder / C4–C7 production paths are unchanged. ⚠ **Reviewed 2026-08-19 (§14.9 / response §14.9a):** C1 and C2 confirmed; **no production-code change from this review.** R-C5's log sentence is corrected (§14.8 R-C1 row now says shipped mux video is `abs=0.10`, 5 ms proof is the dedicated single-shot test). The remaining R-C5 coverage gap (multi-shot dissolve exactness) is C3 remainder, not a C2 defect; the session-scoped lock is declined. Split out of [`motion_new_styles_and_long_form_videos.md`](motion_new_styles_and_long_form_videos.md) §6, which specified Track C in one table and seven rows; this document is that table turned into a buildable plan, with four scoping decisions taken and three of §6's own premises corrected against the real code.
> **Scope:** the seven C-items (C1–C7), plus **C8** (a scaling problem none of them named) and **§13 — the frontend**, which §1–§12 wrongly treated as a consumer rather than a deliverable. ⚠ **Read §13 before quoting any effort figure above it: Track C is ~26–29.5 days, not ~15–20** (measured 2026-08-19, up from an original ~25–28 guess — see the Verdict and §4.1a/§4.1b/§9.1 for what the C0/C8 probes actually found). Nothing about styles, motion, or script pre-flight — those are the parent document's Tracks A/B/D and are treated here as fixed context.
> **Related:** [`motion_new_styles_and_long_form_videos.md`](motion_new_styles_and_long_form_videos.md) §6/§7/§13, [`13_Implementation_Guide.md`](../13_Implementation_Guide.md) §M8/M9 and its Backlog, [`14_Captions_Plan.md`](../14_Captions_Plan.md).
> **Fixtures:** `m8_test_project` (13 shots), `captions_test_project` (19), `hinglish_final_project` (19), `hinglish_test_project` (14), `hindi_test_project` (11). **Every calibration number in this document comes from those five real projects.** There is no long-form fixture; C0's is **synthesised in Python** (§11, Q1) and the real planned one waits for C1.
> **Decisions:** fifteen, all taken 2026-08-18 — eleven below plus four frontend decisions in §13.2 (F1 no long-run notification, F2 ETag+slim payload+adaptive polling, F3 adaptive review screen, F4 one draft with timestamp deep links) — four scoping decisions in §1 (length range, no segment cache, scene-by-scene review, per-minute budget) and seven design decisions in §11 (C0 fixture, planning threshold, `Scene.act_id`, provider caps, budget reservation, final approval, argv measurement). ⚠ **§11 has no open questions left.** Q4 is **fully answered**: ElevenLabs concurrency **3**; OpenAI limits TPM not concurrency, and `gpt-5.6-terra` is **500,000 TPM / 500 RPM** — so the LLM cap is **8**. ElevenLabs Starter's monthly allowance is also confirmed (**60,000 chars/month, Multilingual v2**) — which surfaced a real durability fix, now §3.3. ⚠ **Nothing external remains unknown.**

---

## Verdict up front

**Track C is smaller than §6 claims, and its risk is concentrated in one place nobody measured.**

Three of §6's premises did not survive being checked against the code:

**1. C6 has no blocker any more.** §6 marks the orphan-run bug as *"a blocking dependency that is easy to under-rate… land it before the first long run, not after the first loss."* It landed: `reclaim_orphaned_runs` is called from `main.py`'s `lifespan` before the app serves a request. **Track C now has no prerequisites at all.**

**2. C3 is not "build segment rendering" — the renderer already segments and concats.** `group_into_runs` splits the shot list at every hard cut, `_render_run` renders each run to its own MP4, and the concat demuxer joins them with `-c copy`. That is precisely the architecture §6 proposed building. What is actually missing is narrower and different: the segment *boundaries are chosen by the planner's transitions*, not by anything the renderer controls — so a dissolve-heavy 10-minute video is **one single run of ~185 shots**, and that is exactly the case that crashes.

**3. The argv fix is not one line, and `-filter_complex_script` alone is not enough on Windows.** The measured growth is ~384 chars/shot, of which roughly 215 is the filter graph and 170 is the input arguments (long `storage/{uuid}/assets/{64-hex}.jpg` paths). Moving the filter graph to a file removes ~56% of the length — at 185 shots that takes ~71,000 chars down to ~31,500, against a 32,767 limit. **It lands inside the limit by about 4%**, which is not a fix, it is a coincidence. Both halves have to shrink.

**And the thing nobody measured is the encode.** §6's own Q3 probe measured 12.8s for 40 shots — but at 480×854, with solid-colour placeholders, and **every shot `STATIC`**, i.e. never touching the `zoompan` path that real archival shots almost all use. Extrapolating shots × pixels × an unknown zoompan multiplier gives a band of **roughly 2 to 9 minutes** of single-threaded encode for a 10-minute video. That 4.5× spread is the whole uncertainty in this track, and it decides whether `-threads 1` (which I5's byte-exactness test depends on) can survive long-form at all.

**⚠ Measured 2026-08-19 (§4.1a): the guess was low, there's a second axis, and the true figure for a real 10-minute video is ~18.6 minutes** (the probe rendered 8.46 min of output, so its 15.8 min reading understates by ~18%; the transferable number is **1.86× realtime** motion / **1.34×** static). **15.8 minutes**, not 2–9, for the realistic (Ken Burns) case against real archival photos at production resolution — the static baseline alone (11.4 min) already exceeds the whole guessed band, because the guess's shot/pixel multipliers underpriced real images relative to the placeholder stills they were calibrated on. **The zoompan multiplier itself came in lower than guessed (1.39×, not 2–4×)** — the miss is in the baseline, not in Ken Burns. Worse, **a single dissolve-heavy 185-shot run OOM-killed ffmpeg at ~6.7 GB resident** on first attempt — memory, not just time, is a real constraint nobody in §0–§11 asked about. **This overturns D2 as written**: 15.8 min is past the fallback trigger D2's own text set ("if 9 minutes rather than 2"), so per-run fingerprint caching is now the recommended default for C3's remainder, not a contingent maybe. ⚠ **The memory finding is no longer open either** — a same-day follow-up (§4.1b) isolated the cause (185 looping `-loop 1 -t` inputs vs. single-decode ones) and validated the fix by direct measurement: peak RSS 10.61 GB → 3.47 GB, ~8% faster too. Full detail and methodology: §4.1a/§4.1b.

| # | Item | Effort | Changed from §6 |
|---|---|---|---|
| **C0** | Measure the real encode wall (probe) | ~~0.5 d~~ **spent** | **done 2026-08-19 — §4.1a/§4.1b. Overturned D2, found an unanticipated memory constraint AND fixed it (validated), net +2.5 d of newly-visible C3 work** |
| **C1** | Planning at length, two-path, + §2.5 durability | **4–5 d** | +1 d — §2.5's durability gap, found via Q4 |
| **C2** | Narration concurrency + quota durability | **1.5 d** | cap is **3** (ElevenLabs Starter); +§3.3's disk-fallback cache fix |
| **C3** | Render at length | **4.5–6.5 d** | ⚠ **grew after C0** — D2 overturned (§4.1a): per-run caching + two-pass now in scope, not contingent. −0.5 d back: the memory sub-task (§4.1b) is done, with a validated fix in hand, not just scoped |
| **C4** | Asset reuse, temporal | 1.5 d | +0.5 d — the current penalty *degenerates*, it doesn't just weaken |
| **C5** | Scene-grouped review + partial approval | 3–4 d | +1 d — needs a new engine state |
| **C6** | Budget per minute of output | 1 d | unblocked |
| **C7** | Music at length | 1–1.5 d | **per-act, not per-scene** — 65 scenes makes §5.4's proposal wrong |
| **C8** | Timeline document growth | ~~1–2 d~~ **spent, 0 d follow-on** | **done 2026-08-19 — §9.1. Measured smaller than extrapolated (197 KB not 232 KB); diff/fingerprint costs sub-10ms. Verdict: nothing needed.** |

**Total ~18.5–21.5 d backend — and ~26–29.5 d including the frontend (§13.7), which every figure in this table excludes.** ⚠ Net change from C0+C8+§4.1b's memory test all landing this session: C3 grew 2–3 d → 4.5–6.5 d (+2.5 d net, after giving back 0.5 d for the memory sub-task closing with a validated fix rather than an open scope item), C8 shrank 1–2 d → 0 d follow-on (−1 to −2 d) — a probe cutting both ways in the same session, which is the point of measuring rather than guessing in either direction. §6 estimated 10–14. The remaining increase over §6 is C5 and honesty about C3's argv work; the decrease is dropping per-segment fingerprinting.

---

## 0. What is verified, what is calibrated, what is guessed

Marked so nobody downstream has to reverse-engineer the confidence, matching the parent document's §0 discipline.

**Verified by reading the code, 2026-08-18:**

- `reclaim_orphaned_runs` exists in `app/workflow/trigger.py` and is called from `main.py`'s `lifespan` before the app accepts requests. C6's blocker is closed.
- `render_timeline` (`app/renderer/slideshow.py:254`) already: probes every shot's media once, groups into runs via `group_into_runs`, renders each run to `work_dir / run_{i:03d}.mp4` in a **serial `for` loop**, and concatenates with the concat demuxer + `-c copy -fflags +bitexact`. Single-run output is a `.replace()`, not a re-encode.
- `run_ffmpeg` (`slideshow.py:84`) is a bare `create_subprocess_exec` wrapper. **There was no concurrency anywhere in `app/`** until 2026-08-19: `bounded_gather` / `reserve_then_gather` now live in `app/utils/bounded_gather.py` (§3.2a). Three of the four loops are wired: shot/asset planners via `bounded_gather` (C1, §2.6), TTS via `reserve_then_gather` (C2, §3.3). ffmpeg run encodes are still serial (C3 remainder). `as_completed` / `TaskGroup` still appear nowhere.
- `_render_run` pins `-threads 1` and `+bitexact` explicitly, for `tests/integration/test_render_determinism.py`'s byte-for-byte proof (I5). Not incidental — commented as required.
- `NarrationStep._synthesize_scene_alignments` unique-by-hashes scenes, restores from `{hash}.mp3` + `{hash}.alignment.json` when the DB row is gone, and pays through `reserve_then_gather` at cap 3. A missing sidecar (legacy mp3-only) still re-synthesises.
- The Scene Planner's user content (`app/planners/scene/planner.py:126`) embeds **every numbered fragment** in the prompt and requires the model to tile `1..N` exactly with at most `max_scenes` scenes.
- `settings.max_scenes = 12`, `max_shots_per_project = 40`, `max_video_duration_s = 90.0`, `project_budget_cap_cents = 1000`.
- `max_scenes` and `max_shots_per_project` are **structural** invariants in `Timeline._validate_structural_invariants` — always enforced, never exempted by `narration_locked`.
- Asset reuse is a **flat, global, binary** penalty: `already_used_hashes` is `list_content_hashes_for_project(project_uuid)` (every asset ever used in the project), and ranking applies `- 0.4 * (1.0 if hash in already_used else 0.0)`. No notion of *when* it was used.
- `TimelineService.approve` sets one document-level `status = APPROVED`. There is no per-scene or per-shot approval state.
- `ensure_still_image` writes to `work_dir / f"{shot_id}_still.png"` but **returns the original path unchanged** when `needs_normalising` is False — so a render's input paths are a mix of short work-dir names and long `storage/{uuid}/assets/{64-hex}.ext` ones.
- `work_dir = project_dir / "work"` (`render.py:195`), i.e. under `storage/{project_uuid}/`.

**Calibrated from the five real fixtures, 2026-08-18 (measured, not assumed):**

| fixture | chars | `N` frags | scenes | shots | chars/frag | frags/scene | shots/`N` |
|---|---|---|---|---|---|---|---|
| `m8_test_project` | 662 | 13 | 5 | 13 | 50.9 | 2.6 | 1.00 |
| `captions_test_project` | 876 | 19 | 6 | 19 | 46.1 | 3.2 | 1.00 |
| `hinglish_final_project` | 686 | 24 | 6 | 19 | 28.6 | 4.0 | 0.79 |
| `hinglish_test_project` | 696 | 20 | 5 | 14 | 34.8 | 4.0 | 0.70 |
| `hindi_test_project` | 483 | 10 | 5 | 11 | 48.3 | 2.0 | 1.10 |
| **mean** | | | | | **~42** | **~3.2** | **~0.9** |

**Projected from those constants** (14.4 chars/sec English, from the parent §3.6):

| target | chars | `N` frags | scenes | shots | vs today's caps |
|---|---|---|---|---|---|
| 90 s (today) | ~1,300 | ~31 | ~10 | ~28 | fits |
| 3 min | ~2,600 | ~62 | ~20 | ~56 | **`max_scenes` 12 ✗, shot cap 40 ✗** |
| 5 min | ~4,300 | ~103 | ~33 | ~93 | ✗✗ |
| **10 min** | **~8,640** | **~206** | **~65** | **~185** | ✗✗ |

⚠ **These are projections from five short scripts, and the frags/scene spread is 2.0–4.0 — a 2× band.** They are good enough to size the problem and choose thresholds; they are not good enough to set a hard cap on. Every one gets re-measured against the real long-form fixture (Q1) before any number in this document becomes a config default.

**Guessed, and flagged as such:**

- The encode extrapolation in §4. It multiplies a measured 12.8s by three factors, one of which (the `zoompan` multiplier) has never been measured at all. **This is the single number in this document most worth replacing with a measurement, which is why C0 exists.**
- Every day-figure.

---

## 1. The four decisions taken, and what each one costs

Put to the user as concrete scenarios rather than abstract preferences, 2026-08-18. Recorded here with consequences, so a later reader can see what was traded rather than only what was chosen.

### D1. Length: the pipeline switches strategy by script length. 90 s to 10 min are all normal.

**Chosen over** "3–5 min typical" (which would have made C1 a config change) and "10 min is the target" (which would have made the act layer unconditional).

**What it costs:** two planning paths instead of one, and a threshold that has to be defensible. **What it buys:** the 90-second path — the one every existing project and all five fixtures use — stays byte-identical, so long-form cannot regress short-form. Given the parent document's §13 review found three separate cases of a change to a shared path silently breaking a style, that is the right trade.

⚠ **The threshold is not a preference, it is an empirical question:** at what `N` does one-call scene planning actually degrade? Nobody knows — see Q2. Until measured, the plan uses `N ≤ 70` (≈3.5 min) for the single-call path.

### D2. Render: no per-segment fingerprint cache. Full re-encode on any edit; make it fast. — ⚠ OVERTURNED by C0's measurement, §4.1a

**Chosen over** per-scene segment caching (edit scene 7 → re-encode scene 7) and per-run caching.

**What it buys, and it is more than it looks:** per-scene segments would have forced segment boundaries onto scene edges, and a dissolve **cannot cross a concat-demuxer boundary** — so scene-aligned caching would have quietly constrained what transitions the Shot Planner is allowed to emit at a scene edge. That is a creative constraint imposed by a caching optimisation, which is the exact inversion the parent document's §2.2 warns about ("do not let the renderer decide camera behaviour… the Timeline stops describing what the video looks like"). Declining it keeps the renderer downstream of the Timeline.

**What it costs:** every edit re-encodes everything. That is only acceptable if §4's encode number lands at the low end of its band. **D2 is therefore conditional on C0's measurement, and this plan says so explicitly rather than treating the decision as closed regardless of the number.** If a 10-minute re-encode turns out to be 9 minutes rather than 2, per-run caching (which needs no new boundary rules, since runs already exist) is the fallback — and it is the *cheap* fallback, not the scene-aligned one.

**⚠ Measured 2026-08-19: 15.8 minutes for 8.46 min of output — i.e. ~18.6 minutes for a real 10-minute video, past the plan's own 9-minute trigger by 2×.** C0 (§4.1a) measured a realistic 185-shot dissolve-heavy render at **947.6s wall clock**, worse than the explicit number this section named as the threshold for abandoning full re-encode. **D2 as originally chosen does not survive its own stated condition.** The rejection reasoning above (scene-aligned caching constrains the planner's transitions) still holds and still rules out per-scene caching — but per-run caching does not carry that cost (runs are chosen by transitions already, not imposed by the cache), so it is not reopening the creative-constraint question, only accepting the fallback D2 always said it would need if the number came in high. **Per-run fingerprint caching is now the plan for C3's remainder (§12 step 9), not a contingency.** The dissolve-heavy single-run case (one run = all 185 shots, so any edit still invalidates the whole run) is real residual risk — see §4.1a's two-pass suggestion.

### D3. Review: scene-by-scene approval with bulk actions.

**Chosen over** draft-video-first review and auto-approve-with-exceptions.

**What it costs:** the expensive one of the four. A per-scene approval state is genuinely new machinery in the workflow engine — see §6, which is why C5 grew from §6's 2–3 d to 3–4 d.

**Why it is still right:** auto-approve inverts the one-gate design's own premise (the human *is* the check that replaced the killed automated constraint pass). And 200 individual decisions is not a review, it is a formality someone will click through — which produces the appearance of review without the substance.

### D4. Budget: cap scales per minute of output.

**Chosen over** a fixed ceiling and a per-minute-plus-motion-count pair.

**What it costs:** the number gets large. $10/90 s → ~$65 for 10 minutes, and a mis-planned run can now lose real money in one go. **This makes the pre-approval estimate load-bearing rather than informational** — see §7.

⚠ **The rejected third option is worth keeping in view.** Motion is ~50¢/shot against ~1–3¢ for a still, so motion count, not total shot count, is what actually decides the bill. A per-minute total cap alone permits a 10-minute project to spend its entire ~$65 on ~130 motion shots. A4's per-project motion cap (already built, per the parent §12) becoming length-aware is the natural companion, and §7 specifies it as such.

---

## 2. C1 — Planning at length

### 2.1 What breaks, precisely

The Scene Planner is one LLM call whose prompt contains **every fragment, numbered**, and whose output must tile `1..N` exactly. At `N`≈206 that prompt carries ~206 numbered lines (~8.6 KB of script text alone) and the model must produce ~65 scenes covering every index in order with no gap or overlap.

⚠ **The failure mode is not "the output is too long" — it is the tiling invariant.** `_make_validator` rejects any gap, overlap, or out-of-order range, and the repair loop feeds violations back. The parent document's own S2 section records that this exact class of ask — "reproduce a deterministic structure over many indices" — already failed twice on *short* scripts and is the reason the fragment-index interface exists at all. At 206 indices the probability of a clean tiling on the first attempt drops, the repair loop burns attempts, and `run_structured_with_repair` eventually raises. **This is a loud failure, not a silent one** (same as the parent §3.4's corrected finding), but it is a loud failure after a paid Director call.

Shot planning is already per-scene and needs no restructuring — only bounded concurrency (§2.4).

### 2.2 The two paths

**Path A — single call, `N ≤ 70`.** Exactly today's behaviour, unchanged, with `max_scenes` resolved by length rather than fixed at 12 (§2.3).

**Path B — hierarchical, `N > 70`.** Two passes, both reusing the machinery that already exists:

1. **Act pass.** The whole fragment list → 3–7 **acts**, each an ordered contiguous fragment range. Identical interface to the Scene Planner's own (contiguous index ranges, tiling-validated by the same rule), just coarser: 206 fragments into 5 acts is a judgement a model makes reliably, because there are 5 boundaries to choose rather than 65.
2. **Scene pass, per act.** The existing Scene Planner, called once per act on that act's fragments, with fragment indices **re-based to 1..M within the act** and `max_scenes` scaled to the act's share. Each call then sees ~40 fragments and produces ~13 scenes — squarely inside the range it already works at on the fixtures.

⚠ **Re-basing indices is the part most likely to be got wrong, and it has a precedent to copy exactly.** The Shot Planner already re-splits a scene's `narration_text` into its *own* locally-numbered fragments and converts ranges back to absolute character spans (`app/planners/fragments.py`'s "Shared with the Scene Planner" section). The act pass must do the identical thing one level up: local numbering into the model, absolute spans back out, conversion in code and never in the prompt. **Do not pass absolute fragment indices into a per-act call** — the model will see "fragments 84 to 122" and the whole point of S2 was to stop asking models to do index arithmetic.

**Acts persist as one flat field: `Scene.act_id: str | None` — DECIDED (§11, Q3).** Not a nesting level, not transient. They exist to bound one LLM call's fan-out, and they matter for exactly one other thing at render time: music (§8), which groups scenes by `act_id`. Additive, so every existing timeline stays valid with `act_id` absent, and `None` is the correct value for every project below the D1 threshold.

**The threshold itself (`N > 70`) is a deliberate guess, not a measured constant — DECIDED (§11, Q2).** Path B therefore gets built and used unconditionally above `N` = 70, accepting that if the real wall is nearer `N`≈150 then every 3-to-5-minute script pays for an act-pass call it did not need. ⚠ **The guess is safe only in this direction** — hierarchical planning works at any length, so switching too early wastes a call while switching too late is impossible. If this number is ever *raised*, measure first.

### 2.3 The constraint bundle becomes length-aware

`max_scenes = 12` and `max_shots_per_project = 40` are structural invariants (`_validate_structural_invariants`), so both must rise or nothing plans at all past ~90 seconds.

⚠ **`resolve_constraint_bundle(style)` already exists and already resolves exactly these bounds** (`app/script/styles.py`, parent §13.7). Length must enter *through that function*, not as a second, parallel resolution path. Adding a competing source for the same three numbers is how the parent document's R1 happened — two call sites resolving one invariant differently — and R1's fix was specifically to make that structurally impossible via a single shared resolver. **Extend `resolve_constraint_bundle` to take the script's `N` (or the estimated duration) alongside the style; do not add a `resolve_length_bundle` beside it.**

Derived from §0's table, to be replaced by real measurements:

| bound | 90 s | 3 min | 10 min | rule |
|---|---|---|---|---|
| `max_video_duration_s` | 90 | 180 | 600 | user-chosen target, not derived |
| `max_scenes` | 12 | 24 | **70** | `ceil(N / 3.2)` + headroom |
| `max_shots_per_project` | 40 | 80 | **220** | `ceil(N × 0.9)` + headroom |

⚠ **These interact with style.** `retention_fast` already overrides the shot cap to 58 for a 90-second video (~51 shots at 1.75s). At 10 minutes that style wants ~340 shots. Style override × length scaling must compose in one place, and the composition rule needs stating: **length sets the base, style multiplies it.** Not the reverse, and not "whichever is larger" — that silently discards one of the two.

### 2.4 Shot planning concurrency

Already per-scene, already independent per scene, already validated per scene. At 65 scenes the serial loop is 65 sequential LLM calls. Bounded concurrency (§3.2's shared helper) turns that into ~9 rounds at a cap of 8.

⚠ **The shot-cap check is inside the per-scene loop and accumulates `total_shots` across scenes** (parent §3.4). Under concurrency that accumulator becomes a shared mutable count across concurrent tasks — a race that would make the cap check non-deterministic. **Check the cap after the gather, over the collected result, not inside the concurrent body.** This is a small change that is very easy to miss and produces an intermittent, length-dependent failure if missed.

⚠ **There is a third per-scene loop, not two — the Asset Planner.** `app/planners/asset/planner.py:133` loops `for scene in scenes` with its own `run_structured_with_repair` per scene. So a 10-minute run makes **~65 shot-planner + ~65 asset-planner + ~65 TTS calls = ~195 sequential network round trips**, not the ~130 §3 originally accounted for. Asset planning is a fourth consumer of §3.2's helper, and — because it draws on the same per-model TPM budget as shot planning (§11, Q4) — **its cap is not independent of shot planning's.** The two loops must stay sequential *with respect to each other*, each internally concurrent. They already are; this is now a constraint to preserve rather than an accident.

### 2.5 The durability gap — 65 calls, no cache, one append

**Found while answering Q4, and it is the most expensive thing in C1.** Two facts compose badly at length:

- **Planner LLM calls have no cache of any kind.** Narration is cached on `compute_narration_content_hash`; `LlmCallRepository` is an *audit log*, not a cache. Verified by grep: no `prompt_hash`, no `get_by_prompt_hash`, nothing cache-shaped in `repair.py`, `shot/planner.py`, or `asset/planner.py`.
- **The shot planner runs every scene, then appends once.** `_run_real` calls `ShotPlanner.plan(scenes=...)` for all scenes and only then does a single `append_version`. Same shape in the asset planner.

**So a single transient — one 429, one timeout, one malformed response past its repair budget — at scene 64 of 65 discards all 63 completed calls and re-pays for them.** At 90 seconds with 5 scenes this is a rounding error nobody would notice. At 65 scenes across two loops it is ~130 chances to lose most of a planning pass, and ⚠ **concurrency makes it strictly more likely**, since more calls in flight means more TPM pressure means more 429s. C1 would otherwise ship a feature whose failure probability rises with the speedup it was built for.

**Two fixes, and they are complementary rather than alternatives:**

1. **Per-call retry with backoff, inside §3.2's helper.** A 429 is absorbed where it happens and never reaches step level. ⚠ This is the *load-bearing* one: it is the only fix that addresses the actual cause, and TPM-shaped limits are self-clearing within a minute by construction, so backoff is exactly the right instrument.
2. **Incremental persistence — append per scene (or per batch of N), not once at the end.** Makes a lost attempt cost one scene rather than sixty-four. ⚠ **Costs a full timeline-document write per scene**, which at 232 KB per version (§9, C8) is ~15 MB per planning pass at 185 shots. **So this fix and C8 are in direct tension and must be sized together** — batching (append every ~10 scenes) is the obvious middle, trading a bounded loss for a bounded write volume.

**Recommendation: build (1) with C1, and decide (2) against C8's real measured numbers rather than the 232 KB extrapolation.** (1) alone removes most of the risk; (2) without C8's numbers trades an unmeasured cost for a measured one.

### 2.6 — Landed 2026-08-19: Path A unchanged, Path B + concurrent planners

**Built.** Production planning now length-aware. Incremental persist (fix 2) is **not** built — C8 measured 197 KB/version and said do nothing; retry-in-helper (fix 1) is the durability that shipped.

| piece | where | why |
|---|---|---|
| `ConstraintBundle` | `resolve_constraint_bundle(style, n_fragments=)` | Length sets the base (`max(today's cap, f(N))`); style multiplies the shot cap (`58/40`). `n_fragments=None` is byte-identical to the old 90 s numbers. Unpackable as the old 3-tuple. |
| `Scene.act_id` | timeline schema, default `None` | Additive. Path A never sets it. Path B prefixes scene ids with `act_id` so per-act `sc_01` cannot collide. |
| Path B | `ScenePlanner._plan_hierarchical` at `N > 70` | Act pass (3–7 contiguous ranges) then per-act `ScenePlanner._plan_single` on the **act's script slice** (local 1..M, never absolute indices). Per-act calls go through `bounded_gather`. |
| Concurrent shot/asset | `ShotPlanner.plan` / `AssetPlanner.plan` | `planner_concurrency()` (8). Shot cap and video-shot cap run **after** the gather. `run_structured_with_repair(..., db_lock=)` serialises `llm_call` inserts on the shared session; the LLM HTTP call stays concurrent. The two loops stay sequential wrt each other (same TPM budget). |
| Preflight duration | `check_feasibility` | Uses the same bundle, so a 10-minute script is no longer blocked by the flat 90 s cap. A one-fragment run-on still is (N=1 keeps the 90 s ceiling). |

Tests: `test_styles` length/style multiply; `test_act_planner` tiling; `test_scene_planner` Path A `act_id is None` + Path B re-base; existing shot/asset cap tests now hit the post-gather check. 51 passed.

---

## 3. C2 — Narration concurrency

### 3.1 The change

`_synthesize_scene_alignments` is a serial loop; each scene's synthesis is independent, cached on `compute_narration_content_hash`, and already resumable. At 65 scenes, serial TTS is the longest wall-clock stretch in a long run.

Bounded concurrency, cap ~4–6 (ElevenLabs rate limits, Q4).

### 3.2 The shared piece — build it once

**There was no concurrency anywhere in `app/` until §3.2a.** C1's per-scene shot planning, C1's per-scene ASSET planning (§2.4), C2's per-scene TTS, and C3's parallel run encodes are FOUR consumers of one primitive. **The primitive is built (§3.2a); C1 and C2 are wired; ffmpeg runs stay serial until C3 remainder.** The helper has:

- a cap from config, **per consumer and of the right *kind* per consumer** — the four limits are not just different numbers, they are different quantities (§11, Q4):

  | consumer | what the provider actually limits | cap |
  |---|---|---|
  | TTS (C2) | **concurrent requests** — ElevenLabs Starter | fixed semaphore, **3** |
  | Shot Planner (C1) | **tokens/min** — OpenAI TPM | **8** (derived: 34% of `gpt-5.6-terra`'s 500,000 TPM; ceiling 16) |
  | Asset Planner (C1) | same TPM budget as above | ⚠ **shares** the shot planner's budget — run the two loops sequentially |
  | ffmpeg runs (C3) | local CPU | `cpu_count - 2` |

  ⚠ **A semaphore does not bound TPM.** Token cost per call varies (a `retention_fast` style fragment adds ~400 tokens; an act pass is ~3,600), so a count-based cap only approximates the real limit. Pair it with per-call backoff (§2.5) rather than trusting the count.

- **per-call retry with backoff** (§2.5) — the fix for the durability gap, and the reason a 429 must never reach step level;
- **deterministic result ordering** — results returned in input order regardless of completion order. Non-negotiable for C3, where run order is the video's order, and for C1, where scene order is the script's order. `asyncio.gather` already preserves order; the risk is someone reaching for `as_completed` and reintroducing I5's "no unordered iteration" violation;
- **per-item failure isolation** matching `ResolveAssetsStep`'s existing per-shot behaviour — one scene's TTS failure must not cancel the other 64. Bare `gather` cancels siblings on the first exception; `return_exceptions=True` plus explicit handling is the shape.

⚠ **Budget checks under concurrency.** `_synthesize_scene_alignments` calls `check_budget(already_spent, additional)` per scene, where `already_spent` is a DB read. Run 6 of those concurrently and all six can read the same pre-spend total and all six pass a check that only five should have — a classic TOCTOU that overspends the cap by up to `cap × per-item cost`. **Narration is cents-scale so the overshoot is small, but the identical pattern exists in `ResolveAssetsStep` around ~50¢ motion generation, where it is not small.**

**DECIDED (§11, Q5): reserve pessimistically before the gather** — the sequence becomes **reserve → check → submit**, so a sibling's reservation is already visible to the next check. This is not new machinery: `insert_pending` already persists `estimated_cost_cents` before anything else for M7's crash-recovery invariant, and reserving is that same write moved one step earlier. A failed submission's reservation is released by the existing `mark_failed` path. ⚠ **Must land before C2, not with it** — it is the one place in Track C where the wrong build order ships an overspend bug.

### 3.2a — Landed 2026-08-19: the helper, not the consumers

**Built, tested, wired for C1 and C2.** ffmpeg `_render_run` is still serial (C3 remainder). This step introduced the primitive those three would otherwise each invent.

| piece | where | why this shape |
|---|---|---|
| `bounded_gather` | `app/utils/bounded_gather.py` | One `asyncio.gather` + one `Semaphore`. Results in input order. Each item's exception is *returned* in that slot (`return_exceptions` shape) so one scene's failure cannot cancel the other 64. `as_completed` is absent on purpose (I5). |
| per-call backoff | inside the worker, **semaphore held across sleep** | §2.5: a 429 is absorbed where it happens. Releasing the slot on 429 would admit another call into the same exhausted budget; holding it is what makes the cap bite while TPM/concurrency clears. Reuses `app/workflow/retry.py::backoff_sleep`. Default 3 attempts (`settings.bounded_gather_max_attempts`), independent of the engine's step-level retries. |
| caps of the right *kind* | `settings` + three accessors | `narration_concurrency() → 3` (ElevenLabs concurrent requests). `planner_concurrency() → 8` (TPM approximation; **shot and asset planners share this one function** so they cannot drift). `ffmpeg_run_concurrency() → max(1, cpu_count - 2)`. `RateLimiter` is not imported — it paces calls/sec, which matches none of the four. |
| `reserve_then_gather` | same module | Q5 as a caller-supplied `reserve` / `check` / `submit` / `release` loop: serial reserve+check, then `bounded_gather` for submit. A `check` failure releases everything reserved so far and re-raises. A failed submit releases only that item. |

**Why the consumers were not wired with the helper.** The plan's own sequencing puts C1/C2/C3 after this step. Wiring narration concurrency before the helper existed was the overspend bug Q5 forbade; wiring it in the same PR as the helper would mix "the primitive works" with "narration is now concurrent," and a failure would not tell us which. C1 wired the planners; C2 (§3.3) wired TTS.

**Correction found while building, for C2/C3 to carry:** §3.2 claimed *"a failed submission's reservation is released by the existing `mark_failed` path."* That path today sets `status="failed"` and `error=...` and **does not zero `cost_cents`**. `total_cost_cents_for_project` sums every row regardless of status, so a reservation persisted via `insert_pending(estimated_cost_cents=...)` would stay in the spend total after `mark_failed`. `reserve_then_gather`'s `release` callback is therefore not a no-op wrapper around today's `mark_failed` — C2 (narration) and any concurrent generation path must pass a `release` that actually clears the reserved cents (zero `cost_cents` on a not-yet-billed row, or delete it). Do not "fix" `mark_failed` globally: a job that *was* submitted and then failed may have been billed, and keeping that cost is the conservative M7 behaviour. The distinction is reserved-but-never-submitted vs submitted-then-failed, and it belongs at the call site.

Tests: `backend/tests/unit/utils/test_bounded_gather.py` (17, no network). Pins ordering-under-reordering, the in-flight cap, isolation, TransientError retry vs PermanentError no-retry, Q5's "check sees prior reserves," release-on-halt, and that `asyncio.as_completed` / `RateLimiter(` are not called.

### 3.3 — Landed 2026-08-19: concurrent TTS + disk-fallback cache

**Built.** `_synthesize_scene_alignments` is the TTS consumer of `reserve_then_gather`. Narration has no `insert_pending`, so Q5's reservation is in-memory (`reserved_cents` accumulated serially, then the HTTP calls gather). That is the `release` that actually clears reserved cents — decrementing the running total, not wrapping `mark_failed` (which does not exist on this table and would not zero `cost_cents` anyway; §3.2a's correction).

| piece | where | why this shape |
|---|---|---|
| unique-by-hash gather | `NarrationStep._synthesize_scene_alignments` | Identical scene text is one paid call and one row (`content_hash` is globally unique). Cap `narration_concurrency() == 3`. |
| in-memory reserve → check → submit | `reserve_then_gather` callbacks | `check_budget` sees sibling reservations via `additional_cents=reserved_cents`. A `check` halt releases everything reserved so far; a failed submit releases only that hash. The HTTP call is outside the reservation loop, which is what Q5 bought. |
| `db_lock` on insert | around `narration_repo.insert` only | `AsyncSession` is not concurrent-safe. File writes and the provider call stay outside the lock. |
| `{hash}.alignment.json` sidecar | next to `{hash}.mp3` | Alignment lives in the DB row. After `clean_database` truncates `narration` the mp3 is still on disk but cannot rebuild `alignment`. The sidecar is the missing half. Written on every synth; back-filled next to an existing mp3 on a DB cache hit. |
| disk fallback | `_restore_row_from_disk` | Row missing **and** this project's mp3 **and** sidecar exist and are non-empty → re-insert, no provider call. mp3-only (every file written before C2) still re-synthesises — the bytes are not enough. Cross-project reuse stays the DB row; this path is the pytest-wiped-this-project case §3.3 named. |
| cost constant | `elevenlabs_cost_cents_per_character = 0.0103` | ₹8.80/1K Starter Multilingual v2. Was 0.018 (1.74× over). 10-minute narration is now ~$0.89, not ~$1.56. |
| duration cap | `_reconcile_and_append` | Routes through `resolve_constraint_bundle` (R1 leftover from C1). The flat 90 s cap would reject every long-form narration even after C1 authorised the length at plan time. Small-N still uses `settings.max_video_duration_s`. |

Whole-step failure is unchanged: any hash that fails after `bounded_gather`'s retries raises and the step fails. Siblings that already completed stay cached, so a retry only re-pays the failed hash. Not per-scene isolation — a missing scene still has no placeholder.

Tests: `tests/integration/test_narration_step.py` (sidecar written on synth, disk fallback after `DELETE`, mp3-only still pays, identical text one call, in-flight ≤ 3, one failure fails the step, cost constant) plus `tests/unit/workflow/test_narration_sidecar.py`. Existing eight narration-step tests still pass.

---

## 4. C3 — Render at length

### 4.1 C0 first: measure the encode. Nothing here is designable without it.

§6's Q3 probe measured **12.8s for 40 shots / 104.4s of output** — but at 480×854, with trivial solid-colour placeholder stills, and **every shot `STATIC`**, so the `zoompan` path was never exercised. Real archival shots are mostly Ken Burns or punch-in, and `_ken_burns_filter` scales to a 1.6× oversized working canvas (1152×2048 at production resolution) and resamples it **every frame**.

The extrapolation, with its factors named so each can be challenged:

| factor | value | basis |
|---|---|---|
| shots | 4.6× | 185 / 40 |
| pixels | 2.25× | (720×1280) / (480×854) |
| `zoompan` vs `scale+pad` | **2–4× (guessed)** | never measured |
| **total** | **~130–530 s** | |

**So: somewhere between 2 and 9 minutes of single-threaded encode for a 10-minute video.** That 4.5× spread is the entire uncertainty in Track C, and it decides D2.

**C0 (0.5 d) — DECIDED (§11, Q1): the fixture is synthesised in Python, not planned.** Build one ~185-shot Timeline object directly in code at production resolution, with real archival photos already on disk, realistic camera movements, and dissolve-heavy transitions (the worst case for §4.3's parallelism). No LLM call, no asset resolution, no spend — exactly the shape the parent document's own Q3 probe used. Run the real, unmodified `render_timeline`.

Report: total wall clock, per-run breakdown, and **the same run with every shot forced `STATIC`** — the difference between those two *is* the zoompan multiplier, measured rather than guessed. Do it on **Linux, in the real `backend/Dockerfile` container**, not on Windows.

⚠ **Capture the real argv length in the same run — DECIDED (§11, Q7): measure it even though §4.2's fix makes it non-threatening.** One log line, and it closes the parent document's Q3 remainder rather than retiring it as irrelevant, so the next thing that lengthens the command (split-screen's second input per shot, a deeper storage root) can be reasoned about instead of re-probed.

⚠ **What a green C0 does *not* prove.** This fixture says nothing about planning quality at length (§11 Q2's territory, deliberately unmeasured) or about real asset variety (C4's). Do not let it be read as "long-form works."

### 4.1a — C0 measured, 2026-08-19: the guess was low, and there's a second axis nobody named

**Run:** `backend/scripts/c0_probe.py`, inside the real `backend/Dockerfile` container (Linux 6.6, WSL2), against a synthesised 185-shot/65-scene Timeline at production resolution (720×1280, 30 fps), real archival JPGs from `tests/fixtures/hinglish_final_project_media/` cycled across all shots, every shot DISSOLVE-joined except the last (`group_into_runs` → **1 run**, confirmed). "Motion" = a realistic cycle of `SLOW_ZOOM`/`SLOW_PUSH`/`PULL_BACK`/`PAN`/`PUNCH_IN`; "static" = every shot's camera forced to the `STATIC` default, everything else identical. Real, unmodified `render_timeline` and `run_ffmpeg`; only `run_ffmpeg` was wrapped (not altered) to time each invocation and capture its argv.

| | wall clock (`render_timeline`, incl. probing/normalising) | pure ffmpeg encode | argv | argv chars |
|---|---|---|---|---|
| **motion** (realistic Ken Burns mix) | **947.6 s (15.8 min)** | 943.9 s | 391 args | 76,689 |
| **static** (every shot forced `STATIC`) | **682.4 s (11.4 min)** | 679.0 s | 1,131 args | 63,749 |
| **zoompan multiplier (motion/static)** | **1.39×** | | | |

⚠ **Review addendum, 2026-08-19 — the headline figure understates the finding by ~18%, because the probe did not render ten minutes.** `DURATIONS = [2.5, 3.0, 3.5, 4.0, 3.2]` cycled over 185 shots sums to **599.4 s raw**, and D5's overlap arithmetic subtracts 184 dissolves × 0.5 s, so the actual **output is 507.4 s — 8.46 minutes**, not 10. Reading 947.6 s as "the 10-minute case" therefore prices an 8.5-minute video.

**The number to quote is the ratio, not the total** — it is the only form that transfers to another length:

| variant | encode | output | **encode : output** |
|---|---|---|---|
| motion (realistic Ken Burns mix) | 943.9 s | 507.4 s | **1.86× realtime** |
| static (every shot `STATIC`) | 679.0 s | 507.4 s | **1.34× realtime** |

| target output | motion encode | static encode |
|---|---|---|
| 90 s (today) | ~2.8 min | ~2.0 min |
| 3 min | ~5.6 min | ~4.0 min |
| 5 min | ~9.3 min | ~6.7 min |
| **10 min** | **~18.6 min** | **~13.4 min** |

**So a genuine 10-minute video is ~18.6 minutes of encode.** That is further past D2's 9-minute trigger than §4.1a's own text claims, and it strengthens rather than changes the conclusion. Per-shot cost, for future extrapolation: **5.1 s/shot motion, 3.7 s/shot static** at 720×1280/30 fps on real archival JPEGs — use these, not the 12.8 s placeholder measurement, as the baseline for any further estimate.

**The guess was directionally wrong in a way worth stating plainly.** §4.1's band was **~130–530 s (2–9 min)**, built by multiplying a 12.8 s placeholder-still measurement by a *guessed* 2–4× `zoompan` factor. The real `zoompan` multiplier (**1.39×**) is *lower* than the guessed range — but the real **static** baseline (679 s) is already far above the entire guessed band, because the guess's other two factors (shots ×4.6, pixels ×2.25) badly underpriced what real, full-resolution, variably-sized archival JPGs (32 KB–597 KB, decoded and rescaled per shot rather than being the near-free solid-colour blits the 12.8 s figure was taken on) cost relative to the placebo-colour stills the original 12.8 s number came from. **Lesson for future extrapolations in this document: a multiplier applied to a measurement taken on synthetic input inherits that input's cheapness in every factor, not just the one being varied.**

⚠ **Correction to this paragraph's own mechanism, 2026-08-19.** An earlier draft explained the expensive baseline by saying real JPEGs are "scaled to a 1152×2048 working canvas even for the *static* path." **That is wrong and was verified wrong:** `WORKING_CANVAS_SCALE = 1.6` (→ 1152×2048) is read **only** by `_ken_burns_filter`; `_normalize_filter` — the static path — scales straight to 720×1280 (`scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:…`). The conclusion stands unchanged (real, variably-sized archival JPEGs cost far more to decode and rescale than solid-colour placeholders); only the cited mechanism was wrong. Recorded rather than silently edited, because "the static path also pays the oversized-canvas cost" would have been a false premise for anyone later trying to optimise it.

**Argv:** 76,689 chars for the motion variant, close to §4.2's own ~71,000-char projection (within 8%) — confirms the crash is real and, on Windows, would exceed `CreateProcess`'s 32,767-char limit by 2.3×. Not new information, but no longer a projection.

**⚠ New finding, not anticipated anywhere in §0–§11: memory, not just time, is a real constraint on a single dissolve-heavy run at this length.** The first attempt at the **static** variant was OOM-killed by the Linux kernel (confirmed via `dmesg`: `oom-kill`, `task=ffmpeg`, `anon-rss:6720368kB`) at 13.8% of the target run length, against this dev machine's *default* WSL2 VM memory ceiling (7.2 GB — Docker Desktop's default 50%-of-host allocation on a 14.8 GB machine). The motion variant had already completed successfully in the same environment, so memory growth is not simply proportional to "how expensive per-frame the filter is" — a single 185-input `-filter_complex` with a 185-node cascading `xfade` chain appears to accumulate memory as the run progresses regardless of which per-shot filter feeds it, and the static variant failing where the motion variant had already succeeded is the observation that needs explaining — see the correction and the better-supported hypothesis immediately below. Raising the ceiling to 12 GB let the static variant complete; the true peak RSS for either variant was not captured (docker's `--rm` removes the container before stats can be pulled post-hoc), so **the real number is somewhere above 6.72 GB and below 12 GB, for one render process, on one project.**

⚠ **Correction to the OOM's stated cause, 2026-08-19 — the page-cache explanation cannot be right.** The kernel reported **`anon-rss:6720368kB`**: that is 6.72 GB of **anonymous** (non-file-backed) memory inside the ffmpeg process itself. **Page cache is file-backed and evictable — the kernel reclaims it rather than OOM-killing** — so "leftover page-cache pressure from the first run" cannot produce an anon-rss OOM, and the inference drawn from it (*"back-to-back long-form renders on the same host compound"*) is **unsupported and should not be planned around.**

**A better-supported hypothesis, and the argv counts are the evidence.** The two variants opened structurally different inputs, which the arg counts show exactly: **motion = 391 args, static = 1,131 args** — that is `-i path` (2 args/shot) versus `-loop 1 -t X -i path` (6 args/shot), ×185 shots plus ~21 trailing. Every shot in this probe is a **still**; the difference is that `_render_run` gives a Ken-Burns shot a single-decode `-i` input (`zoompan`'s own `d=` sets the length) while a `STATIC` shot gets a **looping** `-loop 1 -t` input that generates frames until its cutoff. **So the static variant held 185 looping image decoders open, the motion variant 185 single-frame ones.**

That explains what the page-cache theory cannot: **why the CHEAPER variant died and the more expensive one survived.** It attributes the memory to input shape rather than to filter cost, neighbour runs, or elapsed progress.

⚠ **It is a hypothesis, not a measurement** — peak RSS was never captured for either variant, so this is inference from the arg shapes plus the failure ordering. **But it is cheap to test and it points at a cheap fix:** a still that `ensure_still_image` has already normalised does not need `-loop 1 -t` at all if its length can come from elsewhere in the graph, so the remedy may be an input-shape change in `_render_run` rather than a memory-limit bump in deploy config. **Test this before raising any production memory limit** — the two answers lead to completely different work.

⚠ **The OOM is a dev-machine artifact in its specific numbers (WSL2's default allocation) but not in its substance.** Nothing in §0–§11 measured or even asked about memory, and production render workers (containers, k8s pods) are routinely memory-limited in the same few-to-low-double-digit-GB range this OOM occurred in. A finding this size deserves its own line item rather than a footnote — **recommended: fold a memory ceiling into C0's own scope retroactively is too late, so add it to C3's remainder (§12 step 9) as an explicit sub-task: measure peak RSS properly (`docker stats` polled during a run that isn't `--rm`'d until stats are captured, or `/usr/bin/time -v`), across both variants, before deciding whether long-form rendering needs a memory limit raised in production deploy config, a hint in the runbook, or an architectural fix (bounding how many concurrent inputs one `filter_complex` opens at once, rather than one input per shot in the run).**

### 4.1b — §12 step 9a done early, 2026-08-19: hypothesis tested, confirmed, and a validated fix in hand

**Two follow-up runs closed the memory question completely, ahead of C3's own scheduled sequencing** (cheap enough — no shared-fixture dependency, no code changes to production paths — to do alongside C8's probe rather than wait for steps 5–8).

**Run 1 — re-measured peak RSS for both original variants** (`RUSAGE_CHILDREN.ru_maxrss`, read immediately after the single `run_ffmpeg` call each variant makes — exact, no extra tooling, no `--rm` workaround needed):

| variant | peak RSS |
|---|---|
| motion (Ken Burns, single-decode `-i` inputs) | **4.96 GB** |
| static (`-loop 1 -t` looping-decoder inputs) | **10.61 GB** |

**This alone falsifies the page-cache theory a second, independent way and confirms the input-shape hypothesis directionally**: the "cheaper" filter (static) used more than double the memory of the "more expensive" one (motion's 1.6×-canvas `zoompan` resampling), in the same process, same environment, same run immediately after the first — nothing "compounded" from a neighbour run; the two variants simply hold structurally different numbers of bytes open at once.

**Run 2 — isolated the variable.** A standalone experiment (`static_altinput` in `c0_probe.py`, not wired through `_render_run`/`render_timeline` — deliberately outside production code, since no real `Shot`/`Camera` combination produces this input shape today): identical 185 shots, images, durations, and dissolve transitions as the `static` variant, but every input given as a single-decode `-i path` (Ken Burns's own shape) and held for its duration via `tpad=stop_mode=clone:stop_duration=X` **inside the filtergraph** instead of `-loop 1 -t` at the demuxer.

| variant | peak RSS | encode time | argv |
|---|---|---|---|
| static (`-loop 1 -t`) | 10.61 GB | 691.0 s | 1,131 args / 63,749 chars |
| **static\_altinput (`-i` + `tpad`)** | **3.47 GB** | **635.5 s** | 391 args / 68,747 chars |

**Confirmed, not merely supported: switching the static path's input shape cuts peak memory by ~3× (10.61 GB → 3.47 GB) and is incidentally ~8% faster (691.0 s → 635.5 s)** — the looping demuxer input was costing both memory and wall-clock, not trading one for the other. `_render_run`'s `-loop 1 -t X -i path` construction for `STATIC`/`SPLIT_FRAME` stills should be replaced with `-i path` + a `tpad=stop_mode=clone:stop_duration=<duration_s>` stage prepended to `_normalize_filter`'s existing scale/pad/setsar chain — the same "one decode, generate duration inside the graph" shape `zoompan`'s `d=` parameter already gives every Ken-Burns shot, extended to the plain static path that has never used it.

**This resolves §12 step 9a's fork decisively: it is a `_render_run` input-shape fix, not a production memory-limit change.** At 3.47 GB peak for the full 185-shot dissolve-heavy `static` case (vs. motion's 4.96 GB, now the higher of the two as expected — Ken Burns' oversized working canvas is a real, inherent cost of the visual effect, not a bug), a single long-form render worker no longer needs anywhere near the 10+ GB the unfixed path demanded. **Recommendation: land this fix as the first sub-task of C3's remainder (§12 step 9), ahead of per-run caching and the two-pass work** — it is now known-cheap (one input-construction branch in `_render_run`), independently beneficial (faster *and* lighter regardless of caching strategy), and removes the memory axis as a blocker for whichever of per-run-caching/two-pass C3 ultimately ships.

**Consequence for D2 — this is the number D2 said would decide it.** §1's D2 stated its own trigger explicitly: *"If a 10-minute re-encode turns out to be 9 minutes rather than 2, per-run caching... is the fallback."* The measured number is **15.8 minutes** for the realistic case — worse than the stated fallback trigger, not better. **D2 as written ("no per-segment fingerprint cache, full re-encode on any edit") should not ship as the default for the dissolve-heavy case.** Per-run fingerprint caching (§4.3's already-preferred lever, and the *cheap* fallback per D2's own text — "needs no new boundary rules, since runs already exist") is no longer a contingent nice-to-have; on this measurement it is what makes C5's scene-by-scene review workflow (§6) usable at all — a human fixing one shot in a 65-scene review session cannot be made to wait 15.8 minutes per fix when the render's own run-level architecture already supports caching the runs that didn't change. **Recommendation: build per-run fingerprint caching as part of C3's remainder (§12 step 9), not as a maybe.** ⚠ **And the asymmetry here is the same one §4.3 already found for parallelism, which makes it a pattern rather than a coincidence: run count is chosen by the planner's transitions, so BOTH levers help exactly the style that did not need help.**

| style | transitions | runs at 185 shots | cache granularity | cost of fixing one shot |
|---|---|---|---|---|
| `retention_fast` | cuts only | **~185** | one shot per entry | re-encode **1 shot** (~5 s) |
| `documentary_archival` | mostly dissolves | **1** | all 185 shots in one entry | re-encode **everything** (~18.6 min) |

**Per-run caching solves the edit-latency problem completely for the fast style and not at all for the archival one — and archival stretched to long-form is the case Track C actually exists for** (§4.3's own crash finding says the same thing about the same style). So per-run caching should still ship, because it is nearly free given runs already exist and it fully covers one real style; but ⚠ **it must not be recorded as "C3's edit-latency fix," because for the common long-form style it changes nothing.**

**Therefore §4.3's two-pass option is promoted from "the more attractive remaining lever" to the actual answer for the dissolve-heavy case:** cache each shot's normalised/zoompanned **stream** individually and re-chain only the `xfade`s on an edit. That yields per-shot granularity **regardless of transitions**, which is the only property that helps both styles. Its cost (a second encode of every frame) is now much easier to justify against a measured 18.6 minutes than against the guessed 2–9. ⚠ It also interacts with the memory hypothesis above — a two-pass graph opens far fewer simultaneous inputs in the `xfade` pass, so it may resolve both findings at once. Worth checking together rather than separately.

This does not fully solve the dissolve-heavy single-run case (one run covering all 185 shots means one shot's edit still invalidates the whole run's cache entry) — that residual is exactly why §4.3's two-pass option (render each shot's normalised/zoompanned stream once, cache *those*, re-chain only the `xfade`s on edit) is now the more attractive of its two remaining levers, not `-threads 1` relaxation, which trades away I5 for a problem a cache can solve without touching determinism at all.

### 4.2 The argv crash: two halves, and one is not optional

Measured growth is ~384 chars/shot; Windows' `CreateProcess` limit is 32,767. At 185 shots that projects to **~71,000 chars** — 2.2× over. Linux's `ARG_MAX` (~2 MB) is not threatened at any plausible length.

The composition, from the probe's own numbers:

| part | ~chars/shot | at 185 shots |
|---|---|---|
| filter graph fragment (normalise/zoompan + xfade) | ~215 | ~40,000 |
| input args (`-loop 1 -t X -i <path>`) | ~170 | ~31,000 |

**Fix half 1 — `-filter_complex_script <file>`.** Moves the graph out of argv into a file. Removes ~56%.

⚠ **This alone is not a fix.** It leaves ~31,000 chars against a 32,767 limit — inside by about 4%. That is not headroom, it is luck, and it degrades with the length of the storage root: input paths are `storage/{36-char-uuid}/assets/{64-hex}.jpg` under an installation-dependent prefix, so moving the project to a deeper directory reintroduces the crash. A fix whose validity depends on where the repo is checked out is not a fix.

**Fix half 2 — short, relative input paths.** Run ffmpeg with `cwd=work_dir` and reference every input by a short local name (`s000.png`, `s001.mp4`). `ensure_still_image` already writes normalised stills into `work_dir` — but it **returns the original long path untouched** when `needs_normalising` is False, and motion clips bypass it entirely, so today's input list is a mix. Making every input resolve to a short work-dir name (symlink, or copy where symlinks are unavailable) takes the input-args half from ~170 to ~25 chars/shot: **~4,600 chars at 185 shots.**

Both halves together: ~4,600 chars of argv plus a filter file. That is a fix with two orders of magnitude of headroom, and it holds at any length on any platform.

⚠ **`escape_ffmpeg_filter_path` still applies inside the filter file.** The parent §12 already records one Windows drive-letter-colon bug caught in a hand-written filter string. A filter *file* does not change ffmpeg's own escaping rules — and relative paths sidestep the drive-letter case entirely, which is a second, independent reason to prefer half 2.

### 4.2a — Landed 2026-08-19: both argv halves + the tpad memory fix, together

**Why together, not argv first then tpad later.** Both live in `_render_run`. After tpad, *every* still is `-i path` (STATIC no longer has a 6-arg `-loop 1 -t X -i` branch), so landing tpad in the same change deletes the input-shape split the argv work would otherwise have had to preserve and then rip out. Step 9a's "land tpad first in C3 remainder" is therefore done here, out of listed order, for the same reason 9a itself ran early: it is independently beneficial and cheaper folded than sequenced.

| piece | what | why this shape |
|---|---|---|
| Half 1 — filter file | graph written to `work_dir / run_NNN.filter`; argv carries a 2-token flag + the short filename | Removes ~56% of argv. The slideshow graph has no embedded paths, so `escape_ffmpeg_filter_path` is unused here; relative names still sidestep the drive-letter case for anything that later *does* land in the file. |
| Half 1 flag | `filter_graph_file_flag()`: ffmpeg **≥ 9** → `-/filter_complex`; **&lt; 9** → `-filter_complex_script` | ⚠ **The plan's own `-filter_complex_script` does not exist on ffmpeg 9** (this Windows box, gyan 9.0: `Unrecognized option 'filter_complex_script'`). Debian bookworm in `backend/Dockerfile` is 5.1 and still has the old flag, and does not understand `-/`. Version-dispatched, cached per binary. Do not hardcode either name. |
| Half 2 — short names | `stage_short_input`: symlink → hardlink → copy into `s000.jpg`; `run_ffmpeg(..., cwd=work_dir)` | `ensure_still_image` still returns the long path when the file is already a still; motion clips never went through it. Staging every input is what makes half 2 hold regardless. |
| tpad (§4.1b) | STATIC/SPLIT_FRAME: `-i` + `tpad=stop_mode=clone:stop_duration=frames/fps` after scale/pad/setsar, before fps | **Order follows the measured probe, not the earlier "prepended to scale" sentence in §4.1b.** `c0_probe.py::run_static_altinput_variant` is the validated graph (10.61 GB → 3.47 GB). `hold_s` is `frame_count / fps`, the same duration-to-frames arithmetic Ken Burns already uses. There is no `-loop` branch left in `_render_run`. |
| argv log | `render.run_argv` with `arg_count` / `argv_chars` / `shots` | Closes Q7 on every real run, not just C0. |

`still.py` still flattens GIF/animated formats to a single PNG — without `-loop` that is no longer "ffmpeg would reject `loop`", it is "an animated stream would feed `tpad`/`zoompan` more than one frame." Same gate, restated reason.

Tests: `tests/unit/renderer/test_slideshow_argv.py` (flag dispatch, tpad order, staging, argv contains neither the graph nor the long path). Integration: `test_render_determinism` / `test_render_ken_burns` / `test_render_motion_clips` — 17 passed against real ffmpeg 9, including I5 byte-identity across two independent encodes.

### 4.3 Parallel run encodes — and the case where they buy nothing

Runs are independent ffmpeg processes; each pins `-threads 1` and `+bitexact`; concat order is by index. **Running them concurrently cannot change any individual run's output bytes**, so I5 holds and `test_render_determinism` keeps passing. Straightforward via §3.2's helper, capped at ~`cpu_count - 2`.

⚠ **But run count is decided by the planner's transitions, not by the renderer — and the crash case is the case with no parallelism available.** `group_into_runs` starts a new run at every hard cut:

| style | transitions | runs at ~185 shots | parallelism | argv crash |
|---|---|---|---|---|
| `retention_fast` | cuts only | **~185** | excellent | structurally immune |
| `documentary_archival` | mostly dissolves | **as few as 1** | **none** | **exposed** |

So for the dissolve-heavy long-form case — archival montage stretched to 10 minutes, which is the most likely thing anyone actually makes — there is exactly one ffmpeg process, single-threaded, and §4.3 offers it nothing. **Run-level parallelism helps precisely the style that did not need help.**

**If C0 lands at the high end, the levers are, in order of preference:**

1. **Per-run fingerprint caching** (D2's stated fallback). Needs no new boundary rules — runs already exist — and helps the second render, not the first.
2. **Two-pass within a long run:** render each shot's normalised/zoompanned stream to an intermediate in parallel, then chain the `xfade`s over pre-rendered intermediates. Genuinely parallelises the expensive part (per-frame resampling) even in a single run. ⚠ **Costs a second encode of every frame**, so it is a win only if the first pass parallelises better than the second pass costs — arithmetic that C0's numbers will settle, not this document.
3. **Relax `-threads 1` for long renders only.** Cheapest by far and directly attacks the bottleneck. ⚠ **This breaks I5's byte-exactness test, and that test is load-bearing** — it is what makes the render cache provably safe rather than probably safe. Not to be done as a quiet config change. If it is taken, it needs its own decision record and a replacement test (e.g. same-duration/same-frame-count rather than same-bytes).

**Recommendation: do not choose between these now.** They are ordered by preference and gated on one measurement that costs half a day.

---

## 5. C4 — Asset reuse at length

### 5.1 The penalty does not merely weaken — it degenerates

Today: `already_used_hashes = list_content_hashes_for_project(project_uuid)` — **every asset used anywhere in the project** — and ranking subtracts a flat `0.4` if a candidate is in that set. Binary, global, monotonically growing.

§6 notes the current system "already repeats a photo twice inside 41s". The long-form failure is worse than more of that:

- At shot 20 of 185, the used-set is small; the penalty discriminates.
- At shot 150, most topically-relevant assets are already in the set. **Nearly every candidate carries the same `-0.4`, so the term becomes a constant** — and a constant subtracted from every candidate changes no ranking at all. The penalty silently stops working exactly when repetition matters most.

⚠ **This is a quality cliff that presents as "the ranker got worse later in the video", with nothing in the logs to explain it.** Not a nit.

### 5.2 The fix: a window, not a set

Replace the global set with a **temporal window** — assets used within the last *W* seconds of rendered time (or the last *K* shots), keyed off `compute_shot_start_times`, which already exists and is already D5-overlap-aware.

- A photo reused 8 minutes apart in a 10-minute documentary is **fine**, and arguably good — it is a callback. The current rule penalises it identically to a reuse 3 seconds later.
- A photo reused twice inside 40 seconds is the actual defect.

**Suggested shape:** graded rather than binary — full penalty inside *W*, decaying to zero beyond it. Start at `W ≈ 60 s` and a full penalty larger than today's 0.4 (a *near* reuse deserves a harder penalty than the current flat one, precisely because far reuse is no longer being punished for free).

⚠ **`W` is uncalibrated and this is a taste judgement dressed as a parameter.** It needs eyes on a real long render, same class as the grade tuning the parent §9 flags as non-compressible human time. Ship a defensible default, expect to change it.

⚠ **Interaction with `retention_fast`:** tripling shot count for the same runtime means three times as many shots competing for the same asset pool inside any window. Fast styles need either a larger candidate pool per shot or a shorter `W`, and probably both. Do not tune `W` on a documentary render and assume it transfers.

---

## 6. C5 — Scene-grouped review and partial approval

### 6.1 What exists

One approval: `TimelineService.approve(project_id, version)` sets a single document-level `status = APPROVED`. `GET /progress` returns a flat `shots` array. There is no per-scene or per-shot approval state anywhere.

### 6.2 What D3 requires

**Progress becomes scene-grouped.** Additive: keep the existing flat `shots` array (nothing that consumes it breaks) and add a `scenes` array carrying, per scene, its id, fragment range, shot ids, per-state counts, and approval state. ⚠ Order by `timeline.all_shots()` order — scene then shot — never by `shot_id`; the `/progress` endpoint already had to fix exactly this ordering assumption once.

**Per-scene approval state.** The new machinery, and the expensive part. `metadata.approved_scenes: list[str]` (scene ids), written by a new `POST /{project_id}/scenes/{scene_id}/approve` via `append_version(produced_by=HUMAN, owns={"metadata.approved_scenes"})`.

- The dotted `owns` path is already supported — `_is_owned` matches ancestor prefixes, so `metadata.approved_scenes` grants exactly that field and not all of `metadata`. Precedent: `metadata.grade_style` (parent §13.5).
- **The gate is satisfied only when every scene id appears in the set.** That is the one line that turns 65 approvals into one gate, and it keeps the run's single-gate model intact rather than introducing 65 gates.

⚠ **Approving a scene must not freeze it against later regeneration.** A25's `asset_locked` already exists and already conflicts with A20 in a documented way; scene approval must be a *review* record, not a second locking mechanism, or the two will disagree and the parent document's A25/A20 note becomes a three-way problem.

**Approval is final — no un-approve. DECIDED (§11, Q6).** The set is monotonic: once a scene id is in `metadata.approved_scenes` it stays. This buys the largest simplification available in C5 — **no reverse edge in the workflow state machine**, which today has no notion of moving backwards from a post-approval step.

⚠ **The cost is real and lands on this section, not on the engine.** There is no way to record "I approved this and I was wrong," and at 65 scenes reviewed in one sitting that will happen. **So the per-shot override path must be reachable from the scene row itself** — one click from where the mistake is noticed, not a separate screen. Q6 promoted this from an affordance to a **requirement of C5**; a scene-grouped view that only groups and approves, without the repair path in the same row, ships the cost without the mitigation.

**Bulk actions.** "Regenerate every failed shot in this scene" — a batch wrapper over the existing per-shot endpoints. ⚠ **The Backlog's missing batch endpoint stops being an ergonomic nit here** (the parent §1 says the same about A6). At ~50¢ per motion shot, a bulk regenerate over a 12-shot scene is a **$6 click**. It must return an estimate and require confirmation, not fire on the first press.

⚠ **Q6's irreversibility raises the stakes of the bulk actions specifically.** "Approve all remaining scenes" is now an irreversible $0 action that gates an irreversible ~$65 one, and it will sit in the same toolbar as "regenerate all failed in this scene" — a reversible $6 one. **Two irreversible-but-opposite actions and one expensive-but-recoverable one must not share a confirmation pattern.** Distinguish them in the UI, or the cheap click and the costly one become the same gesture.

**The draft is still the right artifact to review against** even though D3 chose scene-by-scene as the mechanism — a 480p draft of 10 minutes is the only way to judge pacing, and pacing is the thing per-shot review structurally cannot see. Scene-grouped approval and draft-first review are complements, not the alternatives the question framed them as; build the grouping, and link each scene to its draft timestamp.

---

## 7. C6 — Budget per minute of output

### 7.1 The change

`project_budget_cap_cents = 1000` becomes a per-second-of-target-output derivation: `cap = ceil(target_duration_s × cents_per_second)`, with `cents_per_second` set so 90 s still resolves to 1000 (≈11.1 ¢/s → ~$65 for 10 min). Existing projects land on exactly today's number, which is what makes this safe to roll out.

### 7.2 What D4 makes load-bearing

At $65 a mis-planned run is a real loss, so two things stop being informational:

**The pre-approval estimate.** `estimate_project_cost_cents` already exists and already uses `ShotBinding.state == "awaiting_generation"` to count what will *actually* be generated rather than what the plan nominally says (the Task 5 fix). At long-form scale that estimate needs to be **confirmed by the human before the generation pass runs**, not merely displayed on a progress screen. ⚠ Note its own documented limitation: a shot with no binding yet falls back to the primary-strategy guess, so the estimate is least accurate exactly at the start of a fresh project — which is when it is being shown. Say so in the UI rather than presenting a number that looks firmer than it is.

**A length-aware motion cap.** Per §1's D4 caution, a total cap alone lets one project spend ~$65 on ~130 motion shots. A4's per-project motion cap (built, parent §12) should scale with length too, but **sub-linearly** — a 10-minute video does not need 6.7× the motion of a 90-second one to read as motion-rich, and motion is the line item that decides the bill.

⚠ **The `check_budget` TOCTOU from §3.2 matters most here.** Concurrent motion submissions each reading the same pre-spend total can overshoot by `concurrency × 50¢`. Small at cap 4; not small if anyone raises the cap.

---

## 8. C7 — Music at length: per-act, not per-scene

### 8.1 §5.4's own proposal is wrong at this scale, by its own reasoning

The parent §5.4 says M8's one-bed-per-video decision reopens past two or three minutes, and that per-scene scoring becomes right, "and the input for it is already present (`scene.emotion`)".

**At ~65 scenes, per-scene music is 65 track changes in 10 minutes — one every 9 seconds.** That is not dynamic, it is the "choppy rather than dynamic" failure M8's original decision was protecting against, arrived at from the opposite direction. §5.4's reasoning was sound for the 3-minute case it was written about and does not survive extrapolation to 10 minutes.

**The right unit is the act** (§2.2) — 3–7 beds across 10 minutes, one change every 1.5–3 minutes. And this is what makes `energy_arc`, which the Director already writes and which a single flat bed structurally cannot express, meaningful for the first time.

⚠ **This is the one place acts must exist at render time, not just at planning time** — which is why Q3 was a real design question and not an implementation detail. **Settled (§11, Q3): `Scene.act_id`**, so `select_music` groups scenes by that field and needs no new document structure. ⚠ **`energy_arc` still has no structurally enforced home** — per-act beds make it *observable* for the first time, but the field remains Director-written prose nothing validates.

**Below the D1 threshold there are no acts, so the answer there is simply today's one bed.** Clean: `N ≤ 70` → one bed; `N > 70` → one bed per act.

### 8.2 The library can support this, but only just

Measured against the real 54-track manifest: **min 62 s, median 149 s, max 2193 s; 20 tracks ≥ 180 s, only 4 ≥ 300 s.**

- Per-act beds of 1.5–3 minutes are well served by the 20 tracks ≥ 180 s.
- A *single* bed under a 10-minute video needs 600 s and only 4 tracks reach it, so the existing `-stream_loop -1` loop would run 4× on the median track — §6's C7 row, confirmed with real numbers.
- ⚠ **The 6 moods × 3 energies taxonomy has only 3 tracks per cell.** A 10-minute video wanting 5 acts that happen to share a mood and energy has 3 candidates for 5 slots — so either an act repeats a bed, or act-level selection must be allowed to move across the energy axis within one mood. Decide it deliberately; repeating a bed at act 4 that played at act 1 is fine, repeating consecutively is not.
- **`bpm` is `null` for all 54 tracks**, so §5.3's tempo-fit ranking has nothing to rank on. Independent of Track C, but per-act selection is the first feature that would actually benefit from it.

---

## 9. C8 — Timeline document growth (not in §6's list)

**Measured:** the real 13-shot `m8_test_project` timeline document is **16,245 bytes — ~1,250 bytes per shot.**

| shots | bytes/version |
|---|---|
| 13 (today) | 16 KB |
| 60 (3 min) | 73 KB |
| 185 (10 min) | **232 KB** |

`append_version` writes a **full copy** of the document on every append (I3 immutability — correct, and not to be changed). There are 29 `append_version` call sites across the workflow steps and API. A normal run appends 6–8 versions; every per-shot human override at the gate appends another.

**So a 10-minute project's version history is ~2 MB before any human touches it, and a review session with 50 per-shot regenerations adds ~12 MB.** Per project.

⚠ **This is not a crash, which is exactly why it will not be noticed until it is expensive.** Three consequences worth sizing before long-form ships:

- **DB growth.** Linear in shots × appends. 232 KB rows are fine for Postgres; hundreds per project across many projects is a capacity question nobody has asked.
- **`find_additive_violations` runs a full recursive diff of old against new on every append** — O(document) per append, so O(shots × appends) per project. Correct and worth keeping; just no longer free.
- **`compute_render_fingerprint` dumps the whole document** on every render and every draft. Also fine, also no longer free.

**Suggested scope (1–2 d):** measure the real cost at 185 shots rather than extrapolating from 13 (the per-shot constant may not hold — `asset_plan.search_queries` and prompts are the bulk and may not scale linearly); then decide whether anything is needed at all. **Plausibly the answer is "nothing, but now it is known"**, which is a legitimate outcome for a scaling item and better than discovering it during a demo.

### 9.1 Measured, 2026-08-19: the "nothing, but now it is known" outcome, confirmed

**Run:** `backend/scripts/c8_probe.py` — a 185-shot/65-scene Timeline built with realistic field content (prompt/`intent_text`/`asset_plan.search_queries` sampled from the real `m8_test_project` fixture's actual shots, not filler text), serialized with the exact compact encoding `compute_render_fingerprint` itself uses (`json.dumps(..., sort_keys=True, separators=(",", ":"))`), so the byte count reported is the one that actually lands in Postgres.

| | bytes | bytes/shot |
|---|---|---|
| real 13-shot `m8_test_project` (re-measured, same encoding) | 16,245 | 1,250 |
| §9's linear extrapolation to 185 shots | 231,179 | 1,250 |
| **185-shot realistic-content timeline, measured** | **197,265** | **1,066** |

**The per-shot constant does not hold, but in the safe direction.** §9 flagged the risk that free-text fields (`prompt`, `search_queries`) might scale *worse* than linearly; measured, they scale slightly *better* — fixed per-scene/per-shot structural overhead (ids, enums, framing/camera objects) amortises over more shots, so real bytes/shot drops from 1,250 to 1,066 rather than climbing. **231 KB was the wrong number by 15%, in the reassuring direction.** Version-history volume is correspondingly lower than §9's own worst case: **~1.38 MB for a normal 7-version run, ~11.2 MB for a review session with 50 per-shot overrides** (vs. the ~2 MB / ~12 MB §9 estimated from the extrapolation) — same order of magnitude, not a new number to plan around.

**The other two consequences §9 named are not free, but they are not a problem either:**

| operation | measured cost, 185 shots |
|---|---|
| `find_additive_violations` (one scene-approval-shaped diff, old vs. new) | **0.67 ms** |
| `compute_render_fingerprint` (full document) | **6.52 ms** |

Both are sub-10ms at the largest size Track C targets. Neither shows up on a user-facing latency budget next to a 200+ms API round trip, let alone an 18.6-minute render.

**Verdict, matching §9's own predicted best case: nothing is needed.** No batching, no partial-diff optimisation, no fingerprint caching. **DB row growth (~11 MB per heavily-reviewed long-form project) is the only real number here, and it is a capacity-planning fact, not an engineering task** — worth a line in a future ops/scaling review if projects accumulate at volume, not a Track C deliverable. C8 closes as measurement-only, 0 d of follow-on implementation.

---

## 10. Cross-cutting, and what long-form does *not* break

**What holds up unchanged, verified:** the fragment-index interface (S1/S2) scales fine — it is index arithmetic in code, and C1's act pass is the same pattern one level up. Per-shot failure isolation in `ResolveAssetsStep` already handles 185 shots the same way it handles 13. The narration content-hash cache makes C2 safe and resumable by construction. `reclaim_orphaned_runs` makes a 40-minute run survivable. The concat demuxer already joins segments losslessly. `narration_locked` already exempts measured durations from planning bounds at any length.

**Two invariants to hold explicitly through this track:**

- **I5 / determinism.** §4.3's option 3 is the only item in Track C that touches it, and it must not be taken quietly.
- **I1 / the Timeline describes the video.** D2's reasoning was specifically to avoid a caching optimisation constraining what transitions a planner may emit. The same test applies to anything else added here: if a render-side decision starts limiting creative output, it is the wrong side of the line.

**One thing that gets harder in every direction:** cost. Motion at ~50¢/shot, fast-cut tripling shot count, long-form multiplying it again. The parent document's Backlog item *"LLM calls are never costed"* also becomes more visible as C1 fans planning out from 4 calls to ~70.

---

## 11. Questions closed — all seven answered 2026-08-18

Put to the user as scenarios, with the consequence of each option stated. Recorded with what each costs, so a later reader sees the trade and not only the choice. **No open questions remain in this plan.**

### Q1 → Synthesise the C0 fixture in Python; the real planned fixture waits for C1

Build the ~185-shot Timeline directly in code — real archival photos already on disk, realistic camera movements, dissolve-heavy transitions (the worst case for §4.3). No LLM call, no asset resolution, no spend, available immediately.

**Why this was the right call and not merely the cheap one:** the real-fixture option was **circular** — a real 185-shot planned project cannot exist until C1 raises `max_scenes` past 12, and C1's design depends on C0's answer. The stretched-fixture option would have been actively misleading for C4, where duplicating 13 assets 14× makes every shot a reuse by construction. Synthesising answers the encode question completely and answers nothing else, which is exactly the scope C0 needs.

⚠ **What this fixture explicitly cannot tell us:** anything about planning quality at length (Q2's territory) or real asset variety (C4's). Do not let a green C0 be read as "long-form works."

### Q2 → Skip the measurement. Build Path B, switch at `N > 70`.

**Chosen over** measuring the real breaking point at `N` = 60/100/150/200 (~$1 of LLM, ~1 hour).

⚠ **Recorded honestly: `N ≤ 70` is now a deliberate guess, not a measured constant, and this plan is choosing to build on it.** Two consequences, accepted up front:

- **Every 3-to-5-minute script pays for an act-pass LLM call that may be unnecessary.** If the real wall is at `N`≈150, Path B does nothing for scripts between 3 and 7 minutes except add a call, a validation surface, and an index re-basing step. That cost is small and recurring rather than large and one-off, which is why it is acceptable — but it is a cost.
- **The threshold cannot be defended if it is ever questioned.** Anyone asking "why 70?" gets "projected from five short fixtures" as the honest answer.

**This is safe in the direction that matters:** hierarchical planning works at *any* length, so switching too early wastes a call and switching too late is impossible. The failure mode of a wrong guess here is waste, never breakage — which is what makes skipping the measurement defensible rather than reckless. ⚠ **It would not be defensible in the other direction** (a threshold guessed *above* the real wall), so if this number is ever raised, measure first.

### Q3 → `Scene.act_id: str | None` — a flat field, not a nesting level

Acts persist into the Timeline as one optional string on the existing `Scene`.

- **Additive**, so every existing timeline and all five fixtures stay valid with `act_id` absent.
- Music groups scenes by `act_id` with a one-line groupby (§8), so acts reach render time without the renderer learning a new structure.
- `None` means "no acts" — the correct value for every project below the D1 threshold.
- No `schema_version` bump, no change to `all_shots()`, no change to the fingerprint payload shape, and none of the 29 `append_version` call sites need re-checking.

**Rejected: a real `timeline.acts[].scenes[]` nesting level.** It would have given `energy_arc` a structurally honest home, at the cost of a schema bump, every traversal helper, every `owns=` ownership path, and every existing fixture. ⚠ **`energy_arc` therefore still has no first-class home** — per-act music (§8) is the first thing that makes it *observable*, via `act_id` grouping, but the field itself remains Director-written prose nothing structurally enforces. Noted rather than solved.

**Also rejected: transient acts** (music deriving spans from runs of consecutive same-emotion scenes instead). That would have let music spans and planning acts disagree — a 5-act video yielding 11 music spans, with the bed changing mid-act for no reason a viewer can perceive.

### Q4 → ANSWERED IN FULL. ElevenLabs concurrency 3; `gpt-5.6-terra` is 500,000 TPM → LLM cap 8.

**My guesses (TTS 4–6, LLM 8) are both withdrawn.** One was too high, the other was the wrong *kind* of number. Same discipline as the parent document's A3 Kling duration check — which found the live schema differed from what the plan assumed — and ⚠ **the parent document has now been wrong twice about an external API by not looking (Pixabay's non-existent music API; Kling's unset `generate_audio` default).** Declining the third opportunity is what turned up the TPM finding below, which no amount of reasoning would have produced.

**Why the caps matter more than they look.** A 429 becomes a `TransientError`, which fails the **whole step** and retries it. Narration survives that cheaply — the content-hash cache makes already-synthesised scenes free on the retry. ⚠ **Planning does not: planner calls have no cache at all, and the shot planner does 65 calls before a single `append_version`.** See §2.5, which exists because of this answer.

**ElevenLabs: Starter plan, concurrency limit 3.** Firm number, supplied directly. **My guess of 4–6 was too high** — C2's cap is **3**, so 65 scenes is ~22 rounds rather than ~11. Half the speedup I assumed, and the correct number.

**OpenAI: the constraint is not concurrency at all — it is TPM.** The user supplied their project rate-limit page: per-model **tokens/min** and **requests/min** (e.g. 200,000 TPM / 500 RPM on `gpt-3.5-turbo`; 10,000 TPM / 500 RPM on `gpt-4`). OpenAI does not publish a concurrent-request ceiling. **This invalidates the shape of my own §3.2 proposal for the LLM half:** a semaphore of 8 bounds *in-flight calls*, which is not the quantity being limited.

**`gpt-5.6-terra` — the configured planning model — is 500,000 TPM / 500 RPM.** Confirmed from the user's own rate-limit page, 2026-08-18. **This is the best case available on that page**, and it closes the question that could have reshaped C1: the catastrophic scenario needed a limit near the `gpt-4` row's 10,000 TPM, and nothing in the gpt-5.x family is close (the lowest planning-plausible rows are `gpt-5-chat-latest` at 30,000 and the `*-pro` variants at 50,000 TPM / **50 RPM**).

⚠ **Useful detail from the same row: `gpt-5.6-terra`'s shared-limits group contains only itself.** So `settings.openai_vision_model` (`gpt-4o-mini`, a separate row) draws on a **different** budget — depiction checks and vision constraint calls do not compete with planning for TPM. **The §3.2 warning that shot-planner and asset-planner caps are not independent still holds** (both are terra), but it does not extend to the vision path.

**Derived cap: concurrency 8, with headroom to 16.**

| concurrency | TPM used | % of 500k | RPM used | % of 500 |
|---|---|---|---|---|
| 4 | ~86,000 | 17% | 48 | 10% |
| **8 (recommended)** | **~172,000** | **34%** | **96** | **19%** |
| 12 | ~258,000 | 52% | 144 | 29% |
| 16 (ceiling at 70% headroom) | ~344,000 | 69% | 192 | 38% |

**At concurrency 8, a 10-minute run's ~195 planning calls take ~2 minutes instead of ~16 serial** — and sit at a third of the token budget, leaving room for the per-call variance (style fragments, the act pass) that a count-based cap cannot model. ⚠ **Do not start at 16.** The 70% target already absorbs variance; 8 leaves room for a second project planning concurrently, which nothing in the single-instance assumption prevents.

⚠ **One residual unknown, not material to C1:**

1. ~~**ElevenLabs Starter's monthly character allowance**~~ — **ANSWERED 2026-08-18: 60,000 characters/month on Starter for Multilingual v2 (₹8.80 per 1K).** ⚠ **This turned out to be tighter than "a quota footnote" and it changes one thing in this plan** — see §3.3 below, which exists because of it.

**§3.3 — The narration quota is a real long-form constraint, and one line of code decides how often you pay it twice**

| | chars | quota consumed |
|---|---|---|
| 90-second video (today) | ~1,300 | 2.2% |
| **10-minute video** | **~8,640** | **14.4%** |

**So Starter allows ~6.9 ten-minute videos per month with zero re-synthesis — or ~3.5 if each one gets a single voice or speed retry.** `voice_id` and (once R8 lands) `speed` are both part of `compute_narration_content_hash`, so either change re-synthesises all 65 scenes at full cost.

⚠ **The sharp edge: the narration cache is keyed on a DATABASE ROW, with no fallback to the file on disk.** `narration.py:204` reads `narration_repo.get_by_content_hash(...)` and synthesises whenever the row is `None` — it never checks whether the mp3 for that exact content hash is already sitting in `storage/{project}/narration/`. And `tests/conftest.py`'s autouse `clean_database` **truncates every table**, including `narration`.

**So a `pytest` run between two long-form sessions silently costs 8,640 characters — 14% of the monthly quota — even though every audio file is still on disk, byte-identical, under the right name.** At 90 seconds that same accident costs 662 characters and nobody notices; this is the standing "pytest truncates the shared Postgres" hazard (parent §7) with a price tag attached for the first time. ⚠ Note the tests themselves are safe — they use the fake narration provider — the loss is to *real* runs whose cache rows a test run wiped.

**Recommended fix, small and it pays for itself the first time: a disk-existence fallback in the cache check.** If the row is missing but `storage/{project}/narration/{content_hash}.mp3` exists and is non-empty, re-insert the row from the file instead of re-synthesising. The content hash already guarantees the bytes are the right bytes — that is the entire premise of the cache — so this adds no new correctness assumption, only durability. **Fold it into C2**, since C2 is already touching this loop. ⚠ **Landed 2026-08-19 with one extra file:** the mp3 is not enough — `alignment` is JSONB, not recoverable from audio — so C2 also writes `{content_hash}.alignment.json` beside the mp3 and restores only when **both** exist. mp3-only legacy still re-synthesises. See §3.3.

**Two smaller findings from the same page:**

- ⚠ **`elevenlabs_cost_cents_per_character` was 0.018, a ~1.74× over-estimate.** Real: ₹8.80/1K ≈ ₹76 (~$0.89) per 10-minute video. Config implied ~$1.56 (₹132). **Corrected 2026-08-19 to 0.0103** (C2 / §3.3). Narration is still ~1.4% of the §7 per-minute cap either way.
- **Flash/Turbo is 2× the quota on the same Starter plan** (1,20,000 vs 60,000 included — ~13.9 ten-minute videos/month) at half the per-character price, **and** a 40,000-character per-request limit instead of 10,000. ⚠ **This is worth a deliberate look for long-form specifically, not a silent switch:** it must be gated on (a) a listening test against the Hinglish/Devanagari fixtures, since `eleven_multilingual_v2` is the current pick precisely for multi-script quality, and (b) confirming Flash supports the `/with-timestamps` endpoint that caption alignment (D2) depends on. **A model change is a taste-and-verification decision, not a cost optimisation** — same class as the grade tuning the parent §9 flags as non-compressible human time.

⚠ **Related but distinct, and CLOSED — the PER-REQUEST character limit.** Checked against ElevenLabs' published table, 2026-08-18: `settings.elevenlabs_model = "eleven_multilingual_v2"` (`config.py:95`) allows **10,000 characters per text-to-speech request** (~10 min of audio). **This is a non-issue as built**, because narration is synthesised **per scene**, not per script — measured across all five fixtures, a real request is **44–305 characters**, and a 10-minute project averages ~133 (8,640 / 65 scenes). Roughly 33× headroom on the average, ~14× on a generously long single scene.

⚠ **But it is a live trap for exactly the optimisation someone will reach for at this scale.** At 65 scenes, "batch the narration into one request and save 64 round trips" is a tempting idea — and it *would appear to work*: a 10-minute script is ~8,640 characters, **under** the 10,000 limit. It breaks at roughly **11.5 minutes of output**, which is just past this track's own target. So a change that passes every test at 10 min fails on the first 12-minute script.

**Record this as a reason, not just a limit:** the per-scene TTS design exists for M8's caching and resumability, but it is **also** what makes long-form narration possible at all under `eleven_multilingual_v2`. Anyone consolidating those requests must switch to a higher-limit model first (`eleven_flash_v2_5` at 40,000) and confirm it still supports the `/with-timestamps` endpoint the caption alignment (D2) depends on — which is a materially bigger change than "save some round trips."

**Narration cost, for C6's arithmetic:** `elevenlabs_cost_cents_per_character = 0.0103` × ~8,640 chars = **~$0.89 of narration per 10-minute video**, about 1.4% of the ~$65 per-minute-scaled cap (§7). (Was 0.018 → ~$1.56 / 2.4%, corrected C2.) ⚠ **So the monthly character quota, not the cost, is the binding constraint on narration** — and a voice retry doubles the characters while barely moving the dollar figure, which is exactly the shape that makes a quota easy to exhaust without noticing on a cost dashboard.

**R8's outstanding check now has a concrete target:** the parent document's *"speed support on the configured ElevenLabs model is unverified"* means specifically `eleven_multilingual_v2`, and `ElevenLabsNarrationProvider` currently sends only `{"text", "model_id"}` in its payload (`elevenlabs.py:76`) — so adding `speed` is a payload change to that exact model's schema, not a generic one.

**The arithmetic, from real prompt line counts and the §0 fixture calibration:**

| loop | calls at 65 scenes | ~tokens/call | ~total |
|---|---|---|---|
| Shot Planner (86-line base prompt dominates) | 65 | ~1,750 | ~114,000 |
| Asset Planner (111-line base prompt dominates) | 65 | ~1,790 | ~116,000 |
| **planning total, one 10-min run** | **~130** | | **~230,000 tok** |

**Concurrency translated into TPM**, assuming ~5 s per call (12 calls/min per slot):

| concurrency | ~TPM | vs 200,000 | vs 10,000 |
|---|---|---|---|
| 1 | ~21,000 | fine | **2× over** |
| 3 | ~64,000 | fine | **6× over** |
| 8 | ~172,000 | 86% — at the edge | **17× over** |

⚠ **If the planning model's TPM is anywhere near the 10,000 on the `gpt-4` row, long-form planning cannot run at all — not even serially.** That is the single reason unknown 1 above has to be closed before C1, and it is a scroll on a page the user already has open.

**Why "no rate-limit issues today" is true and does not transfer.** A 90-second run makes ~15 planning calls totalling roughly 25,000 tokens spread over a minute or two — about 10% of a 200,000 TPM budget. A 10-minute run makes ~130 and burns ~230,000. **That is a 9× increase, and it crosses a 200,000/min line the moment it is bursted rather than spread.** The absence of a problem at 90 seconds is not evidence about 10 minutes; it is evidence that the budget was never approached.

**Design consequences, folded into §3.2:**

- **TTS: a fixed semaphore of 3.** Concurrency is genuinely what ElevenLabs limits, so a semaphore is the right instrument and 3 is the right number.
- **LLM: the cap must be *derived* from the model's TPM, not chosen as a count** — `concurrency ≈ TPM / (tokens_per_call × 12)`, with a conservative floor. ⚠ **And a semaphore alone is not sufficient even then**, because token cost per call varies (a `retention_fast` style fragment adds ~400 tokens; an act pass is ~3,600). Pair the semaphore with per-call retry-and-backoff so a 429 is absorbed where it happens (§2.5) rather than failing a whole step.
- ⚠ **The shot-planner and asset-planner caps are not independent** — both draw on the same per-model TPM budget. If they ever run concurrently with each other, the budget is shared and the caps must be halved. Simplest safe rule: **the two loops run sequentially with respect to each other**, each internally concurrent. They already do, and this is now a constraint to preserve rather than an accident.

⚠ **Also settled, by rejection: `RateLimiter` is the wrong tool and must not be reused.** It paces *arrival rate* (calls/sec); ElevenLabs limits concurrency, OpenAI limits tokens/min. It matches neither. (`RateLimiter` stays exactly where it is, in asset resolution, where calls/sec genuinely is the Wikimedia constraint.)

### Q5 → Reserve pessimistically before the gather

The sequence becomes **reserve → check → submit**, so a concurrent sibling's reservation is already visible to the next check.

**This fits the existing shape rather than adding machinery:** `insert_pending` already persists `estimated_cost_cents` before anything else happens, for M7's crash-recovery invariant. Reserving is that same write moved one step earlier — and a failed submission's reservation is released by the `mark_failed` path that already exists.

**Rejected: a lock around check-and-submit.** Obviously correct, but it puts a network round trip inside the lock, so six concurrent submits serialise and concurrency buys nothing on the highest-latency step. Move the submit outside the lock and the race returns.

**Rejected: keeping paid steps serial.** Zero budget risk, but the 185-shot generation pass is where a long run's wall-clock actually goes — this would have conceded the largest available speedup to avoid a solvable problem.

⚠ **This must land before C2, not with it.** It is the one item in Track C where building in the wrong order means shipping an overspend bug — and the same TOCTOU exists today around ~50¢ motion generation, where the overshoot is `concurrency × 50¢` rather than `concurrency ×` fractions of a cent.

### Q6 → Scene approval is final. No un-approve.

Once a scene is in `metadata.approved_scenes` it stays there; the set is monotonic. Scene 12 gets fixed through paths that already exist — per-shot regenerate/override, then `POST /render/only`, which is structurally unable to reach any paid step.

**What this buys:** no reverse edge in the workflow state machine. The engine has no notion of moving backwards from a post-approval step today, and adding one to serve a review-UI affordance would have been the largest single piece of new engine behaviour in Track C.

⚠ **The accepted cost, stated plainly because it will be felt: there is no way to record "I approved this and I was wrong."** At 65 scenes reviewed in one sitting this *will* happen, and the person it happens to will look for the button. The mitigation is not a state machine — it is making the per-shot override path obvious **from the scene row itself** in §6's grouped progress view, so the repair is one click from where the mistake is noticed. **§6 gains that as a requirement, not a nice-to-have.**

⚠ **Second-order consequence worth watching:** irreversible approval raises the stakes of §6's bulk actions. "Approve all remaining scenes" is now an irreversible $0 action that gates an irreversible ~$65 one. It must not sit next to "regenerate all failed in this scene" without a confirmation that distinguishes the two.

### Q7 → Measure the Linux argv length in C0 anyway

C0 already runs in the real `backend/Dockerfile` container; capturing the real argv length costs one log line, and it closes a question open since 2026-08-17.

Even at ~450× headroom against `ARG_MAX`, having the real number means the next thing that lengthens the command — split-screen's second input per shot (parent §2.6), a deeper storage root, more filter stages — can be reasoned about instead of re-probed. **The parent document's Q3 remainder closes here rather than being retired as irrelevant.**

---

## 12. Sequencing

**The ordering principle is the parent document's own: no new capability ships until the ground under it is measured.** Track C's ground is one encode number.

1. **C0 — the encode probe (0.5 d).** Synthetic ~185-shot timeline, production resolution, real photos, realistic cameras, run in the real Linux container. Reports the encode wall, the zoompan multiplier, and the real argv length. ⚠ **Confirms or overturns D2**, so nothing in C3 is designed before it lands. Also closes Q7.
2. **One lookup, minutes (§11, Q4 — otherwise fully answered).** ElevenLabs Starter's **monthly character allowance**, against ~8,640 chars per 10-min video and a full re-synthesis on any voice or speed change. ⚠ **A quota question, not a design one** — it cannot reshape anything below, so it does not gate step 3. *(Caps are settled: TTS 3, LLM 8. Q2's measurement is deliberately skipped — `N > 70` is a guess this plan chose to build on.)*
3. ~~**The shared bounded-gather helper (1 d).**~~ **Done 2026-08-19 (§3.2a).** `bounded_gather` + `reserve_then_gather` in `app/utils/bounded_gather.py`; caps in Settings (`narration_concurrency=3`, `planner_concurrency=8`, `ffmpeg_reserved_cores=2`). Consumers not wired — that is C1/C2/C3. ⚠ C2 must supply a `release` that actually clears reserved cents; today's `mark_failed` does not (see §3.2a).
4. ~~**C3's argv fix (1 d).**~~ **Done 2026-08-19 (§4.2a), folded with §12 step 9a (tpad).** Both argv halves + STATIC `-loop` → `-i`/`tpad`. ffmpeg 9 uses `-/filter_complex`, not `-filter_complex_script` — see §4.2a.
5. ~~**C1 (3–4 d).**~~ **Done 2026-08-19 (§2.6).** Length-aware `ConstraintBundle`, Path B act pass, concurrent shot/asset planning (cap after gather, `db_lock` on inserts). Incremental persist declined (C8).
6. ~~**C2 (1 d).**~~ **Done 2026-08-19 (§3.3).** Unique-by-hash `reserve_then_gather` at cap 3, `{hash}.alignment.json` sidecar + disk fallback, cost constant 0.0103, duration cap via `ConstraintBundle`.
7. **C6 (1 d).** Per-minute cap, length-aware motion cap, and the pre-approval confirmation D4 makes load-bearing.
8. **C4 (1.5 d).** Temporal reuse window. Before C5, so the first long review is looking at output the reuse rule already improved rather than at repetition that will be fixed later.
9. **C3's remainder — rescoped by C0, now 3.5–5.5 d after (a) landed early.** Four sub-tasks, in this order:
   - ~~**(a) Test the memory hypothesis first (~0.5 d).**~~ **Probe done 2026-08-19 (§4.1b). Production fix landed the same day with step 4 (§4.2a)** — `_render_run` has no `-loop` branch left. (b)/(d) start from the tpad input shape; do not reintroduce `-loop 1 -t`.
   - **(b) Per-run fingerprint caching (1–1.5 d).** Now the plan rather than a contingency (D2 overturned). ⚠ **Do not record this as "the edit-latency fix"** — per §4.1a's asymmetry table it fully solves `retention_fast` (~185 runs) and does **nothing** for `documentary_archival` (1 run), which is the style long-form is actually for.
   - **(c) Parallel run encodes (0.5 d).** Same asymmetry, same caveat: helps the cuts-only style that was never the problem. Cheap, so still worth it. ⚠ **Staging names are already run-unique (`run_000_s000.jpg`, §14.2 / R-C2)** — do not simplify them back to `s000.jpg` when adding concurrency; that collision is why they got the run stem.
   - **(d) Two-pass within a long run (2–3 d) — the real answer for the dissolve-heavy case.** Cache each shot's normalised/zoompanned stream, re-chain only the `xfade`s on edit; per-shot granularity regardless of transitions. The second encode of every frame is far easier to justify against a measured ~18.6 min than against the guessed 2–9. ⚠ Should reuse (a)'s `tpad` input shape for the still path when building the per-shot intermediate encode, not the old `-loop 1 -t` — no reason to reintroduce the memory cost into a new code path this probe just found and fixed.
   - ⚠ **Explicitly NOT `-threads 1` relaxation.** It trades away I5's byte-exactness for a problem caching solves without touching determinism, and it was the least-preferred of §4.3's levers before C0; the measurement does not change that ordering.
10. **C5 (3–4 d).** Scene-grouped progress, per-scene approval (**final, no un-approve** — §11 Q6), bulk actions with cost confirmation, draft timestamp links, and the per-shot override reachable **from the scene row** — which Q6 promoted from an affordance to a requirement, since it is now the only repair path for a scene approved in error.
11. **C7 (1–1.5 d).** Per-act music, and the act-repeat rule from §8.2.
12. ~~**C8 (1–2 d).** Measure timeline document growth at real scale, then decide whether anything is needed.~~ **Done 2026-08-19 (§9.1), out of sequence order** — cheap enough (no docker/ffmpeg dependency) to run alongside C0's memory-hypothesis test rather than wait for steps 5–11. Verdict: nothing needed, 0 d follow-on.

Steps 1–4 are all measurement or repair of something already known to be broken, and together they are ~3 days. **Everything after them is contingent on what step 1 says**, which is the point.

---

## 13. Frontend contract, and what long-form breaks in the UI

> **Why this section exists, stated plainly: §1–§12 were written backend-first, and that was a mistake for three of their own decisions.** D3 (scene-by-scene review), D4 (budget confirmation) and the parent document's R10 (clip playback) all have most of their cost in the UI, and every effort figure above counted only the backend half. **C5's "3–4 d" is a backend-only number.** This section is the correction, and it is not optional: nobody is going to drive a 10-minute video generation through Postman.
>
> **Four further decisions taken 2026-08-18** (F1–F4 below), so §13 ships decided rather than as a list of questions. Total decisions in this plan: **fifteen**.

### 13.1 What exists today — verified, 2026-08-18

| | |
|---|---|
| Stack | React + Vite + TypeScript, Tailwind, shadcn/Radix primitives, `@tanstack/react-query`, `react-router-dom` |
| Pages | 6, 1,483 lines total: `AssetReviewGate` (462), `NewProject` (341), `Result` (261), `Progress` (225), `ProjectList` (149), `ProjectEntry` (45) |
| Routes | `/`, `/new`, `/projects/:id`, `/projects/:id/progress`, `/projects/:id/review`, `/projects/:id/result` |
| Polling | `PROGRESS_POLL_MS = 2500`, one interval for every view (`lib/queries.ts:7`) |
| Review layout | `visibleShots.map(...)` — **every shot rendered at once, no virtualisation** (`AssetReviewGate.tsx:353`) |
| Approval | `canApprove = unfilledShots.length === 0` → **one all-or-nothing button** (`AssetReviewGate.tsx:253`) |
| Scene awareness | ⚠ **none.** `ShotProgress` (`lib/types.ts:174`) has no `scene_id` |
| Virtualisation dep | ⚠ **none installed** — no `react-window`/`@tanstack/react-virtual` in `package.json` |

⚠ **Two findings here are more than inventory, and both invalidate an assumption made earlier in this document.**

**1. `ShotProgress` carries no `scene_id`, so scene grouping is not derivable client-side at all.** §6 treats the API contract as the easy half of C5 and the UI as the work. It is the reverse: the backend must *invent* a grouping that has never been transmitted, and until it does, no amount of frontend work produces a scene-grouped view.

**2. The 480p draft is never surfaced in the review UI.** `POST /{project_id}/render/draft` and `GET /{project_id}/video/draft` exist and work; **nothing in the frontend calls either** (`grep draft` across `AssetReviewGate.tsx` and `lib/queries.ts` returns nothing). Only `Result.tsx` plays a video, and only the *final* one. ⚠ **§6 leans on the draft as "the only way to judge pacing" and §11/Q6 made scene approval final — so the plan asks a human to make an irreversible judgement using an artifact the UI does not show them.** That is the single largest gap in this document, and it was invisible while the plan stayed backend-side.

### 13.2 The four frontend decisions

**F1 → Do nothing about the 40-minute gap. You check back when you check back.**

A 10-minute run is ~25–40 minutes wall clock. `Progress.tsx` auto-navigates the instant `workflow_state` flips, which works only because a 90-second run finishes before you look away.

**Accepted as a fire-and-forget batch job.** The progress screen is accurate whenever you return, and the auto-navigate still fires if you happen to be watching. **Zero new work.**

⚠ **The accepted cost: a gate can sit open for hours with nothing signalling it, and under Q6 that gate is the last reversible moment in the run.** Recorded so this is a known trade rather than an oversight. **The cheap upgrade stays available whenever it starts to bite** — a `Notification` on state transition plus a `document.title` badge is frontend-only, needs no backend change, and can be added in an afternoon. Do not build it now; do not forget it exists.

**F2 → ETag/304, slimmer payload, adaptive interval.** See §13.4.

**F3 → Adaptive review screen: flat below a shot threshold, scene-grouped above.** See §13.5, which also contains the ⚠ risk this option carries and the mitigation that removes it.

**F4 → One draft file; scene rows deep-link to a timestamp.** `compute_shot_start_times` already exists and is already D5-overlap-aware, so per-scene start times are a payload addition, not a computation. ⚠ **But per §13.1's second finding, this is not "add deep links to the existing draft player" — there is no draft player.** F4's real scope is: wire draft render + playback into the review gate *at all*, then add the deep links. Sized accordingly in §13.9.

⚠ **F4 stays inside C5 at §12 step 10 — considered and declined, 2026-08-18.** Pulling it out as its own earlier item was offered and turned down, so the consequence is recorded rather than left implicit: **the draft player arrives last, after every other piece of long-form work that assumes you can watch the draft.** In particular §13.5's whole review model ("watch the draft, drill into what looks wrong") is unusable until step 10 lands, so any long-form review attempted before then is a 185-still inspection — the thing §13.7's attention argument says nobody sustains. Not a blocker; a known ordering cost, and one that can be reversed at any time by promoting F4 in §12.

**Rejected for F4: per-scene draft segments.** It would have been faster to load, but it is per-scene segment rendering — the exact thing D2 declined for the final render — and reintroducing it in the draft path would create a second, divergent rendering mode whose boundaries the planner does not know about.

### 13.3 The API surface Track C adds or changes

Consolidated because it is currently spread across ~600 lines of prose, and whoever builds the frontend should not have to reconstruct it.

| Method | Path | Purpose | Section |
|---|---|---|---|
| `POST` | `/{id}/scenes/{scene_id}/approve` | Per-scene approval; monotonic, no un-approve | §6, Q6 |
| `POST` | `/{id}/scenes/{scene_id}/regenerate-failed` | Bulk regenerate within one scene; **must return a cost estimate and require confirmation** | §6 |
| `GET` | `/{id}/progress` | ⚠ **changed** — gains `scenes[]`, per-scene start times, ETag; shot detail moves behind expansion | §13.4 |
| `GET` | `/{id}/scenes/{scene_id}/shots` | Shot detail for one expanded scene | §13.4 |
| `GET` | `/{id}/video/draft` | **exists, unused by the UI** — F4 wires it up | §13.1 |
| `POST` | `/{id}/render/draft` | **exists, unused by the UI** — F4 wires it up | §13.1 |
| `GET` | `/{id}/shots/{shot_id}/clip` | Streams real clip bytes for motion review (parent R10) | parent §13.10 |
| `POST` | `/{id}/grade` | Mutable grade override, no freeze check (parent R5) | parent §13.5 |
| `POST` | `/{id}/style` | Pre-planning style; **400s once a timeline exists** | parent §13.5 |

⚠ **Two of these already exist on the backend and are unreachable from the UI** (`/video/draft`, `/render/draft`), and two were built for the parent document's fixes and have no UI either (`/shots/{id}/clip`, `/grade`). **So four endpoints are already shipped and invisible.** Any frontend work should start there — it is the cheapest capability in the whole plan.

### 13.4 The progress feed — the numbers, and the three fixes

Sized from the **real** `ShotProgress` shape (nested `asset`/`clip` details plus `says`/`prompt`/`intent`): ~787 bytes per shot.

| shots | per `/progress` response |
|---|---|
| 13 (today) | ~10 KB |
| 56 (3 min) | ~43 KB |
| **185 (10 min)** | **~142 KB** |

At `PROGRESS_POLL_MS = 2500` that is **~3.3 MB/min per open tab**, and a 40-minute run is **~960 server-side polls**, each parsing a 232 KB timeline document (§9), querying 185 binding rows, and recomputing `estimate_project_cost_cents`.

⚠ **§6's own instruction makes this worse, and that conflict was not noticed when it was written.** §6 says to keep the flat `shots` array *and* add a `scenes` array "so nothing that consumes it breaks." That is right for compatibility and wrong for scale — it grows the payload at exactly the length where it is already the problem.

**Three fixes, none needing new infrastructure:**

1. **ETag / `304 Not Modified`.** During a 3-minute encode, ~70 consecutive polls return byte-identical data. An ETag turns each of those from ~142 KB into ~200 bytes. ⚠ **The etag must be computed from the response content, not from `timeline.version`** — a shot binding resolving does not bump the timeline version, so version-keyed etags would serve stale progress. The natural key is a hash of the assembled payload, and `FileResponse`'s existing validator behaviour on `/asset` is the local precedent for getting this right.
2. **Scene summaries by default, shot detail on expand.** `scenes[]` of ~65 rows (id, `act_id`, shot count, per-state counts, approval state, `starts_at_s`) is ~8 KB. Per-shot detail comes from `GET /{id}/scenes/{scene_id}/shots` when a group is opened. ⚠ **This supersedes §6's additive instruction** — the flat `shots` array should be *dropped* from the default response rather than kept alongside. It is a breaking change to one consumer that this same work is rewriting anyway.
3. **Adaptive interval.** 2.5 s stays for small projects. Back off to 5–10 s when `total_shots` is large or `current_step` is a known long-runner (render, narration). ⚠ Keep it in `lib/queries.ts` as one derived value, not sprinkled per-hook — today's single `PROGRESS_POLL_MS` constant is the pattern to preserve.

Net effect: ~95% of polls become ~200 bytes, and the ones that carry data carry ~8 KB instead of ~142 KB.

### 13.5 The review screen — and the R1-shaped risk in F3, with its mitigation

F3 chose **adaptive**: today's flat grid and single Approve below a shot threshold, scene-grouped with per-scene approval above it.

⚠ **The risk was flagged when the option was offered and it is real: two approval models means the gate's engine-side satisfied condition differs by project size, and "one invariant, two code paths that can disagree" is exactly the shape of the parent document's R1** — the bug that made `retention_fast` unrunnable and survived 513 green tests because no test crossed the boundary.

**The mitigation, and it removes the risk rather than managing it: adaptive UI, single backend model.**

- **The backend only ever has per-scene approval.** `metadata.approved_scenes` is the one source of truth, and the gate is satisfied iff every scene id is present — at every project size, with no threshold anywhere in the engine.
- **The flat grid is sugar.** Its single Approve button calls approve on every scene in one action. It is a UI affordance over the same model, not a second model.
- ⚠ **Therefore the threshold lives in exactly one place: a frontend rendering decision.** No engine code, no `is_satisfied` branch, no config value read by both sides. If a threshold ever appears in `generate_timeline.py` or in the gate's satisfied condition, F3 has been implemented wrongly and R1 has been recreated.
- **The test that pins it:** a project below the threshold and one above must produce the *same* `approved_scenes` state after approval. That is one test, and it is the one that makes this safe.

**The rest of the long-form review work, in dependency order:**

- **Scene grouping** — needs §13.4's `scenes[]` first; nothing is possible before it.
- **Virtualisation** — 185 shot cards with thumbnails in one DOM is not viable. ⚠ **No virtualisation library is installed**, so this is a new dependency (`@tanstack/react-virtual` is the natural pick — same maintainers as the query library already in use). Note that grouping reduces the need: 65 collapsed scene rows virtualise trivially, and only an *expanded* scene's ~3 shots render. **Grouping may make virtualisation unnecessary, which is worth checking before adding a dependency.**
- **Bulk actions with cost confirmation** — ~50¢/motion shot means a 12-shot scene regenerate is a **$6 click**. ⚠ And per Q6, "approve all remaining scenes" is an irreversible $0 action that gates an irreversible ~$65 one, sitting in the same toolbar as a reversible $6 one. **Three actions, three different confirmation weights, and they must not look alike.**
- **Draft playback + per-scene deep links** (F4) — see §13.1's finding: this starts from zero, not from an existing player.
- **Motion clip playback** — `GET /shots/{id}/clip` exists (parent R10) and has no UI. A `<video>` in the lightbox that already exists (`lightboxTarget`, `AssetReviewGate.tsx:190`) is most of the work.

### 13.6 Thumbnail cold start — 185 ffmpeg invocations at the worst moment

`GET /shots/{id}/asset` lazily extracts and caches a representative frame for a video binding (`cached_video_frame`). **On the first load of a motion-heavy 185-shot review, that is up to 185 ffmpeg invocations**, browser-throttled to ~6 concurrent — so the gate stalls precisely when the human has arrived to look at it.

**Fix: pre-warm the frame cache at the end of `ResolveAssetsStep`**, when the clip has just been downloaded and the process is already doing media work. Moves the cost off the human's critical path entirely, and the cache is already keyed and invalidated correctly (mtime), so nothing new has to be reasoned about.

### 13.7 Frontend effort, alongside the backend figures

The correction this section exists to make.

| item | backend | **frontend** | notes |
|---|---|---|---|
| C0 probe | ~~0.5 d~~ spent | — | done 2026-08-19, §4.1a — overturned D2, grew C3 |
| C1 planning | 4–5 d | — | invisible to the UI |
| C2 narration | 1.5 d | — | |
| C3 render | **4.5–6.5 d** | — | ⚠ grew from 2–3 d after C0 (§4.1a/§12 step 9) — per-run caching + two-pass now in scope; memory sub-task done early with a validated fix (§4.1b), −0.5 d back |
| C4 reuse | 1.5 d | — | |
| **C5 review** | **3–4 d** | **4–6 d** | scene grouping, adaptive gate, bulk actions, confirmations, draft playback from zero |
| C6 budget | 1 d | **1 d** | the pre-approval confirmation D4 made load-bearing |
| C7 music | 1–1.5 d | — | |
| C8 doc growth | ~~1–2 d~~ spent, 0 d | — | done 2026-08-19, §9.1 — measurement only, no follow-on work |
| **§13.4 progress feed** | **1 d** | **1 d** | ETag + payload reshape + adaptive interval |
| **§13.6 pre-warm** | **0.5 d** | — | |
| **parent R10/R5 wiring** | — | **0.5 d** | four shipped endpoints with no UI |
| **totals** | **~18.5–21.5 d** | **~7.5–8.5 d** | |

**Track C is ~26–29.5 days, not ~15–20.** ⚠ Net of three probes landing this session: C0 moved C3 from 2–3 d to 4.5–6.5 d net (§4.1a/§4.1b), C8 moved itself from 1–2 d to 0 d follow-on (§9.1) — plus the frontend correction this table already made (~40% of C5 and ~30% of the whole track, previously uncounted). **This is the number to plan against.**

### 13.8 What does not change

Recorded so the redesign stays bounded. `NewProject`, `ProjectList`, `ProjectEntry` and `Result` need no long-form work — a 10-minute project creates, lists and plays exactly like a 90-second one. React Query stays (F2 deliberately avoided SSE, which would have replaced it). The five existing routes stay; no new route is added (F3 chose adaptive over a separate long-form screen). And the `/progress` → auto-navigate → review → approve → result flow is structurally unchanged — it gains grouping and a draft player, it does not become a different application.

---

## 14. Implementation review — §3.2a / §4.1b / §4.2a / §9.1, verified 2026-08-19

> **Method.** Read every changed file and re-derived the claims against real ffmpeg rather than against the log entries. Where a number is quoted below it was produced by running something, not by reading. Three findings: **one real bug that ships today, one latent bug that a step already scheduled in §12 will trigger, and one operational note.** Everything else checked out, including the memory fix, which was validated exactly as claimed.

### 14.1 R-C1 — BUG, shipping now: every STATIC still is one frame too long

`_render_run` computes `hold_s = frame_counts[i] / settings.fps` and emits `tpad=stop_mode=clone:stop_duration={hold_s}`. **But `tpad` appends its hold *after the end of the input*, and the input is no longer nothing — it is one decoded frame.** So the stream is `1 frame + hold_s`, i.e. `(frames + 1) / fps`.

**Measured against real ffmpeg, three durations, 720×1280 @ 30 fps:**

| target | frames | `hold_s` | actual | delta |
|---|---|---|---|---|
| 3.40 s | 102 | 3.4000 | 3.4333 s | **+0.0333 s** |
| 2.20 s | 66 | 2.2000 | 2.2333 s | **+0.0333 s** |
| 0.80 s | 24 | 0.8000 | 0.8333 s | **+0.0333 s** |

Exactly one frame at 30 fps, every time. ⚠ **This is a regression against the behaviour it replaced** — `-loop 1 -t 3.400` truncated at exactly 3.400 s; `-i` + `tpad` does not.

**The good news, established by measurement rather than assumed: it does not accumulate.** Rendered through the real, unmodified `render_timeline` with dissolve-joined STATIC shots and compared against `compute_timeline_duration`:

| run | expected | actual | delta |
|---|---|---|---|
| 1 shot | 3.0000 s | 3.0333 s | +1 frame |
| 3 shots | 8.0000 s | 8.0333 s | +1 frame |
| 10 shots | 25.5000 s | 25.5333 s | **+1 frame** |

**Constant, not per-shot.** The `xfade` offsets are computed from `shot.duration_s` and are correct, so each intermediate shot's extra frame is absorbed by the next transition; only the final shot's trailing frame reaches the output. **So D5's arithmetic holds and there is no progressive audio drift** — the failure A1's own pitfall warned about ("audio drifts against picture progressively") did **not** happen. The defect is a constant 33 ms tail.

**Fix — verified exact, including the edge case:**

```python
hold_s = (frame_counts[i] - 1) / settings.fps
```

| target | frames | `hold_s` | actual | delta |
|---|---|---|---|---|
| 3.40 s | 102 | 3.3667 | 3.4000 s | **0.0000** |
| 2.20 s | 66 | 2.1667 | 2.2000 s | **0.0000** |
| 0.80 s | 24 | 0.7667 | 0.8000 s | **0.0000** |
| 0.03 s | 1 | 0.0000 | 0.0333 s | **0.0000** |

⚠ `frames == 1` gives `stop_duration=0.0`, which ffmpeg accepts and which is correct — a one-frame shot is one frame, no hold. So no guard is needed, but the `frames - 1` form should carry a comment saying why, or someone will "fix" it back.

**⚠ Why the 17-passing-test run did not catch it, and this is the part worth carrying forward.** [`test_render_narration_mux.py`](../../backend/tests/integration/test_render_narration_mux.py) asserts both stream durations against `compute_timeline_duration`:

```python
assert by_type["audio"] == pytest.approx(expected_total, abs=0.005)   # 5 ms
assert by_type["video"] == pytest.approx(expected_total, abs=0.05)    # 50 ms
```

**The video tolerance is 10× looser than the audio one, and 0.0333 fits inside it with 17 ms to spare.** The suite is not wrong to have a tolerance — encoders round — but the asymmetry is unexplained, and it is exactly wide enough to hide a one-frame error at 30 fps. ⚠ At 24 fps a one-frame error is 41.7 ms and still passes; at 20 fps it is 50 ms and lands precisely on the boundary. **Recommended alongside the fix: tighten the video assertion to `abs=0.005` to match audio.** That single change is what makes this class of bug visible, and it is a stronger deliverable than the one-line arithmetic fix beside it.

### 14.2 R-C2 — LATENT: staged input names collide across runs, and §12 step 9c is what triggers it

`_render_run` stages every input as `s{i:03d}{suffix}` where **`i` is the index within the run** (`for i, shot in enumerate(run)`), into a `work_dir` that **every run shares** (`render_timeline` passes the same `work_dir` to each `_render_run` call).

**So run 0 and run 1 both stage `s000.jpg`,** and `stage_short_input` opens with `dest.unlink()` on an existing target.

**Safe today, and only by accident of scheduling:** runs render in a serial `for` loop, so run 0's ffmpeg has exited before run 1 overwrites the name it was reading.

⚠ **§12 step 9c is "parallel run encodes (0.5 d)" and it is already in the plan.** The moment runs render concurrently, one run unlinks and replaces a file another run's ffmpeg has open — **silently, producing a wrong-picture render rather than an error**, because a valid JPEG at the expected path is exactly what ffmpeg will read. On Linux the unlink even leaves the original inode readable for the process that already opened it, so the corruption is timing-dependent and will not reproduce reliably.

**This is the parent document's R1 shape again:** two changes that are each individually correct, composing into a defect. Step 4 (landed) and step 9c (scheduled) were designed in different passes and neither owns the collision.

**Fix, either form, both cheap — do it now rather than when 9c is built:**

- include the run index in the name — `r{run:03d}_s{i:03d}{suffix}`; or
- give each run its own subdirectory — `work_dir / f"run_{i:03d}" / f"s{i:03d}{suffix}"`, with `cwd` pointed at it.

⚠ **Note the per-run filter file already got this right** — `script_name = f"{output_path.stem}.filter"` yields `run_000.filter`, `run_001.filter`, uniquely per run. **The staged inputs are the one thing in this change that did not inherit that discipline**, which is worth saying plainly because it means the author knew about per-run naming and the inputs were simply missed.

### 14.3 R-C3 — Note, not a defect: staging can duplicate every asset

`stage_short_input` tries symlink → hardlink → copy.

| environment | outcome | disk cost |
|---|---|---|
| production Linux container | symlink | **zero** |
| Windows dev, no Developer Mode, same volume | hardlink | **zero** |
| storage and `work_dir` on different volumes | **copy** | up to **~110 MB** per render at 185 shots |

The fallback chain is the right design and the common cases are free. Recording only the third row: `work_dir = project_dir / "work"` sits under `storage/`, so a split only happens if someone points `storage_root` across volumes. **No change recommended — a runbook line, if anything.**

### 14.4 What was verified and holds up

Checked rather than trusted, so the green items are as load-bearing as the findings.

**§4.1b's memory work — confirmed, and the hypothesis it tested was the right one.** The review hypothesis in §4.1a (input shape, not page cache, evidenced by 391 vs 1,131 args) was tested and held: static `-loop 1 -t` at **10.61 GB** versus motion `-i` at **4.96 GB** — the *cheaper* filter using more than twice the memory, which no filter-cost or neighbour-run theory explains. The `-i` + `tpad` variant at **3.47 GB** and **8% faster** makes this a strict improvement on both axes, not a trade. ⚠ **The one-frame bug in §14.1 is in the *arithmetic* of that fix, not in its premise** — the input-shape change is correct and should stay.

**§4.2a's argv work — correct in the details that usually go wrong:**
- `filter_graph_file_flag` dispatches on the real major version and is `@lru_cache`d, so the `-version` subprocess runs once per binary rather than once per render. ⚠ And the finding it records is a genuine catch the plan had wrong: **`-filter_complex_script` does not exist on ffmpeg 9** — §4.2's own recommendation would have failed outright on the dev machine.
- Output path uses `resolve().relative_to(work_dir)` with a `ValueError` fallback to the absolute path — so `cwd=work_dir` cannot silently write the output somewhere unexpected. This is the detail most likely to have been missed and it was not.
- `run_ffmpeg` gained `cwd` as a keyword with a `None` default, so every existing caller is unaffected.

**§3.2a's helper — matches its stated design exactly:**
- `async with semaphore` wraps the whole retry loop **including `backoff_sleep`**, so a slot is held across backoff. That is the property §2.5 argued for and it is easy to get backwards.
- `asyncio.gather` over coroutines (never `as_completed`), so result order is the input order — the I5-adjacent property C3 depends on.
- `_run_one` catches `Exception` and **returns** it in the slot, so no sibling is cancelled. ⚠ Worth noting it catches `Exception`, not `BaseException`, so `asyncio.CancelledError` still propagates correctly — the right choice, and an easy one to get wrong in the other direction.
- All three caps floored at ≥ 1, so a `0` in config cannot deadlock the semaphore. `planner_concurrency()` is a single function both planner loops read, which is the structural answer to "the two caps must not drift" rather than a comment asking for it.
- 17 unit tests, matching the claim; `settings` carries `narration_concurrency=3`, `planner_concurrency=8`, `ffmpeg_reserved_cores=2`.
- **Deliberately unwired**, as claimed — the production loops are still serial, so nothing paid runs concurrently before Q5's reservation ordering lands.

**§9.1's C8 verdict — sound, and the "nothing needed" outcome is the honest one.** 197,265 bytes at 185 shots (1,066 B/shot) against the 1,250 B/shot extrapolation: the constant does not hold, and it fails in the safe direction. Sub-10 ms diff and fingerprint costs at the largest size Track C targets are genuinely not worth optimising. ⚠ The one number to keep is the one §9.1 already isolates: **~11 MB of `timeline_version` rows per heavily-reviewed long-form project** is capacity planning, not engineering.


### 14.6 R-C4 — the ffmpeg version dispatch: the premise was stale, and the threshold is off by two

§4.2a's flag dispatch is correct in mechanism and wrong in its stated premise. **Measured directly in the real image, 2026-08-19:**

```
$ docker run --rm video-generation-engine-backend:latest ffmpeg -version
ffmpeg version 7.1.5-0+deb13u1
```

⚠ **Production is ffmpeg 7.1.5, not 5.1.** §4.2a states *"⚠ **[Corrected §14.6, 2026-08-19: production is ffmpeg 7.1.5 on Debian *trixie*, not 5.1 on bookworm — measured in the real image. It supports BOTH flags, so the threshold should be `>= 7`, not `>= 9`.]** Debian bookworm — this project's Docker image — is 5.1 and still has the old flag, and does not understand `-/filter_complex`."* The base image has moved to Debian **trixie** (`deb13u1`), and `python:3.12-slim` tracks it. **The claim was presumably true when written and the base image moved underneath it** — which is itself the argument for the pin recommended below, evidenced rather than hypothesised.

**Both flags work on 7.1.5** — verified in the container, not inferred: `-/filter_complex` was added in ffmpeg 7.0 and `-filter_complex_script` survived until 9, so **7.x and 8.x accept either.**

| binary | `-filter_complex_script` | `-/filter_complex` | flag the dispatch picks |
|---|---|---|---|
| dev, 9.0 (gyan, Windows) | **Unrecognized option** | OK | `-/filter_complex` |
| **production, 7.1.5 (trixie)** | **OK** | **OK** | ⚠ `-filter_complex_script` |

**So the two environments take different code paths for no reason** — production supports the modern flag and is handed the legacy one purely because the threshold is `>= 9`.

**Fix: change the threshold from `>= 9` to `>= 7`.** Dev and production then take the *same* branch, and §14.2's "the production path is untested" problem stops existing rather than needing coverage. The `< 7` branch survives only as a safety net for a binary nobody currently runs.

⚠ **The fallback direction is still a real bug and is independent of the threshold.** The regex is `ffmpeg version n?(\d+)`; on no match `major = 0`, which selects the legacy flag. Tested against realistic build strings:

| version string | parsed | with threshold 7 | |
|---|---|---|---|
| `9.0-full_build-www.gyan.dev` | 9 | `-/filter_complex` | ✓ |
| `7.1.5-0+deb13u1` | 7 | `-/filter_complex` | ✓ |
| `5.1.6-0+deb12u1` | 5 | `-filter_complex_script` | ✓ |
| `n7.1` | 7 | `-/filter_complex` | ✓ |
| **`N-120345-g0a1b2c3d`** (nightly) | **0** | **`-filter_complex_script`** | ⚠ **wrong — nightlies are built from master** |
| `2026-01-15-git-abcdef` (dated build) | 2026 | `-/filter_complex` | right by accident |

**An unparseable version is far more likely to be new than old**, so defaulting to the legacy flag is backwards. Two options, either acceptable:

- **cheap:** on parse failure default to the *modern* flag rather than `major = 0`; or
- **robust, and preferred:** stop parsing the version and **probe the capability** — run `-/filter_complex` once against a trivial graph and fall back on failure. Immune to every version-string format, and `@lru_cache` already means one subprocess per process lifetime rather than per render.

**Also: pin ffmpeg in `backend/Dockerfile`.** It currently does a bare `apt-get install -y ffmpeg`, so the version is whatever the base image's apt snapshot serves — which is exactly how §4.2a's "5.1" became stale. ⚠ A pin makes the dispatch branch deterministic and the plan's claims falsifiable. **Note the render cache is already safe either way:** `ffmpeg_version` is part of `compute_render_fingerprint`, so two binaries can never serve each other's cached output. The pin protects the *branch selection* and the *documentation*, not the cache.

**Minor, same area:** two places shell out to `ffmpeg -version` — `fingerprint.py:135` (async, for the fingerprint) and `slideshow.py:145` (sync, for the flag). Worth consolidating.

**The good news, and it retires an alarm this review raised before measuring.** The dev/production gap is **two** major versions (9 vs 7.1.5), not the four the "5.1" claim implied — and every filter both plan documents depend on exists in the production image, confirmed by `-h filter=`:

`tpad` · `xfade` (including `wipeleft` and `fadeblack`) · `zoompan` · `eq` · `subtitles` · `ass`

⚠ **Existence is not equivalence** — filter *defaults* and rounding can still differ between 7.1 and 9, so the grade's `eq` values, `build_punch_in_expression`'s output, and the text-card ASS rendering are still only *visually* verified on ffmpeg 9. But nothing is missing, so the risk is "may look slightly different" rather than "will fail," which is a materially smaller problem than this review initially flagged.

**Recommended order:**

1. **Threshold `>= 9` → `>= 7`** (one character) — collapses dev and production onto one path, which is worth more than testing two.
2. **Fix the fallback direction**, preferably by capability probe.
3. **Pin ffmpeg in the Dockerfile** and correct §4.2a's "5.1" to "7.1.5 (trixie)".
4. **Run the render integration suite in the container once** — cheaper and more meaningful after step 1, since it then exercises the same branch dev does, and it is the only way to close the "verified on 9" residual above.

### 14.7 Recommended order

0. **R-C4 step 1 first — the one-character threshold change (`>= 9` → `>= 7`).** It costs nothing and it collapses dev and production onto a single argv branch, which makes every subsequent verification below (including a container test run) cover the path that actually ships.
1. **R-C1's tolerance tightening first, then the arithmetic fix** — in that order, deliberately. Tightening `abs=0.05` → `abs=0.005` makes the existing suite fail, which proves the bug is real and the test now covers it; fixing `hold_s` then makes it pass. Fixing first and tightening after proves nothing about whether the test would have caught it.
2. **R-C2 now, not when 9c is built.** It is a two-line rename today and a silent, timing-dependent wrong-picture bug later. ⚠ Add a note to §12 step 9c that the staging namespace was made run-unique for exactly this reason, or the next pass may simplify it back.
3. **R-C3 — a runbook line, or nothing.**
4. **R-C4's remaining steps** — fallback direction (capability probe preferred), Dockerfile pin, and one container run of the render integration suite. ⚠ The container run is what closes the "visually verified on ffmpeg 9, ships on 7.1.5" residual; it is worth doing once, after step 0.

### 14.8 — Fixes landed, 2026-08-19

Applied in §14.7's order. Production loops other than `_render_run` are still serial.

| ID | what landed | why this shape |
|---|---|---|
| **R-C1** | `hold_s = (frame_counts[i] - 1) / settings.fps`. Comment on the `- 1`. `test_static_tpad_duration_is_frame_exact`: 3.40 s @ 30 fps, `abs=0.005`. | **Shipped mux video band is `abs=0.10`, not 5 ms.** The mux fixture is four hard-cut runs of non-round narration durations; after frame-quantise + concat-copy it carries ~80 ms of legitimate residual, so 5 ms is the wrong comparison there. Audio stays at 5 ms. The 5 ms / frame-exact proof was moved to the dedicated single-shot test. Diagnostic only (not the outcome): tightening mux to 5 ms *first* failed `4.333` vs `4.153` (+180 ms) and proved the bug on this fixture; after the arithmetic that 180 ms is gone and the remaining ~80 ms is why the band stayed at 100 ms. |
| **R-C2** | `short_input_name(..., run_stem=output_path.stem)` → `run_000_s000.jpg` | Same uniqueness the filter file already had. §12 step 9c is annotated so the next pass does not simplify it back. |
| **R-C3** | Comment on `stage_short_input` only | Copy-across-volumes is the fallback; production Linux is a symlink. |
| **R-C4** | `filter_graph_file_flag` is a **capability probe** of `-/filter_complex` (missing-script; "Unrecognized option" → legacy). No version regex. `slideshow.py` no longer calls `ffmpeg -version` — `fingerprint.py::get_ffmpeg_version` remains the one version probe, for the cache key. Dockerfile pins `ffmpeg=7:7.1.5-0+deb13u1` (measured). | Probe, not `>= 7`: nightlies like `N-120345-g…` are gone as a class of bug. Dev 9 and production 7.1.5 now take `-/filter_complex`. |
| **R-C4 container** | Render suite run in the rebuilt image. **19 passed on 7.1.5, 20 on Windows 9** (mux is host-only). | Found a real 7.1 vs 9 gap the review predicted: motion-clip + tpad-still xfade died with `rate of 1/0 is invalid`. Fix: `-framerate {fps}` on still inputs; `fps` before *and* after `tpad`; `fps` again after motion `trim`/`setpts`. Still-only xfades had passed; this only showed up on the mixed path, which is why the container run was load-bearing. |

### 14.9 Review of §2.6 / §3.3 / §14.8, verified 2026-08-19

> **Method.** Re-derived every claim against the code and against real ffmpeg. ⚠ **R-C1's fix was verified against a filter graph that §14.8 then changed** (the 7.1.5 `rate of 1/0` fix added `-framerate` and a second `fps`), so the first thing re-checked was whether its exactness survived. It did. **One finding (R-C5), one latent note, everything else confirmed.**

#### R-C5 — the mux test ships at 100 ms, not the 5 ms §14.8 describes

§14.8's R-C1 row reads: *"Tightened the mux test to 5 ms **first** — it failed `4.333`…"*. That describes a transient diagnostic step. **The shipped value is `abs=0.10`** (`test_render_narration_mux.py:218`) — **twice as loose as the 50 ms band §14.1 criticised**, and 20× looser than the log implies.

| | before review | §14.1 criticised it as | **shipped now** |
|---|---|---|---|
| audio band | `abs=0.005` | correct | `abs=0.005` |
| video band | `abs=0.05` | "10× looser, hides one frame with 17 ms to spare" | **`abs=0.10`** |

⚠ **The decision itself is sound and is documented in the test** — the fixture is four hard-cut runs of non-round narration durations, each frame-quantised then concat-copied, so it carries ~80 ms of legitimate residual and a 5 ms band is not achievable there. Moving the exactness proof to a dedicated test is the right call. **The problem is that §14.8 records the diagnostic step as the outcome**, so a reader of the log believes the mux path is now guarded at 5 ms. It is guarded at 100 ms. Correct the log entry.

**Two substantive consequences, not just bookkeeping:**

**1. The compensating test is single-shot and render-only.** `test_static_tpad_duration_is_frame_exact` (`test_render_ken_burns.py:171`) renders **one** `STATIC` shot at 3.4 s. So frame-exactness is proven for a still with **no `xfade`, no concat, and no mux**. At 30 fps a 100 ms band absorbs **three frames**, so a 1–3 frame regression introduced in the `xfade` chain, the concat demuxer, or the mux would pass every test in the suite.

⚠ **That is not hypothetical — it is the exact bug §14.1 found.** The original defect surfaced as +1 frame on multi-shot dissolve chains, and this review measured it at 1, 3 and 10 shots through the real `render_timeline`. **A multi-shot exactness assertion is a few lines** (build N dissolve-joined STATIC shots, render, compare `probe_duration_seconds` against `compute_timeline_duration` at `abs=0.005`) and it closes the whole class. **Recommended: add it beside the single-shot test.**

**2. The 100 ms band has less than one frame of headroom.** Against the ~80 ms residual the comment itself states, the margin is ~20 ms — under one frame at 30 fps. So the test is simultaneously too loose to catch a small regression and tight enough to flake if narration durations shift. ⚠ **Prefer pinning the residual instead of bounding it:** assert the delta is within one frame of the *known* quantisation, or assert against a recorded expected value, rather than a band chosen to sit between two failure modes.

#### Note — three independent `asyncio.Lock()`s, one shared `AsyncSession`

`shot/planner.py:282`, `asset/planner.py:125`, `scene/planner.py:365` and `narration.py:306` each create their own `asyncio.Lock()` local to their own gather. **Correct today**, because `generate_timeline._run_real` awaits scene → shot → asset strictly in sequence, so no two gathers ever overlap and each lock is the only writer to the session while it runs.

⚠ **But the safety is a property of the call ordering, not of the locking.** Four independent locks over one `AsyncSession` means that if any two planner gathers were ever overlapped, the locks would not serialise session access at all — they guard different critical sections. The plan already forbids overlapping them, for an unrelated reason (§11 Q4: shot and asset planning share one TPM budget), so **the enforcement is a documentation note, not code** — the same shape as R-C2, which was safe-by-scheduling until §12 step 9c was scheduled to break it.

**Cheapest durable fix if this ever matters: one session-scoped lock** (created where the session is, passed down) rather than one per gather. No behaviour change today; it stops being a latent hazard.

#### What was verified and holds up

**R-C1's fix survives §14.8's own graph change — re-measured, not assumed.** The 7.1.5 fix added `-framerate {fps}` on still inputs and `fps` both before *and* after `tpad`, which changes the input frame's duration from the image demuxer's 1/25 s to exactly 1/fps. Re-measured against real ffmpeg on the current graph:

| target | frames | `hold_s` | actual | delta |
|---|---|---|---|---|
| 3.4000 s | 102 | 3.3667 | 3.4000 s | **0.0000** |
| 2.2000 s | 66 | 2.1667 | 2.2000 s | **0.0000** |
| 0.8000 s | 24 | 0.7667 | 0.8000 s | **0.0000** |
| 0.0333 s | 1 | 0.0000 | 0.0333 s | **0.0000** |

⚠ **And `-framerate {fps}` makes the `- 1` principled rather than empirical** — with the input frame now exactly `1/fps`, `(frames - 1)/fps + 1/fps == frames/fps` is arithmetic rather than a measured coincidence. Worth noting in the docstring, because it means the `- 1` is now *load-bearing on `-framerate` being present*: removing `-framerate` would silently reintroduce a partial-frame error.

**The container run earned its place, and it validated this review's own prediction.** §14.6 warned that "existence is not equivalence — filter defaults and rounding can still differ between 7.1 and 9." The run found exactly that: `rate of 1/0 is invalid` on an `xfade` between a motion clip and a `tpad` still, on 7.1.5 only, **and only on the mixed path** — still-only xfades passed. That is a class of bug no amount of host-side testing would have surfaced.

**§14.8's other three fixes are as claimed:**
- **R-C2** — `short_input_name(..., run_stem=...)` → `run_000_s000.jpg`, the same per-run uniqueness the filter file already had, with §12 step 9c annotated so it is not simplified back.
- **R-C4** — `filter_graph_file_flag` is a genuine capability probe; **zero regex matches remain** in `slideshow.py` and it no longer shells out to `ffmpeg -version` (`fingerprint.py` is the single version probe, for the cache key). `Dockerfile` pins `ffmpeg=7:7.1.5-0+deb13u1`. The nightly-build class of bug is gone rather than mitigated.
- **R-C3** — comment only, as recommended.

**§2.6 (C1) gets both of this document's own warnings right:**
- ⚠ §2.4 warned the shot-cap accumulator becomes a race under concurrency. **`shot/planner.py` gathers at line 309 and checks `total_shots` at 317–321 — after the gather, over the collected result.** Correct.
- ⚠ §2.2 warned "do not pass absolute fragment indices into a per-act call." **`_one_act` calls `_plan_single(script=act.script_slice, …)`, which re-splits that slice into local `1..M` fragments.** The model never sees an absolute index. Correct, and it follows the S2 precedent exactly.
- `act_max_scenes` / `act_max_duration` are pro-rated by the act's fragment share, so the per-act caps sum to the project cap rather than each inheriting the whole budget.

**§3.3 (C2) implements Q5's ordering exactly:**
- `reserve` accumulates `reserved_cents` serially; `check()` **re-reads** `total_project_spend_cents` and compares against the accumulated reservation, so a sibling's reservation is genuinely visible — the TOCTOU §3.2 identified is closed.
- `release` decrements on halt or failed submit.
- `db_lock` wraps **only** `narration_repo.insert`; the provider HTTP call and the file write stay outside it, so the lock does not serialise the work concurrency exists to parallelise.
- `_restore_row_from_disk` requires **both** the mp3 and the `.alignment.json` sidecar to exist and be non-empty, and an mp3-without-sidecar (every file written before C2) correctly re-synthesises rather than reconstructing a fabricated alignment. That is the right failure direction.
- `elevenlabs_cost_cents_per_character` corrected to `0.0103` — matches §11 Q4's measured ₹8.80/1K.
- ⚠ Minor, no action needed: `check()` re-queries project spend on **every** reserve, so 65 scenes means 65 `total_project_spend_cents` queries during the serial reserve phase. Slightly wasteful, and arguably *more* correct than a single snapshot since it picks up spend from other sources. Recorded so it is not mistaken for a bug later.

#### Recommended, in order

1. **Correct §14.8's R-C1 row** to say the mux video band is `abs=0.10` with the exactness proof relocated — one sentence, and it stops the log from overstating the guard.
2. **Add the multi-shot exactness test.** It is the assertion that would have caught §14.1's bug at the size it actually appeared, and it closes the xfade/concat gap the single-shot test leaves open.
3. **Note `-framerate`'s role in the `_normalize_filter` docstring** — the `- 1` is now correct *because* the input is `1/fps`; that dependency should be written down where someone would break it.
4. **Optional: one session-scoped lock** instead of four gather-scoped ones. No behaviour change now; removes a latent hazard of the same shape as R-C2.

### 14.9a — Response, 2026-08-19: C2 has nothing to fix; R-C5 is a log + coverage note, not a C2 defect

Read as scenarios, not as a punch list. **No production-code change from this review.** Item 1 (the log sentence) is corrected in §14.8's R-C1 row above. Items 2–4 are not C2 work.

**C1 and C2 — the stories that already work, so there is no patch.**

- *Budget almost full, 65 scenes start at once.* Without reserve, every scene reads “plenty left” and all 65 call ElevenLabs. C2’s `reserve` adds estimated cents serially; scene 2’s `check` already includes scene 1. The call that would break the cap never goes on the network. Q5 holds.
- *pytest truncates `narration`, the mp3 is still on disk.* Both `{hash}.mp3` and `{hash}.alignment.json` → restore the row, do not pay. mp3 only (every file written before C2) → pay again. We refuse to invent timestamps from audio. Right failure direction.
- *Two scenes speak the same sentence.* One paid call, both scenes get that audio.
- *Eight scenes plan shots at once, the project is near the shot cap.* The cap is counted **after** the gather, over the finished list — not inside each worker — so two scenes cannot both see “39 so far” and sneak past 40.
- *Act 3 of a 10-minute script.* The model sees a local `1..M` slice of that act’s own words, never “fragments 84 to 122.”

**R-C5 — the story the log currently mis-tells, and the gap that is not a C2 bug.**

- *What a reader of the old §14.8 row would believe:* CI fails unless muxed video is within 5 ms. *What ships:* mux video is allowed 100 ms (`test_render_narration_mux.py`). Audio is 5 ms. That 100 ms call is the right call for **that** fixture (~80 ms of real leftover from non-round narration rounded to frames, then concat-copied). The lie was the log, not the band. **Log corrected above.**
- *What the 5 ms test actually watches:* one still, 3.4 s, no dissolve, no concat, no mux. *What the original one-frame bug looked like:* several stills joined by dissolves. At 30 fps, 100 ms absorbs three frames, so a 1–3 frame regression on the dissolve / concat / mux path still passes every test we have. That is a **render-suite coverage** gap, the same class as §14.1, sitting on C3’s remainder (xfade / concat / mux), not on C2. Not taken here.
- *The 100 ms band vs ~80 ms leftover:* ~20 ms of room, less than one frame. Too loose to catch a small dissolve regression, tight enough to flake if this fixture’s narration lengths shift. Same coverage note as the bullet above; pinning the residual belongs with a multi-shot exactness test, not with a C2 change.

**The lock note — a story that cannot happen with today’s order.**

- Scene planning, then shot planning, then asset planning, then narration. Each makes its own lock. They never overlap, so each lock is the only writer to the session while it runs. Fine today.
- *The story the locks would not stop:* overlapping two of those gathers “to save wall clock.” Two keys, one filing cabinet. SQLAlchemy’s async session is not safe for that. Enforcement is the call order (and §11 Q4’s “don’t overlap shot and asset, they share TPM”), not a shared lock. Same shape as R-C2 before staging names were made run-unique. Optional session-scoped lock **declined** — no behaviour change now, and nothing in §12 is scheduled to overlap those gathers.

**R-C1 still exact after the graph change — measured, so no re-fix.** 3.4 / 2.2 / 0.8 / 1-frame all came back at 0.0000 s on the current `-framerate` + dual-`fps` graph. The `- 1` in `hold_s` is now arithmetic *because* `-framerate` makes the first frame `1/fps`. Worth a docstring if someone later strips `-framerate` as cleanup; not a C2 item, not taken here.

| §14.9 recommended | disposition |
|---|---|
| 1. Correct the §14.8 R-C1 row | **Done** in this response — shipped mux video band is `abs=0.10`; 5 ms proof is the dedicated single-shot test |
| 2. Multi-shot dissolve exactness test | **Not taken.** Real coverage gap on the xfade/concat path; it is C3 remainder, not a C2 defect |
| 3. `-framerate` in the `_normalize_filter` docstring | **Not taken.** Render comment, not C2 |
| 4. Session-scoped lock | **Declined.** Safe by today’s call order; optional, no behaviour change |

**So: nothing to fix on C2, and nothing to change in production code from this review.** The only edit this response makes is the log sentence R-C5 asked for.
