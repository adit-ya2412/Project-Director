"""M0 walking-skeleton end-to-end test.

Proves the full path: create project -> upload script -> render -> download
a real MP4 -- entirely on fakes, with zero API keys configured. This is the
test referenced as M0's "done when" criterion in
docs/13_Implementation_Guide.md.
"""

import subprocess

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.schemas.timeline import Timeline
from app.timeline.duration import compute_timeline_duration


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _ffprobe_json(path, *entries: str) -> dict:
    # ffprobe's -show_entries joins different sections (stream=..., format=...)
    # with ':' -- a ',' only separates fields within one section.
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        ":".join(entries),
        str(path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    import json

    return json.loads(result.stdout)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["dry_run"] is True


def test_script_to_video_end_to_end(client, tmp_path):
    # 1. Create project
    create_resp = client.post("/api/v1/projects", json={"name": "Germany's Resource Gap"})
    assert create_resp.status_code == 200
    project = create_resp.json()
    project_id = project["id"]
    assert project["status"] == "created"

    # 2. Upload script
    script = (
        "Germany possessed abundant coal, fueling its factories and its "
        "ambitions. But it lacked one vital resource: oil, and that "
        "dependency would shape the war to come. That single gap in "
        "resources would drive strategic decisions with consequences the "
        "world still remembers."
    )
    script_resp = client.post(f"/api/v1/projects/{project_id}/script", json={"content": script})
    assert script_resp.status_code == 200
    assert script_resp.json()["status"] == "script_uploaded"

    # 3. Render (runs the whole fake pipeline synchronously in M0)
    render_resp = client.post(f"/api/v1/projects/{project_id}/render")
    assert render_resp.status_code == 200
    rendered = render_resp.json()
    assert rendered["status"] == "completed", rendered.get("error")
    assert rendered["timeline"] is not None

    timeline = Timeline.model_validate(rendered["timeline"])
    assert len(timeline.all_shots()) == 6
    expected_duration = compute_timeline_duration(timeline.all_shots())

    # 4. Download the MP4
    video_resp = client.get(f"/api/v1/projects/{project_id}/video")
    assert video_resp.status_code == 200
    assert video_resp.headers["content-type"] == "video/mp4"
    assert len(video_resp.content) > 10_000  # a real file, not a stub

    video_path = tmp_path / "downloaded.mp4"
    video_path.write_bytes(video_resp.content)

    probe = _ffprobe_json(video_path, "stream=width,height,r_frame_rate", "format=duration")
    stream = probe["streams"][0]
    assert stream["width"] == settings.render_width
    assert stream["height"] == settings.render_height
    assert stream["r_frame_rate"] == f"{settings.render_fps}/1"

    actual_duration = float(probe["format"]["duration"])
    assert abs(actual_duration - expected_duration) < 0.5

    # 5. Status endpoint agrees
    status_resp = client.get(f"/api/v1/projects/{project_id}/status")
    assert status_resp.json()["status"] == "completed"


def test_render_without_script_fails_cleanly(client):
    create_resp = client.post("/api/v1/projects", json={"name": "Empty"})
    project_id = create_resp.json()["id"]

    render_resp = client.post(f"/api/v1/projects/{project_id}/render")
    assert render_resp.status_code == 400


def test_unknown_project_returns_404(client):
    resp = client.get("/api/v1/projects/does-not-exist")
    assert resp.status_code == 404
