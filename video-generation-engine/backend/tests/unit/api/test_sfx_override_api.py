"""C3f endpoint-shell tests (analysis.md RV10): the `file` × `enabled`
branching, storage paths, provenance fields, and the `/sfx/retry` reset -
through REAL FastAPI routing with every database dependency overridden.
No Postgres; safe under `--noconftest` (see the RV3 conftest gate).

`start_workflow_run` is monkeypatched at `app.api.projects`' own
namespace (the only place the endpoint looks it up), and the fake
timeline service APPLIES each captured transform to the active timeline
exactly as the real `TimelineService.append_version` would - so tests
assert on the resulting document, not merely that a callback fired."""

import hashlib
import shutil
import subprocess
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.projects as projects_module
from app.api.deps import get_repo, get_timeline_service
from app.core.config import settings
from app.db.session import get_db
from app.schemas.timeline import (
    ProducedBy,
    Scene,
    SfxClipSelection,
    SfxKind,
    SfxPlan,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.workflow.trigger import WorkflowTriggerResult

_FFMPEG = shutil.which(settings.ffmpeg_binary) or shutil.which("ffmpeg")
_PROJECT = "11111111-1111-1111-1111-111111111111"


class _FakeRepo:
    async def get(self, project_id):
        return object()  # only None matters to _get_project_or_404


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
        return new

    async def approve(self, project_id, version):
        self.approved_versions.append(version)


def _timeline(*, with_sfx: bool = True) -> Timeline:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    scene = Scene(id="sc_01", order=0, title="S", duration_s=3.0, shots=[shot])
    timeline = Timeline(
        timeline_id="t1",
        project_id=_PROJECT,
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,  # DRAFT -> the shared tail skips re-approve
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )
    if with_sfx:
        timeline.sfx_plan = SfxPlan(
            clips=[
                SfxClipSelection(
                    kind=SfxKind.WHOOSH,
                    provider="local",
                    track_id="w.mp3",
                    source_url="",
                    licence="cc0",
                    attribution="",
                    content_hash="hash-w",
                ),
                SfxClipSelection(
                    kind=SfxKind.STINGER,
                    provider="local",
                    track_id="s.mp3",
                    source_url="",
                    licence="cc0",
                    attribution="",
                    content_hash="hash-s",
                ),
            ]
        )
    else:
        timeline.sfx_plan = None
    return timeline


@pytest.fixture()
def make_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
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

    def _build(timeline: Timeline | None | object = "default"):
        service = _FakeTimelineService(_timeline() if timeline == "default" else timeline)
        app = FastAPI()
        app.include_router(projects_module.router)

        async def _override_db():
            yield None

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_repo] = lambda: _FakeRepo()
        app.dependency_overrides[get_timeline_service] = lambda: service
        return TestClient(app), service, started

    return _build


def _tone_wav(tmp_path) -> bytes:
    out = tmp_path / "tone.wav"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out.read_bytes()


# -- request-shape validation ------------------------------------------------


def test_no_file_and_enabled_true_is_400(make_client):
    client, service, started = make_client()
    res = client.post(f"/projects/{_PROJECT}/sfx/whoosh/override")
    assert res.status_code == 400
    assert "nothing to do" in res.json()["detail"]
    assert service.append_calls == [] and started == []


def test_file_with_enabled_false_is_400(make_client):
    client, _, _ = make_client()
    res = client.post(
        f"/projects/{_PROJECT}/sfx/whoosh/override",
        files={"file": ("a.mp3", b"xx", "audio/mpeg")},
        data={"enabled": "false"},
    )
    assert res.status_code == 400
    assert "conflicting" in res.json()["detail"]


def test_unknown_kind_is_422(make_client):
    client, _, _ = make_client()
    res = client.post(f"/projects/{_PROJECT}/sfx/fart/override")
    assert res.status_code == 422


def test_missing_timeline_is_400(make_client):
    client, _, _ = make_client(timeline=None)
    res = client.post(f"/projects/{_PROJECT}/sfx/whoosh/override", data={"enabled": "false"})
    assert res.status_code == 400
    assert "no timeline" in res.json()["detail"]


def test_missing_sfx_plan_is_400(make_client):
    client, _, _ = make_client(timeline=_timeline(with_sfx=False))
    res = client.post(f"/projects/{_PROJECT}/sfx/whoosh/override", data={"enabled": "false"})
    assert res.status_code == 400
    assert "no sfx_plan" in res.json()["detail"]


def test_diegetic_kind_is_rejected(make_client):
    """long_form_direction.md A8: DIEGETIC is a valid `SfxKind` enum
    member (so FastAPI's own path-param validation accepts it, unlike
    `test_unknown_kind_is_422` above), but this endpoint's one-clip-
    per-kind override model does not apply to it - it must be rejected
    with a 400, not silently wipe every shot's cue behind a single
    ungrounded clip."""
    client, service, started = make_client()
    res = client.post(
        f"/projects/{_PROJECT}/sfx/diegetic/override", data={"enabled": "false"}
    )
    assert res.status_code == 400
    assert "per-shot" in res.json()["detail"]
    assert service.append_calls == [] and started == []


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
def test_garbage_upload_is_400_at_the_endpoint(make_client):
    client, service, _ = make_client()
    res = client.post(
        f"/projects/{_PROJECT}/sfx/whoosh/override",
        files={"file": ("junk.mp3", b"<html>not audio</html>", "audio/mpeg")},
    )
    assert res.status_code == 400
    assert "junk.mp3" in res.json()["detail"]
    assert service.append_calls == []


# -- happy paths: assert on the TRANSFORMED DOCUMENT -------------------------


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
def test_valid_upload_replaces_the_kinds_clip(make_client, tmp_path):
    client, service, started = make_client()
    content = _tone_wav(tmp_path)

    res = client.post(
        f"/projects/{_PROJECT}/sfx/whoosh/override",
        files={"file": ("my_whoosh.wav", content, "audio/wav")},
    )
    assert res.status_code == 202
    assert res.json()["workflow_run_id"] == "run-1"

    # HUMAN provenance, owning exactly sfx_plan (I3).
    assert len(service.append_calls) == 1
    assert service.append_calls[0]["produced_by"] == ProducedBy.HUMAN
    assert service.append_calls[0]["owns"] == frozenset({"sfx_plan"})
    # DRAFT timeline: no self-approval.
    assert service.approved_versions == []
    # Engine resumed exactly once.
    assert started == [_PROJECT]

    clips = {c.kind: c for c in service._timeline.sfx_plan.clips}
    expected_hash = hashlib.sha256(content).hexdigest()
    whoosh = clips[SfxKind.WHOOSH]
    stinger = clips[SfxKind.STINGER]
    assert whoosh.provider == "project_sfx"
    assert whoosh.licence == "user_supplied"
    assert whoosh.track_id == f"{expected_hash}.wav"
    assert whoosh.content_hash == expected_hash
    assert "my_whoosh.wav" in whoosh.attribution
    assert stinger.content_hash == "hash-s"  # other kind untouched

    stored = settings.storage_root / _PROJECT / "sfx" / f"{expected_hash}.wav"
    assert stored.exists() and stored.read_bytes() == content


def test_disable_removes_only_that_kinds_clips_and_resumes(make_client):
    client, service, started = make_client()
    # Simulate a completed auto-selection: the flag is what makes
    # SelectSfxStep skip re-selecting - and what /sfx/retry resets.
    service._timeline.sfx_plan.selection_attempted = True

    res = client.post(f"/projects/{_PROJECT}/sfx/whoosh/override", data={"enabled": "false"})
    assert res.status_code == 202
    kinds = {c.kind for c in service._timeline.sfx_plan.clips}
    assert kinds == {SfxKind.STINGER}
    # Disable does NOT reset the attempt flag - only /sfx/retry does.
    assert service._timeline.sfx_plan.selection_attempted is True
    assert started == [_PROJECT]


def test_sfx_retry_resets_clips_and_attempt_flag(make_client):
    client, service, started = make_client()
    service._timeline.sfx_plan.selection_attempted = True
    # long_form_direction.md A8: a shot previously marked permanently
    # failed for diegetic generation must also become retriable again -
    # otherwise wiping `clips` alone leaves it stuck forever.
    service._timeline.sfx_plan.diegetic_failed_shot_ids = ["sh_01"]

    res = client.post(f"/projects/{_PROJECT}/sfx/retry")
    assert res.status_code == 202
    assert service._timeline.sfx_plan.clips == []
    assert service._timeline.sfx_plan.selection_attempted is False
    assert service._timeline.sfx_plan.diegetic_failed_shot_ids == []
    assert service.append_calls[-1]["produced_by"] == ProducedBy.HUMAN
    assert service.append_calls[-1]["owns"] == frozenset({"sfx_plan"})
    assert started == [_PROJECT]


def test_sfx_retry_with_no_sfx_plan_is_400(make_client):
    client, _, _ = make_client(timeline=_timeline(with_sfx=False))
    res = client.post(f"/projects/{_PROJECT}/sfx/retry")
    assert res.status_code == 400
    assert "no sfx_plan" in res.json()["detail"]
