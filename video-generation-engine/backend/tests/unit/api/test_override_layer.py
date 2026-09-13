"""gate_panel_overrides.md P1+P2: `panel=layer:N` override writes a
completed `GeneratedClip` under `layer_prompt_hash`; every still upload
is fit-to-canvas first; SUBJECT planes that will not chroma-key are
rejected at upload with the measured fraction.

Same FastAPI+fakes idiom as `test_focal_override_api.py`. No Postgres,
no paid provider.
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
from PIL import Image, ImageDraw

import app.api.projects as projects_module
from app.api.deps import get_repo, get_timeline_service
from app.assets.substrate_crop import fit_upload_to_canvas
from app.core.config import settings
from app.db.session import get_db
from app.renderer.parallax import ParallaxKeyGuardError, guard_subject_plane_bytes
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    CreativeContext,
    LayerRole,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
    Timeline,
    TimelineMetadata,
    TimelineStatus,
)
from app.script.styles import resolve_generation_request_format, resolve_render_format
from app.workflow.steps.render import _file_sha256
from app.workflow.steps.resolve_assets import layer_prompt_hash
from app.workflow.trigger import WorkflowTriggerResult

_PROJECT = "44444444-4444-4444-4444-444444444444"
_STYLE = "illustrated_risograph"


def _png_bytes(width: int, height: int, color: tuple[int, int, int] = (1, 2, 3)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _subject_like_png(width: int, height: int) -> bytes:
    """Flat magenta field + figure in the lower portion — inside the
    production keyed band after fit (mirrors test_parallax._subject_like_png)."""
    image = Image.new("RGB", (width, height), (0xFF, 0x00, 0xFF))
    figure_top = int(height * 0.45)
    ImageDraw.Draw(image).rectangle(
        [(0, figure_top), (width - 1, height - 1)], fill=(10, 10, 10)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _gradient_magenta_png(width: int, height: int) -> bytes:
    """Top strip magenta-ish so `sample_key_colour` succeeds; field
    gradients magenta→dark — Gemini failure mode the fraction/scatter
    guards reject."""
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        column.putpixel((0, y), (int(0xFF * (1 - t)), 0, int(0xFF * (1 - t))))
    image = column.resize((width, height), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _canvas():
    frame = resolve_render_format(_STYLE, frame_aspect=None)
    cover = resolve_generation_request_format(_STYLE, frame)
    return frame, cover


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


def _parallax_shot(shot_id: str = "sh_01") -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="a quiet room, wide shot",
        camera=Camera(movement=CameraMovement.PARALLAX),
        layers=[
            ShotLayer(role=LayerRole.BACKGROUND, prompt="an empty archival room"),
            ShotLayer(role=LayerRole.SUBJECT, prompt="a seated figure, seen from behind"),
        ],
    )


def _plain_shot(shot_id: str = "sh_plain") -> Shot:
    return Shot(id=shot_id, order=1, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt="plain")


def _timeline(*, shots: list[Shot] | None = None) -> Timeline:
    if shots is None:
        shots = [_parallax_shot()]
    scene = Scene(id="sc_01", order=0, title="S", duration_s=sum(s.duration_s for s in shots), shots=shots)
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
    bindings: dict[str, SimpleNamespace] = {}
    clips_by_hash: dict[str, SimpleNamespace] = {}

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

        async def get(self, project_id, timeline_version, shot_id):
            return bindings.get(f"{timeline_version}:{shot_id}")

    class _FakeGeneratedClipRepository:
        def __init__(self, session):
            self._session = session

        async def get_by_prompt_hash(self, prompt_hash: str):
            return clips_by_hash.get(prompt_hash)

        async def insert(self, *, prompt_hash, **kwargs):
            clip = SimpleNamespace(id=uuid.uuid4(), prompt_hash=prompt_hash, **kwargs)
            clips_by_hash[prompt_hash] = clip
            return clip

    class _FakeWorkflowRunRepository:
        def __init__(self, session):
            self._session = session

        async def get_latest(self, project_uuid):
            return SimpleNamespace(id=uuid.uuid4(), state="running")

    monkeypatch.setattr(projects_module, "AssetRepository", _FakeAssetRepository)
    monkeypatch.setattr(projects_module, "ShotBindingRepository", _FakeShotBindingRepository)
    monkeypatch.setattr(projects_module, "GeneratedClipRepository", _FakeGeneratedClipRepository)
    monkeypatch.setattr(projects_module, "WorkflowRunRepository", _FakeWorkflowRunRepository)

    # Layer panels skip vision; primary still may call it — never pay.
    async def fake_locate_subject_focal(**kwargs):
        return None

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

    return SimpleNamespace(
        build=_build,
        clips_by_hash=clips_by_hash,
        bindings=bindings,
        assets_by_hash=assets_by_hash,
    )


def _layer_hash(timeline: Timeline, shot: Shot, layer_index: int) -> str:
    return layer_prompt_hash(
        shot,
        shot.layers[layer_index],
        layer_index=layer_index,
        project_uuid=uuid.UUID(timeline.project_id),
        creative_context=timeline.creative_context,
        style=timeline.metadata.render_style,
        frame_aspect=timeline.metadata.frame_aspect,
    )


def test_layer1_override_resolves_via_render_lookup(make_client, tmp_path):
    """Done-when: POST panel=layer:1 → layer_prompt_hash + get_by_prompt_hash
    returns a completed clip at canvas size; primary binding untouched."""
    frame, _cover = _canvas()
    timeline = _timeline()
    shot = timeline.scenes[0].shots[0]
    client, service, _session, _started = make_client.build(timeline)
    content = _subject_like_png(1536, 2688)

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:1",
        files={"file": ("subject.png", content, "image/png")},
        data={"description": "hand-keyed subject"},
    )
    assert res.status_code == 202, res.text
    assert service.append_calls  # asset_locked via append_version
    assert shot.asset_locked is True

    phash = _layer_hash(timeline, shot, 1)
    clip = make_client.clips_by_hash.get(phash)
    assert clip is not None
    assert clip.status == "completed"
    assert clip.provider == "human_override"
    assert clip.model_id == "human_override"
    assert clip.cost_cents == 0
    assert clip.local_path and Path(clip.local_path).exists()
    with Image.open(clip.local_path) as image:
        assert image.size == (frame.width, frame.height)

    # Binding primary untouched — layer path must not call apply_override.
    assert make_client.bindings == {}


def test_layer0_and_layer1_write_different_hashes(make_client):
    timeline = _timeline()
    shot = timeline.scenes[0].shots[0]
    client, *_ = make_client.build(timeline)
    payloads = {
        0: _png_bytes(800, 1400, color=(10, 10, 10)),  # BACKGROUND: unkeyed
        1: _subject_like_png(800, 1400),
    }
    for index, content in payloads.items():
        res = client.post(
            f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:{index}",
            files={"file": (f"l{index}.png", content, "image/png")},
            data={"description": f"layer {index}"},
        )
        assert res.status_code == 202, res.text
    h0 = _layer_hash(timeline, shot, 0)
    h1 = _layer_hash(timeline, shot, 1)
    assert h0 != h1
    assert h0 in make_client.clips_by_hash
    assert h1 in make_client.clips_by_hash
    assert make_client.clips_by_hash[h0].local_path != make_client.clips_by_hash[h1].local_path


def test_layer_on_shot_with_no_layers_is_400(make_client):
    timeline = _timeline(shots=[_plain_shot("sh_plain")])
    client, service, *_ = make_client.build(timeline)
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_plain/override?panel=layer:1",
        files={"file": ("x.png", _png_bytes(100, 100), "image/png")},
        data={"description": "x"},
    )
    assert res.status_code == 400
    assert "no layers" in res.json()["detail"]
    assert service.append_calls == []


def test_layer2_on_two_layer_shot_is_400(make_client):
    client, service, *_ = make_client.build()
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:2",
        files={"file": ("x.png", _png_bytes(100, 100), "image/png")},
        data={"description": "x"},
    )
    assert res.status_code == 400
    assert "out of range" in res.json()["detail"]
    assert service.append_calls == []


@pytest.mark.parametrize("panel", ["subject", "background"])
def test_role_name_panels_are_400(make_client, panel):
    client, service, *_ = make_client.build()
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel={panel}",
        files={"file": ("x.png", _png_bytes(100, 100), "image/png")},
        data={"description": "x"},
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "layer:<index>" in detail
    assert service.append_calls == []


def test_video_on_layer_is_400(make_client, monkeypatch):
    """Parallax planes are stills; reject video before any lock/write."""

    async def fake_validate_video(content):
        return "mp4", 720, 1280

    def fail_image(content):
        from app.core.errors import PermanentError

        raise PermanentError("not an image")

    monkeypatch.setattr(projects_module, "validate_and_identify_image", fail_image)
    monkeypatch.setattr(projects_module, "validate_and_identify_video", fake_validate_video)
    client, service, *_ = make_client.build()
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:1",
        files={"file": ("clip.mp4", b"fake-video-bytes", "video/mp4")},
        data={"description": "x"},
    )
    assert res.status_code == 400
    assert "still image" in res.json()["detail"]
    assert service.append_calls == []
    assert make_client.clips_by_hash == {}


def test_primary_override_on_parallax_shot_still_binds_primary(make_client):
    timeline = _timeline()
    client, *_ = make_client.build(timeline)
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=primary",
        files={"file": ("p.png", _png_bytes(900, 1600, color=(70, 70, 70)), "image/png")},
        data={"description": "fallback primary"},
    )
    assert res.status_code == 202, res.text
    assert make_client.clips_by_hash == {}
    binding = make_client.bindings.get("1:sh_01")
    assert binding is not None
    assert binding.asset_id is not None
    assert binding.state == "resolved"
    assert len(make_client.assets_by_hash) == 1


def test_layer_replace_overwrites_existing_clip_in_place(make_client, tmp_path):
    frame, _ = _canvas()
    timeline = _timeline()
    shot = timeline.scenes[0].shots[0]
    phash = _layer_hash(timeline, shot, 1)
    clips_dir = tmp_path / _PROJECT / "clips"
    clips_dir.mkdir(parents=True)
    old_path = clips_dir / f"{phash}.png"
    old_bytes = _subject_like_png(frame.width, frame.height)
    old_path.write_bytes(old_bytes)
    make_client.clips_by_hash[phash] = SimpleNamespace(
        id=uuid.uuid4(),
        prompt_hash=phash,
        local_path=str(old_path),
        status="completed",
        provider="fal",
        model_id="seedream",
        cost_cents=4,
        error=None,
        prompt="old",
        project_id=uuid.UUID(_PROJECT),
        shot_id="sh_01",
    )
    client, *_ = make_client.build(timeline)
    # Distinct figure colour so replace changes file bytes.
    new_image = Image.new("RGB", (1536, 2688), (0xFF, 0x00, 0xFF))
    ImageDraw.Draw(new_image).rectangle(
        [(0, int(2688 * 0.45)), (1535, 2687)], fill=(200, 100, 50)
    )
    new_buf = io.BytesIO()
    new_image.save(new_buf, format="PNG")
    new_bytes = new_buf.getvalue()
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:1",
        files={"file": ("new.png", new_bytes, "image/png")},
        data={"description": "replace"},
    )
    assert res.status_code == 202, res.text
    assert len(make_client.clips_by_hash) == 1
    clip = make_client.clips_by_hash[phash]
    assert clip.provider == "human_override"
    assert clip.model_id == "human_override"
    assert clip.cost_cents == 0
    assert clip.error is None
    assert clip.status == "completed"
    assert Path(clip.local_path).read_bytes() != old_bytes
    with Image.open(clip.local_path) as image:
        assert image.size == (frame.width, frame.height)


def test_get_asset_panel_layer_returns_fitted_still(make_client):
    frame, _ = _canvas()
    timeline = _timeline()
    client, *_ = make_client.build(timeline)
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:1",
        files={"file": ("s.png", _subject_like_png(1536, 2688), "image/png")},
        data={"description": "x"},
    )
    assert res.status_code == 202, res.text
    got = client.get(f"/projects/{_PROJECT}/shots/sh_01/asset?panel=layer:1")
    assert got.status_code == 200, got.text
    with Image.open(io.BytesIO(got.content)) as image:
        assert image.size == (frame.width, frame.height)


def test_primary_still_upload_is_canvas_sized(make_client, tmp_path):
    """Fit applies to shipped primary/secondary paths too (§4.4)."""
    frame, _ = _canvas()
    timeline = _timeline(shots=[_plain_shot("sh_plain")])
    client, *_ = make_client.build(timeline)
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_plain/override?panel=primary",
        files={"file": ("big.png", _png_bytes(1536, 2688, color=(5, 6, 7)), "image/png")},
        data={"description": "fitted primary"},
    )
    assert res.status_code == 202, res.text
    assert len(make_client.assets_by_hash) == 1
    asset = next(iter(make_client.assets_by_hash.values()))
    with Image.open(asset.local_path) as image:
        assert image.size == (frame.width, frame.height)


def test_layer_content_hashes_are_file_bytes_not_prompt_hash(tmp_path):
    """§4.1: overwriting a plane under the same prompt_hash must change
    the fingerprint input — hash file bytes, not the lookup key."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(_png_bytes(64, 64, color=(1, 2, 3)))
    b.write_bytes(_png_bytes(64, 64, color=(9, 8, 7)))
    ha = _file_sha256(a)
    hb = _file_sha256(b)
    assert ha != hb
    # Same prompt_hash-shaped key, different bytes → different fingerprint inputs.
    prompt_hash = "same-lookup-key"
    assert ha != prompt_hash and hb != prompt_hash
    assert hashlib.sha256(a.read_bytes()).hexdigest() == ha


# ---------------------------------------------------------------------------
# P2 — reject a SUBJECT plane that will not chroma-key, at upload.
# ---------------------------------------------------------------------------


def _fit_like_override(content: bytes) -> bytes:
    """Same fit the upload path applies — assert guards on fitted bytes."""
    frame, cover = _canvas()
    return fit_upload_to_canvas(
        content,
        cover_width=cover.width,
        cover_height=cover.height,
        canvas_width=frame.width,
        canvas_height=frame.height,
    )


def test_gradient_magenta_subject_is_400_with_measured_fraction(make_client):
    """Done-when reject: Gemini-shaped gradient field fails at upload;
    detail carries the production measured fraction."""
    _frame, cover = _canvas()
    content = _gradient_magenta_png(cover.width, cover.height)
    fitted = _fit_like_override(content)
    with pytest.raises(ParallaxKeyGuardError) as expected:
        guard_subject_plane_bytes(
            fitted, shot_id="sh_01", layer_role=LayerRole.SUBJECT.value
        )

    client, service, *_ = make_client.build()
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:1",
        files={"file": ("gradient.png", content, "image/png")},
        data={"description": "bad key"},
    )
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert detail == str(expected.value)
    assert "0." in detail or "keyed fraction" in detail or "scatter" in detail
    assert service.append_calls == []
    assert make_client.clips_by_hash == {}


def test_clean_subject_like_plane_is_accepted(make_client):
    """Done-when accept: flat magenta + figure in band → 202 + clip."""
    frame, _ = _canvas()
    timeline = _timeline()
    shot = timeline.scenes[0].shots[0]
    client, service, *_ = make_client.build(timeline)
    content = _subject_like_png(1536, 2688)
    # Production helper must also accept the fitted bytes.
    guard_subject_plane_bytes(_fit_like_override(content))

    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:1",
        files={"file": ("subject.png", content, "image/png")},
        data={"description": "clean subject"},
    )
    assert res.status_code == 202, res.text
    assert service.append_calls
    phash = _layer_hash(timeline, shot, 1)
    clip = make_client.clips_by_hash.get(phash)
    assert clip is not None
    assert clip.status == "completed"
    with Image.open(clip.local_path) as image:
        assert image.size == (frame.width, frame.height)


def test_gradient_on_background_layer_is_not_key_guarded(make_client):
    """BACKGROUND (`layer:0`) is unkeyed — gradient still 202."""
    client, service, *_ = make_client.build()
    content = _gradient_magenta_png(800, 1400)
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:0",
        files={"file": ("bg.png", content, "image/png")},
        data={"description": "bg gradient"},
    )
    assert res.status_code == 202, res.text
    assert service.append_calls
    assert make_client.clips_by_hash


def test_primary_solid_colour_still_202(make_client):
    """Key guard is SUBJECT-plane only — primary solid colour still ships."""
    timeline = _timeline(shots=[_plain_shot("sh_plain")])
    client, service, *_ = make_client.build(timeline)
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_plain/override?panel=primary",
        files={"file": ("p.png", _png_bytes(900, 1600, color=(70, 70, 70)), "image/png")},
        data={"description": "solid primary"},
    )
    assert res.status_code == 202, res.text
    assert service.append_calls
    assert make_client.clips_by_hash == {}
    assert make_client.assets_by_hash


def test_rejected_subject_does_not_lock_or_write_clip(make_client):
    """Mirror video-on-layer 400: no append_version, empty clip repo."""
    client, service, *_ = make_client.build()
    # Uniform non-cutout plate: sample_key_colour reads the field itself,
    # so keyed_fraction is ~1.0 ("ate the subject") — still a guard reject.
    content = _png_bytes(1536, 2688, color=(10, 10, 10))
    fitted = _fit_like_override(content)
    with pytest.raises(ParallaxKeyGuardError) as expected:
        guard_subject_plane_bytes(
            fitted, shot_id="sh_01", layer_role=LayerRole.SUBJECT.value
        )
    res = client.post(
        f"/projects/{_PROJECT}/shots/sh_01/override?panel=layer:1",
        files={"file": ("dark.png", content, "image/png")},
        data={"description": "no magenta"},
    )
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == str(expected.value)
    assert service.append_calls == []
    assert make_client.clips_by_hash == {}
    timeline = _timeline()
    assert timeline.scenes[0].shots[0].asset_locked is False
