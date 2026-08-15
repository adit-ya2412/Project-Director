"""TimelineService — proves Invariant I3 (immutable Timeline versions) is
enforced in code, not just convention, and (M6.5, A11/A20) that
`ShotBinding` carry-forward across a version bump is impossible to skip,
living inside `_persist` rather than as an opt-in a caller could forget.
Needs real Postgres (docs/12_Testing_Strategy.md: integration tests,
unlike unit tests, are allowed to hit the database)."""

import uuid

import pytest_asyncio

from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.models.asset import AssetModel
from app.models.project import ProjectModel
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    TimelineStatus,
)
from app.timeline.service import TimelineService


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("timeline-service-test")
        return project.id


def _shot(shot_id: str, order: int, duration_s: float = 3.0) -> Shot:
    return Shot(id=shot_id, order=order, intent=ShotIntent.EXPLAIN, duration_s=duration_s)


def _scene(scene_id: str, order: int, shots: list[Shot]) -> Scene:
    return Scene(
        id=scene_id,
        order=order,
        title=f"Scene {order}",
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
    )


async def test_create_initial_is_empty_v1(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        initial = await service.create_initial(project_id, script="a script")
    assert initial.version == 1
    assert initial.parent_version is None
    assert initial.scenes == []
    assert initial.status == TimelineStatus.DRAFT


async def test_create_initial_twice_rejected(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="a script")
        try:
            await service.create_initial(project_id, script="a script")
            raise AssertionError("expected PermanentError")
        except PermanentError:
            pass


async def test_append_version_without_create_initial_rejected(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        try:
            await service.append_version(
                project_id, produced_by=ProducedBy.DIRECTOR, transform=lambda t: t
            )
            raise AssertionError("expected PermanentError")
        except PermanentError:
            pass


async def test_append_version_creates_next_version(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def add_scene(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0)])]
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.DIRECTOR,
            transform=add_scene,
            owns=frozenset({"scenes"}),
        )
    assert appended.version == 2
    assert appended.parent_version == 1
    assert len(appended.scenes) == 1
    assert appended.scenes[0].id == "sc_01"


async def test_mutating_returned_timeline_does_not_affect_stored_version(project_id):
    """The core promise of Invariant I3: what you get back is yours to
    mutate freely, and it can never corrupt what's in the database."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def add_scene(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0)])]
            return base

        result = await service.append_version(
            project_id,
            produced_by=ProducedBy.DIRECTOR,
            transform=add_scene,
            owns=frozenset({"scenes"}),
        )

        # Mutate the object handed back to the caller.
        result.scenes[0].title = "MUTATED-AFTER-RETURN"
        result.scenes.append(_scene("sc_intruder", 99, []))

        stored = await service.get_active(project_id)

    assert stored.scenes[0].title == "Scene 0"
    assert len(stored.scenes) == 1


async def test_append_version_rejects_change_without_declared_ownership(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def add_scene(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0)])]
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.DIRECTOR,
            transform=add_scene,
            owns=frozenset({"scenes"}),
        )

        def rewrite_title_without_permission(base):
            base.scenes[0].title = "changed without owning scenes"
            return base

        try:
            await service.append_version(
                project_id,
                produced_by=ProducedBy.SCENE_PLANNER,
                transform=rewrite_title_without_permission,
                owns=frozenset(),  # does NOT declare ownership of scenes
            )
            raise AssertionError("expected PermanentError for non-additive change")
        except PermanentError:
            pass

        # Rejected write must not have created a new version.
        latest = await service.get_active(project_id)
    assert latest.version == 2


async def test_append_version_allows_change_with_declared_ownership(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def add_scene(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0)])]
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.DIRECTOR,
            transform=add_scene,
            owns=frozenset({"scenes"}),
        )

        def rewrite_title_with_permission(base):
            base.scenes[0].title = "Retitled by Scene Planner"
            return base

        updated = await service.append_version(
            project_id,
            produced_by=ProducedBy.SCENE_PLANNER,
            transform=rewrite_title_with_permission,
            owns=frozenset({"scenes"}),
        )
    assert updated.version == 3
    assert updated.scenes[0].title == "Retitled by Scene Planner"


async def test_diff_reports_scene_and_shot_level_changes(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def v2(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0, duration_s=3.0)])]
            return base

        await service.append_version(
            project_id, produced_by=ProducedBy.DIRECTOR, transform=v2, owns=frozenset({"scenes"})
        )

        def v3(base):
            base.scenes[0].shots[0].duration_s = 5.0
            base.scenes[0].shots.append(_shot("sh_01_02", 1))
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.SHOT_PLANNER,
            transform=v3,
            owns=frozenset({"scenes"}),
        )

        diff = await service.diff(project_id, 2, 3)

    assert diff.from_version == 2
    assert diff.to_version == 3
    assert len(diff.scenes_changed) == 1
    scene_diff = diff.scenes_changed[0]
    assert scene_diff.scene_id == "sc_01"
    assert scene_diff.shots_added == ["sh_01_02"]
    assert scene_diff.shots_removed == []
    changed_shot_ids = {c.shot_id for c in scene_diff.shots_changed}
    assert changed_shot_ids == {"sh_01_01"}


async def test_approve_sets_status_and_pins_active_version(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def add_scene(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0)])]
            return base

        v2 = await service.append_version(
            project_id,
            produced_by=ProducedBy.DIRECTOR,
            transform=add_scene,
            owns=frozenset({"scenes"}),
        )

        approved = await service.approve(project_id, v2.version)
        assert approved.status == TimelineStatus.APPROVED

        refetched = await service.get_version(project_id, v2.version)
        assert refetched.status == TimelineStatus.APPROVED

    async with async_session_factory() as session:
        model = await session.get(ProjectModel, uuid.UUID(project_id))
        assert model.active_timeline_version == v2.version


async def test_rollback_appends_a_copy_and_preserves_history(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def v2(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0)])]
            return base

        v2_result = await service.append_version(
            project_id, produced_by=ProducedBy.DIRECTOR, transform=v2, owns=frozenset({"scenes"})
        )

        def v3(base):
            base.scenes[0].shots.append(_shot("sh_01_02", 1))
            return base

        v3_result = await service.append_version(
            project_id,
            produced_by=ProducedBy.SHOT_PLANNER,
            transform=v3,
            owns=frozenset({"scenes"}),
        )
        assert len(v3_result.scenes[0].shots) == 2

        rolled_back = await service.rollback_to(project_id, v2_result.version)

        # History is untouched - v2 and v3 both still readable.
        original_v2 = await service.get_version(project_id, 2)
        original_v3 = await service.get_version(project_id, 3)

    assert rolled_back.version == 4
    assert rolled_back.parent_version == 3
    assert len(rolled_back.scenes[0].shots) == 1  # matches v2's content
    assert original_v2 is not None and len(original_v2.scenes[0].shots) == 1
    assert original_v3 is not None and len(original_v3.scenes[0].shots) == 2


# --- M6.5, A11/A20: ShotBinding carry-forward across a version bump -----


async def _seed_resolved_binding(
    session, project_id: str, version: int, shot_id: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """A minimal stand-in for what the search-only ResolveAssetsStep pass
    would have written - just enough (asset_id, state, rung) to prove
    carry-forward copies it, without pulling in the whole real search
    path."""
    asset = AssetModel(
        project_id=uuid.UUID(project_id),
        provider="wikimedia",
        source_url="http://example.test/x.jpg",
        type="image",
        licence="cc0",
        content_hash=f"hash-{shot_id}-{version}",
        confidence=0.9,
    )
    session.add(asset)
    await session.flush()

    binding_repo = ShotBindingRepository(session)
    binding = await binding_repo.get_or_create_pending(uuid.UUID(project_id), version, shot_id)
    binding.state = "resolved"
    binding.asset_id = asset.id
    binding.rung = "historical_search"
    await session.flush()
    return asset.id, binding.id


async def test_binding_carries_forward_when_prompt_and_asset_plan_are_unchanged(project_id):
    """A20's central case: narration only ever changes `duration_s`, so a
    binding must survive that version bump untouched in substance."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def v2(base):
            shot = _shot("sh_01_01", 0)
            shot.prompt = "a coal mine"
            base.scenes = [_scene("sc_01", 0, [shot])]
            return base

        v2_result = await service.append_version(
            project_id, produced_by=ProducedBy.DIRECTOR, transform=v2, owns=frozenset({"scenes"})
        )
        asset_id, _ = await _seed_resolved_binding(
            session, project_id, v2_result.version, "sh_01_01"
        )

        def v3_duration_only(base):
            base.scenes[0].shots[0].duration_s = 9.0
            return base

        v3_result = await service.append_version(
            project_id,
            produced_by=ProducedBy.NARRATION,
            transform=v3_duration_only,
            owns=frozenset({"scenes"}),
        )

        binding_repo = ShotBindingRepository(session)
        carried = await binding_repo.get(uuid.UUID(project_id), v3_result.version, "sh_01_01")
        original = await binding_repo.get(uuid.UUID(project_id), v2_result.version, "sh_01_01")

    assert carried is not None
    assert carried.state == "resolved"
    assert carried.asset_id == asset_id
    assert carried.rung == "historical_search"
    # The original row at the superseded version is untouched, not moved
    # or deleted - carry-forward copies.
    assert original is not None
    assert original.asset_id == asset_id


async def test_binding_does_not_carry_forward_when_prompt_changes(project_id):
    """A20: a re-plan that changes a shot's `prompt` must not carry the
    old binding across - it was acquired for a question no longer being
    asked."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def v2(base):
            shot = _shot("sh_01_01", 0)
            shot.prompt = "a coal mine"
            base.scenes = [_scene("sc_01", 0, [shot])]
            return base

        v2_result = await service.append_version(
            project_id, produced_by=ProducedBy.DIRECTOR, transform=v2, owns=frozenset({"scenes"})
        )
        await _seed_resolved_binding(session, project_id, v2_result.version, "sh_01_01")

        def v3_reprompt(base):
            base.scenes[0].shots[0].prompt = "a different subject entirely"
            return base

        v3_result = await service.append_version(
            project_id,
            produced_by=ProducedBy.SHOT_PLANNER,
            transform=v3_reprompt,
            owns=frozenset({"scenes"}),
        )

        binding_repo = ShotBindingRepository(session)
        carried = await binding_repo.get(uuid.UUID(project_id), v3_result.version, "sh_01_01")

    assert carried is None  # must re-resolve against the new prompt


async def test_binding_does_not_carry_forward_when_asset_plan_changes(project_id):
    """A20: acquisition-relevant also means `asset_plan` - a shot whose
    search queries or licence requirements changed must re-resolve, even
    if its `prompt` happens to read the same."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def v2(base):
            shot = _shot("sh_01_01", 0)
            shot.prompt = "a coal mine"
            shot.asset_plan = AssetPlan(
                strategy=AssetStrategy.HISTORICAL_SEARCH,
                search_queries=["coal mine"],
                fallback_chain=[AssetStrategy.HISTORICAL_SEARCH, AssetStrategy.GENERATE_IMAGE],
                licence_requirements=["cc0"],
            )
            base.scenes = [_scene("sc_01", 0, [shot])]
            return base

        v2_result = await service.append_version(
            project_id, produced_by=ProducedBy.DIRECTOR, transform=v2, owns=frozenset({"scenes"})
        )
        await _seed_resolved_binding(session, project_id, v2_result.version, "sh_01_01")

        def v3_replan(base):
            base.scenes[0].shots[0].asset_plan.search_queries = ["Ruhr coal mine 1936"]
            return base

        v3_result = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=v3_replan,
            owns=frozenset({"scenes"}),
        )

        binding_repo = ShotBindingRepository(session)
        carried = await binding_repo.get(uuid.UUID(project_id), v3_result.version, "sh_01_01")

    assert carried is None  # must re-resolve against the new asset_plan


async def test_binding_does_not_carry_forward_when_the_shot_no_longer_exists(project_id):
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        def v2(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_01", 0)])]
            return base

        v2_result = await service.append_version(
            project_id, produced_by=ProducedBy.DIRECTOR, transform=v2, owns=frozenset({"scenes"})
        )
        await _seed_resolved_binding(session, project_id, v2_result.version, "sh_01_01")

        def v3_remove_shot(base):
            base.scenes = [_scene("sc_01", 0, [_shot("sh_01_02", 0)])]
            return base

        v3_result = await service.append_version(
            project_id,
            produced_by=ProducedBy.SHOT_PLANNER,
            transform=v3_remove_shot,
            owns=frozenset({"scenes"}),
        )

        binding_repo = ShotBindingRepository(session)
        carried_old_shot = await binding_repo.get(
            uuid.UUID(project_id), v3_result.version, "sh_01_01"
        )
        new_shot_binding = await binding_repo.get(
            uuid.UUID(project_id), v3_result.version, "sh_01_02"
        )

    assert carried_old_shot is None  # the removed shot has nothing to carry to
    assert new_shot_binding is None  # a brand new shot gets no binding until resolved
