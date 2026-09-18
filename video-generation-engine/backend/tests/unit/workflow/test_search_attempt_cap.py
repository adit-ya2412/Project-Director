"""The search pass gives up rather than retrying a shot forever.

Measured 2026-09-17 on project c2b422f5: 3 bindings sat `pending` across
five consecutive timeline versions, re-running the entire free asset
search on every engine resume - including resumes fired by unrelated
human corrections such as setting a narration tone. `attempts` was
incremented on every `TransientError` and read by nothing.
"""

import pytest

from app.core.config import settings
from app.workflow.steps.resolve_assets import search_attempts_exhausted


def test_under_the_cap_keeps_retrying():
    for attempts in range(settings.max_search_attempts_per_shot):
        assert not search_attempts_exhausted(
            attempts=attempts, generation_permitted=False
        )


def test_at_the_cap_gives_up():
    assert search_attempts_exhausted(
        attempts=settings.max_search_attempts_per_shot, generation_permitted=False
    )


def test_past_the_cap_stays_given_up():
    # A binding that somehow overshot (e.g. attempts carried forward from
    # before this cap existed) must still terminate, not wrap around.
    assert search_attempts_exhausted(
        attempts=settings.max_search_attempts_per_shot + 7, generation_permitted=False
    )


@pytest.mark.parametrize("attempts", [0, 3, 99])
def test_the_generation_pass_is_never_capped_here(attempts):
    """It parks bindings on `pending` for in-flight fal.ai video jobs by
    setting that state directly, not through the transient handler, so
    its `attempts` never climbs - and its lifecycle is not this rule's
    to decide."""
    assert not search_attempts_exhausted(
        attempts=attempts, generation_permitted=True
    )


def test_the_cap_is_configurable_not_hardcoded(monkeypatch):
    monkeypatch.setattr(settings, "max_search_attempts_per_shot", 10)
    assert not search_attempts_exhausted(attempts=9, generation_permitted=False)
    assert search_attempts_exhausted(attempts=10, generation_permitted=False)
