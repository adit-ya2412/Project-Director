"""Bounded gather — ordering, isolation, retry, caps, Q5 reservation.

Pure asyncio, no DB, no network. `backoff_sleep` is stubbed to keep
retry tests off the real exponential clock.
"""

import asyncio
import inspect

import pytest

from app.core.errors import PermanentError, TransientError
from app.utils import bounded_gather as gather_mod
from app.utils.bounded_gather import (
    bounded_gather,
    ffmpeg_run_concurrency,
    narration_concurrency,
    planner_concurrency,
    reserve_then_gather,
)


@pytest.fixture
def no_backoff(monkeypatch):
    async def _instant(_attempt, **_kwargs):
        return None

    monkeypatch.setattr(gather_mod, "backoff_sleep", _instant)


def test_helper_does_not_use_as_completed_or_rate_limiter():
    """I5: unordered iteration is forbidden; §11 Q4: RateLimiter paces
    the wrong quantity. Both are load-bearing absences, not style."""
    source = inspect.getsource(gather_mod)
    # The docstring names both as things this file must not *call*.
    # Match the call forms, not the words.
    assert "asyncio.as_completed" not in source
    assert "RateLimiter(" not in source
    assert "from app.assets.rate_limit" not in source
    assert "asyncio.gather" in source


async def test_empty_input_returns_empty_list():
    async def worker(_item: int) -> int:
        raise AssertionError("worker must not run on an empty input")

    assert await bounded_gather([], worker, concurrency=3) == []


async def test_results_are_in_input_order_even_when_later_items_finish_first():
    async def worker(i: int) -> int:
        # Higher index finishes first — if anyone reaches for
        # as_completed, this test fails.
        await asyncio.sleep(0.02 * (6 - i))
        return i

    assert await bounded_gather(range(6), worker, concurrency=6) == list(range(6))


async def test_concurrency_never_exceeds_cap():
    in_flight = 0
    max_seen = 0

    async def worker(_i: int) -> None:
        nonlocal in_flight, max_seen
        in_flight += 1
        max_seen = max(max_seen, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1

    await bounded_gather(range(12), worker, concurrency=3)
    assert max_seen <= 3
    assert max_seen == 3


async def test_one_items_failure_does_not_cancel_siblings():
    async def worker(i: int) -> int:
        if i == 2:
            raise PermanentError("scene 2 failed")
        await asyncio.sleep(0.01)
        return i

    results = await bounded_gather(range(5), worker, concurrency=3)
    assert results[0] == 0
    assert results[1] == 1
    assert isinstance(results[2], PermanentError)
    assert "scene 2 failed" in str(results[2])
    assert results[3] == 3
    assert results[4] == 4


async def test_transient_error_is_retried_then_succeeds(no_backoff):
    calls = {"n": 0}

    async def worker(i: int) -> int:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("429")
        return i

    results = await bounded_gather([7], worker, concurrency=1, max_attempts=3)
    assert results == [7]
    assert calls["n"] == 3


async def test_exhausted_transient_error_is_returned_not_raised(no_backoff):
    calls = {"n": 0}

    async def worker(_i: int) -> int:
        calls["n"] += 1
        raise TransientError("still 429")

    results = await bounded_gather(["x"], worker, concurrency=1, max_attempts=3)
    assert len(results) == 1
    assert isinstance(results[0], TransientError)
    assert calls["n"] == 3


async def test_permanent_error_is_not_retried(no_backoff):
    calls = {"n": 0}

    async def worker(_i: int) -> int:
        calls["n"] += 1
        raise PermanentError("schema")

    results = await bounded_gather(["x"], worker, concurrency=1, max_attempts=5)
    assert isinstance(results[0], PermanentError)
    assert calls["n"] == 1


async def test_custom_is_retryable_overrides_default(no_backoff):
    calls = {"n": 0}

    async def worker(_i: int) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("flaky")
        return "ok"

    results = await bounded_gather(
        [1],
        worker,
        concurrency=1,
        max_attempts=2,
        is_retryable=lambda exc: isinstance(exc, ValueError),
    )
    assert results == ["ok"]
    assert calls["n"] == 2


async def test_zero_concurrency_does_not_deadlock():
    async def worker(i: int) -> int:
        return i

    assert await bounded_gather([1, 2], worker, concurrency=0) == [1, 2]


def test_narration_cap_is_elevenlabs_starter_concurrency(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "narration_concurrency", 3)
    assert narration_concurrency() == 3
    monkeypatch.setattr(settings, "narration_concurrency", 0)
    assert narration_concurrency() == 1


def test_shot_and_asset_planner_share_one_cap(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "planner_concurrency", 8)
    assert planner_concurrency() == 8
    # One function, two consumers — a second function with a different
    # default is how the TPM budget would get double-spent.
    assert planner_concurrency is gather_mod.planner_concurrency


def test_ffmpeg_cap_is_cpu_count_minus_reserved(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ffmpeg_reserved_cores", 2)
    monkeypatch.setattr(gather_mod.os, "cpu_count", lambda: 8)
    assert ffmpeg_run_concurrency() == 6
    monkeypatch.setattr(gather_mod.os, "cpu_count", lambda: 2)
    assert ffmpeg_run_concurrency() == 1
    monkeypatch.setattr(gather_mod.os, "cpu_count", lambda: None)
    assert ffmpeg_run_concurrency() == 1


async def test_reserve_then_gather_reserves_and_checks_before_any_submit():
    events: list[tuple] = []

    async def reserve(i: int) -> None:
        events.append(("reserve", i))

    async def check() -> None:
        events.append(("check",))

    async def submit(i: int) -> int:
        events.append(("submit", i))
        return i

    results = await reserve_then_gather(
        [1, 2, 3],
        reserve=reserve,
        check=check,
        submit=submit,
        concurrency=3,
    )
    assert results == [1, 2, 3]
    first_submit = next(i for i, e in enumerate(events) if e[0] == "submit")
    assert events[:first_submit] == [
        ("reserve", 1),
        ("check",),
        ("reserve", 2),
        ("check",),
        ("reserve", 3),
        ("check",),
    ]


async def test_reserve_then_gather_check_sees_prior_reservations():
    """The TOCTOU Q5 exists to close: each check observes every earlier
    reserve in this batch, so N concurrent items cannot all pass a
    check that only N-1 should."""
    spent = {"cents": 0}

    async def reserve(_i: int) -> None:
        spent["cents"] += 50

    async def check() -> None:
        if spent["cents"] > 100:
            raise PermanentError("budget")

    async def submit(i: int) -> int:
        return i

    with pytest.raises(PermanentError, match="budget"):
        await reserve_then_gather(
            [1, 2, 3],
            reserve=reserve,
            check=check,
            submit=submit,
            concurrency=3,
        )
    # Third reserve pushed spend to 150; check halted before any submit.
    assert spent["cents"] == 150


async def test_reserve_then_gather_releases_on_check_failure():
    reserved: list[int] = []
    released: list[int] = []

    async def reserve(i: int) -> None:
        reserved.append(i)

    async def check() -> None:
        if len(reserved) >= 2:
            raise PermanentError("budget")

    async def submit(i: int) -> int:
        raise AssertionError("submit must not run after a budget halt")

    async def release(i: int) -> None:
        released.append(i)

    with pytest.raises(PermanentError, match="budget"):
        await reserve_then_gather(
            [1, 2, 3],
            reserve=reserve,
            check=check,
            submit=submit,
            release=release,
            concurrency=3,
        )
    assert reserved == [1, 2]
    assert released == [1, 2]


async def test_reserve_then_gather_releases_failed_submit_only():
    released: list[int] = []

    async def reserve(_i: int) -> None:
        return None

    async def check() -> None:
        return None

    async def submit(i: int) -> int:
        if i == 2:
            raise PermanentError("provider")
        return i

    async def release(i: int) -> None:
        released.append(i)

    results = await reserve_then_gather(
        [1, 2, 3],
        reserve=reserve,
        check=check,
        submit=submit,
        release=release,
        concurrency=3,
    )
    assert results[0] == 1
    assert isinstance(results[1], PermanentError)
    assert results[2] == 3
    assert released == [2]
