"""N1 (2026-08-15): narration must be redoable with a different voice.
`NarrationStep.is_satisfied` returns true whenever the active version is
`produced_by == NARRATION`, with no way back - the fix is the same
`produced_by=HUMAN` `append_version` shape as the per-shot override
(A24) and M3's music retry, setting `metadata.voice_id` (a field
`NarrationStep.run` already reads, but that nothing wrote before this).

These tests exercise the mechanism directly (`TimelineService
.append_version` + `NarrationStep`) rather than only through the HTTP
route - `tests/e2e/test_narration_retry_api.py` covers the route itself
and its own validation/re-approval behaviour. DRY_RUN +
`FakeNarrationProvider` throughout: no real ElevenLabs calls, matching
this session's "do not spend money" constraint - the cache-hit and
re-synthesis properties are about the CONTENT-HASH mechanism, which
`FakeNarrationProvider` exercises for real (it still writes real
content-hash-keyed `narration` rows, just with undecodable fake bytes -
see that fake's own docstring).

Written but NOT run in this session - a live, human-driven project sits
at the approval gate (now fully rendered) in the same shared dev
Postgres, and running pytest would truncate it via `tests/conftest.py`'s
autouse `clean_database` fixture.
"""

import uuid as uuid_module
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.narration import NarrationModel
from app.models.shot_binding import ShotBindingModel
from app.providers.elevenlabs import compute_narration_content_hash
from app.repositories.project_repository import PostgresProjectRepository
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
from app.workflow.steps.narration import NarrationStep

_VOICE_A = "voice-A-test"
_VOICE_B = "voice-B-test"
_SCENE_TEXT = "Bro, Germany ke paas oil tha hi nahi. Phir bhi unke tanks chalte rahe."


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


def _one_shot_scene() -> Scene:
    shot = Shot(
        id="sc_01_sh_01",
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


async def _narration_row_count(session, project_id: str) -> int:
    result = await session.execute(
        select(NarrationModel).where(NarrationModel.project_id == uuid_module.UUID(project_id))
    )
    return len(result.scalars().all())


@pytest_asyncio.fixture
async def project_narrated_with_voice_a(monkeypatch) -> str:
    """A project whose narration has already run once, with `voice_id
    = _VOICE_A` - the exact "narration is frozen at the first voice"
    state N1 exists to unstick."""
    monkeypatch.setattr(settings, "dry_run", True)

    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).create("N1 narration retry test")
        project_id = project.id

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _seed(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            base.metadata.voice_id = _VOICE_A
            return base

        seeded = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_seed,
            owns=frozenset({"scenes", "metadata"}),
        )
        session.add(
            ShotBindingModel(
                project_id=uuid_module.UUID(project_id),
                timeline_version=seeded.version,
                shot_id="sc_01_sh_01",
                state="resolved",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error

    return project_id


async def test_voice_retry_flips_is_satisfied_and_resynthesises_with_the_new_voice(
    project_narrated_with_voice_a,
):
    project_id = project_narrated_with_voice_a

    async with async_session_factory() as session:
        active = await TimelineService(session).get_active(project_id)
        assert active.produced_by == ProducedBy.NARRATION
        assert await NarrationStep().is_satisfied(_make_ctx(project_id, session)) is True
        assert await _narration_row_count(session, project_id) == 1

    # The retry transform - identical in shape to
    # `POST /narration/retry`'s own (see app/api/projects.py).
    async with async_session_factory() as session:
        service = TimelineService(session)

        def _set_voice_b(base: Timeline) -> Timeline:
            base.metadata.voice_id = _VOICE_B
            return base

        new_timeline = await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_set_voice_b,
            owns=frozenset({"metadata"}),
        )
        assert new_timeline.produced_by == ProducedBy.HUMAN

    async with async_session_factory() as session:
        assert await NarrationStep().is_satisfied(_make_ctx(project_id, session)) is False

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error

    async with async_session_factory() as session:
        active = await TimelineService(session).get_active(project_id)
        assert active.produced_by == ProducedBy.NARRATION
        assert await NarrationStep().is_satisfied(_make_ctx(project_id, session)) is True
        # A genuinely new row for the new voice, not the old one reused.
        assert await _narration_row_count(session, project_id) == 2
        hash_b = compute_narration_content_hash(
            text=_SCENE_TEXT,
            voice_id=_VOICE_B,
            model=settings.elevenlabs_model,
            output_format=settings.elevenlabs_output_format,
        )
        row = await session.execute(
            select(NarrationModel).where(NarrationModel.content_hash == hash_b)
        )
        assert row.scalar_one_or_none() is not None


async def test_switching_back_to_a_previous_voice_synthesises_nothing_new(
    project_narrated_with_voice_a,
):
    """The property the coordinator explicitly wants proven: the
    narration cache is keyed on `hash(text + voice_id + model +
    output_format)`, so trying voice B and returning to voice A costs
    nothing the second time."""
    project_id = project_narrated_with_voice_a

    # Move to voice B first (mirrors the test above).
    async with async_session_factory() as session:
        service = TimelineService(session)

        def _set_voice_b(base: Timeline) -> Timeline:
            base.metadata.voice_id = _VOICE_B
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_set_voice_b,
            owns=frozenset({"metadata"}),
        )
    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error
    async with async_session_factory() as session:
        assert await _narration_row_count(session, project_id) == 2

    # Now back to voice A - already synthesised once by the fixture.
    async with async_session_factory() as session:
        service = TimelineService(session)

        def _set_voice_a(base: Timeline) -> Timeline:
            base.metadata.voice_id = _VOICE_A
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_set_voice_a,
            owns=frozenset({"metadata"}),
        )
    async with async_session_factory() as session:
        assert await NarrationStep().is_satisfied(_make_ctx(project_id, session)) is False

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error

    async with async_session_factory() as session:
        # Still 2 - the whole point. A third row would mean voice A got
        # re-synthesised instead of hitting its existing cache entry.
        assert await _narration_row_count(session, project_id) == 2


async def test_voice_change_leaves_fresh_bindings_so_a_stale_render_is_not_served(
    project_narrated_with_voice_a,
):
    """`RenderStep.is_satisfied` compares the existing render file's
    mtime against the latest ShotBinding update for the active version -
    this proves a voice-change version bump always produces a binding
    update newer than any pre-existing render, via the SAME
    `TimelineService._carry_forward_bindings` mechanism that already
    (and independently) makes the render fingerprint itself differ
    (`tests/unit/renderer/test_fingerprint.py
    ::test_different_narration_changes_the_fingerprint` covers that
    half already - this test covers the OTHER half, the binding-
    timestamp staleness check `RenderStep.is_satisfied` itself runs)."""
    project_id = project_narrated_with_voice_a

    # A render "already happened" at this point in real wall-clock time.
    marker_time = datetime.now(UTC)

    async with async_session_factory() as session:
        service = TimelineService(session)

        def _set_voice_b(base: Timeline) -> Timeline:
            base.metadata.voice_id = _VOICE_B
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_set_voice_b,
            owns=frozenset({"metadata"}),
        )
    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        assert result.outcome == "ok", result.error

    async with async_session_factory() as session:
        active = await TimelineService(session).get_active(project_id)
        result = await session.execute(
            select(ShotBindingModel).where(
                ShotBindingModel.project_id == uuid_module.UUID(project_id),
                ShotBindingModel.timeline_version == active.version,
            )
        )
        bindings = result.scalars().all()
        assert bindings, "carry-forward must have produced a binding for the new version"
        latest_binding_update = max(b.updated_at for b in bindings)
        # This is exactly RenderStep.is_satisfied's own comparison
        # (video_mtime >= latest_binding_update means "still fresh") -
        # a render file from BEFORE the voice change must compare as
        # stale against it.
        assert latest_binding_update > marker_time
