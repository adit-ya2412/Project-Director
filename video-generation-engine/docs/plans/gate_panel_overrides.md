# Plan: every image a shot uses is visible and replaceable at the gate

Status, 2026-09-07: **P3a BUILT** (commit `6dac690`). P0, P1, P2, P3b, P4
still to build. Provider choice settled — see §7.

Section order note: §7 (external sourcing, measured) sits before §6
(implementation log) because the log grows downward and §7 is reference.

Written to be handed to a coding agent. Slices are ordered and the order
matters: **P0 and P3a each ship alone and each fix a live problem**, before
any layer work exists. Build in the order given.

Scope confirmed by the user 2026-09-06: build all of P0–P4. See §5.

---

## 0. Orientation — read these before writing code

- **Canon lives in `docs/13_Implementation_Guide.md`.** Every id this plan
  cites is defined there: `I2` (line ~108, the Timeline holds decisions and
  never media), `I5` (line ~120, rendering is a pure function), `A25` /
  `A25a` (line ~1514, what a human override locks and why). `I6` (nothing
  expensive before human approval) and `R1`/`R2` are in the same document.
- **There is no `CLAUDE.md` in this repo**, only a `.claude/` config
  directory. Learn conventions by reading neighbouring code.
- **This codebase documents WHY, heavily and deliberately.** Match that
  register. Comments record measured reasons and decisions; they never
  restate what the code plainly does.
- Related plan: `docs/plans/illustrated_faceless.md` — F2 built the parallax
  layers this plan makes reachable. Its §7 log and §8 landmines are worth
  skimming.

### Constraints

- **Do not start a server.** The user runs their own.
- **Do not spend money.** No fal.ai, no ElevenLabs, no renders. Everything
  here is verifiable offline.
- `pytest tests/unit` ad-hoc is safe. **Do not** run `make test` or seed with
  `--force` — both wipe the shared dev database.
- Test baseline at time of writing: **1223 passing, 6 failing** (5 in
  `test_sfx_overlays_diegetic.py`, 1 cross-project pollution in
  `test_director_planner.py`). Pre-existing. Report if the count changes.
- Postgres may be down; every slice here is unit-testable without it.

---

## 1. The problem, measured

The user's cost-saving workflow is to copy a shot's prompt at the approval
gate, generate the image with a provider whose quota they already pay for
(Gemini, Grok), and upload the result instead of paying fal.ai 4c. It works
well for single-image shots.

It breaks on any shot using **more than one** image, because the gate can only
replace one of them.

Measured 2026-09-06:

| Fact | Where |
|---|---|
| `_OVERRIDE_PANELS = frozenset({"primary", "secondary"})` | `app/api/projects.py:187` |
| `overrideShot` sends **no** `panel`, so every upload lands on the default `primary` | `frontend/src/lib/api.ts:322` |
| `grep -rn "panel=" frontend/src/` → nothing | — |
| `grep -rn "layers" frontend/src/` → nothing. The gate does not know layers exist | — |
| Upload path reads bytes, calls `validate_and_identify_image`, stores. Never calls `center_crop_to_canvas` | `app/api/projects.py` override handler |
| Generation path applies `center_crop_to_canvas` at 4 call sites | `app/workflow/steps/resolve_assets.py` |

### What it costs today

**Split-screen, in the styles that allow it.** The user supplies the top
panel; the bottom always generates. Two providers, two media, **side by side
in one frame**. This has been happening on every hand-supplied `split_frame`
shot.

**Parallax, in `illustrated_risograph`.** A parallax shot's picture is two
generated planes, neither reachable. Measured on project `a9dde33c`
(`The City Rats`, 41 shots): 10 parallax shots x 2 planes = 20 images that
must come from fal.ai regardless. The film changes medium 10 times.

**The substrate border.** `center_crop_to_canvas` exists because the paper-
border artefact survived two attempts to fix it with prompt wording
(`illustrated_faceless.md` §8.1). Uploads skip it, so a provider that draws a
margin keeps it in frame.

### What it is worth

Direct saving is **80c per film** on the measured project, and that is not
the argument. Music is free (`music_cost_cents_estimate: int = 0`,
Openverse), search is free, rendering is free. The return is **coherence** —
one provider for every image — plus closing a split-screen hole that already
exists in the shipped styles.

---

## 2. The decision this plan turns on

**Where does an overridden layer image get recorded?**

There is no per-layer binding column. `ShotBindingModel` has
`asset_id`/`clip_id` and their `secondary_*` pair, nothing for layers —
deliberately (see `layer_prompt_hash`'s docstring). A layer's image is found
by **recomputing `layer_prompt_hash` and looking the clip up by
`prompt_hash`**, on every render (`app/workflow/steps/render.py:273`).

That looks like a blocker and is actually the answer.

> **Decision: an uploaded layer image is written as a completed
> `GeneratedClip` under the hash `layer_prompt_hash` would produce.**

`render.py` then finds it exactly as it finds a generated one and **needs no
change** — no migration, no new column, no second lookup path.

Safe only because the hash is **project-scoped**: it hashes
`seed = _layer_seed(_project_seed(str(project_uuid)), layer_index)`, so one
project's uploaded plane can never be served to another. Verified by reading
`layer_prompt_hash` (`app/workflow/steps/resolve_assets.py:566`) on
2026-09-06. **Re-verify before relying on it** — if that seed ever leaves the
hash, this decision is void.

Rejected: **per-layer binding columns** (a migration plus changes to
`render.py`, `is_satisfied` and the fingerprint, to buy what the hash lookup
already does); **recording the override on the Timeline** (violates I2).

---

## 3. Slices

### P0 — Export every prompt for a film, in one action

**Ships alone. Do this first.** With 61 images on a 41-shot film, the real
friction is not uploading — it is copying 61 prompts one at a time. This is a
fraction of the work of P1–P4 and may be worth more than all of them.

One action at the gate that yields every image prompt for the project in
shot order: shot id, panel/plane, and the exact prompt string that would be
sent. Include layer prompts (`layer_styled_prompt`) even though they are not
yet uploadable — the user can already generate them, they just cannot supply
them until P1.

- Use the SAME prompt-construction functions the generation path uses, never
  a re-derivation. For layers that is `layer_styled_prompt(shot, layer,
  creative_context, frame=frame)`; find the primary's equivalent and reuse it.
  (R1: one rule, one place — a second copy of prompt construction WILL drift.)
- Format: plain text, copyable in one gesture. Not JSON unless the user asks.
- **Each exported prompt MUST state the aspect ratio and orientation in
  words.** Measured 2026-09-06 and non-obvious: the real pipeline sends size
  as an API parameter (`image_size: {width: 778, height: 1383}`) that does
  not exist when a human pastes prompt text into a chat UI. With no
  orientation in the words, providers guess — Grok returned 784x1168 (2:3),
  Qwen returned 1664x928 (landscape) for a 9:16 film. Adding
  `Vertical portrait image, 9:16 aspect ratio, much taller than it is wide`
  did **not** fix Qwen (it ignored the text and needed its UI aspect
  setting), so the export should ALSO tell the user to set the provider's own
  aspect control. State both; rely on neither alone.
- Include the substrate/no-text guidance the shipped prompts are missing
  (see §7.3) if that gap has not been closed by then.

**Done when:** a 41-shot project yields 61 prompts in order, each
byte-identical to what generation would send apart from the added
orientation preamble, and the export names the target pixel size. Test the
prompt-body identity directly.

### P3a — Frontend: show both panels of a split-screen shot

**Ships alone, immediately after P0, and depends on no other slice here.**
`panel=secondary` has worked server-side since R16 and has never been
reachable from the UI, so this fixes a problem that exists in the shipped
styles today — confirmed by the user 2026-09-06 as happening "fairly often".

Every hand-supplied `split_frame` shot has so far been one provider on top
and fal.ai on the bottom, mismatched **inside a single frame**. That is more
visible than the same mismatch spread across separate shots.

The gate renders one image per shot. For a `split_frame` shot it should
render both panels, each with its exact prompt (copyable), its own upload
control posting `panel=primary` or `panel=secondary`, and its
resolved/pending/failed state.

**Done when:** a `split_frame` shot offers two upload slots posting
`panel=primary` and `panel=secondary`, and neither one touches the other's
binding.

### P1 — Backend: a panel target for every image a shot uses

Extend the override endpoint's panel vocabulary to name a layer plane.

> **Decision: index form, `layer:0` / `layer:1`.** Not role names. Indices
> generalise to F3's third plane, roles could legitimately repeat (two
> foreground planes), and `layer_index` is already the addressing scheme
> `layer_prompt_hash` and `_layer_seed` use. Keep `_OVERRIDE_PANELS`
> membership-testable — parse the index out and validate it separately.

- Validate against the shot's real shape, the way `panel=secondary` already
  400s when `camera.movement != SPLIT_FRAME`: the index must exist in
  `Shot.layers`.
- Write bytes as a completed `GeneratedClip` under the computed
  `layer_prompt_hash` (§2), reusing the generation path's storage helper.
- **Fit every upload to the canvas, for every panel** including the existing
  `primary`/`secondary`. This is a behaviour change to a shipped path (see
  §4.4) and belongs here, not a later slice.

  > **CORRECTION, 2026-09-06.** An earlier version of this bullet said
  > "apply `center_crop_to_canvas` on upload". **That is wrong and would
  > destroy uploads.** That function takes a literal canvas-sized window
  > from the centre and never scales — correct for the generation path,
  > which requests only ~8% over canvas, and catastrophic for an arbitrary
  > upload. Measured: Qwen delivers 1536x2688, and a literal 720x1280
  > centre window covers 47% of that frame and landed entirely on the
  > subject's shirt — 2 of 5 planes keyed at all.
  >
  > The correct policy is **scale to COVER `canvas x (1 +
  > substrate_crop_oversize_fraction)`, aspect preserved, then hand those
  > bytes to `center_crop_to_canvas`.** Measured 2026-09-06 against real
  > Qwen output: 5/5 planes pass the key guard with this, 2/5 without. The
  > existing 8% constant is already the right margin — it trims a
  > provider-drawn paper edge exactly as it does for fal.ai. No new
  > constant, no new sampler.

**Done when:** uploading to `layer:1` of a parallax shot causes the next
render to composite that image as the subject plane, proven without a paid
render by asserting `render.py`'s own lookup resolves to the uploaded clip.

### P2 — Reject a plane that will not key, at upload time

A subject plane is chroma-keyed against magenta sampled from the delivered
bytes. `check_keyed_fraction` rejects outside
`_KEYED_FRACTION_MIN`/`_KEYED_FRACTION_MAX` (0.15/0.95);
`check_keyed_distribution` catches scatter. Both in `app/renderer/parallax.py`.

Today those run at render. An uploaded plane that fails degrades the shot to
a flat image (`should_composite_parallax` returns `False`) — quietly, minutes
later, after the user has moved on.

Run the same guard **at upload**, using the production functions (never a
reimplementation), and return the measured keyed fraction in the error so the
user knows whether the magenta was patchy or the subject too large.

**The thresholds are not yet trustworthy for this workflow.** `0.15`/`0.95`
were measured against Seedream output only. The user will be pasting into
**Gemini and Grok** (confirmed 2026-09-06), and Gemini in particular tends to
add gradients and vignettes to a flat colour field — the exact thing the guard
rejects. Before trusting the numbers, measure: have the user generate a
handful of magenta-field subject planes in each provider, run
`sample_key_colour` / `keyed_fraction` / `keyed_scatter_fraction` over them,
and record the real distribution in §6. This is free and needs no render.

Ship the guard with the existing constants; retune only against measured
samples, never by guessing. If a provider turns out to need different bounds,
that is a per-provider fact and does not belong hardcoded in
`app/renderer/parallax.py`.

**Done when:** a synthetic plane with a gradient magenta is rejected at upload
with its measured fraction in the message, a clean one is accepted, and §6
records the measured fractions from real Gemini and Grok samples.

### P3b — Frontend: show a parallax shot's two planes

Extends P3a's per-image UI to layers. Needs P1's backend.

A `parallax` shot renders two upload slots posting `layer:0` and `layer:1`,
each with its layer prompt (`layer_styled_prompt`) copyable.

> **Decision on a parallax shot's primary:** show it, behind a collapsed
> disclosure labelled as the fallback used only if a plane fails. Hiding it
> leaves a fallback nobody can control; showing it prominently invites wasted
> uploads.

**Done when:** a `parallax` shot offers two slots posting `layer:0` and
`layer:1`, with the fallback primary present but de-emphasised.

### P4 — Lock semantics for layers

`A25`/`A25a` freeze a shot's `prompt`/`asset_plan`/`secondary_*` after an
override so a re-plan cannot invalidate a hand-supplied image. They say
nothing about layers.

An uploaded plane is keyed by a hash **derived from the layer's prompt**, so a
re-plan that changes that prompt silently orphans the upload — the render
recomputes a different hash, finds nothing, generates. Extend the lock to
cover `Shot.layers` when a layer override exists.

**Read `A25a` first.** It records that enforcement is *reject loudly*, and
that there is **no unlock endpoint** — a shot locked by an override cannot be
handed back to the planner today. Do not add one here; A25a says to add it
when re-planning arrives, not before. Just do not make that gap worse.

**Done when:** appending a version that changes a locked shot's layer prompts
raises, with a message naming the shot and the layer.

---

## 4. Cautions

**4.1 R2 / fingerprint.** Layer bytes reach the render fingerprint via
`layer_content_hashes`, populated from the clips `render.py` looks up. Because
an upload becomes a clip under the same hash, this should follow for free —
**verify with a test, do not assume**. F5 found `compute_shot_stream_
fingerprint` hand-picks its fields and needed an explicit entry where the
whole-timeline functions did not.

**4.2 DRY_RUN hashes are not project-scoped.** `layer_prompt_hash` returns
`generation_prompt_hash(prompt, "fake_image", ...)` with no seed when
`settings.dry_run` is set. Fine for tests, but any test asserting the
project-scoping property of §2 must not run under dry-run.

**4.3 Never let an upload become a cross-project cache entry.** Image and
narration caches are global by hash — `app/projects/deletion.py` exists
because of that. Layer hashes are project-scoped by seed and therefore safe.
If any path ever writes an uploaded image under a hash **without** a
project-scoped seed, that property is lost. State this in the code, not only
here.

**4.4 The crop changes shipped behaviour.** Adding `center_crop_to_canvas` to
the upload path trims every hand-supplied image from now on. That is the
intent, and it changes bytes for anyone re-uploading an image they uploaded
before. Call it out in the commit; do not slip it in.

**4.5 Do not hardcode tunable values in tests.** Three tests in this project
have already failed on tuning rather than regression (a `749x1332` crop size,
a `0.85` guard ceiling, an alpha filter chain twice). Derive from module
constants.

---

## 5. Resolved with the user, 2026-09-06

1. **Scope: build all of P0–P4.** P0 alone was offered and declined; the user
   wants the coherence fix, not only the copy-paste relief. Note the
   distinction that drove the choice — **P0 fixes effort, not coherence**: it
   makes 61 prompts copyable in one gesture but leaves the 20 parallax planes
   unsuppliable, so the film would still change medium 10 times.

2. **Split-screen is frequent in the existing styles**, so P3a fixes a live
   defect rather than enabling a future one. This is why P3a was split out of
   P3 and moved ahead of all layer work: it needs only `panel=secondary`,
   which already works server-side, and it can ship before P1 exists.

3. **Providers are Gemini and Grok, both.** Two consequences:
   - P2's thresholds need measuring against real samples from each (see P2).
   - **Coherence is per-film, not per-provider.** Using Gemini for some shots
     and Grok for others *within one film* reintroduces exactly the mismatch
     this plan removes. Whatever the gate ends up showing, it should not
     encourage mixing inside a single project. Worth a line of UI copy in
     P3a/P3b.

## 5b. Still open

1. **Does the gate need to enforce one-provider-per-film, or just advise it?**
   Enforcing means tracking which provider supplied each image, which nothing
   currently records. Advising is a sentence of UI copy. Start with advising;
   revisit only if mixing actually happens in practice.

---

## 7. External sourcing — what was measured, 2026-09-06

The whole point of this plan is that the user generates images in a provider
whose quota they already pay for and uploads them. Three providers were tested
against `illustrated_risograph` subject planes, using the production
`sample_key_colour` / `keyed_fraction` / `keyed_scatter_fraction` and the
production compositor. Guards: keyed fraction 0.15–0.95, scatter < 0.0007.

### 7.1 Verdict: Grok is the pick

| | Grok | Gemini | Qwen |
|---|---|---|---|
| Watermark | yes — but see 7.2 | yes | no |
| Aspect delivered | 784x1168 (2:3) | — | 1664x928 landscape; 1536x2688 once its UI aspect was set |
| Paper edge artefact | none | — | yes, 3/5 even after a corrected prompt |
| Key result | **9/10 pass** | — | 5/5 pass with the §P1 fit policy |
| Risograph fidelity | **best of the three** | — | drifts to ink sketch / graded photo, inconsistent between images |
| Faceless rule | held for "seen from behind" only | — | same |

**Chosen: Grok.** Its key measurements were clean, it produced no substrate
edge, and its risograph rendering was the most faithful. Qwen's fatal flaw is
not the key — it is that the SAME world token came back as a bold ink
illustration in one image and a graded photograph in another, which is the
incoherence this whole exercise exists to remove, merely relocated from "two
providers" to "one inconsistent provider".

**Not tested, deliberately** (the user called a halt to probing 2026-09-07):
Grok background planes, and whether Grok holds one medium across ~60 images.
The second is the real risk and it is unmeasured. If a film comes back
visibly mixed, that is where to look first.

### 7.2 The watermark is NOT a blocker — an earlier claim here was wrong

Recorded because the reasoning error is instructive. It was measured that
~12% of Grok's watermark pixels **survive the chroma key** (the mark is a
semi-transparent light logo, so it shifts the magenta outside the 0.06
`colorkey` tolerance). That measurement is correct. The conclusion drawn from
it — that the mark therefore lands in the finished frame — was **not**, and
was asserted before following the bytes through to the composite.

Two later stages remove it, verified on a real composite at t=0, t=2s and
t=3.9s of a 4s shot (`tmp/key-samples/watermark-demo/`):

1. the substrate crop trims the outer margin before anything is persisted;
2. a parallax plane is scaled to **1.2x** and hangs 72px off each side and
   128px off top/bottom (the "scale must COVER the output" rule that stops
   drift exposing an edge), so a corner mark sits outside the canvas.

**The caveat that keeps this from being a design guarantee:** it works
because Grok delivers 2:3, and forcing that into 9:16 crops ~104px per side.
If Grok ever delivers native 9:16, the crop shrinks to 29px per side and a
mark ~10% in from the bottom **would** survive on plain, non-parallax shots,
which get no 1.2x overscale. So: currently removed by the aspect mismatch and
the crop, not by design. Re-check if Grok's output size changes.

**Lesson worth keeping:** surviving the chroma key and appearing in the frame
are different questions. Follow the bytes to the composite before calling
something a blocker.

### 7.3 A production gap this exposed, unrelated to uploads

**There is no "no text" instruction anywhere in the shipped prompts** —
not `shot_planner_styles/illustrated_risograph.md`, not
`prompts/director/generation_only.md`, not the prompt construction in
`resolve_assets.py`. `grep -rn "no text\|lettering\|watermark" app/prompts/`
returns nothing.

The F1 microtest probe DID carry one (`No text, no lettering, no numbers, no
watermark`); production never got it. And the Director's figure block
actively invites text by specifying "a workplace ID badge" — Grok duly wrote
`RAHUL / GURGAON MNC` plus a barcode on it.

Seedream appears less eager to render legible lettering, which is why this has
not bitten yet. That is luck, not design. **Worth fixing in the style
fragment regardless of which provider the user picks**, and it is cheap.
Positive framing, per §1.3: "every badge, label and screen is blank and
unmarked", not "no text".

### 7.4 `sample_key_colour` is fragile for uploads

It takes the median of a **24px strip at the very top** of the image
(`app/renderer/parallax.py`). Correct for the generation path, where the
oversize crop has already removed any margin. For an upload with a
provider-drawn paper edge, the strip is paper: Qwen round 1 sampled
`0xF8F5E4` (cream) and **10/10 images failed the key**, despite the magenta
underneath being flat and excellent.

Two fixes were measured, and the cheap one is enough:

- **Sample inset ~8% from the edges** — recovered 5/5. But it fixes only the
  key; the cream edge stays in the image, unkeyed, and would composite over
  the background as a visible frame.
- **The §P1 fit policy (scale-to-cover at the 8% oversize, then crop)** —
  also 5/5, and it removes the edge as well. **Prefer this.** No change to
  `sample_key_colour` needed.

### 7.5 One more gap, found while building P3a

`_unfilled_shot_ids` (`app/api/projects.py`) — the guard that decides whether
the approval gate will let a project through — reads only `binding.state`,
never `binding.secondary_state`. **A split-screen shot counts as "ready" when
only its top panel is filled.** So a user who hand-supplies top panels can
approve, and the bottom panels then generate from fal.ai post-approval:
mismatched, and charged, which is the exact outcome this plan exists to
prevent.

Not fixed with P3a because it changes approval-gate behaviour — it would
start blocking approvals that currently pass, including on projects already
mid-flight. Needs the user's say-so. Small change when wanted.

Two smaller ones, both only matter when a split panel is bound to VIDEO
rather than a still: `GET /clip` takes no `panel` parameter, so a
bottom-panel clip shows as a still rather than playing; and the video
thumbnail cache path is keyed on shot alone, so two video-bound panels on one
split shot would collide.

---

## 6. Implementation log

### P3a — built 2026-09-06

**Backend (`backend/app/api/projects.py`).** `_shot_progress_entry` now
returns two new fields on every shot: `camera_movement` (emitted always —
cheap, and the gap it closes, nothing here named a shot's own camera
movement at all, is bigger than split-screen alone) and `secondary`
(emitted only for `camera.movement == SPLIT_FRAME`, `None` otherwise).
`secondary` is a nested object mirroring the primary's own shape
(`prompt`/`state`/`last_error`/`asset`/`clip`), not five more flat
`secondary_*` keys — one existence check (`shot.secondary != null`) is
now the frontend's single signal for "does this shot have a bottom
panel", matching (not duplicating) `_OVERRIDE_PANELS`' own SPLIT_FRAME-
only gate for `panel=secondary`. Extracted `_resolved_media_detail`
(asset-id-wins-over-clip-id) as a shared helper so the primary and
secondary halves build their `asset`/`clip` dicts from one rule (R1),
not two copies that could drift.

Added the "READ THIS BEFORE WRITING THE FRONTEND" comment the brief
asked for, naming A12's exact mistake (a frontend field with no backend
counterpart, invisible because TypeScript types describe the API but
never verify it) directly above the new fields, plus a payload-level
test (`tests/unit/api/test_progress_secondary_panel.py`) that asserts
against the dict `_shot_progress_entry` returns — never the frontend
type — so the same mistake cannot repeat silently here.

**Frontend.**
- `lib/types.ts`: new `ShotSecondaryPanel` interface; `ShotProgress`
  gains `camera_movement: string` and `secondary: ShotSecondaryPanel |
  null`.
- `lib/api.ts`: `overrideShot` and `shotAssetUrl` both gain a `panel:
  "primary" | "secondary" = "primary"` parameter. Every existing call
  site is unaffected — the default reproduces today's URL/behaviour
  byte-for-byte.
- `lib/queries.ts`: `useOverrideShot`'s mutation input gains an optional
  `panel`, threaded straight through to `api.overrideShot`.
- `lib/asset-source.ts`: extracted `assetSourceFromDetail(asset, clip)`
  out of `shotAssetSource(shot)` so the secondary panel can reuse the
  exact same provider→badge classification instead of a second copy.
- `pages/AssetReviewGate.tsx`: `ShotImage` and `ImageLightbox` now take
  an explicit `panel` and the specific `asset`/`clip`/`state` to render,
  instead of assuming `shot`'s own primary fields — `ShotCard`'s existing
  body calls them with `panel="primary"` and is otherwise untouched (same
  JSX, same copy, same props) for every non-split shot. A new
  `SecondaryPanelBlock` component, rendered ONLY when `shot.secondary !=
  null`, adds the bottom panel's image/prompt/state/error/upload button
  as an additive row inside the same `Card`. `overrideTarget` and
  `lightboxTarget` now carry `{ shot, panel }` instead of a bare shot, and
  the override dialog's title/copy only mentions "top/bottom panel" when
  `shot.secondary` is non-null — a non-split shot's dialog text is
  unchanged.

**Test results.** `pytest tests/unit`: 1227 passed, 6 failed (same 6
pre-existing failures named in §0 — 5 in `test_sfx_overlays_diegetic.py`,
1 in `test_director_planner.py` — count unchanged from the stated
baseline; the +4 are this slice's new payload tests). `npx tsc --noEmit`
in `frontend/`: clean. `npx oxlint` on the touched files: clean. No
server started, no paid provider called, Postgres untouched (fakes only,
per the existing `test_focal_override_api.py` idiom — no
`PYTEST_TRUNCATE_DB`).

**Corrections to the brief.**
- The "uploading to `panel=secondary` rebinds only the secondary and
  leaves the primary binding untouched — and vice versa" test the brief
  asked for **already existed** before this slice
  (`tests/unit/api/test_override_panel.py`, testing
  `apply_override_to_binding` directly) — confirmed still passing, not
  duplicated.
- `GET /shots/{shot_id}/clip` (the endpoint that streams an actual
  playable video, R10) has **no `panel` parameter** — it always resolves
  the PRIMARY binding (`_resolve_bound_media_path(session, binding)`, no
  `panel=` forwarded). The brief's "GET .../asset also already accepts
  panel" is correct and re-verified, but `/clip` is a different endpoint
  and does not. Consequence: a `split_frame` shot whose BOTTOM panel is
  bound to a motion clip (the override endpoint accepts video for any
  panel since 2026-09-02) can only be shown as `/asset`'s extracted still
  frame in this frontend, never played — a deliberate, documented scope
  decision (extending `/clip` is a backend change outside this
  frontend-only slice), not a bug in what shipped.
- Found, not fixed (both pre-existing, orthogonal to P3a's brief):
  - `_resolve_bound_media_path`'s `panel=secondary` branch is correct,
    but `get_shot_asset`'s video-thumbnail cache
    (`shot_frame_cache_path(project_id, shot_id)`) is keyed on shot only,
    **not on panel**. If both panels of one `split_frame` shot are ever
    bound to motion clips, their extracted-frame JPEGs collide on the
    same cache file. Narrow (requires two video panels on one shot,
    which nothing in this codebase produces today outside a hand
    upload) but real if it happens.
  - `approve_timeline`'s money guard (`_unfilled_shot_ids`, Task 2) reads
    only the PRIMARY `ShotBinding.state`. A `split_frame` shot can be
    approved while its bottom panel is still `awaiting_generation`, and
    the post-approval pipeline will then generate it unattended for real
    money — the same class of gap I6 exists to close, just not one this
    guard currently covers for the secondary panel. Not part of P3a's
    "Done when" (which is about visibility/upload, not the approval
    gate), so left alone here; worth its own line item if this plan
    grows a P-something for it.
