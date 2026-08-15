"""E2E proof of GET /progress folding shot semantics into each shot
entry (M9): `says`, `prompt`, `intent`, `duration_s`, `starts_at_s`, and
the `shots` array in TIMELINE order (scene order, then shot order)
rather than `shot_id` order - the exact gap a human at the approval gate
hit: `/progress` reported execution state with no meaning, and nothing
joined it to `/timeline`'s narration/prompt/intent.

Written but deliberately NOT run in this session - a live project sits
at the approval gate in the shared dev Postgres, and running pytest
(which truncates every table via tests/conftest.py's autouse
`clean_database` fixture) would destroy it. This file is what the
coordinator's own full-suite run, once the live test is finished, should
exercise. The new fields were instead verified by hand against the real
running server - see the accompanying report for exactly what was
checked there.
"""

import asyncio
import uuid as uuid_module

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import async_session_factory
from app.main import app
from app.models.shot_binding import ShotBindingModel
from app.schemas.timeline import (
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)
from app.timeline.service import TimelineService

# Deliberately split so shot_id alphabetical order disagrees with
# timeline order - "sc_01_aa_second" sorts before "sc_01_zz_first", but
# plays second. Shot-id sorting happening to coincide with timeline
# order on every real fixture today is exactly the coincidence this test
# refuses to rely on.
_SCENE_1_TEXT = "Germany had coal but no oil."
_SPLIT = len("Germany had coal")
_SCENE_2_TEXT = "That gap shaped the war."


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    with TestClient(app) as c:
        yield c


async def _seed_out_of_order_timeline(project_id: str) -> None:
    scene_1 = Scene(
        id="sc_01",
        order=0,
        title="Coal",
        narration_text=_SCENE_1_TEXT,
        duration_s=4.0,
        shots=[
            Shot(
                id="sc_01_zz_first",  # alphabetically LAST, but plays FIRST
                order=0,
                intent=ShotIntent.INTRODUCE,
                intent_text="open on coal",
                narration_span=(0, _SPLIT),
                duration_s=2.0,
                prompt="1930s coal mine, archival photograph",
                transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
            ),
            Shot(
                id="sc_01_aa_second",  # alphabetically FIRST, but plays SECOND
                order=1,
                intent=ShotIntent.EXPLAIN,
                intent_text="the missing resource",
                narration_span=(_SPLIT, len(_SCENE_1_TEXT)),
                duration_s=2.0,
                prompt="empty oil depot",
                transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
            ),
        ],
    )
    scene_2 = Scene(
        id="sc_02",
        order=1,
        title="Consequence",
        narration_text=_SCENE_2_TEXT,
        duration_s=3.0,
        shots=[
            Shot(
                id="sc_02_only",
                order=0,
                intent=ShotIntent.REVEAL,
                intent_text="the stakes",
                narration_span=(0, len(_SCENE_2_TEXT)),
                duration_s=3.0,
                prompt="wartime map",
                transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
            ),
        ],
    )

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base):
            base.scenes = [scene_1, scene_2]
            base.metadata.total_duration_s = 7.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )

        project_uuid = uuid_module.UUID(project_id)
        for shot_id in ("sc_01_zz_first", "sc_01_aa_second", "sc_02_only"):
            session.add(
                ShotBindingModel(
                    project_id=project_uuid,
                    timeline_version=appended.version,
                    shot_id=shot_id,
                    state="resolved",
                )
            )
        await session.commit()


def test_progress_shots_are_in_timeline_order_with_full_semantics(client):
    project_id = client.post("/api/v1/projects", json={"name": "progress semantics test"}).json()[
        "id"
    ]
    asyncio.run(_seed_out_of_order_timeline(project_id))

    progress = client.get(f"/api/v1/projects/{project_id}/progress").json()
    shots = progress["shots"]
    assert len(shots) == 3

    # Timeline order (scene order, then shot order) - NOT alphabetical
    # shot_id order, which would put "sc_01_aa_second" first.
    assert [s["shot_id"] for s in shots] == [
        "sc_01_zz_first",
        "sc_01_aa_second",
        "sc_02_only",
    ]

    first, second, third = shots

    assert first["says"] == "Germany had coal"
    assert first["prompt"] == "1930s coal mine, archival photograph"
    assert first["intent"] == "introduce"
    assert first["duration_s"] == 2.0
    assert first["starts_at_s"] == 0.0

    assert second["says"] == _SCENE_1_TEXT[_SPLIT:]
    assert second["prompt"] == "empty oil depot"
    assert second["intent"] == "explain"
    assert second["starts_at_s"] == 2.0  # hard cut - no overlap to subtract

    assert third["says"] == _SCENE_2_TEXT
    assert third["prompt"] == "wartime map"
    assert third["intent"] == "reveal"
    assert third["starts_at_s"] == 4.0  # end of scene 1's two hard-cut shots

    # Additive only - every field /progress already returned is untouched.
    for s in shots:
        assert set(s) >= {
            "shot_id",
            "state",
            "rung",
            "last_error",
            "will_generate",
            "locked",
            "asset",
            "clip",
        }
        assert s["asset"] is None  # no binding.asset_id was set - unaffected
        assert s["clip"] is None
