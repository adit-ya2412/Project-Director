# ADR-003

## Title

Central Workflow Orchestrator

---

## Status

Accepted

---

## Context

Workflow coordination should not be duplicated across modules.

---

## Decision

A dedicated Orchestrator manages execution order, retries, workflow state, and event publishing.

---

## Consequences

Advantages

- Single coordination point
- Simpler monitoring
- Easier workflow extensions