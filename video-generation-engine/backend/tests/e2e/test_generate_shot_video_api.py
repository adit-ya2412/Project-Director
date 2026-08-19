"""HTTP-level proof of Track A's A6 (motion_new_styles_and_long_form_
videos.md, 2026-08-18): `POST`/`GET /projects/{id}/shots/{shot_id}/generate/video`.

Project setup (script upload, render trigger) runs under DRY_RUN as
every other e2e test does - real image/narration/music generation is not
what this file is testing. Video generation itself has no DRY_RUN fake
(a pre-existing gap the endpoint's own docstring names - `_resolve_one_
fake` never generates video at all), so `settings.dry_run` is flipped to
`False` for just the video calls, with `FalImageProvider`/`FalVideoProvider`
monkeypatched to local fakes - the same pattern `tests/integration/
test_resolve_assets_generation_real.py` already uses one layer down,
exercised here through the real HTTP surface instead.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import projects as projects_module
from app.core.config import settings
from app.main import app
from app.providers.base import ImageResult, VideoJobStatus

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


class _FakeImageProvider:
    name = "fal_image"

    def __init__(self, hosted_url: str = "http://fal.example/keyframe.jpg") -> None:
        self._hosted_url = hosted_url
        self.calls: list = []

    async def generate(self, request):
        self.calls.append(request)
        return ImageResult(
            content=b"keyframe-bytes", content_type="image/jpeg", hosted_url=self._hosted_url
        )


class _FakeVideoProvider:
    name = "fal_video"

    def __init__(self, poll_result: VideoJobStatus | None = None) -> None:
        self.submit_calls: list = []
        self._poll_result = poll_result or VideoJobStatus(
            state="completed", content=b"fake-video-bytes", content_type="video/mp4"
        )

    async def submit(self, request) -> str:
        self.submit_calls.append(request)
        return "job-e2e-1"

    async def poll(self, job_id: str) -> VideoJobStatus:
        return self._poll_result


def _create_and_render(client: TestClient) -> tuple[str, dict]:
    project_id = client.post(
        "/api/v1/projects", json={"name": "generate video endpoint test"}
    ).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})
    awaiting = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    return project_id, awaiting


def test_post_rejects_under_dry_run(client):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    resp = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert resp.status_code == 400
    assert "DRY_RUN" in resp.json()["detail"]


def test_get_rejects_under_dry_run_too(client):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    resp = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert resp.status_code == 400
    assert "DRY_RUN" in resp.json()["detail"]


def test_get_404s_with_a_real_provider_configured_but_nothing_in_flight(client, monkeypatch):
    """A GET must never have the side effect of a fresh, paid submission
    - proven here by a video provider that would fail the test (via its
    own `submit_calls`/return shape) if `submit` were ever actually
    called; `poll_video_job` itself never even reaches `poll()` when
    nothing is in flight, which this 404 is the direct evidence of."""
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(projects_module, "FalVideoProvider", lambda: _FakeVideoProvider())

    resp = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert resp.status_code == 404


def test_post_then_get_submits_and_resolves_a_video(client, monkeypatch):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    monkeypatch.setattr(settings, "dry_run", False)
    image_provider = _FakeImageProvider()
    video_provider = _FakeVideoProvider()
    monkeypatch.setattr(projects_module, "FalImageProvider", lambda: image_provider)
    monkeypatch.setattr(projects_module, "FalVideoProvider", lambda: video_provider)

    post_resp = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert post_resp.status_code == 202, post_resp.text
    post_body = post_resp.json()
    assert post_body["status"] == "pending"
    assert post_body["job_id"] == "job-e2e-1"
    assert len(video_provider.submit_calls) == 1
    assert len(image_provider.calls) == 1  # the blocking keyframe generation

    get_resp = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert get_resp.status_code == 200, get_resp.text
    get_body = get_resp.json()
    assert get_body["status"] == "completed"
    assert get_body["clip_id"] == post_body["clip_id"]

    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    shot_progress = next(s for s in progress["shots"] if s["shot_id"] == shot_id)
    assert shot_progress["state"] == "generated"


def test_post_is_idempotent_while_a_job_is_still_in_flight(client, monkeypatch):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    monkeypatch.setattr(settings, "dry_run", False)
    image_provider = _FakeImageProvider()
    video_provider = _FakeVideoProvider(poll_result=VideoJobStatus(state="in_progress"))
    monkeypatch.setattr(projects_module, "FalImageProvider", lambda: image_provider)
    monkeypatch.setattr(projects_module, "FalVideoProvider", lambda: video_provider)

    first = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert first.status_code == 202, first.text

    second = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert second.status_code == 202, second.text
    assert second.json()["status"] == "pending"
    # A second POST while still in flight must never resubmit (M7's own
    # never-resubmit invariant) - only the first call actually reached
    # the video provider.
    assert len(video_provider.submit_calls) == 1

    poll = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert poll.status_code == 200, poll.text
    assert poll.json()["status"] == "pending"


def test_a_failed_job_is_reported_and_bindings_reflect_it(client, monkeypatch):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    monkeypatch.setattr(settings, "dry_run", False)
    image_provider = _FakeImageProvider()
    video_provider = _FakeVideoProvider(
        poll_result=VideoJobStatus(state="failed", error="model overloaded")
    )
    monkeypatch.setattr(projects_module, "FalImageProvider", lambda: image_provider)
    monkeypatch.setattr(projects_module, "FalVideoProvider", lambda: video_provider)

    client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    poll = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate/video")
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["status"] == "failed"
    assert body["error"] == "model overloaded"
