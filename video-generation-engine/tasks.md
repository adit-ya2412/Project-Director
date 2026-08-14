# Video Generation Engine - Task Tracker

**Project Status:** 🟡 Planning Complete

---

# Overall Progress

- [x] Documentation
- [x] Repository Structure
- [x] Backend Foundation
- [ ] Database (Postgres + Alembic done; Redis not yet wired into app code)
- [ ] Domain Models (Project/Script/Timeline done; Asset/Render/Workflow are schema-only)
- [ ] Workflow Engine
- [ ] AI Agents
- [ ] Asset Pipeline
- [ ] Rendering
- [ ] API
- [ ] Frontend
- [ ] MVP

---

TASK-000 Freeze Documentation v1.0

> **Note (2026-08-14):** actual build order follows `docs/13_Implementation_Guide.md`'s
> vertical slices (M0-M10), not this sprint list — see that doc's section 4.1 for why.
> Checkboxes below are updated to reflect real progress regardless of which sprint a
> task originally sat under.

# Sprint 1 — Foundation

## Repository

- [x] TASK-001 Create backend structure
- [ ] TASK-002 Create frontend structure
- [x] TASK-003 Setup FastAPI
- [x] TASK-004 Setup Docker
- [x] TASK-005 Setup docker-compose (Postgres + Redis verified healthy 2026-08-14)
- [x] TASK-006 Setup configuration management
- [x] TASK-007 Setup logging
- [x] TASK-008 Setup linting (ruff)
- [x] TASK-009 Setup formatting (black)
- [ ] TASK-010 Setup pre-commit hooks

---

# Sprint 2 — Database

- [x] TASK-011 PostgreSQL (running via docker-compose, full schema applied)
- [x] TASK-012 SQLAlchemy (async engine, 11 models)
- [x] TASK-013 Alembic (initial migration generated + applied)
- [ ] TASK-014 Redis (container running; no application code uses it yet)
- [x] TASK-015 File Storage (local filesystem, `STORAGE_ROOT`-based)

---

# Sprint 3 — Domain Models

- [x] TASK-016 Project Model (table + repository, exercised by tests)
- [x] TASK-017 Script Model (table + repository, exercised by tests)
- [x] TASK-018 Timeline Model (`timeline_version` table + Pydantic IR, exercised by tests)
- [x] TASK-019 Scene Model (embedded in the Timeline IR JSONB — canon 3.3 supersedes a separate table)
- [x] TASK-020 Shot Model (embedded in the Timeline IR JSONB — canon 3.3 supersedes a separate table)
- [ ] TASK-021 Asset Model (table exists; no code writes to it yet — lands with M6)
- [ ] TASK-022 Render Model (table exists; no code writes to it yet — lands with M8)
- [ ] TASK-023 Workflow Model (`workflow_run`/`workflow_step_attempt` tables exist; no code writes to them yet — lands with M4)

---

# Sprint 4 — Core Services

- [ ] TASK-024 Project Service
- [ ] TASK-025 Timeline Service
- [ ] TASK-026 Asset Service
- [ ] TASK-027 Render Service

---

# Sprint 5 — AI Planning

- [ ] TASK-028 Director Agent
- [ ] TASK-029 Scene Planner
- [ ] TASK-030 Shot Planner
- [ ] TASK-031 Asset Planner

---

# Sprint 6 — Workflow Engine

- [ ] TASK-032 Workflow Engine
- [ ] TASK-033 Event System
- [ ] TASK-034 Workflow State Machine
- [ ] TASK-035 Retry Engine

---

# Sprint 7 — Asset Pipeline

- [ ] TASK-036 Asset Resolver
- [ ] TASK-037 Wikimedia Provider
- [ ] TASK-038 Pexels Provider
- [ ] TASK-039 Local Asset Provider
- [ ] TASK-040 Asset Ranking

---

# Sprint 8 — AI Providers

- [ ] TASK-041 OpenAI Provider (planning LLM only)
- [ ] TASK-042 fal.ai client + model bake-off (see Implementation Guide, M7 Step 0)
- [ ] TASK-043 Image Provider (fal, rung 6)
- [ ] TASK-044 Video Provider (fal, rung 5 — submit/poll/resume)
- [ ] TASK-045 Narration Provider (ElevenLabs, word timings required)

---

# Sprint 9 — Rendering

- [ ] TASK-046 FFmpeg Pipeline
- [ ] TASK-047 Caption Generator
- [ ] TASK-048 Audio Synchronization
- [ ] TASK-049 Video Renderer
- [ ] TASK-050 MP4 Export

---

# Sprint 10 — REST API

- [ ] TASK-051 Projects API
- [ ] TASK-052 Script API
- [ ] TASK-053 Timeline API
- [ ] TASK-054 Asset API
- [ ] TASK-055 Workflow API
- [ ] TASK-056 Render API

---

# Sprint 11 — Frontend

- [ ] TASK-057 Project Dashboard
- [ ] TASK-058 Script Upload
- [ ] TASK-059 Timeline Viewer
- [ ] TASK-060 Asset Viewer
- [ ] TASK-061 Workflow Progress
- [ ] TASK-062 Render Page

---

# Sprint 12 — Polish

- [ ] TASK-063 Error Handling
- [ ] TASK-064 Performance Improvements
- [ ] TASK-065 Logging Improvements
- [ ] TASK-066 Testing
- [ ] TASK-067 Documentation Review
- [ ] TASK-068 MVP Release

---

# Stretch Goals

- [ ] Research Agent
- [ ] Thumbnail Generator
- [ ] Music Planner
- [ ] Publishing Pipeline
- [ ] YouTube Integration
- [ ] Multi-language Support
- [ ] Team Workspaces
- [ ] Long-form Videos

---

# Definition of Done

A task is complete when:

- [ ] Code implemented
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Documentation updated (if required)
- [ ] Code reviewed
- [ ] Merged into main

---

# MVP Success Criteria

The project is considered MVP complete when a user can:

- [ ] Create a project
- [ ] Paste a script
- [ ] Generate a timeline
- [ ] Approve the timeline
- [ ] Resolve assets
- [ ] Generate missing media
- [ ] Render a final MP4
- [ ] Download the completed video