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
> **Status:** designed 2026-08-15 from two real runs. Sequenced after M8 steps 1–3 (narration, done) and interleaved with M8 steps 4–6.

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

## Known gap, not yet scheduled

**Real video footage is never searched for.** `WikimediaAssetProvider` hardcodes `filetype:bitmap`, and the Pexels provider uses the photos endpoint, not `/videos/search`. So although a shot can declare `preferred_type: video`, every search rung can only return a still, and the *only* route to motion is generating it. For a WWII documentary that is backwards — genuine archival film exists on Commons and is better material than any generated clip.

Preference order for motion, once this is addressed: **real archival footage > Ken Burns on a real photograph (M8 step 5) > generated video.** Generated video is where synthetic artefacts are most visible, at roughly 12× the cost of an image (~50¢ vs ~4¢).

## Build order

1. **Entity retrieval (A1, A2), measured against the A17 benchmark.** Cheapest, needs no UI, improves quality automatically. Its result determines how much burden steps 3–4 must carry.
2. **Director-constraint enforcement at generation (A12, A13, A14).** Small, and the only harm-relevant item here.
3. **Pipeline reorder (A5, A7) plus binding carry-forward (A11).** The structural change that makes the step supervised. A11 is a hard prerequisite.
4. **Upload endpoint and per-shot override (A8, A9, A10, A15).** Only useful once 3 exists, since the gate is where a human acts on it.
5. **Reassess vision verification for search (A16)** against whatever failures actually remain.

**Caveat:** there is no frontend — M9 has not been built. "You see the images at approval" means, for now, an API exposing the resolved asset per shot plus files on disk. The full experience needs M9; the backend reordering is still worth doing first, so M9 is not built against the wrong pipeline shape.

## Done when

- [ ] The A17 benchmark improves substantially and is re-measured after every retrieval change — **in progress, deliberately not ticked.** Step 1 (`86d42e1`) moved it from 2 correct + 2 partial to 4 correct + 1 partial with zero regressions, and step 2 re-measured it unchanged (retrieval untouched). But 4/11 means **7 shots are still wrong**, and the phase goal is media that matches the script — a doubling is not a finish. The remaining failures are all generic, no-entity shots (`a wartime fuel depot`, `German tanks rail yard`) where free-text search's candidate pool contains nothing on-topic at all; no gate or ranking change reaches those, which is the evidence for steps 3–4 (uploads and a supervised gate) rather than more automated scoring. Re-measure after every retrieval change and only tick this when the number justifies it.
- [ ] A human can see real images per shot, and swap or override any of them, before anything expensive runs
- [ ] A human override survives re-resolution and version bumps
- [x] No generated image ships that violates a Director constraint — step 2, below.
- [x] Generation retries are bounded and counted against the project budget — step 2, below.

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

1. **`NarrationProvider` + ElevenLabs + persistence.** The Protocol in `providers/base.py` (it is named in that file's docstring but does not exist yet), `providers/elevenlabs.py` as the only file that touches the endpoint, a `narration` table (segment ↔ scene, audio path, `alignment` JSONB, voice/model/character count), and storage at `{project}/narration/{content_hash}.mp3` per D3. Cache on `hash(text + voice_id + model + output_format)` — a re-render must never re-pay for identical audio, the same discipline as `generated_clip.prompt_hash`.
2. **The master clock.** `app/timeline/narration_fit.py`: given a scene's alignment plus its shots' `narration_span`s, compute each shot's real spoken duration and reconcile. This writes a **new Timeline version** (`produced_by=narration`, `owns={"scenes", "metadata"}`) rather than mutating in place or fixing it up inside the renderer — corrected durations are a decision, so they belong in the IR (I1), and `append_version` is the only legal writer (I3).
3. **Mux narration into the render.** Leave the existing silent visual path exactly as it is; assemble one continuous narration track (hook + scenes in order) and mux it in a single final pass. Do **not** thread audio through the per-run `xfade` graph — that recreates precisely the progressive drift D5 exists to prevent.
4. **Music.** `MusicProvider` + Pixabay, the chosen track recorded somewhere durable (see open decisions), then the deterministic ducking mix: bed at `MUSIC_BED_GAIN_DB`, ducked to `MUSIC_DUCK_GAIN_DB` across every interval where narration is speaking — computed from the alignment arrays as a static volume envelope, never a live sidechain compressor (I5).
5. **Ken Burns.** `camera.movement`/`direction`/`intensity` → `zoompan`/`crop` expressions. Purely a renderer concern; no planner changes (canon 3.1).
6. **Determinism + draft mode.** Populate `render.fingerprint` — the column already exists and nothing writes it yet — and skip-if-unchanged; plus the 480p draft path.

## Multi-language (Hindi first) and the hook

Both are wanted for the first real M8 run, and neither is only a prompt change:

- **Language.** `Timeline.metadata.language` already exists and is carried through every version, but it is currently written once from `settings.default_language` and then never read by anything. M8 makes it real: the Director and Scene Planner must be *told* the target language and write `narration_text` in it directly, and `eleven_multilingual_v2` (already the configured default) covers Hindi through the same timestamped endpoint. **Plan in the target language; do not translate afterwards** — a translated line rarely takes the same time to speak as the original, so post-hoc translation reintroduces exactly the timing drift D1 exists to eliminate. Needs: a per-project language input (API + `Project`), that language threaded into the Director/Scene Planner user content, and a real `ELEVENLABS_VOICE_ID` (currently blank — pick it by listening; it is not a spec decision).
- **The hook.** A short opening line that earns the first three seconds. If the script already opens with one, nothing to do; if it doesn't, the Scene Planner should be able to write one. It **cannot** live in `narration_text`: `ScenePlanner._make_validator` hard-rejects any output whose concatenated `narration_text` is not verbatim-identical to the submitted script, and that check is load-bearing — it is what keeps narration traceable to its source. So the hook becomes a **new top-level `Timeline.hook: str | None`**, outside the verbatim check, with its own TTS segment spoken before scene 1, no `narration_span`, and no owning scene. Needs: the schema field, a Scene Planner prompt + output-schema change, and step 3 above prepending its audio.

## Open decisions for M8

None of these are settled. Answer them before or during the build, and record the answer here.

- **Per-scene TTS, or one request for the whole script?** Per-scene matches the data model (`narration_span` offsets are per-scene, so alignment indices line up with zero arithmetic), makes the cache per-scene (edit one scene, re-synthesise one scene), and keeps the per-scene shape every other planner already uses. Cost is identical either way — billing is per character. The real tradeoff is prosody: separately synthesised scenes will not flow into one another the way a single continuous read does. **Recommendation: per-scene**, then listen to a real render before deciding whether the seams matter.
- **What wins when real narration breaks a D7 cap?** Narration is the master clock (D1), so a shot must stretch to cover its words — but that can push a shot past `MAX_SHOT_DURATION_S`, or the whole video past the 90s `MAX_VIDEO_DURATION_S`. Truncating audio is not an option; it cuts words off mid-sentence. **Recommendation:** let per-shot duration exceed its cap (the cap is a planning heuristic; the narration is real), but treat exceeding total `MAX_VIDEO_DURATION_S` as an explicit, loud failure that tells the user to shorten the script — never a silent trim.
- **Narration runs after approval (I6), so approved durations are not final.** TTS costs money, so it cannot run before the gate — which means the timeline the user approves carries planner-estimated durations while the rendered video carries narration-corrected ones. That is defensible (approval is of the creative plan, not of millisecond timings), but it should be a deliberate choice rather than an accident, and the approval UI should eventually say so.
- **Where does the chosen music track live?** D6 puts music *selection* in the Timeline as a creative decision, but `music_plan` currently carries only `mood`/`tempo`/`energy_arc`/`search_terms`/`licence_requirements` — no chosen track. Either the selected track becomes a Timeline field (another `append_version`) or a `music` table row referenced by the render. The former is more consistent with D6 and I1; decide before building step 4.
- **Does TTS count against the budget cap?** `check_budget` currently sums `generated_clip.cost_cents` only. ElevenLabs bills per character, so a long script is a real — if small — cost. Folding narration into the same cap keeps that one number meaningful.

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

- [ ] Rendering the same project twice produces byte-identical output
- [ ] Audio stays in sync from first frame to last on a full 90-second video
- [ ] Music beds under narration and ducks cleanly; no clipping, no bed audible over the voice
- [ ] Draft and final modes both work
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
| `MusicProvider` | **Pixabay Music** | — | See the caveat below. |

### Why an aggregator for media generation

Both generative rungs go through **one** provider — fal.ai — rather than Google Veo direct plus OpenAI images. The reasoning:

- **The right model for this content is unknown and unknowable in advance.** "Which model produces convincing 1930s archival-style footage" is a narrow aesthetic question that no general benchmark answers. Picking a vendor up front is picking on reputation, not evidence.
- **So make it an experiment, not a procurement decision.** One integration, one key; comparing candidate models is a config change and a re-render of the fixture, not a new provider implementation.
- **It removes the worst integration in the stack.** Veo direct means a GCP project, service-account JSON, Vertex enablement, and quota requests. fal is an API key.
- **One queue abstraction instead of several.** Every hosted model exposes the same submit/poll semantics, so the crash-resume machinery in M4/M7 is written once.
- **Volume makes the markup irrelevant.** 90-second videos with generation at rungs 5–6 — the last resort after four search tiers — means a handful of clips per project. The aggregator's margin is noise next to the engineering time saved.

Accepted trade-offs: an aggregator margin, and a dependency whose outage stops all media generation. Both are tolerable here — the margin is small at this volume, and a failed generation already degrades to a placeholder without failing the render. Go direct later, on the model the bake-off proves out, with the interface already in place. **Replicate** is the equivalent alternative if fal disappoints.

> **`FAL_IMAGE_MODEL` and `FAL_VIDEO_MODEL` are deliberately unset in `.env.example`.** They are settled empirically in M7 by rendering the fixture through candidates and comparing output — not chosen here. Verify current model availability and pricing on fal's model pages before committing budget.

**Music provider caveat.** D6 specified a stock music library, but Epidemic Sound's API is partner-gated and Artlist has no public API. v1 therefore ships against **Pixabay Music** (free, permissive, real public API), behind a `MusicProvider` interface so a licensed library drops in unchanged if partner access is obtained. `MUSIC_PROVIDER` in `.env` selects the implementation.

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
| Pixabay Music | `PIXABAY_API_KEY` | M8 |

None are needed before M5 — `DRY_RUN=true` runs the whole pipeline on fakes and still produces an MP4.
As of 2026-08-15, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `FAL_KEY`, and
`PEXELS_API_KEY` are populated in `.env` and proven working against the
real APIs end-to-end (see the M5–M7 Implementation notes below);
`PIXABAY_API_KEY` is populated but not yet exercised — that's M8's music
rung.

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
                                 rejects a custom value. 93/93 tests green.
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
M8 Renderer        ██████░░░░░░ steps 1-3 done 2026-08-15 — ElevenLabs narration
                                 provider + content-hash cache, the master clock
                                 (character-level alignment reconciled into a new
                                 Timeline version), and audio muxed onto the render
                                 via the concat FILTER. Proven live end to end on a
                                 real Hindi script: predicted 39.568s vs 39.5668s
                                 actual audio, 1.2ms across five separately
                                 synthesised segments. Steps 4-6 (music+ducking,
                                 Ken Burns, determinism+draft) not started.
                                 Captions deliberately out of scope this pass.
M6.5 step 1+2      ████░░░░░░░░ entity retrieval (`86d42e1`) and Director-constraint
  (of 5)                        enforcement at generation both done and measured/tested
                                 (see that section's Done-when + implementation notes for
                                 both). Step 1: 2 correct + 2 partial → 4 correct + 1
                                 partial on the 11-shot A17 benchmark, zero regressions.
                                 Step 2: vision check + bounded regeneration (A12-A14,
                                 A18-A19) - 23 new tests, 204/204 suite green, DRY_RUN
                                 verified keyless by forcing OPENAI_API_KEY empty and
                                 watching the suite pass. Steps 3-5 (pipeline reorder +
                                 binding carry-forward, upload endpoint, reassess vision
                                 for search) not started.
Next               M6.5 step 3 · Pipeline reorder (A5, A7) plus binding carry-forward
                                 (A11) - move free retrieval before the approval gate;
                                 A11 is a hard prerequisite (bindings are keyed by
                                 timeline version and would otherwise be orphaned by an
                                 append_version). Then step 4 (upload endpoint, A8-A10,
                                 A15), step 5 (reassess vision for search, A16), then
                                 finish M8 steps 4-6. Reuse projects
                                 58f0a5e6-008d-468e-862a-e365e463878e (English) and
                                 35290b04-584d-415e-9816-ab6a8998b3e2 (Hindi, with
                                 real narration) via scripts/seed_test_project.py -
                                 their planning, assets and TTS are already paid for.
```

---

**If you are lost:** re-read [Section 2](#2-the-seven-invariants), find your phase in [Section 4.4](#44-phase-map), and check [Section 20](#20-anti-patterns--stop-if-you-are-about-to-do-this) for what not to do. That is the whole system in three screens.
