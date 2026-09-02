"""long_form_direction.md A12: `POST /shots/{shot_id}/sfx-cue/clear`, the
narrow per-shot endpoint that clears one shot's `Shot.sfx_cue`.

Same idiom as `test_sfx_override_api.py` (RV10/RV3): real FastAPI routing,
every database dependency overridden with a fake, `start_workflow_run`
monkeypatched at `app.api.projects`' own namespace. No Postgres; safe
under `--noconftest`.

This endpoint additionally touches `session.commit()` and
`WorkflowRunRepository` directly on the DRAFT (not-yet-approved) branch
- mirroring `override_shot_asset`'s own "join the existing run, do not
resume" shape (needed for the identical reason: resuming pre-approval
with a `produced_by=HUMAN` version would make `NarrationStep.is_satisfied`
think narration is stale and re-run it, which costs real money). Both are
faked here too, the same way `start_workflow_run` already is.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.projects as projects_module
from app.api.deps import get_repo, get_timeline_service
from app.db.session import get_db
from app.schemas.timeline import (
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.workflow.trigger import WorkflowTriggerResult

_PROJECT = "22222222-2222-2222-2222-222222222222"


class _FakeRepo:
    async def get(self, project_id):
        return object()  # only None matters to _get_project_or_404


class _FakeSession:
    def __init__(self):
        self.committed = 0

    async def commit(self):
        self.committed += 1


class _FakeTimelineService:
    def __init__(self, timeline: Timeline | None):
        self._timeline = timeline
        self.append_calls: list[dict] = []
        self.approved_versions: list[int] = []

    async def get_active(self, project_id):
        return self._timeline

    async def append_version(self, project_id, *, produced_by, transform, owns):
        new = transform(self._timeline)
        self.append_calls.append({"produced_by": produced_by, "owns": frozenset(owns)})
        self._timeline = new
        return new

    async def approve(self, project_id, version):
        self.approved_versions.append(version)
        self._timeline.status = TimelineStatus.APPROVED


def _timeline(*, status: TimelineStatus = TimelineStatus.DRAFT, cue: str | None = "a bell tolling") -> Timeline:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue=cue)
    other = Shot(id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue=None)
    scene = Scene(id="sc_01", order=0, title="S", duration_s=6.0, shots=[shot, other])
    return Timeline(
        timeline_id="t1",
        project_id=_PROJECT,
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


@pytest.fixture()
def make_client(monkeypatch):
    started: list[str] = []

    async def fake_start(project_id, session, background_tasks):
        started.append(project_id)
        return WorkflowTriggerResult(
            project_id=project_id,
            workflow_run_id="run-1",
            state="started",
            joined_existing_run=False,
        )

    monkeypatch.setattr(projects_module, "start_workflow_run", fake_start)

    class _FakeWorkflowRunRepository:
        def __init__(self, session):
            self._session = session

        async def get_latest(self, project_uuid):
            return SimpleNamespace(id=uuid.uuid4(), state="running")

    monkeypatch.setattr(projects_module, "WorkflowRunRepository", _FakeWorkflowRunRepository)

    def _build(timeline: Timeline | None | object = "default"):
        service = _FakeTimelineService(_timeline() if timeline == "default" else timeline)
        session = _FakeSession()
        app = FastAPI()
        app.include_router(projects_module.router)

        async def _override_db():
            yield session

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_repo] = lambda: _FakeRepo()
        app.dependency_overrides[get_timeline_service] = lambda: service
        return TestClient(app), service, session, started

    return _build


def test_missing_timeline_is_400(make_client):
    client, _, _, _ = make_client(timeline=None)
    res = client.post(f"/projects/{_PROJECT}/shots/sh_01/sfx-cue/clear")
    assert res.status_code == 400
    assert "no timeline" in res.json()["detail"]


def test_unknown_shot_is_404(make_client):
    client, _, _, _ = make_client()
    res = client.post(f"/projects/{_PROJECT}/shots/does-not-exist/sfx-cue/clear")
    assert res.status_code == 404


def test_shot_with_no_cue_is_400(make_client):
    client, service, _, started = make_client()
    res = client.post(f"/projects/{_PROJECT}/shots/sh_02/sfx-cue/clear")
    assert res.status_code == 400
    assert "no sfx cue" in res.json()["detail"]
    assert service.append_calls == [] and started == []


def test_clear_on_draft_timeline_does_not_resume_the_engine(make_client):
    """Mirrors `override_shot_asset`'s own first-gate branch: a
    `produced_by=HUMAN` version must not trigger a resume before
    approval, or `NarrationStep.is_satisfied` sees a non-NARRATION
    version and re-narrates for real money."""
    client, service, session, started = make_client()
    res = client.post(f"/projects/{_PROJECT}/shots/sh_01/sfx-cue/clear")
    assert res.status_code == 202
    assert res.json()["joined_existing_run"] is True
    assert started == []  # NOT resumed
    assert service.approved_versions == []

    cleared = next(s for s in service._timeline.all_shots() if s.id == "sh_01")
    assert cleared.sfx_cue is None
    assert service.append_calls == [
        {"produced_by": ProducedBy.HUMAN, "owns": frozenset({"scenes"})}
    ]
    assert session.committed == 1


def test_clear_on_approved_timeline_re_approves_and_resumes(make_client):
    client, service, session, started = make_client(timeline=_timeline(status=TimelineStatus.APPROVED))
    res = client.post(f"/projects/{_PROJECT}/shots/sh_01/sfx-cue/clear")
    assert res.status_code == 202
    assert started == [_PROJECT]
    assert service.approved_versions == [service._timeline.version]

    cleared = next(s for s in service._timeline.all_shots() if s.id == "sh_01")
    assert cleared.sfx_cue is None


def test_clear_leaves_other_shots_cue_untouched(make_client):
    client, service, _, _ = make_client()
    client.post(f"/projects/{_PROJECT}/shots/sh_01/sfx-cue/clear")
    untouched = next(s for s in service._timeline.all_shots() if s.id == "sh_02")
    assert untouched.sfx_cue is None  # was already None; still None, not an error
