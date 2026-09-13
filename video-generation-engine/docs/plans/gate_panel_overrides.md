# Plan: every image a shot uses is visible and replaceable at the gate

Status, 2026-09-12: **P0, P3a, P1, P2, and P3b BUILT** (P3b: this
session, 2026-09-12; P2: earlier 2026-09-12; P1: earlier 2026-09-12;
P3a: commit `6dac690`; P0: 2026-09-08). P4 still to build. Provider
choice settled — see §7.

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

> **Addendum, 2026-09-13 — the gap above turned out to have TWO independent
> halves, and only one of them is still open.**
>
> The paragraph above was written while `_unfilled_shot_ids` had no notion of
> layers at all, so "reads only `binding.state`" undersold the blast radius:
> **a layered (parallax) shot ALSO has no per-layer binding column**
> (`layer_prompt_hash`'s own docstring, §2), so its binding sits at
> `awaiting_generation` forever — even once every plane is uploaded or
> generated. This is not a corner of the split-frame gap above; it is a
> second, separate hole with the opposite urgency.
>
> **Measured live, 2026-09-13, on the user's own 100-shot project
> `48086fed-02a0-46ba-be58-e2c5cf99db9e`** ("adi shankracharya decoded",
> timeline v119, `illustrated_risograph` at `frame_aspect=16:9`): the guard
> reported **11 unfilled shots**, every one `movement=parallax`,
> `binding.state='awaiting_generation'`. **10 of the 11 already had BOTH
> layer clips `completed`** — the user had supplied every image in the film
> and could not approve it. Only 1 (`act_02_sc_03_sh_03`) was genuinely
> missing a plane (layer 1) and correctly needed to keep blocking.
>
> **Fixed this session (permissive, ships without further sign-off — I6
> already requires blocking a genuinely incomplete shot, and this change can
> only ever turn a reported-unfilled shot into filled, never the reverse):**
> `_unfilled_shot_ids` now also checks, for any shot with non-empty
> `shot.layers`, whether EVERY layer resolves to a `status == "completed"`
> `GeneratedClip` (`resolved_layer_clips`, extracted into
> `resolve_assets.py` and shared with `render.py`'s own lookup — R1, one
> walk, not two that could drift). Gated on `shot.layers` being non-empty,
> never on `camera.movement == PARALLAX` — `_cap_parallax_layers` leaves 19
> shots on this same project at `movement=parallax, layers=[]`, rendered as
> a plain still that still needs its ordinary primary image; those must
> (and do) keep falling back to `binding.state` unchanged. A shot with even
> one unresolved plane still blocks, same as before.
>
> **Still open, unchanged, needs the user's own say-so before touching it:**
> the split-frame half this paragraph originally described —
> `binding.secondary_state` is still never read. That fix is *restrictive*
> (it would start blocking approvals that pass today, including projects
> already mid-flight), the opposite direction of risk from the layer fix
> above, which is why the two halves are being tracked and decided
> separately rather than bundled. See §6's implementation-log entry for this
> session for the full account.

---

## 6. Implementation log

### Gate layer fix — built 2026-09-13

**Why — a live user was blocked, right now.** The user had supplied every
image for a 100-shot film (`48086fed-02a0-46ba-be58-e2c5cf99db9e`, "adi
shankracharya decoded", timeline v119, `illustrated_risograph`,
`frame_aspect=16:9`) and the approval gate still refused. `_unfilled_shot_
ids` reads only `binding.state`, and a layer plane has no per-layer binding
column at all (§2) — uploading or generating one never touches
`binding.state`, so a fully-supplied layered shot stayed
`awaiting_generation` forever. See §7.5's addendum (same section, dated the
same day) for the full before/after account; this entry is the build log.

**Measured, read-only, against the live project (real Postgres, no
mutation — `session.rollback()`, never `commit()`):**

| | count |
|---|---|
| shots reported unfilled by the OLD `binding.state`-only check | 11 |
| … of those, already had BOTH layer clips `status="completed"` | 10 |
| … of those, genuinely still missing a layer (`act_02_sc_03_sh_03`, layer 1) | 1 |
| parallax shots total on this project | 32 |
| … with `layers=[]` (capped by `_cap_parallax_layers`, renders as a plain still) | 19 |
| … with non-empty `layers` | 13 |

After the fix: unfilled count is **1** (`act_02_sc_03_sh_03`, correctly
still blocking), and all 19 empty-layer parallax shots were confirmed
**not** wrongly cleared (they still fall back to `binding.state`, unchanged).

**Fix.** `_unfilled_shot_ids` (`app/api/projects.py`) is now `async` and,
for any shot whose OLD check would mark it unfilled, additionally checks —
only when `shot.layers` is non-empty — whether every layer resolves to a
completed, on-disk `GeneratedClip`. Gated on `shot.layers`, never on
`camera.movement == PARALLAX`: the 19 empty-layers shots above prove those
are two different questions. A shot with even one unresolved layer (missing
clip, wrong `status`, or a `local_path` file no longer on disk) still
blocks — never a partial pass, matching `build_two_layer_parallax_filter_
complex`'s own all-or-nothing `[background, subject]` requirement. Strictly
permissive: the new path can only remove a shot from `unfilled`, never add
one, so it cannot let a genuinely incomplete shot through I6's money gate.
`binding.secondary_state` (the split-frame half of §7.5's original note) is
untouched — see the §7.5 addendum for why that stays open.

**R1: the per-layer hash-and-lookup walk is not duplicated.** It already
existed inline inside `render.py`'s `resolve_render_inputs` (recompute
`layer_prompt_hash` per layer, `GeneratedClipRepository.get_by_prompt_
hash`, require every one). That walk was extracted verbatim into a new
`resolved_layer_clips(shot, *, project_uuid, creative_context, style,
frame_aspect, clip_repo)` in `app/workflow/steps/resolve_assets.py`
(returns `None` unless every layer resolves, else the ordered list of
`GeneratedClip`s), and both `render.py` and `_unfilled_shot_ids` now call
it. Extraction, not a fresh implementation reusing only `layer_prompt_
hash` — the gate and the renderer must reach the identical verdict about
which layered shots are ready, or the gate could approve a film the
renderer then can't composite. One behavioural addition over the old
inline code: an explicit `clip.status == "completed"` check. Today that is
redundant (`GeneratedClipModel`'s own docstring: `local_path` is only ever
set together with `status="completed"`), but a money gate should fail
closed against that invariant ever changing, not rely on it silently.

**`style`/`frame_aspect` reach the helper the production way.** Both call
sites in `_unfilled_shot_ids` already had the active `Timeline` in hand
(`approve_timeline`/`approve_scene` both resolve it before calling this
helper) and read `timeline.metadata.render_style` /
`timeline.metadata.frame_aspect` / `timeline.creative_context` /
`uuid.UUID(timeline.project_id)` — the exact fields `render.py` and every
existing `layer_prompt_hash` call site in this file already use. No
default assumed, no guess: the measured project is `16:9`, and a helper
that silently assumed the 9:16 canvas default would have computed the
wrong hash and found nothing, reproducing the same bug under a different
cause.

**Tests.** New `tests/unit/api/test_unfilled_shot_ids_layers.py` (5 cases,
calling `_unfilled_shot_ids` directly with a monkeypatched
`GeneratedClipRepository` — same idiom as `test_progress_layer_panels.py`):
parallax shot with both layer clips completed → filled; one layer missing
→ still unfilled; a layer clip present but not `status="completed"` → still
unfilled; `movement=parallax` with `layers=[]` → falls back to
`binding.state` (unfilled while `awaiting_generation`, filled once
terminal); a plain non-layer shot → behaviour unchanged (no binding /
non-terminal / every `_TERMINAL_SHOT_STATES` value). Focused run:
`pytest tests/unit/api/test_unfilled_shot_ids_layers.py tests/unit/api/
test_progress_layer_panels.py tests/unit/api/test_progress_secondary_panel.py
tests/unit/api/test_override_layer.py tests/unit/api/test_override_panel.py
tests/unit/api/test_focal_override_api.py tests/unit/workflow/
test_layer_generation.py tests/unit/renderer/test_fingerprint_parallax.py
tests/unit/assets/test_substrate_crop.py -q` → **90 passed**.
`tests/unit/timeline/test_shot_layers.py tests/unit/workflow/
test_render_step.py -q` → **34 passed** (proves the `render.py` extraction
didn't regress the render step). Full `pytest tests/unit -q`: baseline
measured fresh this session (branch had moved since the last recorded
baseline) at **1726 passed, 6 failed** — the same 6 named in §0 (5 in
`test_sfx_overlays_diegetic.py`, 1 in `test_director_planner.py`); after
this fix, **1731 passed, 6 failed** — same 6, +5 for the new test file, no
new failures.

**Re-verification.** No server started, no fal.ai / ElevenLabs / paid
provider called, no `make test` / seed `--force`. The live project was
read via a throwaway script (`async_session_factory`, real Postgres,
`session.rollback()` at the end, `commit()` never called) purely to
confirm the diagnosis's numbers and the fix's effect — nothing about that
project was written. **Standing cleanup performed this session** (per the
recurring instruction, `project_purge_test_projects.md`): 134 leaked
`*-test`/probe-named projects deleted via `scripts/purge_test_projects.py`
(the real `delete_project` path, one at a time) — 0 failures; all 38
human-named films survive untouched, confirmed by a follow-up dry-run
(`0 leaked, 38 keep`).

**Corrections to the diagnosis handed to this session.** None material —
every measured number (11 unfilled / 10 already-complete / 1 genuinely
missing / 32 parallax shots / 19 empty-layer / 13 non-empty) was
re-verified live against Postgres and held exactly.

**Follow-up correction, same day (2026-09-13): the first pass was
guard-only, and the UI kept the old rule.** The user restarted their
backend after the fix above and nothing changed for them — the Approve
button stayed disabled, and scenes still said "1 still need a picture".
The coordinator's own read-only check against the live project confirmed
the *guard* half was right (`_unfilled_shot_ids` now reports 1 unfilled,
matching the diagnosis, and none of the 19 empty-layer shots were wrongly
cleared), but found the "is this shot filled" question was still answered
in **three places that disagreed**:

1. `_unfilled_shot_ids` (the fixed guard) — layer-aware.
2. `GET /progress`'s own per-scene `unfilled_in_scene` counter
   (`app/api/projects.py`, `get_progress`) — still `b.state in
   _TERMINAL_SHOT_STATES` only, driving the "N still need a picture" text
   on every scene.
3. The frontend's `isFilled` (`AssetReviewGate.tsx`) — still
   `TERMINAL_STATES.has(shot.state)`, driving `canApprove` and the global
   "N still need a picture" banner.

Three independent encodings of one question is exactly the R1 failure
this codebase keeps warning about — worse than the original bug, because
the backend guard and the UI now actively disagreed about whether the
film was ready, rather than both being wrong the same way.

**Corrected shape: one server-side predicate, everything reads it.**
New `_shot_is_filled(shot, binding, *, timeline, session, clip_repo=None)`
(`app/api/projects.py`, immediately above `_unfilled_shot_ids`) holds the
exact logic the first pass put inline in `_unfilled_shot_ids` — terminal
`binding.state` first, else (only when `shot.layers` is non-empty and a
`timeline` was supplied) all-layers-resolved via the same
`resolved_layer_clips` — and is now the ONLY place that question is
answered:

- `_unfilled_shot_ids` is now a thin loop over `_shot_is_filled`.
- `_shot_progress_entry` calls it once and adds an explicit `"filled"`
  key to every shot's payload — `state` is left alone (still the honest
  raw binding state; the UI still needs it for "still searching"/"headed
  for generation"/"failed" labelling on the primary panel specifically).
- `get_progress`'s scene loop calls it per shot to decide
  `completed_in_scene` vs `unfilled_in_scene` (`b.state == "failed"` still
  separately drives `failed_in_scene`, unchanged), sharing one
  `GeneratedClipRepository` across the whole request the same lazy-once
  way the guard already did.
- The frontend's `isFilled(shot)` now returns `shot.filled` directly — no
  re-derivation from `state` or from `layers` (a frontend copy would have
  been a FOURTH encoding). Renamed the OLD `isFilled` behaviour (raw
  primary-binding-state check) to `isPrimaryFilled`, kept byte-for-byte,
  because it turned out to still be needed: `ShotCard`'s fallback-image
  section for a parallax shot (badges, "Replace fallback" vs "Upload
  fallback", and disabling "Generate video" — which needs the PRIMARY
  image as its source frame, not the planes) reads the PRIMARY panel's
  own fill state, which is a genuinely different question from "can this
  shot be approved" and must not collapse into it. `isPanelFilled`'s
  primary-panel fallback and the plain-shot override-dialog copy were
  repointed to `isPrimaryFilled` for the same reason. This is the one
  deliberate departure from "just make isFilled read the field" as
  literally proposed — argued for above rather than applied silently,
  since collapsing the two meanings would have let a layered shot's
  fallback panel wrongly claim to have an image, and let "Generate video"
  enable before a fallback frame actually exists.

**A12 trap, addressed directly.** New
`tests/unit/api/test_progress_filled_field.py` calls the real
`get_progress` endpoint function (fakes for its `Depends(...)` params,
same idiom `test_override_layer.py` uses) and asserts `"filled" in
shots_by_id[shot_id]` for every shot in the payload dict — not merely
that the value looks right — plus the scene-level counts: a fully-resolved
layered shot moves from `unfilled_shots` to `completed_shots` while its
own `state` stays `awaiting_generation`; a partially-resolved one stays
unfilled; an empty-layers parallax shot is unaffected; a plain shot is
unaffected.

**Live re-verification (read-only, second pass).** Against the same
project (`48086fed-02a0-46ba-be58-e2c5cf99db9e`, v119), calling the real
`get_progress` function directly (real repositories, not fakes;
`session.rollback()`, never `commit()`): **27 scenes, `sum(unfilled_shots)
== 1`, `sum(completed_shots) == 99`**, the one remaining unfilled scene is
`act_02_sc_03` (`unfilled=1`) containing exactly `act_02_sc_03_sh_03` —
matching `_unfilled_shot_ids` exactly (`PAYLOAD AND GUARD AGREE: True`).
All 100 shot entries carry the `filled` key (0 missing). Ten scenes that
previously showed "1 still needs a picture" now show 0.

**Tests.** `pytest tests/unit/api -q`: **69 passed** (adds
`test_progress_filled_field.py`'s 3 cases to the existing API suite).
Full `pytest tests/unit -q`: **1734 passed, 6 failed** — same 6
pre-existing failures, no new ones (1731 → 1734, +3). `npx tsc --noEmit`
in `frontend/`: clean.

**Standing cleanup, second pass.** A follow-up `--dry-run` found 201
newly-leaked `*-test` projects in the shared dev Postgres (concurrent
activity elsewhere in the same DB, not this session's own test runs,
which are fakes-only) — purged via `scripts/purge_test_projects.py`, 0
failures, all 38 human-named films (including the live project) confirmed
untouched by a following dry-run (`0 leaked, 38 keep`).

**Re-verification.** No server started, no fal.ai / ElevenLabs / paid
provider called, no `make test` / seed `--force`. The `split_frame` /
`binding.secondary_state` half of §7.5 remains untouched — still
restrictive, still needs the user's own sign-off.

### P3b — built 2026-09-12

**Why.** P1 made `panel=layer:N` writable and GET-able, but `/progress`
never said a shot had planes — the gate had nothing to render two
upload slots from. Same A12 lesson as P3a's `secondary`: inventing a
frontend field with no backend counterpart is invisible to TypeScript.
`camera_movement` already existed; **layers did not**. Without emitting
`layers` from `_shot_progress_entry`, a parallax shot's 2 planes stay
fal.ai-only and the film still changes medium mid-shot.

**Backend payload (A12).** `_shot_progress_entry` always emits `layers`:
`None` when `shot.layers` is empty or `timeline` is absent (kwarg
defaults `None` so older tests still run); otherwise a list in
`Shot.layers` index order. Each entry:

```
{index, role, prompt, state, last_error, asset: null, clip}
```

`prompt` is `layer_styled_prompt(..., frame=resolve_render_format(
style, frame_aspect))` — the string generation sends, which the user
copies into Grok — never raw `layer.prompt`. Clip lookup is the SAME
path render.py uses: `layer_prompt_hash` +
`GeneratedClipRepository.get_by_prompt_hash` (no binding column, §2).
`state`: clip.status completed→`"generated"`, failed→`"failed"`,
missing→`None`. `clip` dict matches `_resolved_media_detail`'s clip
half; `asset` stays null (layers are clips). Existence of the list
(`shot.layers != null`) is the frontend's single signal for plane
slots, matching `shot.secondary != null`. Both callers (`get_progress`
~3210, `get_scene_shots` ~3308) now pass `timeline=timeline`.

**Frontend slots + collapsed fallback.** `ShotLayerPanel` +
`OverridePanel` in `lib/types.ts`; `overrideShot` / `shotAssetUrl`
default `"primary"` (no query) and append `?panel=` for non-primary
(`secondary` and `layer:N`). When `shot.layers != null` only:
`LayerPanelBlock` per plane (role label from `role`, copyable
`layer_styled_prompt` via `CopyButton`, upload posting that panel);
primary is **not** the lead action — it lives in a collapsed native
`<details>` summarised **"Fallback image — used only if a plane
fails"** (not `Disclosure.tsx` — that is monospace technical-dump
styling, wrong for a picture). Generate / generate-video stay inside
the disclosure (no `panel` on those endpoints). Non-parallax
`ShotCard` body (including split_frame) stays the P3a shape. One line
of §5.3 coherence copy: do not mix providers inside one film
(advising, not enforcing). Dialog title/toast name the plane when
layers are set; non-parallax dialog text unchanged. `ImageLightbox`
resolves `shot.layers[i]`; layers are stills (never playable via
`/clip`).

**asset-source.** `clip.provider === "human_override"` → `"uploaded"`
before the generic clip→`"generated"` branch. P1 stores layer
overrides as clips, not assets; without this a hand-supplied plane
badges as AI.

**Tests / checks.**
- `tests/unit/api/test_progress_layer_panels.py` (new): plain/split →
  `layers is None`; parallax 2-list with `layer_styled_prompt`
  equality (call the function, no hardcoded string); completed
  layer:1 fills that entry only; no-timeline → `layers is None`.
- `test_progress_secondary_panel.py` updated only to expect
  `"layers": None` on non-layer shots.
- Focused run (from `backend/`, repo-root `.venv`):
  `pytest tests/unit/api/test_progress_layer_panels.py
  tests/unit/api/test_progress_secondary_panel.py
  tests/unit/api/test_override_layer.py -q --tb=short` → **25
  passed**.
- From `frontend/`: `npx tsc --noEmit` clean; `npx oxlint` on the
  five touched files → **0 warnings, 0 errors**.

**Corrections to the brief.** None material. `timeline` is an optional
kwarg (default `None` → `layers=None`) rather than required, so
existing unit callers keep working; production callers pass it.

**Found-not-fixed leftovers** (explicitly out of this slice): P4 lock
layers; `_unfilled_shot_ids` still ignores `secondary_state` and
layers; `GET /clip` still has no `panel`. Do not fix those here.

**Re-verification.** No server started, no fal.ai / ElevenLabs /
Gemini / Grok / paid provider called, no `make test` / seed
`--force`, no shared-Postgres test projects created (fakes only).

**Orchestrator review (grok-4.6, 2026-09-12).** Implemented by a
`grok-4.5` subagent (`01a095ee-31a4-79a3-87e8-54f41bf94a19`). Brief
held: A12 payload first (`layers` on `_shot_progress_entry` with
`layer_styled_prompt` + hash lookup), two plane slots posting
`layer:0`/`layer:1`, primary collapsed as fallback, `human_override`
clips badge as uploaded, non-parallax card including split_frame
kept. Re-ran: **25 passed**, `tsc --noEmit` clean, oxlint 0/0. No
browser in this session — refresh the gate on a parallax project
(e.g. The City Rats) to see the slots. Next slice is **P4** (lock
`Shot.layers` so a re-plan cannot orphan an uploaded plane).

### P2 — built 2026-09-12

**Why.** Render already runs `sample_key_colour` → `keyed_fraction` →
`check_keyed_fraction` → `keyed_scatter_fraction` →
`check_keyed_distribution` on a SUBJECT plane and, on
`ParallaxKeyGuardError`, degrades that shot to flat
(`slideshow.py` ~793). An uploaded plane that fails therefore composites
wrong minutes later, quietly. The gate is where the human can still
retry — same production sequence, HTTP 400 with the measured fraction
in `detail`, no lock and no clip write.

**Backend.** New `guard_subject_plane_bytes(image_bytes, *, shot_id="",
layer_role="")` in `app/renderer/parallax.py` runs that exact five-call
sequence and returns the sampled key (so render does not re-sample).
`override_shot_asset` (`app/api/projects.py`) calls it **after**
`fit_upload_to_canvas` and **before** `append_version`, only when
`panel_kind == "layer"` and `shot.layers[layer_index].role` is
`SUBJECT` or `FOREGROUND` (FOREGROUND treated like subject if it ever
appears; today F2 is BACKGROUND+SUBJECT only). BACKGROUND (`layer:0`)
and primary/secondary are unguarded — background is unkeyed; primary is
the flat fallback. On `ParallaxKeyGuardError`: HTTP 400,
`detail=str(exc)` (messages already distinguish zero / too-low /
ate-subject / scatter and include the measured fraction). Reject-before-
lock mirrors the video-on-layer 400: no `append_version`, no clip write,
no binding change.

**Fit-then-guard order is load-bearing (§7.4).** `sample_key_colour`
reads a 24px top strip. A paper-edged upload samples cream and falsely
fails a plate that keys after the P1 cover-then-crop. Guard runs on
fitted bytes only.

**R1 extract, not a second implementation.** `slideshow.py`'s existing
try-block now calls `guard_subject_plane_bytes` instead of inlining the
five calls. Degrade-on-failure behaviour is unchanged: catch
`(ParallaxKeyGuardError, OSError, ValueError)`, log
`render.parallax_guard_failed_degrading`, set `parallax=False`.

**Thresholds.** Shipped Seedream constants unchanged
(`_KEYED_FRACTION_MIN`/`_MAX` 0.15/0.95, `_SCATTER_FRACTION_MAX`
0.0007). Not retuned this slice.

**Provider sample honesty (done-when §6 / §7.1).** User halted provider
probing 2026-09-07. Quoting §7.1 as the measured distribution we have:
**Grok 9/10 pass** on these exact guards (keyed fraction 0.15–0.95,
scatter < 0.0007); Gemini key column is empty / **still unmeasured**
(halt). No new paid samples were generated this session. Ship Seedream
constants; do not invent Gemini numbers.

**P1 test fixture correction.** P1's `test_override_layer.py` uploaded
solid-colour PNGs to `layer:1`. Those are fraction-0 under the new
guard. Layer:1 uploads in that file are now subject-like plates (flat
magenta field + figure in the lower portion). `layer:0` BACKGROUND
stays unguarded (solid / gradient still 202).

**Tests.** Extended `tests/unit/api/test_override_layer.py`:
- gradient-magenta SUBJECT → 400, `detail` equals
  `str(ParallaxKeyGuardError)` from `guard_subject_plane_bytes` on the
  same fitted bytes (measured fraction in the message); no lock, no clip;
- clean subject-like → 202, clip under `layer_prompt_hash`, canvas-sized;
- gradient on `layer:0` BACKGROUND → 202;
- primary solid colour → 202 (guard is not for primary);
- solid non-magenta SUBJECT → 400, `append_calls == []`, empty clip repo;
- existing P1 layer:1 cases updated to keyable plates.

Focused run (from `backend/`, repo-root `.venv`):
`pytest tests/unit/api/test_override_layer.py
tests/unit/renderer/test_parallax.py
tests/unit/api/test_override_panel.py
tests/unit/api/test_focal_override_api.py
tests/unit/renderer/test_fingerprint_parallax.py -q --tb=short`
→ **105 passed**. Did not run full `pytest tests/unit` / `make test`;
the 6 pre-existing unit failures named in §0 were left alone.

**Corrections to the brief.** None material. The brief already required
fit-then-guard, SUBJECT-only, reject-before-lock, and the R1 extract;
all shipped as specified. Gemini measurement was acknowledged as halted
rather than inventing numbers.

**Found-not-fixed leftovers** (explicitly out of this slice): P3b
parallax gate UI; P4 lock layers; Gemini still unmeasured; thresholds
not retuned; `_unfilled_shot_ids` still ignores `secondary_state` and
layers; `GET /clip` still has no `panel`.

**Re-verification.** No server started, no fal.ai / ElevenLabs / Gemini
/ Grok / paid provider called, no `make test` / seed `--force`, Postgres
unused (fakes only).

**Orchestrator review (grok-4.6, 2026-09-12).** Implemented by a
`grok-4.5` subagent (`01a095bb-cba2-7631-a3cd-84871b49d054`). Brief
held: fit-then-guard, SUBJECT/FOREGROUND only, reject before lock,
shared helper with slideshow, Seedream thresholds untouched, P1
layer:1 fixtures switched to keyable plates. Re-ran the focused suite:
**105 passed**. Gemini remains unmeasured (halt 2026-09-07); Grok 9/10
from §7.1 is what §6 records. Next slice is P3b (parallax slots at the
gate).

### P1 — built 2026-09-12

**Backend.** `_OVERRIDE_PANELS` stays `frozenset({"primary",
"secondary"})` — membership-testable as the brief required. New
`_parse_override_panel` (shared by `override_shot_asset` and
`get_shot_asset`) accepts those two plus `layer:<int>` via
`^layer:(\d+)$`. Role names (`background`/`subject`) are 400 with a
message listing the allowed forms. Shape checks stay at the call site:
`secondary` still requires `SPLIT_FRAME`; `layer:N` requires
`0 <= N < len(shot.layers)` (a shot with no layers, or `layer:2` on a
2-layer shot, is 400).

`panel=layer:N` does **not** call `apply_override_to_binding` (no layer
columns; that helper now raises if handed anything outside
`_OVERRIDE_PANELS` so a future caller cannot silently fall through to
PRIMARY). The shot is still `asset_locked` via the existing
`append_version` path (A25, shot-wide). Bytes land as a completed
`GeneratedClip` under the SAME `layer_prompt_hash(...)` call
`render.py` uses, at `storage/{project}/clips/{prompt_hash}.{ext}` —
the path shape `generate_layer_image_real` already writes. Provider/
model are `human_override`, `cost_cents=0`. Video on a layer is 400
(parallax planes are stills). Focal/vision is skipped for layer panels
(Ken Burns does not aim keyed planes).

**Replace-in-place.** `prompt_hash` is UNIQUE globally. If a fal.ai row
already sits under that hash, the file is overwritten and the existing
row is updated (`local_path`, `status="completed"`,
`provider`/`model_id="human_override"`, `cost_cents=0`, `error=None`) —
never inserted (unique collision). Safe as a human override of THIS
project's plane because real-mode `layer_prompt_hash` still folds
`_layer_seed(_project_seed(project_uuid), layer_index)` — re-verified
this session by reading the function body. A hash that dropped the
project seed would turn the overwrite into cross-project cache poison
(§4.3); that comment is in the code, not only here. DRY_RUN hashes
remain unscoped (§4.2); fine for unit tests.

**Fit policy (P1 CORRECTION / §4.4).** New
`fit_upload_to_canvas` in `app/assets/substrate_crop.py`: scale to COVER
a caller-supplied cover size (LANCZOS), then `center_crop_to_canvas`.
Cover comes from `resolve_generation_request_format` at every use site
— never `substrate_crop_oversize_fraction` directly (R1). Applied to
EVERY still upload (primary, secondary, AND layers) after image
validation and before content_hash/store, so persisted bytes are the
fitted ones. Videos skip fit. This **changes shipped primary/secondary
upload bytes**. Bare centre-crop on a Qwen 1536×2688 was the wrong
policy (shirt-only window, 2/5 keyed); cover-then-crop keyed 5/5.

**Fingerprint (§4.1).** `resolve_render_inputs` still looks layers up via
`layer_prompt_hash` + `get_by_prompt_hash` (no second lookup path). What
it puts in `layer_content_hashes` is now `sha256` of the clip **file
bytes** (`_file_sha256` local to `render.py`), not the prompt_hash
string. A human overwrite under the same hash therefore misses the
whole-timeline render cache instead of serving the old film.

**GET `/shots/{id}/asset?panel=layer:N`.** Resolves via the same
`layer_prompt_hash` + clip repo path; 404 if no clip yet; 400 if the
shot has no such layer. Layers are stills — video-thumbnail branch
skipped.

**Tests.**
- `tests/unit/assets/test_substrate_crop.py` — +5 fit tests (canvas
  size; scale-vs-window on a Qwen-shaped source; cover is a caller
  input; deterministic; small image upscales rather than raising).
- `tests/unit/api/test_override_layer.py` (new) — done-when
  (`layer:1` → render lookup resolves canvas-sized clip, binding
  untouched); `layer:0`≠`layer:1`; no-layers / out-of-range / role
  names / video-on-layer → 400; primary on parallax still binds;
  replace-in-place; GET `panel=layer:1`; primary upload is
  canvas-sized; file-bytes hash helper.
- `tests/unit/api/test_focal_override_api.py` — sidecar lookups now key
  on fitted bytes so A13 still holds after the upload-path fit.
- `tests/unit/api/test_override_panel.py` — unchanged, still passes.
- `tests/unit/workflow/test_layer_generation.py` — docstring corrected
  (lookup key vs fingerprint bytes); still passes.

Focused run:
`pytest tests/unit/assets/test_substrate_crop.py
tests/unit/api/test_override_layer.py
tests/unit/api/test_override_panel.py
tests/unit/api/test_focal_override_api.py
tests/unit/workflow/test_layer_generation.py -q` → **47 passed**.
`tests/unit/renderer/test_fingerprint_parallax.py` → **23 passed**.
Full `pytest tests/unit -q`: **1715 passed, 6 failed** — same 6
pre-existing failures (5 in `test_sfx_overlays_diegetic.py`, 1 in
`test_director_planner.py`). Pass count is above the P0 log's 1238
baseline because the suite has grown since; no new failures from this
slice.

**Corrections to the brief.** None material — the P1 CORRECTION (do not
bare-`center_crop` uploads) was already in the plan and is what shipped.
`apply_override_to_binding` gained an explicit reject for non-panel
values rather than only being avoided by the layer branch.

**Found-not-fixed leftovers** (explicitly out of this slice): P2 key
guard at upload; P3b parallax gate UI; P4 lock layers;
`_unfilled_shot_ids` still ignores `secondary_state` and layers;
`GET /clip` still has no `panel`; video thumbnail cache still keyed on
shot alone. This slice does **not** add gate UI (P3b).

**Re-verification.** Real-mode `layer_prompt_hash` still project-scopes
via `_layer_seed(_project_seed(str(project_uuid)), layer_index)` —
§2 holds. No server started, no fal.ai / ElevenLabs / paid provider
called, no `make test` / seed `--force`, Postgres unused (fakes only).

**Orchestrator review (grok-4.6, 2026-09-12).** Implemented by a
`grok-4.5` subagent (`01a09524-a8c3-76c1-867e-d4b7796d63f7`). Brief
held: parser is index-form, layers write `GeneratedClip` not binding,
fit uses `resolve_generation_request_format` (R1), replace-in-place
because `prompt_hash` is unique, fingerprint hashes file bytes so an
overwrite misses the whole-timeline cache, GET `panel=layer:N` is in
so P3b is not blocked on a second backend slice.

One correction after review: `fit_upload_to_canvas` used
`max(cover, ceil(dim * scale))` independently per axis, which can
stretch a near-cover float undershoot. Replaced with a uniform extra
scale; added `test_fit_does_not_stretch_one_axis_to_cover` and
`test_layer_panel_does_not_fall_through_to_primary`. Focused re-run
after that: **72 passed** (the implementer's 70 plus those two).

The §4.1 fingerprint test in `test_override_layer.py` pins
`_file_sha256` itself rather than `resolve_render_inputs`; the wiring
is the comment + assignment at `render.py` ~379-383. Acceptable for
this slice; a payload-level test of `resolve_render_inputs` would be
stronger if this plan grows a follow-up.

P3b is the next UI slice. P2 (key at upload) and P4 (lock layers)
remain backend.

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

### P0 — built 2026-09-08

**Backend.** `styled_prompt` (`app/workflow/steps/resolve_assets.py`) is
the RENAMED `_styled_prompt` — the export needed the exact function
`generate_image_real` feeds `_generate_image_once` as `base_prompt`
(sent on unmodified from there, per the brief's own verified facts), and
no other production module had ever imported a private, underscore-led
name across a module boundary before this one would have been the
first. Exposing it properly (matching `layer_styled_prompt`'s own
precedent — already public for the identical "render.py needs this too"
reason) keeps that convention intact instead of breaking it once. Every
internal call site (`generate_image_real`, `layer_styled_prompt`,
`submit_video_generation`, and the unwired dead `_generate_image_real_old`
at line ~2012) was renamed along with the definition; nothing about
generation behaviour changed.

New module `app/assets/prompt_export.py`:
`PromptExportEntry`/`build_prompt_export_entries`/
`render_prompt_export_text`. `build_prompt_export_entries` walks
`timeline.scenes` then `scene.shots` (scene-then-shot order) and, per
shot, calls `styled_prompt` for the primary and `layer_styled_prompt`
for each of `shot.layers` in index order — the SAME `RenderFormat`
(resolved once per project, matching `generate_image_real`'s own single
resolve-per-call) feeds every one of those calls, so every entry's
`.prompt` is provably the same string a real generation call would send
(proven directly in tests, not asserted from reading the code).

A `camera.movement == PARALLAX` shot's primary is flagged
(`is_parallax_fallback=True`), never skipped or reordered — it IS still
generated by the real pipeline (`ResolveAssetsStep.run`'s `needs_layers`
gate only ever ADDS layer generation, verified again by re-reading it
this session; the brief's claim held), but `render.py`'s own lookup
only reaches for it when a plane fails to resolve. The flag is keyed on
`camera.movement` alone, not on whether `shot.layers` is actually the
well-formed two-entry background/subject shape
`should_composite_parallax` requires — a `PARALLAX` shot with fewer
layers is already a documented, if currently unproduced, legal state
(`CameraMovement.PARALLAX`'s own docstring), and re-deriving that whole
precondition here would also need resolved clip paths that do not exist
yet at export time, before anything has been generated.

`GET /projects/{id}/prompts/export` (`app/api/projects.py`, placed next
to `GET /timeline`) loads the active timeline, calls the two functions
above, and returns plain text with `Content-Disposition: attachment;
filename="{project_id}-prompts.txt"`. Plain text, not JSON — the
destination is a paste box in someone else's chat UI. No new DB reads
beyond the project/timeline lookup every other endpoint here already
does; nothing about generation state (bindings, clips) is consulted,
since this reports what WOULD be sent, independent of what already has
been.

**The header — §7's least obvious requirement.** States the target
pixel size from `resolve_generation_request_format` (never a hardcoded
number — verified this reads `778x1383` for `illustrated_risograph`'s
720×1280 canvas at the default 8% oversize, matching the brief's own
example exactly) AND, in words, tells the human to also set the
provider's own aspect-ratio/orientation control — stating both because
Grok/Qwen guessed wrong from pixels-as-a-parameter alone and Qwen kept
guessing wrong from words alone too (§7.1). The per-entry orientation
sentence ("Vertical portrait image, 9:16 aspect ratio...") is repeated
on EVERY entry rather than stated once at the top of the file, because
the user's actual gesture is "copy one prompt block, paste it" (the
same one-at-a-time habit this export exists to speed past) — a reminder
that only lives in an easily-dropped header would silently stop
applying the moment someone copies a single block instead of the whole
file. Neither the header nor the orientation sentence ever touches
`entry.prompt` itself — they are separate lines the prompt string is
joined with, never concatenated into it — so the identity property
holds all the way out to the rendered text, not just at the dataclass
layer.

**Frontend (`AssetReviewGate.tsx`, read fresh per the brief since P3a
just touched it).** `lib/api.ts` gains `promptExportUrl` (a raw URL for
an `<a download>`) and `fetchPromptExportText` (a manual `fetch` +
`res.text()` — the existing generic `request<T>()` always calls
`res.json()` and would break on a `text/plain` body). New
`ExportPromptsButton` component, mounted in the sticky header next to
the Approve button (wrapped in a shared flex container so the header's
existing two-item `justify-between` layout is preserved), offering two
actions: **"Copy all prompts"** (fetches the text, then
`navigator.clipboard.writeText`, matching the existing `CopyButton`
idiom's copied/check-icon feedback) and **"Download .txt"** (a plain
`<a href=... download>` — no JS, relies on the backend's own
`Content-Disposition`). Both, not one, because they serve different
gestures: copy is the one-click "paste everywhere" case; download is
for actually working through 60+ prompts in an editor rather than
holding them all in one clipboard entry at once. Shown even in the
backstop (`isBackstop`) view, unlike the Approve button — grabbing
prompts is useful while fixing a failed shot too, not only pre-approval.

**Tests.** `tests/unit/assets/test_prompt_export.py` (8 tests): scene-
then-shot ordering; a plain shot exports 1 entry, a parallax shot
exports 3 (`primary`, `layer_0`/background, `layer_1`/subject); only a
parallax shot's primary is ever flagged as the fallback; the header
names the request-format size (asserted by calling
`resolve_generation_request_format` directly, never a hardcoded
`778x1383`, and asserting it differs from the canvas size — a test that
only checked the canvas would pass even if the header regressed to
naming the wrong one); the header also mentions the provider's own
aspect control; every entry carries its own orientation sentence; a
landscape opt-in style gets the landscape sentence, never the portrait
one. **The identity test**
(`test_prompts_are_byte_identical_to_the_real_generation_path`) runs
against `illustrated_risograph` with a real multi-word `visual_style`
(exercising the truncation logic `styled_prompt`'s own docstring
documents) and asserts every entry's `.prompt` equals a DIRECT call to
`styled_prompt`/`layer_styled_prompt` with the same shot/layer/
creative_context/frame — never a hardcoded expected string.
`tests/unit/api/test_export_prompts_api.py` (3 tests) covers the route's
own plumbing only (404s, headers, that it really calls through rather
than stubbing) via the same FastAPI-router-plus-fakes idiom
`test_focal_override_api.py` already uses.

**Test results.** `pytest tests/unit`: 1238 passed, 6 failed — same 6
pre-existing failures named in §0/P3a's log (5 in
`test_sfx_overlays_diegetic.py`, 1 in `test_director_planner.py`); the
+11 are this slice's own tests (8 + 3), exactly accounting for the rise
from P3a's own 1227. `npx tsc --noEmit` in `frontend/`: clean. `npx
oxlint` on the touched files: clean. No server started, no paid
provider called, Postgres untouched by anything this slice's own tests
do (fakes only, no `PYTEST_TRUNCATE_DB`) — but see below, Postgres WAS
touched separately as standing cleanup.

**Standing cleanup performed this session.** 66 leaked `*-test`-named
projects (accumulated from earlier ad-hoc test runs, unrelated to this
slice's own tests) were found in the shared dev Postgres and deleted one
at a time via the real `delete_project` (which already contains the
cross-project generated-clip/narration cache guard — no separate
set-op was needed for a one-at-a-time delete, only for a hypothetical
bulk endpoint). 0 failures; 31 human-named projects survive untouched,
including `a9dde33c` / "The City Rats" — the exact project this plan's
own §1/§7 measurements were taken against.

**Corrections to the brief.** None found — every fact cited in the
brief (`_styled_prompt`'s exact location and signature, `frame` vs
request-format distinction, `layer_styled_prompt`'s wrapping mechanism,
the dead code at line ~2012 and its missing `frame` argument, the
`needs_layers` gate never suppressing primary generation for a
`PARALLAX` shot, the 778×1383 example) was re-verified against the
current code and held exactly as stated.

**Scope note, not in the brief's own "Done when" but worth recording:**
this export deliberately does NOT include a `split_frame` shot's
`secondary_prompt`. The brief's own "WHAT TO BUILD" §1 enumerates only
"the primary, or layer 0/1" — never a panel — and its "Done when"
count (61 prompts on the measured 41-shot project) is exactly
41 primaries + 20 layer prompts, with no split-screen shots in that
project to account for. A split-screen shot's own prompts are already
visible and individually copyable at the gate today (P3a's
`SecondaryPanelBlock`), so nothing about them is newly invisible the
way the layer prompts were — folding them into this bulk export too
would be a small, low-risk addition if wanted, but is out of this
slice's literal scope as written.
