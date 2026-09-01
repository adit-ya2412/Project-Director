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


def test_default_pipeline_runs_narration_before_approval_and_generation_after():
    """Task 1 (2026-08-16, the one-gate redesign): `NarrationStep` moved
    from AFTER `AwaitApprovalStep` to BEFORE it - a deliberate, narrow I6
    exception (narration costs ~10 cents and now runs pre-approval) so
    the one gate shows REAL, narration-measured shot durations rather
    than the planner's pre-audio guess. See `app/workflow/engine.py`'s
    own module docstring for the full reasoning."""
    names = [step.name for step in DEFAULT_PIPELINE]
    assert names == [
        "generate_timeline",
        "resolve_assets_search",
        # M8 step 4 (D6/21.2): music selection runs alongside the free
        # search pass, before the approval gate - a human should hear
        # what the video will sound like before approving it.
        "select_music",
        "select_sfx",
        "romanize_captions",
        "narration",
        "await_approval",
        "resolve_assets_generate",
        # long_form_direction.md A8 (2026-09-01): diegetic SFX generation
        # is paid, so it runs here - post-approval, immediately following
        # the generation half of the asset ladder - never beside
        # `select_sfx` above (free search, pre-approval).
        "generate_diegetic_sfx",
        # M6.5, A15/A26/A28: the review gate sits between the generation
        # pass and the renderer - a shot that ended `failed` must never
        # reach `RenderStep`, not even as a placeholder. Under the
        # one-gate design (Task 2's approval-time guard) this is largely
        # a backstop now - see that guard's own docstring.
        "await_review",
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


async def test_search_pass_resolves_before_narration_and_carries_forward_across_it(
    project_id, monkeypatch
):
    """Task 1 (2026-08-16): with `NarrationStep` moved before
    `AwaitApprovalStep`, both the free search pass AND narration now run
    within the SAME engine run, before a human ever approves anything -
    proving A11/A20 carry-forward survives that version bump is no less
    important than it was under the old order, just earlier."""
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_x")
    steps = [
        GenerateTimelineStep(),
        _search_step(),
        NarrationStep(),
        AwaitApprovalStep(),
        _generation_step(),
    ]

    # Run 1: generate_timeline fills v2 from the fixture, the free search
    # pass resolves every shot at v2 (DRY_RUN's FakeAssetProvider always
    # finds something, and every shot in the fixture plans a search-type
    # strategy), then - Task 1 - NarrationStep ALSO runs, before approval:
    # it reconciles durations into v3 and, per A11/A20, must carry every
    # binding search already found forward across that bump. The engine
    # then stops cleanly at the still-unapproved gate - narration ran (the
    # deliberate, narrow I6 exception - ~10 cents pre-approval), but
    # nobody has approved anything yet, and generation (the expensive
    # part) has not.
    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    async with async_session_factory() as session:
        narrated = await TimelineService(session).get_active(project_id)
        search_only_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), narrated.version - 1
        )
        narrated_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), narrated.version
        )

    assert narrated.status.value == "draft"  # narration does not self-approve pre-approval
    assert narrated.produced_by.value == "narration"

    # A5's whole point: the search-only version already had every shot
    # resolved - not empty ones - before narration (or approval) ever ran.
    assert len(search_only_bindings) == len(narrated.all_shots()) > 0
    assert all(b.state == "resolved" for b in search_only_bindings)
    search_only_asset_by_shot = {b.shot_id: b.asset_id for b in search_only_bindings}
    assert all(asset_id is not None for asset_id in search_only_asset_by_shot.values())

    # The NARRATION version's own bindings reference the SAME assets -
    # proof of carry-forward (A11/A20), not a coincidental re-search
    # landing on the same fake result.
    assert len(narrated_bindings) == len(narrated.all_shots()) > 0
    assert all(b.state == "resolved" for b in narrated_bindings)
    for b in narrated_bindings:
        assert b.asset_id == search_only_asset_by_shot[b.shot_id]

    # A human approves the narrated plan, exactly like the API does.
    async with async_session_factory() as session:
        await TimelineService(session).approve(project_id, narrated.version)

    # Run 2: resumes past every already-satisfied step (search, narration,
    # approval), runs the paid generation pass - which must find every
    # shot already resolved and do nothing. No further version bump: with
    # narration already run BEFORE approval (Task 1), approving does not
    # trigger a second narration pass the way it used to.
    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    async with async_session_factory() as session:
        final_timeline = await TimelineService(session).get_active(project_id)
        final_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), final_timeline.version
        )
        stale_bindings = await ShotBindingRepository(session).list_for_version(
            uuid_module.UUID(project_id), narrated.version - 1
        )

    assert final_timeline.version == narrated.version  # no further version bump
    assert len(final_bindings) == len(final_timeline.all_shots()) > 0
    assert all(b.state == "resolved" for b in final_bindings)
    for b in final_bindings:
        assert b.asset_id == search_only_asset_by_shot[b.shot_id]
    # The search-only version's own bindings are untouched, not deleted -
    # carry-forward copies, it never deletes (same immutability spirit as
    # the Timeline versions themselves).
    assert len(stale_bindings) == len(search_only_bindings)


async def test_narration_reconciliation_alone_does_not_change_acquisition_relevant_fields(
    project_id, monkeypatch
):
    """A20's rule is that a binding carries forward when `prompt` and
    `asset_plan` are unchanged - this proves narration's own transform
    (`_apply_durations`, which touches only `duration_s`/`metadata`)
    actually satisfies that rule for every shot the fixture has, which is
    what makes the carry-forward in the test above happen at all rather
    than by coincidence. Task 1: narration no longer needs approval to
    run first, so this is provable in a single engine run."""
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_x")
    steps = [GenerateTimelineStep(), _search_step(), NarrationStep()]

    async with async_session_factory() as session:
        await WorkflowEngine(_make_ctx(project_id, session), steps=steps).run()

    async with async_session_factory() as session:
        service = TimelineService(session)
        final_timeline = await service.get_active(project_id)
        pre_narration = await service.get_version(project_id, final_timeline.version - 1)

    assert final_timeline.produced_by.value == "narration"
    assert pre_narration.produced_by.value != "narration"

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
        lambda **_kwargs: {
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
