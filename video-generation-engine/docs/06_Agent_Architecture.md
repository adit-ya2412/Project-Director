# Agent Architecture

**Version:** 1.0

---

# Purpose

This document defines the AI agents responsible for planning the video generation workflow.

Agents make creative decisions.

They never execute deterministic operations.

---

# Agent Pipeline

```
Director

↓

Scene Planner

↓

Shot Planner

↓

Asset Planner
```

Each agent enriches the Timeline.

---

# Director

Input

- Script

Output

- Timeline
- Narrative
- Story Flow

Responsibilities

- Understand script
- Identify story arc
- Split into scenes
- Estimate pacing

---

# Scene Planner

Input

Timeline

Output

Scenes

Responsibilities

- Scene titles
- Scene summaries
- Emotional tone
- Duration

---

# Shot Planner

Input

Scene

Output

Shots

Responsibilities

- Camera angle
- Duration
- Shot intent
- Transition
- Prompt

---

# Asset Planner

Input

Shot

Output

Asset Plan

Responsibilities

- Search strategy
- Query generation
- Asset type
- AI generation fallback

---

# Future Agents

Version 2

- Research Agent
- Music Planner
- Thumbnail Planner
- Caption Planner
- SEO Planner

---

# Shared Context

Every agent receives

- Script
- Timeline
- Previous decisions
- Style preferences

Agents never modify completed stages directly.

---

# Rules

Agents should

- Produce structured output
- Never call APIs
- Never download assets
- Never render video

Their responsibility ends at planning.

---

# Summary

AI agents are planners.

Execution belongs to deterministic services.