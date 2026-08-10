# Timeline Intermediate Representation (IR)

**Version:** 1.0

---

# Purpose

The Timeline IR is the canonical data structure exchanged between all planning components.

Every planner receives a Timeline and returns an enriched Timeline.

---

# Flow

```
Script

↓

Timeline V1

↓

Timeline V2

↓

Timeline V3

↓

Approved Timeline

↓

Execution
```

---

# Timeline Structure

```
Timeline

├── Metadata
├── Scenes
│      ├── Shots
│      │      ├── Asset Plan
│      │      ├── Prompt
│      │      └── Camera
│
└── Workflow Metadata
```

---

# Metadata

Contains

- project_id
- version
- duration
- language

---

# Scene

Contains

- title
- summary
- emotion
- order
- duration

---

# Shot

Contains

- intent
- prompt
- duration
- framing
- camera
- transition
- asset_strategy

---

# Asset Plan

Contains

- search query
- provider
- preferred media
- fallback

---

# Timeline Evolution

```
Director

↓

Adds Scenes

↓

Scene Planner

↓

Adds Metadata

↓

Shot Planner

↓

Adds Shots

↓

Asset Planner

↓

Adds Asset Plans
```

Every planner enriches the Timeline.

Nothing is discarded.

---

# Immutability

Timeline versions are immutable.

Every modification creates a new version.

```
Timeline V1

↓

Timeline V2

↓

Timeline V3
```

---

# Serialization

The Timeline should support

- JSON
- Database persistence
- API responses

The internal representation should remain provider-independent.

---

# Example

```
Project

↓

Scene

↓

Shot

↓

Asset Strategy

↓

Prompt

↓

Transition
```

---

# Benefits

Using a shared Timeline IR provides

- deterministic workflows
- versioning
- debugging
- partial regeneration
- provider independence

---

# Summary

The Timeline IR is the backbone of the Video Generation Engine.

Every planner enriches it.

Every execution component consumes it.

It remains the single source of truth throughout the lifecycle of a project.