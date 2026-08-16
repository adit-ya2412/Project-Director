# Frontend — parked 2026-08-16, mid-build

**Status: the seven screens are built; the app does not compile, and it has never
once talked to the running backend.** Read this before touching anything — the
backend contract changed underneath this code while it was parked, so some of it
is wrong in ways `tsc` will not tell you about.

Committed deliberately in this state, at the user's request, to be picked up
later. Nothing here is abandoned or throwaway.

## Stack

React 19 · Vite 8 · TypeScript 6 · Tailwind 4 · TanStack Query · Radix
primitives · React Router 7. Dark theme. `npm install` has already been run;
`node_modules` is present and complete.

    npm run dev        # vite dev server, expects the API on localhost:8000
    npm run build      # tsc -b && vite build   <-- currently FAILS, see below
    npm run lint       # oxlint

## What exists

All seven screens from the F1–F7 design in
[`docs/13_Implementation_Guide.md`](../docs/13_Implementation_Guide.md), wired as
real routes in `src/App.tsx`:

| Route | Page | Design |
|---|---|---|
| `/` | `ProjectList` | F1 — list + thumbnails, failures included |
| `/new` | `NewProject` | F2 — script, images, mandatory 10–15 word descriptions |
| `/projects/:id` | `ProjectEntry` | routes to the right screen for current status |
| `/projects/:id/progress` | `Progress` | F3 — step-by-step, shot-level detail |
| `/projects/:id/review` | `Gate1AssetReview` | F4 — planner picks + misses, override |
| `/projects/:id/generated-review` | `Gate2GeneratedReview` | F5 — generated images, editable prompts |
| `/projects/:id/result` | `Result` | F6/F7 — video, voice/music retry, warnings |

~2,400 lines. No stubs, no TODO markers, no placeholder screens — every page is a
real implementation. The `src/lib/` layer (`api.ts`, `queries.ts`, `types.ts`,
`steps.ts`, `resolution.ts`, `errors.ts`) is the whole backend surface in one
place; start there.

## Pick-up list, in the order it should be done

### 1. Make it compile (two errors, both small)

- `tsconfig.app.json:20` — `baseUrl` is deprecated under TypeScript 6 and is now
  a **hard error**, so `tsc -b` fails before it compiles a single file. Either
  add `"ignoreDeprecations": "6.0"` or migrate the path alias to `paths` without
  `baseUrl`.
- `src/pages/Progress.tsx:89` — `PRE_APPROVAL_STEPS.includes(progress.current_step)`
  passes a `string` where the `StepName` union is required.

With the first silenced, the second is the **only** type error in all 53 files.

### 2. The 202 contract — the part that is silently wrong

This code was written *before* F0a landed and against the old synchronous
contract. `src/lib/api.ts:107` carries the author's own note that this was
coming. It has now arrived, and these five functions are typed `Promise<Project>`
while the backend returns `WorkflowTriggerResult`
(`{project_id, workflow_run_id, state, joined_existing_run}`) with **HTTP 202**:

- `renderProject` → `POST /render`
- `approveTimeline` → `POST /timeline/approve`
- `overrideShot` → `POST /shots/{id}/override`
- `retryMusic` → `POST /music/retry`
- `retryNarration` → `POST /narration/retry`

Retype all five and recheck every call site. This is not cosmetic: these calls
used to return the settled project, and now they return *before the work starts*.
Any screen that reads the response to decide what to show next is now reading a
run id and will show the wrong thing. The correct pattern everywhere is: fire the
trigger, then poll `GET /progress`.

`POST /render/only` (R3 — re-render without touching a paid step) is **absent
from the client entirely** and needs adding; it is the endpoint the Result screen
should use for a free re-render.

### 3. `regenerateShot` has no backend — this is the real gap

`src/lib/api.ts:165` posts to `POST /projects/{id}/shots/{shot_id}/regenerate`.
**That endpoint does not exist.** The author flagged the guess honestly in the
docstring rather than hiding it; it was correct to keep building, and the guessed
shape mirrors the sibling `/override` route, so the frontend needs no change if
the backend adds exactly that.

But it means **F5c — editing a prompt and regenerating the image, which is the
entire reason Gate 2 exists** — is a backend feature that was designed and never
built. Gate 2 renders, and its regenerate button 404s. Budget backend work here,
not frontend work.

The two F0b media endpoints the same comment block flags as unbuilt
(`GET /shots/{id}/asset`, `GET /thumbnail`) **do now exist** — that guess landed
correctly and needs no change.

### 4. Serve it from FastAPI

Static-file serving for the built frontend is not wired. Touches both sides.

### 5. Then run it against a live project

None of the above is the expensive part. Nothing here has ever met a real API
response, so expect field-name and shape mismatches, null cases the types claim
are impossible, and polling that either hammers or stalls. The two approval gates
are the risk concentration — they are the most complex screens and the most
likely to need rework rather than patching. Verifying them end to end costs real
pipeline runs (10–15 min and real money each).

## Honest estimate

~1 hour for items 1, 2 and 4 — well-defined, no unknowns. Then 2–4 hours for
item 5, which is an estimate of defects nobody has seen yet and should be
distrusted accordingly; it firms up sharply about an hour into the first live
run, when it becomes clear whether this is wiring or rework. Item 3 is separate
backend work.

Call it one working session to operational, assuming the screens are right in
*design* and only wrong in *wiring*.
