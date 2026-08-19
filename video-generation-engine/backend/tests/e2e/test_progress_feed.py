"""Track C §13.4: default /progress is scene summaries, shot detail is
opt-in, ETag is a payload hash (not timeline.version).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

from .test_scene_approval_api import _seed_scenes, _two_scenes


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


def test_default_progress_omits_shot_detail_and_has_scenes(client):
    project_id = client.post("/api/v1/projects", json={"name": "13.4 slim"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _two_scenes()))

    slim = client.get(f"/api/v1/projects/{project_id}/progress")
    assert slim.status_code == 200
    body = slim.json()
    assert body["shots"] == []
    assert [s["id"] for s in body["scenes"]] == ["sc_01", "sc_02"]
    assert slim.headers.get("etag")

    expanded = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    assert len(expanded["shots"]) == 3
    assert expanded["shots"][0]["scene_id"] == "sc_01"


def test_progress_etag_returns_304_when_payload_is_unchanged(client):
    project_id = client.post("/api/v1/projects", json={"name": "13.4 etag"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _two_scenes()))

    first = client.get(f"/api/v1/projects/{project_id}/progress")
    etag = first.headers["etag"]
    second = client.get(f"/api/v1/projects/{project_id}/progress", headers={"If-None-Match": etag})
    assert second.status_code == 304


def test_scene_shots_endpoint_returns_one_scene(client):
    project_id = client.post("/api/v1/projects", json={"name": "13.4 scene shots"}).json()["id"]
    asyncio.run(_seed_scenes(project_id, _two_scenes()))

    resp = client.get(f"/api/v1/projects/{project_id}/scenes/sc_01/shots")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scene_id"] == "sc_01"
    assert [s["shot_id"] for s in body["shots"]] == ["sh_a", "sh_b"]

    missing = client.get(f"/api/v1/projects/{project_id}/scenes/nope/shots")
    assert missing.status_code == 404
