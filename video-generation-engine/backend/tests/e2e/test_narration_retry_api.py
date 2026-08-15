"""HTTP-level proof of N1 (2026-08-15): `POST /projects/{id}/narration/retry`
makes narration redoable with a different voice - the third instance of
the "automated creative choice, human redo path" shape (per-shot
override, M3's music retry, this). DRY_RUN + `FakeNarrationProvider`
throughout - no real ElevenLabs calls, no money spent, matching this
session's constraint.

Written but NOT run in this session - a live, human-driven, now fully
rendered project sits at the approval gate in the same shared dev
Postgres; running pytest would truncate it via `tests/conftest.py`'s
autouse `clean_database` fixture.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import async_session_factory
from app.main import app
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

_SCENE_TEXT = "Bro, Germany ke paas oil tha hi nahi."


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


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


def _create_project(client: TestClient) -> str:
    return client.post("/api/v1/projects", json={"name": "narration retry test"}).json()["id"]


async def _seed_narrated_project(project_id: str, *, voice_id: str) -> None:
    """A fully-planned, single-shot project whose narration has already
    run once with `voice_id` - `GenerateTimelineStep.is_satisfied` must
    read True (non-empty scenes/shots/asset_plan) or resuming the engine
    would re-plan with the DRY_RUN fake planner and clobber this seed,
    exactly the pitfall already documented in
    `tests/e2e/test_music_retry_api.py`."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            base.metadata.voice_id = voice_id
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )

    async with async_session_factory() as session:
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=PostgresProjectRepository(session),
            timeline_service=TimelineService(session),
        )
        result = await NarrationStep().run(ctx)
        assert result.outcome == "ok", result.error


async def _read_active(project_id: str) -> Timeline:
    async with async_session_factory() as session:
        return await TimelineService(session).get_active(project_id)


def test_retry_requires_a_timeline_to_exist(client):
    project_id = client.post("/api/v1/projects", json={"name": "no timeline yet"}).json()["id"]
    resp = client.post(
        f"/api/v1/projects/{project_id}/narration/retry", json={"voice_id": "new-voice"}
    )
    assert resp.status_code == 400


def test_retry_rejects_an_empty_voice_id(client):
    project_id = _create_project(client)
    asyncio.run(_seed_narrated_project(project_id, voice_id="voice-A"))

    resp = client.post(f"/api/v1/projects/{project_id}/narration/retry", json={"voice_id": "   "})
    assert resp.status_code == 400


def test_retry_sets_the_new_voice_and_resynthesises(client):
    project_id = _create_project(client)
    asyncio.run(_seed_narrated_project(project_id, voice_id="voice-A"))

    before = asyncio.run(_read_active(project_id))
    assert before.produced_by == ProducedBy.NARRATION
    assert before.metadata.voice_id == "voice-A"

    resp = client.post(
        f"/api/v1/projects/{project_id}/narration/retry", json={"voice_id": "voice-B"}
    )
    assert resp.status_code == 200, resp.text

    after = asyncio.run(_read_active(project_id))
    # NarrationStep genuinely re-ran (DRY_RUN's fake still cycles
    # produced_by back to NARRATION on success) and picked up the new
    # voice - not merely that the HTTP call returned 200.
    assert after.metadata.voice_id == "voice-B"
    assert after.produced_by == ProducedBy.NARRATION
    assert after.version > before.version


def test_retry_re_approves_when_the_timeline_was_already_approved(client):
    project_id = _create_project(client)
    asyncio.run(_seed_narrated_project(project_id, voice_id="voice-A"))

    async def _approve_current() -> None:
        async with async_session_factory() as session:
            service = TimelineService(session)
            active = await service.get_active(project_id)
            await service.approve(project_id, active.version)

    asyncio.run(_approve_current())

    resp = client.post(
        f"/api/v1/projects/{project_id}/narration/retry", json={"voice_id": "voice-B"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] != "draft"
