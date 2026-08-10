# ADR-004

## Title

Provider Abstraction Layer

---

## Status

Accepted

---

## Context

The system integrates with multiple external providers such as OpenAI, Gemini, Veo, ElevenLabs, Pexels, Wikimedia and future services.

Directly coupling business logic to provider SDKs would make replacing providers difficult.

---

## Decision

Every external integration will implement a common provider interface.

Examples

- ImageProvider
- VideoProvider
- AssetProvider
- NarrationProvider

Business logic interacts only with these interfaces.

Concrete implementations are selected through configuration.

---

## Consequences

Advantages

- Provider independence
- Easier testing
- Mockable integrations
- Future extensibility

Disadvantages

- Slight increase in abstraction