"""C5: per-scene approval, progress `scenes[]`, bulk regenerate-failed,
and the F3 pinning invariant — a short project and a longer one land
on the same `approved_scenes` state after `POST /timeline/approve`.
"""

import asyncio
import uuid as uuid_module

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import async_session_factory
from app.main import app
from app.models.shot_binding import ShotBindingModel
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.timeline import ProducedBy, Scene, Shot, ShotIntent, Transition, TransitionType
from app.timeline.service import TimelineService


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


def _shot(shot_id: str, order: int, duration_s: float = 2.0) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        prompt=f"prompt for {shot_id}",
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )


async def _seed_scenes(
    project_id: str,
    scenes: list[Scene],
    *,
    failed_shot_ids: frozenset[str] = frozenset(),
) -> int:
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base):
            base.scenes = scenes
            base.metadata.total_duration_s = sum(s.duration_s for s in scenes)
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )

        project_uuid = uuid_module.UUID(project_id)
        for scene in scenes:
            for shot in scene.shots:
                session.add(
                    ShotBindingModel(
                        project_id=project_uuid,
                        timeline_version=appended.version,
                        shot_id=shot.id,
                        state="failed" if shot.id in failed_shot_ids else "resolved",
                    )
                )
        await session.commit()
        return appended.version


def _two_scenes() -> list[Scene]:
    return [
        Scene(
            id="sc_01",
            order=0,
            title="Coal",
            duration_s=4.0,
            shots=[_shot("sh_a", 0), _shot("sh_b", 1)],
        ),
        Scene(
            id="sc_02",
            order=1,
            title="Oil",
            duration_s=2.0,
            shots=[_shot("sh_c", 0)],
        ),
    ]


def _one_scene() -> list[Scene]:
    return [
        Scene(
            id="sc_only",
            order=0,
            title="Only",
            duration_s=2.0,
            shots=[_shot("sh_only", 0)],
        )
    ]


def test_progress_includes_scenes_and_scene_id_on_shots(client):
    project_id = client.post("/api/v1/projects", json={"name": "c5 progress scenes"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _two_scenes()))

    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    scenes = progress["scenes"]
    assert [s["id"] for s in scenes] == ["sc_01", "sc_02"]
    assert scenes[0]["title"] == "Coal"
    assert scenes[0]["shot_ids"] == ["sh_a", "sh_b"]
    assert scenes[0]["total_shots"] == 2
    assert scenes[0]["completed_shots"] == 2
    assert scenes[0]["failed_shots"] == 0
    assert scenes[0]["unfilled_shots"] == 0
    assert scenes[0]["approved"] is False
    assert scenes[0]["starts_at_s"] == 0.0
    assert scenes[0]["act_id"] is None
    assert scenes[1]["starts_at_s"] == 4.0
    assert scenes[1]["shot_ids"] == ["sh_c"]

    by_shot = {s["shot_id"]: s for s in progress["shots"]}
    assert by_shot["sh_a"]["scene_id"] == "sc_01"
    assert by_shot["sh_c"]["scene_id"] == "sc_02"


def test_per_scene_approve_is_monotonic_and_does_not_stamp_document(client):
    project_id = client.post("/api/v1/projects", json={"name": "c5 scene approve"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _two_scenes()))

    first = client.post(f"/api/v1/projects/{project_id}/scenes/sc_01/approve")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["scene_id"] == "sc_01"
    assert body["approved"] is True
    assert body["approved_scenes"] == ["sc_01"]
    assert body["all_scenes_approved"] is False

    timeline = client.get(f"/api/v1/projects/{project_id}/timeline").json()
    assert timeline["status"] == "draft"
    assert timeline["metadata"]["approved_scenes"] == ["sc_01"]
    version_after_first = timeline["version"]

    again = client.post(f"/api/v1/projects/{project_id}/scenes/sc_01/approve")
    assert again.status_code == 200, again.text
    assert again.json()["approved_scenes"] == ["sc_01"]
    timeline_again = client.get(f"/api/v1/projects/{project_id}/timeline").json()
    assert timeline_again["version"] == version_after_first

    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    by_id = {s["id"]: s for s in progress["scenes"]}
    assert by_id["sc_01"]["approved"] is True
    assert by_id["sc_02"]["approved"] is False


def test_per_scene_approve_refuses_unfilled_shots(client):
    project_id = client.post("/api/v1/projects", json={"name": "c5 unfilled scene"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _two_scenes(), failed_shot_ids=frozenset({"sh_b"})))

    resp = client.post(f"/api/v1/projects/{project_id}/scenes/sc_01/approve")
    assert resp.status_code == 400
    assert "sh_b" in resp.json()["detail"]
    assert "sh_c" not in resp.json()["detail"]

    ok = client.post(f"/api/v1/projects/{project_id}/scenes/sc_02/approve")
    assert ok.status_code == 200, ok.text


def test_unknown_scene_returns_404(client):
    project_id = client.post("/api/v1/projects", json={"name": "c5 missing scene"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _one_scene()))

    resp = client.post(f"/api/v1/projects/{project_id}/scenes/sc_nope/approve")
    assert resp.status_code == 404


def test_timeline_approve_stamps_the_same_scene_set_on_short_and_long_projects(client):
    """F3's pinning test: the backend has one model. A one-scene project
    (stands in for below the frontend threshold) and a two-scene project
    (stands in for above it) both end with every scene id in
    `approved_scenes` after the same `POST /timeline/approve` call."""
    short_id = client.post("/api/v1/projects", json={"name": "c5 short"}).json()["id"]
    long_id = client.post("/api/v1/projects", json={"name": "c5 long"}).json()["id"]
    asyncio.run(_seed_scenes(short_id, _one_scene()))
    asyncio.run(_seed_scenes(long_id, _two_scenes()))

    short_resp = client.post(f"/api/v1/projects/{short_id}/timeline/approve")
    long_resp = client.post(f"/api/v1/projects/{long_id}/timeline/approve")
    assert short_resp.status_code == 202, short_resp.text
    assert long_resp.status_code == 202, long_resp.text

    short_tl = client.get(f"/api/v1/projects/{short_id}/timeline").json()
    long_tl = client.get(f"/api/v1/projects/{long_id}/timeline").json()
    assert short_tl["status"] == "approved"
    assert long_tl["status"] == "approved"
    assert set(short_tl["metadata"]["approved_scenes"]) == {"sc_only"}
    assert set(long_tl["metadata"]["approved_scenes"]) == {"sc_01", "sc_02"}


def test_per_scene_then_document_approve_matches_all_at_once_stamp(client):
    per_scene_id = client.post("/api/v1/projects", json={"name": "c5 per scene then all"}).json()[
        "id"
    ]
    all_at_once_id = client.post("/api/v1/projects", json={"name": "c5 all at once"}).json()["id"]
    asyncio.run(_seed_scenes(per_scene_id, _two_scenes()))
    asyncio.run(_seed_scenes(all_at_once_id, _two_scenes()))

    assert client.post(f"/api/v1/projects/{per_scene_id}/scenes/sc_01/approve").status_code == 200
    assert client.post(f"/api/v1/projects/{per_scene_id}/timeline/approve").status_code == 202
    assert client.post(f"/api/v1/projects/{all_at_once_id}/timeline/approve").status_code == 202

    per_scene = client.get(f"/api/v1/projects/{per_scene_id}/timeline").json()
    all_at_once = client.get(f"/api/v1/projects/{all_at_once_id}/timeline").json()
    assert (
        set(per_scene["metadata"]["approved_scenes"])
        == set(all_at_once["metadata"]["approved_scenes"])
        == {"sc_01", "sc_02"}
    )


def test_regenerate_failed_requires_confirmation_then_fills(client):
    project_id = client.post("/api/v1/projects", json={"name": "c5 regen failed"}).json()["id"]
    version = asyncio.run(
        _seed_scenes(project_id, _two_scenes(), failed_shot_ids=frozenset({"sh_a", "sh_b"}))
    )
    assert version >= 1

    missing = client.post(f"/api/v1/projects/{project_id}/scenes/sc_01/regenerate-failed")
    assert missing.status_code == 400
    detail = missing.json()["detail"]
    expected = 2 * settings.fal_image_cost_cents_estimate
    assert f"confirmed_cost_cents={expected}" in detail

    wrong = client.post(
        f"/api/v1/projects/{project_id}/scenes/sc_01/regenerate-failed",
        params={"confirmed_cost_cents": expected - 1},
    )
    assert wrong.status_code == 400

    ok = client.post(
        f"/api/v1/projects/{project_id}/scenes/sc_01/regenerate-failed",
        params={"confirmed_cost_cents": expected},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["regenerated"] is True
    assert set(body["shot_ids"]) == {"sh_a", "sh_b"}
    assert body["estimated_cost_cents"] == expected

    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    by_shot = {s["shot_id"]: s for s in progress["shots"]}
    assert by_shot["sh_a"]["state"] == "generated"
    assert by_shot["sh_b"]["state"] == "generated"
    assert by_shot["sh_c"]["state"] == "resolved"


def test_regenerate_failed_on_already_approved_scene_is_the_repair_path(client):
    """Q6: scene approval is a review record, not a lock."""
    project_id = client.post("/api/v1/projects", json={"name": "c5 repair after approve"}).json()[
        "id"
    ]
    asyncio.run(_seed_scenes(project_id, _two_scenes()))
    assert client.post(f"/api/v1/projects/{project_id}/scenes/sc_01/approve").status_code == 200

    async def _fail_one():
        async with async_session_factory() as session:
            timeline = await TimelineService(session).get_active(project_id)
            repo = ShotBindingRepository(session)
            binding = await repo.get(uuid_module.UUID(project_id), timeline.version, "sh_a")
            assert binding is not None
            binding.state = "failed"
            await session.commit()

    asyncio.run(_fail_one())

    expected = settings.fal_image_cost_cents_estimate
    resp = client.post(
        f"/api/v1/projects/{project_id}/scenes/sc_01/regenerate-failed",
        params={"confirmed_cost_cents": expected},
    )
    assert resp.status_code == 200, resp.text
    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    scene = next(s for s in progress["scenes"] if s["id"] == "sc_01")
    assert scene["approved"] is True
    by_shot = {s["shot_id"]: s for s in progress["shots"]}
    assert by_shot["sh_a"]["state"] == "generated"


def test_regenerate_failed_with_no_failures_is_400(client):
    project_id = client.post("/api/v1/projects", json={"name": "c5 no failures"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _one_scene()))
    resp = client.post(
        f"/api/v1/projects/{project_id}/scenes/sc_only/regenerate-failed",
        params={"confirmed_cost_cents": 0},
    )
    assert resp.status_code == 400
    assert "no failed shots" in resp.json()["detail"]
