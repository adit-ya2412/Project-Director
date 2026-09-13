"""gate_panel_overrides.md §7.5 addendum (2026-09-13): `_unfilled_shot_ids`
(`app/api/projects.py`) used to read only `binding.state`. A layer plane
(`Shot.layers`) has no per-layer binding column - uploading or generating
one never touches `binding.state` at all, so a shot with every plane
already `completed` still reported as unfilled forever. Measured live on
project `48086fed-02a0-46ba-be58-e2c5cf99db9e`: 11 shots blocked, 10 of
which already had both layer clips done.

This suite calls `_unfilled_shot_ids` directly - same idiom as
`test_progress_layer_panels.py`'s `_shot_progress_entry` tests - with a
monkeypatched `GeneratedClipRepository` (module-level, so the function's
own internal `GeneratedClipRepository(session)` construction is faked)
rather than going through HTTP. No Postgres, no server, no paid provider.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.api.projects as projects_module
from app.api.projects import _TERMINAL_SHOT_STATES, _unfilled_shot_ids
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

_PROJECT = "11111111-2222-3333-4444-555555555555"
_STYLE = "illustrated_risograph"


class _FakeGeneratedClipRepository:
    """Constructed with `(session)` exactly like the real repository -
    `_unfilled_shot_ids` builds one internally via
    `GeneratedClipRepository(session)`, so this stands in for that class,
    not an instance handed in."""

    def __init__(self, _session):
        pass

    async def get_by_prompt_hash(self, prompt_hash: str):
        return _CLIPS_BY_HASH.get(prompt_hash)


_CLIPS_BY_HASH: dict[str, SimpleNamespace] = {}


@pytest.fixture(autouse=True)
def _clip_repo(monkeypatch):
    _CLIPS_BY_HASH.clear()
    monkeypatch.setattr(projects_module, "GeneratedClipRepository", _FakeGeneratedClipRepository)
    yield
    _CLIPS_BY_HASH.clear()


def _completed_clip(local_path, *, status: str = "completed") -> SimpleNamespace:
    """`resolved_layer_clips` requires the file to actually exist on disk
    (a stale DB row pointing at a deleted file is not a usable image
    either) - callers pass a real path under `tmp_path` and this writes
    placeholder bytes there so that check passes for a genuinely-present
    plane."""
    path = Path(local_path)
    path.write_bytes(b"fake-image-bytes")
    return SimpleNamespace(status=status, local_path=str(path))


def _parallax_shot(shot_id: str = "sh_01", *, layers: list[ShotLayer] | None = None) -> Shot:
    if layers is None:
        layers = [
            ShotLayer(role=LayerRole.BACKGROUND, prompt="an empty archival room"),
            ShotLayer(role=LayerRole.SUBJECT, prompt="a seated figure, seen from behind"),
        ]
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="a quiet room, wide shot",
        camera=Camera(movement=CameraMovement.PARALLAX),
        layers=layers,
    )


def _plain_shot(shot_id: str = "sh_plain") -> Shot:
    return Shot(id=shot_id, order=1, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt="plain")


def _timeline(shots: list[Shot]) -> Timeline:
    scene = Scene(
        id="sc_01", order=0, title="S", duration_s=sum(s.duration_s for s in shots), shots=shots
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


def _binding(state: str) -> SimpleNamespace:
    return SimpleNamespace(state=state)


def _hash_for(timeline: Timeline, shot: Shot, layer_index: int) -> str:
    return layer_prompt_hash(
        shot,
        shot.layers[layer_index],
        layer_index=layer_index,
        project_uuid=uuid.UUID(timeline.project_id),
        creative_context=timeline.creative_context,
        style=timeline.metadata.render_style,
        frame_aspect=timeline.metadata.frame_aspect,
    )


@pytest.mark.asyncio
async def test_parallax_shot_with_both_layers_completed_is_filled(tmp_path):
    """The measured bug: binding never leaves `awaiting_generation` for a
    layered shot, but both planes are done - must not be reported unfilled."""
    shot = _parallax_shot()
    timeline = _timeline([shot])
    _CLIPS_BY_HASH[_hash_for(timeline, shot, 0)] = _completed_clip(tmp_path / "bg.png")
    _CLIPS_BY_HASH[_hash_for(timeline, shot, 1)] = _completed_clip(tmp_path / "subj.png")
    bindings = {shot.id: _binding("awaiting_generation")}

    unfilled = await _unfilled_shot_ids(
        [shot], bindings, timeline=timeline, session=object()
    )

    assert unfilled == []


@pytest.mark.asyncio
async def test_parallax_shot_with_one_layer_missing_still_unfilled(tmp_path):
    """`act_02_sc_03_sh_03`-shaped case: layer 0 present, layer 1 absent.
    A partial set cannot be composited - must keep blocking."""
    shot = _parallax_shot()
    timeline = _timeline([shot])
    _CLIPS_BY_HASH[_hash_for(timeline, shot, 0)] = _completed_clip(tmp_path / "bg.png")
    # layer 1's hash is simply never inserted - clip repo returns None.
    bindings = {shot.id: _binding("awaiting_generation")}

    unfilled = await _unfilled_shot_ids(
        [shot], bindings, timeline=timeline, session=object()
    )

    assert unfilled == [shot.id]


@pytest.mark.asyncio
async def test_parallax_shot_with_a_non_completed_layer_clip_still_unfilled(tmp_path):
    """A `submitted`/`failed`/`rejected` row is not a usable image even
    though it exists - only `status == "completed"` counts."""
    shot = _parallax_shot()
    timeline = _timeline([shot])
    _CLIPS_BY_HASH[_hash_for(timeline, shot, 0)] = _completed_clip(tmp_path / "bg.png")
    _CLIPS_BY_HASH[_hash_for(timeline, shot, 1)] = _completed_clip(
        tmp_path / "subj.png", status="failed"
    )
    bindings = {shot.id: _binding("awaiting_generation")}

    unfilled = await _unfilled_shot_ids(
        [shot], bindings, timeline=timeline, session=object()
    )

    assert unfilled == [shot.id]


@pytest.mark.asyncio
async def test_parallax_movement_with_empty_layers_falls_back_to_binding_state():
    """`_cap_parallax_layers` leaves plenty of shots at `movement=parallax`
    with `layers=[]` - rendered as a plain still needing its ordinary
    primary image. Gating on `camera.movement` instead of `shot.layers`
    would wrongly treat these 19-shots-on-the-measured-project as filled."""
    shot = _parallax_shot(layers=[])
    timeline = _timeline([shot])
    bindings = {shot.id: _binding("awaiting_generation")}

    unfilled = await _unfilled_shot_ids(
        [shot], bindings, timeline=timeline, session=object()
    )

    assert unfilled == [shot.id]

    # And once the binding itself reaches a terminal state, it clears -
    # exactly the pre-existing, unchanged behaviour for a plain shot.
    bindings[shot.id] = _binding("resolved")
    unfilled = await _unfilled_shot_ids(
        [shot], bindings, timeline=timeline, session=object()
    )
    assert unfilled == []


@pytest.mark.asyncio
async def test_plain_non_layer_shot_behaviour_is_unchanged():
    shot = _plain_shot()
    timeline = _timeline([shot])

    # No binding at all.
    unfilled = await _unfilled_shot_ids([shot], {}, timeline=timeline, session=object())
    assert unfilled == [shot.id]

    # Non-terminal binding state.
    bindings = {shot.id: _binding("awaiting_generation")}
    unfilled = await _unfilled_shot_ids(
        [shot], bindings, timeline=timeline, session=object()
    )
    assert unfilled == [shot.id]

    # Terminal binding states clear it, matching _TERMINAL_SHOT_STATES.
    for state in _TERMINAL_SHOT_STATES:
        bindings = {shot.id: _binding(state)}
        unfilled = await _unfilled_shot_ids(
            [shot], bindings, timeline=timeline, session=object()
        )
        assert unfilled == []

    # The fake clip repo must never even be consulted for a shot with no
    # layers - nothing was ever inserted into _CLIPS_BY_HASH here, and the
    # assertions above already passed without it.
