"""`_cap_element_reveals` — the project-wide reveal spacing pass (F5,
illustrated_faceless.md §2/F5).

Same class of pass as `_cap_layer_entries`/`_cap_text_cards`/`_cap_sfx_cues`
(a spacing cap on a NARRATIVE-frequency device, not a cost one): the
illustrated_risograph fragment's own rate cue asks for a reveal only on the
rare genuine chart/diagram shot, but the Shot Planner is called ONCE PER
SCENE and cannot see whether another scene already reached for one. Unlike
a layer entry (already gated behind the rarer `parallax` movement), a
reveal attaches to a plain `static` shot with no equivalent upstream
scarcity - argued in the plan as the reason this cap is NEEDED, not
optional. Pure, no DB, no LLM — run with `--noconftest`.
"""

from app.planners.shot.planner import _cap_element_reveals
from app.schemas.timeline import Camera, CameraMovement, RevealDirection, Scene, Shot, ShotIntent


def _shot(idx: int, *, reveal: bool = False, id_prefix: str = "") -> Shot:
    return Shot(
        id=f"{id_prefix}sh_{idx:02d}",
        order=idx,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(movement=CameraMovement.STATIC),
        reveal_direction=RevealDirection.BOTTOM_TO_TOP if reveal else None,
        reveal_start_fragment=1 if reveal else None,
        reveal_end_fragment=1 if reveal else None,
    )


def _scene(sid: str, reveals: list[bool]) -> Scene:
    return Scene(
        id=sid,
        order=0,
        title=sid,
        duration_s=float(2 * len(reveals)),
        shots=[_shot(i, reveal=r, id_prefix=f"{sid}_") for i, r in enumerate(reveals)],
    )


def _reveal_shot_ids(scenes: list[Scene]) -> list[str]:
    return [s.id for sc in scenes for s in sc.shots if s.reveal_direction is not None]


def test_under_cap_is_byte_identical():
    # Ten shots separate the two reveals - exactly `min_gap`, so both
    # survive untouched.
    scenes = [_scene("sc_01", [True, *([False] * 10), True])]
    out = _cap_element_reveals(scenes, min_gap=10)
    for sc, orig_sc in zip(out, scenes, strict=True):
        for shot, orig_shot in zip(sc.shots, orig_sc.shots, strict=True):
            assert shot.reveal_direction == orig_shot.reveal_direction
            assert shot is orig_shot  # never even model_copy'd


def test_a_project_with_no_reveals_is_unaffected():
    scenes = [_scene("sc_01", [False, False]), _scene("sc_02", [False])]
    out = _cap_element_reveals(scenes, min_gap=2)
    assert _reveal_shot_ids(out) == []


def test_reveals_closer_than_the_gap_are_cleared_but_the_shot_survives():
    scenes = [_scene("sc_01", [True, True, False, False, False])]
    out = _cap_element_reveals(scenes, min_gap=4)
    assert _reveal_shot_ids(out) == ["sc_01_sh_00"]
    # The SECOND shot's reveal is cleared, but the shot itself, its
    # picture, and its camera movement are untouched - it simply renders
    # as a plain static shot instead of a wipe.
    cleared = out[0].shots[1]
    assert cleared.camera.movement == CameraMovement.STATIC
    assert cleared.reveal_direction is None
    assert cleared.reveal_start_fragment is None
    assert cleared.reveal_end_fragment is None


def test_spacing_is_enforced_across_scene_boundaries_not_per_scene():
    """The whole point: two scenes each individually reasonable (one
    reveal apiece) are still too dense together when the scenes are
    short. A per-scene rule cannot see this; this pass can."""
    scenes = [_scene("sc_01", [True, False]), _scene("sc_02", [True, False])]
    assert _reveal_shot_ids(_cap_element_reveals(scenes, min_gap=4)) == ["sc_01_sh_00"]


def test_a_reveal_far_enough_away_is_kept():
    scenes = [_scene("sc_01", [True, False, False, False, False, True])]
    assert _reveal_shot_ids(_cap_element_reveals(scenes, min_gap=4)) == [
        "sc_01_sh_00",
        "sc_01_sh_05",
    ]


def test_already_sparse_reveals_are_untouched():
    scenes = [_scene("sc_01", [True, False, False, False, False, False, True])]
    out = _cap_element_reveals(scenes, min_gap=4)
    assert _reveal_shot_ids(out) == ["sc_01_sh_00", "sc_01_sh_06"]
    assert [s.reveal_direction for s in out[0].shots] == [
        s.reveal_direction for s in scenes[0].shots
    ]


def test_log_records_the_trim_event(caplog):
    scenes = [_scene("sc_01", [True, True, True])]
    with caplog.at_level("WARNING"):
        _cap_element_reveals(scenes, min_gap=4)
    records = [
        r for r in caplog.records if r.message == "shot_planner.element_reveals_too_dense_trimmed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.kept == 1
    assert record.cleared == 2
    assert record.min_gap == 4


def test_min_gap_zero_or_negative_is_a_no_op():
    scenes = [_scene("sc_01", [True, True, True])]
    out = _cap_element_reveals(scenes, min_gap=0)
    assert out is scenes
