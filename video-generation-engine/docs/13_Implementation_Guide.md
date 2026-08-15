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
| **A26** | **The A15 gate fires after the generation pass whenever any shot ended `failed`, and has exactly ONE exit: resolve every failed shot. There is no "proceed anyway". A project cannot reach `completed` while any shot is failed.** | Decided by the user, 2026-08-15: "you should not be able to finish a video if we can't fix it." A button that ships a visibly broken video gets clicked reflexively, and generated media is the least reliable rung — the one most likely to be the thing failing. This is not a deadlock: the remedy is always available, because a per-shot upload (A24) bypasses every gate and always resolves. **Consequence, accepted deliberately:** an unattended run halts until a human acts, and a project with one unfixable shot stays unfinished rather than shipping with a placeholder. This overrides M7's "a 59-shot video with one gap is more useful than no video" **at the project level only** — per-shot isolation still holds during a pass (one shot failing never aborts the others), and the renderer still degrades gracefully; what changes is that the project is not marked complete. |
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

## Backlog — deferred, not blocking

Raised during the first real Hinglish run (2026-08-15, project `194ad0e7`, fixture `hinglish_test_project`). Deliberately not fixed then, so the run could continue.

- **LLM calls are never costed.** `llm_call.cost_cents` is `0` on every row — the column exists and token counts are recorded faithfully (that run: 23,607 in / 12,817 out across 15 planning calls on `gpt-5.6-terra`, plus 355,110 in / 768 out across 13 `gpt-4o-mini` vision calls), but nothing prices them. **Deferred by the user, 2026-08-15.** Needs a per-model price table in config and a cost computed at insert.
- **The approval-gate cost estimate reads 0¢ when generation is pending.** Same run: 10 of 14 shots were queued to generate and `estimated_cost_cents` still showed `0`. The estimate appears to count only shots whose *primary* `asset_plan.strategy` is a generation rung, missing every shot that arrived there by falling through the ladder — which, after M6.5, is the normal route. This defeats M7's own goal ("estimate cost before the approval gate and show it") precisely when the number matters most. Related to the item above but a separate defect: this one is about generation, not LLM calls.
- **Asset reuse is a soft ranking penalty, not a hard rule, and repeats visibly.** Same run bound one `Sasol_CTL,_Secunda.jpg` to both `sc_04_sh_03` (~30.0s) and `sc_05_sh_03` (~38.3s, the final shot) — the same photograph twice, six seconds apart, in a 41-second video. `already_used_hashes` reaches `rank_candidates` only as a `reuse_penalty` score component, so a reused candidate is demoted but stays eligible and wins anyway when the pool is thin. A hard exclusion is **not** obviously right — it would push the shot to paid generation, which would almost certainly look worse than a real photograph of the actual plant. The likelier fix is a *temporal* rule: penalise reuse far more heavily when the two shots are close together, and barely at all when they are far apart.
- **Landscape source material versus a vertical render.** The best archival images are wide (that Sasol photo is 3008×2000; the render is 720×1280), so a 9:16 crop keeps roughly the middle third and discards the sweep that made the composition work. Ken Burns mitigates it by moving across the frame rather than sitting in the centre. Not a bug — a standing tension between the material and the format, worth measuring on a real render before deciding whether it needs smarter cropping (e.g. saliency-aware rather than centre crop).

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
