"""`_cap_parallax_layers` - the project-wide parallax layer budget (§4.3,
illustrated_faceless.md F2a).

Same class of pass as `_cap_glitch_transitions`/`_cap_text_cards`/
`_cap_sfx_cues`: the Shot Planner is called ONCE PER SCENE and cannot see
how many layers other scenes already spent, so a whole-project cost cap
cannot be enforced in the prompt alone. Pure, no DB, no LLM - run with
`--noconftest`.
"""

from app.planners.shot.planner import _cap_parallax_layers
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    LayerRole,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
    Transition,
    TransitionType,
)

_LAYERS = [
    ShotLayer(role=LayerRole.BACKGROUND, prompt="a room"),
    ShotLayer(role=LayerRole.SUBJECT, prompt="a figure"),
]


def _shot(idx: int, *, layers: list[ShotLayer] | None = None, id_prefix: str = "") -> Shot:
    movement = CameraMovement.PARALLAX if layers else CameraMovement.STATIC
    return Shot(
        id=f"{id_prefix}sh_{idx:02d}",
        order=idx,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(movement=movement),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
        layers=list(layers or []),
    )


def _scene(sid: str, layered_flags: list[bool]) -> Scene:
    return Scene(
        id=sid,
        order=0,
        title=sid,
        duration_s=float(2 * len(layered_flags)),
        shots=[
            _shot(i, layers=_LAYERS if flag else None, id_prefix=f"{sid}_")
            for i, flag in enumerate(layered_flags)
        ],
    )


def _layered_shot_ids(scenes: list[Scene]) -> list[str]:
    return [s.id for sc in scenes for s in sc.shots if s.layers]


def test_under_cap_is_byte_identical():
    scenes = [_scene("sc_01", [True, False, True])]
    out = _cap_parallax_layers(scenes, max_layers=10)
    for sc, orig_sc in zip(out, scenes, strict=True):
        for shot, orig_shot in zip(sc.shots, orig_sc.shots, strict=True):
            assert shot.layers == orig_shot.layers
            assert shot is orig_shot  # never even model_copy'd


def test_a_project_with_no_layers_is_unaffected():
    scenes = [_scene("sc_01", [False, False]), _scene("sc_02", [False])]
    out = _cap_parallax_layers(scenes, max_layers=2)
    assert _layered_shot_ids(out) == []


def test_excess_layers_are_cleared_keeping_the_first_shots():
    """4 layered shots x 2 layers = 8 layers, capped at 4 -> only the
    first 2 layered shots (4 layers) survive."""
    scenes = [_scene("sc_01", [True, True, True, True])]
    out = _cap_parallax_layers(scenes, max_layers=4)
    assert _layered_shot_ids(out) == ["sc_01_sh_00", "sc_01_sh_01"]
    # Cleared shots keep their movement (a documented, unguarded no-op -
    # the same degrade an under-specified SPLIT_FRAME shot already takes)
    # but their layers are gone.
    cleared = [s for s in out[0].shots if not s.layers]
    assert len(cleared) == 2
    for shot in cleared:
        assert shot.camera.movement == CameraMovement.PARALLAX
        assert shot.layers == []


def test_the_budget_is_enforced_project_wide_not_per_scene():
    """The whole point: two scenes that are each individually within
    budget (one parallax shot apiece, 2 layers) are still too many
    together once a THIRD scene also wants one - a per-scene rule cannot
    see this; this pass can."""
    scenes = [
        _scene("sc_01", [True]),
        _scene("sc_02", [True]),
        _scene("sc_03", [True]),
    ]
    out = _cap_parallax_layers(scenes, max_layers=4)
    # Only the first two scenes' parallax shots survive (4 layers total);
    # the third scene's own shot is cleared even though, seen alone, it
    # never exceeded anything.
    assert _layered_shot_ids(out) == ["sc_01_sh_00", "sc_02_sh_00"]


def test_a_shot_never_loses_only_one_of_its_two_layers():
    """`parallax.py`'s two-layer builder rejects anything but exactly
    [background, subject] - the cap must clear a whole shot's layers,
    never leave a lone layer behind."""
    scenes = [_scene("sc_01", [True, True])]
    out = _cap_parallax_layers(scenes, max_layers=3)
    for shot in out[0].shots:
        assert len(shot.layers) in (0, 2)


def test_log_records_the_budget_exceeded_event(caplog):
    scenes = [_scene("sc_01", [True, True, True])]
    with caplog.at_level("WARNING"):
        _cap_parallax_layers(scenes, max_layers=2)
    records = [
        r
        for r in caplog.records
        if r.message == "shot_planner.parallax_layer_budget_exceeded_downgrading"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.max_layers == 2
    assert record.planned_layers == 6
    assert record.kept_layers == 2
    assert record.cleared_shots == 2
