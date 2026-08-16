"""HTTP-level proof of M3 (M8 hardening, 2026-08-15): a music-selection
miss is no longer permanent. `POST /projects/{id}/music/retry` resets
`music_plan.selected_track`/`selection_attempted` via a real
`append_version` (I3) - optionally overriding the Timeline's own frozen
`search_terms`, since the whole point is escaping terms that were bad
from the start - and resumes the engine so `SelectMusicStep` genuinely
runs again.

DRY_RUN + `FakeMusicProvider` throughout (always finds a canned
candidate) - this proves the RESET-and-RESUME mechanism itself, the only
thing M3 actually changed; the real Openverse re-selection with the new
simple-literal terms (M1) and the real duration floor (M2) were verified
live and separately (not through this suite - see the coordinator's
report). Written but NOT run in this session - a live, human-driven
project sits at the approval gate in the same shared dev Postgres.

F0a (2026-08-16): `POST /music/retry` now returns `202` immediately - every
assertion below that used to read the trigger's own response body now
polls via `tests/e2e/_polling.py::trigger_and_wait` instead.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import async_session_factory
from app.main import app
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    EnergyArc,
    MusicPlan,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    Transition,
    TransitionType,
)
from app.timeline.service import TimelineService

from ._polling import trigger_and_wait

_JARGON_TERMS = [
    "documentary industrial ambient",
    "investigative historical underscore",
    "minimal mechanical pulse",
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


def _one_shot_scene() -> Scene:
    """A minimal but FULLY planned scene (non-empty shots, every shot has
    an `asset_plan`) - required so `GenerateTimelineStep.is_satisfied`
    returns True and the engine does NOT re-run the (DRY_RUN fake)
    planner chain on top of this seed - `_run_fake` completely replaces
    `music_plan` (along with everything else) whenever `timeline.scenes`
    is empty, which would silently overwrite the very state these tests
    are trying to control."""
    shot = Shot(
        id="sc_01_sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="archival photograph",
        asset_plan=AssetPlan(strategy=AssetStrategy.HISTORICAL_SEARCH),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    return Scene(id="sc_01", order=0, title="Scene", duration_s=3.0, shots=[shot])


async def _seed_stuck_music_plan(project_id: str, *, search_terms: list[str]) -> None:
    """Mirrors the real live project's own stuck state exactly: a
    `music_plan` whose search failed, frozen into the Timeline, with
    `selection_attempted=True` and no `selected_track` - the state
    `SelectMusicStep.is_satisfied` currently (correctly) treats as "done,
    nothing more to do", forever, without M3."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base: Timeline) -> Timeline:
            base.scenes = [_one_shot_scene()]
            base.metadata.total_duration_s = 3.0
            base.music_plan = MusicPlan(
                mood="tense",
                tempo="moderate",
                energy_arc=EnergyArc.BUILD,
                search_terms=list(search_terms),
                licence_requirements=["cc0", "by"],
                selected_track=None,
                selection_attempted=True,
            )
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata", "music_plan"}),
        )


def _create_project(client: TestClient) -> str:
    return client.post("/api/v1/projects", json={"name": "music retry test"}).json()["id"]


def test_retry_overrides_frozen_search_terms_and_finds_a_track(client):
    project_id = _create_project(client)
    asyncio.run(_seed_stuck_music_plan(project_id, search_terms=_JARGON_TERMS))

    trigger_and_wait(
        client,
        "post",
        f"/api/v1/projects/{project_id}/music/retry",
        json={"search_terms": ["documentary music", "ambient"]},
    )

    async def _read_back() -> Timeline:
        async with async_session_factory() as session:
            return await TimelineService(session).get_active(project_id)

    timeline = asyncio.run(_read_back())
    assert timeline.music_plan.search_terms == ["documentary music", "ambient"]
    assert timeline.music_plan.selection_attempted is True
    # FakeMusicProvider (DRY_RUN) always finds a canned candidate - a
    # populated selected_track here proves SelectMusicStep genuinely ran
    # again, not that is_satisfied merely flipped and nothing followed.
    assert timeline.music_plan.selected_track is not None
    assert timeline.music_plan.selected_track.provider == "fake_music"


def test_retry_without_search_terms_keeps_the_existing_ones(client):
    project_id = _create_project(client)
    asyncio.run(_seed_stuck_music_plan(project_id, search_terms=_JARGON_TERMS))

    trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/music/retry", json={})

    async def _read_back() -> Timeline:
        async with async_session_factory() as session:
            return await TimelineService(session).get_active(project_id)

    timeline = asyncio.run(_read_back())
    # Not overridden - still the (bad) terms the project already had -
    # but the attempt genuinely re-ran regardless (a code fix like M1/M2
    # can help even without a human supplying anything new).
    assert timeline.music_plan.search_terms == _JARGON_TERMS
    assert timeline.music_plan.selected_track is not None


def test_retry_rejects_an_explicitly_empty_search_terms_list(client):
    project_id = _create_project(client)
    asyncio.run(_seed_stuck_music_plan(project_id, search_terms=_JARGON_TERMS))

    resp = client.post(f"/api/v1/projects/{project_id}/music/retry", json={"search_terms": []})
    assert resp.status_code == 400


def test_retry_requires_a_timeline_to_exist(client):
    project_id = client.post("/api/v1/projects", json={"name": "no timeline yet"}).json()["id"]
    resp = client.post(f"/api/v1/projects/{project_id}/music/retry", json={})
    assert resp.status_code == 400


def test_retry_requires_a_music_plan_to_exist(client):
    project_id = _create_project(client)

    async def _seed_no_music_plan() -> None:
        async with async_session_factory() as session:
            service = TimelineService(session)
            await service.create_initial(project_id, script="unused")

    asyncio.run(_seed_no_music_plan())

    resp = client.post(f"/api/v1/projects/{project_id}/music/retry", json={})
    assert resp.status_code == 400


def test_retry_re_approves_when_the_timeline_was_already_approved(client):
    """Mirrors `override_shot_asset`'s own belt-and-braces pattern: a
    correction to an already-approved timeline is re-approved in the same
    call, so resuming does not demand a redundant second human click."""
    project_id = _create_project(client)
    asyncio.run(_seed_stuck_music_plan(project_id, search_terms=_JARGON_TERMS))

    async def _approve_current() -> int:
        async with async_session_factory() as session:
            service = TimelineService(session)
            active = await service.get_active(project_id)
            await service.approve(project_id, active.version)
            return active.version

    asyncio.run(_approve_current())

    body = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/music/retry", json={})
    # Approval survived the retry - the project did not fall back to
    # awaiting a redundant second approval for a correction already
    # requested.
    assert body["status"] != "draft"
