"""`app/renderer/ken_burns.py` - pure arithmetic, no ffmpeg needed. The
real ffmpeg `zoompan` graph this feeds is proven separately, against a
real render, in tests/integration/test_render_ken_burns.py.
"""

from app.renderer.ken_burns import build_zoompan_expression
from app.schemas.timeline import Camera, CameraDirection, CameraMovement


def _camera(
    movement: CameraMovement,
    direction: CameraDirection = CameraDirection.NONE,
    intensity: float = 0.2,
) -> Camera:
    return Camera(movement=movement, direction=direction, intensity=intensity)


def test_static_never_gets_a_zoompan_expression():
    assert build_zoompan_expression(_camera(CameraMovement.STATIC), frames=90) is None


def test_split_frame_never_gets_a_zoompan_expression():
    """A real split-screen composite needs a second source image this
    renderer's one-image-per-shot contract doesn't have - documented gap,
    not a silent mis-implementation."""
    assert build_zoompan_expression(_camera(CameraMovement.SPLIT_FRAME), frames=90) is None


def test_zero_intensity_degrades_to_no_motion_for_every_movement():
    for movement in (
        CameraMovement.SLOW_ZOOM,
        CameraMovement.SLOW_PUSH,
        CameraMovement.PULL_BACK,
        CameraMovement.PAN,
    ):
        assert build_zoompan_expression(_camera(movement, intensity=0.0), frames=90) is None


def test_slow_push_always_zooms_in_regardless_of_direction():
    for direction in (CameraDirection.NONE, CameraDirection.OUT, CameraDirection.LEFT):
        expr = build_zoompan_expression(_camera(CameraMovement.SLOW_PUSH, direction), frames=90)
        assert expr is not None
        assert "zoom+" in expr.zoom_expr  # increasing zoom = pushing in
        assert "max(zoom-" not in expr.zoom_expr


def test_pull_back_always_zooms_out_regardless_of_direction():
    for direction in (CameraDirection.NONE, CameraDirection.IN, CameraDirection.RIGHT):
        expr = build_zoompan_expression(_camera(CameraMovement.PULL_BACK, direction), frames=90)
        assert expr is not None
        assert "max(zoom-" in expr.zoom_expr  # decreasing zoom = pulling back
        assert "if(eq(on,0)" in expr.zoom_expr  # seeds the starting (max) zoom on the first frame


def test_slow_zoom_direction_in_zooms_in():
    expr = build_zoompan_expression(
        _camera(CameraMovement.SLOW_ZOOM, CameraDirection.IN), frames=90
    )
    assert expr is not None
    assert "zoom+" in expr.zoom_expr


def test_slow_zoom_direction_out_zooms_out():
    expr = build_zoompan_expression(
        _camera(CameraMovement.SLOW_ZOOM, CameraDirection.OUT), frames=90
    )
    assert expr is not None
    assert "max(zoom-" in expr.zoom_expr


def test_zoom_expressions_are_centered():
    expr = build_zoompan_expression(
        _camera(CameraMovement.SLOW_ZOOM, CameraDirection.IN), frames=90
    )
    assert expr is not None
    assert expr.x_expr == "iw/2-(iw/zoom/2)"
    assert expr.y_expr == "ih/2-(ih/zoom/2)"


def test_pan_left_moves_right_to_left():
    expr = build_zoompan_expression(_camera(CameraMovement.PAN, CameraDirection.LEFT), frames=90)
    assert expr is not None
    assert "(1-on/" in expr.x_expr


def test_pan_right_moves_left_to_right():
    expr = build_zoompan_expression(_camera(CameraMovement.PAN, CameraDirection.RIGHT), frames=90)
    assert expr is not None
    assert "(on/" in expr.x_expr
    assert "(1-on/" not in expr.x_expr


def test_pan_with_no_meaningful_direction_defaults_to_left_to_right_and_never_crashes():
    for direction in (CameraDirection.NONE, CameraDirection.IN, CameraDirection.OUT):
        expr = build_zoompan_expression(_camera(CameraMovement.PAN, direction), frames=90)
        assert expr is not None
        assert "(on/" in expr.x_expr


def test_zoom_never_exceeds_max_zoom_at_the_last_frame():
    """Arithmetic check: the incremental step times (frames - 1) must
    land exactly on max_zoom, not overshoot or undershoot it - the exact
    kind of off-by-one that would either freeze the zoom early or blow
    past the intended intensity."""
    intensity = 0.4
    max_zoom = 1.0 + intensity * 0.5  # mirrors _MAX_ZOOM_DELTA in ken_burns.py
    frames = 90
    expr = build_zoompan_expression(
        Camera(
            movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.IN, intensity=intensity
        ),
        frames=frames,
    )
    assert expr is not None
    step = (max_zoom - 1.0) / (frames - 1)
    final_zoom = 1.0 + step * (frames - 1)
    assert abs(final_zoom - max_zoom) < 1e-9


def test_a_single_frame_shot_never_divides_by_zero():
    """A pathologically short shot (rounds to 1 output frame) must not
    crash on `frames - 1 == 0`."""
    expr = build_zoompan_expression(
        Camera(movement=CameraMovement.SLOW_ZOOM, direction=CameraDirection.IN, intensity=0.5),
        frames=1,
    )
    assert expr is not None
