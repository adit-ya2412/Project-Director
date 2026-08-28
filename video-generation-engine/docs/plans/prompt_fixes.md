# Prompt & Planner-Coordination Fixes

**Status:** Implemented 2026-08-26. See §6. Written 2026-08-26 after a
read-through of all nine prompt files under `backend/app/prompts/`,
prompted by "any improvements for the agent-loop prompts?"

Two of the findings are real defects reachable in production today, not
style preferences. Both are the **same structural class as bugs already
fixed this session** — a feature shipped, one consumer never updated
(the frontend gaps in `ui_style_feature_coverage.md`), and a per-scene
planner asked to enforce a whole-project invariant it cannot see
(`style_extensions.md`'s `max_video_shots_per_project` race). Neither is
a new kind of problem for this codebase, which is the strongest argument
for fixing both properly rather than patching prose.

---

## 0. Navigation

| # | Read | Why |
|---|---|---|
| 1 | `docs/plans/style_extensions.md` §P-C3 + the asset-planner downgrade it describes | The precedent for §3.2's fix. `app/planners/asset/planner.py:143` (`_downgrade_to_image`) and `:238` (the warning log) are the exact shape to copy — a post-gather corrective pass, not a prompt instruction. |
| 2 | same doc, §2.7 "When to fail loudly vs. correct silently" | Already-decided policy on which of the two behaviours applies. §3.2 below picks one and says why. |
| 3 | `docs/plans/ui_style_feature_coverage.md` §1.2 | The precedent for §3.1: a style shipped and a consumer silently kept working with stale data. Same failure mode, different consumer. |
| 4 | `backend/app/prompts/director/v1.md:54-71` and `asset_planner/v1.md` (the `entity` section) | **Read before writing any new prompt prose.** These are the two best prompts in the codebase and the reason is visible: concrete good/bad pairs plus *measured* evidence. §3.4 is about making the weaker prompts look more like these. |

---

## 1. Scope

### 1.1 In scope

| # | Fix | Severity | Kind |
|---|---|---|---|
| §3.1 | `archival_montage` missing from the suitability check | 🔴 Live defect | Data + prompt |
| §3.2 | "At most one glitch per video" is structurally unenforceable | 🔴 Live defect | Code (planner) |
| §3.3 | `punch_in` absent from the base camera table | 🟡 Gap | Prompt |
| §3.4 | Conflicting duration constraints with no stated priority | 🟡 Ambiguity | Prompt |
| §3.5 | No examples in `scene_planner` / `act_planner` | ⚪ Quality | Prompt |

### 1.2 Out of scope

- **Rewriting prompts wholesale.** Every prompt here already works in
  production; the two 🔴 items are narrow and specific. A general
  "improve the prompts" pass would make regressions hard to attribute.
- **Prompt versioning (`v2.md`).** Established convention in this repo
  is editing prompts in place — every prompt is still `v1`, including
  ones edited more than once (settled 2026-08-26, `style_extensions.md`
  §P-B's own resolution). Do not introduce versioning as part of these
  fixes.
- **`wipeleft`/`fadeblack`'s identical coordination weakness.** Named in
  §3.2's own notes because it is the same defect one severity tier down,
  but deliberately not fixed here — see §3.2's "deliberately not
  extended" note for the reasoning.

### 1.3 Investigated and DISMISSED — do not "fix" this

**`compare → split_frame` in the base camera table is NOT over-producing
split-frame shots.** The initial read-through flagged this as a likely
problem (a 1:1 intent→camera mapping pointing at the only shot type that
costs *two* assets). **Checked against two real 46-shot timelines before
writing this plan, and the hypothesis is wrong:**

| Timeline | Total shots | `compare` intents | `split_frame` shots |
|---|---|---|---|
| `radar_project` (WWII/radar) | 46 | 1 | 2 |
| `test_project` (transmissions) | 46 | 0 | 2 |

`split_frame` sits at ~4% of shots in both, and in `test_project` it
appears **with zero `compare`-intent shots at all** — so the model is
plainly not applying that table row mechanically. The table reads as
loose guidance, which is how it was intended. Recorded here so the same
plausible-sounding concern isn't re-raised and "fixed" into a real
regression later.

---

## 2. Lessons carried forward

### 2.1 A prompt instruction cannot enforce what the caller cannot see

This is §3.2's whole point and it has now bitten this codebase twice:

- `max_video_shots_per_project` — the Asset Planner runs per-scene, so
  a project-wide video cap could not be respected per-call. Fixed with a
  post-gather corrective pass (`asset/planner.py:229-262`).
- The glitch transitions (§3.2) — the Shot Planner also runs per-scene
  (`shot/planner.py:359`), so "at most one per video" has the identical
  flaw. **The instruction was written this session, by this author, with
  full knowledge of the first bug, and still reproduced it.** That is the
  argument for treating "whole-project invariant + per-scene planner" as
  a code-level pattern to check for, not a prose problem to word better.

**Rule going forward:** any prompt sentence containing "per video",
"per project", "at most one", "never twice", or "elsewhere in this
video" is a red flag — the planner reading it almost certainly cannot
see the rest of the video. Either enforce it post-gather in code, or
delete the claim.

### 2.2 Style catalogues have more consumers than the style registry

`STYLE_PACING_BANDS` is not the only place a style must be registered.
Adding `archival_montage` this session required (and in one case
*missed*) updates in:

- `app/script/styles.py` — the band ✅
- `app/renderer/grading.py` — `STYLE_GRADES` ✅
- `app/prompts/shot_planner_styles/` — the fragment ✅
- `frontend/src/lib/styles.ts` + `resolution.ts` — ✅ (this session, after being missed initially)
- **`app/script/suitability.py::_STYLE_DESCRIPTIONS` + `prompts/script_suitability/v1.md` — ❌ still missing, this plan's §3.1**

**Whoever adds style #5 should grep for every existing style name
(`grep -rn "retention_fast" backend/ frontend/src/`) and update every hit
before calling it done.** §3.1's fix should add a test that makes this
structural rather than a matter of remembering.

### 2.3 Prompt quality in this repo correlates with measured evidence

`director/v1.md:54-71` doesn't just say "use short search terms" — it
records that five production-library phrasings returned one usable result
between them "and it was birdsong," against the live API. That specificity
is why the behaviour sticks. §3.5's additions should follow the same bar:
a real example from a real run, or nothing.

---

## 3. The fixes

### 3.1 🔴 `archival_montage` is invisible to the suitability check

**The defect, precisely.** `app/script/suitability.py:37-53`'s
`_STYLE_DESCRIPTIONS` contains three entries — `documentary_archival`,
`retention_fast`, `stillness`. Line 80 resolves the description with
`.get(style, style)`, so for the 4th style the *name becomes its own
description*, and the model receives:

```
Style under consideration: archival_montage
Style description: archival_montage
```

`prompts/script_suitability/v1.md` independently describes the same three
styles and no fourth. Its own instruction is *"Styles, described by when
they are the RIGHT choice — **never judge by the name alone**."* For
`archival_montage`, the name alone is all that exists. **The check will
return a confident, fabricated verdict** — the specific failure the
prompt was written to prevent.

**Reachability:** `check_suitability` returns `None` early under
`settings.dry_run` or a null provider (`suitability.py:77`), so this is
live only on real runs with a real provider — which is every real
`archival_montage` project.

**Fix:**
1. `app/script/suitability.py` — add an `archival_montage` entry to
   `_STYLE_DESCRIPTIONS`, in the same voice as the other three (when it
   is the RIGHT choice, and when it is wrong).
2. `app/prompts/script_suitability/v1.md` — add the matching 4th bullet
   to the styles list.
3. ⚠ **Make the `.get(style, style)` fallback loud rather than silent.**
   The fallback is what turned a missing entry into a plausible-looking
   prompt instead of an error. Options, in preference order: raise on an
   unknown style (it can only be a registry key by the time it reaches
   here); or keep the fallback but log a warning. Do NOT leave it silent —
   silence is why this shipped.

**Test (pure, no DB, no LLM):** assert `set(_STYLE_DESCRIPTIONS) ==
set(STYLE_PACING_BANDS)`. This is the §2.2 structural fix — style #5
fails this test on the day it's added, rather than shipping a fabricated
verdict. Cheap, and worth more than the two content edits above.

### 3.2 🔴 "At most one glitch per video" cannot be enforced per-scene

**The defect, precisely.** `prompts/shot_planner/v1.md:47-60` instructs:
*"use AT MOST ONE per video"* and *"must never appear in the same video
as each other."* The Shot Planner runs **one LLM call per scene**
(`shot/planner.py:359`, `bounded_gather(scenes, _one_scene, …)`). Each
call sees one scene and has no visibility into any other scene's
transitions. On an 8-scene script where several scenes each contain a
plausible "something breaks" beat, nothing prevents 8 glitch transitions.

This is `max_video_shots_per_project` again (§2.1), in a prompt written
after that fix — which is the point.

**Fix — copy the asset planner's own pattern, don't reword the prompt.**
`asset/planner.py:229-262` is the template: gather all scenes, count the
project-wide total afterwards, and correct the excess deterministically
with a warning log. Concretely, in `ShotPlanner.plan`'s post-gather block
(`shot/planner.py:363-372`, right where `max_shots_per_project` is
already checked):

- Walk `planned_scenes` in scene/shot order.
- Keep the **first** glitch transition encountered; downgrade every
  subsequent one to `TransitionType.CUT` with `duration_s=0.0`.
- Log once, in the existing `logger.warning(..., extra={...})` shape
  (§2.1 of `style_extensions.md` — this codebase's logger is stdlib, NOT
  structlog; bare kwargs raise `TypeError`, a mistake already made once
  this session).

**Silently correct, don't fail loudly** — and state the reasoning in the
comment, per `style_extensions.md` §2.7's requirement that this choice be
argued rather than assumed. The argument here: the model was never *able*
to see the other scenes, so a hard failure would punish it for missing
information it was structurally denied — exactly the reasoning that moved
the video-shot cap from `PermanentError` to a downgrade earlier this
session. A glitch transition becoming a plain cut is also a strictly
safe degradation (`cut` is the base default), unlike a failed render.

**Prompt change alongside it (secondary, not the fix):** soften
`v1.md:54`'s "AT MOST ONE per video" to something honest about the
planner's actual visibility — it can be told to use these *rarely and
only for a corruption beat*, which is per-scene-judgeable, but it cannot
be told to count across a video it cannot see. **Do not simply reword
and skip the code fix** — prose cannot close this.

**Deliberately NOT extended to `wipeleft`/`fadeblack`.** Lines 41-46
carry the same shape of instruction ("reserve for the story's biggest
turn" is a whole-video judgement made per-scene) and therefore the same
weakness. Left alone here because the consequence is materially smaller —
an over-used wipe reads as showy, an over-used glitch reads as broken —
and because a corrective pass that silently rewrites *ordinary*
transitions is a much larger behavioural change than one that caps a
deliberately-rare effect. Recorded so the omission is visibly a decision,
not an oversight.

**Tests (pure, no DB):** the fixture-driven shape in
`tests/unit/planners/` — build `planned_scenes` with glitches in scenes
1, 3 and 5, assert only the first survives and the rest are `CUT`;
assert a single-glitch timeline is untouched; assert non-glitch
transitions are never modified.

### 3.3 🟡 `punch_in` is missing from the base camera table

`prompts/shot_planner/v1.md:21-30` maps six intents to six camera moves.
`punch_in` is not among them — it appears only inside the
`retention_fast` and `archival_montage` style fragments. For
`documentary_archival` and `stillness`, the model can still emit
`punch_in` (it's in the structured-output enum) but is never told it
exists or when it's appropriate.

This mirrors, in the prompt layer, the exact drift that
`ui_style_feature_coverage.md` §2.3 found in the frontend type layer —
`punch_in` shipped into the enum and two consumers never learned about
it.

**Fix:** one line in the base table naming `punch_in` and its register
(a hard, stepped zoom snap — an emphasis move, not a drift), phrased so
the slower styles understand it's available but rarely right for them.
Keep it consistent with what the two style fragments already say, so the
base prompt and the overrides don't contradict each other.

**⚠ Verify before writing:** re-read both style fragments first. They
currently *override* the base table; if the base table starts naming
`punch_in` for a specific intent, check that neither fragment now
contradicts it. This is a prompt-consistency check, not a code one.

### 3.4 🟡 Two duration constraints conflict with no stated priority

`prompts/shot_planner/v1.md:61-76` requires both:

- *"every shot's `duration_s` values must sum to the scene's
  `duration_s`"* (line 71-72), and
- *"Respect the numeric limits you are given"* — a min and max shot
  duration (line 73-76).

On a short scene with many fragments these are simultaneously
unsatisfiable, and the prompt never says which yields. The model is left
to guess, silently, on a constraint the downstream validator does check.

**Fix:** state the precedence explicitly. Recommended ordering, matching
what the pipeline actually tolerates: fragment coverage is inviolable
(the validator rejects gaps/overlaps outright), duration limits are the
next hardest, and the scene-sum is the soft one — durations are
reconciled against *real measured narration* later anyway
(`narration_locked` / the A26 exemption), so a planning-time sum is an
estimate, not a contract.

**⚠ Confirm that ordering against the real validator before writing it
into the prompt** — `shot/planner.py`'s own validation is the authority
on which of these actually hard-fails. Don't encode this plan's guess.

### 3.5 ⚪ `scene_planner` and `act_planner` have no examples

Both are pure prose. The two best-performing prompts in the repo
(`director/v1.md`'s search-terms section, `asset_planner/v1.md`'s
`entity` section) are the two with concrete good/bad pairs and measured
evidence (§2.3).

**Fix, if worth doing at all:** one good/bad pair each — for
`scene_planner`, a boundary that falls on a real narrative turn versus
one that falls at an arbitrary fragment count; for `act_planner`, a
4-act split of a real script versus an over-fragmented 7-act one.

**Use a real example from a real run** (the `3d56cf87` radar timeline has
6 scenes over 46 shots and is a reasonable source), not an invented one —
§2.3's bar. If no real example is to hand, skip this item rather than
inventing one; a fabricated example in a prompt is worse than no example.

---

## 4. Testing & DB safety

**Unchanged and non-negotiable** — same rules as
`style_extensions.md` §6, restated because this plan touches
`backend/tests/`:

1. Every test here is a pure function of fixtures. **No live DB, no live
   LLM.** §3.1's registry-parity test and §3.2's downgrade tests are both
   plain assertions over in-memory objects.
2. Run with explicitly-scoped paths and `--noconftest`
   (e.g. `pytest tests/unit/planners/test_shot_planner_glitch_cap.py
   --noconftest -q`).
3. **Never run the full suite or `make test`**, and never set
   `PYTEST_TRUNCATE_DB`. The autouse `clean_database` fixture TRUNCATEs
   every table in the shared Postgres that the dev server also uses —
   there is no separate test database, and there are live projects in it.
4. ⚠ Note for whoever runs the §3.2 tests: `tests/unit/planners/
   test_shot_planner.py` (the existing file) **does** use
   `async_session_factory` and will error under `--noconftest` with a
   connection refusal. That is expected and not a regression. Put the new
   glitch-cap tests in their **own file** so they stay DB-free and
   runnable in isolation.

---

## 5. Sequencing

1. **§3.1** — the only item producing wrong output *right now*. Smallest
   fix, highest value. Ship the parity test with it (§2.2), not after.
2. **§3.2** — the code fix, then the prompt softening. Not the reverse:
   softening the prompt alone would make the defect *less visible*
   without removing it.
3. **§3.3 / §3.4** — prompt-only, independent, either order. Both need
   their "verify first" step honoured (§3.3's fragment-consistency check,
   §3.4's validator check) before any prose is written.
4. **§3.5** — optional. Skip entirely if no real example is available.

---

## 6. Implementation log

### P-PF — All five in-scope items (2026-08-26)

**Scope executed:** §3.1–§3.4 in full, plus §3.5 for `scene_planner`
only. `act_planner` examples skipped (no stored act split on a real
run — fabricating a 4-act grouping of `3d56cf87`'s scene titles would
violate §2.3). No prompt versioning, no wholesale rewrites, no
wipeleft/fadeblack cap. No live DB, no `PYTEST_TRUNCATE_DB`.

**Changes:**

1. **§3.1 suitability + loud fallback**
   - `backend/app/script/suitability.py`
     - `_STYLE_DESCRIPTIONS["archival_montage"]` (~lines 54–64) — same
       voice as the other three (when it is right, and when it is
       wrong). Copy grounded in `STYLE_PACING_BANDS["archival_montage"]`
       (9:16, harder cuts, text cards) and the neighbouring styles'
       "wrong for" clauses.
     - `_description_for` (~lines 68–81) replaces `.get(style, style)`.
       `KeyError` on a miss, naming known keys. By the time this runs,
       the preflight endpoint has already 400'd unknown styles
       (`projects.py:731-735`), so a miss here is registry/descriptions
       drift, not a typo.
   - `backend/app/prompts/script_suitability/v1.md:14` — matching 4th
     bullet.
   - `backend/tests/unit/script/test_suitability.py` (new) — parity
     `set(_STYLE_DESCRIPTIONS) == set(STYLE_PACING_BANDS)`, every
     registered style resolves to a real description, unknown style
     raises, `archival_montage`'s text is not its own name.

2. **§3.2 glitch cap (code first, then prompt)**
   - `backend/app/planners/shot/planner.py`
     - `_GLITCH_TYPES` / `_cap_glitch_transitions` (~lines 62–116) —
       walk scene/shot order, keep the first glitch, downgrade later
       ones to `CUT`/`duration_s=0.0`. `logger.warning(..., extra={...})`
       (stdlib, not bare kwargs). Comment argues silent-correct vs fail-
       loudly per style_extensions.md §2.7, and records the wipeleft/
       fadeblack omission as a decision.
     - `ShotPlanner.plan` returns `_cap_glitch_transitions(planned_scenes)`
       after the existing `max_shots_per_project` check (~line 430).
   - `backend/app/prompts/shot_planner/v1.md:52-67` — "AT MOST ONE per
     video" softened to per-scene rarity plus an honest "you cannot see
     other scenes; a later pass caps the project at one." Prose is not
     the enforcement.
   - `backend/tests/unit/planners/test_shot_planner_glitch_cap.py`
     (new, own file per §4.4) — first-of-three survives; single-glitch
     untouched; wipeleft/fadeblack/dissolve/fade never modified; two
     glitches in one scene keep only the first; `_GLITCH_TYPES` is
     exactly the three custom values.

3. **§3.3 `punch_in` on the base camera table**
   - Re-read `shot_planner_styles/retention_fast.md` (`punch_in` is the
     default; `pull_back` on reveal, `pan` on introduce;
     `slow_push`/`slow_zoom` off-limits) and `archival_montage.md`
     (`punch_in` reserved for `emphasize`; `pan`/`slow_push` carry most
     shots) before writing.
   - `backend/app/prompts/shot_planner/v1.md:29-33` — added as a
     register note, **not** a remap of `emphasize → punch_in` (that
     would contradict `emphasize → slow_zoom` for archival/stillness
     and fight `archival_montage`'s "reserved for emphasize" only if
     the base claimed it as the default for that intent). Style
     fragments that make it a default, or reserve it for emphasize,
     still override.

4. **§3.4 duration precedence**
   - Confirmed against `_make_validator` (`planner.py` fragment tiling
     ~185-208 hard-fails; min/max ~210-214 hard-fails; scene-sum
     ~238-244 uses `tolerance = max(1.0, 0.2 * scene.duration_s)`).
   - `backend/app/prompts/shot_planner/v1.md:79-90` — that order,
     written as what the validator actually hard-fails, not a
     preference. Scene-sum called an estimate (narration_locked
     replaces it later).

5. **§3.5 examples**
   - `backend/app/prompts/scene_planner/v1.md:15-24` — good/bad pair
     from the live `3d56cf87` radar timeline (nine real scene titles,
     46 shots): "The Invisible Weapon" → "Chain Home's Principle" as a
     narrative turn vs splitting on a five-fragment quota.
   - `act_planner/v1.md` **unchanged**. No stored act split exists on
     that project (46 shots, under the long-form threshold). A 4-act
     grouping of those titles would have been invented. Skipped per
     §3.5's own rule.

**Verification performed:**

```
.venv\Scripts\python.exe -m pytest
  tests/unit/script/test_suitability.py
  tests/unit/planners/test_shot_planner_glitch_cap.py
  --noconftest -q
```

**12 passed** (7 suitability + 5 glitch-cap). No warnings. `PYTEST_TRUNCATE_DB`
was never set. `ruff check` clean on the four Python files; `black`
applied to `planner.py` and the glitch-cap test.

**Effects / reviewer notes:**

- Every real `archival_montage` preflight now gets a real style
  description instead of the string `archival_montage`. Style #5 fails
  `test_style_descriptions_cover_every_pacing_band` on the day it is
  added.
- A multi-scene script can no longer accumulate one glitch per scene.
  The first in document order is kept; the rest become cuts. Existing
  single-glitch (or zero-glitch) timelines are byte-identical through
  this pass.
- `documentary_archival` / `stillness` now know `punch_in` exists, with
  guidance that it is rarely right for them. `retention_fast` /
  `archival_montage` fragments still override.
- Shot-planner duration conflicts now have a stated priority matching
  the validator, so the model is not guessing on a constraint that
  actually hard-fails.
