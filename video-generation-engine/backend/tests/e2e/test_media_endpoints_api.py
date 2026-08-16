"""HTTP-level proof of F0b (2026-08-16): `GET /projects/{id}/shots/{shot_id}
/asset` and `GET /projects/{id}/thumbnail` - the two endpoints that
finally serve real image bytes a browser can display, instead of a
server filesystem path. DRY_RUN + fakes throughout, same premise as
tests/e2e/test_skeleton.py.

The underlying cache mechanics (mtime invalidation, ffmpeg call counting)
are proven directly against real files in
tests/integration/test_thumbnails.py; this file proves the HTTP
CONTRACT - status codes, content-types, and F1's source-priority order -
over the real FastAPI routes.
"""

import asyncio
import io
import uuid as uuid_module

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.clock import utcnow
from app.core.config import settings
from app.db.session import async_session_factory
from app.main import app
from app.models.generated_clip import GeneratedClipModel
from app.models.shot_binding import ShotBindingModel
from app.renderer.slideshow import RenderSettings, render_timeline
from app.schemas.timeline import (
    Camera,
    CameraMovement,
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

_SCRIPT = (
    "Germany possessed abundant coal, fueling its factories and its "
    "ambitions. But it lacked one vital resource: oil, and that "
    "dependency would shape the war to come. That single gap in "
    "resources would drive strategic decisions with consequences the "
    "world still remembers."
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


def _create_and_render(client: TestClient) -> tuple[str, dict]:
    project_id = client.post("/api/v1/projects", json={"name": "media endpoints test"}).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})
    awaiting = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    return project_id, awaiting


def test_shot_asset_404s_before_any_timeline_exists(client):
    project_id = client.post("/api/v1/projects", json={"name": "no timeline yet"}).json()["id"]
    resp = client.get(f"/api/v1/projects/{project_id}/shots/whatever/asset")
    assert resp.status_code == 404


def test_shot_asset_404s_for_a_shot_id_not_in_the_timeline(client):
    project_id, _awaiting = _create_and_render(client)
    resp = client.get(f"/api/v1/projects/{project_id}/shots/not-a-real-shot/asset")
    assert resp.status_code == 404


def test_shot_asset_serves_a_real_decodable_image(client):
    """The free search pass (M6.5, A5) already resolved every shot before
    the approval gate - `GET /shots/{id}/asset` must be able to display
    what a human is being asked to approve."""
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    resp = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/asset")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(resp.content)) as image:
        image.verify()  # a real, structurally valid image - not a path or an error page


def test_shot_asset_sets_no_cache_so_a_regenerate_is_never_served_stale(client):
    """Task 7 (2026-08-16): this URL is stable per shot, but the bytes
    behind it are not - a regenerate rebinds the same shot to a different
    underlying file. Without `Cache-Control`, a browser may apply
    heuristic freshness and never even ask the server again after the
    first load, which is exactly the "stale picture" bug this closes.
    `no-cache` forces revalidation on every load; `ETag`/`Last-Modified`
    (set by Starlette's `FileResponse` from the file's own current
    `os.stat`, not a fixed value) are what that revalidation actually
    checks against."""
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    resp = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/asset")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers.get("etag")  # present and non-empty - real revalidation is possible
    assert resp.headers.get("last-modified")


def test_shot_asset_etag_and_bytes_change_after_an_override_at_the_same_url(client):
    """The actual end-to-end proof behind Task 7, not just that headers
    are present: the SAME URL, after a human swaps this shot's picture,
    serves DIFFERENT bytes and a DIFFERENT `ETag` - so a client that
    revalidates (as `no-cache` now forces) cannot mistake the new picture
    for the old one."""
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    before = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/asset")
    assert before.status_code == 200

    override_resp = trigger_and_wait(
        client,
        "post",
        f"/api/v1/projects/{project_id}/shots/{shot_id}/override",
        files={"file": ("override.png", _override_png_bytes(), "image/png")},
        data={"description": "a different photo for this exact shot"},
    )
    assert override_resp["status"] in ("awaiting_approval", "completed"), override_resp.get("error")

    after = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/asset")
    assert after.status_code == 200
    assert after.content != before.content
    assert after.headers["etag"] != before.headers["etag"]


def _override_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), color=(200, 50, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_thumbnail_404s_when_nothing_is_available_yet(client):
    project_id = client.post("/api/v1/projects", json={"name": "brand new"}).json()["id"]
    resp = client.get(f"/api/v1/projects/{project_id}/thumbnail")
    assert resp.status_code == 404


def test_thumbnail_falls_back_to_the_first_shots_asset_before_any_video_exists(client):
    """F1, source (2): a project sitting at the approval gate has no
    video yet, but the free search pass already gave it a real bound
    image - exactly the moment F1 says a thumbnail is wanted most."""
    project_id, _awaiting = _create_and_render(client)

    resp = client.get(f"/api/v1/projects/{project_id}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(resp.content)) as image:
        image.verify()


def test_thumbnail_prefers_the_final_video_once_one_exists(client):
    """F1, source (1): once `final.mp4` exists it wins over the shot-asset
    fallback, even though both are technically available."""
    project_id, _awaiting = _create_and_render(client)
    completed = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert completed["status"] == "completed", completed.get("error")

    resp = client.get(f"/api/v1/projects/{project_id}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(resp.content)) as image:
        image.verify()
    with Image.open(io.BytesIO(resp.content)) as image:
        # A video-source thumbnail is the raw extracted frame (F1 never
        # mentions resizing this case, unlike the shot-asset fallback) -
        # so it comes back at the render's own resolution.
        assert image.size == (settings.render_width, settings.render_height)


def _seed_video_bound_shot(project_id: str, video_path) -> int:
    """A shot whose binding points at a GENERATED CLIP that is itself a
    VIDEO (rung 5, image-to-video) rather than a still image - the case
    `GET /shots/{id}/asset` has to turn into a displayable frame rather
    than streaming raw video bytes to an `<img>` tag."""
    shot = Shot(
        id="sh_video",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    scene = Scene(id="sc_video", order=0, title="Scene", duration_s=3.0, shots=[shot])

    async def _seed() -> int:
        async with async_session_factory() as session:
            service = TimelineService(session)
            await service.create_initial(project_id, script="unused")

            def _fill(base: Timeline) -> Timeline:
                base.scenes = [scene]
                base.metadata.total_duration_s = 3.0
                return base

            appended = await service.append_version(
                project_id,
                produced_by=ProducedBy.ASSET_PLANNER,
                transform=_fill,
                owns=frozenset({"scenes", "metadata"}),
            )

            clip = GeneratedClipModel(
                project_id=uuid_module.UUID(project_id),
                shot_id="sh_video",
                provider="fake_video",
                model_id="fake-video-model",
                prompt="a test prompt",
                prompt_hash="test-prompt-hash",
                local_path=str(video_path),
                status="completed",
            )
            session.add(clip)
            await session.flush()

            session.add(
                ShotBindingModel(
                    project_id=uuid_module.UUID(project_id),
                    timeline_version=appended.version,
                    shot_id="sh_video",
                    state="generated",
                    clip_id=clip.id,
                )
            )
            await session.commit()
            return appended.version

    return asyncio.run(_seed())


def test_shot_asset_extracts_a_frame_from_a_video_bound_generated_clip(client, tmp_path):
    """The renderer already knows how to turn one static image into a
    silent video (`render_timeline`) - reused here purely to synthesise a
    real, valid MP4 without needing a real fal.ai video generation call."""
    project_id = client.post("/api/v1/projects", json={"name": "video clip shot"}).json()["id"]

    still_path = tmp_path / "still.png"
    Image.new("RGB", (640, 360), color=(50, 60, 70)).save(still_path, format="PNG")

    video_path = tmp_path / "generated.mp4"
    render_settings = RenderSettings(
        width=320,
        height=240,
        fps=24,
        pixel_format="yuv420p",
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
    )
    shot = Shot(
        id="sh_video",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    timeline_for_render = Timeline(
        timeline_id="t1",
        project_id=project_id,
        version=1,
        produced_by=ProducedBy.ASSET_PLANNER,
        created_at=utcnow(),
        scenes=[Scene(id="sc_video", order=0, title="Scene", duration_s=2.0, shots=[shot])],
    )
    asyncio.run(
        render_timeline(
            timeline_for_render,
            {"sh_video": still_path},
            render_settings,
            video_path,
            work_dir=tmp_path / "work",
        )
    )
    assert video_path.exists()

    _seed_video_bound_shot(project_id, video_path)

    resp = client.get(f"/api/v1/projects/{project_id}/shots/sh_video/asset")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(resp.content)) as image:
        image.verify()
    with Image.open(io.BytesIO(resp.content)) as image:
        assert image.size == (320, 240)  # the synthesised clip's own dimensions
