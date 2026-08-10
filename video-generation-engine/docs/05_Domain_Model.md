# Domain Model

**Project:** Video Generation Engine

**Version:** 1.0

---

# Purpose

This document defines the core business entities of the Video Generation Engine.

Every persistent object in the system should correspond to one of these domain models.

---

# Domain Hierarchy

```
Project
│
├── Script
├── Timeline
│   ├── Scene
│   │   ├── Shot
│   │   │   ├── AssetPlan
│   │   │   ├── Asset
│   │   │   └── GeneratedClip
│   │   └── SceneMetadata
│   └── TimelineMetadata
│
├── Workflow
└── Render
```

---

# Project

Root entity.

Represents one video generation request.

Fields

- id
- name
- description
- status
- created_at
- updated_at

Relationships

- One Script
- One Timeline
- Many Assets
- One Render

---

# Script

Original user input.

Fields

- id
- project_id
- content
- language
- version

---

# Timeline

Source of truth.

Contains every creative decision.

Fields

- id
- version
- total_duration
- status

Contains

- Scenes

---

# Scene

Logical narrative block.

Fields

- id
- title
- summary
- emotion
- duration
- order

Contains

- Shots

---

# Shot

Smallest planning unit.

Fields

- id
- intent
- duration
- camera
- transition
- asset_strategy
- prompt

Relationships

- AssetPlan
- Asset
- Clip

---

# AssetPlan

Planning object.

Defines how media should be acquired.

Fields

- strategy
- search_query
- preferred_type
- fallback

---

# Asset

Reusable media.

Fields

- id
- provider
- source
- type
- path
- license
- confidence

---

# Generated Clip

Media produced by AI.

Fields

- id
- provider
- duration
- prompt
- file_path

---

# Render

Represents final output.

Fields

- id
- output_path
- resolution
- fps
- duration
- status

---

# Workflow

Tracks execution.

Fields

- state
- progress
- current_step
- started_at
- completed_at

---

# Relationships

```
Project
    │
    ├── Script
    ├── Timeline
    │       │
    │       ├── Scene
    │       │      │
    │       │      ├── Shot
    │       │      │      │
    │       │      │      ├── AssetPlan
    │       │      │      ├── Asset
    │       │      │      └── Clip
    │
    └── Render
```

---

# Aggregate Root

Project is the Aggregate Root.

All operations originate from Project.

---

# Versioning

Versioned entities

- Script
- Timeline
- Render

Immutable history should be preserved.

---

# Summary

The domain model is intentionally simple.

The Project owns the production lifecycle, while the Timeline represents the complete creative plan that downstream components execute.