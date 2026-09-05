"""`should_composite_parallax` (illustrated_faceless.md §2.2/F2a) - pure
dispatch-gate logic, no ffmpeg. Mirrors `test_split_screen.py`'s own
`test_should_composite_requires_two_stills_and_split_movement`: the real
ffmpeg-level composite + guard-degrade behaviour this gate feeds is
covered end-to-end in `tests/integration/test_render_parallax.py`.
"""

from pathlib import Path

from app.renderer.motion import MediaKind
from app.renderer.slideshow import should_composite_parallax
from app.schemas.timeline import CameraMovement, LayerRole, ShotLayer

_BACKGROUND = ShotLayer(role=LayerRole.BACKGROUND, prompt="a room")
_SUBJECT = ShotLayer(role=LayerRole.SUBJECT, prompt="a figure")
_LAYERS = [_BACKGROUND, _SUBJECT]
_PATHS = [Path("bg.png"), Path("sub.png")]
_STILLS = [MediaKind.STILL, MediaKind.STILL]


def test_a_well_formed_parallax_shot_composites():
    assert should_composite_parallax(
        CameraMovement.PARALLAX, _LAYERS, layer_paths=_PATHS, layer_kinds=_STILLS
    )


def test_a_non_parallax_movement_never_composites_even_with_layers():
    assert not should_composite_parallax(
        CameraMovement.STATIC, _LAYERS, layer_paths=_PATHS, layer_kinds=_STILLS
    )


def test_parallax_with_no_layers_does_not_composite():
    assert not should_composite_parallax(
        CameraMovement.PARALLAX, [], layer_paths=[], layer_kinds=[]
    )


def test_parallax_with_three_layers_does_not_composite():
    """F2a is two-layer only (F3 is a third plane) - `parallax.py`'s own
    builder rejects anything else; this gate must agree, not raise."""
    layers = [_BACKGROUND, _SUBJECT, ShotLayer(role=LayerRole.FOREGROUND, prompt="chairs")]
    paths = [*_PATHS, Path("fg.png")]
    kinds = [*_STILLS, MediaKind.STILL]
    assert not should_composite_parallax(
        CameraMovement.PARALLAX, layers, layer_paths=paths, layer_kinds=kinds
    )


def test_wrong_role_order_does_not_composite():
    assert not should_composite_parallax(
        CameraMovement.PARALLAX,
        [_SUBJECT, _BACKGROUND],
        layer_paths=_PATHS,
        layer_kinds=_STILLS,
    )


def test_a_missing_layer_path_degrades():
    assert not should_composite_parallax(
        CameraMovement.PARALLAX, _LAYERS, layer_paths=[_PATHS[0], None], layer_kinds=_STILLS
    )


def test_no_resolved_paths_at_all_degrades():
    assert not should_composite_parallax(
        CameraMovement.PARALLAX, _LAYERS, layer_paths=[], layer_kinds=[]
    )


def test_a_motion_clip_on_either_plane_degrades():
    assert not should_composite_parallax(
        CameraMovement.PARALLAX,
        _LAYERS,
        layer_paths=_PATHS,
        layer_kinds=[MediaKind.STILL, MediaKind.MOTION],
    )
    assert not should_composite_parallax(
        CameraMovement.PARALLAX,
        _LAYERS,
        layer_paths=_PATHS,
        layer_kinds=[MediaKind.MOTION, MediaKind.STILL],
    )
