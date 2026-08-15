"""Unit tests for Director-constraint enforcement on generated media
(M6.5, A12/A13/A18) - pure/fast where possible, one DB-backed test for
the `llm_call` audit row (matches the existing pattern for
`run_structured_with_repair`, which also needs a real session).

Asserts OUTCOME (was a call made, what verdict came back, does the
recorded call reflect it) rather than mechanism - the M6.5 "why this
phase exists" lesson applies here too.
"""

import uuid as uuid_module

import pytest_asyncio

from app.assets.constraint_check import (
    build_revised_prompt,
    check_generated_image_constraints,
    seed_for_attempt,
    varied_seed,
)
from app.db.session import async_session_factory
from app.providers.base import ConstraintCheckRequest, ConstraintVerdict, StructuredCompletion
from app.providers.fakes.vision import FakeVisionConstraintProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("constraint-check-test")
        return project.id


class _RaisingProvider:
    """Would raise if ever called - proves a code path made zero calls
    rather than merely asserting a count against a fake that happens not
    to mind."""

    name = "raising"

    async def check_constraints(self, request: ConstraintCheckRequest) -> StructuredCompletion:
        raise AssertionError("check_constraints must not be called")


async def test_empty_constraints_makes_zero_calls(project_id):
    async with async_session_factory() as session:
        llm_call_repo = LlmCallRepository(session)
        verdict = await check_generated_image_constraints(
            provider=_RaisingProvider(),
            llm_call_repo=llm_call_repo,
            project_id=uuid_module.UUID(project_id),
            image=b"fake-bytes",
            image_content_type="image/png",
            shot_prompt="a coal mine",
            constraints=[],
        )
    assert verdict.violated is False


async def test_no_provider_makes_zero_calls_and_is_not_violated():
    """DRY_RUN's idiom: `provider=None`. No session/repo needed at all -
    this must be safe to call with nothing wired up, the same guarantee
    the walking-skeleton e2e test depends on."""
    verdict = await check_generated_image_constraints(
        provider=None,
        llm_call_repo=None,  # type: ignore[arg-type]  # never touched when provider is None
        project_id=uuid_module.uuid4(),
        image=b"fake-bytes",
        image_content_type="image/png",
        shot_prompt="a coal mine",
        constraints=["no Nazi symbols"],
    )
    assert verdict.violated is False
    assert verdict.violated_constraint == ""


async def test_a_real_call_is_recorded_in_llm_call_repo(project_id):
    provider = FakeVisionConstraintProvider(
        verdicts=[
            ConstraintVerdict(
                violated=True, violated_constraint="no Nazi symbols", reason="a swastika is visible"
            )
        ]
    )
    async with async_session_factory() as session:
        llm_call_repo = LlmCallRepository(session)
        verdict = await check_generated_image_constraints(
            provider=provider,
            llm_call_repo=llm_call_repo,
            project_id=uuid_module.UUID(project_id),
            image=b"fake-bytes",
            image_content_type="image/png",
            shot_prompt="a wartime factory",
            constraints=["no Nazi symbols"],
        )

        from sqlalchemy import select

        from app.models.llm_call import LlmCallModel

        rows = (
            (
                await session.execute(
                    select(LlmCallModel).where(
                        LlmCallModel.project_id == uuid_module.UUID(project_id)
                    )
                )
            )
            .scalars()
            .all()
        )

    assert verdict.violated is True
    assert verdict.violated_constraint == "no Nazi symbols"
    assert len(rows) == 1
    assert rows[0].agent == "constraint_check"
    assert len(provider.calls) == 1
    assert provider.calls[0].constraints == ["no Nazi symbols"]
    assert provider.calls[0].shot_prompt == "a wartime factory"


def test_build_revised_prompt_is_deterministic_and_readable():
    """A18: a deterministic rebuild, not an LLM rewrite - same inputs,
    same output, every time, and the violated constraint's exact text
    survives verbatim into the revised prompt."""
    revised = build_revised_prompt("a wartime factory", ["no Nazi symbols"])
    assert revised == build_revised_prompt("a wartime factory", ["no Nazi symbols"])
    assert "a wartime factory" in revised
    assert "no Nazi symbols" in revised


def test_build_revised_prompt_with_no_violations_returns_the_base_prompt_unchanged():
    assert build_revised_prompt("a wartime factory", []) == "a wartime factory"


def test_build_revised_prompt_does_not_duplicate_a_repeated_constraint():
    """The same constraint violated on two different attempts must not
    make the directive appear twice - repeating an identical instruction
    to an image model is not a stronger instruction, just a longer
    prompt."""
    once = build_revised_prompt("a wartime factory", ["no Nazi symbols"])
    twice_in_the_list = build_revised_prompt(
        "a wartime factory", ["no Nazi symbols", "no Nazi symbols"]
    )
    # The caller is expected to pass a de-duplicated list (resolve_assets
    # only ever appends once per distinct constraint) - this just proves
    # the function itself doesn't amplify a duplicate if one slips through.
    assert once.count("no Nazi symbols") == 1
    assert twice_in_the_list.count("no Nazi symbols") == 1


def test_build_revised_prompt_includes_every_distinct_violated_constraint():
    revised = build_revised_prompt(
        "a wartime factory", ["no Nazi symbols", "no AI faces of real historical figures"]
    )
    assert "no Nazi symbols" in revised
    assert "no AI faces of real historical figures" in revised


def test_varied_seed_is_deterministic_not_random():
    """A13: never `random` - same project seed and attempt index always
    produce the same varied seed, so a re-run after a crash lands on the
    identical seed rather than a fresh roll."""
    a = varied_seed(12345, attempt=2)
    b = varied_seed(12345, attempt=2)
    assert a == b


def test_varied_seed_differs_from_the_project_seed_and_by_attempt():
    project_seed = 12345
    seed_at_2 = varied_seed(project_seed, attempt=2)
    assert seed_at_2 != project_seed
    # Different attempt indices must not coincidentally collide either -
    # otherwise a hypothetical attempt-3 would silently reuse attempt-2's
    # seed.
    assert seed_at_2 != varied_seed(project_seed, attempt=3)


def test_seed_for_attempt_keeps_the_project_seed_until_the_last_attempt():
    """A13: attempt 0 always gets the project's fixed seed; the varied-
    seed lever only fires on the LAST attempt the configured cap allows -
    at the default cap of 3, that's attempt 2 (attempts 0 and 1 both keep
    the project seed)."""
    project_seed = 12345
    assert seed_for_attempt(project_seed, attempt=0, max_attempts=3) == project_seed
    assert seed_for_attempt(project_seed, attempt=1, max_attempts=3) == project_seed
    assert seed_for_attempt(project_seed, attempt=2, max_attempts=3) != project_seed


def test_seed_for_attempt_derives_the_switchover_from_max_attempts():
    """The regression this specifically guards: a hardcoded switchover
    (e.g. always "attempt < 2") would silently stop the seed from ever
    varying if the cap were configured below 3 - at `max_attempts=2`, the
    loop only ever reaches attempts 0 and 1, and a fixed threshold of 2
    would mean both stay on the project seed forever, quietly disabling
    half of A13. Deriving the switchover from `max_attempts` itself keeps
    the lever alive at any configured cap."""
    project_seed = 12345
    assert seed_for_attempt(project_seed, attempt=0, max_attempts=2) == project_seed
    assert seed_for_attempt(project_seed, attempt=1, max_attempts=2) != project_seed


def test_seed_for_attempt_with_a_cap_of_one_never_varies():
    """No retries at all means no room for the second lever either -
    attempt 0 is the only attempt, and it must still be the project seed."""
    project_seed = 12345
    assert seed_for_attempt(project_seed, attempt=0, max_attempts=1) == project_seed
