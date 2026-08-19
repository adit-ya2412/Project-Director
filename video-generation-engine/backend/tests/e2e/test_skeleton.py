"""Walking-skeleton end-to-end test.

Proves the full path: create project -> upload script -> render (stops at
AWAITING_APPROVAL, ADR-008) -> approve -> download a real MP4 -- entirely
on fakes, with zero API keys configured. This is the test referenced as
M0's "done when" criterion in docs/13_Implementation_Guide.md, extended
in M4 for the real human-approval gate.

F0a (2026-08-16): `POST /render`/`POST /timeline/approve` now return
`202` immediately and finish in the background - every place this test
used to read the trigger's own response body now polls instead, via
`tests/e2e/_polling.py::trigger_and_wait`. The pipeline's own behaviour
under test (stops at the approval gate, resumes past it, produces a real
narrated/rendered MP4) is unchanged; only how the test OBSERVES that
behaviour changed.
"""

import subprocess

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.schemas.timeline import Timeline
from app.timeline.duration import compute_timeline_duration

from ._polling import trigger_and_wait


@pytest.fixture
def client(monkeypatch):
    # Pinned to the fake-provider path regardless of the ambient .env's
    # DRY_RUN value: this suite's entire premise (see module docstring) is
    # "entirely on fakes, with zero API keys configured" - it must not
    # silently make real, paid provider calls just because a developer's
    # local .env has DRY_RUN=false for a live manual test.
    monkeypatch.setattr(settings, "dry_run", True)
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

    # 3. Render — the engine runs generate_timeline, THEN the free
    # search-only ResolveAssetsStep pass (M6.5, A5 - search costs
    # nothing, so I6 permits it before approval), then stops at the human
    # approval gate (ADR-008). Nothing EXPENSIVE has happened yet - but
    # search has, and the whole point of moving it here is that the human
    # reaches this gate having already seen what was found.
    #
    # F0a: the trigger itself only ever returns a 202 + run id now -
    # `trigger_and_wait` posts it and polls `GET /status` for the actual
    # outcome, returning the same `Project` body this test used to read
    # straight off the POST response.
    awaiting = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    assert awaiting["error"] is None, awaiting.get("error")
    assert awaiting["timeline"] is not None

    timeline = Timeline.model_validate(awaiting["timeline"])
    assert len(timeline.all_shots()) == 6
    assert timeline.status == "draft"
    # Task 1 (2026-08-16): `NarrationStep` now runs BEFORE the approval
    # gate (a deliberate, narrow I6 exception - see
    # `app/workflow/engine.DEFAULT_PIPELINE`'s own docstring for why), so
    # by the time a human reaches AWAITING_APPROVAL the durations shown
    # are already the REAL, narration-measured ones (here, faked), not
    # the planner's pre-audio guess - proof the reorder took effect, not
    # just that the gate is still reached.
    assert timeline.produced_by == "narration"
    reconciled_duration = compute_timeline_duration(timeline.all_shots())

    progress_resp = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots")
    assert progress_resp.status_code == 200
    progress = progress_resp.json()
    assert progress["workflow_state"] == "awaiting_approval"
    assert progress["current_step"] == "await_approval"
    # M6.5, A5: proof the reorder actually happened, not just that the
    # pipeline still reaches the gate - every shot is already resolved
    # (DRY_RUN's FakeAssetProvider always finds something) BEFORE
    # approval, with its source visible via `shots[*].asset`, and none
    # are waiting on the (not-yet-run, paid) generation pass.
    assert len(progress["shots"]) == 6
    assert all(s["state"] == "resolved" for s in progress["shots"])
    assert all(s["asset"] is not None for s in progress["shots"])
    assert all(s["will_generate"] is False for s in progress["shots"])

    # M8 step 4: music selection also runs before the approval gate
    # (D6/21.2 - Pixabay search is free, so a human approving a video
    # should hear what it will sound like) - the ACTIVE timeline by the
    # time we reach the gate already carries a real selection, made via
    # `FakeMusicProvider` (whose one canned candidate's "cc0" licence
    # satisfies the fixture's own `music_plan.licence_requirements`).
    assert timeline.music_plan is not None
    assert timeline.music_plan.selection_attempted is True
    assert timeline.music_plan.selected_track is not None
    assert timeline.music_plan.selected_track.provider == "fake_music"

    timeline_resp = client.get(f"/api/v1/projects/{project_id}/timeline")
    assert timeline_resp.status_code == 200
    assert timeline_resp.json()["status"] == "draft"

    # Rendering again while awaiting approval is a no-op resume, not a
    # second pipeline run - it should land right back at the same gate.
    render_again = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    assert render_again["timeline"]["version"] == awaiting["timeline"]["version"]

    # 4. Approve — resumes the same run: resolve_assets (paid pass) ->
    # render -> complete. Narration already ran BEFORE this gate (Task
    # 1), so approving does not append another narration version - the
    # version approved here IS the narration-reconciled one already
    # shown at the gate above (`NarrationStep.is_satisfied` is already
    # true for it), which is exactly what makes it safe for a human to
    # judge on-screen duration before clicking approve.
    rendered = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert rendered["status"] == "completed", rendered.get("error")
    assert rendered["timeline"]["status"] == "approved"
    assert rendered["timeline"]["version"] == awaiting["timeline"]["version"]

    final_timeline = Timeline.model_validate(rendered["timeline"])
    assert final_timeline.produced_by == "narration"
    expected_duration = compute_timeline_duration(final_timeline.all_shots())
    assert expected_duration == pytest.approx(reconciled_duration)

    final_progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    assert final_progress["workflow_state"] == "completed"
    assert final_progress["completed_shots"] == final_progress["total_shots"] == 6
    assert final_progress["progress"] == 1.0

    # Approving twice is rejected cleanly.
    second_approve = client.post(f"/api/v1/projects/{project_id}/timeline/approve")
    assert second_approve.status_code == 400

    # 5. Download the MP4
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

    # 6. Status endpoint agrees
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
