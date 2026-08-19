"""HTTP-level proof of Tasks 3/4/6 (2026-08-16, the one-gate redesign):
`POST /projects/{id}/shots/{shot_id}/generate`.

- Task 3: repeat clicks on an unchanged shot vary the seed, so a second
  click is a genuine, billed regeneration - never a silent, free replay
  of the first result.
- Task 6: the response reports `cache_hit` explicitly, and `cost_cents`
  is what THIS call actually cost (0 on a real cache hit), never the
  clip row's original charge.
- Task 4: an optional edited `prompt` is a Timeline change (I2), recorded
  as its own `append_version(produced_by=HUMAN)` before generating - with
  the single highest-risk proof this whole task named directly: editing
  ONE shot's prompt must not orphan every OTHER shot's binding (A11/A20),
  and must never touch `duration_s` (A29). Also proven here: the
  documented, NOT-silently-worked-around conflict between an edited
  prompt and a previously-LOCKED (overridden) shot (A25).

DRY_RUN + `FakeImageProvider` throughout - no real fal.ai call. Note
`FakeImageProvider` derives its output purely from the PROMPT TEXT, not
the seed (see that fake's own docstring) - so this file proves
cache_hit/cost/clip-identity behaviour (which does not depend on the fake
varying its pixels by seed) rather than that two regenerated images
literally look different; that half is proven against a REAL,
seed-driven test double in
tests/integration/test_resolve_assets_generation_real.py
::test_repeated_explicit_generation_varies_the_seed_and_produces_a_new_clip.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.main import app

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


def _png_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _create_and_render(client: TestClient) -> tuple[str, dict]:
    project_id = client.post("/api/v1/projects", json={"name": "generate endpoint test"}).json()[
        "id"
    ]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})
    awaiting = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    return project_id, awaiting


def test_generate_reports_cache_hit_and_repeat_clicks_are_never_free(client):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    first = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["cache_hit"] is False
    assert first_body["cost_cents"] == settings.fal_image_cost_cents_estimate

    second = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate")
    assert second.status_code == 200, second.text
    second_body = second.json()
    # Task 3: the seed varies on the second click for the SAME shot (a
    # genuinely new attempt), so this is NOT a cache hit - clicking
    # "generate" twice must not silently return the first, free result.
    assert second_body["cache_hit"] is False
    assert second_body["cost_cents"] == settings.fal_image_cost_cents_estimate
    assert second_body["clip_id"] != first_body["clip_id"]

    progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    assert progress["spent_cost_cents"] >= 2 * settings.fal_image_cost_cents_estimate


def test_generate_hits_the_cache_when_a_different_shot_shares_the_exact_prompt(client):
    """Task 6's `cache_hit` is not a flag that's always `False` after
    Task 3 - a genuine cache hit still happens when two DIFFERENT shots'
    FIRST-EVER attempts land on the identical `(prompt, model, seed)`:
    attempt 0 always uses the bare PROJECT seed (shared by every shot in
    a project, by design - M7's fixed-per-project stylistic
    consistency), so two shots with identical prompt text collide on the
    same `prompt_hash` the first time either of them generates."""
    project_id, awaiting = _create_and_render(client)
    shots = awaiting["timeline"]["scenes"][0]["shots"]
    assert len(shots) >= 2
    shot_a, shot_b = shots[0]["id"], shots[1]["id"]
    shared_prompt = shots[0]["prompt"]

    # Give shot_b the exact same prompt shot_a already has, via the
    # endpoint's own edited-prompt path (Task 4) - proving the cache-hit
    # mechanism and the prompt-edit mechanism compose correctly, not just
    # in isolation.
    edit_resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_b}/generate",
        json={"prompt": shared_prompt},
    )
    assert edit_resp.status_code == 200, edit_resp.text
    first_cost = edit_resp.json()["cost_cents"]
    assert first_cost == settings.fal_image_cost_cents_estimate  # shot_b's own first attempt

    first_a = client.post(f"/api/v1/projects/{project_id}/shots/{shot_a}/generate")
    assert first_a.status_code == 200, first_a.text
    # shot_a's own first-ever attempt, at the SAME project seed and the
    # SAME prompt text shot_b just used - a real cache hit.
    assert first_a.json()["cache_hit"] is True
    assert first_a.json()["cost_cents"] == 0
    assert first_a.json()["clip_id"] == edit_resp.json()["clip_id"]


def test_generate_with_edited_prompt_appends_a_new_version_and_carries_forward_other_bindings(
    client,
):
    """Task 4's single highest-risk claim, proven directly against the
    real HTTP surface and the real database: editing ONE shot's prompt
    must not orphan every OTHER shot's binding (A11/A20), and must never
    touch `duration_s`/the timeline's total duration (A29)."""
    project_id, awaiting = _create_and_render(client)
    shots = awaiting["timeline"]["scenes"][0]["shots"]
    assert len(shots) >= 2
    target_shot = shots[0]
    other_shot_ids = [s["id"] for s in shots[1:]]
    duration_before = target_shot["duration_s"]
    total_duration_before = awaiting["timeline"]["metadata"]["total_duration_s"]
    version_before = awaiting["timeline"]["version"]

    before_progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    other_assets_before = {
        s["shot_id"]: s["asset"]["local_path"]
        for s in before_progress["shots"]
        if s["shot_id"] in other_shot_ids
    }
    assert all(other_assets_before.values())  # every OTHER shot already has a real asset

    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{target_shot['id']}/generate",
        json={"prompt": "a completely different, hand-edited prompt"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cache_hit"] is False

    timeline = client.get(f"/api/v1/projects/{project_id}/timeline").json()
    assert timeline["version"] > version_before  # I2: the edit is a real Timeline version
    assert timeline["produced_by"] == "human"
    new_target_shot = next(
        s for scene in timeline["scenes"] for s in scene["shots"] if s["id"] == target_shot["id"]
    )
    assert new_target_shot["prompt"] == "a completely different, hand-edited prompt"
    # A29: editing a prompt never touches timing.
    assert new_target_shot["duration_s"] == duration_before
    assert timeline["metadata"]["total_duration_s"] == pytest.approx(total_duration_before)

    after_progress = client.get(f"/api/v1/projects/{project_id}/progress?expand=shots").json()
    other_assets_after = {
        s["shot_id"]: (s["asset"]["local_path"] if s["asset"] else None)
        for s in after_progress["shots"]
        if s["shot_id"] in other_shot_ids
    }
    # The proof itself: every OTHER shot's binding survived the version
    # bump pointing at the exact SAME underlying file - carried forward,
    # never re-resolved (A11/A20) - rather than silently going empty.
    assert other_assets_after == other_assets_before


def test_generate_without_an_edited_prompt_never_bumps_the_timeline_version(client):
    """The common case (the whole endpoint's original contract) must be
    untouched by Task 4 - omitting `prompt` never creates a new Timeline
    version at all."""
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]
    version_before = awaiting["timeline"]["version"]

    resp = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate")
    assert resp.status_code == 200, resp.text

    timeline = client.get(f"/api/v1/projects/{project_id}/timeline").json()
    assert timeline["version"] == version_before


def test_generate_rejects_a_blank_edited_prompt(client):
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/generate", json={"prompt": "   "}
    )
    assert resp.status_code == 400


def test_generate_peers_with_override_but_an_edited_prompt_on_a_locked_shot_is_refused(client):
    """The highest-risk interaction Task 4 flags directly:
    `TimelineService._reject_locked_shot_drift` (A25) unconditionally
    refuses ANY later version that changes a locked shot's `prompt` -
    regardless of `produced_by`. Generate and override are peers (a
    human may still regenerate an UNEDITED-prompt AI alternative for a
    shot they previously overrode - see the endpoint's own docstring),
    but editing the PROMPT of a locked shot is refused outright, surfaced
    as 400, never silently bypassed. There is deliberately no unlock
    endpoint - A25a's own documented, deferred gap."""
    project_id, awaiting = _create_and_render(client)
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]

    overridden = trigger_and_wait(
        client,
        "post",
        f"/api/v1/projects/{project_id}/shots/{shot_id}/override",
        files={"file": ("photo.png", _png_bytes(), "image/png")},
        data={"description": "a human-chosen photo for this exact shot"},
    )
    assert overridden["status"] == "awaiting_approval"
    locked_shot = next(
        s
        for scene in overridden["timeline"]["scenes"]
        for s in scene["shots"]
        if s["id"] == shot_id
    )
    assert locked_shot["asset_locked"] is True

    # Peer behaviour: generating WITHOUT an edited prompt still works on
    # a locked shot - it never refuses based on `asset_locked` any more.
    plain_generate = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate")
    assert plain_generate.status_code == 200, plain_generate.text

    # But an edited prompt on the same, still-locked shot is rejected -
    # A25's guarantee ("my photo is always in the plan") would otherwise
    # break the moment a re-plan (even a human one) could drift the
    # locked shot's own prompt away from what it was locked against.
    edited = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/generate",
        json={"prompt": "trying to change the locked shot's prompt"},
    )
    assert edited.status_code == 400
    assert "asset_locked" in edited.json()["detail"]

    # And the shot's prompt is genuinely unchanged - the rejection was
    # not a partial, silent write.
    timeline = client.get(f"/api/v1/projects/{project_id}/timeline").json()
    still_locked_shot = next(
        s for scene in timeline["scenes"] for s in scene["shots"] if s["id"] == shot_id
    )
    assert still_locked_shot["prompt"] == locked_shot["prompt"]
