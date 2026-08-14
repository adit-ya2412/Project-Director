"""Error taxonomy.

Every exception in the system is one of these three. Provider integrations
map their SDK-specific exceptions into these at the provider boundary —
nothing above `providers/` should ever see a raw SDK exception.
"""


class EngineError(Exception):
    """Base class for all engine errors."""


class TransientError(EngineError):
    """Rate limit, timeout, 5xx, connection reset. Safe to retry."""


class PermanentError(EngineError):
    """Invalid script, schema violation, licence rejected, budget exceeded.

    Not retryable — a human or a code change must intervene.
    """


class UserActionRequired(EngineError):
    """Awaiting approval, ambiguous input, manual asset needed.

    The workflow pauses; it does not fail.
    """
