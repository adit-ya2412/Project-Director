"""`AwaitReviewStep` (M6.5, A15/A26/A28) - the review gate's own condition
logic, proven directly against real `ShotBinding` rows: satisfied exactly
when no shot at the active version is `failed`, and - critically - no
acknowledgement state anywhere (A26: there is no "proceed anyway"). Once
a failed binding is fixed (the override endpoint's own effect, exercised
end-to-end in tests/integration/test_upload_and_override_api.py), the
SAME step, asked again, is satisfied - proving the remedy really is
"resolve the shot", not "click a button that overrides the check".
"""

import uuid

import pytest_asyncio

from app.db.session import async_session_factory
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.timeline import ProducedBy, Scene, Shot, ShotIntent
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps.await_review import AwaitReviewStep


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("await-review-test")
        return project.id


def _shot(shot_id: str) -> Shot:
    return Shot(id=shot_id, order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)


async def _seed_timeline(project_id: str, shot_ids: list[str]) -> int:
    shots = [_shot(sid) for sid in shot_ids]
    scene = Scene(
        id="sc_01", order=0, title="Scene", duration_s=sum(s.duration_s for s in shots), shots=shots
    )
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="a script")

        def _fill(base):
            base.scenes = [scene]
            return base

        result = await service.append_version(
            project_id, produced_by=ProducedBy.DIRECTOR, transform=_fill, owns=frozenset({"scenes"})
        )
        return result.version


async def test_satisfied_with_no_bindings_at_all(project_id):
    version = await _seed_timeline(project_id, ["sh_01"])
    async with async_session_factory() as session:
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=PostgresProjectRepository(session),
            timeline_service=TimelineService(session),
        )
        satisfied = await AwaitReviewStep().is_satisfied(ctx)
    assert satisfied is True
    assert version >= 2


async def test_satisfied_when_every_binding_resolved_or_generated(project_id):
    version = await _seed_timeline(project_id, ["sh_01", "sh_02"])
    async with async_session_factory() as session:
        binding_repo = ShotBindingRepository(session)
        b1 = await binding_repo.get_or_create_pending(uuid.UUID(project_id), version, "sh_01")
        b1.state = "resolved"
        b2 = await binding_repo.get_or_create_pending(uuid.UUID(project_id), version, "sh_02")
        b2.state = "generated"
        await session.commit()

        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=PostgresProjectRepository(session),
            timeline_service=TimelineService(session),
        )
        satisfied = await AwaitReviewStep().is_satisfied(ctx)
    assert satisfied is True


async def test_not_satisfied_and_awaiting_review_when_a_shot_failed(project_id):
    version = await _seed_timeline(project_id, ["sh_01", "sh_02"])
    async with async_session_factory() as session:
        binding_repo = ShotBindingRepository(session)
        b1 = await binding_repo.get_or_create_pending(uuid.UUID(project_id), version, "sh_01")
        b1.state = "resolved"
        b2 = await binding_repo.get_or_create_pending(uuid.UUID(project_id), version, "sh_02")
        b2.state = "failed"
        b2.last_error = "still violates a Director constraint after every attempt"
        await session.commit()

        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=PostgresProjectRepository(session),
            timeline_service=TimelineService(session),
        )
        step = AwaitReviewStep()
        assert await step.is_satisfied(ctx) is False
        result = await step.run(ctx)
    assert result.outcome == "awaiting_review"
    assert result.error is None


async def test_no_deadlock_fixing_the_binding_directly_clears_the_gate(project_id):
    """A26: there is no acknowledgement flag to flip - the ONLY way past
    this gate is for the failed shot to stop being failed. This proves
    the gate reads live state, not a cached decision: flipping the
    binding is enough, with nothing else recorded anywhere."""
    version = await _seed_timeline(project_id, ["sh_01"])
    async with async_session_factory() as session:
        binding_repo = ShotBindingRepository(session)
        binding = await binding_repo.get_or_create_pending(uuid.UUID(project_id), version, "sh_01")
        binding.state = "failed"
        await session.commit()

        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=PostgresProjectRepository(session),
            timeline_service=TimelineService(session),
        )
        step = AwaitReviewStep()
        assert await step.is_satisfied(ctx) is False

        # Stands in for what the override endpoint does to the binding
        # (never a separate "acknowledge" bit) - see
        # test_upload_and_override_api.py for the real endpoint doing
        # exactly this over HTTP.
        binding.state = "resolved"
        binding.last_error = None
        await session.commit()

        assert await step.is_satisfied(ctx) is True
        result = await step.run(ctx)
    assert result.outcome == "ok"
