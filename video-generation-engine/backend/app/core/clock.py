"""The only place `datetime.now()` is called.

Rendering must be deterministic (Invariant I5) — no wall-clock time may leak
into any render input. Everything that needs "now" imports it from here so
it stays a single, greppable seam.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
