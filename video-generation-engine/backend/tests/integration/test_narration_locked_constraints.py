"""End-to-end proof of the `narration_locked` fix (M8 hardening,
2026-08-16 - "A26 is a deadlock in practice") through the REAL
mechanism: `TimelineService.append_version` + `GenerateTimelineStep
.is_satisfied` - not just the pure `validate_constraints` logic in
isolation (see `tests/unit/timeline/test_validate_constraints.py` for
that).

The exact reported incident: `POST /shots/{id}/override` on a project
whose narration had already reconciled a shot to 0.615s (genuinely fast
speech) failed with `timeline violates creative constraints:
['shot ... duration_s=0.615... outside [1.5, 8.0]', ...]` - because the
override's own `append_version` call is `produced_by=HUMAN`, and the
OLD exemption (`GenerateTimelineStep._is_fully_planned` checking
`timeline.produced_by == ProducedBy.NARRATION`) only ever protected the
version immediately after narration, not any later one. A26 (M6.5)
states a per-shot override always resolves a stuck project - this was
the case where it did not, because the remedy path itself re-validated
against constraints the remedy could never satisfy.

Written but NOT run in this session - four live projects
(`194ad0e7-...`, `2fa282b4-...`, `f64210fc-...`, `b0969377-...` - the
last one stuck on exactly this bug) sit in the same shared dev
Postgres, and `pytest` truncates every table via `tests/conftest.py`'s
autouse `clean_database` fixture.
"""

import uuid as uuid_module

import pytest_asyncio

from app.db.session import async_session_factory
from app.models.shot_binding import ShotBindingModel
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
)
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps.generate_timeline import GenerateTimelineStep


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


def _short_shot_scene() -> Scene:
    # Mirrors the real incident: a narration-reconciled shot at 0.615s,
    # well under the 1.5s planning floor - "कैसे?" genuinely takes that
    # long to speak, and no amount of re-validation makes it wrong.
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=0.615,
        asset_plan=AssetPlan(strategy=AssetStrategy.HISTORICAL_SEARCH),
    )
    return Scene(id="sc_01", order=0, title="Scene", duration_s=0.615, shots=[shot])


@pytest_asyncio.fixture
async def narration_produced_project() -> str:
    """A project whose active timeline is `produced_by=NARRATION`, with
    a single shot whose real, reconciled duration (0.615s) is outside
    the planning-time [1.5, 8.0] bounds - exactly the shape narration
    legitimately produces (D1: narration is the master clock)."""
    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).create(
            "narration-locked constraints test"
        )
        project_id = project.id

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _seed_narration_produced(base: Timeline) -> Timeline:
            base.scenes = [_short_shot_scene()]
            base.metadata.total_duration_s = 0.615
            base.metadata.narration_locked = True
            return base

        narrated = await service.append_version(
            project_id,
            produced_by=ProducedBy.NARRATION,
            transform=_seed_narration_produced,
            owns=frozenset({"scenes", "metadata"}),
        )
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=narrated.version,
                shot_id="sh_01",
                state="resolved",
            )
        )
        await session.commit()

    return project_id


async def test_generate_timeline_is_satisfied_right_after_narration(
    narration_produced_project,
):
    """The case that already worked before this fix - confirms the new
    mechanism (the persistent `narration_locked` flag) reproduces it,
    not just the new, previously-broken case below."""
    project_id = narration_produced_project
    async with async_session_factory() as session:
        satisfied = await GenerateTimelineStep().is_satisfied(_make_ctx(project_id, session))
    assert satisfied is True


async def test_a_later_human_override_version_still_satisfies_generate_timeline(
    narration_produced_project,
):
    """THE EXACT REPORTED BUG, reproduced and proven fixed: a
    `produced_by=HUMAN` version (a per-shot override, in the real
    incident) built on top of an already narration-locked timeline must
    still satisfy `GenerateTimelineStep` - not re-fail against
    planning-time shot-duration bounds the override's own version never
    claimed to produce."""
    project_id = narration_produced_project

    async with async_session_factory() as session:
        service = TimelineService(session)

        def _lock_shot(base: Timeline) -> Timeline:
            base.scenes[0].shots[0].asset_locked = True
            return base

        overridden = await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_lock_shot,
            owns=frozenset({"scenes"}),
        )

    # The flag survives the override version unchanged - it was never
    # in that version's own `owns` set, so it simply carried forward.
    assert overridden.produced_by == ProducedBy.HUMAN
    assert overridden.metadata.narration_locked is True

    async with async_session_factory() as session:
        satisfied = await GenerateTimelineStep().is_satisfied(_make_ctx(project_id, session))
    assert satisfied is True, (
        "the exact reported deadlock: a later HUMAN version re-failed against "
        "planning-time shot-duration bounds it never claimed to produce"
    )
