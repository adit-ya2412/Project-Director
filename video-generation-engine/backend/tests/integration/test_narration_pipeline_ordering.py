"""Proves the M6.5 pipeline reorder (A5-A7, A11, A20-A22):

GenerateTimeline -> ResolveAssets(search, free) -> AwaitApproval ->
Narration -> ResolveAssets(generate, paid) -> Render -> Complete

- The free search pass runs and resolves shots BEFORE approval (A5) - the
  human reaches the gate having already seen what was found.
- A human still reaches the approval gate even if every search provider
  is entirely down (A22) - proven here at the full-pipeline level; a
  step-level version lives in test_resolve_assets_real.py.
- Narration's own version bump (A7 - it must run after approval, before
  the paid pass) does not orphan the bindings a human already reviewed -
  they carry forward per-shot (A11/A20), so the paid pass never
  re-acquires (and re-pays for) what search already found. Getting the
  reorder wrong here - either pass in the wrong place, or carry-forward
  missing - would either violate I6 (generation before approval) or
  silently throw away the curation this whole phase exists to protect.

Exercises the real DRY_RUN pipeline (fake planner + fake asset/image
providers, real Postgres) through both `ResolveAssetsStep` instances -
`RenderStep` needs a real FFmpeg binary and is out of scope here (see
tests/e2e, which needs ffmpeg on PATH for the same reason).
"""

import uuid as uuid_module

import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.engine import DEFAULT_PIPELINE, WorkflowEngine
from app.workflow.steps import resolve_assets as resolve_assets_module
from app.workflow.steps.await_approval import AwaitApprovalStep
from app.workflow.steps.generate_timeline import GenerateTimelineStep
from app.workflow.steps.narration import NarrationStep
from app.workflow.steps.resolve_assets import GENERATION_RUNGS, SEARCH_RUNGS, ResolveAssetsStep

_SCRIPT = (
    "Germany possessed abundant coal, fueling its factories and its "
    "ambitions. But it lacked one vital resource: oil, and that "
    "dependency would shape the war to come. That single gap in "
    "resources would drive strategic decisions with consequences the "
    "world still remembers."
)


def _search_step() -> ResolveAssetsStep:
    return ResolveAssetsStep(name="resolve_assets_search", permitted_strategies=SEARCH_RUNGS)


def _generation_step() -> ResolveAssetsStep:
    return ResolveAssetsStep(name="resolve_assets_generate", permitted_strategies=GENERATION_RUNGS)


def test_default_pipeline_runs_search_before_approval_and_generation_after_narration():
    names = [step.name for step in DEFAULT_PIPELINE]
    assert names == [
        "generate_timeline",
        "resolve_assets_search",
        "await_approval",
        "narration",
        "resolve_assets_generate",
        "render",
        "complete",
    ]


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("narration-pipeline-order-test")
        project.script = _SCRIPT
        await repo.update(project)
        return project.id


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


async def test_search_pass_resolves_before_approval_and_carries_forward_across_narration(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_x")
    steps = [
        GenerateTimelineStep(),
        _search_step(),
        AwaitApprovalStep(),
        NarrationStep(),
        _generation_step(),
    ]

    # Run 1: generate_timeline fills v2 from the fixture, the free search
    # pass resolves every shot (DRY_RUN's FakeAssetProvider always finds
    # something, and every shot in the fixture plans a search-type
    # strategy), then the engine stops cleanly at the still-unapproved
    # approval gate - narration must not have run yet (I6).
    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    async with async_session_factory() as session:
        pre_narration = await TimelineService(session).get_active(project_id)
        pre_narration_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), pre_narration.version
        )
    assert pre_narration.status.value == "draft"
    assert pre_narration.produced_by.value != "narration"
    # A5's whole point: the human reaches the gate with shots the free
    # pass ALREADY resolved, not empty ones.
    assert len(pre_narration_bindings) == len(pre_narration.all_shots()) > 0
    assert all(b.state == "resolved" for b in pre_narration_bindings)
    pre_narration_asset_by_shot = {b.shot_id: b.asset_id for b in pre_narration_bindings}
    assert all(asset_id is not None for asset_id in pre_narration_asset_by_shot.values())

    # A human approves the pre-narration plan, exactly like the API does.
    async with async_session_factory() as session:
        await TimelineService(session).approve(project_id, pre_narration.version)

    # Run 2: resumes past generate_timeline/search/await_approval, runs
    # narration (appends + self-approves a new version, carrying bindings
    # forward per A11/A20), then the paid generation pass - which must
    # find every shot already resolved and do nothing.
    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    async with async_session_factory() as session:
        final_timeline = await TimelineService(session).get_active(project_id)
        final_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), final_timeline.version
        )
        stale_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), pre_narration.version
        )

    assert final_timeline.produced_by.value == "narration"
    assert final_timeline.version == pre_narration.version + 1
    # Every shot has a binding at the NEW version too...
    assert len(final_bindings) == len(final_timeline.all_shots()) > 0
    assert all(b.state == "resolved" for b in final_bindings)
    # ...and it references the SAME asset each time (A20: carried
    # forward, never re-resolved) - proving this is carry-forward, not a
    # coincidental re-search landing on the same fake result.
    for b in final_bindings:
        assert b.asset_id == pre_narration_asset_by_shot[b.shot_id]
    # The pre-narration version's own bindings are untouched, not deleted
    # - carry-forward copies, it never deletes (same immutability spirit
    # as the Timeline versions themselves).
    assert len(stale_bindings) == len(pre_narration_bindings)


async def test_narration_reconciliation_alone_does_not_change_acquisition_relevant_fields(
    project_id, monkeypatch
):
    """A20's rule is that a binding carries forward when `prompt` and
    `asset_plan` are unchanged - this proves narration's own transform
    (`_apply_durations`, which touches only `duration_s`/`metadata`)
    actually satisfies that rule for every shot the fixture has, which is
    what makes the carry-forward in the test above happen at all rather
    than by coincidence."""
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_x")
    steps = [GenerateTimelineStep(), _search_step(), AwaitApprovalStep(), NarrationStep()]

    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()
    async with async_session_factory() as session:
        pre_narration = await TimelineService(session).get_active(project_id)
        await TimelineService(session).approve(project_id, pre_narration.version)

    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()
    async with async_session_factory() as session:
        final_timeline = await TimelineService(session).get_active(project_id)

    pre_shots = {s.id: s for s in pre_narration.all_shots()}
    for shot in final_timeline.all_shots():
        pre_shot = pre_shots[shot.id]
        assert shot.prompt == pre_shot.prompt
        assert shot.asset_plan == pre_shot.asset_plan
        # Duration is exactly the kind of field narration IS allowed to
        # change - not asserted equal, since real reconciliation may (and
        # for this fixture's fake alignment, does) differ slightly.


async def test_total_search_outage_still_reaches_the_approval_gate(project_id, monkeypatch):
    """A22, at the full-pipeline level: if every search provider the free
    pass depends on is down, the human must still reach approval and see
    that nothing was found, rather than the whole run failing before it
    gets there."""
    monkeypatch.setattr(settings, "dry_run", False)

    class _RaisingAssetProvider:
        name = "wikimedia"
        rung = "historical_search"

        async def search(self, query):
            raise RuntimeError("simulated total provider outage")

        async def fetch(self, candidate):
            raise RuntimeError("simulated total provider outage")

    monkeypatch.setattr(
        resolve_assets_module,
        "_real_search_providers",
        lambda: {
            strategy: _RaisingAssetProvider() for strategy in resolve_assets_module.SEARCH_RUNGS
        },
    )

    # generate_timeline still needs a real OpenAI call in non-DRY_RUN
    # mode, which this test has no interest in exercising - so it seeds
    # the timeline directly, past that step, exactly at the point the
    # search pass would pick it up.
    async with async_session_factory() as session:
        service = TimelineService(session)
        timeline = await service.create_initial(project_id, script=_SCRIPT)

        from app.schemas.timeline import (
            AssetPlan,
            AssetStrategy,
            ProducedBy,
            Scene,
            Shot,
            ShotIntent,
        )

        shot = Shot(
            id="sh_01",
            order=0,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            prompt="a coal mine",
            asset_plan=AssetPlan(
                strategy=AssetStrategy.HISTORICAL_SEARCH,
                search_queries=["archival photo"],
                fallback_chain=[AssetStrategy.HISTORICAL_SEARCH, AssetStrategy.GENERATE_IMAGE],
                licence_requirements=["cc0"],
            ),
        )
        scene = Scene(id="sc_01", order=0, title="Scene", duration_s=3.0, shots=[shot])

        def _fill(base):
            base.scenes = [scene]
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_fill,
            owns=frozenset({"scenes", "creative_context", "metadata"}),
        )

    steps = [_search_step(), AwaitApprovalStep()]
    async with async_session_factory() as session:
        project = await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    # The run reaches the gate - it is not FAILED, despite every search
    # call for the one shot raising.
    assert project.status.value == "awaiting_approval"

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
        bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), timeline.version
        )
    assert len(bindings) == 1
    assert bindings[0].state == "failed"  # the one shot's own failure, not a blocked gate
