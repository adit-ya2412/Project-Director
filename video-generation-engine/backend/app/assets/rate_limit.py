"""A minimal async rate limiter (implementation guide, Phase M6 advice:
"respect rate limits... Wikimedia will block you otherwise, and their API
terms require it."). One instance per provider, reused across every call
made during a single resolve_assets run."""

import asyncio
import time


class RateLimiter:
    def __init__(self, calls_per_second: float) -> None:
        self._min_interval = 1.0 / calls_per_second if calls_per_second > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()
