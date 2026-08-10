# ADR-001

## Title

Use a Modular Monolith for Version 1

---

## Status

Accepted

---

## Context

The project requires multiple logical components but does not initially require distributed services.

---

## Decision

Implement Version 1 as a Modular Monolith.

Modules remain isolated through interfaces.

---

## Consequences

Advantages

- Simpler deployment
- Easier debugging
- Faster development

Disadvantages

- Single deployment unit
- Limited horizontal scaling

Migration to microservices remains possible because modules are already isolated.