"""docs/plans/baked_in_letterbox.md §5.2: `override_shot_asset` strips a
baked-in pillarbox from a human-uploaded VIDEO immediately after
`media_type` is decided, before either downstream write (the layer clip
write or the plain asset write) - never at a write site, because both
consume the same `content` local and this endpoint's persisted
`content_hash` must describe the CORRECTED bytes from birth (plan §2's
manual-repair incident).

Same FastAPI+fakes idiom as `test_override_layer.py`, trimmed to the
non-layer (primary) video path this plan's crop actually reaches - a
video on a LAYER panel is already rejected with a 400 before this code
runs (`test_video_on_layer_is_400`), so this call site's crop can only
ever see the plain-asset write in practice.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import app.api.projects as projects_module
from app.api.deps import get_repo, get_timeline_service
from app.core.config import settings
from app.db.session import get_db
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    CreativeContext,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineMetadata,
    TimelineStatus,
)
from app.workflow.trigger import WorkflowTriggerResult
from tests.media_fixtures import make_real_clip

_PROJECT = "55555555-5555-5555-5555-555555555555"
_STYLE = "illustrated_risograph"


def _plain_shot(shot_id: str = "sh_video") -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="plain",
        camera=Camera(movement=CameraMovement.STATIC),
    )


def _timeline() -> Timeline:
    shot = _plain_shot()
    scene = Scene(id="sc_01", order=0, title="S", duration_s=shot.duration_s, shots=[shot])
    return Timeline(
        timeline_id="t1",
        project_id=_PROJECT,
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
        metadata=TimelineMetadata(render_style=_STYLE),
        creative_context=CreativeContext(),
    )


class _FakeRepo:
    async def get(self, project_id):
        return object()


class _FakeSession:
    def __init__(self):
        self.flushed = 0
        self.committed = 0

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.committed += 1


class _FakeTimelineService:
    def __init__(self, timeline: Timeline):
        self._timeline = timeline
        self.append_calls: list[dict] = []

    async def get_active(self, project_id):
        return self._timeline

    async def append_version(self, project_id, *, produced_by, transform, owns):
        new = transform(self._timeline)
        self.append_calls.append({"produced_by": produced_by, "owns": frozenset(owns)})
        self._timeline = new
        return new

    async def approve(self, project_id, version):
        pass


@pytest.fixture()
def make_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)

    async def fake_start(project_id, session, background_tasks):
        return WorkflowTriggerResult(
            project_id=project_id,
            workflow_run_id="run-1",
            state="started",
            joined_existing_run=False,
        )

    monkeypatch.setattr(projects_module, "start_workflow_run", fake_start)

    assets_by_hash: dict[str, SimpleNamespace] = {}
    bindings: dict[str, SimpleNamespace] = {}

    class _FakeAssetRepository:
        def __init__(self, session):
            self._session = session

        async def get_by_content_hash(self, project_id, content_hash):
            return assets_by_hash.get(content_hash)

        async def insert(self, *, content_hash, **kwargs):
            asset = SimpleNamespace(id=uuid.uuid4(), content_hash=content_hash, **kwargs)
            assets_by_hash[content_hash] = asset
            return asset

    class _FakeShotBindingRepository:
        def __init__(self, session):
            self._session = session

        async def get_or_create_pending(self, project_id, timeline_version, shot_id):
            key = f"{timeline_version}:{shot_id}"
            if key not in bindings:
                bindings[key] = SimpleNamespace(
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
            return bindings[key]

    class _FakeWorkflowRunRepository:
        def __init__(self, session):
            self._session = session

        async def get_latest(self, project_uuid):
            return SimpleNamespace(id=uuid.uuid4(), state="running")

    monkeypatch.setattr(projects_module, "AssetRepository", _FakeAssetRepository)
    monkeypatch.setattr(projects_module, "ShotBindingRepository", _FakeShotBindingRepository)
    monkeypatch.setattr(projects_module, "WorkflowRunRepository", _FakeWorkflowRunRepository)

    async def fake_locate_subject_focal(**kwargs):
        return None

    monkeypatch.setattr(projects_module, "locate_subject_focal", fake_locate_subject_focal)

    def _build():
        service = _FakeTimelineService(_timeline())
        session = _FakeSession()
        app = FastAPI()
        app.include_router(projects_module.router)

        async def _override_db():
            yield session

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_repo] = lambda: _FakeRepo()
        app.dependency_overrides[get_timeline_service] = lambda: service
        return TestClient(app), service, session

    return SimpleNamespace(build=_build, assets_by_hash=assets_by_hash, bindings=bindings)


def _post_video(client, content: bytes):
    return client.post(
        f"/projects/{_PROJECT}/shots/sh_video/override?panel=primary",
        files={"file": ("clip.mp4", content, "video/mp4")},
        data={"description": "video override"},
    )


def _fake_strip(calls: list[bytes], marker: bytes = b"CROPPED_MARKER"):
    async def fake_strip(content, *, ffmpeg_binary, ffprobe_binary):
        calls.append(content)
        return content + marker

    return fake_strip


def test_video_override_calls_letterbox_crop_before_the_hash_is_taken(
    make_client, monkeypatch, tmp_path
):
    """The ordering property itself (plan §2/§3): the persisted asset's
    `content_hash` and on-disk bytes must both reflect the CROPPED bytes,
    not the raw upload - proving the crop ran before the hash, not after,
    and before the write, not instead of feeding it."""
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", True)
    monkeypatch.setattr(projects_module, "strip_baked_in_letterbox", _fake_strip(calls))

    client, _service, _session = make_client.build()
    clip_path = tmp_path / "clip.mp4"
    make_real_clip(clip_path, duration_s=1.0, width=64, height=64)
    raw_content = clip_path.read_bytes()

    res = _post_video(client, raw_content)
    assert res.status_code == 202, res.text

    assert calls == [raw_content]  # called once, with the RAW upload bytes
    assert len(make_client.assets_by_hash) == 1
    asset = next(iter(make_client.assets_by_hash.values()))
    expected = raw_content + b"CROPPED_MARKER"
    assert asset.content_hash == hashlib.sha256(expected).hexdigest()
    persisted = Path(asset.local_path).read_bytes()
    assert persisted == expected
    assert hashlib.sha256(persisted).hexdigest() == asset.content_hash


def test_video_override_is_not_called_for_a_still_upload(make_client, monkeypatch, tmp_path):
    """Only `media_type == 'video'` should ever reach the crop - an image
    override must never pay for a video subprocess pipeline."""
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", True)
    monkeypatch.setattr(projects_module, "strip_baked_in_letterbox", _fake_strip(calls))

    client, _service, _session = make_client.build()
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1600), color=(5, 6, 7)).save(buffer, format="PNG")
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_video/override?panel=primary",
        files={"file": ("still.png", buffer.getvalue(), "image/png")},
        data={"description": "still override"},
    )
    assert res.status_code == 202, res.text
    assert calls == []


def test_kill_switch_makes_the_video_override_a_byte_identical_no_op(
    make_client, monkeypatch, tmp_path
):
    """`letterbox_crop_enabled = False` must make this call site a
    byte-identical no-op - the persisted asset must hash and equal the
    RAW upload, and the crop function must never even be invoked."""
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", False)
    monkeypatch.setattr(projects_module, "strip_baked_in_letterbox", _fake_strip(calls))

    client, _service, _session = make_client.build()
    clip_path = tmp_path / "clip.mp4"
    make_real_clip(clip_path, duration_s=1.0, width=64, height=64)
    raw_content = clip_path.read_bytes()

    res = _post_video(client, raw_content)
    assert res.status_code == 202, res.text

    assert calls == []
    asset = next(iter(make_client.assets_by_hash.values()))
    assert asset.content_hash == hashlib.sha256(raw_content).hexdigest()
    assert Path(asset.local_path).read_bytes() == raw_content
