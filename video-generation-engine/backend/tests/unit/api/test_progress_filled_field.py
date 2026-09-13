"""gate_panel_overrides.md §7.5 addendum, 2026-09-13 CORRECTION.

The first pass of the gate-layer fix changed only `_unfilled_shot_ids`
(the approval guard). `GET /progress` kept computing its own per-scene
`unfilled_shots` count straight off `binding.state`, and each shot's own
payload had no layer-aware notion of "filled" at all — so a layered shot
with every plane resolved still showed up as "1 still needs a picture"
on its scene, and the frontend's `isFilled` (reading `shot.state`) kept
the Approve button disabled. Backend and UI disagreed with the guard —
worse than the original bug.

This suite proves `_shot_is_filled` (the one shared predicate,
app/api/projects.py) now drives BOTH `_shot_progress_entry`'s new
`filled` field and `get_progress`'s own `unfilled_shots`/`completed_shots`
scene counters — calling the real `get_progress` endpoint function
directly (its `Depends(...)`-defaulted params overridden with fakes,
same idiom `test_override_layer.py` uses for the override endpoint),
never a parallel derivation.

A12 lesson, stated again because it is the exact trap here: assert the
PAYLOAD DICT contains `"filled"`, not merely that its value looks right
— a field added to a frontend type but never emitted here is invisible
to TypeScript and silently `undefined` in the browser.

No Postgres, no server; fakes only.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.api.projects as projects_module
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    CreativeContext,
    LayerRole,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
    Timeline,
    TimelineMetadata,
    TimelineStatus,
)
from app.workflow.steps.resolve_assets import layer_prompt_hash

_PROJECT = "66666666-7777-8888-9999-000000000000"
_STYLE = "illustrated_risograph"

_CLIPS_BY_HASH: dict[str, SimpleNamespace] = {}
_BINDINGS: dict[str, SimpleNamespace] = {}


class _FakeProjectRepo:
    def __init__(self, project):
        self._project = project

    async def get(self, project_id):
        return self._project


class _FakeTimelineService:
    def __init__(self, timeline: Timeline):
        self._timeline = timeline

    async def get_active(self, project_id):
        return self._timeline


class _FakeWorkflowRunRepository:
    def __init__(self, _session):
        pass

    async def get_latest(self, _project_uuid):
        return None


class _FakeShotBindingRepository:
    def __init__(self, _session):
        pass

    async def list_for_version(self, _project_uuid, _version):
        return list(_BINDINGS.values())


class _FakeGeneratedClipRepository:
    def __init__(self, _session):
        pass

    async def get_by_prompt_hash(self, prompt_hash: str):
        return _CLIPS_BY_HASH.get(prompt_hash)

    async def total_cost_cents_for_project(self, _project_id):
        return 0


class _FakeNarrationRepository:
    def __init__(self, _session):
        pass

    async def total_cost_cents_for_project(self, _project_id):
        return 0


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    _CLIPS_BY_HASH.clear()
    _BINDINGS.clear()
    monkeypatch.setattr(projects_module, "WorkflowRunRepository", _FakeWorkflowRunRepository)
    monkeypatch.setattr(projects_module, "ShotBindingRepository", _FakeShotBindingRepository)
    monkeypatch.setattr(projects_module, "GeneratedClipRepository", _FakeGeneratedClipRepository)
    monkeypatch.setattr(projects_module, "NarrationRepository", _FakeNarrationRepository)
    yield
    _CLIPS_BY_HASH.clear()
    _BINDINGS.clear()


def _binding(shot_id: str, **overrides) -> SimpleNamespace:
    base = dict(
        shot_id=shot_id,
        asset_id=None,
        clip_id=None,
        state="awaiting_generation",
        rung=None,
        last_error=None,
        secondary_asset_id=None,
        secondary_clip_id=None,
        secondary_state=None,
        secondary_last_error=None,
    )
    base.update(overrides)
    ns = SimpleNamespace(**base)
    _BINDINGS[shot_id] = ns
    return ns


def _parallax_shot(shot_id: str) -> Shot:
    # `layer_prompt_hash` folds in the STYLED PROMPT TEXT, not `shot.id` -
    # two shots sharing identical prompt/layer text would collide on the
    # same hash. Each shot below gets prompt text unique to its own id so
    # `full`'s and `partial`'s clips can never be mistaken for each other.
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt=f"a quiet room, wide shot ({shot_id})",
        camera=Camera(movement=CameraMovement.PARALLAX),
        layers=[
            ShotLayer(role=LayerRole.BACKGROUND, prompt=f"an empty archival room ({shot_id})"),
            ShotLayer(
                role=LayerRole.SUBJECT,
                prompt=f"a seated figure, seen from behind ({shot_id})",
            ),
        ],
    )


def _plain_shot(shot_id: str, *, order: int = 0) -> Shot:
    return Shot(id=shot_id, order=order, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt="plain")


def _timeline(scenes: list[Scene]) -> Timeline:
    return Timeline(
        timeline_id="t1",
        project_id=_PROJECT,
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=scenes,
        metadata=TimelineMetadata(render_style=_STYLE),
        creative_context=CreativeContext(),
    )


def _complete_clip(timeline: Timeline, shot: Shot, layer_index: int, tmp_path: Path) -> None:
    phash = layer_prompt_hash(
        shot,
        shot.layers[layer_index],
        layer_index=layer_index,
        project_uuid=uuid.UUID(timeline.project_id),
        creative_context=timeline.creative_context,
        style=timeline.metadata.render_style,
        frame_aspect=timeline.metadata.frame_aspect,
    )
    path = tmp_path / f"layer_{shot.id}_{layer_index}.png"
    path.write_bytes(b"fake-image-bytes")
    _CLIPS_BY_HASH[phash] = SimpleNamespace(
        status="completed", local_path=str(path), provider="human_override",
        model_id="human_override", error=None,
    )


async def _run_progress(timeline: Timeline, *, expand: str | None = "shots") -> dict:
    project = SimpleNamespace(id=_PROJECT, status="awaiting_approval")
    request = SimpleNamespace(headers={})
    response = await projects_module.get_progress(
        _PROJECT,
        request,
        repo=_FakeProjectRepo(project),
        timeline_service=_FakeTimelineService(timeline),
        session=object(),
        expand=expand,
    )
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_layered_shot_with_all_planes_done_counts_as_completed_not_unfilled(tmp_path):
    """The measured bug, at the /progress layer this time: a parallax
    shot with both planes resolved must drop out of the scene's
    `unfilled_shots` count even while its own `binding.state` is still
    `awaiting_generation` forever (no per-layer binding column)."""
    full = _parallax_shot("sh_full")
    partial = _parallax_shot("sh_partial")
    resolved_plain = _plain_shot("sh_plain_ok", order=1)
    scene_a = Scene(
        id="sc_a", order=0, title="A", duration_s=9.0, shots=[full, partial, resolved_plain]
    )
    pending_plain = _plain_shot("sh_plain_pending", order=0)
    scene_b = Scene(id="sc_b", order=1, title="B", duration_s=3.0, shots=[pending_plain])
    timeline = _timeline([scene_a, scene_b])

    _complete_clip(timeline, full, 0, tmp_path)
    _complete_clip(timeline, full, 1, tmp_path)
    _complete_clip(timeline, partial, 0, tmp_path)
    # partial's layer 1 is never inserted - clip repo returns None for it.

    _binding("sh_full", state="awaiting_generation")
    _binding("sh_partial", state="awaiting_generation")
    _binding("sh_plain_ok", state="resolved", asset_id=None)
    _binding("sh_plain_pending", state="awaiting_generation")

    payload = await _run_progress(timeline)

    scenes_by_id = {s["id"]: s for s in payload["scenes"]}
    assert scenes_by_id["sc_a"]["total_shots"] == 3
    assert scenes_by_id["sc_a"]["completed_shots"] == 2  # sh_full + sh_plain_ok
    assert scenes_by_id["sc_a"]["unfilled_shots"] == 1  # sh_partial only
    assert scenes_by_id["sc_b"]["total_shots"] == 1
    assert scenes_by_id["sc_b"]["completed_shots"] == 0
    assert scenes_by_id["sc_b"]["unfilled_shots"] == 1

    shots_by_id = {s["shot_id"]: s for s in payload["shots"]}
    # A12: the field must be IN the payload dict, not merely correct in value.
    for shot_id in ("sh_full", "sh_partial", "sh_plain_ok", "sh_plain_pending"):
        assert "filled" in shots_by_id[shot_id], shot_id

    assert shots_by_id["sh_full"]["filled"] is True
    assert shots_by_id["sh_full"]["state"] == "awaiting_generation"  # state stays honest
    assert shots_by_id["sh_partial"]["filled"] is False
    assert shots_by_id["sh_plain_ok"]["filled"] is True
    assert shots_by_id["sh_plain_pending"]["filled"] is False


@pytest.mark.asyncio
async def test_parallax_with_empty_layers_is_unaffected(tmp_path):
    """A `movement=parallax` shot with `layers=[]` (capped by
    `_cap_parallax_layers`) must still fall back to `binding.state` -
    never wrongly cleared by the layer path."""
    shot = _parallax_shot("sh_capped")
    shot.layers = []
    scene = Scene(id="sc_a", order=0, title="A", duration_s=3.0, shots=[shot])
    timeline = _timeline([scene])
    _binding("sh_capped", state="awaiting_generation")

    payload = await _run_progress(timeline)
    scene_payload = payload["scenes"][0]
    assert scene_payload["unfilled_shots"] == 1
    assert scene_payload["completed_shots"] == 0
    shot_payload = payload["shots"][0]
    assert shot_payload["filled"] is False


@pytest.mark.asyncio
async def test_plain_shot_behaviour_unchanged():
    shot = _plain_shot("sh_plain")
    scene = Scene(id="sc_a", order=0, title="A", duration_s=3.0, shots=[shot])
    timeline = _timeline([scene])
    _binding("sh_plain", state="resolved")

    payload = await _run_progress(timeline)
    assert payload["scenes"][0]["completed_shots"] == 1
    assert payload["scenes"][0]["unfilled_shots"] == 0
    assert payload["shots"][0]["filled"] is True
