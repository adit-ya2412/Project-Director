"""P0 (docs/plans/gate_panel_overrides.md): `GET /projects/{id}/prompts/
export`. Same idiom as `test_focal_override_api.py` - real FastAPI
routing, `get_repo`/`get_timeline_service` overridden with fakes, no
Postgres, safe under `--noconftest`. The prompt CONTENT itself (ordering,
identity, the parallax fallback label, the size header) is covered
directly against `app.assets.prompt_export` in
`tests/unit/assets/test_prompt_export.py` - this file is only about the
endpoint's own plumbing: 404s, the response headers, and that it actually
calls through to that module rather than a route-local re-derivation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.projects as projects_module
from app.api.deps import get_repo, get_timeline_service
from app.schemas.timeline import ProducedBy, Scene, Shot, ShotIntent, Timeline, TimelineStatus

_PROJECT = "33333333-3333-3333-3333-333333333333"


class _FakeProject:
    def __init__(self, name: str = "The City Rats"):
        self.name = name


class _FakeRepo:
    def __init__(self, project: _FakeProject | None):
        self._project = project

    async def get(self, project_id):
        return self._project


class _FakeTimelineService:
    def __init__(self, timeline: Timeline | None):
        self._timeline = timeline

    async def get_active(self, project_id):
        return self._timeline


def _timeline() -> Timeline:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt="a coal mine")
    scene = Scene(id="sc_01", order=0, title="S", duration_s=3.0, shots=[shot])
    return Timeline(
        timeline_id="t1",
        project_id=_PROJECT,
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


def _client(*, project: _FakeProject | None, timeline: Timeline | None) -> TestClient:
    app = FastAPI()
    app.include_router(projects_module.router)
    app.dependency_overrides[get_repo] = lambda: _FakeRepo(project)
    app.dependency_overrides[get_timeline_service] = lambda: _FakeTimelineService(timeline)
    return TestClient(app)


def test_404_when_the_project_does_not_exist():
    client = _client(project=None, timeline=None)
    resp = client.get(f"/projects/{_PROJECT}/prompts/export")
    assert resp.status_code == 404


def test_404_when_no_timeline_has_been_generated_yet():
    client = _client(project=_FakeProject(), timeline=None)
    resp = client.get(f"/projects/{_PROJECT}/prompts/export")
    assert resp.status_code == 404


def test_success_is_plain_text_with_a_downloadable_filename():
    client = _client(project=_FakeProject(), timeline=_timeline())
    resp = client.get(f"/projects/{_PROJECT}/prompts/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert f"{_PROJECT}-prompts.txt" in disposition
    # The one shot's own prompt really is in the body - proves the route
    # actually calls through to `build_prompt_export_entries`, not a stub.
    assert "a coal mine" in resp.text
    assert "sh_01" in resp.text
