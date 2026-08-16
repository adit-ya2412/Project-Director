"""R3 (2026-08-16): `render_precondition_gap` (`app/workflow/render_only.py`)
against the REAL database - every step's own `is_satisfied` queries
`TimelineService`/`ShotBindingRepository` for real, so this cannot be
proven as a pure unit test (see `tests/unit/workflow/test_render_only.py`
for the DB-free half: what `RENDER_ONLY_STEPS` itself contains).

One project is carried through every real stage the pipeline passes
through before a render becomes possible, and the gap is checked at each
one - proving the function names the ACTUAL first blocking step at every
point, not just "generate_timeline" (the trivial, empty-project case) or
"None" (the fully-ready case) alone.
"""

import uuid as uuid_module

import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.shot_binding import ShotBindingModel
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    Transition,
    TransitionType,
)
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.render_only import render_precondition_gap
from app.workflow.steps.narration import NarrationStep


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


_SCENE_TEXT = "Bro, Germany ke paas oil tha hi nahi."


def _one_shot_scene() -> Scene:
    # `narration_text`/`narration_span` set (mirroring
    # tests/e2e/test_narration_retry_api.py's own fixture) so the SAME
    # scene can be carried all the way through a real `NarrationStep.run()`
    # call in the "fully ready" test below, not just through the earlier,
    # narration-free stages.
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="archival photograph",
        narration_span=(0, len(_SCENE_TEXT)),
        asset_plan=AssetPlan(strategy=AssetStrategy.HISTORICAL_SEARCH),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    return Scene(
        id="sc_01",
        order=0,
        title="Scene",
        narration_text=_SCENE_TEXT,
        duration_s=3.0,
        shots=[shot],
    )


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).create("render-only precondition test")
        return project.id


async def test_gap_is_generate_timeline_before_any_planning(project_id):
    """An empty v1 (`create_initial`, before any planner has run) does
    not count as planned - the identical distinction
    `GenerateTimelineStep.is_satisfied` itself draws (see that module's
    own comment: "a crash between the two calls must not look like
    already done on resume")."""
    async with async_session_factory() as session:
        await TimelineService(session).create_initial(project_id, script="unused")
        await session.commit()

    async with async_session_factory() as session:
        gap = await render_precondition_gap(_make_ctx(project_id, session))
    assert gap == "generate_timeline"


async def test_gap_is_resolve_assets_search_once_planned_but_unresolved(project_id):
    """Fully planned (non-empty scenes/shots/asset_plan), but the free
    search pass has not resolved anything yet - no `shot_binding` rows
    exist at all."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        await session.commit()

    async with async_session_factory() as session:
        gap = await render_precondition_gap(_make_ctx(project_id, session))
    assert gap == "resolve_assets_search"


async def test_gap_is_narration_once_search_and_music_are_done(project_id):
    """The free search pass resolved the one shot, and there is no
    `music_plan` at all (`SelectMusicStep.is_satisfied` treats "nothing
    to select against" as satisfied, not blocking) - but `NarrationStep`
    never ran. Task 1 (2026-08-16): narration now runs BEFORE the
    approval gate, so this is the first real gap reported here, not
    `await_approval` - the plan being unapproved doesn't even come up yet
    until narration itself is satisfied."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=appended.version,
                shot_id="sh_01",
                state="resolved",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        gap = await render_precondition_gap(_make_ctx(project_id, session))
    assert gap == "narration"


async def test_gap_is_await_approval_once_narrated_but_never_approved(project_id, monkeypatch):
    """Task 1 (2026-08-16): with `NarrationStep` moved before
    `AwaitApprovalStep`, this is the first scenario where `await_approval`
    is genuinely the reported gap - search resolved, a REAL `NarrationStep
    .run()` pass already reconciled durations (so `narration` itself is
    satisfied), but nobody has approved the plan yet. `NarrationStep`
    does not self-approve on this, its first pass for the project (see
    that step's own docstring) - the version it produced is exactly what
    a human is meant to review at the gate."""
    monkeypatch.setattr(settings, "dry_run", True)
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=appended.version,
                shot_id="sh_01",
                state="resolved",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error
        await session.commit()

    async with async_session_factory() as session:
        narrated = await TimelineService(session).get_active(project_id)
    assert narrated.produced_by == ProducedBy.NARRATION
    assert narrated.status.value == "draft"  # not self-approved - nobody has clicked approve

    async with async_session_factory() as session:
        gap = await render_precondition_gap(_make_ctx(project_id, session))
    assert gap == "await_approval"


async def test_gap_is_narration_once_approved_but_never_narrated(project_id):
    """Approved, resolved, no music plan to worry about - but
    `NarrationStep` never ran (`produced_by` is still `ASSET_PLANNER`).
    Task 1: narration is checked before approval in pipeline order, so
    this gaps at "narration" regardless of whether the plan happens to
    already be approved (as here) or not (see the two tests above) -
    approving early just isn't the normal path any more, since Task 2's
    guard would refuse it directly through the API in this state anyway."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=appended.version,
                shot_id="sh_01",
                state="resolved",
            )
        )
        await session.commit()
        await service.approve(project_id, appended.version)
        await session.commit()

    async with async_session_factory() as session:
        gap = await render_precondition_gap(_make_ctx(project_id, session))
    assert gap == "narration"


async def test_gap_is_none_once_every_real_step_is_satisfied(project_id, monkeypatch):
    """Everything ahead of render is done for real, including a real
    `NarrationStep.run()` pass (DRY_RUN's `FakeNarrationProvider`) - the
    exact state a render-only trigger is supposed to accept."""
    monkeypatch.setattr(settings, "dry_run", True)

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=appended.version,
                shot_id="sh_01",
                state="resolved",
            )
        )
        await session.commit()
        await service.approve(project_id, appended.version)
        await session.commit()

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error
        await session.commit()

    async with async_session_factory() as session:
        gap = await render_precondition_gap(_make_ctx(project_id, session))
    assert gap is None


async def test_gap_is_await_review_once_a_shot_has_failed_generation(project_id, monkeypatch):
    """Narration ran for real - but the shot's binding at the NEW
    (narration-reconciled) version has since failed the paid generation
    pass. Render must never proceed while a shot is `failed` (A26) - the
    render-only trigger is not an exception to that rule."""
    monkeypatch.setattr(settings, "dry_run", True)

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=appended.version,
                shot_id="sh_01",
                state="resolved",
            )
        )
        await session.commit()
        await service.approve(project_id, appended.version)
        await session.commit()

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error
        await session.commit()

    async with async_session_factory() as session:
        narrated = await TimelineService(session).get_active(project_id)
        binding = await ShotBindingRepository(session).get(
            uuid_module.UUID(project_id), narrated.version, "sh_01"
        )
        assert binding is not None
        binding.state = "failed"
        binding.last_error = "simulated: exhausted every generation attempt"
        await session.commit()

    async with async_session_factory() as session:
        gap = await render_precondition_gap(_make_ctx(project_id, session))
    assert gap == "await_review"
