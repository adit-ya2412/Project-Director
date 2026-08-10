# ADR-009

## Title

Workflow as Explicit Pipeline Steps

---

## Status

Accepted

---

## Context

Complex AI workflows become difficult to monitor and debug when execution logic is hidden inside large functions.

---

## Decision

The production pipeline is modeled as explicit workflow steps.

Pipeline

```

Create Project

↓

Generate Timeline

↓

Approve Timeline

↓

Resolve Assets

↓

Generate Missing Media

↓

Render Video

↓

Completed

```

Each step:

- Has defined inputs
- Produces defined outputs
- Can be retried
- Can report progress
- Can fail independently

---

## Consequences

Advantages

- Easy debugging
- Resume support
- Better monitoring
- Partial execution
- Easier testing

Disadvantages

- Slight increase in orchestration complexity

---

## Future

Individual workflow steps may execute on distributed workers without changing business logic.