# Implementation Guide

**Project:** Video Generation Engine
**Version:** 1.0
**Status:** Living document — this one is *not* frozen. Update it as decisions change.
**Audience:** Any human or AI agent picking up development at any point.

---

> **Read this first.** Documents `00`–`12` describe *what* the system is. This document describes *how to build it*, *in what order*, and *what will go wrong*. It is the entry point. If you read nothing else, read [Section 1](#1-orientation-10-minutes) and the phase you are working on.

---

# Table of Contents

1. [Orientation (10 minutes)](#1-orientation-10-minutes)
2. [The Seven Invariants](#2-the-seven-invariants)
3. [Canon — resolving contradictions in the frozen docs](#3-canon--resolving-contradictions-in-the-frozen-docs)
4. [Build Strategy and why it is shaped this way](#4-build-strategy-and-why-it-is-shaped-this-way)
5. [Repository layout and module ownership](#5-repository-layout-and-module-ownership)
6. [The four core contracts](#6-the-four-core-contracts)
7. [Phase M0 — Walking Skeleton](#phase-m0--walking-skeleton)
8. [Phase M1 — Foundation](#phase-m1--foundation)
9. [Phase M2 — Persistence and Domain](#phase-m2--persistence-and-domain)
10. [Phase M3 — Timeline Service](#phase-m3--timeline-service)
11. [Phase M4 — Workflow Engine](#phase-m4--workflow-engine)
12. [Phase M5 — AI Planners](#phase-m5--ai-planners)
13. [Phase M6 — Asset Pipeline](#phase-m6--asset-pipeline)
14. [Phase M6.5 — Asset Quality and Supervision](#phase-m65--asset-quality-and-supervision)
15. [Phase M7 — Media Generation](#phase-m7--media-generation)
15. [Phase M8 — Renderer](#phase-m8--renderer)
16. [Phase M9 — API and Frontend](#phase-m9--api-and-frontend)
17. [Phase M10 — Hardening](#phase-m10--hardening)
18. [Cross-cutting concerns](#18-cross-cutting-concerns)
19. [Conventions](#19-conventions)
20. [Anti-patterns — stop if you are about to do this](#20-anti-patterns--stop-if-you-are-about-to-do-this)
21. [Decisions — closed](#21-decisions--closed)
22. [Working agreement for AI agents](#22-working-agreement-for-ai-agents)
23. [Quick reference](#23-quick-reference)

---

# 1. Orientation (10 minutes)

## What this system does

A user pastes a script. The system plans a video the way a film crew would — narrative structure, scenes, shots, camera moves, asset strategy — pauses for human approval, then sources or generates the media and renders a finished MP4.

## The one sentence that explains the architecture

> **AI produces a plan. The plan is a document. Deterministic code executes the document.**

Everything else follows from that. The plan is called the **Timeline**. It is the only source of truth.

## The shape of a run

```
Script
  │
  ▼
Director ──────────┐
Scene Planner      │  each one reads Timeline vN
Shot Planner       │  and writes Timeline vN+1
Asset Planner ─────┘
  │
  ▼
╔═══════════════════════════╗
║  HUMAN APPROVAL GATE      ║  ← nothing expensive has happened yet
╚═══════════════════════════╝
  │
  ▼
Asset Resolver   (search: project → archives → public domain → stock)
  │
  ▼
Media Generator  (only for what search could not find)
  │
  ▼
Renderer         (FFmpeg — pure, deterministic, no AI)
  │
  ▼
final.mp4
```

## Reading order for a newcomer

| Order | Document | Why |
|---|---|---|
| 1 | [00.5_Glossary.md](00.5_Glossary.md) | Vocabulary is enforced. Wrong words cause wrong code. |
| 2 | This document, sections 1–6 | Invariants, canon, contracts. |
| 3 | [07_Timeline_IR.md](07_Timeline_IR.md) | The data structure everything revolves around. |
| 4 | [03_Engineering_Principles.md](03_Engineering_Principles.md) | The 20 rules you will be reviewed against. |
| 5 | [00_Creative_Philosophy.md](00_Creative_Philosophy.md) | Required *only* before writing planner prompts — it is the prompt spec. |
| 6 | The ADR for the module you are touching | Reasons behind constraints that look arbitrary. |
| 7 | Everything else | On demand. |

**Do not read all 14 documents before writing code.** They are largely restatements of each other at different altitudes. The glossary, the IR doc, and this guide contain ~90% of the actionable content.

---

# 2. The Seven Invariants

These are non-negotiable. A change that violates one of these is a change to the architecture and requires a new ADR *before* the code is written.

### I1 — The Timeline is the only source of truth

No module keeps a private representation of project state. If you find yourself adding a field to a service so it can "remember" something between steps, that field belongs in the Timeline or in the workflow state — never in the module.

### I2 — The Timeline contains decisions, never media

No file paths, no bytes, no URLs to downloaded content inside the Timeline. The Timeline says *"find a photo of a Ruhr coal mine, 1936"*. Where that photo ended up living is **execution state**, stored separately (see [ShotBinding](#63-shotbinding-execution-state)).

### I3 — Timeline versions are immutable

Never mutate a persisted Timeline. Every planner produces a new version with a `parent_version` pointer. Rollback and partial regeneration depend entirely on this.

### I4 — AI never touches state, IO, or money

Planners return structured data. They do not write to the database, call provider APIs, download files, or spend generation credits. If a planner needs a fact from the outside world, that fact is fetched by deterministic code and passed *in*.

### I5 — Rendering is a pure function

`render(approved_timeline, resolved_assets, render_settings) → identical bytes, every time`. No AI in the render path. No wall-clock time, no randomness, no set iteration order, no locale-dependent formatting.

### I6 — Nothing expensive runs before approval

Search is cheap and may run early. Image generation, video generation, TTS, and rendering run only after `TimelineApproved`.

### I7 — Modules communicate through the Orchestrator

Modules take a command and return a result. A module never imports another module's service or writes another module's tables. ([ADR-005](adr/ADR-005-Commands-Not-State.md))

---

# 3. Canon — resolving contradictions in the frozen docs

Documents `00`–`12` were frozen at v1.0 and contain several disagreements. **This section is authoritative.** If you disagree, change it *here* first, then the affected doc, then the code.

## 3.1 The asset acquisition ladder

Four different orderings exist across the docs. **Canon:**

| Rung | Source | Cost | Notes |
|---|---|---|---|
| 0 | **Generation cache** | free | Exact hit on `hash(prompt + model + params)` from any previous project |
| 1 | **Project assets** | free | User-uploaded, or produced earlier in this project |
| 2 | **Historical / archival** | free | Wikimedia Commons, national archives, Library of Congress |
| 3 | **Public domain** | free | General PD sources |
| 4 | **Stock** | free–low | Pexels, Pixabay |
| 5 | **AI video generation** | high | Via fal.ai; specific model settled by bake-off in M7 |
| 6 | **AI image generation** | medium | Last resort |

**Clarification that the frozen docs get wrong:** "Image animation" (Ken Burns, slow zoom on a still) is **not** a rung on this ladder. It is a *render-time treatment* applied to any still image asset, regardless of which rung produced it. It belongs to the Renderer, driven by the shot's `camera` field.

An `AssetPlan.fallback_chain` must be a subsequence of this ladder in this order. It may skip rungs; it may never reorder them.

## 3.2 Project ↔ Timeline cardinality

[05_Domain_Model.md](05_Domain_Model.md) says "One Timeline" per project; [ADR-006](adr/ADR-006-Immutable-Timeline.md) requires many immutable versions. **Canon:** a Project has **many Timeline versions** and **at most one `active_timeline_version`**. "The Timeline" in prose always means the active version.

## 3.3 Timeline storage: document, not normalized rows

[10_Data_Model.md](10_Data_Model.md) implies normalized `scene` / `shot` / `asset_plan` tables. Combined with immutable versioning, that means duplicating every scene and shot row on every planner pass, and a schema migration every time the creative model gains a field.

**Canon:** the Timeline is stored as a **single JSONB document per version**, validated by Pydantic on read and write.

- *Benefit:* versioning is a row insert; rollback is a pointer update; diffing two versions is a JSON diff; the IR schema evolves without Alembic migrations.
- *Cost:* you cannot `SELECT` across shots in SQL.
- *Mitigation:* the mutable, per-shot execution state lives in a real relational table (`shot_binding`), and that is the thing you actually need to query ("which shots still need media?").

## 3.4 ADR numbering

Five ADR files have internal headings that contradict their filenames, and two ADRs describe the same decision.

| File | Internal heading | Action |
|---|---|---|
| `ADR-003-Provider-Abstraction.md` | `# ADR-004` | Fix heading to 003 |
| `ADR-004-Orchestrator.md` | `# ADR-003` | Fix heading to 004 |
| `ADR-006-Immutable-Timeline.md` | `# ADR-005` | Fix heading to 006 |
| `ADR-007-Asset-Resolution.md` | `# ADR-006` | Fix heading to 007 |
| `ADR-011-Human-Approval.md` | `# ADR-007` | **Mark Superseded by ADR-008** — duplicate decision |

**Canon: the filename is the ADR number.** Cite ADRs by filename, never by internal heading.

## 3.5 Backend package name

Architecture doc says `planner/`; the scaffold has `planners/`. **Canon: `planners/`** (plural, with `director/` as a sibling since the Director is an agent, not a planner).

---

# 4. Build Strategy and why it is shaped this way

## 4.1 The strategy: vertical skeleton first, then depth

The frozen roadmap ([11_Project_Roadmap.md](11_Project_Roadmap.md)) is *horizontal* — finish the whole domain layer, then the whole AI layer, then the whole asset layer, then rendering. That ordering is how the system is *described*, but it is a poor way to *build* it, because the first time anything reaches FFmpeg is Phase 7, and by then every earlier assumption has been baked into eight modules.

**This guide restructures the work as: build one thin end-to-end slice first (M0), then deepen each stage in place.**

```
Horizontal (frozen roadmap)          Vertical (this guide)
──────────────────────────           ──────────────────────
██████████ domain                    █ ▁▁▁▁▁▁▁▁▁  M0 skeleton, all stages fake
██████████ AI                        █ ███▁▁▁▁▁▁  M1–M4 real infra, fake AI
██████████ assets                    █ ██████▁▁▁  M5–M7 real AI + assets
██████████ render                    █ ██████████ M8+ real render
        ↑                                     ↑
  first MP4 exists                     first MP4 exists
  at ~80% of the work                  at ~8% of the work
```

### Why this is better — concretely

| Benefit | What it prevents |
|---|---|
| **An MP4 exists on day one** | The renderer's real constraints (resolution mismatch, SAR, audio sync, Windows path escaping) shape the IR *before* four planners are written against a naive IR. |
| **Integration risk is front-loaded** | FFmpeg pipelines and long-running provider jobs are where projects die. Meeting them early is cheap; meeting them in month three is a rewrite. |
| **Every later task has a socket to plug into** | "Implement the Shot Planner" is a well-defined task when a `FakeShotPlanner` already satisfies a real interface. It is an open-ended research project otherwise. |
| **The demo never regresses to zero** | There is always something runnable to show, and always something concrete to debug. |
| **Agents cannot get lost** | Each phase replaces one fake with one real implementation. The blast radius of any single task is one module. |
| **Cost stays near zero for weeks** | Fakes burn no API credits. You only start paying once the pipeline is proven. |

### The rule that makes it work

> **Every stage ships a `Fake*` implementation of its interface before it ships the real one, and the fake is kept forever.**

The fakes are not throwaway scaffolding. They become the test doubles that make the suite fast and free ([12_Testing_Strategy.md](12_Testing_Strategy.md) requires external services be mocked), and they stay as the `dry-run` mode that lets a user rehearse a whole project without spending a cent.

## 4.2 Second reordering: Workflow Engine before AI Planners

The frozen roadmap puts AI Planning at Phase 4 and the Workflow Engine at Sprint 6. **Build the Workflow Engine first.**

A planner is a *step implementation*. Writing planners before the step abstraction exists means each planner invents its own retry, progress, persistence, and error handling — and all four then get rewritten when the engine arrives. Building the engine first means each planner is a single `run()` method with everything else supplied.

## 4.3 The API grows continuously, it is not a phase

`tasks.md` places the REST API at Sprint 10. In practice you need `POST /projects` and `GET /projects/{id}/status` on day one to drive the skeleton. **Add each endpoint when the capability behind it lands.** The endpoint set in [09_API_Specification.md](09_API_Specification.md) is the target, not a milestone.

## 4.4 Phase map

| Phase | Name | Replaces which fake | Frozen-doc equivalent |
|---|---|---|---|
| M0 | Walking Skeleton | — (creates all fakes) | *new* |
| M1 | Foundation | — | Sprint 1 / Phase 1–2 |
| M2 | Persistence & Domain | in-memory store | Sprints 2–3 / Phase 3 |
| M3 | Timeline Service | fixture timeline | Phase 3 |
| M4 | Workflow Engine | linear script | Sprint 6 |
| M5 | AI Planners | `FakeDirector` etc. | Sprint 5 / Phase 4 |
| M6 | Asset Pipeline | `FakeAssetProvider` | Sprint 7 / Phase 5 |
| M7 | Media Generation | `FakeImageProvider`, `FakeVideoProvider` | Sprint 8 / Phase 6 |
| M8 | Renderer | slideshow renderer | Sprint 9 / Phase 7 |
| M9 | API & Frontend | curl | Sprints 10–11 |
| M10 | Hardening | — | Sprint 12 / Phase 8 |

---

# 5. Repository layout and module ownership

```
video-generation-engine/
├── backend/
│   ├── app/
│   │   ├── main.py                 FastAPI app factory. Wiring only.
│   │   ├── api/                    HTTP layer. Routers, request/response models.
│   │   │                           MUST NOT contain business logic.
│   │   ├── core/                   Settings, logging, errors, ids, clock, DI container.
│   │   │                           Imported by everything; imports nothing from app.
│   │   ├── db/                     Engine, session, Base, Alembic wiring.
│   │   ├── models/                 SQLAlchemy ORM models. Persistence shape only.
│   │   ├── schemas/                Pydantic models. API + IR + command/result shapes.
│   │   ├── repositories/           All SQL lives here. One repo per aggregate.
│   │   ├── timeline/               Timeline IR types, versioning, validation, diff.
│   │   ├── orchestrator/           Command dispatch, step sequencing, retries, events.
│   │   ├── workflow/               Step definitions, state machine, progress.
│   │   ├── director/               Director agent (script → narrative structure).
│   │   ├── planners/
│   │   │   ├── scene/              Scene Planner
│   │   │   ├── shot/               Shot Planner
│   │   │   └── asset/              Asset Planner
│   │   ├── assets/                 Asset Resolver, ranking, download, dedupe, licence gate.
│   │   ├── providers/              ALL external IO. One subpackage per provider.
│   │   │   ├── base.py             Protocols: Image/Video/Narration/AssetProvider, LLMProvider
│   │   │   ├── fakes/              Deterministic fakes for every protocol. Never delete.
│   │   │   ├── openai/  fal/  elevenlabs/  wikimedia/  pexels/  pixabay/
│   │   ├── renderer/               FFmpeg graph construction and execution.
│   │   ├── workers/                Background execution entry points.
│   │   ├── prompts/                Versioned prompt templates (.md / .jinja). Not code.
│   │   └── utils/                  Genuinely generic helpers only.
│   └── tests/
│       ├── unit/  integration/  e2e/  fixtures/
├── frontend/                       Next.js. Not started.
├── docker/  infra/  scripts/
├── docs/                           00–12 frozen. This file living. adr/ append-only.
└── storage/                        gitignored. Local file storage root.
```

## Dependency rule

```
api  →  orchestrator  →  workflow  →  {director, planners, assets, renderer}  →  providers
                                                    ↓
                                              repositories  →  models  →  db
         everything  →  core, schemas
```

**Arrows point one way.** A provider never imports a planner. A repository never imports a service. If you need a back-edge, you need an event or a callback passed in — not an import.

## The `providers/` firewall

Every network call, subprocess spawn, and filesystem write to external content happens inside `providers/` or `renderer/`. This is what makes [I4](#i4--ai-never-touches-state-io-or-money), the test strategy, and the dry-run mode all work with a single mechanism. If `import httpx` appears outside `providers/`, that is a bug.

---

# 6. The four core contracts

Get these right and the rest of the system is mechanical. Get them wrong and every phase pays for it.

## 6.1 Timeline IR

Canonical JSON document, one per version, stored in `timeline_version.document` (JSONB).

```jsonc
{
  "schema_version": "1.0",
  "timeline_id": "uuid",
  "project_id": "uuid",
  "version": 3,
  "parent_version": 2,
  "produced_by": "shot_planner",        // director | scene_planner | shot_planner | asset_planner | human
  "status": "draft",                    // draft | awaiting_approval | approved | superseded
  "created_at": "2026-08-14T10:00:00Z",

  "metadata": {
    "language": "en",
    "aspect_ratio": "9:16",
    "resolution": [1080, 1920],
    "fps": 30,
    "total_duration_s": 58.5,          // derived from narration, never invented — D1
    "voice_id": "…"                    // narration voice for this project
  },

  "music_plan": {                       // D6 — creative, so it lives here, not in the renderer
    "mood": "sombre, restrained",
    "tempo": "slow",
    "energy_arc": "build",              // flat | build | fall | build_fall
    "search_terms": ["documentary underscore", "sparse strings", "wartime"],
    "licence_requirements": ["cc0", "pixabay"]
  },

  "creative_context": {                 // ADR-010. Additive only — never overwrite.
    "tone": "sober documentary",
    "visual_style": "1940s archival, desaturated",
    "historical_period": "1936-1945",
    "audience": "general",
    "camera_language": "static and slow push; no whip pans",
    "colour_palette": ["#2b2b28", "#8a7f6b", "#d9d2c5"],
    "constraints": ["no swastika imagery", "no AI faces of real people"]
  },

  "scenes": [
    {
      "id": "sc_01",
      "order": 0,
      "title": "Germany's Industrial Economy",
      "summary": "Establishes German coal wealth and oil dependency.",
      "emotion": "curiosity",
      "narrative_purpose": "setup",
      "narration_text": "Germany possessed abundant coal, but lacked domestic oil reserves.",
      "duration_s": 8.0,

      "shots": [
        {
          "id": "sh_01_01",
          "order": 0,
          "intent": "explain",                    // introduce|explain|compare|reveal|contrast|emphasize|transition
          "intent_text": "Show the scale of German coal extraction",
          "narration_span": [0, 34],              // char offsets into scene.narration_text
          "duration_s": 3.0,
          "framing": "wide",
          "camera": {
            "movement": "slow_zoom",              // static|slow_zoom|slow_push|pull_back|pan|split_frame
            "direction": "in",
            "intensity": 0.15                     // 0..1, renderer maps to zoom/pan magnitude
          },
          "transition_out": { "type": "dissolve", "duration_s": 0.4 },
          "prompt": "1930s Ruhr valley coal mine, workers, overcast, archival photograph",

          "asset_plan": {
            "strategy": "historical_search",      // top rung to attempt
            "search_queries": [
              "Ruhr coal mine 1936",
              "German coal miners 1930s",
              "Zeche Zollverein historical"
            ],
            "preferred_type": "image",            // image | video
            "fallback_chain": ["public_domain", "stock", "generate_image"],
            "licence_requirements": ["public_domain", "cc0", "cc_by"]
          }
        }
      ]
    }
  ]
}
```

### Rules

- **Every planner receives a full Timeline and returns a full Timeline.** No partial patches. Diffing is the reader's job.
- **Additive only.** A later planner may fill fields a previous one left null. It must not overwrite a populated field, and it must not touch `creative_context` keys that already exist ([ADR-010](adr/ADR-010-Creative-Context.md)).
- **`schema_version` is checked on every load.** An unknown version fails loudly rather than silently mis-parsing.
- **IDs are stable across versions.** `sh_01_01` in v2 is the same shot in v5. Partial regeneration depends on this — if the Shot Planner regenerates IDs, every resolved asset orphans.
- **No media, no paths, no URLs.** See [I2](#i2--the-timeline-contains-decisions-never-media).
- **Durations derive from narration, never from invention** (D1). A shot's `duration_s` must cover the words spoken over its `narration_span`. The Shot Planner proposes; TTS timings are authoritative, and `append_version` reconciles the two. Those timings are character-level, and `narration_span` is a character-offset pair — so the reconciliation is an index lookup, not an alignment problem ([M8](#phase-m8--renderer)).
- **Hard limits are validated, not just prompted** (D7): `total_duration_s` ≤ 90, total shots ≤ 40, scenes ≤ 12, and 1.5 ≤ `duration_s` ≤ 8.0 per shot. A planner that violates these fails validation and gets one repair attempt.
- **Transitions overlap** (D5). A 0.4s dissolve between two 3.0s shots yields 5.6s of video, not 6.0s. One function owns this arithmetic and both the planner and the renderer call it.

## 6.2 Command / Result

```python
class Command(BaseModel):
    command_id: UUID
    project_id: UUID
    idempotency_key: str          # stable for a given (step, input) — retries must not duplicate work
    issued_at: datetime
    issued_by: str                # "orchestrator" | "api" | "user:{id}"

class GenerateShotsCommand(Command):
    timeline_version: int

class Result(BaseModel):
    command_id: UUID
    outcome: Literal["ok", "retry", "failed"]
    duration_ms: int
    error: ErrorInfo | None = None
    cost: CostInfo | None = None  # tokens / credits / provider calls, for budget tracking

class GenerateShotsResult(Result):
    new_timeline_version: int | None
```

Three outcomes, not two. `retry` means "transient, try me again"; `failed` means "stop, a human must intervene". The distinction drives the entire retry policy ([08_Workflow_Engine.md](08_Workflow_Engine.md)).

## 6.3 ShotBinding (execution state)

This table is the answer to "where did the media go", and the reason the Timeline stays clean.

```python
class ShotBinding(Base):
    id: UUID
    project_id: UUID
    timeline_version: int          # which approved version this binding satisfies
    shot_id: str                   # "sh_01_01" — matches the IR
    state: Literal["pending", "searching", "resolved", "generating",
                   "generated", "failed", "skipped"]
    asset_id: UUID | None          # resolved existing asset
    clip_id: UUID | None           # generated media
    rung: str | None               # which ladder rung succeeded — for cost reporting
    attempts: int
    last_error: str | None
    cost_cents: int
```

Mutable, queryable, per-shot. `SELECT * FROM shot_binding WHERE state = 'pending'` is the media generation work queue. Partial regeneration = reset one row and re-run.

## 6.4 Provider protocols

```python
class ImageProvider(Protocol):
    name: str
    model_id: str                  # from config, never hardcoded — see M7
    async def generate(self, req: ImageRequest) -> ImageResult: ...
    def estimate_cost(self, req: ImageRequest) -> CostInfo: ...

class VideoProvider(Protocol):
    name: str
    model_id: str
    async def submit(self, req: VideoRequest) -> JobHandle: ...      # long-running: submit + poll
    async def poll(self, handle: JobHandle) -> JobStatus: ...
    def estimate_cost(self, req: VideoRequest) -> CostInfo: ...

class AssetProvider(Protocol):
    name: str
    rung: str                                                        # ladder rung it serves
    async def search(self, q: AssetQuery) -> list[AssetCandidate]: ...
    async def fetch(self, c: AssetCandidate) -> AssetBytes: ...

class NarrationProvider(Protocol):
    async def synthesize(self, text: str, voice: str) -> NarrationResult: ...
    # NarrationResult carries audio bytes AND word_timings: list[WordTiming].
    # The timings are not optional — D1 makes them the master clock for the
    # whole render. A provider that cannot return them cannot be used.

class MusicProvider(Protocol):
    name: str
    async def search(self, plan: MusicPlan) -> list[TrackCandidate]: ...
    async def fetch(self, c: TrackCandidate) -> AudioBytes: ...

class LLMProvider(Protocol):
    async def structured(self, prompt: str, schema: type[BaseModel],
                         **opts) -> tuple[BaseModel, LLMCallRecord]: ...
```

`estimate_cost` on every paid provider is not optional — it is what powers the pre-approval cost estimate and the budget cap ([I6](#i6--nothing-expensive-runs-before-approval)).

`model_id` is a field, not a constant, because both generative providers route through fal.ai and the specific model is settled by bake-off in M7. It is recorded on every `generated_clip` row so the generation cache never serves a clip from a model you have since moved off.

`structured()` returning a `LLMCallRecord` alongside the parsed object is what makes planning auditable and replayable. Never call an LLM without recording the exchange.

---

# Phase M0 — Walking Skeleton

> **Goal:** `POST` a script, get back an MP4. Every stage present, every stage fake.

## Why this phase exists

To prove the pipeline's plumbing before any of it is expensive or clever. At the end of M0 nobody has written a prompt, called a paid API, or designed a database schema — but an MP4 exists, and the shape of the IR has been tested against a real FFmpeg invocation.

## Build order

1. `backend/app/main.py` — FastAPI app, `GET /health`.
2. `schemas/timeline.py` — the IR as Pydantic models, exactly as in [6.1](#61-timeline-ir).
3. `tests/fixtures/timeline_v1.json` — a hand-written 3-scene, 6-shot Timeline. **Write this by hand.** It forces you to feel whether the IR is usable.
4. `providers/fakes/` — fake image provider that emits a solid-colour PNG with the prompt text drawn on it; fake asset provider that returns a checkerboard; fake LLM that returns the fixture.
5. `renderer/` — take a Timeline + a dict of `shot_id → image path`, produce an MP4: still images, each held for `duration_s`, hard cuts, no audio.
6. An in-memory project store and a linear `run_pipeline()` function.
7. `POST /projects/{id}/render` → MP4 on disk; `GET /projects/{id}/video` streams it.

## Advice

- **Draw the prompt text onto the fake images.** When you later stare at a 60-second draft, being able to read *"shot sh_02_03: coal barge"* on the frame is worth an hour of log-reading.
- **Do not use a real database.** A `dict[UUID, Project]` is correct for M0. M2 replaces it.
- **Prove FFmpeg on Windows now.** Path quoting, drive letters, and the `subtitles=` filter's colon-escaping (`C\:/path/subs.ass`) are all going to bite. Meet them on day one with a 6-shot slideshow, not on day sixty with a 40-node filter graph.
- **Hard-code the resolution to 1080×1920.** Vertical is the product. Do not build a general video compositor.
- **Time-box this to a few days.** If M0 is taking two weeks, the IR is too complicated — simplify it.

## Done when

- [x] `POST /projects` → `POST /projects/{id}/script` → `POST /projects/{id}/render` → downloadable MP4
- [x] The MP4 has the right duration, right aspect ratio, right number of visible shots
- [x] It runs with zero API keys configured (`DRY_RUN=true`, all fakes)
- [x] `pytest tests/e2e/test_skeleton.py` does the whole thing headlessly

**Status: M0 complete** (2026-08-14). Fixture: `backend/tests/fixtures/timeline_v1.json`
(3 scenes, 6 shots, the Germany coal/oil example used throughout the docs).
Renderer proven against real FFmpeg on Windows: xfade crossfades within a
run, concat-demuxer hard cuts between runs, output verified via `ffprobe`
to be 1080×1920 @ 30fps h264/yuv420p with duration within 2 frames of the
value `app.timeline.duration.compute_timeline_duration` predicts. All 4
tests green; `ruff` / `black` / `mypy` clean across `backend/app`.

`docker compose up -d postgres redis` verified 2026-08-14: both containers
report `(healthy)`, `pg_isready` and `redis-cli ping` both succeed.

---

# Phase M1 — Foundation

> **Goal:** the boring infrastructure that everything else assumes exists.

## Deliverables

`pyproject.toml`, `Settings`, structured logging, error taxonomy, Docker, docker-compose (Postgres + Redis), Makefile, ruff/black/mypy, pre-commit, CI.

## Key files

- `core/config.py` — one `Settings(BaseSettings)` object, loaded once, injected everywhere.
- `core/logging.py` — structured JSON logs.
- `core/errors.py` — the exception hierarchy.
- `core/ids.py` — ID generation. `core/clock.py` — the *only* place `datetime.now()` is called.

## Error taxonomy — define this now, not later

```python
class EngineError(Exception): ...

class TransientError(EngineError):        # → Result(outcome="retry")
    """Rate limit, timeout, 5xx, connection reset."""

class PermanentError(EngineError):        # → Result(outcome="failed")
    """Invalid script, schema violation, licence rejected, budget exceeded."""

class UserActionRequired(EngineError):    # → workflow pauses, does not fail
    """Awaiting approval; ambiguous input; manual asset needed."""
```

Every provider maps its own SDK exceptions into these three at the provider boundary. Nothing above `providers/` should ever see a `openai.RateLimitError`.

## Advice

- **Correlation IDs from the first log line.** Every log record carries `project_id`, `run_id`, `step`, `shot_id` where applicable. Retrofitting this after twelve modules exist is miserable, and [Principle 14](03_Engineering_Principles.md) makes it mandatory anyway.
- **One `Settings` object, injected — never `os.getenv()` scattered through modules.** [Principle 13](03_Engineering_Principles.md).
- **Populate `.env.example` with every key, all blank.** It is currently empty, and it is the fastest way for a new developer or agent to know what the system talks to.
- **Add `DRY_RUN: bool` to settings in M1.** When true, the DI container hands out fakes for every paid provider. This single flag will save more money and time than any other feature in the system.
- **`make check` must run ruff + black + mypy + pytest in one command.** Both humans and agents need one verification command; if there are four, some will be skipped.
- **Do not add Celery.** [Principle 18](03_Engineering_Principles.md) — simple first. Redis is for cache and rate limiting for now. The step interface in M4 is deliberately queue-agnostic, so a queue can be introduced later without touching business logic.

## Done when

- [ ] `docker compose up` gives a working API against Postgres + Redis
- [ ] `make check` is green
- [ ] CI runs `make check` on every PR
- [ ] `DRY_RUN=true` runs M0's pipeline with zero network calls

---

# Phase M2 — Persistence and Domain

> **Goal:** the in-memory store becomes Postgres.

## Tables

| Table | Notes |
|---|---|
| `project` | Aggregate root. `status`, `active_timeline_version`. |
| `script` | Immutable, versioned. Content is text. |
| `timeline_version` | `(project_id, version)` unique. `document` JSONB. `parent_version`. Append-only. |
| `shot_binding` | Mutable per-shot execution state ([6.3](#63-shotbinding-execution-state)). |
| `asset` | Provenance: `source_url`, `licence`, `attribution`, `content_hash`, `local_path`. |
| `generated_clip` | `prompt_hash`, `provider`, `model`, `cost_cents`, `local_path`. |
| `render` | `fingerprint`, `output_path`, `settings` JSONB, `status`. |
| `workflow_run` | State machine: `state`, `current_step`, `progress`, timestamps. |
| `workflow_step_attempt` | One row per attempt. Audit + retry accounting. |
| `llm_call` | Full request/response for every planning call. Audit + replay. |
| `domain_event` | Append-only event log ([08](08_Workflow_Engine.md)). |

## Advice

- **UUID primary keys everywhere.** They let you generate IDs before insert, which the orchestrator needs.
- **`content_hash` (SHA-256 of bytes) is unique on `asset`.** The same Wikimedia photo will be found by three different queries. Dedupe at the byte level or you will store it three times and show it twice in one video.
- **`prompt_hash` is unique on `generated_clip`.** This *is* rung 0 of the ladder. It makes regeneration free and is the single biggest cost saving in the system.
- **Review every Alembic autogenerate.** It gets JSONB, indexes, and enum changes wrong often enough that blind application will corrupt a migration chain.
- **Store money as integer cents.** Never floats.
- **Write repositories, not queries-in-services.** All SQL in `repositories/`. This is what allows the eventual swap of the storage layer and keeps services unit-testable ([Principle 17](03_Engineering_Principles.md)).
- **Do not normalise the Timeline.** See [canon 3.3](#33-timeline-storage-document-not-normalized-rows). This will feel wrong to anyone with a relational instinct — the rationale is written down; read it before "fixing" it.

## Done when

- [x] Alembic migration chain from empty to full schema runs clean
- [x] M0's e2e test passes with the DB backend
- [x] Killing the process mid-run loses no committed state

**Status: M2 complete** (2026-08-14). All 11 tables created via one Alembic
migration (`backend/alembic/versions/ec1b1fb9f37a_initial_schema.py`),
applied to the `docker compose` Postgres. `PostgresProjectRepository`
implements `ProjectRepository` for `project` + `script` + `timeline_version`
(append-a-row-if-content-differs — the real M3 `append_version` discipline
replaces this). `InMemoryProjectRepository` kept as the fast unit-test
double. `tests/e2e/test_skeleton.py` now runs against real Postgres
(`clean_database` fixture truncates all tables before each test); process
restart proven directly (create in one `python` process, read back in a
separate one — see commit history, not just the test suite).

Two bugs found and fixed while building this, both worth knowing about:
- `Settings.model_config.env_file=".env"` resolved against the **process
  cwd**, not the repo root — silently found nothing (all defaults, no
  error) whenever invoked from `backend/` (e.g. `alembic`, or a test
  runner launched from there). Fixed to an absolute path from `__file__`.
- All `datetime` columns were missing `timezone=True`. `app.core.clock.utcnow()`
  is tz-aware UTC everywhere else in the app; a naive column would have
  silently truncated that on every write. Fixed across all 10 model files
  before the migration was applied — worth a second look if you add a
  new timestamp column later.
- Async engine uses `NullPool`: the sync `TestClient` (its own event-loop
  thread) and pytest-asyncio fixtures (a fresh loop per test) both touch
  the same global engine, and a pooled asyncpg connection is bound to
  whichever loop first created it. `NullPool` sidesteps this entirely at
  the cost of a fresh connection per checkout — revisit only once there's
  load to justify real pooling (Principle 18).

Not yet built: the M3 versioning discipline itself, `shot_binding` /
`asset` / `generated_clip` / etc. are schema-only (no code writes to them
yet — that lands with M6/M7), and there is still no `Script`/`Timeline`
immutability enforcement beyond "append if different."

---

# Phase M3 — Timeline Service

> **Goal:** the versioning discipline in [I3](#i3--timeline-versions-are-immutable) becomes impossible to violate.

## The core API

```python
class TimelineService:
    def create_initial(self, project_id, script) -> Timeline: ...
    def get_active(self, project_id) -> Timeline: ...
    def get_version(self, project_id, version) -> Timeline: ...

    def append_version(self, project_id, produced_by: str,
                       transform: Callable[[Timeline], Timeline]) -> Timeline:
        """Load active → deep copy → transform → validate → persist as version+1.
        The ONLY way a new Timeline version is created."""

    def approve(self, project_id, version) -> Timeline: ...
    def diff(self, project_id, v_from, v_to) -> TimelineDiff: ...
    def rollback_to(self, project_id, version) -> Timeline: ...   # appends a copy; never deletes
```

## Advice

- **`append_version` is the only writer.** No `session.add(TimelineVersion(...))` anywhere else in the codebase. Make this a review rule and, if you can, enforce it with an import-linter contract.
- **Deep copy before transform.** If a planner mutates the object it was handed, the previous version is corrupted in the identity map before it is ever flushed. This is the single most likely way [I3](#i3--timeline-versions-are-immutable) gets silently broken.
- **Validate on write *and* on read.** Reading validates against `schema_version`; writing catches planner output that drifted from the schema.
- **Enforce additive-only in code, not by convention.** `append_version` should assert that no previously-populated field became null or changed value, except for fields the calling planner is explicitly declared to own. This one assertion catches the most common category of planner bug.
- **Build `diff` early.** The human approval UI needs it, but *you* need it more — "what did the Shot Planner actually change?" is the question you will ask fifty times in M5.
- **Rollback appends, never deletes.** Rolling back from v7 to v3 creates v8 whose content equals v3. History stays intact.

## Done when

- [x] Every planner-shaped mutation goes through `append_version`
- [x] A test proves that mutating a returned Timeline does not affect the stored one
- [x] `diff(v1, v2)` produces readable scene/shot-level changes
- [x] Approval sets status and pins `active_timeline_version`

**Status: M3 complete** (2026-08-14). `app/timeline/service.py` implements
the full API: `create_initial` (empty v1, before any planner runs),
`append_version` (deep copy → transform → JSON round-trip validation →
additive-only check → persist as version+1), `approve`, `diff`, and
`rollback_to` (appends a copy, never deletes). `app/timeline/additive.py`
is the additive-only enforcement — a caller declares `owns: frozenset[str]`
(dotted field paths it may change freely); every other previously-populated
field must come out unchanged or the write is rejected with `PermanentError`.
`app/timeline/diff.py` is a pure, DB-free `compute_diff` producing
scene/shot-level `FieldChange` lists.

`PostgresProjectRepository` no longer writes `timeline_version` at all —
it only reads the latest row (via `TimelineVersionRepository`) to embed
into a returned `Project`. `TimelineService` is the sole writer, enforced
structurally rather than by convention. The M0 pipeline's fake planner now
goes through `create_initial` + one `append_version` call (`owns={"metadata",
"creative_context", "music_plan", "scenes"}`, since the fixture fills
everything a real Director/Scene/Shot/Asset Planner chain would across four
calls) — proving the discipline works end to end before a single real
planner exists.

14/14 tests pass: the 4 e2e tests unchanged, plus 9 new integration tests in
`tests/integration/test_timeline_service.py` covering deep-copy isolation,
additive-only rejection *and* the ownership-declared success path, diff
output, approve pinning `active_timeline_version`, and rollback preserving
full history (v2 and v3 both still readable after rolling back to v2).

Not yet built: real planners (M5) will exercise `append_version` with
genuinely different `owns` sets per stage (Director owns `scenes` at the
skeleton level; Shot Planner owns `scenes[].shots`; etc.) — M3 proves the
mechanism, M5 proves it under real multi-stage ownership boundaries. No
import-linter contract yet enforcing "only `TimelineService` writes
`timeline_version`" — currently a comment-level rule, worth automating
before more code gets a chance to violate it.

---

# Phase M4 — Workflow Engine

> **Goal:** a resumable, observable, retryable state machine. Then planners become trivial to add.

## The step contract

```python
class WorkflowStep(Protocol):
    name: str
    retryable: bool
    max_attempts: int

    async def is_satisfied(self, ctx: RunContext) -> bool:
        """True if this step's output already exists. Makes runs resumable and idempotent."""

    async def run(self, ctx: RunContext) -> StepResult: ...
```

## Pipeline ([ADR-009](adr/ADR-009-Workflow-Steps.md))

```
create_project → generate_timeline → plan_scenes → plan_shots → plan_assets
→ AWAIT_APPROVAL → resolve_assets → generate_media → render → complete
```

## Advice

- **`is_satisfied()` is what makes resume work.** Before running a step, ask if it is already done. A run that crashed during `generate_media` restarts and skips straight past five planning steps without re-spending anything. Do not implement resume by tracking a step index — track *observable state*.
- **Every step must be idempotent.** Running `resolve_assets` twice must not download twice or create duplicate rows. Idempotency keys ([6.2](#62-command--result)) plus `is_satisfied` give you this.
- **`AWAIT_APPROVAL` is a state, not a blocked coroutine.** The run *ends*. A later `POST /timeline/approve` starts a new run that resumes at the next step. Never hold a request or a task open waiting for a human ([ADR-008](adr/ADR-008-Human-In-The-Loop.md)).
- **Persist a `workflow_step_attempt` row before the attempt, not after.** Otherwise a hard crash leaves no trace of what was in flight.
- **Exponential backoff with jitter, and honour `Retry-After`.** Provider rate limits are the most common transient failure by a wide margin.
- **Emit a domain event per transition** ([08](08_Workflow_Engine.md)). This costs almost nothing now and is the substrate for progress reporting, debugging, and any future distributed execution.
- **Progress should be derived, not stored as a number.** `completed_shots / total_shots` computed from `shot_binding` is always true; a stored `progress = 47` drifts the moment anything fails.
- **Failure is per-task, not per-project** ([Principle 10](03_Engineering_Principles.md)). One shot failing to generate must not abort the other fifty-nine. Mark the binding failed, continue, and surface it at the end.

## Done when

- [x] Kill the process at any step; restart; the run resumes correctly and re-does nothing already done
- [x] A forced transient failure retries and succeeds
- [x] A forced permanent failure stops with a clear error and leaves state inspectable
- [x] `GET /projects/{id}/progress` reflects reality

**Status: M4 complete** (2026-08-14). `app/workflow/engine.py` implements
the `WorkflowEngine`: for each step in order, ask `is_satisfied()` first
(skip if true), else run it with retry+backoff (`app/workflow/retry.py`,
exponential with jitter), persisting a `workflow_step_attempt` row
*before* every attempt starts. Four step outcomes, not three — `"awaiting_approval"`
is a real state the run ends on, never an error (ADR-008): `AwaitApprovalStep`
returns it whenever the active timeline isn't `APPROVED` yet, and a later
`POST /timeline/approve` calls `TimelineService.approve` then starts a
*new* engine invocation that resumes at the next unmet step.

Five steps implement ADR-009's pipeline, collapsed to match what actually
exists today (`app/workflow/steps/`): `generate_timeline` (M5's Director
→ Asset Planner chain, still the M0 fake, now going through `append_version`
inside the engine rather than a bespoke script), `await_approval`,
`resolve_assets` (M6 search + M7 generation collapsed, but *real* `Asset`
and `GeneratedClip` rows with both dedup caches wired — per-project
`content_hash`, global `prompt_hash` — even though the provider underneath
is still a fake), `render`, `complete`.

Two schema bugs fixed before this could work correctly, found while
wiring the real read/write paths for the first time:
- `Asset.content_hash` had a **global** unique constraint — two different
  projects downloading the same public-domain photo would collide.
  Migration `6a4ee7c1aae3` rescoped it to `(project_id, content_hash)`.
  `GeneratedClip.prompt_hash` staying globally unique is correct as-is —
  identical generations *should* be reused across projects (ladder rung 0).
- `ShotBinding` had no uniqueness constraint at all — the same migration
  adds `(project_id, timeline_version, shot_id)`, which is what makes
  `get_or_create_pending` safe to call repeatedly.

Failure isolation is real, not aspirational: `ResolveAssetsStep` catches
per-shot, marks that one `ShotBinding` `failed`, and keeps going — a
`TransientError` leaves the binding `pending` (eligible for a later
retry) rather than `failed`. `RenderStep` gives any shot without a
resolved image a placeholder frame (`app/renderer/placeholder.py`) so
one bad shot never blocks the render.

18/18 tests pass: the e2e test now exercises the real two-phase
render → awaiting_approval → approve → completed flow (plus a
render-again-while-waiting no-op check, and a rejected double-approve),
9 unchanged `TimelineService` tests, and 4 new `tests/integration/test_workflow_engine.py`
tests — retry-then-succeed, exhaust-retries-then-fail, permanent-failure-is-inspectable,
and the resumability proof: two genuinely separate `WorkflowEngine`
instances (standing in for two OS processes) against the same project,
where the second one's `is_satisfied()` correctly skips `generate_timeline`
and the timeline stays at v2 instead of becoming v3.

Not yet built: background/async execution (every run is still
synchronous within one HTTP request — a task queue is a later
refinement the step contract doesn't need to change for), and
`resolve_assets`/`render` still route through fakes — M6/M7 swap the
provider inside the same step shape.

**Update (2026-08-15) — a second `is_satisfied()` staleness bug, found by
the first real end-to-end test.** `RenderStep.is_satisfied()` only asked
"does `project.video_path` point to a file that exists" — true the moment
*any* render has ever completed, regardless of whether the shot bindings
it was rendered from are still what they were. During the first live test,
a bug in the asset-search providers (see M6 notes) got fixed and
`resolve_assets` was re-run and genuinely re-resolved every shot from
placeholders to real photos — but a subsequent `POST /render` call saw the
old video file, considered `RenderStep` already satisfied, and skipped
re-rendering entirely. The "fixed" project kept shipping the exact same
all-placeholder video it had before the fix, silently. `is_satisfied()`
now also compares the render file's mtime against
`max(shot_binding.updated_at)` for the timeline's shot bindings, and
requires the file to be newer. The general lesson (already learned once
this session for `GenerateTimelineStep`, see M5 notes): a step contract
based on "does *some* output exist" is not the same contract as "is this
output still valid *given current upstream state*" — the second one is
what resumability actually requires, and the gap only shows up when
upstream state legitimately changes between two runs of the same project,
which golden-file/mocked tests essentially never exercise.

---

# Phase M5 — AI Planners

> **Goal:** replace `FakeDirector`, `FakeScenePlanner`, `FakeShotPlanner`, `FakeAssetPlanner` with real LLM calls.

## Order

Director → Scene Planner → Shot Planner → Asset Planner. Each one, end to end, before starting the next. Do not write all four prompts and then debug them together.

## Advice

- **[00_Creative_Philosophy.md](00_Creative_Philosophy.md) is the prompt specification.** It is not decoration. The 15 principles — narrative first, one idea per shot, motion has purpose, documentary default, quality over quantity — are what you paste into system prompts and what you write evals against. A shot with no identifiable intent is a bug ([Principle 9](00_Creative_Philosophy.md)).
- **Prompts live in `app/prompts/` as versioned files, never as string literals in Python.** Record `prompt_version` on every `llm_call` row. When output quality shifts, you need to know which prompt produced which timeline.
- **Force structured output.** Use the provider's JSON-schema/structured-output mode with your Pydantic model. On validation failure, allow exactly *one* repair round-trip (feed the error back), then fail permanently. Unbounded repair loops burn money silently.
- **Constrain the output space hard.** Max scenes, max shots per scene, min/max shot duration, enum-only camera moves and transitions. An unconstrained planner will emit forty-two 0.4-second shots and the renderer will produce a strobe.
- **Total duration must be derived from narration, not invented.** A shot's duration has to cover the words spoken over it. Per **D1** the source is ElevenLabs' timestamps (character-level — see [M8](#phase-m8--renderer)), and narration is the master clock — the Shot Planner proposes durations, TTS timings correct them. Build the Shot Planner against that from the start.
- **Enforce the D7 caps in the prompt *and* in validation.** 90s, ≤40 shots, ≤12 scenes, 1.5–8.0s per shot. Prompt-only constraints are suggestions; validation makes them real.
- **The Director produces the `music_plan`** (D6) alongside the emotional arc — same call, since mood and tempo fall straight out of the narrative progression it is already reasoning about. No separate Music Planner agent in v1.
- **Low temperature, and pass a seed where the provider supports it.** Planning is not where you want creativity variance; the creativity is in the prompt.
- **Record every LLM exchange (`llm_call`).** This gives you replay-based tests, cost attribution, and the ability to answer "why did it choose that?" three weeks later.
- **Test with recorded responses.** Golden-file tests: recorded LLM response → planner → expected Timeline. Fast, free, deterministic, and they catch prompt regressions. Real-API tests are a separate, manually-triggered suite.
- **Treat script text as untrusted input.** It flows into prompts, filenames, and eventually FFmpeg arguments. See [18.5 Security](#185-security).
- **Judge quality with a rubric, not vibes.** A small eval set of 5–10 scripts, scored against the Creative Philosophy principles, run whenever a prompt changes. Without this, prompt iteration is a random walk.

## Done when

- [x] A real script produces a coherent Timeline that a human reads and recognises as a sensible plan
- [x] Every planner is additive-only and passes the `append_version` assertion
- [x] Golden-file tests cover all four planners
- [x] Fakes still work — `DRY_RUN=true` still produces an MP4

## Implementation notes (2026-08-14)

Built as designed above, with one refinement to the four-way split once the
Timeline IR's shape was actually worked through: **Director** owns only
`creative_context` + `music_plan` (the whole-script creative vision);
**Scene Planner** owns `scenes` as narrative structure only (title, summary,
emotion, narrative_purpose, narration_text, duration_s — shots left empty);
**Shot Planner** fills `shots` per scene (one LLM call per scene, so the
narration-span/duration-sum constraints stay scoped to something the model
can reason about) and stamps `metadata.total_duration_s` via the same
`compute_timeline_duration()` the renderer will use (D5); **Asset Planner**
fills `asset_plan` per shot, batched one call per scene. Each stage is its
own `append_version` call — v1 (empty, `create_initial`) through v5.

- **`app/providers/base.py`** gained `PlanningLLMProvider` (Protocol) +
  `StructuredCompletion` (the audit-ready return shape) — every planner
  depends on this, never on the OpenAI SDK. `app/providers/openai_provider.py`
  is the only file that imports `openai`; it maps SDK exceptions to
  `TransientError`/`PermanentError` at the boundary (ADR-003).
- **`app/prompts/{agent}/v1.md`** — plain-text prompt files, loaded by
  `app/prompts/loader.py`. Each is the Creative Philosophy's principles
  translated into that agent's specific job.
- **API-facing schemas are deliberately separate from the Timeline IR**
  (`app/planners/{agent}/schemas.py`) and every field is required, with no
  defaults and no `min_length`/`max_length` constraints — OpenAI's
  structured-output strict mode only supports a narrow JSON-Schema subset
  (no `minItems`, and every property must be in `required`, which a
  pydantic field with a default is not). Quantity/shape checks
  (D7 caps, narration-span coverage, ladder ordering) live in each
  planner's own `validate()` callback instead, run by the shared
  `app/planners/repair.py` — call once, and on a violation, retry exactly
  once with the violation fed back into the prompt, then fail permanently
  (`settings.planner_max_repair_attempts`, default 1). Every attempt, repaired
  or not, is recorded as its own `llm_call` row.
- **Resumability goes one level deeper than M4.** `GenerateTimelineStep`
  checks the active Timeline's own content before each stage (empty
  `creative_context`/`music_plan` → run Director; empty `scenes` → run
  Scene Planner; any scene with no `shots` → run Shot Planner; any shot
  with no `asset_plan` → run Asset Planner) rather than tracking a
  separate progress flag — a crash between stages resumes at exactly the
  next one, proven in `tests/integration/test_generate_timeline_real.py`
  by killing a run after v3 (Scene Planner) and confirming a fresh run
  only re-invokes Shot + Asset Planner (Director/Scene Planner's
  `llm_call` rows don't double). **Known scope boundary:** this
  resumability is per-*stage*, not per-*scene* — a crash mid-Shot-Planner
  loop (scene 3 of 5 done) re-plans every scene in that stage on retry,
  since the stage only checkpoints once via one `append_version` after
  every scene succeeds.
- **`DRY_RUN=true` is unchanged**: `FakeTimelinePlanner` still fills the
  whole Timeline in one `append_version` call, gated on `settings.dry_run`
  inside `GenerateTimelineStep`. Real and fake paths share the same
  `is_satisfied`/constraint-validation code after the branch.
- 16 new tests (12 golden-file unit tests with a queued fake provider — no
  network — across all four planners, covering the happy path, the
  repair-then-succeed path, and the fail-after-one-repair path; 2
  integration tests proving the full real chain end-to-end and the
  crash-resume property above), all green; 34/34 tests total; ruff/black/mypy
  clean across 97 source files.

**Update (2026-08-15) — the first real, live, paid run of the full chain
found three real bugs**, none of which any golden-file test could have
caught (golden fixtures hand-craft the model's output; these bugs are all
about what the *real* model actually does):

1. **Cross-scene shot-id collisions.** The Shot Planner prompt's own
   example (`sh_01_01`, `sh_01_02`, ...) doesn't vary the scene number, and
   the model reproduced it literally for *every* scene — all five scenes
   in the first live run came back with shots named `sh_01_01`,
   `sh_01_02`, ... regardless of which scene it was. `Timeline.shot_ids()`
   correctly caught the resulting cross-scene duplicates at the very end
   of `GenerateTimelineStep.run()`, but only after all four planner stages
   (Director + Scene + 5× Shot + 5× Asset — ~12 real, paid OpenAI calls)
   had already completed. Fixed at the code layer rather than the prompt
   layer, since a prompt fix alone can't *guarantee* the model won't
   repeat this: `ShotPlanner` now namespaces every shot id by its scene's
   own id (`f"{scene_id}_{s.id}"`) in `_to_domain_shot`, which is
   structurally unique regardless of what the model returns, because
   `scene_id` is guaranteed unique (the Scene Planner plans every scene in
   one call and can see the whole list; the Shot Planner cannot).
2. **A resumability gap this exposed**: `GenerateTimelineStep.is_satisfied()`
   only checked structural completeness (every scene has shots, every
   shot has an `asset_plan`), not that the timeline actually *passes*
   `validate_constraints()`. A timeline that failed the constraint check
   once would look "satisfied" on a bare retry and the engine would skip
   `generate_timeline` entirely, carrying the broken timeline forward into
   asset resolution rather than failing loudly again. Fixed: `_is_fully_planned`
   now also runs `validate_constraints()`.
3. **`gpt-5.6-terra` (see below) rejects any `temperature` other than its
   fixed default (1.0)** with a 400 — `openai_provider.py` now tries the
   configured `openai_temperature` first and, on that specific
   `param=temperature, code=unsupported_value` error, retries once at the
   model's default rather than hard-failing every planner call on a
   reasoning-tier model. No model allowlist — this reacts to the error
   OpenAI itself reports, so it keeps working if the model changes again.

Separately, `openai_planning_model` moved from `gpt-4o` to `gpt-5.6-terra`
— `gpt-4o` is still callable (not deprecated) but is no longer OpenAI's
current tier; the newer model was chosen deliberately rather than staying
on a known-working default. `tests/unit/planners/test_shot_planner.py`'s
existing tests now assert the namespaced ids directly, including a
same-raw-id-across-scenes case proving cross-scene ids stay unique even
when the (simulated) model reuses the identical raw id in every scene —
exactly the failure mode the real model hit. 93/93 tests total green
after all of this session's fixes (3 net-new test functions — see M6
notes for where they landed).

**Update (2026-08-15) — a second occurrence of the same lesson: the Shot
Planner's narration-span outer boundaries.** A live paid run on a real
Hinglish script (mid-M8, well after this phase's own build window, but
the bug and its fix both belong here) hit `ShotPlanner` failing
permanently:

```
shot_planner output failed validation after 2 attempt(s):
["the last shot's narration_end (140) must equal the scene narration
  length (144) - every character must be covered"]
```

Scene `sc_04` was 144 characters, ending `'...bana rahi thi. '` (a
trailing space before the final full stop); the model's last shot
stopped 4 characters short of it, and the existing validator hard-failed
the entire run over it after both attempts. **This is the identical
mistake as the shot-id collision above**, not a new class of bug: a
value the calling code already knows deterministically (the first shot's
`narration_start` is always `0`; the last shot's `narration_end` is
always `len(scene.narration_text)` — neither is a creative decision) was
being demanded of the model byte-for-byte, and the whole project paid
for that imprecision with a hard failure.

**Fixed in code, not in the prompt** (a prompt fix cannot *guarantee* the
model won't be a few characters off again, the same reasoning that ruled
out a prompt-only fix for the shot-id collision): `app/planners/shot/
planner.py::_snap_narration_boundaries` corrects the first shot's
`narration_start` to `0` and the last shot's `narration_end` to the
scene's true length **before** validation runs, on every attempt.
Deliberately narrow — only those two OUTER edges are touched:

- Every other check still runs exactly as before, unmodified, on the
  (now boundary-corrected) shot list — a genuine gap or overlap between
  two INTERNAL shots is still a hard, immediate failure. Snapping the
  outer edges can only remove the one violation the model was never
  going to hit exactly; it cannot mask a real structural inconsistency
  anywhere else, because the internal tiling walk (`cursor`-based,
  shot-to-shot) never even looks at the two values that got snapped.
- **A snap is logged, not silent** — at `WARNING` if the drift exceeds
  `_LARGE_SNAP_THRESHOLD_CHARS = 10`, at `INFO` otherwise. The threshold
  sits strictly between the two observed scales: 4 characters (a
  trailing space — the real case above, imprecision, not
  misunderstanding) and 40 characters (the coordinator's own illustrative
  example of the model genuinely misreading where a scene ends) — a
  human watching the logs sees the difference between "routine" and
  "worth a look" without either one blocking the run.
- **Confirmed, not merely assumed**: a scene's trailing space cannot be
  double-counted or dropped at a scene boundary. `Shot.narration_span`
  indexes only into its OWN scene's `narration_text` — never a
  concatenation of scenes — and `app/timeline/narration_fit.py`
  (`_spoken_durations_for_scene`) independently re-derives and verifies
  exact tiling per scene at reconciliation time, raising `PermanentError`
  if a scene's shots don't cover it exactly or if `narration_text`'s
  length doesn't match its own alignment array's length. Both checks are
  entirely scene-local; there is no code path anywhere that indexes
  across a scene boundary, so a trailing space living inside one scene's
  own text has nowhere to leak into or out of.
- 4 new regression tests in `tests/unit/planners/test_shot_planner.py`:
  a short (4-character) end-boundary miss now succeeds on the FIRST
  attempt with no repair round; a genuine internal gap between two shots
  (with both outer boundaries already correct) still raises
  `PermanentError` after the repair round is exhausted; a large
  (15-character) miss still succeeds but logs exactly one `WARNING`; the
  same small miss logs at `INFO`, not `WARNING`, so routine corrections
  don't spam the logs. 308/308 tests total green (up from 304), run once
  in the foreground per the shared-test-DB discipline
  (running pytest twice concurrently truncates the same Postgres the
  live test run depends on — see the memory note this project already
  carries on that). `ruff check backend`, `black --check backend` (1
  file reformatted), `mypy backend/app` all clean from the repo root.
  Both fixtures reseeded afterward.

**The lesson, now cost twice**: a value that is a deterministic
consequence of data the calling code already has — a namespace prefix
that must be unique, a span boundary that must equal a known length — is
not a creative judgement, and validating it against the model's raw
output (rather than computing or correcting it directly) turns the
model's ordinary imprecision into a hard, expensive failure. The fix
belongs in code both times, not in a better-worded prompt.

**Update (2026-08-16) — a THIRD occurrence, and this time the fix is not
another patch: the Shot Planner stops asking for character offsets at
all.** A live run on a real Hinglish script (7 scenes, 21 shots, mixed
Devanagari/Latin) surfaced 6 of 21 shots with an INTERNAL boundary
landing mid-word or mid-grapheme-cluster:

```
sc_04_sh_02  ends   ...'Germany की war machine\nइ'   | next starts 'ससे बने fuel'
sc_04_sh_03  starts 'ससे बने fuel पर चल रही थी।\n\nL' | next starts 'euna-Werke'
sc_04_sh_04  starts 'euna-Werke जैसी factories\nद'   | next starts 'िन-रात fuel'
```

`Leuna-Werke` split into `L` + `euna-Werke` at its own internal hyphen.
`दिन` split into `द` + `िन` — separating a dependent Devanagari vowel
sign from its base consonant, which is not merely truncated text, it is
*malformed* text (a grapheme cluster is not the same kind of thing as a
word, and splitting one is a different, worse failure than splitting
the other).

**The first fix attempted — snapping each internal boundary to the
nearest legal word/grapheme boundary, extending `_snap_narration_
boundaries` the same way it already handles the two outer edges — was
built, then explicitly discarded before being committed.** The
coordinator's own correction, quoted because it is the actual decision
being recorded here: *"That is a patch on a bad interface... Models
cannot count characters reliably. That is not a prompt-quality problem
to be fixed with better instructions, and it is not a post-processing
problem to be fixed with better snapping. It is the wrong job for the
tool, and each patch has bought us one more round before the next
variant appears."* Look at the pattern this project had hit three
times by this point: a shot-id namespace collision, an outer-boundary
character miss, and now an internal-boundary character miss — every one
of them is a language model being asked to do character arithmetic,
and every fix so far had corrected the SYMPTOM (a wrong offset) rather
than removing the CAUSE (asking for an offset at all).

**The actual fix: the Shot Planner is no longer asked for
`narration_start`/`narration_end` character offsets.** New
`app/planners/shot/fragments.py::split_narration_fragments` splits a
scene's `narration_text` into an ordered list of numbered fragments,
deterministically, in code, before the model ever sees the scene. The
model is asked only for a CONTIGUOUS RANGE of fragment numbers per shot
("fragments 1 to 2" — a natural judgement, not an arithmetic one), and
`app/planners/shot/planner.py::_to_domain_shot` converts that range
back into the exact character span `Shot.narration_span` has always
stored. **Scope discipline honoured exactly as instructed**: nothing
downstream changed at all — not `Shot.narration_span`'s type, not
`narration_fit.py`, not the renderer, not any other planner. Only the
Shot Planner's own schema (`fragment_start`/`fragment_end` replacing
`narration_start`/`narration_end`), its prompt, its validator, and the
new fragment splitter were touched.

A mid-word or mid-grapheme split is now **structurally impossible**,
not detected and corrected: every fragment boundary is, by construction,
at a sentence end, a line break, or (for a long sentence) a clause
break — never inside a word, and never inside a grapheme cluster,
because a Devanagari dependent vowel sign never immediately follows
whitespace or sentence-ending punctuation. Devanagari needed no
special-case code anywhere in the splitter, which is itself evidence
this is the right fix rather than a fourth patch.

**Fragment granularity — argued, not assumed:**
- **Primary split points: sentence-ending punctuation (`.` `!` `?` the
  Devanagari danda `।` `…`) and newlines.** The user's own scripts are
  written as short lines, so a newline is already a natural,
  human-authored fragment boundary, not an invented rule.
- **Secondary split points — comma, semicolon, colon, the em dash
  `—` — apply ONLY inside a fragment still longer than
  `_LONG_FRAGMENT_THRESHOLD_CHARS = 80` after the primary pass.**
  Deliberately not the default: splitting on every comma would put
  fragment granularity right back to "arbitrary boundaries", one notch
  coarser than character offsets but the same failure. It exists only
  for the opposite risk — one very long run-on sentence that would
  otherwise be a single un-subdividable fragment, forcing every shot
  touching it to include the whole sentence regardless of how long that
  makes the shot. 80 characters is a judgement call between those two
  risks, recorded as one, not derived.
- **The plain hyphen `-` is deliberately excluded from every split set,
  at either pass.** It is what let `Leuna-Werke` split in the first
  place; a compound/hyphenated name must stay whole. The em dash `—`
  (a different character, U+2014 vs U+002D) is a legitimate secondary
  break.
- **"A scene cannot have more shots than fragments" is not a new rule —
  it falls out for free** from the same "fragment ranges tile 1..N with
  no gap or overlap" invariant every other structural check already
  needs: it is arithmetically impossible for more non-empty disjoint
  ranges to exist than there are fragments to distribute them over. A
  model that proposes more shots than a scene has fragments fails the
  identical validation every other tiling violation already fails, fed
  back for repair the same way — not new machinery. The prompt tells
  the model the fragment count up front, so this is a rare repair, not
  the common path. **Decided and tested for the edge case explicitly**:
  a one-fragment scene with a correct single shot succeeds cleanly; a
  one-fragment scene where the model insists on two shots fails (in
  practice, because the outer-edge snap has already forced the second
  shot's `fragment_end` down to the true count of 1, the actual
  violation that surfaces is `fragment_end < fragment_start` on that
  same shot — a different message than "count exceeded" but the
  identical rejection; a second, dedicated test proves the "exceeds this
  scene's fragment count" message directly, on a middle shot the outer
  snap never touches).
- **Lossless reconstruction is structural, not a separate check**: every
  fragment's span is `[start, next_fragment.start)` (or `len(text)` for
  the last), never a separately-tracked gap — concatenating every
  fragment's own span always reproduces `narration_text` exactly,
  including all whitespace, which is what the Scene Planner's own
  verbatim-script check ultimately depends on staying true.
- **The outer-edge snap (`_snap_narration_boundaries`'s successor,
  `_snap_fragment_boundaries`) is kept, exactly as instructed** — "it
  costs nothing, and it still defends against a malformed range" — now
  operating on fragment indices (small integers) rather than character
  offsets, with its own rescaled threshold
  (`_LARGE_FRAGMENT_SNAP_THRESHOLD = 1`: a drift of 1 fragment is an
  off-by-one about an inclusive range; 2 or more suggests the model
  misread the fragment list).

**Verified directly against the real reported bug text, live and pure
(no database, no model, no pytest)**: the exact scene from the bug
report — `"Germany की war machine\nइससे बने fuel पर चल रही थी।\n\n
Leuna-Werke जैसी factories\nदिन-रात fuel बना रही थीं।"` — was run
through the real `split_narration_fragments` and produced exactly the
four natural, newline-delimited fragments, splitting neither
`Leuna-Werke` nor `इससे` nor `दिन`, with lossless reconstruction
confirmed by direct string equality. The planner's own validator was
also exercised directly (not reimplemented) against every scenario in
the test suite below, confirming the traced violation messages before
trusting the test assertions — including the two-attempts-at-tracing
correction on the one-fragment/two-shot case, where the FIRST guess at
the resulting error message was wrong (assumed "exceeds fragment count",
actually "fragment_end < fragment_start", because the outer snap fires
first) and was caught by running the real code rather than reasoning
about it in the abstract.

New `tests/unit/planners/test_fragments.py` (9 cases: lossless
reconstruction across five texts, the Latin hyphenated-name case, the
Devanagari grapheme case, the exact reported bug scene, the long
run-on-sentence subdivision, the short-sentence-stays-whole case, and
the ellipsis/em-dash-plus-newline "leave it alone" case).
`tests/unit/planners/test_shot_planner.py` rewritten for the new schema
(fragment-index drift snaps, a genuine internal gap still failing, the
one-fragment edge case both ways, the existing happy-path/looping/
shot-cap tests). `tests/integration/test_generate_timeline_real.py`'s
own canned fixture reduced from two shots to one per scene (each of its
two scenes is a single plain sentence — exactly one fragment — so two
shots was never valid under the new rule; the test's own purpose, the
four-planner chain's crash-resumability, is unaffected by shot count).
`ruff check backend`, `black --check backend` (1 file reformatted),
`mypy backend/app` all clean from the repo root. **The suite itself was
NOT run** — two live, human-driven projects (`194ad0e7-...`, rendered,
13 irreplaceable uploads; `2fa282b4-...`, at the approval gate) sit in
the same shared dev Postgres, and `pytest` truncates every table via
`tests/conftest.py`'s autouse `clean_database` fixture.

**The lesson, now cost three times, and this time answered differently
than the first two**: the first two fixes corrected a wrong VALUE after
the fact (snap the offset to what it must be). The third time, the
right question turned out to be prior to that — not "how do we correct
this model's arithmetic" but "should this have been arithmetic at all."
Once character offsets were replaced with a judgement a model is
actually good at (grouping natural, pre-cut fragments), the whole class
of failure — mid-word, mid-grapheme, off-by-some-characters — stopped
being a thing to detect and correct, because it stopped being
representable in the schema at all. Deterministic structural facts
belong in code; and when a model keeps getting the same KIND of thing
wrong across multiple unrelated incidents, the question worth asking
is not "how do we validate this better" but "was this the right thing
to ask a model for in the first place."

**Update (2026-08-16) — the redesign verified live, and it surfaced one
small second-order defect, fixed the same day.** A fresh real plan on
the same script (project `f64210fc-...`, 7 scenes, 24 shots) confirmed
the fix directly: **0 of 24 shots have a boundary inside a word**, down
from 6 of 21 on the previous (character-offset) plan of the identical
script — `Leuna-Werke`, `इससे`, `दिन`, `Fischer-Tropsch`, and `Secunda`
all stayed intact, and `Leuna-Werke जैसी factories` is now one whole
shot where the old design produced `L` + `euna-Werke`.

That same run turned up a defect the redesign itself introduced: the
user's script has blank lines between stanzas, and the Scene Planner's
own verbatim check means that whitespace has to live somewhere - it
lands at the front of whichever scene comes next. The splitter emitted
that leading blank run as its OWN fragment, and the Shot Planner -
correctly following its own instructions to assign every fragment to a
shot - gave it one: 2 of 24 shots had narration consisting entirely of
blank lines, still charged a real image, a Ken Burns move, and a slice
of the video's duration (3 of 48 seconds) for a beat of silence.

**Fixed by merging, never discarding**: `app/planners/shot/fragments.py`
gained a post-processing pass (`_merge_whitespace_only_spans`) that
folds any fragment whose content is entirely whitespace into an
adjacent one - forward (into the fragment that follows) by default,
backward only if the whitespace-only fragment is the last one with no
successor. Merging removes the BOUNDARY between two fragments, never
either fragment's characters, so tiling and lossless reconstruction
both continue to hold without any special-casing - exactly the same
"spans are `[start, next-start)`, never a tracked gap" property the
rest of this module already rests on. Fragments are renumbered 1..N
afterward, since merging always changes how many exist. **In practice,
only the very first fragment can ever be whitespace-only** (every other
split point the splitter finds is defined by skipping FORWARD to the
next non-whitespace character, so every fragment but the first already
starts on real content) - the "backward if last" branch is kept for
genuine robustness against a future change to the splitting passes, not
because it is reachable today; a dedicated test pins down the actual,
simpler behaviour (trailing whitespace is absorbed into the previous
fragment's own span, never promoted to a new one) rather than merely
asserting the backward branch is unreachable.

**The degenerate case - a scene whose narration is entirely whitespace -
is left as a single whitespace-only fragment, decided explicitly**:
there is nothing else in the scene to merge it into, and a scene with
zero real narration content at all is a planning-level defect somewhere
upstream, not something this module can fix by inventing words. Verified
live and pure (no database, no model, no pytest) against the exact two
reported scenes before writing the tests: `sc_03` (`"\n\nइसका नाम था
Fischer-Tropsch process.\n\n1925 में invent हुआ,"`, a 3-fragment scene
with a leading blank fragment) now produces exactly 2 fragments, neither
blank; `sc_05` (`"\n\nअब यहाँ twist है।"`, a 2-fragment scene) now
produces exactly 1, the blank run merged into the scene's one real
sentence. 6 new tests in `tests/unit/planners/test_fragments.py`: the
two exact reported scenes, a middle-of-text blank run merging forward,
the trailing-whitespace-is-already-absorbed case, and both degenerate
inputs (all-whitespace and empty). Scoped exactly as instructed - the
Shot Planner's own prompt and schema were not touched, only which
fragments the splitter emits. `ruff check backend`, `black --check
backend`, `mypy backend/app` all clean from the repo root. **The suite
was NOT run** - three live projects (`194ad0e7-...`, `2fa282b4-...`,
`f64210fc-...`) now sit in the same shared dev Postgres.

---

# Phase M6 — Asset Pipeline

> **Goal:** real search, real ranking, real downloads. Rungs 1–4 of the ladder.

## Order

Local project assets → Wikimedia → Pexels → generic public domain.

## Advice

- **Licence checking is a hard gate, not a ranking factor.** An asset whose licence is not in `asset_plan.licence_requirements` is *discarded*, never ranked low. This is a legal exposure, and it is the one place where a `PermanentError` is the right answer.
- **Store provenance at download time**: `source_url`, `licence`, `author`, `attribution_text`, `retrieved_at`. You cannot reconstruct this later, and CC-BY requires it in the output.
- **Make ranking explicit and weighted, in one function.**
  ```python
  score = (w_relevance * relevance      # text/semantic match to query
         + w_quality   * quality        # resolution, aspect fit, sharpness
         + w_period    * period_match   # era accuracy for historical content
         + w_licence   * licence_score  # PD > CC0 > CC-BY
         - w_reuse     * already_used)  # penalise repeats — Philosophy Principle 10
  ```
  Log the component scores for the top 5 candidates. When someone asks "why did it pick that photo?", the answer must be in the logs.
- **Penalise reuse within a project.** [Principle 10](00_Creative_Philosophy.md) demands visual variety. Without an explicit penalty, the same high-scoring archive photo appears in six shots.
- **Dedupe by content hash before ranking**, not after — the same image arrives from multiple providers with different URLs.
- **Cache aggressively and cache the miss too.** Remembering "this query returned nothing useful" prevents repeated round-trips on every re-run.
- **Sanitise every downloaded filename.** Provider-supplied names are attacker-controlled input; path traversal is trivial otherwise. Store by `content_hash`, keep the original name as metadata only.
- **Validate what you downloaded.** Content-type, magic bytes, dimensions, and a size cap. A 400 MB TIFF or an HTML error page saved as `.jpg` will blow up FFmpeg in M8 with an incomprehensible error.
- **Respect rate limits and set a real User-Agent.** Wikimedia will block you otherwise, and their API terms require it.
- **Search runs before approval, generation does not** ([I6](#i6--nothing-expensive-runs-before-approval)). Resolving assets early makes the approval screen far more useful — the user sees actual photos, not just prompts.

## Done when

- [x] A historical script resolves the majority of shots from archives without generating anything
- [x] Every stored asset has complete provenance and passes the licence gate
- [x] Ranking decisions are explainable from logs
- [x] Re-running resolution is free (cache hits) and produces identical results

## Implementation notes (2026-08-14)

Built rungs 2 (`historical_search`) and 4 (`stock_search`) for real —
**Wikimedia Commons** (`app/providers/wikimedia.py`, no API key, User-Agent
required by their terms) and **Pexels** (`app/providers/pexels.py`,
`PEXELS_API_KEY`). Rung 3 (`public_domain`) is served by the *same*
Wikimedia provider under a second registration - Commons genuinely hosts
both historical archives and general public-domain media, so a separate
client would just duplicate the same HTTP logic. Rung 1 (`project_assets`)
is a real, wired-in class (`app/providers/local_assets.py`) that always
returns no candidates - there is no project-asset upload endpoint yet, so
this is an honest stub, not a TODO comment; adding upload later is a
change to that one file, not to the ladder logic.

- **`ResolveAssetsStep` now walks the shot's full `asset_plan.fallback_chain`**
  in DRY_RUN=false mode, trying each search rung in ladder order until one
  yields a licence-passing candidate - a real change from the DRY_RUN path
  (unchanged since M4), which only ever tries the shot's primary strategy
  once, because `FakeAssetProvider` always finds something.
- **The licence gate discards, never deprioritises** - a candidate whose
  licence isn't in the shot's `licence_requirements` never reaches ranking.
- **Dedup by content hash happens before ranking**: up to 5 candidates per
  rung are fetched and hashed, exact-duplicate hashes collapse to one
  entry, and a hash matching an asset already stored for the project
  short-circuits straight to reuse (no re-download, no re-ranking).
- **`app/assets/ranking.py`** is the one explicit, weighted scoring
  function from the guide's formula (relevance/quality/period-match/
  licence/reuse-penalty), logging the top-5 candidates' component scores
  on every call - answering "why did it pick that photo?" from logs alone.
  The reuse penalty (0.4) is deliberately larger than any single other
  component's swing (≤0.35), so a within-project-reused image never wins
  against any genuinely different alternative, proven directly in tests.
- **`app/assets/validation.py`** verifies magic bytes via Pillow (not the
  provider's declared content-type or a file extension - both are
  provider-controlled input) and enforces `MAX_DOWNLOAD_BYTES`; a
  candidate that fails validation is skipped in favour of the next-ranked
  one in the same rung, not an immediate shot failure.
- **Known gap vs. this phase's own advice**: real search still runs where
  M4 placed `resolve_assets` - *after* the approval gate, not before it.
  Moving search ahead of approval (so the approval screen shows resolved
  photos instead of just prompts) is a pipeline-ordering change bigger
  than this phase's asset-search scope and is deferred, not silently
  dropped.
- Both HTTP providers accept an injectable `httpx.AsyncBaseTransport` for
  testing (`httpx.MockTransport`) - real request/response/error-mapping
  code is exercised with zero network calls, real-API testing is a
  separate, manually-triggered concern per the Testing Strategy.
- 27 new tests (12 provider tests via `MockTransport`, 13 pure-function
  ranking/validation tests, 5 `resolve_assets` integration tests covering
  the licence gate, dedup, reuse penalty, provenance completeness, and the
  generation fallback), 61/62 total green - the one failure is the
  pre-existing FFmpeg-dependent e2e render step, unrelated to this phase
  (FFmpeg not on PATH in the dev shell, not a code regression);
  ruff/black/mypy clean across 111 source files.

**Update (2026-08-15) — the first real, live, paid run resolved almost
nothing from real archives** (12 of 13 shots on a WWII/apartheid-history
script fell through to AI generation), which prompted a live investigation
against the actual Wikimedia and Pexels APIs (not guessed) that found two
separate, compounding bugs:

1. **Search queries were too long to match anything, whether joined or
   not.** `WikimediaAssetProvider.search()` and `PexelsAssetProvider.search()`
   both did `" ".join(query.search_terms)`, concatenating the Asset
   Planner's 3-4 distinct candidate queries per shot into one 30-40-word
   mega-string. Splitting that concatenation alone turned out **not** to
   fix it: tested live against the real Commons API, even a single
   isolated 9-word sentence like *"Germany coal hydrogenation plant 1940
   workers pipes pressure vessels"* returned **zero** results, while the
   2-word keyword query *"coal hydrogenation"* returned five real, on-topic
   archival photos — including one from 1946. The archival material
   genuinely exists; the query *style* just never had a chance to find it.
   Commons' (and, more forgivingly, Pexels') full-text search matches
   short, title-like keyword phrases, not natural-language descriptions,
   however accurate. Fixed at both the prompt layer
   (`app/prompts/asset_planner/v1.md` now requires 2-5 word keyword
   queries with worked good/bad examples) and the validation layer
   (`AssetPlanner`'s validator now rejects any query over 6 words and
   triggers the repair loop — prompt wording alone wasn't trusted after
   the M5 shot-id lesson). The provider fix (each query tried as its own
   request, results merged and deduped by id, never concatenated) landed
   too, since a query that's short *and* joined with others just
   recreates the same failure at a smaller scale.
2. **A distinct, unrelated bug the query fix uncovered**: once queries
   actually matched real files, every single *download* (not search) 403'd.
   Tested live: the exact literal `WIKIMEDIA_USER_AGENT` placeholder from
   `.env.example` (`VideoGenerationEngine/0.1 (https://example.com;
   you@example.com)`) is blocklisted by Wikimedia's media CDN
   (`upload.wikimedia.org`) specifically — a *different* request path from
   the search API (`commons.wikimedia.org/w/api.php`), which tolerates it
   fine, which is exactly why every search had been succeeding while every
   fetch silently failed. A real contact value in `.env` resolved it
   immediately (verified with a direct `curl` before touching any code).
   This phase's own Advice section already said "set a real User-Agent,
   Wikimedia will block you otherwise" — true, just not in the way anyone
   expected before hitting it for real.

Net effect on the same script, replayed with the corrected queries: 13/13
shots resolved from real Wikimedia archives, 0 AI-generated, $0 spent (vs.
12/13 AI-generated, $0.36 spent, before the fix). 3 new tests (one per
provider proving separate-not-joined requests plus dedup; one on
`AssetPlanner` proving a sentence-length query gets rejected and repaired).
93/93 tests total green across the whole backend.

---

# Phase M6.5 — Asset Quality and Supervision

> **Goal:** make asset acquisition produce media that actually matches the script, and put a human in front of that step while fixing it is still free.
>
> **Status:** designed 2026-08-15 from two real runs. Sequenced after M8 steps 1–3 (narration, done) and interleaved with M8 steps 4–6. **All 5 build-order steps done as of 2026-08-15** - see the Build order and Done-when sections below and each step's own Implementation notes.

## Why this phase exists — the measured evidence

M6 declared success on "a historical script resolves the majority of shots from archives." It does resolve them. It resolves them to the **wrong things**, and no test caught it because every test asserted mechanism (a licence gate fires, a hash dedupes) rather than outcome (is this a picture of the thing we asked for).

Two real runs, hand-graded:

| run | shots | genuinely correct |
|---|---|---|
| Hindi run, as built | 11 | **2** |
| after the relevance gate (`1aa22d3`) | 11 | **3** |

The original failures were not near-misses. `Germany oil map 1942` returned a crucifixion painting; `South Africa oil embargo` returned a map of South **America**; `German oil depot 1940` returned a Dutch painting of ships in a storm. The relevance gate removed all of those, but the residue is still wrong — a Polish coal elevator for Leuna-Werke, a modern British freight train for a 1940 Ruhr rail yard, a museum **diorama** standing in for wartime footage.

## The two diagnoses

**1. The problem is retrieval, not ranking.** Ranking can only reorder what the provider returned. Commons search is MediaWiki full-text search over file-page wikitext — it answers "which pages contain these words", not "which image depicts this concept". When the right photograph never enters the candidate set, no gate conjures it. Every fix aimed at scoring is polishing the wrong end of the pipe.

Worse, the current design throws away the one asset we already have: **the planner knows the answer and we never ask it.** The model knows the plant is Leuna-Werke, the process is Fischer–Tropsch, the company is Sasol. We flatten that knowledge into a keyword string and hand it to a keyword matcher. The only two correct results in the first run were correct precisely because a distinctive proper noun survived that flattening.

**2. The approval gate guards the cheap step and leaves the risky one unsupervised.** A human approves a *plan* — text, read in seconds, ~$0.40 to redo. Then acquisition, the step that actually determines whether the video is watchable, runs unwatched, and the failure is discovered only after narration and rendering have been paid for. There is exactly one gate and it sits before the part that goes wrong.

## Decisions — all closed (2026-08-15)

| ID | Decision | Rationale |
|---|---|---|
| **A1** | **The Asset Planner emits a named `entity` alongside `search_queries`.** | Naming an entity is world knowledge, which only the model has. It costs nothing extra — one more field in a call already being made. |
| **A2** | **Entity → images is resolved by deterministic code (Wikipedia article images, Commons categories), never by an LLM tool call.** | A lookup is not a judgement. Article images are curated by humans to illustrate that exact topic — relevance for free, no inference cost. |
| **A3** | **Planners do NOT get search tools. I4 stands.** | Tool-calling would fix planner blindness but costs replayability, testability and cost-bounding, at 3–10× planning spend. Revisit only if A1–A2 plus supervision prove insufficient — decide on evidence, not appetite. |
| **A4** | **Where a bounded feedback loop is needed, reuse the existing repair pattern** (`run_structured_with_repair`): resolve, feed failures back, re-plan those shots once. | Keeps planners pure (they only see text handed to them), bounds cost to one extra pass, ~70% of tool-calling's benefit for ~10% of the disruption. |
| **A5** | **Free retrieval (uploads, Wikimedia, Pexels) moves BEFORE the approval gate.** | I6 forbids anything *expensive* before approval; search is free. This is what makes the unsupervised step supervised, at the moment fixing it still costs nothing. |
| **A6** | **Generation stays AFTER approval.** | It costs real money (I6). At approval you see real photos for what was found and an explicit "will be generated" marker for what wasn't — and can still upload instead. |
| **A7** | **Post-approval order is narrate → generate → render.** | Narration is cheap (~9¢) and is what validates real duration. A script that blows the 90s cap must fail there, before dollars of generation are spent on a video that cannot ship. |
| **A8** | **User-supplied assets are optional, uploaded with the script, and become ladder rung 1.** | `project_assets` already exists as a wired stub. A human-chosen image is *guaranteed* relevant — no gate, no vision model, no retrieval lottery. |
| **A9** | **An uploaded image becomes a `ShotBinding`; the shot's `prompt` is left unchanged as creative intent.** | I2 — the Timeline holds decisions, never media. The prompt's job was to drive acquisition, which is now settled. |
| **A10** | **A human override is recorded as an `append_version` with `produced_by=HUMAN`, marking that shot's asset locked.** | Without it, any later re-resolution silently discards the human's choice — the worst possible failure for a curation feature. Also makes provenance auditable. |
| **A11** | **`ShotBinding` rows must carry forward across a version bump that does not change shot identity.** | Prerequisite for A5/A10. Bindings are keyed by `(project_id, timeline_version, shot_id)`, so appending a version orphans them — which would silently eat exactly the curation this phase exists to enable. |
| **A12** | **The Director's `constraints` are enforced at generation time by a vision check.** | The Director already writes "no AI-generated faces of real historical figures" and "avoid Nazi symbols except where historically necessary". Nothing enforces them today. This is the one gap here about *harm* rather than quality. |
| **A13** | **Regeneration is bounded at 2 attempts: revised prompt first, varied seed second (derived from the project seed, never random).** | "A retry bug against a paid video API is the most expensive failure mode this system has." Varying the seed trades away the fixed-per-project stylistic consistency M7 chose deliberately, so it is the second lever, not the first. |
| **A14** | **After bounded retries, a shot is surfaced for human input — never silently shipped, never looped.** | Generation is the bottom rung; below it is only a placeholder. The terminal fallback is a person. |
| **A15** | **Human review of generated media is by exception**, via a conditional second gate, not an unconditional stop. | The engine already supports a step returning `awaiting_approval`. Interrupt only when an automated check fails. |
| **A16** | **Vision verification of *searched* assets is deferred until A1–A2 are measured.** | It would be checking a much better candidate pool by then, and the residue may not justify the cost. Decide with evidence. |
| **A17** | **The 11 Hindi shots (`tests/fixtures/hindi_test_project.json`) are the standing benchmark** for any retrieval change. | Wikipedia and Commons are free to query, so retrieval changes can be measured against real shots at zero cost. Baseline: 2/11 as built, 3/11 after the relevance gate. Move that number. |
| **A18** | **The A13 "revised prompt" is a deterministic append of the violated constraint as an explicit negative directive — not a second LLM call to rewrite the prompt.** | A rewrite call costs money and latency on the *failure* path, and makes the retry non-replayable. The vision check already returns *which* constraint was violated in text; appending it as a negative is testable, free, and is the same information a rewrite would have used. Revisit if a measured run shows appends failing to change the output. |
| **A19** | **Step 2 marks a constraint-violating shot failed and surfaces it; the A15 conditional approval gate lands in step 4, not here.** | A gate is only useful if the human has a remedy, and the remedy is the upload endpoint (A8), which does not exist until step 4. Gating earlier would halt runs with no way to unblock them. Until then the shot degrades to a placeholder — visible, never silently shipped (A14), and the render still completes (M7). |
| **A20** | **A11's carry-forward is per-shot, not per-timeline: a binding carries to the new version when that `shot_id` still exists AND the shot's acquisition-relevant fields (`prompt`, `asset_plan`) are byte-identical. Otherwise it is dropped and that shot re-resolves.** | All-or-nothing carry-forward is wrong in both directions. Narration only changes durations, so every binding is still valid and dropping them would re-run acquisition for nothing. A re-plan can change a shot's `prompt`, and carrying a binding across that change would silently serve an asset acquired for a question no longer being asked. Keying on the fields acquisition actually consumed is the only rule that is right in both cases. |
| **A21** | **The two acquisition passes are one `ResolveAssetsStep` parameterised by which ladder rungs it may use, instantiated twice with distinct step names — not two step classes.** | The ladder walk, relevance gate, licence gate, hash dedup, budget checks and per-shot failure isolation are all shared. Two classes would duplicate that and drift; the difference between the passes is genuinely one thing — which rungs are permitted (1–4 free before approval, 5–6 paid after). `is_satisfied` must be pass-specific, since "search finished" and "generation finished" are different questions. |
| **A22** | **A total failure of the pre-approval search pass never blocks the approval gate.** | Search is best-effort and rungs 1–4 are third-party services that go down. If Wikimedia is unreachable the human should still reach the gate, see that nothing was found, and decide — upload, approve anyway and let generation fill the gaps, or abandon. A network outage that makes a project unapprovable would be a worse failure than the empty result it is reporting. |
| **A23** | **An upload supplied with the script carries a short human-written description, and is matched to shots by the existing rung-1 provider through the same relevance gate as any other candidate — not by a planner.** | A3 stands: planners get no tools and no visibility into the asset pool. The matching machinery already exists and is already measured by A17; reusing it means an upload competes on the same terms as a search result and needs no new scoring path. The description is what makes that possible — matching against a filename would be worthless. |
| **A24** | **A per-shot override names its `shot_id` explicitly and bypasses relevance and licence gates entirely.** | A human pointing at a specific shot has already made the judgement those gates exist to approximate. Re-scoring it would let an automated heuristic overrule a person, which is the exact inversion this phase is correcting. Distinct from A23, where an upload arrives before shots exist and must be matched. |
| **A25** | **A human override sets `asset_locked` on that Shot via an `append_version` with `produced_by=HUMAN`. A locked Shot is exempt from A20 — its binding carries forward unconditionally — AND every later planner pass must preserve that Shot's `prompt` and `asset_plan` verbatim instead of overwriting them.** | Decided by the user, 2026-08-15: "lock wins, my photo is always in the plan, and the plan should include it in the shot." This is a direct conflict with A20 and the lock must win — A20 drops a binding when acquisition-relevant fields change, which is right for machine-acquired assets and catastrophic for human-chosen ones. The second half is what makes "always in the plan" literally rather than approximately true: if a re-plan cannot rewrite a locked Shot's prompt, the plan can never drift away from the image the human chose, so the mismatch that would otherwise need flagging at the gate cannot arise at all. Putting the flag on the Shot rather than only on the binding keeps it in the immutable decision record (I1/I2 — "this shot's asset is locked" is a decision, not media) and makes the override auditable. |
| **A26** | **The A15 gate fires after the generation pass whenever any shot ended `failed`, and has exactly ONE exit: resolve every failed shot. There is no "proceed anyway". A project cannot reach `completed` while any shot is failed.** | Decided by the user, 2026-08-15: "you should not be able to finish a video if we can't fix it." A button that ships a visibly broken video gets clicked reflexively, and generated media is the least reliable rung — the one most likely to be the thing failing. ~~This is not a deadlock: the remedy is always available, because a per-shot upload (A24) bypasses every gate and always resolves.~~ **CORRECTED 2026-08-16 — this claim was wrong, and a live project proved it**: the override mechanism itself always resolves the FAILED SHOT, but the remedy path re-enters general Timeline validation (`GenerateTimelineStep`/`validate_constraints`), which independently rejected narration-measured shot durations the remedy's own version never claimed to produce — a genuine deadlock, not a hypothetical one. See "Constraint validation split" below for the fix (a persistent `narration_locked` flag) and the honest accounting of why "the mechanism resolves it" was not the same claim as "nothing downstream can still reject it." **Consequence, accepted deliberately:** an unattended run halts until a human acts, and a project with one unfixable shot stays unfinished rather than shipping with a placeholder. This overrides M7's "a 59-shot video with one gap is more useful than no video" **at the project level only** — per-shot isolation still holds during a pass (one shot failing never aborts the others), and the renderer still degrades gracefully; what changes is that the project is not marked complete. |
| **A27** | **Uploaded bytes are validated and hashed on arrival, and stored under the project like any other asset.** | An upload is untrusted input reaching the renderer. It goes through the same `validate_and_identify_image` path that every searched asset already does — a file that claims to be a PNG and isn't must fail at the endpoint, not inside ffmpeg during the render. Hashing also makes it participate in the existing dedup. |
| **A28** | **The A26 review gate gets its own project status, distinct from the plan-approval gate, and sits BEFORE render.** | A human arriving at a stopped project must be able to tell "approve this plan" from "fix these failed shots" — they are different questions with different remedies, and one status for both makes the API ambiguous. Placing it before render means a failed shot never renders a placeholder at all, so nothing half-finished lands on disk. |
| **A25a** | **A25's "preserve verbatim" is implemented as *reject loudly*: `append_version` raises if any later version changes a locked Shot's `prompt`/`asset_plan`, rather than silently substituting the old values.** | Deviation from A25's wording, accepted deliberately. Silently preserving means a re-plan appears to succeed while quietly ignoring part of its own output — the kind of divergence that is discovered months later. Rejecting is unreachable today (no code path re-plans after an override: `GenerateTimelineStep.is_satisfied` short-circuits once planned, and narration changes only durations), so it costs nothing now and forces whoever builds re-planning to confront the question. **Known gap:** there is no unlock endpoint, so a shot locked by an override cannot currently be handed back to the planner. Add one when re-planning arrives, not before. |
| **A30** | **A16 is resolved YES, but narrowly: vision-verify only the TOP-ranked candidate per shot, and only when no entity-curated candidate won. One vision call per shot, maximum. A failure drops the candidate and the shot falls through the ladder.** | Decided against the evidence A16 asked for. Vision verification cannot conjure a better photograph — the 7 remaining failures are shots whose candidate pool contains nothing on-topic — so its value is **not** better retrieval. Its value is *detecting that the best thing found is still wrong*, so the shot falls through to generation or to the human instead of confidently displaying a Polish coal elevator for Leuna-Werke. That reframing is what makes it worth doing now: it converts a silent wrong answer into an honest miss. Scoped to the top candidate only because verifying a whole pool multiplies cost for no extra signal, and skipped for entity-curated candidates because a human already curated those (A2). Re-measure against A17 after. |
| **A30a** | **A30's depiction check asks a question the model can actually answer: "could this plausibly illustrate the subject?", rejecting only confident mismatches — never "is this specifically Leuna-Werke?"** | Measured correction, 2026-08-15. A30 as first built cut the search pass from 8/11 resolved to 1/11: it removed all 5 unambiguously wrong picks (a Greek topographic map, 2016 reenactor photos, a burning ship, a Polish coal elevator) **but also dropped 2 genuinely correct ones** — a real Bundesarchiv Leuna photograph and a real Fischer–Tropsch diagram — because nothing in the pixels can confirm a specific named subject. That is an unanswerable question: one chemical plant looks like another, and the identity lives in the archive's catalogue metadata, which the model cannot see. Asking it anyway converts trustworthy Bundesarchiv provenance into a rejection. Calibrate to reject what is *confidently* something else, and let unverifiable specifics pass — the catalogue is the authority on identity, the pixels are the authority on subject matter. |
| **A29** | **An override changes only the binding and `asset_locked`. It never changes `prompt`, `duration_s`, narration text, framing, camera, or transitions.** | Narration is the master clock (D1) — durations are derived from real spoken audio to the millisecond. If an upload could change a shot's duration, every later shot would shift and the audio would need re-synthesising, turning a free, instant swap into a paid re-narration. Decoupling "which picture" from "how long" is what makes curation cheap. A shot that genuinely needs different timing is a separate edit, behind its own decision. |

## Known gap, not yet scheduled

**Real video footage is never searched for.** `WikimediaAssetProvider` hardcodes `filetype:bitmap`, and the Pexels provider uses the photos endpoint, not `/videos/search`. So although a shot can declare `preferred_type: video`, every search rung can only return a still, and the *only* route to motion is generating it. For a WWII documentary that is backwards — genuine archival film exists on Commons and is better material than any generated clip.

Preference order for motion, once this is addressed: **real archival footage > Ken Burns on a real photograph (M8 step 5) > generated video.** Generated video is where synthetic artefacts are most visible, at roughly 12× the cost of an image (~50¢ vs ~4¢).

## Build order

1. ~~**Entity retrieval (A1, A2), measured against the A17 benchmark.**~~ **Done** (`86d42e1`). Cheapest, needs no UI, improves quality automatically. Its result determines how much burden steps 3–4 must carry.
2. ~~**Director-constraint enforcement at generation (A12, A13, A14).**~~ **Done** (`11ad0aa`). Small, and the only harm-relevant item here.
3. ~~**Pipeline reorder (A5, A7) plus binding carry-forward (A11).**~~ **Done** (this step, A20-A22 closing the design questions it raised). The structural change that makes the step supervised.
4. ~~**Upload endpoint and per-shot override (A8, A9, A10, A15).**~~ **Done** (this step, A23-A29 closing the design questions it raised). The remedy that makes the review gate a gate rather than a dead end.
5. ~~**Reassess vision verification for search (A16)** against whatever failures actually remain.~~ **Done** (A16 resolved narrowly as A30). See this phase's Implementation notes for the measured result.

**All five steps of this phase are now done.**

**Caveat:** there is no frontend — M9 has not been built. "You see the images at approval" means, for now, an API exposing the resolved asset per shot plus files on disk. The full experience needs M9; the backend reordering is still worth doing first, so M9 is not built against the wrong pipeline shape.

## Done when

- [x] The A17 benchmark improves substantially and is re-measured after every retrieval change — **re-measured for step 5 (A30), then again for A30a's recalibration — now ticked: the recalibration hits both targets the coordinator set, measured, not asserted.** Steps 1-4: 2 correct + 2 partial → 4 correct + 1 partial → unchanged through step 4 (see each step's own notes). Step 5 (A30, vision-verify the top searched candidate): re-measured live against the real Hindi fixture with a real, isolated control run (identical code, vision check forced to always pass) to separate A30's own marginal effect from everything else. **Control (no depiction check): 8/11 shots resolve via free-text search** - hand-graded against the real downloaded images: 1 unambiguously correct (Sasol Secunda), 2 defensible/partial (a genuine Fischer-Tropsch process diagram; a real Bundesarchiv Leuna photo), 5 unambiguously WRONG (a Greek topographic map for a "German coalfields map" query, modern 2016 WWII-reenactors-on-motorcycles for "German tanks", a burning torpedoed ship for a "resource map", a derelict Polish coal elevator for the Leuna hydrogenation plant, generic modern depot buildings with no visible tanks for "oil storage tanks"). **With A30 (round 1, as originally built): 1/11 resolves** (Sasol only) - it correctly dropped all 5 unambiguously-wrong candidates, but ALSO dropped both defensible ones, because nothing in the PIXELS themselves visually confirms a specific named subject - a real, principled limitation of vision-only verification, not an arbitrary model error. **Net effect of A30 alone: -2 to -3 in raw correct-count, -5 in confidently-wrong-and-shipped** - this is what motivated A30a's recalibration (see that phase's own Implementation notes, immediately below the step-5 notes, for the full two-round story including the round-1 over-correction that briefly let 2 of the 5 wrong picks back in). **With A30a (final, recalibrated): 3/11 resolves** - hand-graded against the same control breakdown: all 3 of the control's correct/defensible picks are restored (Sasol Secunda, the Fischer-Tropsch diagram, the Bundesarchiv Leuna photo) AND all 5 unambiguously wrong picks stay eliminated. **Net effect of A30a versus the control: -5 wrong, 0 correct/defensible lost** - both of the coordinator's targets hit simultaneously, on the real API, hand-verified. The 7 shots this benchmark could never resolve via search (a separate, unaffected limitation - the candidate pool for those shots contains nothing on-topic at all) still need a human upload or generation (A8/A9, step 4).

> **Coordinator's independent re-measurement, and a methodological caveat that supersedes the framing above (2026-08-15).** I re-ran the whole path myself on the real API rather than accepting the number. Result: **5 resolve, all 5 genuinely correct; 5 rejected, all 5 genuinely wrong; 1 shot had no candidate at all.** Better than the 3/11 reported — and the difference exposes something more important than the score.
>
> **The A17 fixture can no longer measure what it claims to.** Every shot in `hindi_test_project.json` has `asset_plan.entity = None`: it was planned before A1 existed and has never been re-planned. So the fixture cannot exercise entity retrieval at all, and *every* measurement taken against it since step 1 — the agent's and mine alike — has supplied **hand-written entities** that the real pipeline would not have for this fixture. Those numbers describe how the system behaves **given a competent Asset Planner**, which is a reasonable prediction of a fresh run (A1 is live and the prompt carries the entity instructions) but is *not* a measurement of the fixture as it stands. On the fixture as it literally is, entity retrieval contributes nothing and almost everything falls through to generation.
>
> **What is solid regardless of that caveat:** every one of the 5 resolved picks came from entity-curated retrieval and every one is correct, and the depiction check rejected 5 candidates that were all genuinely wrong — a Decauville railway map, a Norwegian museum diorama of *Soviet* tanks, a burning tanker, a modern Wembley freight yard, and a modern Fawley scene with cars and trees. **Zero wrong images now reach the video.** That is the real result of this phase: not that search finds more, but that it stops confidently shipping things it never should have.
>
> **Action before the next benchmark claim:** re-plan the Hindi fixture so its shots carry real Asset Planner entities, and re-export it. Until then, quote these numbers as "with entities supplied", never as a plain fixture measurement.
- [x] A human can see real images per shot, and swap or override any of them, before anything expensive runs — **step 3 built "see"; step 4 built "swap or override", and both halves are now verified through the real HTTP API**, not just at the service layer: `tests/e2e/test_upload_and_override_api.py` creates a project, renders it (DRY_RUN, zero API keys) to the point every shot already has a real, visible asset via `GET /progress` (`asset`/`locked` fields), then calls `POST /{id}/shots/{shot_id}/override` with a real multipart file upload and confirms the shot's asset changes and `locked` flips to `true` in the same `GET /progress` response - all before the plan is even approved, i.e. before anything expensive has run.
- [x] A human override survives re-resolution and version bumps — **verified in both directions**, per the coordinator's explicit instruction to test the interaction both ways rather than just the happy path: `tests/integration/test_timeline_service.py::test_locked_shot_binding_carries_forward_even_when_prompt_changes` (locked survives) sits directly alongside the pre-existing `test_binding_does_not_carry_forward_when_prompt_changes` (unlocked does not) - same shape of change, opposite, deliberate outcomes. `tests/e2e/test_upload_and_override_api.py::test_override_before_approval_locks_the_shot_but_still_requires_approval` additionally confirms the lock survives the real narration version bump through the full HTTP pipeline, not just inside `TimelineService` directly.
- [x] No generated image ships that violates a Director constraint — step 2, below.
- [x] Generation retries are bounded and counted against the project budget — step 2, below.
- [x] A shot that failed generation blocks the project from completing until a human fixes it, with no way to ship around it — **new for step 4 (A15/A26/A28)**: `tests/e2e/test_upload_and_override_api.py::test_review_gate_blocks_completion_until_the_failed_shot_is_overridden` manufactures a `failed` binding, drives it through the real `POST /timeline/approve` and `POST /render` routes to `status == "awaiting_review"`, confirms re-rendering without fixing anything is a no-op (not a "proceed anyway"), then confirms the override endpoint is the only thing that clears it.

## Implementation notes (2026-08-15) — step 2: Director-constraint enforcement at generation (A12/A13/A14/A18/A19)

Built exactly the step-2 scope: a vision check on generated media (never
searched assets - A16 still deferred), bounded regeneration on a
violation, and a terminal `failed` binding once attempts are exhausted.
No pipeline reordering, no upload endpoint, no approval-gate change (A19
- that's step 4's job, once the upload endpoint gives a human an actual
remedy).

- **New module `app/assets/constraint_check.py`** - `check_generated_image_constraints`
  (zero constraint checks, zero calls, when `constraints` is empty OR
  `provider is None`), `build_revised_prompt` (A18's deterministic,
  de-duplicated prompt revision), and `seed_for_attempt` (A13's two
  levers). `ConstraintVerdict`/`ConstraintCheckRequest`/
  `VisionConstraintProvider` live in `app/providers/base.py`, not in
  `app/assets/` - the OpenAI provider must produce a `ConstraintVerdict`
  and `app/assets/` must interpret it, and `providers/` sits below
  `assets/` in the dependency rule (section 5), so the shared type has to
  live at or below the lower layer.
- **`OpenAIPlanningProvider.check_constraints`** (`app/providers/openai_provider.py`)
  is the only new OpenAI-touching code - a second, cheaper model
  (`settings.openai_vision_model`, default `gpt-4o-mini`) than the
  planning model, since vision support isn't guaranteed on every
  planning-model choice and this is a mechanical check, not creative
  judgement. Messages are built against the real `openai.types.chat`
  param types (`ChatCompletionUserMessageParam` etc.), not `dict[str,
  Any]` - the looser typing type-checked fine for the pre-existing
  `structured_complete` (a flat two-message, text-only call) but failed
  mypy for this method's nested multimodal content list, and the fix is
  to type it properly against the SDK's own types, not to suppress the
  error.
- **DRY_RUN stays exactly as it was** - `_resolve_one_fake`/`_generate_fake`
  are untouched; DRY_RUN's fake generation never did real generation to
  check in the first place, so the constraint check is never wired into
  that path at all. `ResolveAssetsStep.run()` constructs `vision_provider
  = None if settings.dry_run else OpenAIPlanningProvider()`, the same
  idiom already used for `image_provider`/`video_provider`/
  `entity_provider`; `check_generated_image_constraints` treats `provider
  is None` as "nothing to call". Verified, not assumed: ran the full
  suite with `OPENAI_API_KEY` forced empty in the environment
  (overriding `.env`'s real key) to prove this - a real
  `AsyncOpenAI(api_key=None)` raises `OpenAIError` at *construction*
  (checked directly against the installed `openai==2.8.1`, not inferred
  from docs), unlike `FalVideoProvider`/`FalImageProvider`, whose
  constructors are lazy. That asymmetry means every test that runs
  `ResolveAssetsStep` with `DRY_RUN=false` has to patch
  `OpenAIPlanningProvider` too, even ones that never touch constraints
  (`tests/integration/test_resolve_assets_real.py` didn't, before this
  phase, and needed the same patch added retroactively).
- **Bounded regeneration** (A13): attempt 0 is the project's fixed seed
  (`_project_seed`, unchanged from M7); each subsequent attempt's prompt
  is *rebuilt* from the base prompt plus the de-duplicated set of
  constraints violated so far (`build_revised_prompt`), not appended
  onto the previous attempt's prompt - repeating an identical negative
  directive to an image model is not a stronger instruction, just a
  longer prompt, and a first version of this code did exactly that
  before being caught in review. The varied-seed lever
  (`seed_for_attempt`) fires only on the LAST attempt the configured cap
  (`settings.max_generation_attempts_per_shot`, default 3) allows - a
  first version hardcoded the switchover at attempt index 2, which is
  correct only at the default cap and silently disables the lever
  entirely if the cap is ever configured to 2; also caught in review, and
  covered by `test_seed_for_attempt_derives_the_switchover_from_max_attempts`
  and its integration-level counterpart.
- **Every attempt is billed, including rejected ones**, via a new
  `GeneratedClip.status="rejected"` (never reusable as a cache hit - the
  existing cache-hit check already only trusts `status == "completed"`)
  and a new `violated_constraint` column (Alembic revision
  `a1c9f3e7b2d4`) - a real structured field, not something recovered by
  parsing `error`'s free text. That column exists specifically for
  resumability: a resumed run whose most recent attempt is already
  recorded as `"rejected"` recovers the violated constraint from that row
  and advances straight to the next attempt, without regenerating (paying
  again) or re-running the vision check. A first version of this code
  only short-circuited on `status == "completed"`, so a rejected cache
  hit fell through to a full re-generate-and-re-check - a real
  cost-accounting hole caught in review (real money spent twice, neither
  charge recorded), fixed and covered by
  `test_resume_from_a_rejected_attempt_does_not_regenerate_or_rebill`.
- **Video generation checks the KEYFRAME, not the final clip**
  (`_generate_checked_keyframe`) - it's already an image and it's what
  determines the content. Unlike the image path, a *passing* keyframe
  attempt is not persisted as its own `GeneratedClip` row - its cost
  folds into the video job's own row (`estimated_cents`), exactly as
  before this phase, so nothing double-counts; a *rejected* keyframe
  attempt is billed on its own, the same as the image path. The video job
  is only ever submitted with a keyframe that has already passed the
  check.
- **Cache-key consequence, recorded so nobody discovers it by accident**:
  `prompt_hash` now includes the seed (`prompt|model|seed`, not
  `prompt|model`) - not because attempt 1 and attempt 2 "always" carry
  identical prompt text (an early draft of this note claimed that; it's
  wrong - a *different* constraint violated on consecutive attempts
  produces a strictly different revised prompt each time), but because
  the seed is a genuine generation input (same prompt, different seed,
  different image), and because the de-duplicated revision means two
  attempts *can* legitimately produce byte-identical prompt text (the
  *same* single constraint violated twice running revises to the same
  prompt both times) - that case must not collapse onto one cache entry.
  **Consequence:** this invalidates every `generated_clip` row cached
  under the old `prompt|model` formula. The next real run of any
  existing project with generated (not searched) media will not find its
  old cache entries and will regenerate from scratch, at real cost. This
  is a one-time price, paid once per project on its next real
  (non-DRY_RUN) run - accepted here, not discovered later by whoever pays
  it.
- **`GET /progress`** gained a `shots` array (`shot_id`, `state`, `rung`,
  `last_error`) - the only place per-shot detail is exposed until M9's
  dedicated shot-review surface exists, and A14/A19's "never silently
  shipped" needs the failure reason (naming the violated constraint)
  visible somewhere, not just counted.
- Gate checks, run from the repo root as required (not from `backend/`,
  which silently finds no config): `ruff check backend`, `black --check
  backend`, `mypy backend/app` all clean. Full suite: 204/204 passed,
  watched directly in the foreground (not backgrounded) after a first
  background run died without reporting. Both fixtures
  (`hindi_test_project`, default) reseeded afterward via
  `scripts/seed_test_project.py`.
- 23 new tests: `tests/unit/assets/test_constraint_check.py` (12, pure
  functions + one DB-backed audit-row test), `tests/unit/providers/test_openai_provider_vision.py`
  (5, a hand-rolled fake `AsyncOpenAI`-shaped client per the
  `test_fal_queue.py` pattern - no real network, no real SDK types beyond
  the public param types), `tests/integration/test_resolve_assets_generation_real.py`
  (8 new: empty-constraints, DRY_RUN-never-constructs-vision-provider,
  first violation/retry, second violation/varied seed, third
  violation/terminal failure, video-checks-the-keyframe, the resume/no-
  repay fix, and the configurable-switchover fix).

**What I verified by running it, versus what I reasoned about:** the
"zero API keys" claim is verified (ran the suite with `OPENAI_API_KEY`
forced empty and watched it pass, in addition to reading the SDK's
construction-time key check directly). The gate checks and full suite
above were watched completing in the foreground, not assumed from a
background job. The cost-accounting fix is verified by an integration
test asserting the exact total spend after a resume, not just that the
code compiles.

## Implementation notes (2026-08-15) — step 3: pipeline reorder + binding carry-forward (A5-A7, A11, A20-A22)

Built the target shape exactly: `GenerateTimeline → ResolveAssets(search,
free) → AwaitApproval → Narration → ResolveAssets(generate, paid) →
Render → Complete`. No new dependencies, no money spent building or
testing this (fakes only).

- **One `ResolveAssetsStep`, two instances, not two classes** (A21) -
  `app/workflow/steps/resolve_assets.py`'s constructor now takes
  `name`/`permitted_strategies`; `DEFAULT_PIPELINE`
  (`app/workflow/engine.py`) instantiates it as `resolve_assets_search`
  (`SEARCH_RUNGS` - rungs 1-4) before `AwaitApprovalStep`, and
  `resolve_assets_generate` (`GENERATION_RUNGS` - rungs 5-6) after
  `NarrationStep`. The ladder walk, licence gate, relevance gate, hash
  dedup, budget checks, and per-shot isolation are all the exact same
  code path for both - only which rungs are ever reached differs.
  `is_satisfied` is genuinely pass-specific (A21): each instance derives
  its own "done" state set from whether it permits generation.
- **A new `ShotBinding` state, `awaiting_generation`** - what the search
  pass writes when every rung it's permitted to use came up empty (or a
  shot's chain has none at all). Deliberately excluded from
  `TERMINAL_STATES` (`app/repositories/shot_binding_repository.py`): the
  search pass's own `is_satisfied` treats it as done (search is finished
  with this shot), the generation pass's does not (this is exactly its
  work queue). Getting this state's membership wrong in either set would
  either loop the search pass forever or let the generation pass silently
  skip a shot that needs it.
- **Carry-forward lives inside `TimelineService._persist`, not as an
  opt-in helper** (A11/A20) - the brief's own framing was "it must be
  impossible for a new version to exist without carry-forward having
  been considered", and `_persist` is the one method every version-
  creating path (`append_version`, `rollback_to`) funnels through before
  a new version becomes visible; `create_initial` skips it correctly
  (nothing to carry from). The rule itself (A20) compares each shot's
  `prompt`/`asset_plan` as parsed Pydantic values, not raw JSON strings -
  both sides already went through the same JSON round-trip inside
  `append_version`, so this is a strictly more correct reading of "byte-
  identical" than a literal string comparison would be (immune to
  harmless key-order/formatting noise that never touched real content).
  A carried binding is a NEW row at the new version
  (`ShotBindingRepository.carry_forward`) - the old row is left exactly
  as it was, never deleted or moved, same immutability spirit as the
  Timeline versions themselves.
- **`GET /progress`'s `shots` array (added in step 2) now distinguishes
  what was found from what will be generated** - `asset` (provider,
  source_url, licence, local_path) whenever `asset_id` is set, `clip`
  similarly for `clip_id`, and `will_generate` = `state ==
  "awaiting_generation"`. There is no frontend (M9 doesn't exist yet);
  this is the whole of "the human sees the images" for now, per the
  phase's own caveat.
- **A22 holds structurally, not by new code** - per-shot failure
  isolation (Principle 10) already means `ResolveAssetsStep.run()` always
  returns `outcome="ok"` regardless of how many individual shots' search
  calls raised; that was already true before this phase, it just wasn't
  load-bearing for reaching the approval gate until search moved before
  it. Verified, not just reasoned about: added a step-level test
  (`test_total_search_provider_failure_never_blocks_the_gate`) and a
  full-pipeline one
  (`test_total_search_outage_still_reaches_the_approval_gate`) that make
  every search call raise and assert the run still reaches
  `awaiting_approval`.
- **DRY_RUN preserved end to end** - `_resolve_one_fake` now also respects
  `permitted_strategies`/`generation_permitted`, deferring to
  `awaiting_generation` instead of calling `_generate_fake` when the
  search-only pass's fake search comes up empty, so DRY_RUN exercises the
  same two-pass shape as the real pipeline rather than silently
  collapsing back to one. Verified by running the e2e walking-skeleton
  test with this change in place (see below) and by adding assertions to
  it that every shot is already `resolved`, with a real `asset` visible,
  strictly BEFORE approval - proof the reorder took effect through the
  real HTTP API, not just at the unit level.
- **Existing tests whose *intended* behaviour changed, updated
  accordingly** (not just patched to stop failing):
  - `tests/integration/test_resolve_assets_real.py` is now explicitly the
    search-ONLY pass's test file. Its three "falls back to generation"
    tests now assert `state == "awaiting_generation"` and `clip_id is
    None` - the search-only pass must never generate, even as a
    fallback, which is the actual point of A6. Also gained the A22 test
    above.
  - `tests/integration/test_resolve_assets_generation_real.py` now
    constructs the generation-only instance explicitly
    (`GENERATION_RUNGS`); its shots never had search rungs in their
    fallback chains to begin with, so no behavioural assertions changed.
  - `tests/integration/test_narration_pipeline_ordering.py` was rewritten
    (it previously asserted `stale_bindings == []` - "nothing exists at
    the pre-narration version" - which was only true because the OLD
    single-pass step never ran before narration at all). The NEW,
    intended behaviour is the opposite: bindings DO exist at the pre-
    narration version (the search pass put them there), and the same
    ones - by `asset_id`, not just by count - reappear at the post-
    narration version via carry-forward, while the pre-narration row is
    left untouched. Also gained the pipeline-order and full-pipeline A22
    assertions.
  - `tests/e2e/test_skeleton.py`'s render-step comments updated to
    describe the two-pass shape; new assertions confirm every shot is
    resolved with a visible `asset` before approval.
  - `tests/integration/test_timeline_service.py` gained four new tests
    exercising carry-forward directly against `TimelineService`
    (unchanged fields carry; a changed `prompt` doesn't; a changed
    `asset_plan` doesn't; a removed shot carries nothing) - the pipeline-
    level tests above prove it works end to end, these prove the rule
    itself is exactly A20's, isolated from narration/search entirely.
- No new Alembic migration - `shot_binding.state` is an unconstrained
  string column; `awaiting_generation` is a new value, not a new column.
- **A17 benchmark: unaffected, confirmed by inspection rather than
  re-running the throwaway measurement script.** Step 3 touched
  `app/workflow/`, `app/timeline/service.py`, and `app/api/projects.py`
  only - none of `app/assets/ranking.py`, `app/assets/relevance.py`, or
  `app/providers/wikimedia.py` (the files the benchmark actually
  exercises) changed at all, so the same 11 shots resolve through
  byte-identical ranking/relevance/provider code and there is no
  mechanism by which the score could have moved. Re-running the live-API
  script to double-check a change that provably didn't happen was judged
  not worth the several real minutes of Wikimedia/Wikipedia traffic.
- Gate checks, run from the repo root as required: `ruff check backend`,
  `black --check backend`, `mypy backend/app` all clean. Full suite:
  **211/211 passed**, watched directly in the foreground (ffmpeg on
  `PATH`) - twice, once before and once after the ruff/black auto-fixes,
  to prove the formatting changes didn't alter behaviour. Both fixtures
  (`hindi_test_project`, default) reseeded afterward.
- 7 new tests over the 204 from step 2 (211 total): 2 in
  `test_narration_pipeline_ordering.py` (pipeline order + full carry-
  forward-across-narration proof), 4 in `test_timeline_service.py`
  (direct carry-forward rule tests), 1 in `test_resolve_assets_real.py`
  (A22).

**What I verified by running it, versus what I reasoned about:** the
pipeline order, the carry-forward mechanism (both the happy path and all
three "must NOT carry" cases), A22 (both step-level and full-pipeline),
and DRY_RUN end-to-end were all run and watched passing, not inferred.
The A17-benchmark claim above is the one thing in this note argued by
code inspection rather than re-executed - stated as such, not blurred
into "verified".

## Implementation notes (2026-08-15) — step 4: upload endpoint and per-shot override (A8-A10, A15, A23-A29)

Built the revised scope exactly, including the mid-step decision rewrite
(A25 gaining a second half, A26 losing "proceed anyway", A28/A29 new) -
none of the discarded first-draft design (a `failures_acknowledged_version`
column, a "proceed anyway" endpoint, a defensive `asset_locked` shortcut
in `AwaitApprovalStep`) made it into the final code; see "false starts"
below for why each was wrong.

- **Upload endpoint** (`POST /projects/{id}/assets`, A8/A23/A27) -
  `app/api/projects.py`. Accepts one or more files plus one description
  per file (`files: list[UploadFile]`, `descriptions: list[str]`,
  matched by index; rejected with 400 if the counts differ or any
  description is blank). Every file goes through the exact
  `validate_and_identify_image` path a searched asset already does (A27)
  before anything is written to disk, and is deduplicated by content
  hash exactly like a searched asset (M6) - re-uploading the same bytes
  is reported as a duplicate, not stored twice. Stored as an `AssetModel`
  row with `provider="project_assets"` and the new `description` column
  (Alembic revision `c7d2a8e91f3b`) - the only column this step adds.
  Entirely optional: a project that never calls this endpoint is
  byte-for-byte unaffected, verified by
  `test_upload_is_optional_and_a_no_upload_project_is_unaffected`.
- **`LocalProjectAssetProvider` is real now, not the M6 stub**
  (`app/providers/local_assets.py`) - `search` returns every
  `provider="project_assets"` row for the project
  (`AssetRepository.list_uploads_for_project`, new), `fetch` reads the
  bytes back off `local_path`. No internal filtering: A23 is explicit
  that an upload competes through the SAME relevance gate
  (`app/assets/relevance.py`) every other candidate goes through, scored
  against its own human-written `description` - matching against a
  filename would be worthless, which is the entire reason the upload
  endpoint requires a description at all. `ResolveAssetsStep` had to
  change in exactly two places to accommodate this: `_real_search_providers`
  now takes `asset_repo`/`project_uuid` (the provider needs a live
  session-bound repository, unlike the stateless Wikimedia/Pexels
  providers), and the licence gate is explicitly bypassed for the
  `project_assets` strategy only - `licence_requirements` is written by
  the Asset Planner with no visibility into whether an upload even
  exists (A3), so it can never have been chosen with a human's own photo
  in mind; requiring an uploaded image to happen to satisfy a licence
  string written for Wikimedia/Pexels would be an arbitrary rejection of
  media the human already vetted by choosing to supply it. Proven
  end-to-end against the real relevance gate (not a fake), with a
  deliberately non-matching licence, in
  `test_uploaded_asset_matches_via_the_real_relevance_gate_and_skips_licence_gate`.
- **Per-shot override** (`POST /projects/{id}/shots/{shot_id}/override`,
  A9/A10/A24/A25/A29) - names a `shot_id` directly, bypasses relevance
  and licence gates entirely (A24), and works on ANY shot regardless of
  its current binding state, not only a failed one (a Done-when
  criterion is "swap or override any of them"). Validates and hashes the
  file the same way the general upload endpoint does (A27), records an
  `append_version(produced_by=HUMAN)` that sets `Shot.asset_locked = True`
  on that one shot (new field, `app/schemas/timeline.py`) and nothing
  else (A29 - never `prompt`, `duration_s`, narration, framing, camera,
  or transitions), then writes the shot's `ShotBinding` directly to the
  overridden asset, bypassing every gate.
- **A25's two halves, both enforced in `TimelineService`** - carry-forward
  and prompt/asset_plan immutability are two SEPARATE mechanisms, not one
  check reused, because they answer different questions and the second
  is deliberately not expressible through the existing `owns` mechanism:
  - `_carry_forward_bindings` carries a locked shot's binding forward
    UNCONDITIONALLY - checked directly against `asset_locked` before the
    ordinary A20 prompt/asset_plan equality check, which it now skips
    entirely for a locked shot.
  - `_reject_locked_shot_drift` (new, called from `append_version`,
    unconditionally - not gated by `owns`) raises `PermanentError` if ANY
    later version changes a locked shot's `prompt` or `asset_plan` at
    all. This has to be separate from the additive-violation check
    (`app/timeline/additive.py`) because `owns` grants blanket permission
    over a whole top-level path - `NarrationStep` legitimately owns
    `"scenes"` to change `duration_s` freely, and that same broad grant
    would otherwise also legitimise changing a locked shot's `prompt`,
    which A25 must never allow regardless of what the caller declared
    ownership of. Both mechanisms are tested independently and are
    provably redundant with each other by construction (once drift is
    impossible, the "unconditional" carry-forward branch for a locked
    shot only ever fires on the one field that legitimately still
    changes, `duration_s`) - kept both anyway, belt-and-braces, exactly
    the same discipline `NarrationStep`/`AwaitApprovalStep` already use
    for their own crash-window robustness.
- **The review gate** (`AwaitReviewStep`, A15/A26/A28) - a new pipeline
  step, positioned between `resolve_assets_generate` and `RenderStep`
  (never after - A28: a failed shot must not reach the renderer even as
  a placeholder). Its condition is purely observable - "is any binding at
  the active version `failed`, right now" - with nothing stored anywhere
  as an acknowledgement, because A26 removed the "proceed anyway" exit
  entirely: there is exactly one way past this gate, fixing the shot, so
  there is nothing to acknowledge, only something to resolve. A new,
  distinct `ProjectStatus.AWAITING_REVIEW` (A28) keeps it visibly
  different from `AWAITING_APPROVAL` - the two questions ("approve the
  plan" vs. "fix these failed shots") have different remedies, and one
  status for both would make the API ambiguous about which applies.
- **The override endpoint's self-approval is conditional, not automatic**
  - if the timeline was already approved (or narration has already run)
  before the override, the new locked version is immediately re-approved
  too, mirroring `NarrationStep`'s own append-then-approve pattern
  exactly (two separate commits, same crash-window shape) - this is what
  lets the override endpoint be the review gate's remedy without a
  redundant second human click. If the timeline had NOT yet been
  approved, the override does NOT self-approve, leaving the human's
  first plan approval still required as normal - overriding a shot is a
  legitimate pre-approval action too (previewing search results and
  fixing one before ever approving), and must not silently skip that
  first approval as a side effect. Both paths are tested explicitly
  (`test_override_before_approval_locks_the_shot_but_still_requires_approval`,
  `test_override_after_completion_self_approves_and_preserves_duration_and_narration`).
- **`GET /progress`'s `shots` array gained `locked`** - the other half of
  "a human can see... any shot's asset", alongside the existing `asset`/
  `clip`/`will_generate` fields from step 3.
- **Fixture round-trip: made to fail loudly, not silently** -
  `scripts/seed_test_project.py` re-downloads a missing asset from its
  `source_url` and verifies the hash, which works for every Wikimedia/
  Pexels asset but cannot work for an upload (ladder rung `project_assets`)
  whose bytes were never anywhere but `storage/` (gitignored) in the
  first place. Neither committed fixture (`hindi_test_project`,
  `m8_test_project`) has any uploads, so this is not exercised by the
  reseed above - but if a future fixture snapshot ever does include one
  whose file is missing on disk, the script now raises `SystemExit` with
  an explicit explanation and a next step (re-upload, re-export) rather
  than silently writing an `asset` row pointing at nothing, which would
  otherwise surface much later as an incomprehensible ffmpeg error with
  no connection to the actual cause.
- **False starts, corrected before finishing** (the user changed two
  decisions mid-build and the coordinator reverted the half-applied
  first draft rather than let it linger):
  - First draft had A26 keep "proceed anyway", recorded via a new
    `Project.failures_acknowledged_version` column. The rewritten A26
    removes it entirely ("you should not be able to finish a video if we
    can't fix it") - no column, no acknowledgement state anywhere;
    `AwaitReviewStep`'s condition is purely a live query.
  - First draft had `AwaitApprovalStep` treat `any(shot.asset_locked ...)`
    as approval-equivalent, mirroring the existing `produced_by ==
    NARRATION` shortcut, as a crash-window defence for the override's
    self-approval. Traced through carefully, this is actually unsafe: an
    override performed BEFORE a project's first-ever approval would set
    `asset_locked = True` on a version that has never been approved, and
    this shortcut would then let `AwaitApprovalStep` skip approval
    entirely for it - a real I6/ADR-008 violation (expensive work before
    approval). Dropped; the override endpoint's self-approval is
    conditioned on whether the PRIOR version was already
    approved-or-narration-produced instead (see above), which has no such
    hole.
- Gate checks, run from the repo root as required: `ruff check backend`
  (one real finding - `zip()` without `strict=`, fixed, not suppressed),
  `black --check backend` (5 files reformatted by the auto-formatter,
  re-ran the full suite afterward to confirm no behavioural change),
  `mypy backend/app` all clean. Full suite: **227/227 passed**, watched
  directly in the foreground (ffmpeg on `PATH`) - twice, once before and
  once after the black auto-fixes. Both fixtures (`hindi_test_project`,
  default `m8_test_project`) reseeded afterward; the new Alembic
  migration (`c7d2a8e91f3b`, adds `asset.description`) was applied first.
- 16 new/changed tests over the 211 from step 3 (227 total): 4 in
  `tests/integration/test_await_review.py` (the gate's own condition
  logic, including the no-deadlock proof that fixing the binding
  directly - never a flag - clears it), 1 in
  `tests/integration/test_workflow_engine.py` (the new `awaiting_review`
  outcome's distinct status at the engine level), 3 in
  `tests/integration/test_timeline_service.py` (locked-shot carries
  despite a duration-only change; a locked shot's prompt/asset_plan
  change is rejected outright; same for `asset_plan`), 1 in
  `tests/integration/test_resolve_assets_real.py` (the real
  `LocalProjectAssetProvider` through the real relevance gate, licence
  bypass included), 7 in the new
  `tests/e2e/test_upload_and_override_api.py` (upload validation/dedup,
  a no-upload project unaffected, override pre-approval, override
  post-completion with the A29 duration/narration equality assertion,
  the review gate blocking and clearing over HTTP, override on an
  unknown shot, override with invalid bytes).

**What I verified by running it, versus what I reasoned about:** every
test above was run and watched passing, including the full suite twice.
The one thing NOT verified through DRY_RUN is a real vision-constraint
generation failure driving the review gate - DRY_RUN's fake providers
always succeed, so `test_review_gate_blocks_completion_until_the_failed_shot_is_overridden`
manufactures a `failed` binding directly rather than deriving one from a
real exhausted-retries generation failure (that mechanism is proven for
real, separately, in `test_resolve_assets_generation_real.py` from step
2). This is stated plainly rather than implied: the review gate's own
condition logic (is any binding failed, right now) is identical
regardless of how a binding got to `failed`, so this is a legitimate
proof of the gate and the override endpoint acting as its remedy through
the real HTTP surface - it is not a claim that DRY_RUN itself can
produce a real generation failure end to end.

## Implementation notes (2026-08-15) — step 5: vision-verify searched assets (A16 → A30)

Built exactly A30's scope: the TOP-ranked candidate per rung only (never
a whole pool), skipped entirely when that candidate is entity-curated
(A2), one vision call maximum per rung reached, and a rejection drops
the candidate and abandons the whole rung - falling through to the next
rung in the fallback chain exactly like a licence or relevance rejection
already does, never retried within the same pool.

- **New module `app/assets/depiction_check.py`** - `check_candidate_depicts_subject`,
  the searched-media sibling of `app/assets/constraint_check.py`'s
  `check_generated_image_constraints`: same `None`-provider/DRY_RUN idiom
  (zero calls when the provider is `None` or the search subject is
  blank), same `llm_call` audit path, genuinely different question ("does
  this depict X" vs "does this violate Y") and therefore its own verdict
  type (`DepictionVerdict`, `app/providers/base.py`) rather than a
  constraint-shaped workaround.
- **`OpenAIPlanningProvider.check_depiction`** - a second method on the
  same `VisionConstraintProvider` Protocol as `check_constraints` (M6.5
  step 2), same model (`settings.openai_vision_model`), its own prompt.
  One shared provider, two independent questions.
- **`ResolveAssetsStep` changes, scoped tightly**: `vision_provider` is
  now constructed whenever a real run is happening at all, not only when
  `self._generation_permitted` (the search pass needs it for A30 now,
  the generation pass still needs it for A12) - both docstring claims
  this invalidated ("the search-only pass never constructs
  `OpenAIPlanningProvider`") were corrected in place, not left stale.
  Inside the per-rung ranked-candidate loop, a `checked_top_candidate`
  flag ensures the vision call fires at most once per rung, on the FIRST
  candidate that would otherwise be accepted (a candidate with corrupt
  bytes is skipped for free by the existing validation step first, never
  counted against the one-call budget - proven directly in
  `test_vision_check_skips_a_corrupt_top_candidate_and_checks_the_next_valid_one`).
- **The measurement (A17), done properly - a real control, not a guess**:
  a throwaway script loaded the Hindi fixture's PLANNED timeline into a
  fresh, disposable project and ran the real search-only pass twice -
  once with A30 live, once with the vision check monkeypatched to always
  pass (isolating everything ELSE - ranking, relevance, licence - held
  exactly constant). See the phase's own Done-when box above for the
  full numeric result and the hand-graded reasoning; the short version:
  A30 eliminated 5 unambiguously wrong picks a human would have caught
  immediately, at the real cost of 2 defensible/partial ones the vision
  model could not visually confirm from pixels alone (their catalog
  metadata claims a specific named subject; nothing in the image itself
  proves it). **Both throwaway measurement projects and their storage
  directories were deleted afterward** - the shared dev Postgres has only
  the two real fixtures (`hindi_test_project`, `m8_test_project`) in it
  again, verified by querying the `project` table directly after cleanup.
- **Real cost incurred**: this measurement made real OpenAI vision calls
  (`gpt-4o-mini`, the configured `openai_vision_model`) - roughly 16 calls
  across the live A30 run (one per rung actually reached with a
  licence-and-relevance-passing top candidate; some shots' rungs found
  nothing at all and made zero calls). The control run made zero real
  calls (vision check replaced with a local, free fake) and the
  Wikimedia/Wikipedia calls in both runs are free per their own terms.
  Cost is small (`gpt-4o-mini` vision pricing) but real, not zero -
  stated plainly rather than glossed over.
- Gate checks, run from the repo root as required: `ruff check backend`,
  `black --check backend` (4 files auto-reformatted alongside the M8
  step-4 changes below, full suite re-run afterward to confirm no
  behavioural change), `mypy backend/app` all clean.
- 15 new tests over the 227 from step 4: 3 in
  `tests/unit/assets/test_depiction_check.py`, 4 in
  `tests/unit/providers/test_openai_provider_depiction.py`, 4 in
  `tests/integration/test_resolve_assets_real.py` (the wrong-top-candidate
  falls-through-the-rung case, the entity-curated exemption proven with a
  provider that raises if ever called, the corrupt-bytes-skipped-for-free
  case, and rejection-on-the-last-rung deferring to generation, never
  failing the shot).

**What I verified by running it, versus what I reasoned about:** the
one-call-per-rung cap, the entity-curated exemption, and the
drop-and-fall-through behaviour were all run and watched passing against
canned fakes. The A17 re-measurement is the one thing in this phase
verified against the REAL live API end to end, both with and without
A30, with the resulting images hand-inspected (not just their titles) -
including reading the model's own recorded `reason` text for every
rejection, not assuming the verdict was reasonable without checking it.

## Implementation notes (2026-08-15) — A30a: recalibrating the depiction check

A30 as measured above eliminated all 5 unambiguously wrong picks but
also dropped 2 genuinely correct ones (a real Bundesarchiv Leuna
photograph, a real Fischer-Tropsch diagram) - a false-reject cost the
coordinator judged worse than the check paid for, because nothing in
the PIXELS can confirm a specific named subject; identity lives in the
archive's catalogue metadata, invisible to a vision model. Recalibrated
in place, not reverted - re-measured twice, honestly, including the
regression the first attempt introduced.

- **The rename that makes the new question askable at all**:
  `DepictionVerdict.depicts: bool` → `confidently_wrong: bool` across
  the whole call chain (`app/providers/base.py`, `OpenAIPlanningProvider
  .check_depiction`, `FakeVisionConstraintProvider`,
  `app/assets/depiction_check.py::check_candidate_plausibility` -
  renamed from `check_candidate_depicts_subject`, `ResolveAssetsStep`).
  Not a cosmetic rename: A30's original polarity ("does this depict the
  subject") has no honest `True` answer for an unverifiable specific -
  `confidently_wrong` (biased toward `False`, i.e. "let it through
  unless the pixels themselves contradict it") is the only framing where
  "I can't tell" and "keep it" are the same answer, which is the whole
  point of A30a's asymmetric bias (a false reject costs a real archival
  photograph; a false accept costs one wrong image a human sees, and can
  override, at the approval gate).
- **Round 1 (over-corrected, measured, not guessed)**: rewrote the
  prompt to ask "is this confidently a different KIND of subject" and
  re-measured live. Result: restored both dropped-but-correct images -
  but also let back in 2 of the 5 previously-eliminated wrong picks (the
  Greek topographic map, the modern reenactor photos). Read the model's
  own recorded `reason` text to diagnose exactly why rather than
  guessing: the map was accepted as "consistent with the general theme
  of a resource map" regardless of which country it actually depicted,
  and the reenactors were accepted as "plausibly relat[ing] to wartime
  Germany" despite showing no tanks at all - both are vague *thematic*
  resemblance, precisely the kind of checkable subject-matter mismatch
  A30a is supposed to keep catching, not the unverifiable-specific-
  identity case it's supposed to let through. This regression is
  recorded here rather than smoothed over.
- **Round 2 (final)**: rewrote the prompt again, grounded in the exact
  measured failures above - explicitly distinguishing **checkable
  subject-matter facts** (which country a map depicts, what kind of
  vehicle/object/structure is shown, archival vs. modern era) - reject
  confidently wrong ones of these - from **unverifiable specific named
  identity** ("is this specifically the Leuna plant") - never reject for
  this alone. Concrete positive/negative examples in the prompt are
  drawn directly from the measured Hindi-fixture cases, not invented.
  `_PROMPT_VERSION` bumped `v1` → `v2` so a cached `llm_call` audit row
  is traceably which prompt produced it.
- **The re-measurement, same control methodology as A30's own (the real
  search-only pass run twice against a disposable project seeded from
  the fixture's planned timeline, once with the check live and once
  monkeypatched to always pass)**: **3/11 shots resolve**, and hand-
  grading the actual downloaded images against the control's own
  breakdown shows this is the target outcome exactly - **all 5
  unambiguously wrong picks stay eliminated** (the Greek map, the modern
  reenactors, the burning ship, the derelict Polish coal elevator, the
  generic depot buildings), and **all 3 of the control's correct/
  defensible picks are restored** (Sasol Secunda, the Fischer-Tropsch
  diagram, the Bundesarchiv Leuna photo) - not just the 2 the coordinator
  asked for. Net effect versus A30 (round 1, 1/11): +2 correct-count,
  wrong-count unchanged at 0. Net effect versus no check at all (the
  control, 8/11 with 5 wrong): -5 wrong, -0 correct/defensible lost.
  **Both targets hit simultaneously** - this is not a case of "if you
  cannot get both, say so honestly": both were achieved, measured, and
  are reported here with the actual numbers rather than a favourable
  framing of a partial result.
- Gate checks: `ruff check backend`, `black --check backend`, `mypy
  backend/app` all clean from the repo root (checked again as part of
  the full batch-two gate run below). 19 tests updated for the rename
  across `tests/unit/assets/test_depiction_check.py`,
  `tests/unit/providers/test_openai_provider_depiction.py`,
  `tests/integration/test_resolve_assets_real.py` - no new test files,
  since this is a recalibration of existing, already-tested behaviour,
  not new scope.
- **A real DB incident during this measurement, caught and fixed, not
  hidden**: a live re-measurement script ran in the background while the
  Openverse test suite (a separate, unrelated batch-two item) was
  launched in the background concurrently - `tests/conftest.py`'s
  autouse `clean_database` fixture truncated the shared dev Postgres
  mid-measurement, silently wiping both real fixture projects
  (`hindi_test_project`, `m8_test_project`). Caught immediately via an
  `AttributeError` in the measurement script's own output, both fixtures
  reseeded via `scripts/seed_test_project.py`, and the re-measurement
  re-run in the foreground with no other DB-touching process in flight -
  the same discipline this guide's testing strategy already calls for
  and that this session violated once, by accident, while multitasking.

**What I verified by running it, versus what I reasoned about:** both
calibration rounds were measured live against the real OpenAI API and
the real Hindi fixture, with the resulting images hand-graded against
the exact same control breakdown A30's own measurement used - not
inferred from the model's stated verdict alone. The round-1 regression
was diagnosed by reading the model's own `reason` text, not guessed at.

## Implementation notes (2026-08-15) — M8 step 4: music and ducking (D6/21.2)

Built the full pipeline: `MusicProvider` + a real (if currently
non-functional - see below) Pixabay provider, a pre-approval selection
step recording the choice in `Timeline.music_plan` via `append_version`,
and a deterministic ducking mix in the renderer. No new dependencies, no
real ElevenLabs or fal.ai calls.

- **A verified, corrected factual error in the design decision - flagged,
  not silently worked around.** D6/21.1 calls Pixabay Music "free,
  permissive, a real public API." Checked directly against the live API
  before writing a line of provider code (the same discipline A1/A2 used
  for Wikipedia): `GET https://pixabay.com/api/?...` (images) and
  `GET https://pixabay.com/api/videos/?...` (videos) both succeed with
  the real key already in `.env`; `GET https://pixabay.com/api/music/`
  returns 404, `GET https://pixabay.com/api/audio/` returns 403, and
  Pixabay's own docs (`https://pixabay.com/api/docs/`) list exactly two
  endpoints - Images and Videos. **Pixabay has no public Music/Audio
  search API.** `app/providers/pixabay_music.py` is real,
  `MusicProvider`-conformant scaffolding that says so explicitly - it
  raises a `PermanentError` naming exactly this gap rather than guessing
  at an undocumented endpoint or scraping the website. `SelectMusicStep`
  catches that (and any other provider failure) the same way it catches
  "found nothing suitable" - A22's precedent, extended - so this doesn't
  block anything; it just means a real (non-DRY_RUN) run's music
  selection degrades to silent-but-narrated today, until either Pixabay
  ships a real API or a different provider is wired in behind the same
  Protocol. `MUSIC_PROVIDER=pixabay` stays the default - changing it is a
  separate decision this step does not make silently.
- **The chosen track lives in `Timeline.music_plan`, never a side table**
  (the newly-closed decision) - two new fields, `selected_track`
  (`MusicTrackSelection`: provider, track id, source url, licence,
  attribution, content hash - provenance only, I2) and
  `selection_attempted` (a bool - what makes "looked, found nothing" a
  distinct, resumable Timeline state from "haven't tried yet" WITHOUT a
  side table, mirroring why `ShotBinding`'s `awaiting_generation` state
  exists, but recorded in the Timeline itself here because the brief was
  explicit that music's decision record lives there). A new `ProducedBy.
  MUSIC_SELECTION` - neither an AI planner nor a human, a deterministic
  acquisition step, same category `NARRATION` already established.
- **`SelectMusicStep`** (`app/workflow/steps/select_music.py`) runs
  between `resolve_assets_search` and `AwaitApprovalStep` - Pixabay
  search is free, so A5 applies to music exactly as it does to visual
  assets, and a human approving a video should hear what it will sound
  like. Same hard licence gate as visual assets, ranking via
  `app/assets/music_ranking.py` (reuses `app/assets/relevance.py`'s exact
  term-overlap function against a track's title+tags, no separate
  scoring algorithm). Every failure mode - provider outage, licence
  rejection, failed audio validation, budget cap already exceeded -
  converges on `selected_track=None, selection_attempted=True` and
  `outcome="ok"`; this step never fails the run.
- **Budget folded in, honestly**: `check_budget` is called before every
  fetch attempt (`settings.music_cost_cents_estimate`, 0 by default,
  since Pixabay search is genuinely free) - structurally identical to
  narration/generation's own checks, even though there is, today,
  nothing real for it to ever block. `total_project_spend_cents`
  deliberately does NOT sum a third music total - there is no persisted
  `cost_cents` row for a track selection (no side table, see above), and
  its own docstring now says exactly why.
- **The ducking mix is a static volume envelope, never a live sidechain
  compressor** (I5) - `app/renderer/music.py`. Built as a CHAIN of
  `volume` filters (`enable='between(t,start,end)'`) rather than a
  single `if()` expression, specifically to avoid nested comma-escaping
  in ffmpeg's filtergraph syntax as the number of narration intervals
  grows. Two ffmpeg passes, not one: `build_ducked_bed` produces the
  ducked, faded, video-length music track as its OWN file first;
  `mux_music` then either maps it straight through (no narration) or
  `amix`es it with the video's existing narration stream
  (`duration=longest`, not `first` - a first draft used `first` and it
  silently truncated the whole mixed output to narration's own shorter
  length whenever narration ended before the video did; caught building
  the test for it, fixed, and the fix is what `test_mux_music_combines_narration_and_ducked_bed_without_truncating`
  now proves). Looping (`-stream_loop -1`) plus `atrim` to the video's
  real length covers a track shorter OR longer than the video with the
  same two options, so no duration-based preference was needed in
  ranking.
- **Proven with a real, isolated volume measurement, not just "ffmpeg
  exits 0"** - a first-draft test measured the volume of the FULL mixed
  (narration + ducked music) output and found the duck window
  indistinguishable from the bed window, because narration's own
  loudness swamped the reading; a mixed signal cannot tell "the music
  got quieter" apart from "narration is simply loud". Refactored to test
  `build_ducked_bed`'s output alone (no narration signal in it at all) -
  `test_ducked_bed_is_quieter_during_the_speaking_interval` confirms a
  >8dB measured gap against a 14dB configured one, comfortably outside
  measurement noise.
- **DRY_RUN preserved end to end** - `FakeMusicProvider` always "finds" a
  canned candidate, so DRY_RUN exercises the real selection logic
  (search, licence gate, ranking, recording the choice) fully, but its
  audio is a literal fake byte string, same idiom as
  `FakeNarrationProvider` - never written to disk, and `RenderStep._resolve_music_track`
  returns `None` under DRY_RUN unconditionally, mirroring
  `_resolve_narration_audio`'s own reasoning exactly. Verified via the
  real walking-skeleton e2e test (`tests/e2e/test_skeleton.py`), which
  now also asserts the active timeline carries a real selection
  (`music_plan.selected_track.provider == "fake_music"`) before
  approval - not just that the render still produces a video.
- **`GET /progress` and the fixture round-trip need no changes at all** -
  `music_plan` is part of the Timeline JSON document already, so
  `scripts/export_test_project.py`/`seed_test_project.py` restore it for
  free with zero code changes; there is no music-specific side table to
  forget.
- **A resumability wrinkle, caught and fixed in an existing test, not
  silently left broken**: `test_resume_after_simulated_crash_does_not_redo_completed_steps`
  asserted the active timeline stayed at v2 after a resumed run reached
  the approval gate - true before this step, false now that
  `SelectMusicStep` legitimately appends its own v3 in the same resumed
  run. Fixed by asserting `produced_by == "music_selection"` on the
  final version instead of a bare version number, which is what actually
  proves `GenerateTimelineStep` itself didn't re-run (re-running it would
  produce a DIFFERENT v3, with a different `produced_by`).
- Gate checks: `ruff check backend`, `black --check backend` (4 files
  reformatted), `mypy backend/app` all clean from the repo root. Full
  suite: **254/254 passed**, watched directly in the foreground (ffmpeg
  on `PATH`) - three times across this batch (once before, once after
  black's auto-fixes, and once after fixing the resumability test above).
  Both fixtures reseeded afterward; no new Alembic migration - music
  selection lives entirely in the Timeline's JSONB document, no new
  table or column.
- 24 new tests over the 227+15 above (254 total): 4 in
  `tests/unit/assets/test_music_ranking.py`, 8 in
  `tests/integration/test_select_music.py` (no-plan no-op, DRY_RUN
  records a real selection, `is_satisfied` resumability, the licence
  gate, a matching candidate recorded with full provenance, total
  provider failure degrades cleanly, the REAL `PixabayMusicProvider`'s
  documented limitation exercised directly - not just a fake standing in
  for it, and the budget cap blocking a fetch attempt), 4 in
  `tests/integration/test_render_music_mix.py` (the isolated ducking
  proof, the no-narration flat-bed case, a short track looped to cover
  the full video, and the narration+music combined pass not truncating),
  and the pipeline-shape/resumability updates to existing files.

**What I verified by running it, versus what I reasoned about:** the
Pixabay API gap is verified directly against the live endpoints (four
real HTTP requests, recorded above), not inferred from the design doc's
claim. The ducking envelope's actual effect on measured volume is
verified with real ffmpeg output, isolated from narration specifically
because a first attempt at that same proof was measuring the wrong
signal - that dead end is recorded here rather than smoothed over. The
full suite and gate checks were watched completing in the foreground.
What is NOT verified: Pixabay Music actually returning a real track for
a real project, since no such endpoint exists to call - this is stated
as a known, documented gap, not a working feature.

## Update (2026-08-15) — Pixabay replaced with Openverse; music selection now genuinely functional

The gap above is closed, not merely documented. [Openverse](https://api.openverse.org/v1/audio/)
(no API key, aggregates Jamendo + Freesound behind one search) is real,
live, and verified directly - `21.1`'s Music Provider caveat and the
Provider roster table above are updated to match.

- **New `app/providers/openverse_music.py`** - `OpenverseMusicProvider`,
  the same `MusicProvider` Protocol `PixabayMusicProvider` already
  implements. Filters `license=cc0,by` at the QUERY (the licence gate is
  load-bearing, not ceremonial - Openverse's unfiltered pool is
  dominated by `by-nc-nd`, unusable twice over: NoDerivatives conflicts
  with bedding/ducking a track under narration, and NonCommercial limits
  what the finished video can be used for), then re-gates the RESPONSE
  against `_ACCEPTABLE_LICENCES = frozenset({"cc0", "by"})` - never
  trusting the query filter alone to have been honoured server-side.
  `by` requires attribution, recorded via `TrackCandidate.attribution`
  (a new field - `Asset.attribution` already existed for visual assets;
  this is its music-selection sibling) and preferred by `fetch()` when
  present.
- **Verified live, not assumed**: `documentary ambient` -> 81 permissive
  results; `tense drone` -> 46; `historical documentary` -> 2 (both
  room-ambience field recordings, not music); `sombre orchestral` -> 0.
  The pool is thin and uneven by construction (Freesound skews to sound
  effects; Jamendo's permissively-licensed slice is a minority) - empty
  is a normal, expected outcome for a narrow Director-written
  `music_plan`, not a bug to chase.
- **`select_music.py` gained a real registry** (`_PROVIDERS: dict[str,
  Callable[[], MusicProvider]]`, dispatched on `settings.music_provider`)
  replacing the old hardcoded single-class construction - swapping
  providers is now a config change, matching the pattern every other
  provider protocol in this codebase already follows (21.1).
  `MUSIC_PROVIDER` default moved `"pixabay"` -> `"openverse"` in
  `app/core/config.py`, `.env`, and `.env.example`.
- **`PixabayMusicProvider` kept, not deleted** - it stays exactly as
  honest as it already was (raises `PermanentError` naming the verified
  API gap), reachable by explicitly setting `MUSIC_PROVIDER=pixabay`, in
  case Pixabay ever ships a real Music/Audio endpoint and someone wants
  to re-verify against it without writing a new provider from scratch.
- 11 tests in `tests/unit/providers/test_select_music.py` (updated for
  the registry, plus a new real-Openverse-call test), 7 new in
  `test_openverse_music.py`, 2 new in `test_pixabay_music.py` (proving
  it still fails exactly as documented, not silently). Live Openverse
  calls kept to a handful across the suite, per the "no new
  dependencies, don't spend money" constraint - Openverse is free, so
  this is a courtesy limit on real network calls in CI, not a cost
  concern.

## Implementation notes (2026-08-15) — M8 steps 5-6: Ken Burns, determinism, fingerprint, draft mode

Closes M8. Ken Burns is a pure renderer concern (canon 3.1 - no planner
changes); determinism is *proven*, not asserted, via a real byte-for-
byte comparison; the fingerprint makes I5 actionable (skip a render that
provably would produce the same bytes); draft mode reuses all of the
above at a different resolution rather than being a second code path.

### Step 5 — Ken Burns

- **New `app/renderer/ken_burns.py`** - `build_zoompan_expression(camera,
  *, frames) -> ZoompanExpression | None` (`None` for `STATIC` - the
  existing `-loop 1 -t duration` path is untouched and remains the
  common case), translating `camera.movement`/`direction`/`intensity`
  into `zoompan`'s own `zoom`/`x`/`y` expressions against a
  `WORKING_CANVAS_SCALE = 1.6` oversized working canvas (headroom for
  the pan/zoom to move within without ever exposing an edge).
- **The jitter bug, avoided by construction, not tuned around.**
  `zoompan`'s `zoom` variable is the PREVIOUS output frame's own value -
  it only accumulates smoothly if fed exactly ONE decoded input frame
  per shot. The static path's `-loop 1 -t duration` input hands ffmpeg
  the same source frame decoded many times over the shot's duration,
  which resets `zoom` to 1 on every one of them - the well-known
  "zoompan jitters on a looped still" failure. A Ken Burns shot is
  therefore fed via a bare `-i path` (no `-loop`, no `-t`) - genuinely
  one input frame - and `zoompan`'s own `d`/`fps`/`s` parameters
  generate the shot's whole output duration internally from that one
  frame, which is what lets `zoom` accumulate correctly frame over
  frame instead of resetting.
- **`app/renderer/slideshow.py`** gained `_ken_burns_filter()` and a
  per-shot branch in `_render_run()` between the static and Ken-Burns
  input paths - everything downstream (crossfades, concat, output
  encoding) is unchanged; only how each shot's own clip is produced
  differs.
- 13 new tests in `tests/unit/renderer/test_ken_burns.py` (expression
  correctness, direction/intensity mapping, the `STATIC` -> `None` case),
  4 in `tests/integration/test_render_ken_burns.py` (real ffmpeg,
  including a static+moving shot mixed in one crossfaded render) - all
  passed against the real encoder on the first real run.

### Step 6 — determinism, the render fingerprint, and draft mode

- **Purging non-determinism from every ffmpeg invocation in the
  renderer**: `-fflags +bitexact` (strips non-deterministic
  muxer/encoder metadata such as `creation_time`), `-flags:v
  +bitexact`/`-flags:a +bitexact` per stream, and `-threads 1` on the
  x264 encode specifically - libx264's default multi-threaded mode is
  not guaranteed bit-reproducible run to run. Added to every encode call
  site: `app/renderer/slideshow.py` (the main visual encode and the
  concat pass), `app/renderer/audio.py::mux_narration`,
  `app/renderer/music.py::build_ducked_bed` and `::mux_music`.
- **Proven, not asserted** (`tests/integration/test_render_determinism.py`):
  renders the exact same Timeline + images TWICE, independently, from
  scratch (never through the fingerprint cache - a cache hit would just
  copy a file and prove nothing about the encoder itself), and asserts
  `hashlib.sha256` equality on the actual output bytes. Three cases: a
  static shot, a Ken Burns shot (the riskier one - `zoompan`'s own frame
  generation had to be exactly reproducible too), and a multi-shot
  crossfade. All three pass byte-for-byte on the real encoder, on this
  machine's ffmpeg build.
- **New `app/renderer/fingerprint.py`** -
  `compute_render_fingerprint(timeline, asset_content_hashes,
  narration_content_hashes, music_content_hash, render_settings,
  ffmpeg_version)`, `sha256` of canonical (sorted-key) JSON. Every real
  input to the output bytes is included: the Timeline's own CONTENT
  (scenes, shots, camera, transitions - everything `render_timeline`
  reads) with bookkeeping fields excluded (`schema_version`,
  `timeline_id`, `project_id`, `version`, `parent_version`,
  `produced_by`, `status`, `created_at` - the same set
  `TimelineService._BOOKKEEPING_FIELDS` already treats as non-content,
  for the identical reason: none of them affect a single rendered
  pixel), sorted asset/narration content hashes (never trusted in
  caller-supplied order - I5), the selected music track's content hash,
  the render settings that actually affect output pixels (width,
  height, fps, pixel format - never binary paths), and the installed
  ffmpeg's own version string (a version bump can change encoder
  behaviour on byte-identical inputs, so it must invalidate old cache
  entries).
- **Why bookkeeping fields are excluded - a design revision caught before
  it shipped**: the first version fingerprinted the WHOLE Timeline
  document, "deliberately conservative". That would have made
  cross-project cache reuse impossible BY CONSTRUCTION, since
  `project_id`/`timeline_id` always differ between projects - which
  directly contradicted this same module's own docstring claim about
  cross-project reuse. Caught on review, fixed before commit: excluding
  bookkeeping fields can never cause a false cache HIT (none of them
  reach a rendered pixel), only enables a real cache reuse case this
  codebase already has (the same script re-planned into a fresh test
  project repeatedly).
- **New `app/repositories/render_repository.py`** -
  `get_completed_by_fingerprint`, `insert_completed`,
  `list_completed_drafts_older_than`, `delete`. Dedup is GLOBAL, not
  per-project - the same precedent `GeneratedClipRepository
  .get_by_prompt_hash` and `NarrationRepository.get_by_content_hash`
  already set: the same byte-identical render is the same file no
  matter which project's run reproduces it.
- **`RenderStep.run()` refactored into a module-level `render_video(ctx,
  timeline, render_settings, *, output_filename)`** so the automated
  final render and the on-demand draft endpoint are the SAME code path,
  never two. Checks the fingerprint BEFORE any real work; a hit copies
  the cached render's bytes into THIS project's own output path (never
  a live cross-project file reference, so this project's copy survives
  independently of whatever later happens to the source project's
  storage) and skips the entire render/mux pipeline; a miss renders for
  real through the existing silent -> narrated -> music-muxed pipeline,
  then unconditionally records a new `render` row.
- **Proven end to end through the real database, not just the pure
  hashing function**
  (`tests/integration/test_render_fingerprint_cache.py`): two
  INDEPENDENTLY created projects with byte-identical Timeline scene
  content and byte-identical bound image bytes (but different paths,
  different ids) - the second project's render is asserted byte-for-
  byte identical to the first's AND the real (slow) encoder is proven to
  have been invoked exactly ONCE across both, via a call-counting
  monkeypatch around `render_timeline` that still calls through to the
  real function. Both projects still get their own completed `render`
  row (their own `output_path`, one shared `fingerprint`) - the reuse is
  a real copy into an independent file, never a shared reference.
- **Draft mode**: `render_video` parameterised by `RenderSettings` and
  an output filename specifically so ONE function serves both
  `RenderStep` (`settings.render_width/height`, `final.mp4`) and a new
  on-demand endpoint, `POST /projects/{id}/render/draft`
  (`app/api/projects.py`) - `settings.draft_width/draft_height`,
  `draft.mp4`. The draft endpoint works off the ACTIVE timeline
  regardless of approval status (the pre-approval search pass has
  already resolved what it can - M6.5 - so a draft is genuinely
  available before a human approves anything, matching this phase's own
  Advice: "always render a fast draft first"), and never touches
  `project.status`/`project.video_path` - only `POST /render`'s own
  workflow progression controls those. A new `GET
  /{project_id}/video/draft` mirrors the existing `GET /video` for
  retrieval.
- **Draft and final can never collide on one fingerprint** - proven at
  two levels: the pure fingerprint unit test
  (`test_different_render_dimensions_change_the_fingerprint`) and a real
  `render_video` integration test
  (`tests/integration/test_render_draft.py`) that renders the SAME
  timeline content at both resolutions and confirms two different
  files, ffprobed back to their own distinct dimensions, with different
  bytes - not a cache collision.
- **`DRAFT_RETENTION_DAYS` (D3) wired, not left as an unread config
  value**: new `app/renderer/retention.py::purge_expired_drafts(session,
  *, now=None) -> int`, deleting every completed draft-dimensioned
  `render` row (and its file, if still present) older than
  `settings.draft_retention_days`. Identifies "a draft" by width/height
  matching `settings.draft_width/draft_height` - there is no separate
  `is_draft` column, so this reuses the exact same distinguishing signal
  the fingerprint collision guard above already relies on. **No
  scheduler exists anywhere in this codebase** (no Celery beat, no
  APScheduler) - adding one JUST for this would be new infrastructure
  for a single call site, against the "no new dependencies" constraint.
  Instead, `purge_expired_drafts` is invoked OPPORTUNISTICALLY from
  inside the draft endpoint itself: every draft request is also a
  chance to sweep whatever aged out since the last one. Documented
  honestly as a real limitation: a project that never requests another
  draft never triggers a sweep of its own stale one - acceptable for
  disk-space hygiene, not for a compliance-grade deletion guarantee. The
  purge is always safe even if it raced a render: `render_video`'s
  cache-hit check already verifies the cached file still `.exists()`
  before trusting a fingerprint match, so a row whose file was purged a
  moment earlier is simply treated as a cache MISS and re-rendered for
  real, never as a hit against a missing file.
- 5 new integration tests for retention/draft:
  `tests/integration/test_draft_retention.py` (2 - purges exactly the
  expired-and-draft-dimensioned row, never a fresh draft or a final
  render regardless of age; a true no-op when nothing has expired) and
  `tests/integration/test_render_draft.py` (1, draft vs final ffprobed
  dimensions and byte-difference), plus 4 new e2e tests in
  `tests/e2e/test_draft_render_api.py` over the real HTTP API (draft
  available before approval and never disturbing project status, draft
  and final as independent files at independent resolutions, 400
  without a timeline yet, 404 for `/video/draft` before any draft has
  been rendered) - all on DRY_RUN fakes, zero API keys, matching this
  phase's own constraint.
- **Gate checks, run from the repo root**: `ruff check backend`, `black
  --check backend` (10 files auto-reformatted - accumulated across this
  batch's changes, not just steps 5-6; full suite re-run afterward to
  confirm no behavioural change), `mypy backend/app` - all clean. **Full
  suite: 304/304 passed**, watched directly in the foreground (ffmpeg on
  `PATH`), twice (once before black's reformatting, once after). Both
  fixtures reseeded afterward via `scripts/seed_test_project.py`. No new
  Alembic migration - `render.fingerprint` and every other column
  `RenderModel` needed already existed in the schema, unused, exactly as
  this phase's own build-order item 6 described.
- **50 new tests over the 254 baseline at the top of this batch (304
  total, verified by direct collection, not arithmetic)**: 49 in brand
  new files - 13 + 4 (Ken Burns unit + integration), 3 (determinism), 12
  (fingerprint unit), 1 (fingerprint cache integration), 1 (draft render
  integration), 2 (draft retention), 4 (draft e2e API), 7 (Openverse
  provider), 2 (Pixabay provider, proving it still fails exactly as
  documented) - plus 1 more added to the pre-existing
  `tests/integration/test_select_music.py` (a real live Openverse call).
  The A30a recalibration and the Openverse registry switch also touched
  three further pre-existing files (`test_depiction_check.py`,
  `test_openai_provider_depiction.py`, `test_resolve_assets_real.py`,
  `test_select_music.py` itself) - renamed/updated in place for the
  `confidently_wrong` rename and the provider-registry change, not
  counted again here since their test COUNT didn't change beyond the one
  addition just noted.

**What I verified by running it, versus what I reasoned about:**
determinism is the one claim in this entire phase proven with a literal
byte-for-byte hash comparison against the real encoder, twice, rather
than inferred from "the inputs look the same." The fingerprint
cache-hit path is proven through the real database and a real
call-counting guard around the actual encoder function, not just the
pure hashing logic in isolation. Draft mode's non-collision with final
is proven at both the pure-fingerprint level and through a real
`render_video` call at each resolution. What is NOT independently
re-verified here: whether the DRAFT_RETENTION_DAYS sweep's
request-triggered cadence is operationally sufficient for real usage
patterns once this ships - that is a judgement call, stated as such,
not a measured fact.

---

# Phase M7 — Media Generation

> **Goal:** fill the gaps search could not. Rungs 5–6. This is where real money starts moving.

Both rungs go through **fal.ai** ([why](#why-an-aggregator-for-media-generation)). One key, one queue abstraction, two protocol implementations (`ImageProvider`, `VideoProvider`) over the same client.

## Step 0 — the model bake-off

`FAL_IMAGE_MODEL` and `FAL_VIDEO_MODEL` ship unset on purpose. Settle them here, empirically, before building anything on top:

1. Take the M0 fixture (`backend/tests/fixtures/timeline_v1.json`) — 6 shots with real archival-style prompts.
2. Render it end to end through each candidate model, changing only the config value.
3. Compare the outputs side by side against `creative_context.visual_style`, and record cost and latency per clip.
4. Write the winner into `.env` and note the runner-up in this document, so the next person knows what was already tried.

Judge on **whether generated media sits convincingly beside archival photography**, not on standalone prettiness. A gorgeous clip that looks obviously synthetic next to a 1936 photograph is a worse result than a plainer one that blends ([Principle 7, cinematic continuity](00_Creative_Philosophy.md)). Keep the losing renders — they are the evidence for the decision.

## Advice

- **Estimate cost before the approval gate and show it.** "This project will cost approximately $4.20 — 12 image generations, 2 video generations" turns the approval screen from a formality into a real decision point. `estimate_cost` on every provider exists for this.
- **Enforce a hard per-project budget cap.** Exceeding it raises `PermanentError` and halts. A retry bug against a paid video API is the most expensive failure mode this system has.
- **Check the cache before every generation** (rung 0). `hash(prompt + model + params + seed)` → existing clip. Regeneration after a small edit should re-generate only what changed.
- **Video generation is submit-and-poll, not request-response.** Minutes, sometimes tens of minutes. This is exactly why `VideoProvider` has `submit`/`poll` and why the workflow engine must survive process restarts — a run must be able to reconnect to an in-flight provider job rather than resubmit it. fal's queue exposes the same submit/status/result shape for every model, so write this once against the queue rather than per model.
- **Persist the provider job handle immediately on submit, before anything else.** If you crash between submit and persist, you have paid for a clip you can never find.
- **Idempotency keys on every paid call.** Retry-after-timeout must not double-charge. Use the provider's idempotency mechanism where one exists.
- **Keep the model id out of the provider class and in config.** The whole point of routing through an aggregator is that switching models is a config change. A `FalVideoProvider` that hardcodes a model id throws that away — and makes the bake-off unrepeatable when a better model ships.
- **Record the model id on every `generated_clip` row**, alongside `prompt_hash` and cost. Without it, the generation cache silently serves clips from a model you have since moved off, and cost attribution across a model switch becomes guesswork.
- **Generate consistently, not novelly.** [Creative Philosophy](00_Creative_Philosophy.md): generated media must sit next to archival footage without looking alien. Feed `creative_context.visual_style` into every generation prompt, use a fixed seed per project, and prefer stylistic consistency over per-shot quality.
- **Cap concurrency per provider.** Parallelism is required ([Principle 11](03_Engineering_Principles.md)) but unbounded fan-out will trip rate limits and turn a cheap run into a retry storm. A semaphore per provider, sized from config.
- **Failures degrade, they do not abort.** A failed generation marks its binding failed and falls through to the next rung — or to a placeholder — and the render still completes. A 59-shot video with one gap is far more useful than no video.

## Done when

- [x] ~~The bake-off has run~~ — **deliberately skipped** (see Implementation notes below). `FAL_IMAGE_MODEL`/`FAL_VIDEO_MODEL` are set to direct picks, not a recorded comparison.
- [x] Cost estimate appears before approval (`GET /progress`); exact estimate-vs-actual accuracy wasn't captured on the first real run (see 2026-08-15 note) — a real run did happen and cost tracking ($0.36, then $0.00) was correct, but "within ~20%" specifically remains unverified.
- [x] Budget cap halts a runaway run
- [x] Cache hit rate is visible via `generated_clip.prompt_hash`; a second identical run costs nothing (proven in tests, not against the real API)
- [x] A crash mid-generation resumes without resubmitting in-flight jobs (video only — proven via a simulated crash in tests)
- [x] Real fal.ai image generation proven against the live API (2026-08-15, first real run) — real Seedream calls, real cost, real images composited into a real render
- [ ] Real fal.ai *video* generation (Kling) proven against the live API — the first real run resolved every generation-needing shot as an image; no shot in either live run so far actually needed `generate_video`
- [ ] Switching either model is a one-line `.env` change — the mechanism is real (never hardcoded), but not yet verified by actually doing it once against the live API

## Implementation notes (2026-08-14)

**The bake-off (Step 0) was explicitly skipped by decision, not by oversight.** Comparing real models costs real money and needs human visual judgment ("does this sit convincingly beside archival photography") that shouldn't be made silently. `FAL_IMAGE_MODEL=fal-ai/bytedance/seedream/v4/text-to-image` and `FAL_VIDEO_MODEL=fal-ai/kling-video/o3/standard/image-to-video` are direct picks, verified against fal.ai's own API docs (exact input/output schema, not guessed) but never run once against the real API end-to-end. Revisit if output quality disappoints.

**The video model is image-to-video, not text-to-video** — a fact only discovered by checking the live schema, and it reshapes the whole generation path: every `GENERATE_VIDEO` shot first generates a still keyframe via the image model (same styled prompt, same per-project seed), then feeds that image's fal-hosted URL into Kling. No separate upload step is needed — the image model's own result URL is already fal-hosted.

- **`app/providers/fal_queue.py`** is the only file that imports `fal_client` (ADR-003 firewall) — one generic `submit`/`poll_once` wrapper over fal's queue, shared by both `FalImageProvider` and `FalVideoProvider` per the guide's own advice ("write this once against the queue rather than per model").
- **Image generation is a bounded synchronous poll** (Seedream is fast, typically seconds) — `FalImageProvider.generate()` submits and polls in a loop for up to ~60s, raising `TransientError` if it genuinely never completes so the shot retries later through the normal workflow backoff. **Video generation is real submit-and-poll**: `FalVideoProvider.submit()` returns a job id that `ResolveAssetsStep` persists via `GeneratedClipRepository.insert_pending()` *immediately*, before anything else - a crash between submit and persist would otherwise pay for a clip that can never be found again. A later run finds that in-flight row via `get_in_flight_for_shot()` and polls the *same* job rather than resubmitting; the shot's `ShotBinding` stays `"pending"` (non-terminal) for as many runs as it takes.
- **Budget cap is checked before every paid call**, not just once - `check_budget()` sums `generated_clip.cost_cents` already spent for the project and raises `PermanentError` (never retried) if the next generation would exceed `PROJECT_BUDGET_CAP_CENTS`. Because the check re-runs per shot, a breach doesn't need special-casing beyond normal per-shot isolation (Principle 10) - every subsequent shot's attempt fails the same cheap check immediately rather than making a wasted paid call.
- **The generation cache (rung 0)** is `generated_clip.prompt_hash` keyed on the *styled* prompt (shot prompt + `creative_context.visual_style`) plus model id - checked before spending anything, for both image and video.
- **Cost estimate on `GET /progress`** (`estimated_cost_cents`) only counts shots whose primary `asset_plan.strategy` is already a generation rung - a search-primary shot that later falls through to generation isn't reflected, which is an honest, documented under-estimate rather than a false precision claim.
- 32 new tests (7 `FalQueueClient` tests using a fake stand-in for `fal_client.AsyncClient`'s own `Completed`/`Queued`/`InProgress` types; 11 `FalImageProvider`/`FalVideoProvider` tests via `httpx.MockTransport` for downloads; 8 pure-function cost/budget tests; 6 `resolve_assets` integration tests covering the image happy path, fresh video submission, in-progress resume, completed resume, the budget cap, and the generation cache), 94/94 tests total green, ruff/black/mypy clean.

**Update (2026-08-15) — the first real, live, paid run end to end.**
Everything built above was previously only proven against fakes/mocks;
this is the first time real money moved through the whole system on a
real script (WWII Fischer-Tropsch synthetic fuel / Sasol history,
project `b06ea1f3-ef6a-4910-bde0-e32edbe42a95`, superseded by
`58f0a5e6-008d-468e-862a-e365e463878e` after the M6 query fixes — see
below). Real Director→Scene→Shot→Asset planning, real Wikimedia/Pexels
search, real Seedream image generation for shots search couldn't fill,
real FFmpeg render, real approval gate — all in one pass, total cost
$0.36. `fal_image_cost_cents_estimate`/`fal_video_cost_cents_estimate`
tracking and the budget cap machinery both worked correctly; no bugs
found in this phase's own code. (The bugs the run *did* find — shot-id
collisions, the resumability gaps, the OpenAI temperature rejection, the
asset-search query and User-Agent bugs — all belong to M5/M6/M4; see
their Implementation notes.)

After the M6 query/User-Agent fixes landed, the same timeline was
replayed (skipping the planner calls entirely — no new OpenAI cost — by
seeding a fresh project directly via `TimelineService.append_version`
with the existing scenes/shots/asset_plans, search_queries manually
shortened to the new keyword style) on project `58f0a5e6-...`. Result:
13/13 shots resolved from real Wikimedia archives, **zero** `generate_image`
or `generate_video` calls needed, $0.00 spent. This is genuinely the
better outcome for this script (real archival photography over
AI-generated images, per the ladder's own "reuse before generate"
principle) — it also means this phase's video-generation path (Kling,
image-to-video) still has *not* been exercised against the real API in
either live run; both `Done when` items above about video specifically
and about switching models remain unverified for that reason, not because
anything is suspected broken.

---

# Phase M8 — Renderer

> **Goal:** the deterministic, pure-function output stage. The real one.
>
> **Status:** all 6 build-order steps done as of 2026-08-15. Steps 1-4
> (narration, the master clock, muxing, music/ducking) closed in earlier
> batches; steps 5-6 (Ken Burns, determinism, the render fingerprint,
> draft mode) closed this batch, alongside a recalibration of the
> A16→A30 depiction check (A30a) and replacing the non-functional
> Pixabay music provider with a real, working one (Openverse). See the
> Build order, Done-when, and each step's own Implementation notes below
> for the measured detail.

**Start here, not from a fresh project.** Project
`58f0a5e6-008d-468e-862a-e365e463878e` already has a fully real, verified
timeline (5 scenes, 13 shots, WWII Fischer-Tropsch/Sasol script) with
every shot resolved to a real archival photo (see M6/M7's 2026-08-15
notes) and a working slideshow render at
`storage/58f0a5e6-008d-468e-862a-e365e463878e/renders/final.mp4`. Reusing
it means M8 work starts directly on narration/audio/captions instead of
re-paying for planning and re-resolving assets. (Caveat: the backend test
suite's `clean_database` fixture truncates the same Postgres DB this
project's row lives in — see [12_Testing_Strategy.md](12_Testing_Strategy.md)
— so running `pytest` mid-session will need the project's DB row
re-seeded; the render file itself survives on disk regardless.)

## What ElevenLabs actually returns — checked, not assumed (2026-08-15)

**The timestamps are character-level, not word-level.** `POST /v1/text-to-speech/{voice_id}/with-timestamps` returns JSON containing `audio_base64` plus an `alignment` object of three parallel arrays: `characters`, `character_start_times_seconds`, `character_end_times_seconds`. Every "word-level timings" phrasing in D1/D2 and in the M5 advice above was wrong about the *mechanism*. The decision itself — TTS from the script, narration is the master clock, no forced-alignment step — stands unchanged.

This is **better** than what those sections assumed, and it makes the master clock simpler rather than harder. `Shot.narration_span` is already a `[start, end)` **character-offset pair** into its scene's `narration_text`, so a shot's true spoken duration is a direct index lookup — `character_end_times_seconds[end - 1] - character_start_times_seconds[start]` — with no word-splitting heuristic in between, and therefore nowhere for a word-boundary bug to hide. Build against the character arrays directly; derive words only if something later genuinely needs them.

**Use `alignment`, never `normalized_alignment`.** The normalized variant is aligned to ElevenLabs' normalized text ("Dr." → "Doctor", "1943" → "nineteen forty-three"), whose character indices no longer correspond to the script the Shot Planner indexed its spans against. Silently using it would desynchronise every shot whose narration contains a number or an abbreviation — which, on a historical documentary script, is most of them.

## Build order

Same rule as M5: one piece end to end, verified against the real API, before starting the next.

1. ~~**`NarrationProvider` + ElevenLabs + persistence.**~~ **Done.** The Protocol in `providers/base.py` (it is named in that file's docstring but does not exist yet), `providers/elevenlabs.py` as the only file that touches the endpoint, a `narration` table (segment ↔ scene, audio path, `alignment` JSONB, voice/model/character count), and storage at `{project}/narration/{content_hash}.mp3` per D3. Cache on `hash(text + voice_id + model + output_format)` — a re-render must never re-pay for identical audio, the same discipline as `generated_clip.prompt_hash`.
2. ~~**The master clock.**~~ **Done.** `app/timeline/narration_fit.py`: given a scene's alignment plus its shots' `narration_span`s, compute each shot's real spoken duration and reconcile. This writes a **new Timeline version** (`produced_by=narration`, `owns={"scenes", "metadata"}`) rather than mutating in place or fixing it up inside the renderer — corrected durations are a decision, so they belong in the IR (I1), and `append_version` is the only legal writer (I3).
3. ~~**Mux narration into the render.**~~ **Done.** Leave the existing silent visual path exactly as it is; assemble one continuous narration track (hook + scenes in order) and mux it in a single final pass. Do **not** thread audio through the per-run `xfade` graph — that recreates precisely the progressive drift D5 exists to prevent.
4. ~~**Music.**~~ **Done**, provider corrected mid-step (see the step-4 and Update Implementation notes below): `MusicProvider` + **Openverse** (Pixabay verified live to have no public Music/Audio API), the chosen track recorded in `Timeline.music_plan`, then the deterministic ducking mix: bed at `MUSIC_BED_GAIN_DB`, ducked to `MUSIC_DUCK_GAIN_DB` across every interval where narration is speaking — computed from the alignment arrays as a static volume envelope, never a live sidechain compressor (I5).
5. ~~**Ken Burns.**~~ **Done.** `camera.movement`/`direction`/`intensity` → `zoompan`/`crop` expressions. Purely a renderer concern; no planner changes (canon 3.1). See this step's own Implementation notes for the jitter pitfall and how it was avoided.
6. ~~**Determinism + draft mode.**~~ **Done.** Populated `render.fingerprint` (the column already existed, nothing wrote it) and skip-if-unchanged, proven byte-for-byte via a real double-render, not asserted; plus the 480p draft path and `DRAFT_RETENTION_DAYS` wiring. See this step's own Implementation notes.

**All six build-order steps of this phase are now done.**

## Multi-language (Hindi first) and the hook

Both are wanted for the first real M8 run, and neither is only a prompt change:

- **Language.** `Timeline.metadata.language` already exists and is carried through every version, but it is currently written once from `settings.default_language` and then never read by anything. M8 makes it real: the Director and Scene Planner must be *told* the target language and write `narration_text` in it directly, and `eleven_multilingual_v2` (already the configured default) covers Hindi through the same timestamped endpoint. **Plan in the target language; do not translate afterwards** — a translated line rarely takes the same time to speak as the original, so post-hoc translation reintroduces exactly the timing drift D1 exists to eliminate. Needs: a per-project language input (API + `Project`), that language threaded into the Director/Scene Planner user content, and a real `ELEVENLABS_VOICE_ID` (currently blank — pick it by listening; it is not a spec decision).
- **The hook.** A short opening line that earns the first three seconds. If the script already opens with one, nothing to do; if it doesn't, the Scene Planner should be able to write one. It **cannot** live in `narration_text`: `ScenePlanner._make_validator` hard-rejects any output whose concatenated `narration_text` is not verbatim-identical to the submitted script, and that check is load-bearing — it is what keeps narration traceable to its source. So the hook becomes a **new top-level `Timeline.hook: str | None`**, outside the verbatim check, with its own TTS segment spoken before scene 1, no `narration_span`, and no owning scene. Needs: the schema field, a Scene Planner prompt + output-schema change, and step 3 above prepending its audio.

## Open decisions for M8

None of these are settled. Answer them before or during the build, and record the answer here.

- **Per-scene TTS, or one request for the whole script?** Per-scene matches the data model (`narration_span` offsets are per-scene, so alignment indices line up with zero arithmetic), makes the cache per-scene (edit one scene, re-synthesise one scene), and keeps the per-scene shape every other planner already uses. Cost is identical either way — billing is per character. The real tradeoff is prosody: separately synthesised scenes will not flow into one another the way a single continuous read does. **Recommendation: per-scene**, then listen to a real render before deciding whether the seams matter.
- **What wins when real narration breaks a D7 cap?** Narration is the master clock (D1), so a shot must stretch to cover its words — but that can push a shot past `MAX_SHOT_DURATION_S`, or the whole video past the 90s `MAX_VIDEO_DURATION_S`. Truncating audio is not an option; it cuts words off mid-sentence. **Recommendation:** let per-shot duration exceed its cap (the cap is a planning heuristic; the narration is real), but treat exceeding total `MAX_VIDEO_DURATION_S` as an explicit, loud failure that tells the user to shorten the script — never a silent trim.
- **Narration runs after approval (I6), so approved durations are not final.** TTS costs money, so it cannot run before the gate — which means the timeline the user approves carries planner-estimated durations while the rendered video carries narration-corrected ones. That is defensible (approval is of the creative plan, not of millisecond timings), but it should be a deliberate choice rather than an accident, and the approval UI should eventually say so.
- ~~**Where does the chosen music track live?**~~ **CLOSED 2026-08-15 — the Timeline, and selection happens BEFORE the approval gate.** The chosen track is recorded in `music_plan` via an `append_version`, not in a side table: D6 makes music selection creative, and I1 makes the Timeline the only source of truth for creative decisions. The Timeline holds the *selection* (provider, track id, source url, licence, attribution, content hash) and never the bytes (I2) — the audio lives in `storage/{project}/music/{content_hash}.mp3` like every other asset. **Pixabay search is free, so selection belongs in the pre-approval pass** (A5): a human approving a video should hear what it will sound like, and changing the music after approval is exactly the kind of correction this phase moved earlier. The content hash in the Timeline is also what lets the track participate in the render fingerprint (step 6).
- ~~**Does TTS count against the budget cap?**~~ **CLOSED — already true in code.** `check_budget` is called with `total_project_spend_cents(clip_repo=..., narration_repo=...)`, which sums narration alongside generated clips. Verified in `app/workflow/steps/resolve_assets.py`; no work needed. Music must be folded in the same way when step 4 lands.

## Music search, corrected against real Openverse results (2026-08-15)

The first real run selected **no track at all**, and the cause was not the code. Measured directly against the live API with the licence filter applied:

| the Director's actual terms | permissive results |
|---|---|
| `documentary industrial ambient` | **1** (birdsong) |
| `investigative historical underscore` | **0** |
| `minimal mechanical pulse` | **0** |
| `dark archival documentary` | **0** |
| `restrained tension piano` | **0** |

Simple, literal terms answer readily — `documentary music` → 102 results, top hit *"Documentary Music Strings"*, CC-BY, 53.8s; `ambient`, `orchestral`, `cinematic`, `dark ambient` → the API's 240-result page cap each.

**M1 — the Director writes production-library vocabulary for a pool that does not speak it.** Terms like "investigative historical underscore" are what Epidemic Sound or Artlist understand. Openverse aggregates Freesound and Jamendo, where audio is tagged plainly. The prompt must ask for simple, literal terms.

**M2 — the ranking needs a duration floor, and this only becomes urgent once M1 is fixed.** `music_ranking.py` deliberately has no duration preference because the render loops the bed — sound reasoning for a 30-second music loop, dangerous for this pool: `industrial` returns a **2.5-second air horn**, `tension` a 15-second stab. Fixing the vocabulary without a duration floor would bed an air horn looping sixteen times under a documentary. Prefer tracks at least as long as the video, or a substantial fraction of it.

**M3 — a selection miss is permanent, and it should not be.** `SelectMusicStep.is_satisfied` returns true once `selection_attempted` is set, so a project that found nothing can never try again — not even after the two fixes above. The live project has that flag set and its jargon `search_terms` frozen into the Timeline, so it would render silent forever. A human needs a way to say "try again", optionally with their own terms. This is the same principle the rest of M6.5 rests on: an automated asset choice a human disagrees with must be correctable, and music is an asset choice like any other.

## Implementation notes (2026-08-15) — M1–M3: fixing why the first real run selected no music

All three built against the diagnosis above, scoped tight per the
coordinator's instruction: fix exactly M1–M3, do not build the M4–M7
local-library plan yet (it lands after M1–M3, per that section's own
"Sequencing" note above).

### M1 — Director prompt vocabulary

`app/prompts/director/v1.md`'s `search_terms` guidance was rewritten to
ask explicitly for "simple, literal, one-or-two-word terms a plain
keyword search would match, never production-library jargon" - with the
measured failing terms named directly as what NOT to write, and the
measured working terms (`documentary music`, `ambient`, `orchestral`,
`cinematic`, `dark ambient`) named as what a plainly-tagged pool
actually answers. Prompt-only change (as scoped) - no schema or
validator change, since the defect is entirely in wording, not in a
checkable structural property `search_terms` could be validated against.

**Re-verified live against the real Openverse API** (12 calls: 5 old
jargon terms + 5 new simple terms + 2 combined-query terms for the M2
check below): the five jargon terms from the live run returned 1
permissive result total (birdsong, matching `0711551`'s own finding
exactly); all five new terms returned the API's per-page result cap
(10 each, `_PAGE_SIZE`) - confirming the fix actually changes what a
real search returns, not just what the prompt asks for.

### M2 — a duration floor in music ranking

`app/assets/music_ranking.py` gained `compute_duration_floor_s` and a
duration-aware `rank_music_candidates`. **Chosen design: a
lexicographic reorder, not a hard filter and not a weighted/soft
score** - candidates meeting the floor always sort ahead of ones that
don't, regardless of relevance, but nothing is ever discarded from the
pool. Argued explicitly (per the instruction to argue for the choice,
not just state it):

- **A hard gate** (discard anything under the floor) risks the exact
  failure that motivated this fix in the first place: selecting nothing
  on a thin, honestly-filtered pool. That is literally how the live
  project ended up silent.
- **A pure weighted/blended score** (fold duration into one combined
  number with relevance) risks the air horn still winning if the
  weights are not tuned exactly right - and there is no corpus large
  enough to tune them against with real confidence.
- **A lexicographic reorder** gets both guarantees at once: whenever
  ANY floor-passing candidate exists, it wins over a short one no
  matter the relevance gap; when NONE do, the best-matching short
  candidate is still returned rather than nothing. Selecting a short
  loop that repeats a little is strictly better than silence, and is
  exactly the outcome this pool already produced before this fix
  existed - not a regression, just no longer the risk-free default.

The floor itself: `min(20.0, 0.5 * video_duration_s)` - an absolute
20-second ceiling (chosen to sit above both measured one-shot cases,
2.5s and 15s, while not demanding a track cover anywhere near a full
60-90s documentary, since the render already loops the bed to cover
that) and a `0.5 ×` scaling term so a short video doesn't demand an
unreasonably long track relative to its own length. A candidate with no
reported duration (Openverse does not guarantee the field) is treated
as NOT meeting the floor - unverified is not the same as confirmed long
enough.

**Re-verified live** (2 more calls, `tension`+`industrial` combined,
20 unique permissive candidates returned): without the floor, the top 5
by relevance alone were dominated by 15-16s clips tied on relevance;
with the floor applied (`video_duration_s=60.0` → `floor_s=20.0`), the
34.3s and 63.3s tracks correctly sorted ahead of the sub-20s ones, and a
94s track with a WEAKER relevance score (0.200 vs 0.800) still
out-ranked every floor-failing candidate - direct, measured proof the
lexicographic preference behaves as designed, not just as intended.

### M3 — a recoverable music-selection miss

New `POST /projects/{id}/music/retry` (`RetryMusicSelectionRequest`,
optional `search_terms: list[str] | None`). Resets
`music_plan.selected_track` to `None` and `selection_attempted` to
`False` via a normal `append_version` (I3, `produced_by=HUMAN`,
`owns={"music_plan"}`) - never mutated in place - optionally
overwriting the Timeline's own frozen `search_terms` in the same call,
since the whole point is escaping terms that were bad from the start
(re-running unchanged jargon terms would just fail the same way again).
Mirrors `override_shot_asset`'s own belt-and-braces re-approval exactly:
an already-approved timeline is re-approved after the reset so resuming
does not demand a redundant second human click.

**Costs nothing extra for a project that has never attempted
selection** - `SelectMusicStep.is_satisfied` itself is completely
unchanged; the reset simply puts a stuck project back into the exact
"not yet tried" state that method already recognises, so a project that
never hit this path at all behaves identically to before.

**Scoped tight, as instructed**: no music-upload endpoint. A per-shot-
image-upload analogue (a human supplying their own track file directly)
would be the natural next step if ever wanted, but does not fall out of
this design for free (it would need its own validation/storage path,
mirroring `POST /{id}/assets`) and was not built.

**Verified against a throwaway project, created and deleted the same
way the A30 measurement's disposable projects were - never the live
project.** Seeded a Timeline with `music_plan` in the exact stuck shape
(`search_terms` = the live project's own jargon terms,
`selection_attempted=True`, `selected_track=None`). Confirmed, in order,
against the real database and the real live Openverse API: (1)
`SelectMusicStep.is_satisfied` reads `True` (stuck, matching the live
project); (2) the reset transform (identical to the endpoint's own)
flips it to `False`; (3) re-running `SelectMusicStep` for real, with
human-supplied terms `["documentary music", "ambient"]`, genuinely finds
and records a real track (`"Stasis (music for space)" by Drakensson`,
CC BY 4.0, via Freesound) with full provenance; (4) `is_satisfied` reads
`True` again - freshly and correctly settled, not stuck. The throwaway
project was deleted afterward via the same derived-from-schema,
child-tables-first approach `scripts/seed_test_project.py` already uses
(never a hand-typed table list). A first attempt at this same check
returned no track at all with no error - later understood to coincide
with a real network outage (the same one that killed the session
mid-task); repeated once connectivity was confirmed restored, with a
clean, positive result.

### Verification, honestly

**The test suite was NOT run at any point during M1–M3** - project
`194ad0e7-e545-4524-a597-59e4ff604ba2` sits at the approval gate in the
same shared dev Postgres with 13 of 14 shots overridden with
irreplaceable human-uploaded images, and running `pytest` truncates
every table via `tests/conftest.py`'s autouse `clean_database` fixture.
New/updated tests were written, not executed: 6 new cases in
`tests/unit/assets/test_music_ranking.py` (the duration-floor scaling
formula, the measured air-horn-vs-loop case, the lexicographic-not-
weighted proof, the never-discard-only-reorder proof, the unknown-
duration case, and the floor's no-op behaviour when the video length
isn't known yet), a new `tests/unit/planners/test_director_music_prompt.py`
(regression guard on the prompt's own wording, not on planner code), and
a new `tests/e2e/test_music_retry_api.py` (5 cases over the real HTTP
route, DRY_RUN + `FakeMusicProvider` throughout - the override taking
effect, an omitted override leaving existing terms in place, the empty-
list rejection, the two "nothing to retry" 400s, and the re-approval
belt-and-braces). `ruff check backend`, `black --check backend` (2
files auto-reformatted), `mypy backend/app` all run normally (no
database touched) and are clean. Live-API verification: **16 real
Openverse calls total** across M1/M2/M3 (12 for M1 + 2 more for M2's
combined query + 2 for M3's search, across two M3 attempts - the first
interrupted by the network outage, the second clean), all free, no key
required.

## Music decisions M4–M7 — a curated local library replaces open-ended search (2026-08-15)

Proposed by the user after M1–M3 were diagnosed. Adopted, because it does not merely work around the failure — it removes the failure class.

**M4 — a hand-curated local library becomes the primary music source; search becomes the fallback.** The diagnosis in M1 was that the Director invented `investigative historical underscore` and got birdsong. The deeper problem is not the vocabulary but the *mechanism*: **open-ended search asks a language model to produce something deterministic**, which is the same mistake that caused cross-scene shot-id collisions (M5) and the narration-boundary failure that killed a live run. A closed set of moods removes it — picking from a menu is something a model is reliably good at, and guessing search vocabulary is not. Curation also gives what search cannot: tracks chosen **by ear**, licences verified once by a human rather than gated per result, no duration floor needed (nobody files a 2.5-second air horn under `documentary_dark/`), and determinism — I5 wants rendering to be a pure function, and today the same project can get different music on different days, or none.

This needs **no pipeline change**. `MusicProvider` already exists as an interface, so this is a third implementation selected by `MUSIC_PROVIDER=local`. It is the exact analogue of `project_assets` as ladder rung 1 for images: human-curated content outranks search, which is the whole thesis of M6.5.

Layout, as proposed: `assets/music/{documentary_dark,documentary_mystery,documentary_ambient,industrial,historical_epic,emotional}/`.

**M5 — the manifest is committed; the audio is not.** `manifest.json` carries title, author, licence, source URL, mood, duration and content hash per track, and is committed. The audio files are gitignored like `storage/`. Without the manifest, CC-BY attribution obligations and provenance live only in someone's memory, and a fresh clone has no music with no explanation of why. The content hash also lets a track participate in the render fingerprint (M8 step 6) so music becomes part of what makes a render reproducible.

**M6 — the Director selects a mood from the closed set; it no longer invents search terms for the local provider.** This is the change that actually fixes M1. Keep `search_terms` in `music_plan` for the fallback provider, but the local provider matches on the category.

**M7 — a mood with no matching track degrades; it never forces a wrong pick.** If a script genuinely does not fit the six categories, fall back to the search provider, and past that to silence. Forcing a selection because an enum demanded one would reintroduce, by a different route, exactly the confidently-wrong behaviour A30a exists to prevent. **Attribution:** CC-BY requires credit, and where it appears (video, description, or both) should be decided before the renderer is built rather than retrofitted.

**M8 — the Director chooses the category, and it chooses exactly one for the whole video.** The Director is the only agent that sees the whole script, and it already derives the emotional arc (`music_plan.mood`/`tempo`/`energy_arc`, plus every `scene.emotion`), so the choice costs no extra call. **One bed per video, not one per scene:** at D7's 90-second ceiling, swapping tracks reads as choppy rather than dynamic — short-form documentary gets its dynamics from ducking under narration and the volume envelope, both of which already exist. Per-scene scoring becomes right somewhere past two or three minutes, and the input for it is already present (`scene.emotion`), so this is a deferral, not a dead end.

**M9 — every category must be defined in the prompt by WHEN TO USE IT, never just named.** This is the trap that would otherwise reproduce M1 one level up: `documentary_dark` versus `historical_epic` versus `industrial` means nothing to a model, so it would guess at a private taxonomy exactly as it guessed at stock-library vocabulary. Each category needs a usage description — e.g. *`documentary_dark`: sombre, minor key; grim or morally heavy material — war, exploitation, human cost*; *`industrial`: mechanical, rhythmic, driving; factories, machinery, process and scale*; *`documentary_ambient`: neutral texture, minimal; explanatory passages where the narration carries everything*.

**M10 — hold two or three tracks per category and pick deterministically from the project seed.** With one track per folder, every video on a similar topic gets identical music. Seeding the pick from the existing per-project seed (`_project_seed`) keeps a given project reproducible — I5 — while letting different projects vary.

**Sourcing:** Incompetech (Kevin MacLeod) is CC-BY, genuinely good documentary scoring, and already categorised close to these folder names; Free Music Archive and Jamendo's CC-BY subset fill gaps.

**Sequencing:** land M1–M3 first (the retry endpoint is useful whatever the provider, and M2's duration floor protects the search fallback), render the pending video (re-rendering with music later is free — local ffmpeg, cached narration), then build `LocalMusicProvider`.

## N1 — narration must be redoable with a different voice (2026-08-15)

The first real render produced a voice the user judged badly wrong for Hinglish: `T3s9anIvGvoeogXyFyMt` is not an Indian-accent voice, so it read Romanised Hindi with English phonetics. Choosing a better one is not the problem — **re-running with it is.** `NarrationStep.is_satisfied` returns true whenever the active timeline is `produced_by == NARRATION`, so once narration has run, it can never run again. The voice is effectively frozen at the first attempt.

This is the **third** instance of one pattern: an automated choice a human disagrees with, with no way to redo it. The first was a per-shot image (fixed by A24's override), the second was music (fixed by M3's retry endpoint), and this is narration. Each was discovered the same way — a real run, a human unhappy with the result, and no route back. Worth noticing as a design smell rather than patching a third time in isolation: **any step that makes a creative choice needs a human redo path, and that should be a default assumption when adding one, not a retrofit.**

**The fix is small because the plumbing already exists.** `NarrationStep.run` reads `timeline.metadata.voice_id or settings.elevenlabs_voice_id`, so a per-project voice is already honoured — nothing reads it today because nothing writes it. So: an endpoint appends a `produced_by=HUMAN` version setting `metadata.voice_id`, which makes `is_satisfied` false (the active version is no longer NARRATION), so narration re-runs and picks up the new voice.

Two properties fall out for free and are worth keeping:
- **Switching back is free.** The narration cache is keyed on `hash(text + voice_id + model + output_format)`, so audio for a previously-used voice is still cached — trying three voices and returning to the first costs nothing the second time.
- **Durations recompute correctly.** A different voice speaks at a different pace, narration is the master clock (D1), and its new version reconciles every shot boundary. Human-locked bindings carry forward across that bump (A11/A20/A25), which the first render already proved under real conditions.

## Implementation notes (2026-08-15) — N1: a third redo path, and the considered call about sharing one

### The shared-shape question, decided rather than assumed

This is the third occurrence of one pattern (per-shot image override,
M3's music retry, now this), and the coordinator explicitly asked
whether the two that already existed "want a shared shape" before a
third bespoke endpoint got built - not a rhetorical question, an actual
decision to make and record.

**Verdict: extract the mechanical TAIL, keep the domain-specific FRONT
separate.** Looking at `override_shot_asset`, `retry_music_selection`,
and the new `retry_narration_voice` side by side, the tail - compute
`was_already_approved` (timeline already `APPROVED` or already
`produced_by=NARRATION`), call `append_version(produced_by=HUMAN,
transform=..., owns=...)`, re-approve if it was already approved,
resume the engine - is now byte-for-byte identical between the music
and narration endpoints. That is reusable PLUMBING. The front half -
what precondition to check, what the correction even IS, what
`transform`/`owns` it needs - is genuinely different every time (an
uploaded file plus asset-hash dedup for a shot; search terms for music;
a bare voice id for narration), and folding that into one generic
"correct an asset choice" endpoint would hide the interesting,
domain-specific logic behind a parameter bag - the speculative
framework the coordinator explicitly did not want built.

So: a new private helper, `_resume_after_human_correction` (`app/api/
projects.py`), holds exactly the tail. `retry_music_selection` was
refactored to call it (no behaviour change - same tests should still
pass unmodified). The new `retry_narration_voice` calls it too.
**`override_shot_asset` deliberately still does NOT use it** - it has a
genuinely different shape: it must create and flush a `ShotBinding` row
using the NEW version's id strictly BETWEEN the `append_version` call
and `engine.run()` (which reads bindings for the active version the
moment it starts), so the helper has nowhere to run that step without
either special-casing it or adding a mid-flow callback parameter - which
would just reintroduce the "generic parameter bag" problem one level
down. Three near-identical endpoints, one of which stays a near-copy of
the other two's SHAPE without sharing their CODE, was judged clearer
than a single endpoint with a callback threaded through its middle.

### The fix itself

New `POST /projects/{id}/narration/retry` (`RetryNarrationVoiceRequest
{voice_id: str}`, required - unlike music's optional `search_terms`,
there is no meaningful "retry with the unchanged voice" for narration:
it would hit the identical cache entry and produce a wasted version
bump). Sets `metadata.voice_id` via `append_version(produced_by=HUMAN,
owns={"metadata"})`, which is the entire fix - `NarrationStep.run`
already reads `metadata.voice_id or settings.elevenlabs_voice_id`, and
`is_satisfied` already keys on `produced_by == NARRATION` alone, so
nothing about either needed to change.

### Verified, not merely reasoned about - against a throwaway project, DRY_RUN, zero real ElevenLabs calls

Every property the coordinator asked to see proven was checked directly
against the real database (never the live project - a throwaway one,
created and deleted the same way the A30/M3 measurements were):

1. **`compute_narration_content_hash` differs by `voice_id`** for
   identical text (the property switching-costs-nothing and
   switching-back-is-free both rest on) - confirmed directly.
2. **A real `NarrationStep().run()` with voice A** creates one
   `narration` row, sets `produced_by=NARRATION`, flips `is_satisfied`
   to `True`.
3. **The retry transform** (identical in shape to the endpoint's own)
   sets `metadata.voice_id=B` via a `produced_by=HUMAN` version and
   flips `is_satisfied` back to `False`.
4. **Re-running `NarrationStep` with voice B** creates a genuinely NEW
   row at voice B's own content hash - a real re-synthesis, not a
   silent no-op.
5. **Retrying back to voice A** and re-running `NarrationStep` creates
   NO new row - the narration-row count stays exactly where it was
   after step 2. This is the property the coordinator most wanted
   proven, and it holds.
6. **Fresh `ShotBinding` rows postdate a simulated "already rendered"
   file's mtime** after the voice-change version bumps - proving
   `RenderStep.is_satisfied`'s own binding-timestamp comparison (already
   existing code, `TimelineService._carry_forward_bindings` re-inserts
   every binding row - locked or not - on every `append_version`, always
   with a fresh `updated_at`) would correctly treat the pre-existing
   render as stale and redo it, never silently serving the old voice's
   video back.
7. **`compute_render_fingerprint` differs when only
   `narration_content_hashes` differs** - a pure, DB-free check,
   confirming the render's own cache-hit path can never falsely reuse a
   different voice's output either. (This property is also covered
   generically, and permanently, by the pre-existing
   `tests/unit/renderer/test_fingerprint.py
   ::test_different_narration_changes_the_fingerprint` - no new test
   needed there.)

All seven passed on the first clean run. The throwaway project was
deleted afterward via the same derived-from-schema, child-tables-first
approach used for the A30 and M3 measurements.

### Tests written, not run

`tests/integration/test_narration_voice_retry.py` (3 cases: the full
retry-and-resynthesise cycle with `is_satisfied` checked at each stage;
the switch-back-costs-nothing cache-hit proof; the carry-forward
staleness proof) and `tests/e2e/test_narration_retry_api.py` (4 cases
over the real HTTP route: missing timeline, empty `voice_id` rejected,
the voice actually changing and narration re-running, and the
re-approval belt-and-braces). All DRY_RUN + `FakeNarrationProvider` -
**no real ElevenLabs calls, no money spent**, matching the constraint;
`FakeNarrationProvider` still writes real content-hash-keyed rows (fake
bytes), which is exactly what the cache-hit tests need. Not executed in
this session - the live project (`194ad0e7-...`, now fully rendered) is
still in the same shared dev Postgres, and `pytest` truncates every
table via `tests/conftest.py`'s autouse `clean_database` fixture.
`ruff check backend`, `black --check backend` (1 file auto-reformatted),
`mypy backend/app` all run normally (no database touched) and are
clean.

## Constraint validation split: planning heuristics vs. structural invariants (2026-08-16) — the A26 correction

**A26's own claim, quoted above, is wrong, and this section says so
plainly rather than quietly patching around it**: *"This is not a
deadlock: the remedy is always available, because a per-shot upload
(A24) bypasses every gate and always resolves."* A live project
(`b0969377-...`) reached `awaiting_review` with one failed shot, and
the prescribed remedy - `POST /shots/{id}/override` - itself failed:

```
POST /shots/sc_01_sh_02/override
-> failed | timeline violates creative constraints:
     ['shot sc_01_sh_03 duration_s=0.6150000000000002 outside [1.5, 8.0]',
      'shot sc_04_sh_01 duration_s=1.498 outside [1.5, 8.0]']
```

The override appends its own `produced_by=HUMAN` version exactly as
designed; the durations it got flagged for are ones NARRATION produced,
long before this shot ever failed. There was no way to finish this
project at all - a genuine deadlock, not the "always resolves" A26
promised.

### Why: the exemption was tied to the wrong thing

`GenerateTimelineStep._is_fully_planned` already knew narration-
reconciled durations must not be re-judged against
`min_shot_duration_s`/`max_shot_duration_s` (M8's own settled open
decision: "let per-shot duration exceed its cap - the cap is a planning
heuristic, the narration is real"). But it encoded that as `if
timeline.produced_by == ProducedBy.NARRATION: return True` - a check
against the version that JUST landed, not against the Timeline's
history. The moment ANY later version appends on top - a per-shot
override, a music retry, a narration-voice retry, literally anything -
`produced_by` is no longer `NARRATION`, the bypass stops firing, and
`validate_constraints` re-applies planning-time bounds to numbers that
were never planning estimates to begin with. `sc_04_sh_01` at 1.498s
against a 1.5s floor is the sharpest illustration: two milliseconds of
float noise, flagged as a creative violation, by a check that was never
wrong about the NUMBER, only about which versions it was allowed to
exempt.

### The fix: the category is now explicit, not a special case on `produced_by`

Decided over the coordinator's own candidates (their stated mild
preference, adopted): **the distinction between "always-true structural
invariant" and "planning-time heuristic" is now a real split inside
`Timeline.validate_constraints` itself** (`app/schemas/timeline.py`),
not a condition duplicated at every call site that happens to know
about narration:

- `_validate_structural_invariants` - total video duration, scene
  count, shot count, duplicate shot ids. Always enforced, every
  version, forever. Nothing about narration, an override, or any other
  later version ever has a legitimate reason to exceed these - they
  describe the shape of a renderable Timeline, not a creative estimate,
  and `NarrationStep` itself already refuses to reconcile past the
  video-duration cap (raises `PermanentError` before persisting
  anything), so a timeline that passed through narration successfully
  can never legitimately violate this half either.
- `_validate_planning_time_shot_bounds` - the per-shot `duration_s`
  bounds - skipped entirely whenever `self.metadata.narration_locked`
  is set.
- `Timeline.metadata.narration_locked: bool = False` - a new, PERSISTENT
  field, set once by `NarrationStep`'s own reconciliation
  (`app/workflow/steps/narration.py::_apply_durations`) and never reset
  by anything downstream - it survives every later `append_version`
  the same way `metadata.voice_id` already does, because nothing about
  a later version's own `owns` set touches it unless that version
  explicitly means to. This is what makes the exemption survive past
  the one version immediately after narration, closing the exact gap
  A26 hit.
- `GenerateTimelineStep._is_fully_planned` **lost its `produced_by ==
  NARRATION` special case entirely** - it now just calls
  `validate_constraints` uniformly, the same way it always could have,
  and gets the right answer for every version because the Timeline
  itself now carries the fact that decides it. This is also why the
  fix generalises: a third and fourth caller that need the identical
  reasoning (the coordinator's own prediction: "there will be a third")
  get it for free by calling the same method, rather than needing to
  learn about `narration_locked` and duplicate the check themselves.

**Not fixed by widening the bounds or adding a float epsilon** (both
explicitly ruled out) - either would have quietly accepted the 1.498s
case while leaving 0.615s exactly as broken as before, since 0.615 is
nowhere near 1.5 by any reasonable epsilon. The fix is categorical, not
numeric: a measured duration is not re-judged against a planning
heuristic at all, regardless of by how much it misses the old bound.

### Verified, not merely reasoned about

Directly against the exact reported numbers (pure, no database): a
0.615s shot on a NOT-narration-locked timeline still correctly fails
(the planning-time case must keep working); the same shot on a
narration-locked timeline produced by `NARRATION` itself passes (the
case that already worked); the same shot on a narration-locked timeline
produced by `HUMAN` - **the exact reported bug** - now passes too; the
1.498s float-noise case passes; and duplicate shot ids / an inflated
total duration / too many shots all still fail even when
`narration_locked` is set, proving the exemption is exactly as narrow
as intended. Then through the REAL mechanism end to end, on a
throwaway project created and deleted the same way every other live
measurement this session was (never touching any of the four live
projects): seeded a `produced_by=NARRATION` timeline with a 0.615s shot
and `narration_locked=True`, confirmed `GenerateTimelineStep
.is_satisfied` reads `True`; appended a SECOND, `produced_by=HUMAN`
version on top (mirroring the real override) that never touches
`metadata` at all; confirmed `narration_locked` survived unchanged
(`True`) and `is_satisfied` still reads `True` - the exact deadlock,
reproduced and proven fixed through the real code path, not just the
isolated validation function.

7 new tests in `tests/unit/timeline/test_validate_constraints.py` (the
still-fails-before-narration case, the works-on-the-narration-version-
itself case, **the exact reported bug on a later HUMAN version**, the
1.498s float-noise case, and three structural-invariants-still-enforced
cases: duplicate ids, total duration, shot count) and 2 in
`tests/integration/test_narration_locked_constraints.py` (the same
proof through the real `TimelineService`/`GenerateTimelineStep`
mechanism). `ruff check backend`, `black --check backend` (1 file
auto-reformatted), `mypy backend/app` all clean from the repo root.
**The suite itself was NOT run** - four live projects
(`194ad0e7-...`, `2fa282b4-...`, `f64210fc-...`, `b0969377-...` - the
last mid-run and stuck on exactly this bug) sit in the same shared dev
Postgres.

**The honest correction to A26 itself**: the decision's own text
(above, in the M6.5 table) claims "this is not a deadlock" on the
strength of the override endpoint always resolving a failed shot. That
was true of the override's OWN logic, but false of the system as a
whole, because the remedy path re-entered general Timeline validation
that could independently reject the very state the remedy was trying
to produce. A26 is not wrong about the override mechanism; it was wrong
to declare the deadlock impossible without checking whether anything
downstream of the override could reintroduce one. The lesson generalises
past this one bug: a remedy that appends a new Timeline version is only
as good as every check that version has to pass afterward, and each of
those checks needs to be examined for the same "does this apply to
MEASURED reality, not just planning estimates" question - not assumed
clear because the immediate mechanism looks correct in isolation.

## S1 — the Shot Planner stops doing character arithmetic (2026-08-15)

Three failures, one root cause, finally addressed at the root rather than patched a fourth time:

1. **Cross-scene shot-id collisions** — the model reproduced the prompt's example id verbatim in every scene. Patched by namespacing ids in code.
2. **Outer narration boundaries off by four characters** — `narration_end=140` on a 144-character scene ending in a trailing space. **Killed a live paid run.** Patched by snapping the two outer edges.
3. **Internal boundaries splitting words and graphemes** — `Leuna-Werke` cut into `L` + `euna-Werke`, `इससे` into `इ` + `ससे`, and `दिन` into `द` + `िन`, which separates a Devanagari dependent vowel sign from its consonant and produces malformed text, not merely truncated text. 6 of 21 shots affected on a real run.

Each patch bought one round before the next variant appeared. The common factor is that **we asked a language model to do character arithmetic**, which is not a prompt-quality problem and not a post-processing problem — it is the wrong job for the tool.

**The fix: the Shot Planner no longer emits character offsets.** Each scene's `narration_text` is pre-split into numbered fragments deterministically in code, on sentence and line boundaries. The planner receives the numbered fragments and chooses a **contiguous range of fragment indices** per shot. Code converts those ranges back into exact character spans.

`Shot.narration_span` is unchanged in the persisted schema — this changes what the *planner is asked for*, not what the Timeline stores, so `narration_fit.py`, the master clock and the renderer are all untouched.

What falls out:
- **A mid-word boundary becomes structurally impossible**, rather than detected and corrected.
- Coverage and contiguity become "the ranges tile 1..N" — checkable and repairable in code instead of by re-asking the model.
- The task gets *easier* for the model: "this shot covers fragments 1–2" is a natural judgement; counting to 144 is not.
- Devanagari needs no special handling at all, which is itself evidence the design is right.

The outer-boundary snap from (2) stays as a cheap backstop against a malformed range.

**The general lesson, worth stating plainly because it has now cost three fixes and one live run:** deterministic structural facts belong in code — and when a model keeps getting the same thing wrong, the question is not how to correct its answer but whether it should have been asked the question at all.

## S2 — the Scene Planner stops reproducing the script verbatim (2026-08-16)

S1 fixed the Shot Planner's character arithmetic; the Scene Planner had the identical defect one level up. It was asked to retype the user's script into per-scene `narration_text`, and the planner validated that concatenating every scene reproduced the script's word content exactly — the same "ask a model to reproduce deterministic text" mistake, and it failed the same way: on a real run it failed that check twice in a row and cost a full planning call before the repair budget forced a permanent error. This is the completion of the pattern S1 started, not a fourth, unrelated fix — the fourth and, by construction, last place this particular mistake could live in this pipeline.

**The fix: the same fix.** The script is pre-split into numbered fragments in code, the Scene Planner chooses a contiguous fragment-index range per scene, and code slices the script back into each scene's `narration_text`. Dropping, adding, or reordering a word is now structurally impossible rather than detected and retried — exactly S1's argument, one level up.

**Design decisions, in the order the task asked for them:**

- **The splitter moved, not duplicated.** `split_narration_fragments` used to live at `app/planners/shot/fragments.py`. It is now `app/planners/fragments.py`, imported by both planners. The alternative — the Scene Planner reaching into `app/planners/shot/`, or a second copy of the same ~250-line module — was rejected on the same grounds S1's own docstring already argues against duplication: one deterministic algorithm, one place it can be wrong. Nothing in the module is shot-specific (it always operated on "narration text", never on anything shot-shaped), so the move is a pure rename with no logic change. The refactor was mechanical and complete: `app/planners/shot/planner.py`'s import line, both existing test files that imported the old path (`tests/unit/planners/test_fragments.py`, `tests/unit/planners/test_shot_planner.py`), and one docstring-only path reference in `tests/integration/test_generate_timeline_real.py` were all updated; no file remains at the old `app/planners/shot/fragments.py` path. `app/planners/shot/planner.py`'s own logic — the fragment-range validator, the outer-edge snap, `_to_domain_shot` — was not touched beyond that one import line, per the task's own scope boundary.
- **Granularity composes with S1, and this was checked, not assumed.** After this change the Shot Planner still re-splits each scene's own `narration_text` into its own (finer) fragments. This holds together because `split_narration_fragments` is purely local: `_find_split_points` only scans forward from its current position, and `_merge_whitespace_only_spans` only inspects a fragment's own content — neither looks past the string it is given. A scene's `narration_text` is an exact script slice cut at two of the *script's own* fragment boundaries, so re-running the identical splitter on that exact substring reproduces the identical interior split points. The one place behaviour could in principle differ is at the substring's own edges, and it does not: a script-level fragment boundary is, by construction, either position 0 or the first non-whitespace character after a split trigger, so a scene never starts mid-whitespace; and trailing whitespace collapses the same way whether "no more content" means "end of script" or "end of this scene's slice", because both are simply "nothing further to consider". A scene boundary is therefore always a valid shot-fragment boundary — verified directly (not just reasoned about) against the real splitter: a script with a blank line between two stanzas, sliced at the fragment boundary straddling that blank line, produces a scene whose own re-split matches what splitting the whole script would have produced at that point.
- **Coverage invariant replaces the word-content check, and the old check is kept anyway, as a backstop.** The validator now walks `fragment_start`/`fragment_end` across every scene with a cursor, exactly like the Shot Planner's own tiling check — a gap, overlap, or out-of-range index is a hard failure, and "the script cannot have more scenes than fragments" falls out of the same arithmetic S1 already argued (non-empty disjoint ranges cannot outnumber the fragments to distribute them over). Kept the old concatenate-and-compare check on top, exactly as the task leaned: it costs nothing, and it defends against a bug in *this module's own slicing*, not the model — which is also why it is no longer normalised (lowercased, whitespace-collapsed) the way the old verbatim check was. There is no model-introduced casing or spacing drift left to tolerate once the text is sliced by code from the script itself rather than retyped, so the backstop is a plain, exact string comparison; a mismatch now means this module has a bug, not that the model made a typo.
- **The outer-edge snap made the trip too.** A small drift on the first scene's `fragment_start` or the last scene's `fragment_end` is snapped rather than rejected, mirroring S1's own reasoning and its `_LARGE_FRAGMENT_SNAP_THRESHOLD = 1` (a drift of 1 is the model being imprecise about an inclusive range; more suggests it misread the fragment list) — implemented as a second, separate function in `scene/planner.py` rather than a shared import, since the two operate on different Pydantic models and log different event names, not because the logic is meant to diverge.
- **Whitespace was the actual second-order bug on the last real run, and it is now handled before the model ever sees the script.** The user's script has blank lines between stanzas; under the old verbatim design that whitespace had to land somewhere, and the model's own choices for where produced the earlier blank-shot defect (S1's whitespace-merge note). Under fragment ranges, the blank run is already folded into an adjacent fragment's own span by `split_narration_fragments` before the Scene Planner is ever called — there is no longer a model decision about where the blank line goes, because there is no longer a model decision about narration text at all.

**Verified directly against the real code, not merely reasoned about (pure, no database, no model, no pytest):** the exact fixture that failed twice on a real run — `backend/tests/fixtures/hinglish_final_project.json`, mixed Devanagari/Latin Hinglish with blank lines between stanzas — was split by the real `split_narration_fragments` into 24 fragments, none splitting `Leuna-Werke`, `दिन-रात`, `Fischer-Tropsch`, or `Secunda`; a `ScenePlannerOutput` assigning one scene per fragment was run through the real validator (no violations) and the real `_to_domain_scene` (concatenation reproduced the script character for character). The same script exercised, directly against the real validator and `_to_domain_scene`: clean tiling on a 2-fragment script; a 4-fragment script with a blank line between two stanzas, confirming the blank run lands as trailing whitespace on the earlier scene and the later scene starts clean; a 1-fragment script both ways (one scene succeeds, a second is rejected — outer-edge snap forces the impossible scene's `fragment_end` down to 1 first, so the actual violation is `fragment_end < fragment_start`, not a distinct "too many scenes" message, the identical two-attempts-at-tracing correction S1 needed for the analogous Shot Planner case); a 5-fragment script with an internal gap (fragment 3 skipped), rejected with a "must equal" tiling violation; and the same 5-fragment script with the last scene's `fragment_end` short by 1 and by 3, both silently snapped and reconstructing the script exactly.

New `tests/unit/planners/test_scene_planner.py` (rewritten, 9 tests total): a script whose scenes tile cleanly, a script with blank lines between stanzas, a single-fragment script both ways, an internal gap that fails to tile, both outer-edge snap cases (small drift silent, large drift logged), and the existing too-many-scenes and repair-loop-reuse tests carried over unchanged in intent. `tests/integration/test_generate_timeline_real.py`'s own canned fixture updated mechanically for the new schema (`fragment_start`/`fragment_end` replacing `narration_text` on its `ScenePlanOutput` fixtures) — its own purpose, the four-planner chain's resumability, is unaffected. `ruff check backend`, `black --check backend` (1 file reformatted), `mypy backend/app` all clean from the repo root. **The suite itself was NOT run** — per the same standing instruction as every other change in this document, a full-suite run was in flight in another process against the same shared dev Postgres `pytest` truncates via `tests/conftest.py`'s autouse `clean_database` fixture.

**Scope discipline honoured**: touched the Scene Planner's schema (`fragment_start`/`fragment_end` replacing `narration_text` on `ScenePlanOutput`), its prompt, its validator, and the shared fragment module's location and docstring. The Director, the Asset Planner, `Scene.narration_text`'s persisted shape, `narration_fit.py`, the renderer, and the Shot Planner's own logic (beyond the one import line) were not touched.

**Two defects found by running the full suite for the first time in ~19 commits, both fixed, neither in application code:**

1. **A missed mechanical call site.** `tests/integration/test_generate_timeline_real.py::test_crash_mid_chain_resumes_at_the_next_planner_stage_only` still called `_shot_output(scene_id, narration_text, duration_s)` with the old three-argument signature — the S2 pass that dropped `narration_text` from `_shot_output` (it had been unused since S1) updated the two call sites in `_full_response_queue` but missed this third one, in a different test function further down the same file. Fixed by dropping the stale argument at this call site too; the test's own point — that a resumed run does not re-invoke the Director or Scene Planner — is unaffected, since it never depended on that argument's value.
2. **A test asserting its own wrong intent, found and left uncorrected since the day it was written (2026-08-16, the whitespace-merge fix above).** `test_a_whitespace_only_fragment_in_the_middle_merges_forward` asserted that a blank run *between* two sentences merges forward into the fragment that follows — by analogy with the leading-blank-run cases, but never actually true of its own input, and apparently never run since (the suite had not passed end to end in ~19 commits). The real behaviour: `_find_split_points` skips a trigger's trailing whitespace when computing where the *next* fragment starts, so that whitespace already belongs to the end of the fragment *before* the trigger, before the merge pass ever runs — there is no standalone whitespace-only fragment there for it to fold forward. More generally, verified by fuzzing the real splitter across ~200k random combinations of sentence/clause/newline tokens: an interior (non-leading) whitespace-only fragment cannot arise via either split pass at all, because every split point other than the mandatory 0 is, by construction, the position of a non-whitespace character. Only a fragment starting at position 0 — the text opening with whitespace before any real content — can ever be whitespace-only, exactly the case the two reported-scene tests and the degenerate-input tests already cover. Fixed by rewriting the test (renamed to `test_a_blank_run_between_sentences_is_absorbed_by_the_preceding_fragment`) to assert what the code actually does — the blank run trails the *preceding* fragment, not leads the following one — and by adding this same argument to `app/planners/fragments.py`'s own docstring, so the "forward merge" section can no longer be misread as reachable mid-document. The docstring's account of *why* the fix works (fold whitespace into an adjacent fragment rather than emit it standalone) was always correct; only this one test's claim about *which* fragment reaches that code path was wrong, and it has been corrected rather than loosened or deleted.

Re-verified after both fixes: `ruff check backend`, `black --check backend`, `mypy backend/app` clean from the repo root, and the full suite green.

## R1–R3 — three defects found while testing a two-line config change (2026-08-16)

The intent was to raise `MUSIC_BED_GAIN_DB`/`MUSIC_DUCK_GAIN_DB` and listen. It cost real money and produced a broken video, and the three reasons are each worth fixing.

**R1 — the fixture round-trip does not restore a working project, and this is the one that cost money.** `export_test_project.py` writes `shot_binding` rows carrying their **original** `timeline_version`, while `seed_test_project.py` recreates the timeline **renumbered**. Measured on a real restore: bindings landed at versions 5–11 while only versions 1–2 of the timeline existed, so the **active timeline had zero bindings**. Narration linkage and generated clips did not survive either — a render from the restored state produced no narration at all and 7 of 19 shots as placeholders.

The consequence is worse than a broken render. `ResolveAssetsStep` saw no bindings at the active version, concluded nothing had been resolved, and **began resolving from scratch — including paid OpenAI vision calls.** The script exists precisely so that "planning is the expensive, non-deterministic part… snapshot it rather than re-buying it every time the shared dev database gets truncated". It silently re-buys it. **Every restore is currently a trap**, and no further live testing should lean on one until this is fixed.

The fix must remap binding (and narration, and generated-clip) references onto the renumbered versions, and the round-trip needs a test that actually asserts a restored project is *renderable* — the existing check only asserts rows exist.

**R1 fixed, 2026-08-16.** Three separate bugs, all in the same two scripts, all silent:

1. `export_test_project.py`'s `bindings` query had no `timeline_version` filter at all — it exported every superseded copy of every binding the project ever had (133 rows across versions 5–11 for a 19-shot project), and `seed_test_project.py` inserted them at those original version numbers. Fixed by exporting only the active version's bindings, and by having the seed script **remap** every binding onto whichever version the restore actually produces (`TimelineService.append_version`'s own return value), never the number recorded in the fixture.

   **Remap, not preserve** — decided and worth recording since there was a real choice here. Preserving the original version number would mean either bypassing `TimelineService` to force-insert a specific version (reintroducing the "no other code path may touch this table directly" hazard its own docstring warns about, for a purely cosmetic benefit), or replaying every intermediate version the fixture never captured (it deliberately only snapshots the final state — see that script's docstring). Remapping costs nothing real: nothing downstream cares what number the active version happens to be, only that bindings/narration/clips all agree on it, which is exactly what `TimelineService`'s own `append_version` + `_carry_forward_bindings` machinery already guarantees for every *other* version transition in this codebase. A fixture also stays more readable this way.
2. `seed_test_project.py` hardcoded `produced_by=ProducedBy.ASSET_PLANNER` on the restored version regardless of what the fixture actually recorded. A fixture snapshotted after narration (`produced_by=narration`) came back stamped `asset_planner`, and `RenderStep._resolve_narration_audio` reads that exact field to decide whether narration is safe to mux — so the restore rendered silently even with correct narration rows and audio files sitting right there. Fixed by taking `produced_by` from the fixture's own `timeline_document`.
3. `export_test_project.py` never queried `generated_clip` at all, so any AI-generated shot (ladder rungs 5–6) restored with no way to point at its own media — 7 of 19 shots on the real fixture. Fixed by exporting the `generated_clip` rows the exported bindings reference (keyed on `prompt_hash`, the same global dedup key `ResolveAssetsStep` already cache-hits against, never the row's own database `id`). Generated media has no `source_url`, so unlike an asset it cannot be re-downloaded, and regenerating it would not reproduce it — image/video generation is provider-side non-deterministic even at a fixed seed. `seed_test_project.py` therefore restores a clip only if its bytes are still on disk, and **fails loudly (`SystemExit`) rather than placeholding** if they are not — the same principle F5a and this section both lean on: a silent downgrade is worse than a stop. The same loud-failure check now also covers *any* binding claiming resolved media it cannot back with either an asset or a clip, which incidentally means an old fixture exported before this fix (carrying clip-referencing bindings but no clip data at all) now fails to seed instead of quietly placeholding — accepted, since that fixture's source project no longer exists to re-export from a real regression only for fixtures nobody can re-generate.

   The real `hinglish_final_project` fixture also turned out to reference one human-uploaded asset (rung `project_assets`) with no `source_url` — the pre-existing loud-failure path for uploads (see that script's docstring) caught it correctly the first time this fixture was seeded in anger, which is exactly the intended behaviour, not a new bug.

   **Repo-size trade-off, recorded rather than left for someone to discover later:** generated clips and narration audio cannot be reconstructed from the fixture JSON alone, so their real bytes now have to be committed too. `tests/fixtures/hinglish_final_project_media/` adds **~8.3MB** (1 uploaded image, 7 generated images, 6 narration clips, 1 music track) for one fixture. This is the right call — the alternative is a fixture that silently can't restore the thing it exists to restore — but it means every future fixture that survives past generation/narration adds several more megabytes to the repository, permanently (git history doesn't shrink when a fixture is later replaced). Worth revisiting with LFS or a similar mechanism if this grows into a real cost; not worth blocking on today.

   New test: `tests/integration/test_fixture_round_trip.py` seeds this fixture for real (via the actual CLI script, run as a subprocess so its module-level `os.chdir` doesn't leak into the test session) and proves — not just asserts rows exist — that every shot's binding at the active version resolves to real media, that narration resolves to real audio, that both `ResolveAssetsStep` passes and `NarrationStep` already report `is_satisfied()`, and that a real `render_video()` call produces a video with both an audio and a video stream. A second test confirms the loud-failure path: withhold a generated clip's bytes and the seed refuses rather than placeholding.

   This fix is also what unblocked R2/R3's own investigation: a restored project could finally produce narration, so the `MUSIC_BED_GAIN_DB`/`MUSIC_DUCK_GAIN_DB` change that started this whole entry could actually be re-rendered and listened to (three times, at no cost — local ffmpeg only) rather than measured against a silent video. See the updated "What did work" note below.

**R2 — the render fingerprint omits the audio mix settings.** `compute_render_fingerprint` covers the timeline, asset/narration/music content hashes, `width`/`height`/`fps`/`pixel_format` and the ffmpeg version — but **not** `music_bed_gain_db`/`music_duck_gain_db`, which are read from config at mux time. I5 states the render is a pure function of its inputs; these are inputs. Change the mix and re-render and you get the **cached bytes back**, silently. The only reason this test rendered at all is that the previous `final.mp4` had been deleted, so the cache lookup missed on the absent file rather than on the fingerprint.

**R3 — there is no render-only path.** `POST /render` is not a render command; it advances the entire workflow from the first unsatisfied step. For a step the documentation describes as a pure function of the timeline, having no way to invoke *only* it is wrong — and it is what turned "re-render to hear a mix change" into an unplanned paid run. A render-only endpoint (or an explicit `steps=` filter) would make re-rendering as cheap as it is supposed to be.

**What did work:** the gain change itself, measured — the ducked bed moved from **-52.6 dB to -38.6 dB mean**, 14 dB louder, exactly as intended. The balance against narration remains unverified, because the restored project could not produce narration.

**Follow-up, same day, after R1 was fixed:** with the restored project finally rendering real narration, the mix was re-rendered and listened to three more times against the actual voice track, not just measured in isolation. The ducked bed went **-52.6 → -46.6 → -40.6 dB mean** across the three attempts, while the full mix's overall loudness held steady at **-26.4 dB** throughout (narration is unaffected by this setting — only the bed moves). The original `-22.0`/`-32.0` defaults made the bed nearly inaudible under this script's near-continuous speech; the settled values, now the defaults in `app/core/config.py` (`music_bed_gain_db=-14.0`, `music_duck_gain_db=-20.0`, previously only in one machine's gitignored `.env`), are 12dB louder than the original and comfortably audible without ever competing with the narrator. Recorded in the config comment itself so nobody "tidies" them back toward the old numbers without re-measuring.

**R2 fixed, 2026-08-16.** `compute_render_fingerprint` (`app/renderer/fingerprint.py`) gained two new required keyword parameters, `music_bed_gain_db`/`music_duck_gain_db`, hashed unconditionally (present even as a value on a render with no music selected at all, mirroring how `music_content_hash` is always present, `None` when there is none) — I5's promise is "same fingerprint → provably identical output", so a false MISS (an unrelated config change forces a harmless re-render) is acceptable where a false HIT (silently serving stale audio) is not. `RenderStep.render_video`'s call site now passes `settings.music_bed_gain_db`/`settings.music_duck_gain_db` straight through, the same config values `mux_music` itself already reads at mux time. Every fingerprint computed before this fix is now invalid and will MISS once — correct and cheap, since a miss just re-renders.

Proven at two levels: `tests/unit/renderer/test_fingerprint.py` gained `test_different_bed_gain_changes_the_fingerprint`/`test_different_duck_gain_changes_the_fingerprint` (pure, changing one value changes the hash), and `tests/integration/test_render_fingerprint_cache.py::test_changing_only_the_bed_gain_forces_a_real_rerender` proves it against the REAL pipeline — one project, one real (locally-synthesised) music track, rendered twice with only `settings.music_bed_gain_db` differing between calls, asserting both that `render_timeline`'s real encoder genuinely ran a second time (not a cache hit copying the first render's bytes) and that the two `render` rows recorded two distinct fingerprints.

**Fingerprint audit (asked for regardless of whether anything else needed changing):** every other real render input traced through `app/renderer/slideshow.py`, `app/renderer/audio.py`, `app/renderer/music.py`, `app/renderer/still.py`, and `app/renderer/placeholder.py` reads either its `RenderSettings` parameter (width/height/fps/pixel_format/ffmpeg_binary/ffprobe_binary — already covered, `ffmpeg_binary`/`ffprobe_binary` correctly excluded as documented, they're paths on this machine, not inputs to the encode) or the Timeline/binding content passed into it — nothing else reaches into `app.core.config.settings` for anything that affects a rendered pixel or sample, except the two gains just fixed. Three things worth recording even though none needed a code change:
- `burn_captions`/`caption_font` (`app/core/config.py`) are **not wired into any render code path at all** today (`BURN_CAPTIONS=false`, ASS generation "not built" — Phase M8's own Done-when list). Not a live fingerprint gap, but whoever wires captions in later must add the caption content/font to the fingerprint at the same time, or it will reproduce this exact bug for captions.
- `default_transition_duration_s` is likewise unused outside `config.py` itself — every shot's actual transition duration already lives on the Timeline (`Shot.transition_out.duration_s`), which the fingerprint already hashes as ordinary timeline content. Dead config, not a gap.
- The `settings` JSON column `RenderRepository.insert_completed` stores per render row is a debugging label, not the cache key, and was deliberately left recording only width/height/fps/pixel_format (unchanged) — the actual gain values are visible in `app/core/config.py` for whichever build produced the row, and adding them to a column nothing reads back would be scope creep on a fix that isn't the fingerprint itself.

**R3 fixed, 2026-08-16.** New `POST /projects/{id}/render/only` (`app/api/projects.py::render_only`, backed by `app/workflow/render_only.py`) invokes **only** the render step.

*Design chosen, and why, over the alternative:* a dedicated endpoint, not a `steps=` query filter on `POST /render`. A filter needs a validated enum plus a runtime branch choosing a step list from user input — the exact shape that turns "can this ever reach a paid step" into a question about validation logic rather than about what code exists to run at all. A second, narrow endpoint whose entire step list is a two-item, non-parameterised module constant (`RENDER_ONLY_STEPS`) answers that question by inspection, once. `POST /render/draft` already established the "sibling `/render/...` route for a variant of rendering" shape in this codebase, so this is not a new pattern.

*Structurally incapable, not "checked and trusted":* `RENDER_ONLY_STEPS = [RenderStep(), CompleteStep()]` — `CompleteStep` rides along only to flip `project.status` back to `COMPLETED` after a successful render (it touches nothing else and calls no provider; omitting it would leave `project.status` stuck at `RENDERING` forever, since the normal pipeline's `CompleteStep` never gets a turn). `WorkflowEngine.run()` (`app/workflow/engine.py`) only ever iterates `self._steps`, so an engine built from this list has **no code path** to `GenerateTimelineStep`, `ResolveAssetsStep`, `SelectMusicStep`, or `NarrationStep` — the steps that can touch a paid provider, directly or via a planner. This holds even if the precondition check below were buggy: a wrong precondition result could at worst let an ill-advised render through (placeholders for unresolved shots), never a provider call, because the provider-calling step objects are simply absent from the list the engine was constructed with. That is the literal "incapable, not unlikely" property asked for.

*Why a precondition check exists anyway, given the list above already guarantees safety:* honesty, not safety. A render-only trigger on a project that never reached the real render step (unapproved plan, narration never run, shots still unresolved, or a shot still `failed` at the review gate) would otherwise silently render placeholders — `RenderStep` is deliberately tolerant of missing media (Principle 10). `render_precondition_gap` (`app/workflow/render_only.py`) re-runs the exact same `is_satisfied()` check every step ahead of render in `DEFAULT_PIPELINE` already performs (every one a read-only DB query, never a provider call, even here) and returns the name of the first one still unsatisfied; the endpoint turns that into a `409` naming the step, rather than quietly advancing anything or rendering an incomplete project.

Proven at three levels: `tests/unit/workflow/test_render_only.py` (pure — `RENDER_ONLY_STEPS` contains exactly `RenderStep`+`CompleteStep` and nothing else, and every real pipeline step other than "render"/"complete" is a checked precondition); `tests/integration/test_render_only.py` (`render_precondition_gap` against a real, progressively-advanced project — asserts the gap names `generate_timeline`, then `resolve_assets_search`, then `await_approval`, then `narration`, then `None` once a real `NarrationStep.run()` pass completes it, then `await_review` once a binding is flipped to `failed`); and `tests/e2e/test_render_only_api.py` over the real HTTP surface (`409` before the pipeline ever ran, `409` while still awaiting approval, and — the core proof — every OTHER real step's `run()` monkeypatched to raise, a real render forced by deleting `final.mp4` first, and the render-only trigger still ending `completed` with the deleted file back on disk, never surfacing the planted exception).

## Backlog — deferred, not blocking

Raised during the first real Hinglish run (2026-08-15, project `194ad0e7`, fixture `hinglish_test_project`). Deliberately not fixed then, so the run could continue.

- **LLM calls are never costed.** `llm_call.cost_cents` is `0` on every row — the column exists and token counts are recorded faithfully (that run: 23,607 in / 12,817 out across 15 planning calls on `gpt-5.6-terra`, plus 355,110 in / 768 out across 13 `gpt-4o-mini` vision calls), but nothing prices them. **Deferred by the user, 2026-08-15.** Needs a per-model price table in config and a cost computed at insert.
- ~~**The approval-gate cost estimate reads 0¢ when generation is pending.**~~ **FIXED 2026-08-16** (one-gate work, task 5). Same run: 10 of 14 shots were queued to generate and `estimated_cost_cents` still showed `0`, because the estimate counted only shots whose *primary* `asset_plan.strategy` was a generation rung, missing every shot that arrived there by falling through the ladder — the normal route after M6.5. `estimate_project_cost_cents` now takes an optional `binding_states` map and counts shots the search pass actually left `awaiting_generation`, which is the only thing that knows a shot fell through every free rung. A shot with no binding yet still falls back to the old primary-strategy guess: there is genuinely no way to predict a search hit rate before search has run, and that half of the original limitation is unchanged and documented in the function itself.
- **Asset reuse is a soft ranking penalty, not a hard rule, and repeats visibly.** Same run bound one `Sasol_CTL,_Secunda.jpg` to both `sc_04_sh_03` (~30.0s) and `sc_05_sh_03` (~38.3s, the final shot) — the same photograph twice, six seconds apart, in a 41-second video. `already_used_hashes` reaches `rank_candidates` only as a `reuse_penalty` score component, so a reused candidate is demoted but stays eligible and wins anyway when the pool is thin. A hard exclusion is **not** obviously right — it would push the shot to paid generation, which would almost certainly look worse than a real photograph of the actual plant. The likelier fix is a *temporal* rule: penalise reuse far more heavily when the two shots are close together, and barely at all when they are far apart.
- **A hard-killed process leaves a project permanently unresumable.** Introduced by F0a (2026-08-16), found while reviewing it, deferred by the user the same day. `app/workflow/trigger.py::_claim_or_join` short-circuits on `run_row.state == "running"` and schedules nothing — correct for a live run, wrong for a dead one. Ctrl-C on uvicorn, a reboot, or an OOM kill leaves the `workflow_run` row at `"running"` forever, so every later trigger reports `joined_existing_run=True` and joins a run nobody is executing; only editing Postgres by hand recovers it. The code F0a replaced recovered for free (`engine.py`: a non-terminal row was flipped back to `"running"` and the pipeline resumed) — and `trigger.py`'s own docstring still cites that crash recovery as a reason no queue is needed, while the guard it adds is what breaks it. Soft failures are unaffected: `_execute_in_background` catches exceptions and marks the run failed. **Preferred fix:** reclaim orphans in `main.py`'s `lifespan` rather than add a heartbeat column and a timeout threshold to tune — under this codebase's single-instance assumption a `"running"` row observed *during startup* is provably orphaned, since the process that owned it is gone. No migration, nothing to tune, self-heals on the next server start.
- **Landscape source material versus a vertical render.** The best archival images are wide (that Sasol photo is 3008×2000; the render is 720×1280), so a 9:16 crop keeps roughly the middle third and discards the sweep that made the composition work. Ken Burns mitigates it by moving across the frame rather than sitting in the centre. Not a bug — a standing tension between the material and the format, worth measuring on a real render before deciding whether it needs smarter cropping (e.g. saliency-aware rather than centre crop).

### Raised by the one-gate redesign (2026-08-16), all deferred by the user

- **Video generation still runs the old constraint-check and retry loop.** Explicitly declared out of scope by the user, 2026-08-16. The *image* path had the Director-constraint vision check and the bounded-retry loop removed (the human at the gate is the check now), but `_generate_video_real`/`_generate_checked_keyframe` are untouched, so a shot whose `asset_plan.preferred_type` is VIDEO still generates up to `max_generation_attempts_per_shot` times, still runs `check_generated_image_constraints` on its keyframe, and **can still be killed outright by a constraint violation** — the exact failure mode that destroyed the German-tank shots on the real run. The codebase is knowingly inconsistent here. Whoever converts it should apply the identical treatment (single attempt, no verdict, no `build_revised_prompt`) rather than inventing a third behaviour.
- **`creative_context.constraints` is now dead config on the image path.** The Director still writes constraints (*"No Nazi symbols used decoratively"*) and, after the one-gate work, nothing on the image path reads them. `GeneratedClipModel.violated_constraint` is likewise unwritten by image generation now. Both still matter for video (see above), so neither can simply be deleted. This is the same dead-config trap flagged during the R2 fingerprint audit — config that looks live and is not. Three options when it is picked up: stop the Director writing them, document them as advisory-only, or repurpose them as *positive* prompt guidance rather than a post-hoc blocklist. The middle one is the cheapest honest answer.
- **`shot.asset_locked` can go stale under the three-way choice.** Uploading to a shot sets `asset_locked = True` (A25). Generating on that same shot afterwards is now legal — generate and override are peers, by the user's decision — and replaces the binding, but leaves the flag `True` even though no human-supplied asset is bound any more. Harmless today, because nothing in the one-gate flow re-plans from that state and the flag is only read by `_reject_locked_shot_drift`. It becomes wrong the moment re-planning is reachable after the gate. Related and also unbuilt: there is **no unlock endpoint**, so a human who uploads a photo and then wants to edit that shot's prompt is refused (400) with no route forward except uploading a different photo.
- **No "generate all missing" batch endpoint.** `POST /shots/{id}/generate` is one shot per call, and each call is a real round-trip to fal.ai (tens of seconds). Five empty shots is five clicks and several minutes of waiting. A batch endpoint — with a single confirmation showing the total cost before it spends anything — is the obvious ergonomic fix. Not built; the frontend can loop the single endpoint in the meantime.
- **The frontend catch-all swallows API 404s.** `main.py`'s static-file fallback serves `index.html` for any unmatched path so a hard refresh on a client-side route works (`StaticFiles(html=True)` does not do this — verified live, not assumed). Consequence: a mistyped API path such as `/api/v1/typo` now returns `index.html` with `200` instead of a JSON `404`. Harmless to the app, actively confusing when debugging the API by hand. Fix by excluding `settings.api_base_path` from the catch-all.

## Advice

- **Normalise every input before composition.** Scale, pad, and set `fps`, `pix_fmt=yuv420p`, and `setsar=1` on every clip *individually* before concatenating. Mixed SAR/fps/resolution inputs are the number-one cause of FFmpeg concat failures and of silently mangled output.
- **Narration audio is the master clock** (D1). Everything else is fitted to it. If the plan says 3.0s but the narration for that span is 3.4s, the shot stretches. Apply this in exactly one place.
- **Music is mixed, never chosen, here** (D6). The Renderer receives a selected track and does the mix: narration at full level, music bedded at `MUSIC_BED_GAIN_DB`, ducked to `MUSIC_DUCK_GAIN_DB` while narration is speaking. Use the timings you already have to drive the ducking envelope rather than a live sidechain compressor — it is deterministic, and [I5](#i5--rendering-is-a-pure-function) requires that. Fade the bed in and out at the video boundaries.
- **Fingerprint the render inputs.** `sha256(canonical_timeline_json + sorted asset content hashes + narration hash + music track hash + render settings + ffmpeg version)`. Same fingerprint → skip and return the existing file. This is how you *prove* [I5](#i5--rendering-is-a-pure-function) rather than hope for it.
- **Purge non-determinism from the render path**: no `datetime.now()` in filenames or metadata, no unordered set/dict iteration when building the filter graph, no locale-dependent number formatting, and pass `-fflags +bitexact` where appropriate. Pin the FFmpeg version in Docker and record it in the fingerprint.
- **Always render a fast draft first.** 480p, no captions. Iteration at 8 seconds beats iteration at 4 minutes, and most defects (wrong asset, wrong order, bad pacing) are visible at any resolution.
- **Ken Burns is a renderer concern.** `camera.movement` + `intensity` maps to `zoompan`/`crop` expressions here. Do not push animation decisions back into planning ([canon 3.1](#31-the-asset-acquisition-ladder)).
- **Log the full FFmpeg command line at debug level, always.** You will paste it into a terminal a hundred times. Make that one copy-paste away.
- **Captions: burn via ASS, generated from narration timing.** Escape the subtitle path — on Windows, `subtitles=C\:/path/x.ass`. Generate the ASS file deterministically.
- **Transitions cost frames — they overlap** (D5). A 0.4s dissolve between two 3.0s shots yields 5.6s of video, not 6.0s. Encode this in one function that both the planner and the renderer call. Getting it wrong desynchronises audio from video progressively across the whole timeline, and it will present as a mysterious drift rather than as a transition bug.
- **Handle the missing-media case explicitly.** Failed shots get a defined placeholder treatment, not a crash.

## Done when

- [x] Rendering the same project twice produces byte-identical output — step 6: proven, not asserted, via `tests/integration/test_render_determinism.py` - two fully independent, from-scratch `render_timeline` calls over the same Timeline + images, compared with a literal `hashlib.sha256` equality on the output bytes, across three cases (static shot, Ken Burns shot, multi-shot crossfade). Required purging every source of non-determinism from the real ffmpeg invocations (`-fflags +bitexact`, per-stream `+bitexact`, `-threads 1` on the x264 encode) — see step 6's Implementation notes for exactly where.
- [ ] Audio stays in sync from first frame to last on a full 90-second video
- [x] Music beds under narration and ducks cleanly; no clipping, no bed audible over the voice — step 4 (below): proven with a real, isolated volume measurement (`tests/integration/test_render_music_mix.py`), not just "ffmpeg exits 0" — a bed comfortably audible at `MUSIC_BED_GAIN_DB` measures roughly the configured gap quieter during a narration-speaking interval, confirmed on the ducked bed alone so narration's own loudness can't mask a false pass.
- [x] Draft and final modes both work — step 6: `render_video` reused at `settings.draft_width/height` via `POST /projects/{id}/render/draft`, proven independent of the final render both at the pure-fingerprint level (draft/final dimensions can never collide on one cache entry) and through a real `render_video` call at each resolution (`tests/integration/test_render_draft.py`, ffprobed dimensions on both), plus the full HTTP surface end to end (`tests/e2e/test_draft_render_api.py`) — draft is available BEFORE approval and never disturbs `project.status`/`video_path`. `DRAFT_RETENTION_DAYS` (D3) is wired via `app/renderer/retention.py::purge_expired_drafts`, invoked opportunistically from the draft endpoint (no scheduler infrastructure exists in this codebase to hang a real cron job off) — proven in `tests/integration/test_draft_retention.py`.
- [ ] Mixed inputs (archival JPEG + stock 4K MP4 + generated clip + generated PNG) compose cleanly
- [ ] A Hindi script produces natural-sounding Hindi narration, with every shot still synced to its own `narration_span`
- [ ] The hook, when the Scene Planner writes one, is spoken before scene 1 and is not double-counted in any scene's timing
- [ ] Shot durations in the rendered video match the real narration, not the planner's estimates — verified by probing the output, not by trusting the arithmetic

**Deliberately out of scope for this iteration:** burned captions. `BURN_CAPTIONS=false`; the ASS generation path is not built. D2 still stands for whenever it is — captions come from script text plus these same alignment timings, never from transcribing our own audio.

---

# Phase M9 — API and Frontend

> **Goal:** a person who has never seen the codebase can drive it.

## Advice

- **Match [09_API_Specification.md](09_API_Specification.md).** It is short and it is the contract.
- **Long operations return `202` with a run ID.** Never block an HTTP request on planning, generation, or rendering. Poll `GET /status` and `GET /progress`, or push over WebSocket.
- **The approval screen is the product's most important surface.** It needs, per shot: intent, duration, camera, the resolved asset thumbnail (or the prompt if none), and the cost estimate. This is the screen that justifies the entire architecture — invest in it.
- **Expose the timeline diff in the UI.** "The Shot Planner changed these 6 shots" is the difference between trusting the system and not.
- **Per-scene regenerate is a first-class button** (US-003 in the [PRD](02_Product_Requirements_Document.md)) — reset the relevant `shot_binding` rows and re-run from that step. It is nearly free given M3 + M4, and it is the feature users will value most.

## Done when

- [ ] Full journey through the UI: create → paste → generate → review → approve → watch progress → download
- [ ] Errors are legible to a non-developer
- [ ] Regenerating one scene does not touch the others

## Screen design, agreed with the user screen by screen (2026-08-16)

### F0 — two blocking prerequisites, both backend

**F0a — the trigger endpoints must stop blocking.** This phase's own Advice already says *"Long operations return `202` with a run ID. Never block an HTTP request on planning, generation, or rendering"* — and the implementation does exactly that. `POST /render` ran past **600 seconds** during live testing and had to be backgrounded from the tooling; a browser cannot wait that long. Redis is in `docker-compose.yml` but **nothing in `app/` uses it** — there is no queue, no `BackgroundTasks`, nothing. Triggers must return immediately and the UI polls `GET /status` / `GET /progress`. Nothing else in this phase can be built honestly until this is true.

**F0b — nothing serves image bytes.** `asset.local_path` is a server filesystem path, so a browser cannot display any asset. Needed:
- `GET /projects/{id}/shots/{shot_id}/asset` — the bound image, for the approval screen.
- `GET /projects/{id}/thumbnail` — for the project list.

Both are the same kind of work and should ship together. **Generate lazily and cache to disk, keyed on the source file's mtime** — not eagerly at render time. Lazy needs no pipeline change, wastes nothing on projects nobody opens, and handles both source cases through one path. The mtime key matters: `RenderStep` already shipped a stale-cache bug during this project (a cached render served after assets changed), and a thumbnail cache without invalidation would reproduce it — a re-render with a new voice would keep showing the old video's frame forever.

Both tools are already dependencies: **Pillow** (already used by `app/assets/validation.py`) resizes stills, **ffmpeg** (already driving the renderer) extracts video frames.

### F1 — the project list

Cards: **thumbnail**, name, status chip, shot count and duration where known, created date. `GET /projects` supplies everything except the thumbnail.

**Thumbnail source, in order:**
1. `final.mp4` exists → extract a frame with ffmpeg. **Not frame 0** — that is routinely a fade-in or a dark frame. Take roughly 10% in, clamped to [0.5s, 3s] so short videos do not overshoot.
2. No video yet → the **first shot's bound asset**, resized with Pillow. Projects sit at the approval gate longest, which is exactly when a thumbnail is most wanted, and a bound asset exists from the moment the free search pass finishes.
3. Neither → 404, and the card shows a status chip instead.

**Failed projects are listed prominently, not hidden** (user's explicit call, 2026-08-16). Live testing produced several dead ends — a Shot Planner span failure, a Scene Planner verbatim flake, a narration timing rejection — and each one was a thing the user needed to see and act on, not a record to tidy away. A failed project with a legible reason is the system telling the truth about itself.

### F2 — new project (script, optional assets)

`POST /projects` → `POST /{id}/script` → optionally `POST /{id}/assets` → trigger.

**F2a — voice and music selection are deferred to a later version** (user's call, 2026-08-16). This screen **displays** which voice is configured, and does not offer a picker. Changing a voice after the fact already works (`POST /narration/retry`, N1) and re-auditioning is free because narration is cached per `hash(text + voice + model + format)`. Music selection likewise waits for the curated library (M4–M10).

**F2b — upload descriptions are mandatory and must be 10–15 words**, and the screen must explain what they are for, because the mechanism is not what people assume.

**They are matched by literal term overlap, not by a planner and not by any LLM.** `LocalProjectAssetProvider` puts the human's description into both `title` and `description` on the candidate; `candidate_relevance` then scores the shot's `search_queries` against that text via `term_overlap_relevance` — generic terms weighted a quarter — and `passes_relevance_gate` **discards** anything below `asset_relevance_threshold` (0.25) before it is ever ranked or downloaded. A3 stands: no planner ever sees these.

Two consequences the UI must surface:

- **Write concrete nouns in English** — places, objects, period. The Asset Planner writes its search queries in English because that is what Wikimedia searches, so an English description is what there is to overlap *with*, even when the script is Hindi or Hinglish.
- **Prose and sentiment score zero.** Measured on the real run: descriptions of `"franz"` (×9), `"moving tanks"` (×3) and `"german_infantary"` matched **nothing** — every one of those uploads fell through the gate and had to be placed by hand through per-shot override instead. The feature silently did nothing, which is the worst possible failure mode for an optional input.

Example, against a shot whose queries are *"Leuna-Werke synthetic fuel plant"* / *"German hydrogenation 1943"*:

| description | result |
|---|---|
| `Leuna-Werke synthetic fuel plant, distillation towers, 1943 archival` | matches |
| `my grandfather's old factory in East Germany` | ~0 |
| `franz` | 0 |

**F2c — script formatting is load-bearing and should be hinted.** Line breaks become fragment boundaries (S1/S2), which become shot boundaries. Short lines produce clean one-line-per-shot cuts. **And narration is the script verbatim** — the pipeline never rewrites it — so register and script choice are made here or not at all. Mixed-script Hinglish (Devanagari for Hindi, Latin for loanwords) measurably outperformed Romanised Hindi for TTS pronunciation.

### F3 — progress

Two different waits, wanting two different displays.

**Before approval** (Director → Scene → Shot ×N → Asset ×N → free search → music): shots do not exist yet, so per-shot progress is meaningless. Stage-based, driven by `current_step`. Measured 5–15 minutes on real runs.

**After approval** (narration → generation → render): `completed_shots / total_shots` is real and `spent_cost_cents` climbs per generated image. Per-shot, and where a progress bar earns its place.

- **"Nothing spent yet" is a feature, not a blank.** I6 guarantees no money moves before approval, so pre-approval the screen states £0.00 rather than omitting it — that reassurance is the entire reason the gate exists.
- **Do not display `estimated_cost_cents` — it is known-broken.** It read **0¢** with fifteen generations pending, because it counts only shots whose *primary* strategy is generation and misses everything that fell through the ladder (backlogged, `6902d6a`). Showing a number known to be wrong is worse than showing none.
- **Errors must be translated.** This phase's Done-when already requires "errors are legible to a non-developer", and real failures were not: *"shot sc_03_sh_01's narration_span (0, 2) covers only whitespace - nothing is actually spoken, so it cannot be timed against narration"*. Show a plain sentence, the technical detail behind a disclosure, and **the action** where one exists — most real failures had one.
- Polling every 2–3s is ample; individual planner stages take tens of seconds.
- **Offer retry on a failed plan.** The Scene Planner flake succeeded on a second attempt with no code change, and the engine resumes from the failed stage rather than from scratch, so a retry costs one stage, not a whole plan.

### F4 — Gate 1: asset review, before any money is spent

**This replaces "approve the plan" with "approve the pictures".** Every shot, in playback order, in one list:

- **Found** — the image search selected, shown, with that shot's `intent` and `prompt` beside it.
- **Missing** — no image, but `intent` and `prompt` still shown, marked as headed for generation.

**Insert or override on either kind.** The critical change: gaps are filled **before** generation rather than after it fails. Supply images for every missing shot and generation never runs and costs nothing.

This is what the real run needed and could not do — 15 of 19 shots were headed for generation, the user had relevant archival photographs on disk, and the only route to using them was per-shot override *after* paying for generation, or bulk upload whose descriptions silently failed the relevance gate.

### F5 — Gate 2: review of generated images (new, mandatory)

A second gate after generation and before render. **Every generated image is shown for approval** — this is no longer a failure-only path.

**F5a — the Director's constraints are demoted from blocker to flag** (user's explicit decision, 2026-08-16, deliberately reversing A26 and A12–A14's blocking behaviour).

The real run showed why. The Director wrote *"No Nazi symbols used decoratively"*; generation produced German tanks bearing insignia; the vision check rejected three attempts and **killed the shot** — in a documentary where those tanks are the historical subject. An over-broad rule destroyed legitimate material and the human never saw it or got a say.

**The check still runs and its verdict is still recorded — it simply stops deciding alone.** The generated image is kept and shown at Gate 2 with the objection attached (*"the vision check thinks this violates: no Nazi symbols used decoratively"*), and the human accepts, regenerates, or replaces it.

This is **more** oversight than the current design, not less: today a machine decides unilaterally and the human sees neither the image nor the objection. Under F5 every generated image and every objection is reviewed by a person before it can reach a render.

**F5b — no automatic retries.** Today generation silently burned three attempts at ~4¢ each trying to satisfy a rule that should not have applied. Generate once, show it with any flag, let the human choose. Cheaper and controllable.

**F5c — the prompt is editable, and regeneration uses the edited prompt.** The prompt is what produced the wrong picture, so rewriting it beats re-rolling the same dice. The edit is a Timeline change (I2 — prompts are decisions) and so goes through `append_version` with `produced_by=HUMAN`, and must persist so a later pass cannot revert it. Regeneration costs money, so it needs explicit confirmation.

**F5d — narration stays before generation.** They are independent — no image depends on a duration and no duration depends on an image — so the order is chosen on other grounds:
- Narration is ~10¢ against ~60¢ for generation, and **fails earlier and cheaper**. The real whitespace-span failure hit at narration, before any image existed; generation-first would have burned 60¢ and then failed identically.
- **Its result is stable under every Gate 2 decision**, because an override never changes timing (A29) — swapping an image changes which file plays, never for how long. So nothing done at Gate 2 invalidates it.
- **It makes Gate 2 better:** with durations reconciled, Gate 2 shows how long each image is actually on screen. A busy, detailed image fails at 1.5s and works at 4.6s, and that judgement is impossible without the number.

### F6 — result

Play (`GET /video`), download, and the three corrections that already exist as endpoints: **different voice** (`POST /narration/retry`, N1), **different music** (`POST /music/retry`, M3), and re-render.

- **Surface the music attribution — it is a legal obligation, not a credit roll.** Every track the permissive search can return is CC0 or CC-BY, and CC-BY *requires* attribution. The string is already generated and stored on `music_plan.selected_track.attribution` (e.g. *"Documentary Music Strings" by tyops is licensed under CC BY 4.0…*). It must be copyable from this screen, or the user publishes in breach without knowing. M7 left "video, description, or both" open — this screen is the minimum answer.
- **Show what the video is made of**: how many shots came from archival search, entity retrieval, generation, and the user's own uploads. On the real run that was 8 Wikimedia / 3 Wikipedia-entity / 7 generated / 1 uploaded — the single number the user reacted to most, because generated images are where the piece loses credibility.
- **Show total spend**, from `spent_cost_cents`.
- Re-auditioning a voice is **free** after the first time (narration caches per `hash(text + voice + model + format)`), and re-rendering is free entirely — local ffmpeg. The screen should say so, because "try another voice" reads as expensive when it is not.

### F7 — resolution warnings on human-supplied images (warn, never block)

**The gap:** `_quality_score` (`app/assets/ranking.py`) already measures exactly this — linear upscale needed as `sqrt(target_area / source_area)`, full marks at ≤1.5×, sliding to a floor of 0.1 at ≥4× — but it is a **ranking term for searched candidates only**. Per-shot override deliberately bypasses relevance and licence gates (A24: a human pointing at a shot has already made that judgement), and quality was never checked in that path at all. A human can upload a 320×240 image today and it renders as a blurry mess with no warning at any point.

**The degradation is real and compounds** from four sources: upscaling to 720×1280; Ken Burns zooming *into* the frame (a 1.2× move effectively demands ~864×1536); the 9:16 crop discarding most of a landscape image's width so its usable pixels are far fewer than its dimensions suggest; and H.264 with chroma subsampling handling archival grain poorly.

**Warn, never block** — the same principle as F5a. A human's judgement about their own footage wins; the system's job is to make sure they are not surprised.

| upscale needed | portrait source, roughly | verdict |
|---|---|---|
| ≤1.5× | ~590×1050 and larger | fine |
| 1.5–2.5× | ~370×650 up | soft — visible on a large phone screen |
| ≥4× | below ~180×320 | will look bad |

Shown as a badge carrying the real numbers — *"480×640 → upscaled 1.7×, may look soft"* — at upload **and** again at Gate 1, never as a pass/fail.

Two refinements that make the number honest rather than nominal:
- **Account for that shot's actual Ken Burns zoom** rather than assuming 1×.
- **Score the post-crop region**, not the full frame, since for a landscape source the crop is what actually gets rendered — this is the same tension already backlogged as landscape-versus-vertical.

## The one-gate redesign (2026-08-16) — superseding F4/F5's two-gate plan

**Decided by the user, 2026-08-16, after the F4/F5 screens above (and the
frontend built against them) already existed.** F4/F5 split review into
TWO gates: approve the plan (Gate 1, before any image work), then batch-
generate every missing image UNATTENDED, then review the generated
images (Gate 2, after they already exist). The new design collapses this
to ONE gate: a human sees every shot's picture - found or missing - and,
per shot, either keeps what search found, uploads their own
(`POST /shots/{id}/override`, already existed), or generates one on
demand (`POST /shots/{id}/generate`, new). They approve once, and the
pipeline runs to completion with nothing left unattended between
approval and a finished video.

**Why:** Gate 2 under F4/F5 existed only to catch what unattended batch
generation got wrong - but by the time a human saw it, the money was
already spent. The one-gate design moves that judgement BEFORE any
generation happens at all: nothing is generated unless a human explicitly
asked for it (by clicking `/generate`) or the plan is fully filled by free
search/uploads and gets approved. F5a/F5b/F5c's own reasoning (demote the
Director-constraint check to a flag, no automatic retries, an editable
prompt) all survive into this design, just folded into the ONE gate
instead of a second one: `/generate` generates once, no verdict, no
retry (F5b), and accepts an edited prompt (F5c, now Task 4 below).

This section documents the backend consequences, task by task, exactly
as they were decided and built - so they read as choices, not drift. The
frontend (F1-F7, parked mid-build per the note below) was built against
the SUPERSEDED F4/F5 plan and is not part of this redesign; backend work
here does not touch it.

### Task 1 — `NarrationStep` moved before `AwaitApprovalStep`

Old pipeline order: `GenerateTimeline -> ResolveAssets(search) ->
SelectMusic -> AwaitApproval -> Narration -> ResolveAssets(generate) ->
AwaitReview -> Render -> Complete`. New order: `... -> SelectMusic ->
Narration -> AwaitApproval -> ResolveAssets(generate) -> ...` -
`NarrationStep` and `AwaitApprovalStep` swap.

**Why:** narration is the master clock (D1) and produces REAL shot
durations from ElevenLabs character-level alignment; until it runs,
`duration_s` is only the Shot Planner's pre-audio estimate. The one gate
must show how long each image is actually on screen - a busy, detailed
image fails at 1.5s and works at 4.6s, and that judgement is impossible
against a guess. Narration is also cheap (~10 cents) and fails earliest:
a script whose narration span covers only whitespace, or whose
reconciled duration blows the video-length cap, now fails BEFORE a human
spends time reviewing a gate full of images for a script that could
never ship.

**This is a deliberate, narrow I6 exception** ("nothing expensive runs
before approval") - accepted consciously, not silently: ~10 cents is now
spent pre-approval, versus the alternative of gating on a number that
isn't real yet.

**What had to change, found by checking rather than assuming (both
verified against the actual code, not inferred):**

- `NarrationStep.is_satisfied` only ever checked `timeline.produced_by
  == NARRATION` - genuinely independent of approval, so the reorder
  needed no change there.
- `NarrationStep.run()` used to self-approve its own appended version
  UNCONDITIONALLY, and `AwaitApprovalStep` treated `produced_by ==
  NARRATION` as approval-equivalent - both correct ONLY under the old
  order, where narration could only ever run on an already-approved
  lineage (a crash-window defence, closing the gap between
  `append_version` and `approve`, two separate commits). Under the new
  order this reasoning INVERTS: `produced_by == NARRATION` is now
  routinely the ordinary, UNAPPROVED state a human is looking at while
  deciding whether to approve (the version narration just produced IS
  what the gate is waiting on). Keeping either shortcut would have made
  the gate a silent no-op - the pipeline would sail through the instant
  narration finished, nobody having clicked anything, which would also
  have re-triggered the exact "produced_by==NARRATION implies approved"
  short-circuit inside `override_shot_asset`'s and
  `_resume_after_human_correction`'s own `was_already_approved` checks
  in `app/api/projects.py`, both of which had to lose that clause too.
  Fixed: `AwaitApprovalStep` now checks `status == APPROVED`, full stop;
  `NarrationStep` now self-approves ONLY when the version it narrated
  FROM was already approved (the N1 "redo narration with a different
  voice" path, which runs well after a project's first approval) -
  preserving `POST /narration/retry`'s "resume, no second click"
  contract without reopening the first-approval gate narration now sits
  in front of. See `app/workflow/engine.py`'s own module docstring and
  `app/workflow/steps/narration.py`/`app/workflow/steps/await_approval.py`
  for the full reasoning in place.
- Every test asserting pipeline step order, or seeding an UNAPPROVED
  timeline and expecting `NarrationStep` to self-approve regardless, had
  to be found and updated (`test_narration_pipeline_ordering.py`,
  `test_render_only.py`, `test_workflow_engine.py`,
  `test_skeleton.py::test_script_to_video_end_to_end`) - tests that
  instead seeded an ALREADY-APPROVED timeline before invoking
  `NarrationStep` directly (`test_narration_step.py`,
  `test_narration_voice_retry.py`, `test_narration_retry_api.py`) needed
  no change at all, since the conditional self-approval reduces to the
  old unconditional behaviour exactly when the prior version was already
  approved - which is precisely what those fixtures set up.

### Task 2 — approval blocked while any shot has no media

`POST /timeline/approve` now refuses (400, naming the specific shots) if
any shot at the active version has neither `asset_id` nor `clip_id`
(`ShotBinding.state` not in `("resolved", "generated")`). Under the
one-gate design this is the actual money guard: without it, approving a
plan with empty shots would let `resolve_assets_generate` batch-generate
every one of them unattended immediately afterward - exactly the
unsupervised spend this whole redesign exists to prevent. This is A26's
"you cannot finish with a gap" moved EARLIER, to "you cannot APPROVE with
a gap" - strictly better, since it is caught before anything runs rather
than after. Consequence: `resolve_assets_generate` becomes a no-op safety
net (there is no longer any state it can legitimately find left to do)
rather than the thing that actually spends money; `AwaitReviewStep`
remains as a further backstop for anything that reaches `failed` AFTER
approval regardless (kept, per the user's explicit instruction).

### Task 3 — repeat generation actually produces a different image

`_generate_image_once`'s seed used to be `_project_seed(project_id)`
alone - fixed per project, so a second click on the same shot with the
same prompt hit the SAME `prompt_hash` and returned the identical, free,
first image. The seed now also folds in
`GeneratedClipRepository.count_for_shot` (how many clips already exist
for THIS shot): attempt 0 (no prior clips) still gets the bare project
seed unchanged (preserving the ordinary "generate once" cache/dedup
behaviour every other shot relies on), and every attempt after that
varies deterministically via `varied_seed` (mirroring, not duplicating,
A13's own prior art in `app/assets/constraint_check.py`) - never
`random`, never wall-clock time, so replaying the same sequence of
clicks reproduces the same images (I5, and the render fingerprint
depend on it).

### Task 4 — `/generate` accepts an edited prompt

An optional `prompt` in the request body. Omitted, or unchanged from the
shot's current `prompt`, behaves exactly as before. Supplied and
different, it is a Timeline change (I2) and is recorded as its own
`append_version(produced_by=HUMAN)`, touching only that one shot's
`prompt` (`owns={"scenes"}`) - before anything is generated, and the
fresh clip is bound at the NEW version. The stored value is the RAW
edited text, exactly like a planner's own prompt - `_styled_prompt`
still layers `creative_context.visual_style` on top at generation time
for a human-edited prompt exactly as it does for a planner-written one
(decided by the user: a human edit must not skip the styling every other
shot gets).

**Proven, not assumed, that this doesn't orphan every other shot's
binding**: `TimelineService._carry_forward_bindings` (A20) carries a
binding forward when the shot's `prompt`/`asset_plan` are unchanged from
the previous version - true for every OTHER shot (only the edited one's
prompt changed), so they carry; the edited shot's own OLD binding is
correctly dropped (it needs re-acquisition, which the generate call
immediately provides at the new version). Proven end-to-end over the
real HTTP surface, not just reasoned about, in
`tests/e2e/test_generate_shot_api.py
::test_generate_with_edited_prompt_appends_a_new_version_and_carries_forward_other_bindings` -
every OTHER shot's bound asset file is asserted byte-for-byte identical
(same `local_path`) before and after the edit.

**The highest-risk finding, surfaced rather than worked around**:
`TimelineService._reject_locked_shot_drift` (A25) refuses ANY later
version that changes a locked shot's `prompt`, unconditionally,
regardless of `produced_by` - so editing the prompt of a shot a human
previously overrode (`asset_locked=True`) RAISES `PermanentError`, caught
and surfaced as `400` like any other `append_version` rejection this
file already handles. This is deliberate, not a bug: A25's whole
guarantee ("my photo is always in the plan") requires exactly this. No
bypass or unlock mechanism was added - A25a's own entry above already
documents an unlock endpoint as a deferred, not-yet-built gap, and this
task does not change that. Generating WITHOUT an edited prompt still
works on a locked shot (generate and override are peers, per the user's
explicit decision) - only the PROMPT EDIT is refused, proven in
`test_generate_shot_api.py
::test_generate_peers_with_override_but_an_edited_prompt_on_a_locked_shot_is_refused`.
A related, smaller fix the peer relationship exposed:
`generate_image_real` did not clear `binding.asset_id` when writing a
fresh `clip_id`, which was harmless while generation only ever ran on a
binding that never had `asset_id` set - now that `/generate` may run on
a previously-overridden binding, a stale `asset_id` would have kept
`_resolve_bound_media_path`/`RenderStep` serving the OLD overridden
picture forever (both resolve `asset_id` before `clip_id`). Fixed by
clearing it explicitly, symmetric with `override_shot_asset`'s own clear
of `clip_id`.

### Task 5 — `estimate_project_cost_cents` counts what will actually generate

Signature gained a second, optional parameter:
`estimate_project_cost_cents(timeline, binding_states: dict[str, str] |
None = None)`, mapping `shot_id -> ShotBinding.state` at the active
version. The OLD estimate counted only shots whose PRIMARY
`asset_plan.strategy` was already a generation rung - wrong the moment a
search-primary shot falls through the ladder to generation, which after
M6.5 is the NORMAL route, not an edge case (measured on a real run: 10 of
14 shots queued to generate, estimate read 0). `binding_states` is what
makes the fix possible: only the search pass's own verdict
(`"awaiting_generation"`) actually knows a shot will reach generation
regardless of its plan's primary label. A shot already `"resolved"` (free
search, or a human's own override/upload) or `"generated"` (already
billed, and already reflected in `spent_cost_cents`) is excluded
outright, so nothing is double-counted. No binding yet (search hasn't
reached this shot, or a total outage, A22) falls back to the OLD
plan-only guess - unchanged, since there remains no reliable way to
predict a search hit rate before it runs. `GET /progress` is the one
real caller, and already builds the exact dict this needed for its own
`shots` array, so passing it costs nothing extra there.

### Task 6 — reporting a cache hit

`GET/POST /shots/{id}/generate`'s response gained `cache_hit: bool`, and
`cost_cents` now means what THAT call actually cost - `0` on a cache
hit, never the clip row's ORIGINAL charge (which the field used to
return unconditionally, making a free reuse indistinguishable from a
fresh spend). Threaded up from `_generate_image_once` (which already
had to decide this internally to know whether to call the paid provider
at all) through `generate_image_real` as a `(clip, cache_hit)` tuple.
True cache hits still happen under Task 3's new seed - most commonly
two DIFFERENT shots in the same project sharing identical prompt text at
their own first-ever attempt (attempt 0 always uses the bare, per-project
seed, shared across every shot in that project by design) - proven in
`test_generate_shot_api.py
::test_generate_hits_the_cache_when_a_different_shot_shares_the_exact_prompt`.

### Task 7 — no stale image after a regenerate

`GET /shots/{id}/asset` now sets `Cache-Control: no-cache` on every
response. The URL is stable per shot, but the underlying file behind it
is not (a regenerate or an override rebinds the same shot to a different
file) - without an explicit `Cache-Control`, a browser applies heuristic
freshness (RFC 7234 §4.2.2) and may never even ask the server again
after the first load. Starlette's `FileResponse` already computes
`ETag`/`Last-Modified` FRESH on every call, from the actual file's
current `os.stat` at send time - so the validators were already
correct; `no-cache` (which still permits caching - it forbids using the
cached copy WITHOUT revalidating first) is what makes the browser
actually consult them on every load. Not solved by asking the frontend
to cache-bust the URL with a query parameter - that only protects
clients that remember to do it. Proven end-to-end (not just that the
header is present) in `test_media_endpoints_api.py
::test_shot_asset_etag_and_bytes_change_after_an_override_at_the_same_url`.

### Frontend build status (2026-08-16) — parked mid-build, committed deliberately

All seven screens above (F1–F7) are built as real routes in `frontend/` — ~2,400 lines, no stubs. **The app does not compile and has never talked to the running backend.** Parked at the user's request to be resumed later; committed in that state rather than left uncommitted.

**The full pick-up list lives in [`frontend/README.md`](../frontend/README.md)** — read that before touching it, because the interesting problems are the ones the compiler will *not* report:

- The frontend was written before F0a landed, against the old synchronous contract. Five client functions are typed `Promise<Project>` while the backend now returns `WorkflowTriggerResult` with **HTTP 202** — those calls return *before the work starts*, so any screen reading the response to decide what to show next now shows the wrong thing. `POST /render/only` is absent from the client entirely.
- ~~**F5c has no backend.**~~ **BUILT 2026-08-16, at a different URL.** `regenerateShot` posts to `POST /projects/{id}/shots/{shot_id}/regenerate`, which does not and will not exist. The real endpoint is **`POST /projects/{id}/shots/{shot_id}/generate`** — it takes the same `{prompt}` body the frontend already sends, so this is a one-line repoint, not a rewrite. It is synchronous (**200**, not 202 — one image generation is seconds, not the minutes a whole pipeline run takes) and returns `{shot_id, clip_id, cost_cents, cache_hit}`, *not* a `Project`. `cache_hit` distinguishes "this click spent money" from "reused an existing image, free"; `cost_cents` is what **this call** cost, so it is `0` on a cache hit.
- Two compile errors, both small: a TypeScript 6 `baseUrl` deprecation that is now a hard error and blocks `tsc -b` entirely, and one real type error at `Progress.tsx:89`. With the first silenced, the second is the only type error in all 53 files.
- ~~Static-file serving from FastAPI is not wired.~~ **DONE 2026-08-16** — `main.py` mounts `frontend/dist` and falls back to `index.html` for client-side routes. Build with `npm run build`; the mount is skipped entirely if `dist/` is absent, so a backend-only checkout still starts.

**The two-gate design these screens were built for no longer exists** (2026-08-16). `Gate1AssetReview` and `Gate2GeneratedReview` merge into ONE screen showing every shot in playback order, where each shot offers a three-way choice — keep what the planner found, upload your own (`POST /shots/{id}/override`), or generate (`POST /shots/{id}/generate`) — and approval is refused with a `400` naming the shots while any shot is still empty. `GET /progress` already returns everything that screen needs in one call: per shot, `state`, `rung`, `will_generate`, `locked`, `asset`, `clip`, `says`, `prompt`, `intent`, `duration_s`, `starts_at_s`, plus `spent_cost_cents` and a now-correct `estimated_cost_cents`. Durations there are **real** narration-measured times, not planner estimates, because narration now runs before the gate.

Estimated one working session to operational — but that assumes the screens are right in *design* and only wrong in *wiring*, which the first live run against a real project is what actually tests.

## Implementation notes (2026-08-15) — folding shot semantics into `GET /progress`, ahead of the frontend

No frontend exists yet (M9 proper hasn't started), but the gap this
closes couldn't wait for one: a live paid run put a human in front of
`GET /progress` at the approval gate, and it reported pure execution
state (`shot_id`, `state`, `rung`, `asset`/`clip`) with no meaning - the
narration, prompt, intent, and timing all lived only in `GET /timeline`,
and nothing joined the two. A human could see THAT a shot resolved, not
WHAT it was or whether its picture was right - exactly backwards for a
phase whose whole premise (M6.5) is putting a human in front of
acquisition while fixing it is still free.

- **Additive fields only**, per shot in the `shots` array: `says` (the
  shot's narration text, already resolved - `scene.narration_text[start:
  end]`, not the raw offsets, because the human wants the words, not
  arithmetic to do themselves), `prompt`, `intent`, `duration_s`, and
  `starts_at_s`. Every existing field keeps its name and shape - nothing
  was removed or renamed, since the e2e suite asserts on the old shape
  directly.
- **`starts_at_s` reuses D5's existing run/overlap arithmetic rather than
  a naive cumulative sum** - a naive `sum(duration_s)` up to a shot is
  wrong the moment any transition overlaps two shots (a 0.4s dissolve
  between two 3.0s shots means the second starts 0.4s before the first's
  own footage ends, not after it). New `app/timeline/duration.py::
  compute_shot_start_times(shots) -> dict[shot_id, float]` computes this
  directly from `group_into_runs`/`compute_run_duration` - the SAME two
  functions `compute_timeline_duration` already uses - rather than
  re-deriving the overlap math a third time in the API layer. It is
  `duration.py`'s "one function" (module docstring) gaining one more
  reading of itself, not a second, competing arithmetic.
- **`shots` is now ordered in TIMELINE order** (scene order, then shot
  order within each scene - iterating `timeline.scenes`/`scene.shots`
  directly, which is exactly the order every planner already writes and
  never reorders after) **instead of sorted by `shot_id`.** The two
  happened to coincide on every fixture built so far (ids are namespaced
  `{scene_id}_{s.id}` and scenes/shots are typically numbered in order),
  which is precisely why that coincidence could not be trusted - nothing
  enforced it, and a human reading the list expects playback order, not
  an accident of string sorting.
- **Verified against the real live project**, not merely reasoned about
  - with a real constraint: a live project (`194ad0e7-e545-4524-a597-
  59e4ff604ba2`, 14 shots/5 scenes, sitting at the approval gate) was
  live in the shared dev Postgres, and running `pytest` (which truncates
  every table via `tests/conftest.py`'s autouse `clean_database`) would
  have destroyed it - so the full suite was NOT run for this change. The
  already-running dev server also could not be used directly: it had not
  reloaded this code (confirmed - a plain `curl` against it still
  returned the OLD field set), and restarting a server serving a live,
  in-progress human test was judged too risky to do unilaterally.
  Verified instead by calling the real, updated `get_progress()`
  function directly against a real, read-only database session pointed
  at that same live project (zero commits, zero writes - `TimelineService
  .get_active` and the binding/asset lookups inside `get_progress` are
  all `SELECT`s) - the actual code path, not a reimplementation of it.
  Result matched the coordinator's own known-good values exactly:
  `sc_01_sh_01` says "Bro, Germany ke paas oil tha hi nahi..." at
  `starts_at_s=0.0`; `sc_03_sh_03` carries the Bundesarchiv Leuna asset
  and says "...Leuna-Werke jaisi factories din raat fuel bana rahi thi."
  (a leading space is real - it is the space that already separated it
  from the previous shot's own sentence in the scene's continuous
  narration text, not a bug); the last shot, `sc_05_sh_03`, says "...Ek
  war-time jugaad, jo permanent solution ban gaya." All 14 shots came
  back in timeline order across all 5 scenes.
- **Tests written but deliberately NOT run this session** - per the
  coordinator's explicit instruction while the live project above was in
  play: `tests/unit/timeline/test_duration.py` (new - pure-function
  proof that `compute_shot_start_times` agrees with
  `compute_timeline_duration`/`compute_run_duration` across hard-cut and
  dissolve cases, cross-checked both ways) and `tests/e2e/
  test_progress_shot_semantics.py` (new - a hand-built two-scene, three-
  shot timeline whose shot ids are deliberately chosen so alphabetical
  order disagrees with timeline order, proving the reorder fix over the
  real HTTP surface, plus the new fields' values and the additive-only
  shape of the existing ones). `ruff check backend`, `black --check
  backend` (1 file reformatted), `mypy backend/app` all run normally (no
  database touched) and are clean.

## Implementation notes (2026-08-16) — F0a/F0b: backgrounding triggers and serving media

Both of F0's own two blocking prerequisites, closed in the same pass since they were designed together (agreed with the user 2026-08-16) and ship the same way F0's own text asked for.

**F0a — every trigger endpoint now returns `202` immediately.** `POST /render`, `POST /timeline/approve`, `POST /shots/{shot_id}/override`, `POST /music/retry`, `POST /narration/retry`, and the new `POST /render/only` (R3) no longer `await engine.run()` inline. Each now calls `app/workflow/trigger.py::start_workflow_run`, which claims (or joins) this project's `workflow_run` row in the request's own transaction, then hands the actual pipeline execution to FastAPI `BackgroundTasks` on a **fresh** `AsyncSession` (the request's own session is gone by the time a background callback runs — reusing it would run queries on a dead connection). The response is a small `WorkflowTriggerResult` (`project_id`, `workflow_run_id`, `state`, `joined_existing_run`) with `202`, never the `Project` these endpoints used to return synchronously — `GET /status`/`GET /progress` are the real answer to "what happened", and both already carried `workflow_state`/`current_step` before this change (M9's own earlier implementation note).

*`POST /render/draft` was deliberately left synchronous* — it never calls `engine.run()` at all (it calls `render_video` directly, no planners, no providers), and its own point is to be the FAST preview path (M8 Advice: "iteration at 8 seconds beats iteration at 4 minutes"); backgrounding it would add a poll round-trip to the one render path meant to feel instant, for a call this project's own evidence never measured as slow. Revisit if that measurement ever changes.

*Why FastAPI `BackgroundTasks`, not a queue.* Redis is in `docker-compose.yml`, used by nothing in `app/` — a real temptation given F0a's own text raises it. Rejected: this process already holds a live asyncio event loop and DB connection pool; a `BackgroundTasks` callback runs on that same loop, needs no broker, no second worker process, and no serialisation boundary for `RunContext` (which holds a live `AsyncSession` — not something handed to a different process without redesigning the whole per-step contract). A queue earns its keep when work must survive this PROCESS dying or be spread across machines; this codebase is single-instance, and `WorkflowRunModel`/`WorkflowStepAttemptModel` already give crash recovery for free (a step-attempt row is written before the step starts — M4 Advice — so a killed process resumes correctly on the next trigger, background or not). Building Celery/arq here would be exactly the "speculative framework" this codebase's conventions already warn against.

*Concurrent triggers on one project cannot start two runs.* `app/workflow/trigger.py::_claim_or_join` makes the "read the latest `workflow_run` row, create one or flip it to running" transition — the same transition `WorkflowEngine.run()` already performed inline — atomic across processes with a Postgres advisory lock (`pg_advisory_xact_lock`, keyed on the project UUID, released automatically at commit) wrapped around it, performed once in the request's own transaction *before* the background task is scheduled. A second, genuinely concurrent request blocks on the same lock until the first commits, then observes the row already `state == "running"` and **joins** (reports on it, schedules nothing) rather than starting a second execution. A bare `SELECT ... FOR UPDATE` on the row was considered and rejected as insufficient on its own: it cannot protect a project's very FIRST trigger, where no `workflow_run` row exists yet to lock against — the advisory lock, keyed on the project id rather than a row, is what closes that case too. Proven directly (not through real HTTP concurrency, which `TestClient` cannot force deterministically — see below) in `tests/integration/test_workflow_trigger.py`: a second claim while the first is `"running"` joins the same row; a claim after the first reaches a terminal state starts a genuinely new row; a claim while the first is merely *paused* (`awaiting_approval`/`awaiting_review`) reclaims the SAME row to resume it, never treating a paused run as if it were finished or as if it were still executing.

*A background failure surfaces, it doesn't vanish.* `WorkflowEngine._run_with_retry` already turns any exception from a step's own `run()` into a clean `StepResult(outcome="failed", ...)` — unchanged, already well covered by existing tests. `_execute_in_background`'s own `try`/`except` around the whole `engine.run()` call catches what THAT contract doesn't: a bug in the engine loop itself, or anything else outside a single step's own try/except. Without it, such a crash would vanish into `BackgroundTasks`' own logged-and-dropped exception handling, leaving a project stuck reporting `running` forever with no visible cause. On catch: `project.status` is set to `FAILED` with a legible `project.error` (`"internal error while running the workflow: {exc}"`), the latest `workflow_run` row (already claimed by the request that scheduled this task) is marked `failed`, and both are committed on the background task's own session. Proven in `tests/integration/test_workflow_trigger.py::test_a_crash_inside_the_engine_itself_surfaces_through_status` by monkeypatching `WorkflowEngine.run` itself to raise (not a step — the method the per-step catch doesn't wrap) and asserting the failure lands exactly there.

*The existing e2e suite now polls.* Every e2e test that used to read a trigger's own JSON response body (`resp.json()["status"]`, `["timeline"]`, etc.) now calls the new `tests/e2e/_polling.py::trigger_and_wait` (POST/whatever, assert `202`, poll `GET /status` until a stopping state, return the `GET /projects/{id}` body — the same shape the old synchronous response used to hand back) or, where the trigger's own return value isn't needed, `wait_for_workflow` after a bare POST. No assertion was weakened — every test still proves exactly the outcome it always claimed (a real narrated/rendered MP4, a real music/voice re-selection, a real review-gate block-then-clear, a real draft/final independence); only how the test OBSERVES the outcome changed, because the trigger itself no longer hands it back directly. Updated: `tests/e2e/test_skeleton.py`, `test_music_retry_api.py`, `test_narration_retry_api.py`, `test_upload_and_override_api.py`, `test_draft_render_api.py` (only its `/render`/`/timeline/approve` setup calls — `/render/draft` itself is untouched and still asserted synchronously, per the note above). One genuine note on WHY the polling loop in `_polling.py` always converges on its first iteration under `TestClient`: Starlette runs a response's background tasks before the ASGI call returns, and `TestClient`'s in-process ASGI transport has no real concurrency with the test itself, so by the time `client.post(...)` returns at all the callback has already finished. The loop is still the right thing to write — it's what a real client against a real server has to do, and costs nothing extra here — it just never needs more than one pass in this suite.

**F0b — `GET /projects/{id}/shots/{shot_id}/asset` and `GET /projects/{id}/thumbnail`.** Both serve real, displayable image bytes for the first time — `asset.local_path`/`generated_clip.local_path`/`project.video_path` are all server filesystem paths. New `app/assets/thumbnails.py` owns the two derived-media operations (`cached_video_frame` — ffmpeg, roughly 10% into a clip clamped to [0.5s, 3s], never frame 0; `cached_resized_image` — Pillow, downscaled to at most 640px on the long edge, never upscaled) and the ONE cache-freshness rule both share: a cache file is reused whenever its own mtime is `>=` the source file's mtime, regenerated otherwise. Chosen over a content hash deliberately — a hash would need to read (and for video, decode) the whole source just to answer "has this changed", exactly the cost the cache exists to avoid; mtime is the same signal `RenderStep.is_satisfied` already trusts for the identical reason (see that step's own docstring on the stale-cache bug a naive "the file exists" check already shipped once). Generation is lazy — on first request, never at render/generation time — so a project nobody opens costs nothing extra.

- **The shot-asset endpoint doesn't always need the cache.** A plain bound image (the common case — every free-search result and every human upload) is streamed straight from disk with no derived file at all, since nothing needs generating; only a bound GENERATED CLIP that is itself a *video* (rung 5, image-to-video — detected by file suffix, since neither `Asset` nor `GeneratedClipModel` need a new column for this) goes through `cached_video_frame`, exactly the same function and the same mtime rule the thumbnail endpoint uses for `final.mp4`.
- **The thumbnail endpoint's source order matches F1 exactly:** `final.mp4` exists → a frame (never resized — F1 never asked for that on this path, so it comes back at the render's own resolution); no video yet → the FIRST shot's bound asset in TIMELINE order (`timeline.all_shots()[0]`, not `shot_id` order — the same reorder fix M9's earlier `/progress` note already made, for the identical "nothing enforces the coincidence" reason), resized; neither → `404`. Both real cases share ONE on-disk cache file (`cache/thumbnail.jpg`) keyed on the mtime rule above — a project moving from "shot-asset thumbnail" to "video thumbnail" the first time it renders needs no special-cased bookkeeping about which source produced the current cache, because the freshly-written `final.mp4` is simply newer than whatever was cached before it, and the very next request regenerates from the video.

Proven at three levels: `tests/unit/assets/test_thumbnails.py` (pure — the frame-timestamp clamp, including the short-clip end-of-file guard the [0.5s, 3s] floor alone can't provide, and the video-suffix detection); `tests/integration/test_thumbnails.py` (real ffmpeg/Pillow — a real decodable JPEG at the right dimensions, the `-ss` argument actually lands at the F1-mandated timestamp, and the encoder call is COUNTED, not just re-run twice by coincidence, to prove the cache genuinely skips regeneration when the source is unchanged and genuinely regenerates once a real filesystem mtime bump occurs); and `tests/e2e/test_media_endpoints_api.py` over the real HTTP surface (404s before anything exists, a real image served for a normal bound shot, the thumbnail fallback order proven end to end including the video-preference-once-rendered case, and a synthesised real MP4 bound to a shot via a hand-seeded `GeneratedClipModel` to prove the shot-asset endpoint's own frame-extraction path without needing a real fal.ai video generation call).

`ruff check backend`, `black --check backend`, `mypy backend/app` all clean from the repo root after every change above (`black` reformatted two files mechanically — line wrapping only). The full suite was run once, alone, after all of R2/R3/F0a/F0b landed — see this document's own top-level note on why never twice against the shared dev Postgres.

---

# Phase M10 — Hardening

## Advice

- **Prompt quality now beats new features.** By this point the pipeline works; output quality is almost entirely a function of the Director and Shot Planner prompts. Run the eval set, iterate on prompts, measure.
- **Fix the sharp edges you have been stepping over.** Every `# TODO` you wrote in M4–M8 is now cheap to resolve and will be expensive later.
- **Every bug gets a regression test** ([12_Testing_Strategy.md](12_Testing_Strategy.md)).
- **Profile before optimising.** It will be provider latency and FFmpeg, not your Python.
- **Reconcile the frozen docs with reality** and record what changed. A doc that lies is worse than no doc — and the next agent will trust it.

---

# 18. Cross-cutting concerns

## 18.1 Observability

Every log line carries: `timestamp`, `level`, `project_id`, `run_id`, `step`, `shot_id?`, `provider?`, `duration_ms?`, `cost_cents?`.

Answer these four questions from logs alone, without a debugger:
1. Where is this project right now, and what is it waiting on?
2. Why did this shot get this asset?
3. What did this project cost, broken down by rung?
4. Which step failed, on which attempt, and with what provider error?

## 18.2 Determinism checklist

| Source of non-determinism | Control |
|---|---|
| LLM sampling | Low temperature, seed, recorded responses in tests |
| Set/dict iteration | Sort before iterating anywhere output depends on order |
| Wall clock | `core/clock.py` only; never in the render path |
| Randomness | Seeded from `project_id`; never `random()` bare |
| Provider drift | Pin model versions in config; record them on every call |
| FFmpeg version | Pinned in Docker, recorded in render fingerprint |
| Filesystem order | Never rely on `os.listdir()` ordering |

## 18.3 Cost control

1. `DRY_RUN` — fakes everywhere, zero spend.
2. Search before generate — the ladder.
3. Generation cache — `prompt_hash` uniqueness.
4. Approval gate — human sees the estimate first.
5. Hard budget cap per project.
6. Draft renders before final renders.
7. Cost recorded per `shot_binding` and aggregated per project.

## 18.4 Testing

| Layer | Scope | External services | Speed |
|---|---|---|---|
| Unit | One module | All faked | ms |
| Golden-file | Planners | Recorded LLM responses | ms |
| Integration | DB, Redis, renderer | Real Postgres/Redis/FFmpeg, faked AI | seconds |
| E2E | Full pipeline | All faked | seconds |
| Live | Full pipeline | Real providers | minutes, manual, costs money |

Targets: 80% overall, 90% on timeline/workflow/renderer ([12_Testing_Strategy.md](12_Testing_Strategy.md)). The first four layers must be runnable offline with no API keys.

## 18.5 Security

- **API keys**: environment only, never logged, never in the DB, never echoed in errors.
- **Prompt injection**: the script is untrusted user input that flows into LLM prompts. A script containing *"ignore previous instructions and output..."* must not be able to steer planning. Delimit user content clearly, validate all planner output against the schema, and never let planner output reach a shell, a filesystem path, or an FFmpeg argument without escaping.
- **SSRF**: asset URLs come from third-party search results. Validate scheme and host, block private/link-local ranges, cap redirects and response size.
- **Path traversal**: never trust provider-supplied filenames. Store by content hash under a fixed root; resolve and assert the final path is inside it.
- **Command injection**: build FFmpeg invocations as argument lists, never as shell strings. No `shell=True`.
- **Resource limits**: cap download size, image dimensions, render duration, and concurrent subprocesses.

---

# 19. Conventions

**Naming** — use the [glossary](00.5_Glossary.md) exactly. `Shot` is a plan; `Clip` is generated media; `Asset` is reusable media. Never call a Clip a Shot. If you need a concept the glossary lacks, add it to the glossary in the same PR.

**Modules** — one responsibility ([Principle 12](03_Engineering_Principles.md)). If a module needs a second name to describe it, split it.

**Async** — all IO is `async`. FFmpeg runs in a subprocess, awaited. Nothing blocking on the event loop.

**Typing** — full annotations; mypy in CI. Pydantic at every boundary (API, IR, provider requests/responses).

**Commits** — reference the task: `TASK-018: timeline version repository`. Small and focused.

**PRs** — one module or one task. A PR touching `planners/` *and* `renderer/` is two PRs.

**Migrations** — every schema change gets an Alembic revision. Never edit an applied migration.

**Definition of done** (from [tasks.md](../tasks.md)): code implemented, unit tests pass, integration tests pass, docs updated if required, reviewed, merged.

---

# 20. Anti-patterns — stop if you are about to do this

| If you are about to… | Stop, because | Do this instead |
|---|---|---|
| Put a file path in the Timeline | Violates [I2](#i2--the-timeline-contains-decisions-never-media) | Put it in `shot_binding` / `asset` |
| Mutate a Timeline in place | Violates [I3](#i3--timeline-versions-are-immutable) | `TimelineService.append_version` |
| Call an LLM from the renderer | Violates [I5](#i5--rendering-is-a-pure-function) | Move the decision into a planner |
| Have a planner download a file | Violates [I4](#i4--ai-never-touches-state-io-or-money) | Fetch it in a deterministic step and pass it in |
| Import a service from another module | Violates [I7](#i7--modules-communicate-through-the-orchestrator) | Return a result; let the orchestrator sequence |
| `import httpx` outside `providers/` | Breaks the provider firewall | Add it behind a provider protocol |
| `os.getenv()` in a service | Violates [Principle 13](03_Engineering_Principles.md) | Inject `Settings` |
| Generate media before approval | Violates [I6](#i6--nothing-expensive-runs-before-approval) | Move it after the gate |
| Add a field only one module knows about | Hidden state; violates [I1](#i1--the-timeline-is-the-only-source-of-truth) | Timeline or workflow state |
| Skip the fake implementation | Breaks dry-run and the test suite | Fake first, always |
| Write a prompt inline in Python | Unversionable, untestable | `app/prompts/`, versioned |
| Retry a paid call without an idempotency key | Double-charges | Add the key |
| Normalise the Timeline into tables | See [canon 3.3](#33-timeline-storage-document-not-normalized-rows) | JSONB document + `shot_binding` |
| Introduce a new term | Ambiguity compounds | Add it to the glossary first |

---

# 21. Decisions — closed

These were genuine gaps in `00`–`12`. **All eight are now decided** (2026-08-14). Treat this table as binding; changing any of them means changing this table first, then the affected phase.

| ID | Question | Decision | Affects |
|---|---|---|---|
| **D1** | Where does narration audio come from, and how are timings obtained? | **TTS from the script, narration is the master clock.** ElevenLabs' timestamped endpoint returns timings with the audio — no forced-alignment step, no alignment error. Shot durations, audio sync and captions all derive from these timings. *(Corrected 2026-08-15: those timings are **character-level**, not word-level as originally written here. The decision is unchanged; the mechanism is simpler than assumed, since `Shot.narration_span` is already a character-offset pair — see [M8](#phase-m8--renderer).)* | M5, M8 |
| **D2** | Captions from script text or from transcribing the narration? | **Script text + TTS timings.** Transcribing our own generated audio would only re-introduce error and non-determinism. Follows directly from D1. | M8 |
| **D3** | Storage layout and retention. | `storage/{project_id}/{assets,clips,narration,music,renders}/{content_hash}.{ext}`. Content-hash filenames only — never provider-supplied names. Draft renders purged after 7 days (`DRAFT_RETENTION_DAYS`); finals kept. | M2 |
| **D4** | Which concrete providers ship in v1? | See the [provider roster](#211-provider-roster-v1) below. | M5–M8 |
| **D5** | Does a transition overlap adjacent shots or extend the timeline? | **Overlap.** Forced by D1 — extending the timeline per dissolve would drift video away from the narration clock cumulatively across the video. Planner duration arithmetic must match; implemented in exactly one function. | M5, M8 |
| **D6** | Background music in v1? | **Yes — a stock music library**, mixed under narration with automatic ducking. This makes music selection a *creative* decision, so it lives in the Timeline (see [21.2](#212-consequence-music-is-a-planning-decision)), not the renderer. | M5, M8 |
| **D7** | Maximum video length and shot count? | **90 seconds, max 40 shots.** Also: 1.5s ≤ shot ≤ 8.0s, max 12 scenes. Enforced in the Shot Planner prompt *and* validated on planner output. | M5, M7 |
| **D8** | Any auth in v1? | **No auth**, per [04_System_Architecture.md](04_System_Architecture.md). Do not let the single-user assumption leak into the data model — every table still carries the IDs a multi-user version would need. | M9 |

## 21.1 Provider roster (v1)

Exactly one concrete provider per protocol. [ADR-003](adr/ADR-003-Provider-Abstraction.md) makes adding more cheap later; committing now keeps M5–M8 focused.

| Protocol | Provider | Ladder rung | Notes |
|---|---|---|---|
| `LLMProvider` | **OpenAI** | — | All four planning agents. Must use structured / JSON-schema output — the IR is validated against Pydantic on every call. A cheaper model handles mechanical passes. |
| `ImageProvider` | **fal.ai** | 6 | Model chosen by bake-off (see below). FLUX-family models are the starting candidates for photoreal archival stills. |
| `VideoProvider` | **fal.ai** | 5 | Model chosen by bake-off. Uniform queue API across every hosted model, which is what the M4/M7 submit → persist-handle → poll → resume machinery is written against. |
| `NarrationProvider` | **ElevenLabs** | — | The `/with-timestamps` endpoint is **required**, not optional — D1 depends on the timings (character-level; see [M8](#phase-m8--renderer)). |
| `AssetProvider` | **Wikimedia Commons** | 2 | No key. A descriptive User-Agent with real contact details is required by their terms. |
| `AssetProvider` | **Pexels** | 4 | Stock imagery and footage. |
| `MusicProvider` | **Openverse** | — | Replaced Pixabay (no public Music/Audio API — see the caveat below); `MUSIC_PROVIDER=openverse` is the live default. |

### Why an aggregator for media generation

Both generative rungs go through **one** provider — fal.ai — rather than Google Veo direct plus OpenAI images. The reasoning:

- **The right model for this content is unknown and unknowable in advance.** "Which model produces convincing 1930s archival-style footage" is a narrow aesthetic question that no general benchmark answers. Picking a vendor up front is picking on reputation, not evidence.
- **So make it an experiment, not a procurement decision.** One integration, one key; comparing candidate models is a config change and a re-render of the fixture, not a new provider implementation.
- **It removes the worst integration in the stack.** Veo direct means a GCP project, service-account JSON, Vertex enablement, and quota requests. fal is an API key.
- **One queue abstraction instead of several.** Every hosted model exposes the same submit/poll semantics, so the crash-resume machinery in M4/M7 is written once.
- **Volume makes the markup irrelevant.** 90-second videos with generation at rungs 5–6 — the last resort after four search tiers — means a handful of clips per project. The aggregator's margin is noise next to the engineering time saved.

Accepted trade-offs: an aggregator margin, and a dependency whose outage stops all media generation. Both are tolerable here — the margin is small at this volume, and a failed generation already degrades to a placeholder without failing the render. Go direct later, on the model the bake-off proves out, with the interface already in place. **Replicate** is the equivalent alternative if fal disappoints.

> **`FAL_IMAGE_MODEL` and `FAL_VIDEO_MODEL` are deliberately unset in `.env.example`.** They are settled empirically in M7 by rendering the fixture through candidates and comparing output — not chosen here. Verify current model availability and pricing on fal's model pages before committing budget.

**Music provider caveat.** D6 specified a stock music library, but Epidemic Sound's API is partner-gated and Artlist has no public API.

~~v1 therefore ships against **Pixabay Music**~~ — **wrong, corrected 2026-08-15. Pixabay has no music or audio API at all.** Verified live against the real endpoints with a valid key: `/api/music/` returns **404**, `/api/audio/` returns **403**, and only `/api/` (images) and `/api/videos/` exist. The Pixabay docs list Images and Videos and nothing else. This claim sat in the guide unchallenged from M0 until someone tried to build against it — a reminder that "has a real public API" is a testable assertion and should have been tested when it was written.

**v1 therefore ships against [Openverse](https://api.openverse.org/v1/audio/)** — free, no API key required, and it aggregates Jamendo and Freesound behind one search. Verified live: `q=documentary ambient` returns 240 results, of which **81 are `cc0`/`by`**.

Two consequences that shape the implementation:
- **The licence gate is load-bearing, not ceremonial.** Openverse's unfiltered results are dominated by `by-nc-nd`, which is unusable twice over: **NoDerivatives** conflicts with bedding and ducking a track under narration, and **NonCommercial** limits what the finished video can be used for. Filter to `cc0`/`by` at the query, and gate again on the response.
- **The permissive pool is thin and uneven.** `documentary ambient` → 81 results; `tense drone` → 46; `historical documentary` → 2, and both of those are room-ambience field recordings rather than music. Freesound skews to sound effects, and the Jamendo material is mostly the `nc-nd` that gets filtered out. So a Director `music_plan` with narrow search terms (`sombre orchestral` returned **0**) will legitimately find nothing — graceful degradation to a silent-but-narrated render is a normal outcome here, not an error path.

`MUSIC_PROVIDER` in `.env` selects the implementation, so a licensed library still drops in unchanged if partner access is obtained.

**A note on image-generation quality.** `gpt-image-1` was the earlier choice mainly because it shared the planning account. FLUX-family models generally read more film-like for photoreal archival work. This matters less than it appears: [Principle 4](00_Creative_Philosophy.md) makes generated media the last fallback, and for historical content most shots should resolve from Wikimedia at rung 2. Image generation is the exception path, not the main one — do not over-invest in it.

## 21.2 Consequence: music is a planning decision

Under [I1](#i1--the-timeline-is-the-only-source-of-truth) and [I4](#i4--ai-never-touches-state-io-or-money), *choosing* a track is creative and belongs in the Timeline; *mixing* it is deterministic and belongs in the Renderer. So D6 adds:

- **`metadata.music_plan` in the IR** — mood, tempo, energy arc, and search terms, derived from the emotional progression the Director already produces ([Principle 11](00_Creative_Philosophy.md)).
- **A music-selection step** in the Asset Resolver, ranking candidates against `music_plan` the same way visual assets are ranked, with the same hard licence gate.
- **An audio mix stage** in the Renderer: narration at full level, music bedded at `MUSIC_BED_GAIN_DB` and ducked to `MUSIC_DUCK_GAIN_DB` while narration is speaking.

The music track is **not** a rung on the visual asset ladder — it is a parallel audio track with its own single source.

---

# 22. Working agreement for AI agents

If you are an AI agent picking up work in this repository:

1. **Read**, in order: [00.5_Glossary.md](00.5_Glossary.md) → this document's [Sections 1–6](#1-orientation-10-minutes) → the phase you are in → the ADR for the module you are touching. That is enough. Do not read all 14 documents.
2. **Locate yourself.** Check `tasks.md` and the phase table in [4.4](#44-phase-map). State which phase and task you are working on before writing code.
3. **Obey the [seven invariants](#2-the-seven-invariants).** They are the compressed form of every ADR. If a task appears to require violating one, stop and ask — do not work around it.
4. **Use glossary terms exactly.** Vocabulary drift is how a codebase becomes unnavigable to the next agent.
5. **One module per change.** Match the dependency direction in [Section 5](#5-repository-layout-and-module-ownership). If you need a back-edge, you have misplaced the logic.
6. **Write the fake before the real implementation**, and keep both.
7. **Run `make check` before reporting done.** Report failures honestly with output; never claim a green suite you did not see.
8. **When you discover a contradiction** between documents, do not silently pick one. Add it to [Section 3](#3-canon--resolving-contradictions-in-the-frozen-docs), state the resolution and the reason, and flag it.
9. **Update this document** when a phase completes, an open decision closes, or a new pitfall is found. It is the only living doc; its usefulness decays if it is not maintained.
10. **Do not add dependencies, frameworks, or abstraction layers** not named in the frozen docs without asking. [Principle 18](03_Engineering_Principles.md): simple first.

---

# 23. Quick reference

## Where does this belong?

| Thing | Location |
|---|---|
| A creative decision | Timeline IR |
| A file path or URL to media | `asset` / `generated_clip` table, referenced by `shot_binding` |
| Per-shot execution state | `shot_binding` |
| An external API call | `providers/` |
| SQL | `repositories/` |
| A prompt | `app/prompts/`, versioned |
| Sequencing logic | `orchestrator/` |
| A step implementation | `workflow/steps/` |
| A camera/animation effect | `renderer/` |
| Config | `core/config.py` → `Settings` |
| A new vocabulary term | [00.5_Glossary.md](00.5_Glossary.md), first |

## Phase → primary docs

| Phase | Read |
|---|---|
| M0 | This doc §6, [07_Timeline_IR](07_Timeline_IR.md) |
| M1 | [03_Engineering_Principles](03_Engineering_Principles.md) |
| M2 | [05_Domain_Model](05_Domain_Model.md), [10_Data_Model](10_Data_Model.md), canon §3.3 |
| M3 | [07_Timeline_IR](07_Timeline_IR.md), [ADR-006](adr/ADR-006-Immutable-Timeline.md) |
| M4 | [08_Workflow_Engine](08_Workflow_Engine.md), [ADR-005](adr/ADR-005-Commands-Not-State.md), [ADR-009](adr/ADR-009-Workflow-Steps.md) |
| M5 | [00_Creative_Philosophy](00_Creative_Philosophy.md), [06_Agent_Architecture](06_Agent_Architecture.md), [ADR-010](adr/ADR-010-Creative-Context.md) |
| M6 | [ADR-007](adr/ADR-007-Asset-Resolution.md), canon §3.1 |
| M7 | [ADR-008](adr/ADR-008-Human-In-The-Loop.md), §18.3 |
| M8 | [04_System_Architecture](04_System_Architecture.md), §18.2 |
| M9 | [09_API_Specification](09_API_Specification.md), [02_PRD](02_Product_Requirements_Document.md) |
| M10 | [12_Testing_Strategy](12_Testing_Strategy.md) |

## Provider → key → phase

| Provider | Env key | First needed |
|---|---|---|
| OpenAI (planning) | `OPENAI_API_KEY` | M5 |
| fal.ai (images + video) | `FAL_KEY` | M7 |
| ElevenLabs (narration) | `ELEVENLABS_API_KEY` | M5 |
| Wikimedia (archives) | *(no key — User-Agent required)* | M6 |
| Pexels (stock) | `PEXELS_API_KEY` | M6 |
| Openverse (music) | *(no key)* | M8 |
| Pixabay Music | `PIXABAY_API_KEY` | *(unused — no public Music/Audio API; see 21.1)* |

None are needed before M5 — `DRY_RUN=true` runs the whole pipeline on fakes and still produces an MP4.
As of 2026-08-15, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `FAL_KEY`, and
`PEXELS_API_KEY` are populated in `.env` and proven working against the
real APIs end-to-end (see the M5–M7 Implementation notes below); M8's
music rung is proven live against Openverse (no key needed — see the M8
steps 5-6 Implementation notes); `PIXABAY_API_KEY` is populated but stays
unexercised, since the API it would call does not exist.

## Current status

```
Documentation      ████████████ frozen at v1.0
Canon + build plan ████████████ this document
Decisions D1–D8    ████████████ closed 2026-08-14
Env template       ████████████ .env.example ready for keys
M0 Walking Skeleton ████████████ complete 2026-08-14 — real MP4, real FFmpeg, 4/4 tests green
M1 Foundation       ███████████░ venv, deps, ruff/black/mypy, Makefile, Docker configs, docker
                                 compose up verified (Postgres + Redis healthy); pre-commit
                                 hooks not yet set up
M2 Persistence      ████████████ complete 2026-08-14 — 11-table schema, Alembic migration
                                 applied, PostgresProjectRepository, e2e test runs against
                                 real Postgres, restart-survival proven
M3 Timeline Service ████████████ complete 2026-08-14 — append_version is the sole writer,
                                 additive-only enforcement, diff, approve, rollback_to;
                                 14/14 tests green (4 e2e + 9 new + health)
M4 Workflow Engine  ████████████ complete 2026-08-14 — 5-step pipeline, retry+backoff,
                                 real human-approval gate (render stops, approve resumes),
                                 real ShotBinding/Asset/GeneratedClip read-write, per-shot
                                 failure isolation, resumability proven across two engine
                                 instances; 18/18 tests green
M5 AI Planners      ████████████ complete 2026-08-14, hardened 2026-08-15 — real
                                 Director/Scene/Shot/Asset Planner chain over OpenAI
                                 structured output, one append_version per stage (v2..v5).
                                 First live paid run surfaced two real bugs, both fixed:
                                 cross-scene shot-id collisions (Shot Planner ids now
                                 namespaced by scene_id) and a resumability gap where a
                                 constraint-violating timeline could silently pass on
                                 retry (GenerateTimelineStep.is_satisfied now
                                 re-validates constraints, not just structural
                                 completeness). Planning model moved off gpt-4o to
                                 gpt-5.6-terra; openai_provider.py now falls back to a
                                 model's default temperature when a reasoning-tier model
                                 rejects a custom value. 93/93 tests green. **Hardened
                                 again 2026-08-15 (mid-M8, a live paid Hinglish run):**
                                 a third occurrence of the SAME lesson as the shot-id
                                 collision - the Shot Planner's outer narration-span
                                 boundaries (first shot starts at 0, last shot ends at
                                 the scene's true length) are structural facts, not
                                 model output to validate byte-for-byte, so they are
                                 now snapped in code before validation runs (large
                                 snaps logged, internal gaps still fail loudly). See
                                 this phase's own Implementation notes. 308/308 tests
                                 green.
M6 Asset Pipeline   ████████████ complete 2026-08-14, hardened 2026-08-15 — real Wikimedia
                                 (rungs 2+3) and Pexels (rung 4) search, licence hard-gate,
                                 content-hash dedup before ranking, explicit weighted
                                 ranking with logged component scores, within-project
                                 reuse penalty, magic-byte download validation;
                                 project_assets (rung 1) is a real stub pending an upload
                                 feature. First live paid run surfaced two real bugs, both
                                 fixed and verified against the live Wikimedia API: (1)
                                 search queries were concatenated into one long string
                                 per shot and, separately, the Asset Planner's own queries
                                 were sentence-length — verified empirically that even a
                                 single 9-word natural-language query returns zero
                                 results from Commons where a 2-word keyword query finds
                                 real archival photos; fixed via prompt + validator
                                 (max 6 words/query) + providers trying each query
                                 separately instead of joined. (2) the placeholder
                                 WIKIMEDIA_USER_AGENT value was silently blocklisted by
                                 Wikimedia's media CDN (upload.wikimedia.org) even though
                                 the search API tolerated it — every search succeeded,
                                 every download 403'd. A real contact value fixed it.
                                 DRY_RUN=true path unchanged; 93/93 tests green.
M7 Media Generation ████████████ complete 2026-08-14, verified live 2026-08-15 — real
                                 fal.ai image (Seedream, bounded sync poll) and video
                                 (Kling, image-to-video, real submit/poll/resume)
                                 generation, budget cap enforced per call, cost estimate
                                 on GET /progress, generation cache on prompt_hash.
                                 First real paid end-to-end run (project b06ea1f3)
                                 completed successfully: real Wikimedia/Pexels search +
                                 real fal.ai image generation for shots search couldn't
                                 fill, real FFmpeg render, $0.36 total. A second real run
                                 (project 58f0a5e6, same timeline reused with corrected
                                 asset-search queries — see M6 notes) needed zero
                                 generation calls: all 13 shots resolved from real
                                 archives, $0.00 spent. Bake-off (Step 0) still
                                 deliberately skipped — models are direct picks — but now
                                 genuinely proven against the real API, not just unit
                                 tested. 93/93 tests green.
Workflow Engine     ████████████ hardened 2026-08-15 — RenderStep.is_satisfied() only
  (M4 addendum)                  checked "does a video file exist", so a retry after
                                 resolve_assets fixed a shot's binding kept serving the
                                 OLD (e.g. all-placeholder) render forever. Now compares
                                 the render's file mtime against the latest shot_binding
                                 update and re-renders if any binding changed since.
                                 Also added ProjectStatus.AWAITING_APPROVAL and clear
                                 project.error on that transition, so a project that
                                 failed once and then succeeded on retry stops reporting
                                 the old failure via GET /status.
Code                ████████████ M0 + M2 + M3 + M4 + M5 + M6 + M7, all hardened by a
                                 real end-to-end paid run — renderer (M8) is still the
                                 M0 slideshow renderer: no real narration, no audio
                                 mixing, no captions yet
M8 Renderer        ████████████ ALL 6 STEPS DONE 2026-08-15 — ElevenLabs narration
  — PHASE DONE                  provider + content-hash cache, the master clock
                                 (character-level alignment reconciled into a new
                                 Timeline version), audio muxed onto the render via
                                 the concat FILTER, music (a pre-approval
                                 SelectMusicStep records a track's provenance in
                                 Timeline.music_plan - never a side table, D6/21.2 -
                                 and a deterministic ducking mix, static volume
                                 envelope, never a live sidechain compressor - I5 -
                                 bedded under narration), Ken Burns
                                 (camera.movement/direction/intensity -> zoompan
                                 expressions, fed exactly one decoded input frame
                                 per shot to avoid the well-known jitter-on-a-
                                 looped-still bug), and determinism + draft mode
                                 (render.fingerprint populated and skip-if-
                                 unchanged, PROVEN byte-for-byte via a real double-
                                 render - not asserted - plus the 480p draft path
                                 and DRAFT_RETENTION_DAYS wired to a real,
                                 opportunistic purge). Real gap found, corrected,
                                 not silently patched around: Pixabay has no public
                                 Music/Audio search API (verified live against the
                                 real endpoints) - replaced with Openverse (free,
                                 no key, verified live), which now returns real
                                 tracks with real licence gating (cc0/by only) and
                                 attribution. Narration proven live end to end on a
                                 real Hindi script: predicted 39.568s vs 39.5668s
                                 actual audio, 1.2ms across five separately
                                 synthesised segments. The ducking envelope proven
                                 with a real, isolated volume measurement (not just
                                 "ffmpeg exits 0"): >8dB measured against a 14dB
                                 configured gap. Determinism proven with a literal
                                 sha256 byte-equality check across two independent
                                 from-scratch renders (static, Ken Burns, and multi-
                                 shot-crossfade cases). Fingerprint cache-hit reuse
                                 proven through the real database, not just the
                                 pure hashing function. Draft mode proven both at
                                 the pure-fingerprint and the real-render level, and
                                 through the full HTTP API. Alongside this batch:
                                 A30a recalibrated the depiction check (see M6.5's
                                 own status line below) - both are part of the same
                                 "batch two" the numbers below reflect. 304/304
                                 suite green (up from 254), ruff/black/mypy clean
                                 from the repo root, both fixtures reseeded.
                                 Captions deliberately still out of scope (D2,
                                 unchanged).
M6.5 all 5 steps   ████████████ entity retrieval (`86d42e1`), Director-constraint
  — PHASE DONE                  enforcement at generation, the pipeline reorder +
                                 binding carry-forward, the upload endpoint + per-
                                 shot override, and vision-verifying searched assets
                                 all done and tested (see that section's Done-when +
                                 implementation notes for all five). Step 1: 2
                                 correct + 2 partial → 4 correct + 1 partial on the
                                 11-shot A17 benchmark. Step 2: vision check +
                                 bounded regeneration (A12-A14, A18-A19). Step 3: one
                                 ResolveAssetsStep parameterised by permitted ladder
                                 rungs, run twice (free search before approval, paid
                                 generation after narration - A5-A7, A21); ShotBinding
                                 carry-forward lives inside TimelineService._persist
                                 (A11/A20); a total search-provider outage still
                                 reaches the approval gate (A22). Step 4:
                                 project_assets (ladder rung 1) is real - uploads
                                 matched via the existing relevance gate, never a
                                 planner (A8/A23/A27); a per-shot override bypasses
                                 every gate and locks a shot's asset
                                 (A9/A10/A24/A25/A29); the A15 review gate fires
                                 after generation with exactly ONE exit - override,
                                 never "proceed anyway" (A26) - its own
                                 ProjectStatus.AWAITING_REVIEW, ahead of RenderStep
                                 (A28). Step 5: A16 resolved narrowly as A30 -
                                 vision-verify the TOP searched candidate only,
                                 skipped for entity-curated hits, drop-and-fall-
                                 through on rejection. Measured live with a real
                                 control (A30 on vs off, everything else identical):
                                 eliminated 5 unambiguously wrong picks (a Greek map,
                                 modern WWII-reenactor photos, a burning ship, a
                                 derelict Polish coal elevator, generic depot
                                 buildings) at the real, measured cost of 2
                                 defensible ones a vision-only check cannot confirm
                                 from pixels alone (a genuine Bundesarchiv Leuna
                                 photo; a genuine Fischer-Tropsch diagram) - net
                                 raw correct-count went DOWN (1/11), exactly the
                                 shape the decision itself predicted was possible.
                                 **Recalibrated as A30a (2026-08-15, part of the M8
                                 batch above):** rewrote the prompt to ask what the
                                 pixels can actually answer (reject confidently-
                                 wrong subject matter; never reject unverifiable
                                 specific identity). Round 1 over-corrected (let 2
                                 of the 5 wrong picks back in - diagnosed from the
                                 model's own reasoning, not guessed); round 2, re-
                                 measured live with the same control methodology,
                                 hit both targets at once: **3/11 resolve, all 5
                                 wrong picks stay eliminated, all 3 correct/
                                 defensible picks restored.** 254/254 suite green
                                 at step 5; 304/304 with A30a and the rest of the M8
                                 batch above, both Done-when boxes about seeing and
                                 overriding assets genuinely ticked - verified
                                 through the real HTTP API.
Next               **M8 is complete.** The user's next run is a real, paid,
                                 end-to-end render - flagging now, not after,
                                 exactly what that run will exercise for the FIRST
                                 time in this codebase's life: real Openverse music
                                 search against a live Director-written music_plan
                                 (proven so far only against ad-hoc queries and the
                                 DRY_RUN fake, never a real project's actual
                                 search terms), Ken Burns on real archival photos
                                 at final render resolution and duration (proven so
                                 far only on tiny synthetic test images and short
                                 clips), and the fingerprint cache actually saving a
                                 re-encode on a real multi-minute video rather than
                                 the small synthetic timelines the integration
                                 tests use. None of these are expected to fail -
                                 each is unit/integration-tested against the real
                                 API or the real encoder - but a real project is
                                 the first time all of them run together, at real
                                 scale, with money attached (Openverse itself is
                                 free; the risk is time/quality, not spend). Reuse
                                 projects 58f0a5e6-008d-468e-862a-e365e463878e
                                 (English) and 35290b04-584d-415e-9816-ab6a8998b3e2
                                 (Hindi, with real narration) via
                                 scripts/seed_test_project.py - their planning,
                                 assets and TTS are already paid for. Neither
                                 fixture has any uploads or a selected music track,
                                 so two fixture round-trip branches
                                 (seed_test_project.py's "fail loudly on an
                                 unrestorable upload", and music_plan.selected_track
                                 being restored for free as part of the Timeline
                                 JSON) remain unexercised by either reseed -
                                 documented, not silently assumed safe. M9
                                 (API/Frontend) and M10 (Hardening) remain
                                 unstarted.
```

---

**If you are lost:** re-read [Section 2](#2-the-seven-invariants), find your phase in [Section 4.4](#44-phase-map), and check [Section 20](#20-anti-patterns--stop-if-you-are-about-to-do-this) for what not to do. That is the whole system in three screens.
