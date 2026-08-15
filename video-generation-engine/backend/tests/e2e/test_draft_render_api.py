"""HTTP-level proof of the draft render endpoint (M8 step 6, "always
render a fast draft first"): `POST /{project_id}/render/draft` and
`GET /{project_id}/video/draft`, entirely on fakes, zero API keys - same
DRY_RUN premise as test_skeleton.py.

The key property under test is that a draft is available BEFORE approval
(the pre-approval search pass already resolves what it can - M6.5), and
that it never disturbs the project's own `status`/`video_path`, which
only `POST /render`'s own workflow progression controls.
"""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

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


def _ffprobe_dimensions(path) -> tuple[int, int]:
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    stream = json.loads(result.stdout)["streams"][0]
    return stream["width"], stream["height"]


def _create_project_with_script(client: TestClient) -> str:
    project_id = client.post("/api/v1/projects", json={"name": "draft render test"}).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})
    return project_id


def test_draft_available_before_approval_and_never_disturbs_project_status(client):
    project_id = _create_project_with_script(client)
    awaiting = client.post(f"/api/v1/projects/{project_id}/render").json()
    assert awaiting["status"] == "awaiting_approval", awaiting.get("error")

    draft_resp = client.post(f"/api/v1/projects/{project_id}/render/draft")
    assert draft_resp.status_code == 200, draft_resp.text
    draft_body = draft_resp.json()
    assert draft_body["project_id"] == project_id
    assert draft_body["timeline_version"] == awaiting["timeline"]["version"]
    assert draft_body["expired_drafts_purged"] == 0

    # The draft endpoint must not have advanced the workflow at all - the
    # project is still sitting at awaiting_approval, unresolved.
    status = client.get(f"/api/v1/projects/{project_id}/status").json()
    assert status["status"] == "awaiting_approval"

    video_resp = client.get(f"/api/v1/projects/{project_id}/video/draft")
    assert video_resp.status_code == 200
    assert video_resp.headers["content-type"] == "video/mp4"

    tmp_draft = settings.storage_root / "draft_download_test.mp4"
    tmp_draft.write_bytes(video_resp.content)
    assert _ffprobe_dimensions(tmp_draft) == (settings.draft_width, settings.draft_height)


def test_draft_and_final_are_independent_files_at_independent_resolutions(client):
    project_id = _create_project_with_script(client)
    client.post(f"/api/v1/projects/{project_id}/render")
    client.post(f"/api/v1/projects/{project_id}/render/draft")

    approve_resp = client.post(f"/api/v1/projects/{project_id}/timeline/approve")
    completed = approve_resp.json()
    assert completed["status"] == "completed", completed.get("error")

    final_resp = client.get(f"/api/v1/projects/{project_id}/video")
    draft_resp = client.get(f"/api/v1/projects/{project_id}/video/draft")
    assert final_resp.status_code == 200
    assert draft_resp.status_code == 200
    assert final_resp.content != draft_resp.content

    tmp_final = settings.storage_root / "final_download_test.mp4"
    tmp_draft = settings.storage_root / "draft_download_test2.mp4"
    tmp_final.write_bytes(final_resp.content)
    tmp_draft.write_bytes(draft_resp.content)
    assert _ffprobe_dimensions(tmp_final) == (settings.render_width, settings.render_height)
    assert _ffprobe_dimensions(tmp_draft) == (settings.draft_width, settings.draft_height)


def test_draft_endpoint_requires_a_timeline(client):
    project_id = client.post("/api/v1/projects", json={"name": "no script yet"}).json()["id"]
    resp = client.post(f"/api/v1/projects/{project_id}/render/draft")
    assert resp.status_code == 400


def test_video_draft_404s_when_no_draft_has_been_rendered(client):
    project_id = _create_project_with_script(client)
    client.post(f"/api/v1/projects/{project_id}/render")
    resp = client.get(f"/api/v1/projects/{project_id}/video/draft")
    assert resp.status_code == 404
