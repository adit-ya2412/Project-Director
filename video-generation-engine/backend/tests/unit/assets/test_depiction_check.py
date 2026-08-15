"""Unit tests for searched-asset vision verification (M6.5, A16 -> A30) -
mirrors tests/unit/assets/test_constraint_check.py's pattern: assert
OUTCOME (was a call made, what verdict came back, does the recorded call
reflect it), one DB-backed test for the `llm_call` audit row.
"""

import uuid as uuid_module

import pytest_asyncio

from app.assets.depiction_check import check_candidate_depicts_subject
from app.db.session import async_session_factory
from app.providers.base import DepictionCheckRequest, DepictionVerdict, StructuredCompletion
from app.providers.fakes.vision import FakeVisionConstraintProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("depiction-check-test")
        return project.id


class _RaisingProvider:
    """Would raise if ever called - proves a code path made zero calls
    rather than merely asserting a count against a fake that happens not
    to mind."""

    name = "raising"

    async def check_depiction(self, request: DepictionCheckRequest) -> StructuredCompletion:
        raise AssertionError("check_depiction must not be called")


async def test_no_provider_makes_zero_calls_and_defaults_to_depicts_true():
    """DRY_RUN's idiom: `provider=None`. No session/repo needed at all -
    this must be safe to call with nothing wired up, the same guarantee
    the walking-skeleton e2e test depends on. Defaulting to `depicts=True`
    (rather than False) matters: with no provider to ask, this must never
    itself become a reason a shot falls through the ladder."""
    verdict = await check_candidate_depicts_subject(
        provider=None,
        llm_call_repo=None,  # type: ignore[arg-type]  # never touched when provider is None
        project_id=uuid_module.uuid4(),
        image=b"fake-bytes",
        image_content_type="image/png",
        shot_prompt="a coal mine",
        search_subject="Leuna Werke",
    )
    assert verdict.depicts is True


async def test_blank_search_subject_makes_zero_calls():
    verdict = await check_candidate_depicts_subject(
        provider=_RaisingProvider(),
        llm_call_repo=None,  # type: ignore[arg-type]
        project_id=uuid_module.uuid4(),
        image=b"fake-bytes",
        image_content_type="image/png",
        shot_prompt="a coal mine",
        search_subject="   ",
    )
    assert verdict.depicts is True


async def test_a_real_call_is_recorded_in_llm_call_repo(project_id):
    provider = FakeVisionConstraintProvider(
        depiction_verdicts=[
            DepictionVerdict(depicts=False, reason="this is a different chemical plant entirely")
        ]
    )
    async with async_session_factory() as session:
        llm_call_repo = LlmCallRepository(session)
        verdict = await check_candidate_depicts_subject(
            provider=provider,
            llm_call_repo=llm_call_repo,
            project_id=uuid_module.UUID(project_id),
            image=b"fake-bytes",
            image_content_type="image/png",
            shot_prompt="the Leuna-Werke synthetic fuel plant",
            search_subject="Leuna Werke",
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

    assert verdict.depicts is False
    assert "different chemical plant" in verdict.reason
    assert len(rows) == 1
    assert rows[0].agent == "depiction_check"
    assert len(provider.depiction_calls) == 1
    assert provider.depiction_calls[0].search_subject == "Leuna Werke"
    assert provider.depiction_calls[0].shot_prompt == "the Leuna-Werke synthetic fuel plant"
