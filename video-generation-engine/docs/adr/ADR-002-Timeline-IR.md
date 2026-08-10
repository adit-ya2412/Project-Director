# ADR-002

## Title

Timeline is the Source of Truth

---

## Status

Accepted

---

## Context

Multiple AI planners need to collaborate without conflicting state.

---

## Decision

All planners exchange and enrich a shared Timeline Intermediate Representation (IR).

---

## Consequences

Advantages

- Deterministic execution
- Easy debugging
- Versioning
- Partial regeneration

Disadvantages

- Timeline schema must remain stable.