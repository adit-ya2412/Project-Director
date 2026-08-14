"""Exponential backoff with jitter (implementation guide, Phase M4 advice
— provider rate limits are the most common transient failure by a wide
margin)."""

import asyncio
import random


async def backoff_sleep(
    attempt: int, *, base_delay_s: float = 1.0, max_delay_s: float = 30.0
) -> None:
    """`attempt` is 1-indexed: the attempt number that just failed."""
    delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
    jitter = random.uniform(0, delay * 0.25)
    await asyncio.sleep(delay + jitter)
