"""HTTP-level proof of R3 (2026-08-16): `POST /projects/{id}/render/only`.

Two claims, proven separately:

1. **Fails loudly, never silently advances the workflow** - a render-only
   trigger on a project that hasn't reached the real render step yet gets
   `409` naming the first blocking step, not a render of an incomplete
   project (`render_precondition_gap`, `app/workflow/render_only.py`).
2. **Structurally incapable of invoking a paid provider** - proven here by
   monkeypatching every OTHER real step's `run()` to explode, then
   confirming a render-only trigger on a fully-completed project still
   finishes cleanly. If this endpoint could reach any of those steps at
   all, the explosion would surface as a `failed` status; the point of
   the test is that it structurally cannot, independent of whatever the
   precondition check above does or does not catch.

DRY_RUN + fakes throughout - no real provider is ever configured, so this
also does not (and could not) spend anything even if the structural
guarantee somehow failed.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.workflow.steps.generate_timeline import GenerateTimelineStep
from app.workflow.steps.narration import NarrationStep
from app.workflow.steps.resolve_assets import ResolveAssetsStep
from app.workflow.steps.select_music import SelectMusicStep

from ._polling import trigger_and_wait, wait_for_workflow

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


def _create_project_with_script(client: TestClient) -> str:
    project_id = client.post("/api/v1/projects", json={"name": "render-only test"}).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})
    return project_id


def test_render_only_rejects_a_project_the_pipeline_never_touched(client):
    """No timeline exists at all yet - the very first precondition
    (`generate_timeline`) is the one reported."""
    project_id = _create_project_with_script(client)

    resp = client.post(f"/api/v1/projects/{project_id}/render/only")
    assert resp.status_code == 409, resp.text
    assert "generate_timeline" in resp.json()["detail"]


def test_render_only_rejects_a_project_still_awaiting_approval(client):
    """Planning and the free search pass ran, but a human never approved
    the plan - `await_approval` is what's actually blocking, and the
    error names it rather than the (already-satisfied) planning steps
    ahead of it."""
    project_id = _create_project_with_script(client)
    trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")

    resp = client.post(f"/api/v1/projects/{project_id}/render/only")
    assert resp.status_code == 409, resp.text
    assert "await_approval" in resp.json()["detail"]

    # And the general trigger, unlike this one, IS allowed to advance past
    # it - proving the 409 above was this endpoint's own restriction, not
    # some broader problem with the project.
    approved = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert approved["status"] == "completed", approved.get("error")


def test_render_only_cannot_reach_any_paid_or_planning_step(client, monkeypatch):
    """The core R3 proof. Every step in the pipeline OTHER than render
    itself is patched to explode with a distinctive error; a render-only
    trigger on a project the normal pipeline already carried to
    `completed` must still end `completed`, never surface that error -
    not because the patched steps happen not to be called under DRY_RUN
    (they already all ran once, for real, to get this project to
    `completed` in the first place), but because `RENDER_ONLY_STEPS`
    contains nothing else for the engine to invoke.

    The existing render is also deleted first, so this is not merely
    `RenderStep.is_satisfied()` short-circuiting the whole engine before
    it touches anything - a REAL render-only pass genuinely re-runs
    `RenderStep.run()` here, and still never reaches the exploding
    steps.
    """
    project_id = _create_project_with_script(client)
    trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    completed = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert completed["status"] == "completed", completed.get("error")

    async def _explode(self, ctx):  # noqa: ANN001 - matches WorkflowStep.run's own signature
        raise AssertionError(f"{self.name} must never run under render-only (R3)")

    monkeypatch.setattr(GenerateTimelineStep, "run", _explode)
    monkeypatch.setattr(ResolveAssetsStep, "run", _explode)
    monkeypatch.setattr(SelectMusicStep, "run", _explode)
    monkeypatch.setattr(NarrationStep, "run", _explode)

    # Force a REAL re-render, not a same-fingerprint no-op: delete the
    # file `RenderStep.is_satisfied` checks for, so this project's own
    # completed render row can no longer serve a cache hit either (its
    # `output_path` no longer exists on disk - see `render_video`'s own
    # cache-hit guard).
    video_path = settings.storage_root / project_id / "renders" / "final.mp4"
    assert video_path.exists()
    video_path.unlink()

    resp = client.post(f"/api/v1/projects/{project_id}/render/only")
    assert resp.status_code == 202, resp.text
    result = wait_for_workflow(client, resp.json()["project_id"])

    # The real proof: no exploded step's error ever surfaced, and the
    # project is back to a clean COMPLETED state with a real file again -
    # not FAILED with "generate_timeline must never run", which is what
    # this test would show if the structural guarantee were broken.
    assert result["status"] == "completed", result.get("error")
    assert video_path.exists()
