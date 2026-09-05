"""`Shot.reveal_direction`/`reveal_start_fragment`/`reveal_end_fragment`/
`reveal_start_offset_s`/`reveal_duration_s` (illustrated_faceless.md
§2/F5).

Three things this file must prove, mirroring `test_shot_layers.py`'s own
structure for F2/F4: the five reveal fields default to "no reveal" and
that means today's behaviour exactly (§3.1); the three planner-facing
fields are all-or-nothing and, when set, ordered start<=end (both
directions); and a reveal requires `camera.movement=static`, both
directions (set + non-static rejected; non-static + no reveal legal).
"""

import pytest
from pydantic import ValidationError

from app.schemas.timeline import Camera, CameraMovement, RevealDirection, Shot, ShotIntent


def _shot(**overrides) -> Shot:
    fields = {"id": "sh_01", "order": 0, "intent": ShotIntent.EXPLAIN, "duration_s": 3.0}
    fields.update(overrides)
    return Shot(**fields)


# -- defaults / isolation (§3.1) --------------------------------------------


def test_reveal_fields_default_to_no_reveal():
    shot = _shot()
    assert shot.reveal_direction is None
    assert shot.reveal_start_fragment is None
    assert shot.reveal_end_fragment is None
    assert shot.reveal_start_offset_s == 0.0
    assert shot.reveal_duration_s == 0.0


@pytest.mark.parametrize(
    "style",
    ["documentary_archival", "retention_fast", "archival_montage", "stillness"],
)
def test_reveal_defaults_to_none_regardless_of_which_pre_existing_style_a_shot_belongs_to(style):
    """`Shot` carries no style of its own (style lives on
    `TimelineMetadata.render_style`) - constructing a shot the way each
    of the four pre-F5 styles already does (no reveal kwargs) still
    yields no reveal."""
    shot = _shot(prompt=f"a shot for {style}", camera=Camera(movement=CameraMovement.SLOW_PUSH))
    assert shot.reveal_direction is None


def test_reveal_direction_values():
    assert {d.value for d in RevealDirection} == {"none", "bottom_to_top", "left_to_right"}


# -- all-or-nothing (F5) -----------------------------------------------


def test_reveal_direction_alone_is_rejected():
    with pytest.raises(ValidationError, match="must all be set or all be None"):
        _shot(reveal_direction=RevealDirection.BOTTOM_TO_TOP)


def test_reveal_start_fragment_alone_is_rejected():
    with pytest.raises(ValidationError, match="must all be set or all be None"):
        _shot(reveal_start_fragment=2)


def test_reveal_end_fragment_alone_is_rejected():
    with pytest.raises(ValidationError, match="must all be set or all be None"):
        _shot(reveal_end_fragment=2)


def test_reveal_direction_and_start_without_end_is_rejected():
    with pytest.raises(ValidationError, match="must all be set or all be None"):
        _shot(reveal_direction=RevealDirection.BOTTOM_TO_TOP, reveal_start_fragment=2)


def test_all_three_reveal_fields_together_is_legal():
    shot = _shot(
        reveal_direction=RevealDirection.BOTTOM_TO_TOP,
        reveal_start_fragment=2,
        reveal_end_fragment=3,
    )
    assert shot.reveal_direction is RevealDirection.BOTTOM_TO_TOP
    assert shot.reveal_start_fragment == 2
    assert shot.reveal_end_fragment == 3
    # Not resolved here - that happens at the narration_fit seam.
    assert shot.reveal_start_offset_s == 0.0
    assert shot.reveal_duration_s == 0.0


def test_reveal_end_fragment_before_start_fragment_is_rejected():
    with pytest.raises(ValidationError, match="must be >= reveal_start_fragment"):
        _shot(
            reveal_direction=RevealDirection.BOTTOM_TO_TOP,
            reveal_start_fragment=5,
            reveal_end_fragment=3,
        )


def test_reveal_end_fragment_equal_to_start_fragment_is_legal():
    """A single-fragment reveal window is legal at the schema level -
    range-checking against the owning shot's own fragment range happens
    in the Shot Planner's own `_make_validator`, the identical reason
    `ShotLayer.enter_on_fragment`'s own schema-level test gives."""
    shot = _shot(
        reveal_direction=RevealDirection.LEFT_TO_RIGHT,
        reveal_start_fragment=4,
        reveal_end_fragment=4,
    )
    assert shot.reveal_start_fragment == shot.reveal_end_fragment == 4


# -- camera.movement=static requirement (F5) ----------------------------


def test_reveal_on_a_static_shot_is_legal():
    shot = _shot(
        camera=Camera(movement=CameraMovement.STATIC),
        reveal_direction=RevealDirection.BOTTOM_TO_TOP,
        reveal_start_fragment=1,
        reveal_end_fragment=2,
    )
    assert shot.reveal_direction is RevealDirection.BOTTOM_TO_TOP


@pytest.mark.parametrize(
    "movement",
    [
        CameraMovement.SLOW_ZOOM,
        CameraMovement.SLOW_PUSH,
        CameraMovement.PULL_BACK,
        CameraMovement.PAN,
        CameraMovement.PUNCH_IN,
        CameraMovement.PARALLAX,
    ],
)
def test_reveal_on_a_moving_camera_shot_is_rejected(movement):
    with pytest.raises(ValidationError, match="camera.movement=static"):
        _shot(
            camera=Camera(movement=movement),
            reveal_direction=RevealDirection.LEFT_TO_RIGHT,
            reveal_start_fragment=1,
            reveal_end_fragment=1,
        )


def test_a_moving_camera_shot_with_no_reveal_is_still_legal():
    """The camera/reveal validator must not fire on the overwhelming
    majority of shots, which have no reveal at all."""
    shot = _shot(camera=Camera(movement=CameraMovement.SLOW_ZOOM))
    assert shot.reveal_direction is None
