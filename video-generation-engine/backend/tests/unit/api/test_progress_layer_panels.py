"""P3b (docs/plans/gate_panel_overrides.md): `_shot_progress_entry` emits
`layers` so the gate can render plane upload slots.

Same A12 lesson as P3a's `secondary`: inventing a frontend field with no
backend counterpart is invisible to TypeScript. Assert against the dict
`_shot_progress_entry` returns — never the frontend type.

Calls `_shot_progress_entry` directly with hand-built fakes. Fake
`GeneratedClipRepository` for hash lookup (no binding column). No
Postgres, safe under `--noconftest`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import app.api.projects as projects_module
from app.api.projects import _shot_progress_entry
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
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
from app.script.styles import resolve_render_format
from app.workflow.steps.resolve_assets import layer_prompt_hash, layer_styled_prompt

_PROJECT = "55555555-5555-5555-5555-555555555555"
_STYLE = "illustrated_risograph"


class _FakeSession:
    def __init__(self, assets: dict | None = None, clips: dict | None = None):
        self._assets = assets or {}
        self._clips = clips or {}

    async def get(self, model, id_):
        if model is AssetModel:
            return self._assets.get(id_)
        if model is GeneratedClipModel:
            return self._clips.get(id_)
        raise AssertionError(f"unexpected model {model!r}")


def _scene():
    return SimpleNamespace(id="sc_01", narration_text="unused")


def _binding(**overrides) -> SimpleNamespace:
    base = dict(
        shot_id="sh_01",
        state="resolved",
        rung="project_assets",
        last_error=None,
        asset_id=None,
        clip_id=None,
        secondary_asset_id=None,
        secondary_clip_id=None,
        secondary_state=None,
        secondary_last_error=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _parallax_shot(shot_id: str = "sh_01") -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="a quiet room, wide shot",
        camera=Camera(movement=CameraMovement.PARALLAX),
        layers=[
            ShotLayer(role=LayerRole.BACKGROUND, prompt="an empty archival room"),
            ShotLayer(role=LayerRole.SUBJECT, prompt="a seated figure, seen from behind"),
        ],
    )


def _timeline(*, shots: list[Shot] | None = None) -> Timeline:
    if shots is None:
        shots = [_parallax_shot()]
    scene = Scene(
        id="sc_01",
        order=0,
        title="S",
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
    )
    return Timeline(
        timeline_id="t1",
        project_id=_PROJECT,
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
        metadata=TimelineMetadata(render_style=_STYLE),
        creative_context=CreativeContext(),
    )


async def _entry(shot, binding, *, timeline=None, session=None, clips_by_hash=None, monkeypatch=None):
    if clips_by_hash is not None:
        assert monkeypatch is not None

        class _FakeClipRepo:
            def __init__(self, _session):
                pass

            async def get_by_prompt_hash(self, prompt_hash: str):
                return clips_by_hash.get(prompt_hash)

        monkeypatch.setattr(projects_module, "GeneratedClipRepository", _FakeClipRepo)

    return await _shot_progress_entry(
        session or _FakeSession(),
        scene=_scene(),
        shot=shot,
        binding=binding,
        locked=False,
        start_times={},
        timeline=timeline,
    )


@pytest.mark.asyncio
async def test_plain_and_split_frame_shots_have_layers_none():
    """Non-parallax shots — including split_frame — must not invent plane
    slots. Presence of the list is the frontend's only signal."""
    plain = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt="plain")
    plain_entry = await _entry(plain, _binding())
    assert plain_entry["layers"] is None
    assert plain_entry["secondary"] is None

    split = Shot(
        id="sh_split",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=3.0,
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
        prompt="top",
        secondary_prompt="bottom",
    )
    split_entry = await _entry(split, _binding(secondary_state="pending"), timeline=_timeline(shots=[split]))
    assert split_entry["layers"] is None
    assert split_entry["secondary"] is not None


@pytest.mark.asyncio
async def test_parallax_shot_emits_two_layers_with_styled_prompts(monkeypatch):
    """Two ShotLayers, no clips → 2-list; prompts are layer_styled_prompt
    (assert by calling that function, never a hardcoded string)."""
    shot = _parallax_shot()
    timeline = _timeline(shots=[shot])
    entry = await _entry(
        shot,
        _binding(shot_id=shot.id),
        timeline=timeline,
        clips_by_hash={},
        monkeypatch=monkeypatch,
    )

    assert entry["layers"] is not None
    assert len(entry["layers"]) == 2
    frame = resolve_render_format(
        timeline.metadata.render_style,
        frame_aspect=timeline.metadata.frame_aspect,
    )
    for index, layer in enumerate(shot.layers):
        row = entry["layers"][index]
        assert row["index"] == index
        assert row["role"] == layer.role.value
        assert row["prompt"] == layer_styled_prompt(
            shot, layer, timeline.creative_context, frame=frame
        )
        assert row["state"] is None
        assert row["last_error"] is None
        assert row["asset"] is None
        assert row["clip"] is None


@pytest.mark.asyncio
async def test_completed_layer1_clip_resolves_independently(monkeypatch):
    """A completed clip under layer:1's hash fills that entry only;
    layer:0 stays empty — planes are independent, same as primary vs
    secondary."""
    shot = _parallax_shot()
    timeline = _timeline(shots=[shot])
    layer1_hash = layer_prompt_hash(
        shot,
        shot.layers[1],
        layer_index=1,
        project_uuid=uuid.UUID(timeline.project_id),
        creative_context=timeline.creative_context,
        style=timeline.metadata.render_style,
        frame_aspect=timeline.metadata.frame_aspect,
    )
    clips = {
        layer1_hash: SimpleNamespace(
            provider="human_override",
            model_id="human_override",
            status="completed",
            local_path="/tmp/layer1.png",
            error=None,
        )
    }
    entry = await _entry(
        shot,
        _binding(shot_id=shot.id),
        timeline=timeline,
        clips_by_hash=clips,
        monkeypatch=monkeypatch,
    )

    assert entry["layers"][0]["state"] is None
    assert entry["layers"][0]["clip"] is None
    assert entry["layers"][1]["state"] == "generated"
    assert entry["layers"][1]["clip"] == {
        "provider": "human_override",
        "model_id": "human_override",
        "status": "completed",
        "local_path": "/tmp/layer1.png",
    }


@pytest.mark.asyncio
async def test_parallax_without_timeline_emits_layers_none():
    """timeline defaults to None so older call sites still run; without
    it there is no creative_context/style to style prompts or hash, so
    layers stays None rather than inventing unstyled raw prompts."""
    shot = _parallax_shot()
    entry = await _entry(shot, _binding(shot_id=shot.id))
    assert entry["layers"] is None
