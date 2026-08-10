# ADR-005

## Title

Commands, Not Shared State

---

## Status

Accepted

---

## Context

The Video Generation Engine consists of multiple planning modules and deterministic services working together to produce a video.

Allowing components to directly modify shared application state tightly couples modules, makes execution order difficult to reason about, and introduces unintended side effects.

As the system grows, shared mutable state becomes increasingly difficult to debug and test.

---

## Decision

Components communicate by issuing **commands** and producing **results**, rather than directly modifying shared state.

Each module receives a well-defined input, performs its responsibility, and returns a well-defined output.

Example

```
Director

↓

GenerateTimelineCommand

↓

Timeline
```

```
Shot Planner

↓

GenerateShotsCommand

↓

Updated Timeline
```

The Orchestrator is responsible for coordinating commands and persisting results.

Business modules should never directly update database records owned by another module.

---

## Principles

- Modules consume commands.
- Modules return results.
- Modules do not call each other directly.
- Modules do not mutate another module's state.
- The Orchestrator controls execution order.

---

## Example Workflow

```
Project Created

↓

GenerateTimelineCommand

↓

TimelineGenerated

↓

ApproveTimelineCommand

↓

TimelineApproved

↓

ResolveAssetsCommand

↓

AssetsResolved

↓

GenerateMediaCommand

↓

MediaGenerated

↓

RenderVideoCommand

↓

RenderCompleted
```

---

## Consequences

### Advantages

- Loose coupling
- Easier testing
- Predictable execution
- Better observability
- Easier retries
- Simpler distributed execution
- Clear ownership of responsibilities

### Disadvantages

- More command objects
- Additional orchestration logic

---

## Future

This approach enables future migration to:

- Message queues
- Event-driven architecture
- Distributed workers
- Microservices

without significant changes to business logic.

---

## Rationale

Business logic should focus on **what needs to happen**, while the Orchestrator decides **when and in what order it happens**.

This separation keeps the system modular, deterministic, and easy to evolve.