# ADR-007

## Title

Human Approval Before Generation

---

## Status

Accepted

---

## Context

AI generation is the most expensive phase of the workflow.

Incorrect planning should be identified before media generation begins.

---

## Decision

The workflow pauses after Timeline generation.

The user reviews

- Scenes
- Shots
- Durations
- Camera plans
- Asset strategies

Only after approval does the engine proceed with media generation.

---

## Consequences

Advantages

- Lower generation cost
- Better creative control
- Easier iteration
- Fewer wasted AI calls

Disadvantages

- Adds one manual step to the workflow