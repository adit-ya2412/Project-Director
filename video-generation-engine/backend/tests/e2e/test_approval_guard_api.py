"""HTTP-level proof of Task 2 (2026-08-16, the one-gate redesign):
`POST /projects/{id}/timeline/approve` now refuses (400) if any shot at
the active version has no media bound yet - the money guard the
one-gate design depends on. Under the OLD two-gate design, approving an
incomplete plan was safe, because generation ran unattended and any
gaps only surfaced afterward at a SEPARATE review gate. Under the new
design there is exactly one human checkpoint, so it has to be the thing
that catches "you are about to spend money on shots nobody looked at" -
see `app/api/projects.py::approve_timeline`'s own docstring for the full
reasoning, and `tests/e2e/test_upload_and_override_api.py::
test_a_failed_shot_blocks_approval_and_override_clears_it` for the
sibling case where the unfilled shot is `"failed"` rather than
`"awaiting_generation"`.

DRY_RUN's `FakeAssetProvider` always finds something (see its own
docstring), so a shot can never genuinely reach `awaiting_generation`
through this suite's normal render path - the scenario is manufactured
directly against the database, the same pattern
`test_upload_and_override_api.py::_flip_binding_to_failed` already uses
for the analogous `failed` case.
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
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


def _png_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _create_and_render(client: TestClient) -> tuple[str, dict]:
    project_id = client.post("/api/v1/projects", json={"name": "approval guard test"}).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/script", json={"content": _SCRIPT})
    awaiting = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/render")
    return project_id, awaiting


async def _flip_binding_to_awaiting_generation(
    project_id: str, timeline_version: int, shot_id: str
) -> None:
    """Stands in for what the free search pass leaves behind when every
    permitted rung came up empty (A6/A21) - proven for real, against the
    real ladder walk, in tests/integration/test_resolve_assets_real.py.
    Here the point is only to exercise the approval guard over the real
    HTTP surface."""
    async with async_session_factory() as session:
        repo = ShotBindingRepository(session)
        binding = await repo.get(uuid_module.UUID(project_id), timeline_version, shot_id)
        assert binding is not None
        binding.state = "awaiting_generation"
        binding.asset_id = None
        await session.commit()


def test_approval_is_blocked_while_a_shot_is_awaiting_generation(client):
    project_id, awaiting = _create_and_render(client)
    version = awaiting["timeline"]["version"]
    shots = awaiting["timeline"]["scenes"][0]["shots"]
    gap_shot_id = shots[0]["id"]
    other_shot_ids = [s["id"] for s in shots[1:]]
    asyncio.run(_flip_binding_to_awaiting_generation(project_id, version, gap_shot_id))

    resp = client.post(f"/api/v1/projects/{project_id}/timeline/approve")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert gap_shot_id in detail
    # Only the actual gap is named - other shots that already have media
    # must not be reported as blocking too.
    for other_id in other_shot_ids:
        assert other_id not in detail

    # Nothing was approved - still sitting exactly where it was.
    status_resp = client.get(f"/api/v1/projects/{project_id}/status").json()
    assert status_resp["status"] == "awaiting_approval"
    timeline_resp = client.get(f"/api/v1/projects/{project_id}/timeline").json()
    assert timeline_resp["status"] == "draft"


def test_approval_succeeds_once_the_gap_is_filled_by_an_explicit_generate(client):
    """The intended remedy under the one-gate design: a human clicks
    `POST /shots/{id}/generate` for exactly the shot search couldn't
    find, and approval - which used to be blocked - now succeeds."""
    project_id, awaiting = _create_and_render(client)
    version = awaiting["timeline"]["version"]
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]
    asyncio.run(_flip_binding_to_awaiting_generation(project_id, version, shot_id))

    blocked = client.post(f"/api/v1/projects/{project_id}/timeline/approve")
    assert blocked.status_code == 400

    generate_resp = client.post(f"/api/v1/projects/{project_id}/shots/{shot_id}/generate")
    assert generate_resp.status_code == 200, generate_resp.text

    completed = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert completed["status"] == "completed", completed.get("error")


def test_approval_succeeds_once_the_gap_is_filled_by_an_override(client):
    """The other intended remedy - a human's own photo, via override -
    also clears the same gap."""
    project_id, awaiting = _create_and_render(client)
    version = awaiting["timeline"]["version"]
    shot_id = awaiting["timeline"]["scenes"][0]["shots"][0]["id"]
    asyncio.run(_flip_binding_to_awaiting_generation(project_id, version, shot_id))

    blocked = client.post(f"/api/v1/projects/{project_id}/timeline/approve")
    assert blocked.status_code == 400

    overridden = trigger_and_wait(
        client,
        "post",
        f"/api/v1/projects/{project_id}/shots/{shot_id}/override",
        files={"file": ("fix.png", _png_bytes(), "image/png")},
        data={"description": "a human-supplied photo for the missing shot"},
    )
    assert overridden["status"] == "awaiting_approval"

    completed = trigger_and_wait(client, "post", f"/api/v1/projects/{project_id}/timeline/approve")
    assert completed["status"] == "completed", completed.get("error")


def test_approval_names_every_unfilled_shot_not_just_the_first(client):
    project_id, awaiting = _create_and_render(client)
    version = awaiting["timeline"]["version"]
    shots = awaiting["timeline"]["scenes"][0]["shots"]
    assert len(shots) >= 2
    gap_shot_ids = [shots[0]["id"], shots[1]["id"]]
    for shot_id in gap_shot_ids:
        asyncio.run(_flip_binding_to_awaiting_generation(project_id, version, shot_id))

    resp = client.post(f"/api/v1/projects/{project_id}/timeline/approve")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    for shot_id in gap_shot_ids:
        assert shot_id in detail
