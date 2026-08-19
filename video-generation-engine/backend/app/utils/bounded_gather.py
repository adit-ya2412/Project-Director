"""Bounded gather — the first concurrency primitive in `app/`.

Track C §3.2 / §11 Q4–Q5: four later consumers (shot planner, asset
planner, TTS, ffmpeg run encodes) share one helper so they cannot each
invent a slightly different gather. There is no `asyncio.gather` /
`Semaphore` / `as_completed` anywhere else in `app/` today; this file
is the one that introduces them, and `as_completed` is deliberately
absent — I5 forbids unordered iteration, and run/scene order is the
video's order.

A semaphore is the right instrument for ElevenLabs (concurrent-request
cap 3) and for local CPU (`cpu_count - 2`). It only *approximates*
OpenAI TPM (token cost per call varies; a `retention_fast` fragment
adds ~400 tokens, an act pass ~3,600), so every call is also retried
with backoff on `TransientError`. A 429 is absorbed where it happens
and never reaches step level — that is the load-bearing half of C1's
durability fix (§2.5). TPM-shaped limits are self-clearing within a
minute by construction; backoff is the right instrument.

`RateLimiter` (`app/assets/rate_limit.py`) is the wrong tool and must
not be reused here. It paces arrival rate (calls/sec). ElevenLabs
limits concurrency; OpenAI limits tokens/min. It matches neither.
(`RateLimiter` stays exactly where it is, in asset resolution, where
calls/sec genuinely is the Wikimedia constraint.)

Per-item failure isolation matches `ResolveAssetsStep`'s existing
per-shot behaviour: one scene's TTS failure must not cancel the other
64. Bare `asyncio.gather` cancels siblings on the first exception;
this helper returns each item's exception in place (`return_exceptions`
shape) and lets the caller decide.

Q5 (reserve → check → submit) lives in `reserve_then_gather`. The
reservation loop is serial so a sibling's reservation is already
visible to the next `check_budget`; submit is the gather, so the
network RTT is not serialised. A lock around check-and-submit was
rejected in §11 because it would put that RTT inside the lock.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from app.core.config import settings
from app.core.errors import TransientError
from app.core.logging import get_logger
from app.workflow.retry import backoff_sleep

T = TypeVar("T")
R = TypeVar("R")

logger = get_logger(__name__)


def _default_is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, TransientError)


def narration_concurrency() -> int:
    """ElevenLabs Starter's concurrent-request cap (§11 Q4). A semaphore
    of this size is the right instrument — concurrency is genuinely
    what that provider limits. Never less than 1 (a 0-cap config would
    deadlock the semaphore)."""
    return max(1, settings.narration_concurrency)


def planner_concurrency() -> int:
    """Derived LLM in-flight cap (§11 Q4): 8 ≈ 34% of `gpt-5.6-terra`'s
    500,000 TPM. Shot planning and asset planning share this budget —
    the two loops must stay sequential *with respect to each other*,
    each internally concurrent. This function is the one number both
    loops read so they cannot drift. A semaphore only approximates
    TPM; pair every call with `bounded_gather`'s backoff."""
    return max(1, settings.planner_concurrency)


def ffmpeg_run_concurrency() -> int:
    """Local CPU cap for parallel run encodes (§3.2): `cpu_count - 2`,
    floored at 1 so a 1- or 2-core box still renders."""
    cpus = os.cpu_count() or 2
    return max(1, cpus - settings.ffmpeg_reserved_cores)


async def bounded_gather(
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    concurrency: int,
    max_attempts: int | None = None,
    is_retryable: Callable[[BaseException], bool] | None = None,
) -> list[R | Exception]:
    """Run `worker` over `items` with a hard in-flight cap.

    Results are in input order regardless of completion order
    (`asyncio.gather`, never `as_completed`). Each item's exception,
    after retries are exhausted, is returned in that slot rather than
    raised — siblings keep running. `CancelledError` is not caught
    (it is a `BaseException`); cancelling the gather still cancels
    in-flight workers, which is the shutdown path.

    The semaphore is held across backoff, not released. Releasing it
    on a 429 would immediately admit another call into the same
    exhausted budget; holding it is what makes the cap actually bite
    while the limit clears.
    """
    if not items:
        return []

    attempts_allowed = (
        max_attempts if max_attempts is not None else settings.bounded_gather_max_attempts
    )
    attempts_allowed = max(1, attempts_allowed)
    retryable = is_retryable if is_retryable is not None else _default_is_retryable
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(item: T) -> R | Exception:
        async with semaphore:
            last_exc: Exception | None = None
            for attempt in range(1, attempts_allowed + 1):
                try:
                    return await worker(item)
                except Exception as exc:
                    last_exc = exc
                    if attempt >= attempts_allowed or not retryable(exc):
                        return exc
                    logger.info(
                        "bounded_gather.retry",
                        extra={"attempt": attempt, "error": str(exc)},
                    )
                    await backoff_sleep(attempt)
            assert last_exc is not None
            return last_exc

    # gather on the coroutines, not as_completed: order is the contract.
    return list(await asyncio.gather(*(_run_one(item) for item in items)))


async def reserve_then_gather(
    items: Sequence[T],
    *,
    reserve: Callable[[T], Awaitable[None]],
    check: Callable[[], Awaitable[None]],
    submit: Callable[[T], Awaitable[R]],
    release: Callable[[T], Awaitable[None]] | None = None,
    concurrency: int,
    max_attempts: int | None = None,
    is_retryable: Callable[[BaseException], bool] | None = None,
) -> list[R | Exception]:
    """Q5: reserve → check serially, then submit concurrently.

    `reserve` persists the pessimistic estimated cost (the same write
    `insert_pending` already does for M7's crash-recovery invariant,
    moved one step earlier). `check` is `check_budget` against a total
    that now includes sibling reservations. `submit` is the network
    call and runs inside `bounded_gather`.

    If `check` raises, every item reserved so far is `release`d and
    the error propagates — a budget halt must not leave dangling
    reservations that would poison the next run's spend total. A
    failed `submit` (exception in that item's result slot) is also
    `release`d; a successful submit keeps its reservation, which the
    existing completed-row cost already represents.
    """
    reserved: list[T] = []
    try:
        for item in items:
            await reserve(item)
            reserved.append(item)
            await check()
    except Exception:
        if release is not None:
            for item in reserved:
                await release(item)
        raise

    results = await bounded_gather(
        items,
        submit,
        concurrency=concurrency,
        max_attempts=max_attempts,
        is_retryable=is_retryable,
    )
    if release is not None:
        for item, result in zip(items, results, strict=True):
            if isinstance(result, Exception):
                await release(item)
    return results
