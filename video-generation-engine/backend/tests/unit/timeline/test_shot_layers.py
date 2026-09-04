"""`Shot.layers`/`ShotLayer`/`CameraMovement.PARALLAX`
(illustrated_faceless.md §2.2/F2).

Three things this file must prove, per the plan's own isolation section
(§3.1): `layers` defaults to empty and empty means today's behaviour
exactly; `layers` and split-screen's `secondary_prompt`/
`secondary_asset_plan` are mutually exclusive, both directions (§6 Q1);
and nothing in the renderer's existing composition modules has been
wired to read `Shot.layers` yet (F2 ships the schema + a standalone
`parallax.py`, not the render.py seam - proven by source inspection
rather than merely asserted, matching this codebase's own precedent for
"is X actually wired in" claims).
"""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    Camera,
    CameraMovement,
    LayerRole,
    Shot,
    ShotIntent,
    ShotLayer,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND = _REPO_ROOT / "backend"


def _shot(**overrides) -> Shot:
    fields = {"id": "sh_01", "order": 0, "intent": ShotIntent.EXPLAIN, "duration_s": 3.0}
    fields.update(overrides)
    return Shot(**fields)


# -- defaults / isolation (§3.1) --------------------------------------------


def test_layers_defaults_to_empty():
    assert _shot().layers == []


def test_empty_layers_dumps_as_an_empty_list_not_omitted():
    """Pydantic includes the default in `model_dump` - this is the §3.4-
    shaped one-time fingerprint leak the plan already accepts for
    `frame_aspect`/`grade_style`/`caption_romanization_attempted`, logged
    rather than hidden. Pinning the shape here so a future change to that
    default is a deliberate, reviewed decision."""
    assert _shot().model_dump(mode="json")["layers"] == []


@pytest.mark.parametrize(
    "style",
    ["documentary_archival", "retention_fast", "archival_montage", "stillness"],
)
def test_layers_defaults_to_empty_regardless_of_which_pre_existing_style_a_shot_belongs_to(style):
    """`Shot` carries no style of its own (style lives on
    `TimelineMetadata.render_style`), so this is really "constructing a
    shot the way each of the four pre-F2 styles already does (no
    `layers` kwarg) still yields empty layers" - the isolation claim
    made concrete for all four, not just one representative shot."""
    shot = _shot(prompt=f"a shot for {style}", camera=Camera(movement=CameraMovement.SLOW_PUSH))
    assert shot.layers == []


def test_camera_movement_still_has_every_pre_f2_value_unchanged():
    """Adding PARALLAX must not renumber or rename anything already in
    use - StrEnum values are the actual persisted/hashed strings."""
    assert CameraMovement.STATIC == "static"
    assert CameraMovement.SLOW_ZOOM == "slow_zoom"
    assert CameraMovement.SLOW_PUSH == "slow_push"
    assert CameraMovement.PULL_BACK == "pull_back"
    assert CameraMovement.PAN == "pan"
    assert CameraMovement.SPLIT_FRAME == "split_frame"
    assert CameraMovement.PUNCH_IN == "punch_in"


def test_camera_movement_parallax_is_a_new_real_value():
    assert CameraMovement.PARALLAX == "parallax"
    assert CameraMovement.PARALLAX in list(CameraMovement)


# -- ShotLayer shape ----------------------------------------------------


def test_shot_layer_carries_role_prompt_asset_plan_and_drift_scale():
    layer = ShotLayer(
        role=LayerRole.SUBJECT,
        prompt="a student, seen from behind",
        asset_plan=AssetPlan(strategy=AssetStrategy.GENERATE_IMAGE),
        drift_x=110.0,
        drift_y=0.0,
        scale=1.2,
    )
    assert layer.role is LayerRole.SUBJECT
    assert layer.asset_plan.strategy == AssetStrategy.GENERATE_IMAGE


def test_shot_layer_scale_must_exceed_one():
    """§2.2/parallax_probe.py: a layer must be generated oversized so
    there is room to drift without exposing a frame edge - scale <= 1.0
    has nowhere to travel."""
    with pytest.raises(ValidationError):
        ShotLayer(role=LayerRole.BACKGROUND, scale=1.0)
    with pytest.raises(ValidationError):
        ShotLayer(role=LayerRole.BACKGROUND, scale=0.5)


def test_shot_layer_defaults_are_the_probes_own_measured_values():
    layer = ShotLayer(role=LayerRole.BACKGROUND)
    assert layer.prompt == ""
    assert layer.asset_plan is None
    assert layer.drift_x == 0.0
    assert layer.drift_y == 0.0
    assert layer.scale == 1.2  # parallax_probe.py's own `_OVER`


def test_layer_roles_are_background_subject_foreground():
    assert {r.value for r in LayerRole} == {"background", "subject", "foreground"}


# -- mutual exclusion (§6 Q1), both directions -------------------------


def test_layers_and_secondary_prompt_are_mutually_exclusive():
    layers = [ShotLayer(role=LayerRole.BACKGROUND), ShotLayer(role=LayerRole.SUBJECT)]
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _shot(layers=layers, secondary_prompt="the bottom panel")


def test_layers_and_secondary_asset_plan_are_mutually_exclusive():
    layers = [ShotLayer(role=LayerRole.BACKGROUND), ShotLayer(role=LayerRole.SUBJECT)]
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _shot(
            layers=layers,
            secondary_asset_plan=AssetPlan(strategy=AssetStrategy.GENERATE_IMAGE),
        )


def test_layers_alone_is_legal():
    layers = [ShotLayer(role=LayerRole.BACKGROUND), ShotLayer(role=LayerRole.SUBJECT)]
    shot = _shot(layers=layers)
    assert len(shot.layers) == 2


def test_secondary_prompt_alone_is_still_legal_split_frame_is_untouched():
    """The DO-NOT list forbids touching split_frame/secondary_prompt
    beyond this validator - proving the existing split-screen path is
    still fully legal on its own."""
    shot = _shot(
        camera=Camera(movement=CameraMovement.SPLIT_FRAME),
        secondary_prompt="the bottom panel",
        secondary_asset_plan=AssetPlan(strategy=AssetStrategy.GENERATE_IMAGE),
    )
    assert shot.layers == []
    assert shot.secondary_prompt == "the bottom panel"


def test_empty_layers_list_does_not_trip_the_validator_even_with_secondary_prompt_set():
    """`layers=[]` (falsy) must behave exactly like `layers` never having
    been set - the isolation mechanism is "empty means off", not
    "field present means off"."""
    shot = _shot(layers=[], secondary_prompt="the bottom panel")
    assert shot.layers == []
    assert shot.secondary_prompt == "the bottom panel"


# -- F2 ships schema + a standalone renderer module, nothing wired yet --


@pytest.mark.parametrize(
    "relative_path",
    [
        "app/renderer/ken_burns.py",
        "app/renderer/split_screen.py",
        "app/renderer/slideshow.py",
    ],
)
def test_existing_composition_modules_do_not_yet_reference_shot_layers(relative_path):
    """Source-inspection, not a behavioural assumption: proves the
    isolation claim ("F2 does not wire parallax.py into the existing
    composition pass yet") is a fact about the code, not merely a plan
    statement. `render.py` is checked separately below since the brief
    forbids editing it, not reading it."""
    text = (_BACKEND / relative_path).read_text(encoding="utf-8")
    assert not re.search(r"\.layers\b", text), f"{relative_path} already references .layers"


def test_render_py_does_not_yet_reference_shot_layers():
    """render.py is off-limits to edit in this pass (uncommitted A15 work
    lives there) - this only reads it to confirm F2 has not silently
    become live without the render.py wiring the plan says a later task
    must do."""
    text = (_BACKEND / "app/workflow/steps/render.py").read_text(encoding="utf-8")
    assert not re.search(r"\.layers\b", text)
