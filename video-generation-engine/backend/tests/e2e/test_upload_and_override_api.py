"""HTTP-level proof of M6.5's human-media endpoints - the upload endpoint
(A8/A23/A27), the per-shot override (A9/A10/A24/A25/A29), and the review
gate (A15/A26/A28) - all through the real FastAPI routes, DRY_RUN=true,
zero API keys. Same premise as tests/e2e/test_skeleton.py: this is the
walking-skeleton proof for M6.5's two "Done when" criteria about a human
seeing and overriding assets through the real API, not through calling
the underlying services directly.

DRY_RUN's `FakeAssetProvider`/`FakeImageProvider` always succeed, so
there is no way to drive a REAL generation failure through this surface
without mocking fal.ai/OpenAI (covered instead, at the step level, by
tests/integration/test_resolve_assets_generation_real.py). The review
gate test below manufactures a `failed` binding directly to exercise the
gate itself over HTTP - it is not a claim that DRY_RUN can fail on its
own.

F0a (2026-08-16): every trigger below (`render`, `timeline/approve`,
`shots/{id}/override`) now returns `202` immediately - call sites that
used to read the trigger's own response body now poll via
`tests/e2e/_polling.py::trigger_and_wait` instead.
"""

import asyncio
import io
import uuid as uuid_module

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.db.session import async_session_factory
from app.main import app
from app.repositories.shot_binding_repository import ShotBindingRepository

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
    # Same pin as test_skeleton.py: this suite's premise is fakes-only,
    # zero API keys, regardless of the ambient .env's DRY_RUN value.
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


def _png_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _create_and_render(client: TestClient) -> tuple[str, dict]:
    project_id = client.post("/api/v1/projects", json={"name": "M6.5 upload/override"}).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})
    awaiting = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    return project_id, awaiting


async def _flip_binding_to_failed(project_id: str, timeline_version: int, shot_id: str) -> None:
    """Stands in for what a real, exhausted constraint-violation would
    have left behind (M6.5, A14/A19) - proven for real, with a real
    vision-check provider, in test_resolve_assets_generation_real.py.
    Here the point is only to exercise the review gate/override endpoint
    over the real HTTP surface, not to reprove how a shot gets to
    `failed` in the first place."""
    async with async_session_factory() as session:
        repo = ShotBindingRepository(session)
        binding = await repo.get(uuid_module.UUID(project_id), timeline_version, shot_id)
        assert binding is not None
        binding.state = "failed"
        binding.last_error = "simulated: constraint violated after every attempt"
        await session.commit()


def test_upload_endpoint_validates_hashes_and_dedupes(client):
    project_id = client.post("/api/v1/projects", json={"name": "Upload only"}).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})

    content = _png_bytes()
    resp = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files=[("files", ("photo.png", content, "image/png"))],
        data={"descriptions": ["a Leuna Werke plant photo, aerial view"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["duplicate"] is False
    asset_id = body[0]["asset_id"]

    # Same bytes again (M6, hash dedup) - not an error, no second row.
    dupe_resp = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files=[("files", ("photo-again.png", content, "image/png"))],
        data={"descriptions": ["same photo, re-uploaded"]},
    )
    assert dupe_resp.status_code == 200
    assert dupe_resp.json()[0]["duplicate"] is True
    assert dupe_resp.json()[0]["asset_id"] == asset_id

    # Bad bytes fail AT THE ENDPOINT (A27), not mid-render.
    bad_resp = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files=[("files", ("not-a-photo.png", b"this is not image bytes", "image/png"))],
        data={"descriptions": ["garbage"]},
    )
    assert bad_resp.status_code == 400

    # A23: a description is required - matching against a filename alone
    # would be worthless.
    empty_desc_resp = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files=[("files", ("photo2.png", _png_bytes((5, 5, 5)), "image/png"))],
        data={"descriptions": [""]},
    )
    assert empty_desc_resp.status_code == 400

    mismatch_resp = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files=[("files", ("photo3.png", _png_bytes((7, 7, 7)), "image/png"))],
        data={"descriptions": ["one", "two"]},
    )
    assert mismatch_resp.status_code == 400


def test_upload_is_optional_and_a_no_upload_project_is_unaffected(client):
    """M6.5, A8: a project that never calls the upload endpoint behaves
    exactly as before this phase."""
    project_id, awaiting = _create_and_render(client)
    assert awaiting["error"] is None, awaiting.get("error")
    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    assert len(progress["shots"]) == 6
    assert all(s["state"] == "resolved" for s in progress["shots"])
    assert all(s["locked"] is False for s in progress["shots"])


def test_override_before_approval_locks_the_shot_but_still_requires_approval(client):
    """M6.5 Done-when: a human can see real images per shot and swap or
    override any of them before anything expensive runs - and doing so
    pre-approval must not silently skip the human's first plan approval
    (only a POST-approval override self-approves; see the endpoint's own
    docstring, mirroring NarrationStep's append-then-approve pattern)."""
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]
    version_before = awaiting["timeline"]["version"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/override",
        files={"file": ("override.png", _png_bytes((9, 9, 9)), "image/png")},
        data={"description": "a human-chosen photo for this exact shot"},
    )
    assert resp.status_code == 202, resp.text
    trigger = resp.json()
    # First-gate override must not resume the engine (that re-runs
    # narration and bounces the review UI to /progress).
    assert trigger["joined_existing_run"] is True
    assert trigger["state"] == "awaiting_approval"
    progress_after = client.get(f"/api/v1/projects/{project_id}/progress").json()
    assert progress_after["workflow_state"] == "awaiting_approval"
    assert progress_after["current_step"] == "await_approval"

    overridden = client.get(f"/api/v1/projects/{project_id}").json()
    assert overridden["status"] == "awaiting_approval"
    assert overridden["timeline"]["version"] > version_before

    timeline = client.get(f"/api/v1/projects/{project_id}/timeline").json()
    shots = [s for scene in timeline["scenes"] for s in scene["shots"]]
    locked_shot = next(s for s in shots if s["id"] == shot_id)
    assert locked_shot["asset_locked"] is True
    # A29: an override changes only the binding and the lock - never the
    # shot's prompt.
    original_shot = next(
        s for scene in awaiting["timeline"]["scenes"] for s in scene["shots"] if s["id"] == shot_id
    )
    assert locked_shot["prompt"] == original_shot["prompt"]

    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    detail = next(s for s in progress["shots"] if s["shot_id"] == shot_id)
    assert detail["locked"] is True
    assert detail["asset"]["provider"] == "project_assets"

    completed = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert completed["status"] == "completed", completed.get("error")

    final_shot = next(
        s for scene in completed["timeline"]["scenes"] for s in scene["shots"] if s["id"] == shot_id
    )
    # A25: the lock survives the narration version bump too.
    assert final_shot["asset_locked"] is True


def test_override_after_completion_self_approves_and_preserves_duration_and_narration(client):
    """A29: an override changes only the binding and the lock - never
    `duration_s` (or, transitively, the narration built from it).
    Narration is the master clock; an upload must be a free, instant
    swap, never a paid re-narration."""
    project_id, _awaiting = _create_and_render(client)
    completed = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert completed["status"] == "completed", completed.get("error")
    assert completed["timeline"]["produced_by"] == "narration"

    shot_id = completed["timeline"]["scenes"][0]["shots"][0]["id"]
    duration_before = completed["timeline"]["scenes"][0]["shots"][0]["duration_s"]
    total_duration_before = completed["timeline"]["metadata"]["total_duration_s"]

    result = trigger_and_wait(
        client,
        "post",
        f"/api/v1/projects/{project_id}/shots/{shot_id}/override",
        files={"file": ("override2.png", _png_bytes((3, 3, 3)), "image/png")},
        data={"description": "swapping the picture after the fact"},
    )
    # A self-approving override resumes on its own - no separate call to
    # /timeline/approve needed once the plan was already approved.
    assert result["status"] == "completed", result.get("error")

    new_shot = result["timeline"]["scenes"][0]["shots"][0]
    assert new_shot["id"] == shot_id
    assert new_shot["asset_locked"] is True
    assert new_shot["duration_s"] == duration_before
    assert result["timeline"]["metadata"]["total_duration_s"] == total_duration_before


def test_a_failed_shot_blocks_approval_and_override_clears_it(client):
    """A15/A26/A28, and Task 2 (2026-08-16, the one-gate redesign): there
    is no "proceed anyway" for a failed shot - overriding it is the only
    remedy. This used to be caught at the (post-approval) `AwaitReviewStep`
    gate; Task 2 moves the check EARLIER, to `POST /timeline/approve`
    itself (A26's "you cannot finish with a gap" becomes "you cannot
    APPROVE with a gap") - strictly better, since it is now impossible to
    even approve a plan with a gap, rather than approving it and letting
    `resolve_assets_generate` batch-generate the rest unattended before
    the gap is discovered. `AwaitReviewStep` remains as a backstop (see
    `app/workflow/engine.py`) for anything that reaches `failed` AFTER
    approval - not exercised by this specific scenario, since the guard
    below now catches it first."""
    project_id, awaiting = _create_and_render(client)
    version = awaiting["timeline"]["version"]
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]
    asyncio.run(_flip_binding_to_failed(project_id, version, shot_id))

    blocked = client.post(f"/api/v1/projects/{project_id}/timeline/approve")
    assert blocked.status_code == 400
    assert shot_id in blocked.json()["detail"]

    # Still stuck at awaiting_approval - the guard rejected the request
    # outright, it never touched the workflow at all.
    status_resp = client.get(f"/api/v1/projects/{project_id}/status").json()
    assert status_resp["status"] == "awaiting_approval"

    # The remedy: override the failed shot. Works on ANY binding state,
    # not only a failed one (M6.5 Done-when) - this is the exact same
    # override endpoint, unaffected by Task 2's approval-time guard.
    fixed = trigger_and_wait(
        client,
        "post",
        f"/api/v1/projects/{project_id}/shots/{shot_id}/override",
        files={"file": ("fix.png", _png_bytes((4, 4, 4)), "image/png")},
        data={"description": "the human-supplied fix for the failed shot"},
    )
    # The override happened before the project's first approval, so (per
    # its own docstring) it does not self-approve - a human still has to
    # click approve once, same as `test_override_before_approval_locks_
    # the_shot_but_still_requires_approval` above already proves for the
    # non-failure case.
    assert fixed["status"] == "awaiting_approval", fixed.get("error")

    completed = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert completed["status"] == "completed", completed.get("error")


def test_override_on_unknown_shot_is_rejected(client):
    project_id, _awaiting = _create_and_render(client)
    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/not-a-real-shot/override",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        data={"description": "irrelevant"},
    )
    assert resp.status_code == 404


def test_override_rejects_invalid_image_bytes(client):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]
    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/override",
        files={"file": ("x.png", b"not an image", "image/png")},
        data={"description": "irrelevant"},
    )
    assert resp.status_code == 400
