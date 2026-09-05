"""`_cap_layer_entries` — the project-wide layer-entry spacing pass (F4,
illustrated_faceless.md §2/F4).

Same class of pass as `_cap_text_cards`/`_cap_sfx_cues` (a spacing cap on a
NARRATIVE-frequency device, deliberately NOT shaped like `_cap_parallax_
layers` — that one bounds a real COST, an entry costs nothing beyond the
two-layer shot it already sits on): the illustrated_risograph fragment's
own rate cue asks for a timed entry "on roughly one parallax shot in three
at most", but the Shot Planner is called ONCE PER SCENE and cannot see
whether another scene already reached for one. Pure, no DB, no LLM — run
with `--noconftest`.
"""

from app.planners.shot.planner import _cap_layer_entries
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


def _layers(entry: int | None) -> list[ShotLayer]:
    return [
        ShotLayer(role=LayerRole.BACKGROUND, prompt="a room"),
        ShotLayer(role=LayerRole.SUBJECT, prompt="a figure", enter_on_fragment=entry),
    ]


def _shot(
    idx: int, *, entry: int | None = None, parallax: bool = False, id_prefix: str = ""
) -> Shot:
    is_parallax = parallax or entry is not None
    return Shot(
        id=f"{id_prefix}sh_{idx:02d}",
        order=idx,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(movement=CameraMovement.PARALLAX if is_parallax else CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
        layers=_layers(entry) if is_parallax else [],
    )


def _scene(sid: str, entries: list[int | None]) -> Scene:
    return Scene(
        id=sid,
        order=0,
        title=sid,
        duration_s=float(2 * len(entries)),
        shots=[_shot(i, entry=e, id_prefix=f"{sid}_") for i, e in enumerate(entries)],
    )


def _entry_shot_ids(scenes: list[Scene]) -> list[str]:
    return [
        s.id
        for sc in scenes
        for s in sc.shots
        if any(layer.enter_on_fragment is not None for layer in s.layers)
    ]


def test_under_cap_is_byte_identical():
    # Ten shots separate the two entries - exactly `min_gap`, so both
    # survive untouched.
    scenes = [_scene("sc_01", [1, *([None] * 10), 2])]
    out = _cap_layer_entries(scenes, min_gap=10)
    for sc, orig_sc in zip(out, scenes, strict=True):
        for shot, orig_shot in zip(sc.shots, orig_sc.shots, strict=True):
            assert shot.layers == orig_shot.layers
            assert shot is orig_shot  # never even model_copy'd


def test_a_project_with_no_entries_is_unaffected():
    scenes = [_scene("sc_01", [None, None]), _scene("sc_02", [None])]
    out = _cap_layer_entries(scenes, min_gap=2)
    assert _entry_shot_ids(out) == []


def test_entries_closer_than_the_gap_are_cleared_but_the_layer_survives():
    scenes = [_scene("sc_01", [1, 2, None, None, None])]
    out = _cap_layer_entries(scenes, min_gap=4)
    assert _entry_shot_ids(out) == ["sc_01_sh_00"]
    # The SECOND shot's entry is cleared, but it is still a two-layer
    # parallax shot - only the timed reveal degrades to "present from the
    # start" (§3.1's own graceful-degrade shape), never the layer or the
    # movement.
    cleared = out[0].shots[1]
    assert cleared.camera.movement == CameraMovement.PARALLAX
    assert len(cleared.layers) == 2
    assert cleared.layers[1].enter_on_fragment is None


def test_spacing_is_enforced_across_scene_boundaries_not_per_scene():
    """The whole point: two scenes each individually reasonable (one entry
    apiece) are still too dense together when the scenes are short. A
    per-scene rule cannot see this; this pass can."""
    scenes = [_scene("sc_01", [1, None]), _scene("sc_02", [2, None])]
    assert _entry_shot_ids(_cap_layer_entries(scenes, min_gap=4)) == ["sc_01_sh_00"]


def test_an_entry_far_enough_away_is_kept():
    scenes = [_scene("sc_01", [1, None, None, None, None, 2])]
    assert _entry_shot_ids(_cap_layer_entries(scenes, min_gap=4)) == [
        "sc_01_sh_00",
        "sc_01_sh_05",
    ]


def test_a_parallax_shot_without_an_entry_is_never_this_caps_business():
    """The cap clears ENTRIES, never a plain parallax shot's layers - a
    shot that already carries layers but no `enter_on_fragment` (present
    for the whole shot, the ordinary case even among parallax shots) is
    untouched by this pass entirely."""
    scene = Scene(
        id="sc_01",
        order=0,
        title="sc_01",
        duration_s=4.0,
        shots=[
            _shot(0, entry=1, id_prefix="sc_01_"),
            _shot(1, parallax=True, id_prefix="sc_01_"),
        ],
    )
    out = _cap_layer_entries([scene], min_gap=4)
    plain_parallax = out[0].shots[1]
    assert len(plain_parallax.layers) == 2
    assert plain_parallax.layers[1].enter_on_fragment is None


def test_already_sparse_entries_are_untouched():
    scenes = [_scene("sc_01", [1, None, None, None, None, None, 2])]
    out = _cap_layer_entries(scenes, min_gap=4)
    assert _entry_shot_ids(out) == ["sc_01_sh_00", "sc_01_sh_06"]
    assert [s.layers for s in out[0].shots] == [s.layers for s in scenes[0].shots]


def test_log_records_the_trim_event(caplog):
    scenes = [_scene("sc_01", [1, 2, 3])]
    with caplog.at_level("WARNING"):
        _cap_layer_entries(scenes, min_gap=4)
    records = [
        r for r in caplog.records if r.message == "shot_planner.layer_entries_too_dense_trimmed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.kept == 1
    assert record.cleared == 2
    assert record.min_gap == 4


def test_min_gap_zero_or_negative_is_a_no_op():
    scenes = [_scene("sc_01", [1, 2, 3])]
    out = _cap_layer_entries(scenes, min_gap=0)
    assert out is scenes
