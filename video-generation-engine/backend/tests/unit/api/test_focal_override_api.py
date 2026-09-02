"""long_form_direction.md A13: `POST /shots/{shot_id}/override` used to
bypass focal entirely - a human-uploaded photo aimed its Ken Burns move at
the geometric centre, a framing nobody ever examined. This proves the two
halves added to that endpoint:

A13a - a vision call, made and persisted exactly like `resolve_assets.py`
does for a searched asset, but only when no sidecar exists yet for this
content hash (never re-paying for a repeat upload), and never blocking the
upload on failure.

A13b - a human-supplied `focal_x`/`focal_y` always outranks a vision
answer for the same hash, and a half-answer (one coordinate only, or a
non-finite value) is a 400, not a silent fall-through.

Same idiom as `test_sfx_override_api.py`/`test_clear_sfx_cue_api.py`
(RV10/RV3): real FastAPI routing, every database dependency overridden
with a fake at `app.api.projects`'s own namespace (`AssetRepository`,
`ShotBindingRepository`, `WorkflowRunRepository`, `start_workflow_run`).
`locate_subject_focal` is faked the same way - this suite is about the
endpoint's own branching (which sidecar gets written, when the provider
gets called), not about `locate_subject_focal`'s own internals (covered
elsewhere). No Postgres; safe under `--noconftest`. `settings.storage_root`
is pointed at `tmp_path`, and the sidecar files this test reads back are
real - written by the real `app.assets.focal` functions, not faked.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import app.api.projects as projects_module
from app.api.deps import get_repo, get_timeline_service
from app.assets.focal import FOCAL_SOURCE_HUMAN, FOCAL_SOURCE_VISION, read_focal_sidecar
from app.core.config import settings
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

_PROJECT = "33333333-3333-3333-3333-333333333333"


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeRepo:
    async def get(self, project_id):
        return object()  # only None matters to _get_project_or_404


class _FakeSession:
    def __init__(self):
        self.flushed = 0
        self.committed = 0

    async def flush(self):
        self.flushed += 1

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


def _timeline() -> Timeline:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    scene = Scene(id="sc_01", order=0, title="S", duration_s=3.0, shots=[shot])
    return Timeline(
        timeline_id="t1",
        project_id=_PROJECT,
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,  # DRAFT -> join-existing-run, no re-approve
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


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

    assets_by_hash: dict[str, SimpleNamespace] = {}

    class _FakeAssetRepository:
        def __init__(self, session):
            self._session = session

        async def get_by_content_hash(self, project_id, content_hash):
            return assets_by_hash.get(content_hash)

        async def insert(self, *, content_hash, **kwargs):
            asset = SimpleNamespace(id=uuid.uuid4(), content_hash=content_hash, **kwargs)
            assets_by_hash[content_hash] = asset
            return asset

    monkeypatch.setattr(projects_module, "AssetRepository", _FakeAssetRepository)

    class _FakeShotBindingRepository:
        def __init__(self, session):
            self._session = session

        async def get_or_create_pending(self, project_id, timeline_version, shot_id):
            return SimpleNamespace(
                asset_id=None,
                clip_id=None,
                state="pending",
                rung=None,
                last_error=None,
                secondary_asset_id=None,
                secondary_clip_id=None,
                secondary_state=None,
                secondary_last_error=None,
            )

    monkeypatch.setattr(projects_module, "ShotBindingRepository", _FakeShotBindingRepository)

    class _FakeWorkflowRunRepository:
        def __init__(self, session):
            self._session = session

        async def get_latest(self, project_uuid):
            return SimpleNamespace(id=uuid.uuid4(), state="running")

    monkeypatch.setattr(projects_module, "WorkflowRunRepository", _FakeWorkflowRunRepository)

    vision_calls: list[dict] = []
    vision_script: list[object] = []

    async def fake_locate_subject_focal(
        *, provider, llm_call_repo, project_id, image, image_content_type, shot_id=None
    ):
        vision_calls.append({"shot_id": shot_id, "image_content_type": image_content_type})
        if not vision_script:
            return None
        result = vision_script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(projects_module, "locate_subject_focal", fake_locate_subject_focal)

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

    return SimpleNamespace(build=_build, vision_calls=vision_calls, vision_script=vision_script)


def _sidecar(project_id: str, tmp_path, content: bytes):
    import hashlib

    content_hash = hashlib.sha256(content).hexdigest()
    assets_dir = tmp_path / project_id / "assets"
    return read_focal_sidecar(assets_dir, content_hash), content_hash, assets_dir


# -- A13a: vision path --------------------------------------------------


def test_upload_with_no_coords_calls_vision_and_persists_it(make_client, tmp_path):
    make = make_client
    client, service, _session, _started = make.build()
    make.vision_script.append((0.2, 0.75))
    content = _png_bytes((1, 2, 3))

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("portrait.png", content, "image/png")},
        data={"description": "a portrait, subject in the upper third"},
    )
    assert res.status_code == 202, res.text
    assert len(make.vision_calls) == 1

    focal, _hash, _dir = _sidecar(_PROJECT, tmp_path, content)
    assert focal == (0.2, 0.75)


def test_vision_sidecar_records_the_vision_source(make_client, tmp_path):
    import json

    make = make_client
    client, *_ = make.build()
    make.vision_script.append((0.3, 0.4))
    content = _png_bytes((4, 5, 6))

    client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("a.png", content, "image/png")},
        data={"description": "x"},
    )
    _focal, content_hash, assets_dir = _sidecar(_PROJECT, tmp_path, content)
    payload = json.loads((assets_dir / f"{content_hash}.focal.json").read_text())
    assert payload["focal_source"] == FOCAL_SOURCE_VISION


# -- vision failure degrades gracefully, never blocks the upload --------


@pytest.mark.parametrize("failure", [None, RuntimeError("boom")], ids=["none_answer", "raises"])
def test_vision_failure_still_succeeds_with_no_sidecar(make_client, tmp_path, failure):
    make = make_client
    client, service, _session, _started = make.build()
    if failure is not None:
        make.vision_script.append(failure)
    # else: leave vision_script empty -> fake returns None, the "no usable
    # answer" case `locate_subject_focal` itself already returns.
    content = _png_bytes((7, 8, 9))

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("b.png", content, "image/png")},
        data={"description": "x"},
    )
    assert res.status_code == 202, res.text  # upload succeeds regardless
    assert len(make.vision_calls) == 1

    focal, _hash, assets_dir = _sidecar(_PROJECT, tmp_path, content)
    assert focal is None  # no sidecar written - render falls back to centre, logged there
    content_hash = _hash
    assert not (assets_dir / f"{content_hash}.focal.json").exists()


# -- repeat upload never re-pays for a vision call -----------------------


def test_repeat_upload_of_identical_bytes_does_not_recall_vision(make_client, tmp_path):
    make = make_client
    content = _png_bytes((11, 22, 33))

    client, *_ = make.build()
    make.vision_script.append((0.6, 0.6))
    first = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("c.png", content, "image/png")},
        data={"description": "x"},
    )
    assert first.status_code == 202
    assert len(make.vision_calls) == 1

    # Same bytes, second override call (e.g. re-uploading the same photo).
    second = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("c-again.png", content, "image/png")},
        data={"description": "x, again"},
    )
    assert second.status_code == 202
    assert len(make.vision_calls) == 1  # NOT called a second time

    focal, _hash, _dir = _sidecar(_PROJECT, tmp_path, content)
    assert focal == (0.6, 0.6)  # the original vision answer, untouched


# -- A13b: explicit human coordinates ------------------------------------


def test_explicit_coords_are_used_verbatim_and_skip_vision(make_client, tmp_path):
    import json

    make = make_client
    client, *_ = make.build()
    content = _png_bytes((44, 55, 66))

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("d.png", content, "image/png")},
        data={"description": "x", "focal_x": "0.15", "focal_y": "0.9"},
    )
    assert res.status_code == 202, res.text
    assert make.vision_calls == []  # human answer means never asking vision

    focal, content_hash, assets_dir = _sidecar(_PROJECT, tmp_path, content)
    assert focal == (0.15, 0.9)
    payload = json.loads((assets_dir / f"{content_hash}.focal.json").read_text())
    assert payload["focal_source"] == FOCAL_SOURCE_HUMAN


def test_explicit_coords_outrank_an_existing_vision_sidecar(make_client, tmp_path):
    make = make_client
    content = _png_bytes((77, 88, 99))

    client, *_ = make.build()
    make.vision_script.append((0.5, 0.5))
    client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("e.png", content, "image/png")},
        data={"description": "x"},
    )
    focal_before, _hash, _dir = _sidecar(_PROJECT, tmp_path, content)
    assert focal_before == (0.5, 0.5)

    # A human now corrects the same photo's framing explicitly. Must
    # overwrite the vision sidecar, not merely leave it as the older
    # "already resolved" answer.
    client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("e-again.png", content, "image/png")},
        data={"description": "x", "focal_x": "0.05", "focal_y": "0.95"},
    )
    focal_after, _hash, _dir = _sidecar(_PROJECT, tmp_path, content)
    assert focal_after == (0.05, 0.95)
    assert len(make.vision_calls) == 1  # the vision call from the FIRST request only


# -- invalid coordinates: a clear 4xx, never a silent centre -------------


def test_only_focal_x_supplied_is_400(make_client):
    make = make_client
    client, service, _session, started = make.build()
    content = _png_bytes((1, 1, 1))

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("f.png", content, "image/png")},
        data={"description": "x", "focal_x": "0.3"},
    )
    assert res.status_code == 400
    assert "focal_x" in res.json()["detail"] and "focal_y" in res.json()["detail"]
    # Rejected before anything else happened.
    assert service.append_calls == [] and started == [] and make.vision_calls == []


def test_only_focal_y_supplied_is_400(make_client):
    make = make_client
    client, *_ = make.build()
    content = _png_bytes((2, 2, 2))

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("g.png", content, "image/png")},
        data={"description": "x", "focal_y": "0.3"},
    )
    assert res.status_code == 400


def test_out_of_range_but_finite_coords_are_clamped_not_rejected(make_client, tmp_path):
    """`normalize_focal`'s own existing behaviour (reused verbatim, not a
    new bounds check per this task's own instruction): a value outside
    0..1 is clamped, not refused with a 4xx."""
    make = make_client
    client, *_ = make.build()
    content = _png_bytes((3, 3, 3))

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override",
        files={"file": ("h.png", content, "image/png")},
        data={"description": "x", "focal_x": "1.5", "focal_y": "-0.2"},
    )
    assert res.status_code == 202, res.text
    focal, _hash, _dir = _sidecar(_PROJECT, tmp_path, content)
    assert focal == (1.0, 0.0)
