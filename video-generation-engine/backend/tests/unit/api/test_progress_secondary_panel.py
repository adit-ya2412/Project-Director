"""P3a (docs/plans/gate_panel_overrides.md): `_shot_progress_entry` gains
the split-screen bottom panel. `panel=secondary` has worked server-side
(override + asset serving) since R16, but this payload never said a shot
WAS `split_frame`, let alone anything about its bottom panel - the
browser had nothing to render a second upload slot from.

This is the PAYLOAD test the function's own docstring-comment demands
(A12, 2026-09-02): that mistake was a frontend field with no backend
counterpart, invisible because `TypeScript` types describe the API but
never verify it. Asserting against the dict `_shot_progress_entry`
actually returns - not the frontend `Shot` type - is what would have
caught it.

Calls `_shot_progress_entry` directly with hand-built fakes, the same
idiom `test_secondary_panel_done.py`/`test_override_panel.py` already use
for this file's other pure-ish helpers - no FastAPI routing, no
Postgres, safe under `--noconftest`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.projects import _shot_progress_entry
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
from app.schemas.timeline import Camera, CameraMovement, Shot, ShotIntent


class _FakeSession:
    """Stands in for `AsyncSession.get` - keyed on the SQLAlchemy model
    class exactly like the real thing, so a test that supplies the wrong
    id under the wrong model fails loudly instead of returning the wrong
    row silently."""

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


async def _entry(shot, binding, session=None):
    return await _shot_progress_entry(
        session or _FakeSession(),
        scene=_scene(),
        shot=shot,
        binding=binding,
        locked=False,
        start_times={},
    )


@pytest.mark.asyncio
async def test_non_split_shot_has_no_secondary_and_is_otherwise_unchanged():
    """The common case - regression guard (item 3 of the brief): a shot
    that was never split_frame must look exactly as it did before this
    change, plus the two new, harmless fields."""
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt="a coal mine")
    entry = await _entry(shot, _binding())

    assert entry["camera_movement"] == "static"
    assert entry["secondary"] is None
    # Every field the payload returned before P3a, unmoved.
    assert entry["prompt"] == "a coal mine"
    assert entry["asset"] is None
    assert entry["clip"] is None
    assert entry["shot_id"] == "sh_01"


@pytest.mark.asyncio
async def test_split_frame_shot_reports_split_even_with_empty_layers():
    """Only the ONE meaningful signal - camera.movement - decides
    `secondary`'s presence, never binding state. A split_frame shot whose
    bottom panel has not even been searched yet must still be
    distinguishable from a shot that was never split_frame at all."""
    shot = Shot(
        id="sh_split",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=3.0,
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
        prompt="top: a factory",
        secondary_prompt="bottom: a farm",
    )
    entry = await _entry(shot, _binding(secondary_state="pending"))

    assert entry["camera_movement"] == "split_frame"
    assert entry["secondary"] is not None
    assert entry["secondary"]["prompt"] == "bottom: a farm"
    assert entry["secondary"]["state"] == "pending"
    assert entry["secondary"]["last_error"] is None
    # Unresolved - distinguishable from "not split_frame" (None above) by
    # the presence of the dict, and from "resolved" by these being None.
    assert entry["secondary"]["asset"] is None
    assert entry["secondary"]["clip"] is None


@pytest.mark.asyncio
async def test_split_frame_secondary_asset_resolves_independently_of_primary():
    """The primary and secondary halves are genuinely independent - a
    split shot whose TOP panel is still awaiting generation but whose
    BOTTOM panel already resolved to an uploaded asset must show both
    states at once, matching what `apply_override_to_binding` actually
    writes for a `panel=secondary` override."""
    shot = Shot(
        id="sh_split",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=3.0,
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
        prompt="top: a factory",
        secondary_prompt="bottom: a farm",
    )
    session = _FakeSession(
        assets={
            "bottom-asset": SimpleNamespace(
                provider="project_assets",
                source_url=None,
                licence="human_override",
                attribution=None,
                local_path="/tmp/bottom.png",
            )
        }
    )
    binding = _binding(
        state="awaiting_generation",
        secondary_asset_id="bottom-asset",
        secondary_state="resolved",
    )
    entry = await _entry(shot, binding, session)

    assert entry["will_generate"] is True  # primary still pending generation
    assert entry["asset"] is None  # primary has no asset bound yet
    assert entry["secondary"]["state"] == "resolved"
    assert entry["secondary"]["asset"] == {
        "provider": "project_assets",
        "source_url": None,
        "licence": "human_override",
        "attribution": None,
        "local_path": "/tmp/bottom.png",
    }
    assert entry["secondary"]["clip"] is None


@pytest.mark.asyncio
async def test_split_frame_secondary_last_error_survives_a_failed_upload_or_generation():
    """R18's own point, carried into this payload: 'attempted and failed'
    must not look like 'never attempted' to a human at the gate either."""
    shot = Shot(
        id="sh_split",
        order=0,
        intent=ShotIntent.COMPARE,
        duration_s=3.0,
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
        prompt="top",
        secondary_prompt="bottom",
    )
    binding = _binding(secondary_state="failed", secondary_last_error="fal.ai timed out")
    entry = await _entry(shot, binding)

    assert entry["secondary"]["state"] == "failed"
    assert entry["secondary"]["last_error"] == "fal.ai timed out"
