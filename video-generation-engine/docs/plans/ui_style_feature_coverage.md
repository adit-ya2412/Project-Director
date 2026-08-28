# UI Plan — Style & Feature Coverage

**Status:** Implemented 2026-08-26 (frontend-only). See §7. Written 2026-08-26, following
`docs/plans/style_extensions.md`'s three backend features (word-highlight
captions, `archival_montage`, glitch transitions) landing with **zero**
frontend wiring, and a full frontend audit finding the gap is larger than
just those three — style selection, color grading, and SFX have no real
UI coverage even for what already shipped before this session.

---

## 0. Navigation

| # | Read | Why |
|---|---|---|
| 1 | `docs/plans/style_extensions.md` | The three backend features this plan needs to surface — what they are, why they exist, what's still an unmeasured "starting point" (archival_montage's pacing, v3's glitch intensity) versus fully settled (word-highlight captions, v1 glitch). |
| 2 | `frontend/src/pages/NewProject.tsx:30-49, 260-320` | The current style picker — exactly 3 hardcoded styles, no previews, the frame-aspect toggle pattern to extend. |
| 3 | `frontend/src/lib/resolution.ts:1-15` | The file's own header comment already flags itself as a manually-synced duplicate of backend config — read this before touching it, the hazard is self-documented. |
| 4 | `frontend/src/lib/types.ts:1-10` | Also self-documents its own risk: hand-derived from Pydantic models, never checked against a live OpenAPI schema. Assume drift, verify before trusting. |

**This document is UI-only.** No backend changes are in scope — every
feature named below already exists and works via the API (confirmed live
in `style_extensions.md`'s P-A/P-B/P-C log entries). The gap is entirely
that the frontend doesn't expose it.

---

## 1. Origin and scope

### 1.1 What prompted this

Three style/feature additions landed in the backend this session
(word-highlight captions, `archival_montage`, three glitch transitions),
none reachable from the UI. A full frontend audit (this document's own
research pass) found the gap predates this session: color grading
(`POST /grade`) and SFX control (`POST /sfx/{kind}/override`,
`POST /sfx/retry`) have **zero frontend UI despite full backend support**,
and even the original 3-style picker has no previews, no descriptions
beyond a one-line hint, and a hand-rolled button pattern copy-pasted
three times with no reusable component.

### 1.2 Current state — what exists today, exactly

Verified by reading the actual frontend code, not assumed:

| Area | Current state |
|---|---|
| Style picker (`NewProject.tsx:30-49`) | 3 of 4 styles listed (`documentary_archival`, `retention_fast`, `stillness` — **`archival_montage` absent**). Each is `{id, label, hint, targetShotDurationS}` — label + one-line hint only. **No preview image or video for any style.** |
| Frame-aspect toggle (`NewProject.tsx:282-320`) | Exists only for `stillness` (16:9 default / 9:16 opt-in). No equivalent for any other style, and none needed for the other three (each has a fixed native aspect). |
| Resolution/format logic (`resolution.ts:26-33`) | Hardcoded per-style width/height, **manually duplicated from backend `resolve_render_format`**, self-flagged as a sync hazard in the file's own header. `archival_montage` is not in this switch at all — would silently fall through to the `else` (1280×720 landscape) branch, which is **wrong** (`archival_montage` is 720×1280 per `style_extensions.md` §4.6). |
| Result page (`Result.tsx`) | Shows the video, download link, asset-source-mix, narration voice retry, and a full music card (retry + upload). **Does not show which style rendered**, no grade UI, no caption-highlight indicator, no transition info, **no SFX UI at all**. |
| Shot review (`AssetReviewGate.tsx`) | Per-shot prompt editing and image override exist. `Shot.camera` is read but only feeds a resolution-warning calculation — **never shown as text, never editable**. `Shot.transition_out` and `Shot.text_card` are **not read at all**. |
| Types (`types.ts`) | `Camera`/`CameraMovement` fully typed. **`Transition`/`TransitionType` and `Shot.text_card` do not exist as TypeScript types at all** — nothing today even parses them out of a `GET /timeline` response. |
| API coverage | 29 of 37 backend routes have a frontend caller. **No caller exists for**: `POST /grade`, `POST /sfx/{kind}/override`, `POST /sfx/retry`, `POST /shots/{id}/generate/video` (+ its poll `GET`), `POST /narration/retry-language`, `GET /status`, `GET /script`, `DELETE /projects/{id}`. |
| Reusable components | **None for option/card selection.** Style picker, frame-aspect picker, and language picker each hand-roll the identical button+`cn()` pattern independently in `NewProject.tsx` — three copies of one pattern, no shared component. |
| Preview assets | **None exist anywhere in the frontend** — no thumbnails, no preview images, no preview clips, for any style, in `frontend/public/` or `frontend/src/assets/`. |

### 1.3 In scope for this plan

1. Add `archival_montage` to the style picker (§3.1) — closes the most
   urgent gap, since the style is fully built and tested backend-side
   right now and simply cannot be chosen from the UI.
2. Fix `resolution.ts`'s missing `archival_montage` case (§3.1.1) — a
   **real bug**, not just a gap: today, selecting it via any future UI
   (or the API directly, if a frontend user ever inspects resolution
   client-side) would compute the wrong aspect ratio.
3. Surface which style/transition/caption treatment a render actually
   used, on the Result page (§3.2).
4. Add a color-grade UI (§3.3) — the backend endpoint has existed longer
   than this session's three features and still has no caller.
5. Add an SFX control UI (§3.4) — same story, zero coverage despite full
   backend support (override, disable, retry, all built).
6. Extend `types.ts` with `Transition`/`TransitionType`/`Shot.text_card`
   (§3.5) — prerequisite for §3.2/§3.6, not optional groundwork.
7. A reusable style/option-card component (§4) — needed the moment a 4th
   style is added to the existing 3-copy-pasted pattern; do it once,
   correctly, rather than adding a 4th copy.
8. Style preview assets (§5) — a content need, not just code; flagged
   explicitly because it's the one item here that isn't "write code
   against an existing endpoint."

### 1.4 Explicitly OUT of scope

- **Per-shot transition/camera editing UI** (letting a human override
  which transition or camera move a shot got). The backend has no
  "override transition" endpoint at all — that's new backend surface,
  not a UI gap. If wanted, scope it as a backend-first task referencing
  this document's §3.6 for what the frontend side would need.
- **Glitch-transition-specific UI** (e.g. a toggle for "allow glitch
  transitions"). These are chosen by the Shot Planner LLM per
  `style_extensions.md`'s prompt guidance (at most one per video, only
  for a corruption/failure beat) — there is no user-facing decision to
  expose beyond seeing which transition got used after the fact (§3.2).
- **Word-highlight caption UI** (e.g. a color picker). §3.6 of
  `style_extensions.md` decided this is a single fixed global constant,
  not configurable — nothing to build here unless that backend decision
  is revisited first.

---

## 2. Lessons carried forward

### 2.1 `resolution.ts` and `types.ts` are both self-admitted drift risks

Both files' own header comments say so. Any change here must update the
backend-mirroring logic in lockstep and note in the diff which backend
file/line it was checked against — the same "verify, don't assume"
discipline `style_extensions.md` held itself to throughout (e.g. its own
§4.6 format decision, §5.2's real-ffmpeg verification of xfade names).
**Before writing `archival_montage`'s resolution entry, re-read
`backend/app/script/styles.py`'s live `STYLE_PACING_BANDS["archival_montage"]`
values, don't copy from this document's memory of them** — they're
explicitly flagged as post-launch-tunable starting points and may have
moved.

### 2.2 No reusable selector component exists — don't add a 4th copy

`NewProject.tsx` already hand-rolls the same button pattern three times
(style, frame-aspect, language). Adding `archival_montage` as a 4th
hardcoded button before building the shared component (§4) means a 5th
near-identical copy the next time a style or option list grows. Build
§4 first, or at minimum in the same pass as §3.1.

### 2.3 Type drift is real, not hypothetical — this session found one

The frontend `CameraMovement` type (`types.ts:128-129`) is
`"static" | "slow_zoom" | "slow_push" | "pull_back" | "pan" | "split_frame"`
— **missing `punch_in`**, a real, shipped backend enum value
(`app/schemas/timeline.py`, used extensively by `retention_fast`'s own
prompt fragment). This was found during this plan's own research pass,
not assumed. **Before adding `TransitionType` to `types.ts` (§3.5), spot-
check `CameraMovement` too and fix `punch_in`'s omission in the same
pass** — it's a pre-existing bug this document's research surfaced,
not new scope, but it sits right next to the work §3.5 is already doing
and costs one line to fix alongside it.

### 2.4 The frontend has no visible test suite convention documented here

This plan's own research did not establish what frontend testing looks
like in this repo (unit tests? Playwright? none?). **Before writing any
frontend code from this plan, check `frontend/package.json`'s scripts and
`frontend/src/**/*.test.*`/`*.spec.*` for the actual convention** — do not
assume Jest, Vitest, or Playwright without checking, and do not skip
tests on the assumption none exist without verifying first.

---

## 3. Feature-by-feature UI requirements

### 3.1 Add `archival_montage` to the style picker

**Files touched:**
- `frontend/src/pages/NewProject.tsx:30-49` — add a 4th `STYLES` entry.
  Needs a real label/hint pair; suggest mirroring the backend's own
  framing ("harder cutting, more text cards, 9:16" per
  `style_extensions.md` §4.1) rather than inventing new copy. Needs a
  `targetShotDurationS` — backend's `archival_montage` band is `2.25`
  (verify live per §2.1, don't trust this document).
- `frontend/src/pages/NewProject.tsx:260-281` — the render grid is
  `sm:grid-cols-3`; a 4th entry needs this bumped (`sm:grid-cols-4` or a
  wrap-aware layout) — check it doesn't break at narrow widths before
  shipping.

#### 3.1.1 Fix `resolution.ts`'s missing case — a real bug, not a gap

`canvasForStyle` (`resolution.ts:26-33`) has no `archival_montage` branch
— it would silently fall through to the `else` (1280×720 landscape)
default, which is **wrong**: `archival_montage` is 720×1280 per
`style_extensions.md` §4.6 (re-verify against live backend config per
§2.1). This must be fixed in the SAME change as §3.1 — shipping the style
picker without this fix means selecting `archival_montage` computes the
wrong Ken Burns/resolution-warning math client-side, even though the
actual render (server-side) would still come out correct. Silent client-
only wrongness, exactly the class of bug `resolution.ts`'s own header
comment warns about.

**Test:** whatever frontend test convention exists (§2.4), add a case for
`canvasForStyle("archival_montage", null)` alongside the existing
`retention_fast`/`stillness` cases, asserting `{width: 720, height: 1280}`.

### 3.2 Surface style/transition/caption info on the Result page

**Goal:** a human reviewing the finished render should be able to see
what style/transition/caption treatment actually shaped it, without
reading the API response by hand.

**Minimum viable version:**
- Show `project.render_style` (already fetched, just not displayed) as a
  label near the video player in `Result.tsx`.
- If any shot in the active timeline used a glitch transition
  (`shot.transition_out.type` in the three glitch values), show a small
  badge/note — "This video includes a glitch transition" — since it's a
  rare, deliberate, at-most-once-per-video effect per the Shot Planner's
  own restraint guidance, worth confirming it fired rather than
  discovering it only by watching.

**Prerequisite:** `Transition`/`TransitionType` must exist in `types.ts`
first (§3.5) — there is currently no way to read `transition_out` off a
fetched `Timeline` at all.

**Files touched:** `frontend/src/pages/Result.tsx`, `frontend/src/lib/types.ts`.

### 3.3 Color-grade UI (`POST /grade`)

**Goal:** the backend endpoint (`api/projects.py:624`, `SetGradeRequest`)
lets a human override the render grade independently of `render_style`
(per `style_extensions.md`'s own citation of this as a *separate,
mutable* field from `render_style` — "Grade (`grade_style`) is a
separate, mutable field... works at any time, including after render").
This has never had a frontend caller.

**Files touched:**
- `frontend/src/lib/api.ts` — new `setGrade(id, gradeStyle)` function,
  same shape as `setRenderStyle`.
- `frontend/src/lib/queries.ts` — `useSetGrade` mutation.
- `frontend/src/pages/Result.tsx` — a new card, likely near the
  "Re-render" card (389-404) since changing grade is cheap (no
  re-encode cost beyond the one shared filter pass, per
  `app/renderer/grading.py`'s own docstring) and pairs naturally with
  "Re-render" as the action that actually applies it.

**Open question, flag to the user before building:** should grade be
restricted to the same 4 style-named grades (`documentary_archival`,
`retention_fast`, `stillness`, `archival_montage`), or does the backend
endpoint accept an independent value? Check `SetGradeRequest`'s actual
validation in `api/projects.py` before designing the picker — don't
assume it mirrors the style list.

**ANSWERED 2026-08-26 (live read of `SetGradeRequest` + `set_grade` in
`api/projects.py:299-303, 624-660`):** restricted to the four
`STYLE_PACING_BANDS` keys. A non-`None` unknown string is a 400.
`grade_style=None` is the explicit reset ("use `render_style`'s own
grade"). The picker shipped as those four plus a "Match this project's
style" card that posts `null`.

### 3.4 SFX control UI (`POST /sfx/{kind}/override`, `POST /sfx/retry`)

**Goal:** parity with the existing music card (`Result.tsx:330-386`,
which already has retry + upload). SFX has the identical backend shape
(override with an uploaded file, or `enabled=false` to disable a kind,
per `analysis.md`'s C3f) but zero frontend surface.

**Design note — `retention_fast` has whoosh off by design.** Per
`analysis.md`'s decision 5/5a, don't build this as if every project has
three live SFX kinds — `retention_fast` only ever has stinger/transition
audible (whoosh is gated off entirely for that style). The UI should
reflect *actual* `sfx_plan.clips` for the active project, not assume all
three kinds are always present.

**Files touched:**
- `frontend/src/lib/api.ts` — `overrideSfx(id, kind, file?, enabled?)`,
  `retrySfx(id)`.
- `frontend/src/lib/queries.ts` — corresponding mutations.
- `frontend/src/pages/Result.tsx` — a new card, mirroring the music
  card's shape (attribution display + upload + disable toggle per kind
  present in `sfx_plan.clips`).

### 3.5 Extend `types.ts`

**Prerequisite for §3.2, §3.6.** Add, cross-checked against
`backend/app/schemas/timeline.py` at the time of writing (not copied from
this document, per §2.1's discipline):

- `TransitionType` union type — `"cut" | "dissolve" | "fade" | "wipeleft" | "fadeblack" | "glitch_shift" | "glitch_tear" | "glitch_jitter"`.
- `Transition` interface — `{ type: TransitionType; duration_s: number }`.
- `Shot.transition_out: Transition`.
- `Shot.text_card: string | null`.
- **Fix `CameraMovement`'s missing `punch_in`** (§2.3) in the same pass.

**Test:** if the frontend has a type-check step in CI (verify per §2.4),
confirm it passes; there's no runtime behavior to unit-test for a pure
type addition, but any code in §3.2/§3.6 that reads these fields should
have a test exercising a fixture `Timeline` with each new field
populated.

### 3.6 Shot review: show camera/transition/text_card (read-only first)

**Goal:** `AssetReviewGate.tsx` currently reads `Shot.camera` only for a
silent resolution-math side calculation — a human reviewing shots has no
way to see what camera move, transition, or text card a shot actually
has. This is read-only display scope; editing is explicitly out of scope
(§1.4) since no backend override endpoint exists for these fields.

**Files touched:** `frontend/src/pages/AssetReviewGate.tsx` — likely in
`ShotCard` (381-453), alongside the existing `shot.intent` display
(430), add camera movement and (if non-empty) text card text. Keep it
minimal — a small caption line, not a redesign of the card.

### 3.7 Video-generation endpoint UI (`POST /shots/{id}/generate/video` + poll)

**Lower priority, noted for completeness.** Backend supports on-demand
per-shot video generation with no frontend caller at all. Not required
for this plan's core scope (style/feature coverage) — flagged here so
it isn't silently forgotten, but sequencing (§6) puts it last.

---

## 4. Reusable component: extract the option-card pattern

**Before or alongside §3.1** (§2.2's own warning). `NewProject.tsx`
duplicates this exact pattern three times today (style/frame-aspect/
language pickers):

```
<button type="button" className={cn(
  'rounded-md border px-3 py-2.5 text-left transition-colors',
  selected ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/40 hover:bg-accent/40'
)} aria-pressed={selected}>
```

**Proposed component**: `frontend/src/components/OptionCard.tsx` (or
fold into `frontend/src/components/ui/` alongside the existing shadcn-
style primitives, matching that directory's naming convention — check
which fits before creating a new top-level component file). Props:
`{ selected: boolean; onSelect: () => void; label: string; hint?: string; preview?: ReactNode; disabled?: boolean }`.
The `preview` slot is what makes §5's preview assets actually usable —
build it into the component from the start rather than bolting it on
when previews arrive.

**Migration**: replace all three existing hand-rolled instances in
`NewProject.tsx` with the new component in the same change that adds
`archival_montage` — don't leave the old 3 inline and add a 4th via the
new component, that's worse than either extreme (two patterns instead
of one).

---

## 5. Style preview assets

**Content work, not just code** — flagged separately because it can't be
done by reading the backend, unlike everything else in this plan.

**What's needed:** one representative preview (short clip or still) per
style, for the option-card `preview` slot (§4). Given none of the 4
styles currently has a bundled preview anywhere in the frontend, this is
new content to produce, not a wiring task.

**Suggested source:** this session's own real renders are a starting
point — `_spike_glitch/` (gitignored, not in the repo, but locally
present) has real archival-photo renders demonstrating `archival_montage`'s
grade and the camera-vocabulary mix; `058b0e05`/`3d56cf87` are real
completed projects with real rendered output for `retention_fast`. None
of these are production-quality "marketing preview" assets, but they're
a starting point for what a real preview should look like, rather than
inventing the visual language from scratch.

**Open question — hand to the user, don't decide unilaterally:** static
thumbnail vs. short looping preview clip (autoplay-muted `<video>`) per
style card. A clip communicates pacing (the whole point of `retention_fast`
vs `stillness`) far better than a still, but is real production/encoding
work (needs a real render, not just a screenshot) and a real asset-
hosting decision (bundled in `frontend/public/`? served from backend
storage? CDN?) that this plan shouldn't presume.

**ANSWERED 2026-08-26, provisionally:** static thumbnails, bundled in
`frontend/public/style-previews/`, sourced from this session's grade
probe stills. Looping clips deferred — they are the right long-term
answer for pacing but this pass should not invent an asset-hosting
pipeline. Replace the shared-car stills with real style-specific clips
when those exist. See §7 P-UI.

---

## 6. Sequencing recommendation

1. **§3.5 (types)** first — everything else reads through these types.
2. **§4 (component) + §3.1 (archival_montage in picker, incl. the
   resolution.ts bug fix)** together — do the component extraction in
   the same pass that adds the 4th style, per §2.2.
3. **§3.2 (Result page style/transition surfacing)** — now unblocked by
   §3.5.
4. **§3.6 (shot review read-only display)** — same prerequisite, same
   low cost, do alongside §3.2.
5. **§3.3 (grade UI) and §3.4 (SFX UI)** — independent of everything
   above, can run in parallel with 2-4 or after; sequenced last only
   because they're each a full new card with their own API/mutation
   work, not because they're less valuable — if anything, SFX has been
   a gap longer than any feature this session added.
6. **§5 (preview assets)** and **§3.7 (video-gen UI)** — lowest priority,
   explicitly content-production or nice-to-have work respectively.

---

## 7. Implementation log

### P-UI — Full frontend wiring (2026-08-26)

**Scope executed:** every in-scope item in §1.3, in §6's order, plus the
two lowest-priority items (§5 preview stills, §3.7 per-shot video gen)
because this pass was asked to implement the plan in full. No backend
changes. Out-of-scope items in §1.4 (per-shot transition/camera editing,
glitch-transition toggle, caption colour picker) were not built.

**§2.1 live re-read before writing numbers** (not copied from this
document's memory):

- `backend/app/script/styles.py` `STYLE_PACING_BANDS["archival_montage"]`
  (lines 160–191): `target_shot_duration_s=2.25`, `render_width=720`,
  `render_height=1280`. Still a reasoned starting point, unchanged since
  this document was written.
- `backend/app/schemas/timeline.py` `CameraMovement` (lines 68–82)
  includes `punch_in`; `TransitionType` (lines 93–124) is the eight-value
  union this document listed; `Shot.transition_out` / `Shot.text_card`
  (lines 208, 250) match.
- `backend/app/api/projects.py` `SetGradeRequest` (lines 299–303) +
  `set_grade` (lines 624–660): `grade_style` is `str | None`, and a
  non-`None` value **must** be a key of `STYLE_PACING_BANDS`. That
  answers §3.3's open question: the picker is the four style-named
  grades plus an explicit "Match this project's style" (`null`) reset.
  Independent values are rejected 400.
- `SfxKind` is `whoosh | stinger | transition`
  (`backend/app/schemas/timeline.py:397-403`). Override is Form
  `file` XOR `enabled=false` (`projects.py:2151-2214`).

**§2.4 frontend test convention:** `frontend/package.json` scripts are
`dev` / `build` / `lint` / `preview` only. Zero `*.test.*` / `*.spec.*`
files under `frontend/`. CI type-check is `tsc -b` (via `npm run build`).
No Jest/Vitest/Playwright test runner is wired in the frontend package.
A one-off Playwright script was added at `scripts/verify_style_ui.py`
(same shape as the existing `scripts/verify_review_ui.py`) rather than
inventing a frontend unit-test stack.

**Changes:**

1. **§3.5 types** — `frontend/src/lib/types.ts`
   - `CameraMovement` gained `punch_in` (§2.3, cross-checked against
     `timeline.py:82`).
   - `TransitionType` / `Transition` / `GLITCH_TRANSITIONS` /
     `Shot.transition_out` / `Shot.text_card` added.
   - `SfxKind` / `SfxClipSelection` / `SfxPlan` / `Timeline.sfx_plan`.
   - `TimelineMetadata.render_style` / `grade_style` (the latter is
     `timeline.py:348`, the field `POST /grade` actually writes).
   - `GenerateShotVideoResult` for §3.7.

2. **§4 OptionCard + §3.1 picker + §3.1.1 resolution bug**
   - `frontend/src/components/OptionCard.tsx` (new) — the shared
     button+`cn()` pattern, with a `preview` slot.
   - `frontend/src/lib/styles.ts` (new) — single catalogue of the four
     styles (`targetShotDurationS` 2.25 for `archival_montage` from the
     live band above), plus camera/transition/SFX labels.
   - `frontend/src/pages/NewProject.tsx` — all three hand-rolled
     pickers (style, frame-aspect, language) now use `OptionCard`. Style
     grid is `sm:grid-cols-2 lg:grid-cols-4` so a 4th card doesn't
     crush at narrow widths. `archival_montage` is a 4th `RENDER_STYLES`
     entry.
   - `frontend/src/lib/resolution.ts` `canvasForStyle` now branches
     `retention_fast || archival_montage` → `{width:720,height:1280}`.
     Adjacent: `effectiveKenBurnsZoom` now handles `punch_in` with
     `_MAX_PUNCH_ZOOM_DELTA = 0.9` from `ken_burns.py:145` (same class
     of silent client-only wrongness, sitting next to the §2.3 enum
     fix).

3. **§3.2 Result surfacing + §3.3 grade + §3.4 SFX** —
   `frontend/src/pages/Result.tsx`, `frontend/src/lib/api.ts`,
   `frontend/src/lib/queries.ts`
   - Style label + optional "Grade: …" badge (only when
     `grade_style` differs from `render_style`) + "Includes a glitch
     transition" badge + a one-line caption-treatment note (word-
     highlight is a global constant per `captions.py:430-433` / this
     document's §1.4 — displayed, not configurable).
   - Grade card next to Re-render: four style-named grades + "Match
     this project's style" (`null`). `setGrade` is **not** a workflow
     trigger — it records the override; Re-render bakes it in.
   - SFX card mirrors the music card. Rendered from actual
     `sfx_plan.clips` (so `retention_fast` never shows whoosh). Per-kind
     replace-upload and disable; Retry SFX selection is the undo.
     Override/retry are 202 triggers and hop to `/progress?pending=sfx`.

4. **§3.6 shot review** — `frontend/src/pages/AssetReviewGate.tsx`
   `ShotCard`: one caption line of camera movement, `transition_out`
   (as `out: …`), and text card when non-empty. Read-only.

5. **§3.7 video gen** — same file + `api.generateShotVideo` /
   `pollShotVideo` / `useGenerateShotVideo`. Confirm dialog (paid,
   minutes, needs a still, not available under DRY_RUN). Polls GET
   every 2.5s while `status === "pending"`.

6. **§5 preview assets** — `frontend/public/style-previews/{documentary_archival,retention_fast,archival_montage,stillness}.png`.
   Static stills from `_spike_glitch/style_previews/gradecolor_*.png`
   (this session's grade probe of a colour source, so the look
   difference is actually visible). `stillness.png` was generated with
   ffmpeg `eq=contrast=0.95:saturation=0.75:brightness=-0.02` matching
   `STYLE_GRADES["stillness"]` (`grading.py:60`). **Decision on the
   open question:** static thumbnails as a starting point; looping
   preview clips deferred (they communicate pacing better but need a
   real render + an asset-hosting decision this pass should not
   presume). These are not marketing-quality.

**Verification performed:**

- `frontend/`: `npx tsc -b` (via `npm run build`) → **pass**.
  `npm run lint` (oxlint) → **0 errors** (3 pre-existing
  `only-export-components` warnings in shadcn primitives, untouched).
- Playwright (`scripts/verify_style_ui.py` against Vite at
  `:5173`, 1280×900 and 390×844): **13/13 checks passed**.
  `archival_montage` present and selectable; frame-aspect stays hidden
  for it and appears for stillness; all three OptionCard pickers
  work; four preview `<img>`s render; card remains visible at mobile
  width. Screenshots in `tmp/style-ui-verify/`.
- **Live read-only pass 2026-08-26 (Postgres up, local uvicorn, no
  pytest, no `PYTEST_TRUNCATE_DB`):** `SELECT` showed all 13 live
  projects still present. Result
  (`058b0e05` Automatic transmissions) shows the Fast-cut reel badge,
  word-highlight caption note, SFX card (whoosh/stinger/transition
  from this project's actual `sfx_plan.clips` — older
  `retention_fast` rows still have whoosh), and the grade picker
  with "Match this project's style" selected. Apply grade / Retry
  SFX / Re-render were **not** clicked. Review (`3d56cf87`, grouped
  46-shot layout) shows `punch in · out: cut` and a Generate video
  button once a scene is expanded; Generate video / Approve were
  **not** clicked. Count after the pass still 13.

**Effects / reviewer notes:**

- A 4th style is now choosable. Selecting it no longer computes the
  wrong 16:9 canvas client-side.
- Grade is independently mutable from the Result page without
  re-planning, matching `set_grade`'s own docstring.
- SFX UI will correctly hide whoosh on `retention_fast` because it
  reads `sfx_plan.clips`, not a hard-coded 3-kind list.
- Preview stills currently share one car photo at four grades — they
  show the grade look, not pacing. Replace with real style-specific
  clips when those exist.
- Word-highlight caption colour remains a backend constant. The Result
  page only *names* the treatment.
