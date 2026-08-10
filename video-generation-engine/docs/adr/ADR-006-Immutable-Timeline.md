# ADR-005

## Title

Immutable Timeline

---

## Status

Accepted

---

## Context

Planning agents progressively enrich the Timeline.

Overwriting previous planning decisions would make debugging and regeneration difficult.

---

## Decision

Timeline versions are immutable.

Every planning stage creates a new version.

Example

```
Timeline V1

↓

Timeline V2

↓

Timeline V3
```

Older versions remain available for inspection and rollback.

---

## Consequences

Advantages

- Easy debugging
- Version history
- Safe regeneration
- Better auditing

Disadvantages

- Increased storage requirements