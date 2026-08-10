# ADR-006

## Title

Search Before Generation

---

## Status

Accepted

---

## Context

AI media generation is expensive and may produce inconsistent results.

Many required visuals already exist as public-domain, historical, stock or project assets.

---

## Decision

Every shot follows the same asset acquisition strategy.

Priority

1. Project Assets
2. Historical Archives
3. Public Domain
4. Stock Providers
5. AI Video
6. AI Image

Generation occurs only if no acceptable asset is found.

---

## Consequences

Advantages

- Lower cost
- Faster workflows
- Better historical accuracy
- Higher consistency

Disadvantages

- Additional search latency