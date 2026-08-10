# System Architecture

**Project:** Video Generation Engine

**Version:** 1.0

---

# Purpose

This document describes the high-level architecture of the Video Generation Engine.

The system is designed as a **modular monolith** for Version 1 with clearly separated modules that can later evolve into independent services if required.

---

# Architectural Goals

- Modular
- Testable
- Deterministic
- Provider Independent
- Event Driven
- AI Assisted
- Easy to Extend

---

# High Level Flow

```
Script
    │
    ▼
Director
    │
    ▼
Timeline Generation
    │
    ▼
Scene Planning
    │
    ▼
Shot Planning
    │
    ▼
Asset Planning
    │
    ▼
Asset Resolution
    │
    ▼
Media Generation
    │
    ▼
Renderer
    │
    ▼
Final Video
```

---

# Architecture Overview

```
                  +----------------------+
                  |      Frontend        |
                  +----------+-----------+
                             |
                             |
                    REST / WebSocket
                             |
                             ▼
                  +----------------------+
                  |      FastAPI API     |
                  +----------+-----------+
                             |
                  +----------+-----------+
                  |      Orchestrator    |
                  +----------+-----------+
                             |
      -------------------------------------------------------
      |          |          |         |         |            |
      ▼          ▼          ▼         ▼         ▼            ▼
 Director   ScenePlanner ShotPlanner AssetPlanner Resolver Renderer
      |          |          |         |         |            |
      --------------------------------------------------------
                             |
                             ▼
                        PostgreSQL

                             |
                             ▼

                           Redis

                             |
                             ▼

                    External Providers

      OpenAI / Gemini / Veo / Pexels / Wikimedia / FFmpeg
```

---

# Core Components

## API Layer

Responsibilities

- Project CRUD
- Upload script
- Workflow APIs
- Progress APIs
- Asset APIs

Technology

- FastAPI

---

## Orchestrator

Central coordinator of the application.

Responsibilities

- Execute workflow
- Track state
- Retry failures
- Dispatch planner execution
- Trigger rendering

The Orchestrator contains no business logic.

---

## Director

AI component responsible for understanding the script.

Produces

- narrative structure
- pacing
- emotional flow
- scene boundaries

Output

Timeline V1

---

## Scene Planner

Converts narrative into scenes.

Produces

- scene title
- duration
- purpose
- emotion

---

## Shot Planner

Generates visual shots.

Each shot includes

- framing
- duration
- transition
- camera movement
- intent

---

## Asset Planner

Determines how each shot should obtain media.

Strategies

- Search
- Generate Image
- Generate Video

---

## Asset Resolver

Executes asset searches.

Sources

- Project Library
- Public Domain
- Wikimedia
- Stock Providers

Returns

Best matching asset.

---

## Media Generator

Invokes AI providers.

Supports

- Image Generation
- Video Generation

Stores generated outputs.

---

## Renderer

Produces final MP4.

Responsibilities

- Compose clips
- Apply transitions
- Sync narration
- Add captions
- Export

Uses

FFmpeg

---

# Data Flow

```
Script

↓

Timeline

↓

Scenes

↓

Shots

↓

Assets

↓

Generated Clips

↓

Rendered Video
```

Every stage enriches the previous stage.

---

# State Flow

```
Created

↓

Planning

↓

Pending Approval

↓

Generating Assets

↓

Rendering

↓

Completed
```

Failure state

```
Failed
```

---

# Backend Structure

```
backend/

app/

├── api/
├── orchestrator/
├── director/
├── planner/
├── workflow/
├── timeline/
├── renderer/
├── assets/
├── providers/
├── models/
├── schemas/
├── workers/
├── utils/
└── core/
```

---

# Storage

## PostgreSQL

Stores

- Projects
- Timelines
- Scenes
- Shots
- Assets
- Workflow State

---

## Redis

Stores

- Cache
- Workflow queues
- Temporary generation state
- Provider rate limiting

---

## File Storage

Stores

- Images
- Videos
- Audio
- Render Outputs

Version 1

Local filesystem

Future

S3 / GCS

---

# Provider Layer

All external services are accessed through provider interfaces.

Examples

```
ImageProvider

VideoProvider

NarrationProvider

AssetProvider
```

Core business logic never directly calls external APIs.

---

# Workflow Engine

The Workflow Engine coordinates execution.

Example

```
Generate Timeline

↓

Plan Scenes

↓

Plan Shots

↓

Resolve Assets

↓

Generate Media

↓

Render
```

Each step is independently executable.

---

# Error Handling

Every workflow step returns

- Success
- Failure
- Retry

Retries are configurable.

Failures are logged.

Workflow progress is preserved.

---

# Scalability

Version 1

- Modular Monolith
- Single Database
- Local Workers

Future

- Distributed Workers
- Queue Based Execution
- Object Storage
- Multiple Render Nodes

The internal architecture should not require major redesign when scaling.

---

# Security

Version 1

- API Keys
- Environment Variables
- Provider Isolation
- Input Validation

Future

- Authentication
- Authorization
- Team Workspaces

---

# Architectural Decisions

This architecture is based on the following principles.

- Timeline is the Source of Truth.
- AI Plans.
- Software Executes.
- Rendering is Deterministic.
- Providers are Replaceable.
- Workflows are Event Driven.
- Human Approval before Expensive Operations.

---

# Version 1 Scope

Included

- Script to Timeline
- Timeline to Scenes
- Scene to Shots
- Asset Resolution
- AI Media Generation
- Rendering

Excluded

- Research Agent
- Brand Profiles
- Collaboration
- Publishing
- Analytics

---

# Summary

The Video Generation Engine is built around a modular workflow where AI is responsible for planning and deterministic services are responsible for execution.

Every stage enriches the Timeline until sufficient information exists to render a final video.