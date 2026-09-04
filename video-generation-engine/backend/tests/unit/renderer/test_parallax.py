"""`app/renderer/parallax.py` - pure arithmetic and filter-graph string
construction, no ffmpeg needed (mirrors `test_ken_burns.py`/
`test_split_screen.py`'s own shape). Ports `backend/scripts/
parallax_probe.py`'s measured shape (§1.4/§1.5); this file is the unit
proof that the port kept the same arithmetic and the same "sample, never
assume" discipline for the key colour.
"""

import io

import pytest
from PIL import Image

from app.renderer.parallax import (
    ParallaxKeyGuardError,
    ParallaxLayerInput,
    base_canvas_filter,
    base_offset,
    build_two_layer_parallax_filter_complex,
    check_keyed_fraction,
    drift_expressions,
    keyed_fraction,
    layer_input_chain,
    oversized_size,
    sample_key_colour,
    validate_two_layer_shot,
)
from app.schemas.timeline import LayerRole, ShotLayer

# ---------------------------------------------------------------------------
# Oversize / travel arithmetic (parallax_probe.py's own measured constants,
# generalised).
# ---------------------------------------------------------------------------


def test_oversized_size_matches_the_probes_own_1_2x_arithmetic():
    # parallax_probe.py: _W, _H = 720, 1280; _OVER = 1.2 -> _LW, _LH = 864, 1536
    assert oversized_size(720, 1280, 1.2) == (864, 1536)


def test_oversized_size_rejects_a_scale_that_cannot_cover_the_canvas():
    with pytest.raises(ValueError, match="> 1.0"):
        oversized_size(720, 1280, 1.0)
    with pytest.raises(ValueError):
        oversized_size(720, 1280, 0.8)


def test_base_offset_centres_the_oversized_layer():
    # parallax_probe.py: _X0, _Y0 = -(_LW - _W) // 2, -(_LH - _H) // 2
    lw, lh = oversized_size(720, 1280, 1.2)
    assert base_offset(720, 1280, lw, lh) == (-(lw - 720) // 2, -(lh - 1280) // 2)
    assert base_offset(720, 1280, 864, 1536) == (-72, -128)


def test_drift_expressions_are_deterministic_in_t_only():
    x, y = drift_expressions(-72, -128, 110.0, 0.0, 5.0)
    assert x == "-72-(110.0*t/5.0)"
    assert y == "-128-(0.0*t/5.0)"
    # No RNG, no wall-clock (I5) - the expression string is pure text.
    assert "random" not in x and "time" not in x


# ---------------------------------------------------------------------------
# Filter-graph fragments, string assertions only (probe shows the shape).
# ---------------------------------------------------------------------------


def test_base_canvas_filter_matches_the_probes_shape():
    fragment = base_canvas_filter(width=720, height=1280, fps=30, duration_s=5.0)
    assert fragment == "color=c=0x101418:s=720x1280:r=30:d=5.0[base]"


def test_layer_input_chain_unkeyed():
    fragment = layer_input_chain(0, "bg", width=864, height=1536, keyed=False)
    assert fragment == "[0:v]scale=864:1536,setsar=1,format=rgba[bg]"


def test_layer_input_chain_keyed_includes_similarity_and_blend():
    fragment = layer_input_chain(1, "sub", width=864, height=1536, keyed=True, key="0xB43E7E")
    assert fragment == "[1:v]scale=864:1536,setsar=1,colorkey=0xB43E7E:0.16:0.05,format=rgba[sub]"


def test_layer_input_chain_keyed_without_a_key_raises():
    with pytest.raises(ValueError, match="sampled key colour"):
        layer_input_chain(1, "sub", width=864, height=1536, keyed=True)


# ---------------------------------------------------------------------------
# The full two-layer filter_complex.
# ---------------------------------------------------------------------------


def _bg(index=0, drift_x=24.0, drift_y=0.0, scale=1.2) -> ParallaxLayerInput:
    return ParallaxLayerInput(
        role=LayerRole.BACKGROUND, index=index, scale=scale, drift_x=drift_x, drift_y=drift_y
    )


def _subject(index=1, drift_x=110.0, drift_y=0.0, scale=1.2, key="0xB43E7E") -> ParallaxLayerInput:
    return ParallaxLayerInput(
        role=LayerRole.SUBJECT, index=index, scale=scale, drift_x=drift_x, drift_y=drift_y, key=key
    )


def test_two_layer_filter_complex_matches_the_probes_clip_a_shape():
    fragment = build_two_layer_parallax_filter_complex(
        _bg(), _subject(), canvas_w=720, canvas_h=1280, fps=30, duration_s=5.0
    )
    parts = fragment.split(";")
    assert parts[0] == "color=c=0x101418:s=720x1280:r=30:d=5.0[base]"
    assert parts[1] == "[0:v]scale=864:1536,setsar=1,format=rgba[pxbg]"
    assert parts[2] == "[1:v]scale=864:1536,setsar=1,colorkey=0xB43E7E:0.16:0.05,format=rgba[pxsub]"
    assert (
        parts[3] == "[base][pxbg]overlay=x='-72-(24.0*t/5.0)':y='-128-(0.0*t/5.0)':shortest=1[pxb1]"
    )
    assert parts[4] == "[pxb1][pxsub]overlay=x='-72-(110.0*t/5.0)':y='-128-(0.0*t/5.0)'[out]"
    assert fragment.endswith("[out]")
    # Exactly one keyed layer (the subject), never the background.
    assert fragment.count("colorkey=") == 1
    assert fragment.count("overlay=") == 2


def test_two_layer_filter_complex_uses_a_custom_label():
    fragment = build_two_layer_parallax_filter_complex(
        _bg(), _subject(), canvas_w=720, canvas_h=1280, fps=30, duration_s=5.0, label="pxout"
    )
    assert fragment.endswith("[pxout]")


def test_two_layer_filter_complex_rejects_wrong_role_order():
    with pytest.raises(ValueError, match="BACKGROUND layer first"):
        build_two_layer_parallax_filter_complex(
            _subject(), _bg(), canvas_w=720, canvas_h=1280, fps=30, duration_s=5.0
        )


def test_two_layer_filter_complex_requires_a_subject_key():
    unkeyed_subject = ParallaxLayerInput(
        role=LayerRole.SUBJECT, index=1, scale=1.2, drift_x=110.0, drift_y=0.0, key=None
    )
    with pytest.raises(ValueError, match="sampled key colour"):
        build_two_layer_parallax_filter_complex(
            _bg(), unkeyed_subject, canvas_w=720, canvas_h=1280, fps=30, duration_s=5.0
        )


def test_validate_two_layer_shot_accepts_exactly_background_then_subject():
    layers = [ShotLayer(role=LayerRole.BACKGROUND), ShotLayer(role=LayerRole.SUBJECT)]
    validate_two_layer_shot(layers)  # does not raise


def test_validate_two_layer_shot_rejects_wrong_count():
    with pytest.raises(ValueError, match="exactly 2 layers"):
        validate_two_layer_shot([ShotLayer(role=LayerRole.BACKGROUND)])
    with pytest.raises(ValueError, match="exactly 2 layers"):
        validate_two_layer_shot(
            [
                ShotLayer(role=LayerRole.BACKGROUND),
                ShotLayer(role=LayerRole.SUBJECT),
                ShotLayer(role=LayerRole.FOREGROUND),
            ]
        )


def test_validate_two_layer_shot_rejects_wrong_order():
    with pytest.raises(ValueError, match="first layer must be background"):
        validate_two_layer_shot(
            [ShotLayer(role=LayerRole.SUBJECT), ShotLayer(role=LayerRole.BACKGROUND)]
        )


def test_parallax_layer_input_from_shot_layer_carries_the_planners_own_numbers():
    """Canon 3.1: the renderer executes the planner's numbers, it does
    not invent them - proving the values pass through unchanged."""
    layer = ShotLayer(role=LayerRole.SUBJECT, drift_x=87.0, drift_y=3.5, scale=1.35)
    spec = ParallaxLayerInput.from_shot_layer(layer, index=2, key="0x123456")
    assert spec.role is LayerRole.SUBJECT
    assert spec.index == 2
    assert spec.drift_x == 87.0
    assert spec.drift_y == 3.5
    assert spec.scale == 1.35
    assert spec.key == "0x123456"


# ---------------------------------------------------------------------------
# Key sampling - SAMPLED from bytes, never assumed (§1.5).
# ---------------------------------------------------------------------------


def _png_bytes(width: int, height: int, fill: tuple[int, int, int], patches=()) -> bytes:
    image = Image.new("RGB", (width, height), fill)
    for x, y, colour in patches:
        image.putpixel((x, y), colour)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_sample_key_colour_reads_the_top_strip_not_the_requested_colour():
    """§1.5, measured: asking for pure magenta does not guarantee pure
    magenta comes back. This proves sampling reflects the DELIVERED
    pixels, using a background that intentionally differs from any
    'requested' constant."""
    delivered = (0xB4, 0x3E, 0x7E)  # §1.5's own measured drifted value
    data = _png_bytes(80, 100, delivered)
    assert sample_key_colour(data) == "0xB43E7E"


def test_sample_key_colour_ignores_a_subject_touching_the_bottom_edge():
    """The top-strip-only + median discipline: a subject at the bottom of
    the frame must not pull the sampled key toward the subject's own
    colour."""
    key_colour = (0xFF, 0x00, 0xFF)
    data = _png_bytes(80, 100, key_colour)
    image = Image.open(io.BytesIO(data))
    # A large dark "subject" filling the bottom half - well clear of the
    # sampled top strip (rows 0..24 at stride 4).
    for x in range(0, 80):
        for y in range(50, 100):
            image.putpixel((x, y), (10, 10, 10))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()
    assert sample_key_colour(data) == "0xFF00FF"


def test_sample_key_colour_is_deterministic():
    data = _png_bytes(64, 64, (0x11, 0x22, 0x33))
    assert sample_key_colour(data) == sample_key_colour(data)


def test_sample_key_colour_handles_the_smallest_legal_image_without_crashing():
    """A 1x1 image gives a degenerate strip (height < 24) - the clamp in
    `sample_key_colour` (`strip_h = min(24, height)`) must still produce
    an answer rather than an index error, since real generated stills
    are never this small but a synthetic/test image legitimately can be."""
    data = _png_bytes(1, 1, (5, 5, 5))
    assert sample_key_colour(data) == "0x050505"


# ---------------------------------------------------------------------------
# The keyed-fraction guard (§4.5) - the failure §1.5 hit was SILENT
# (exit code 0); this guard exists specifically to stop being silent.
# ---------------------------------------------------------------------------


def _subject_like_png(key_colour=(0xFF, 0x00, 0xFF), subject_colour=(10, 10, 10)) -> bytes:
    """~40% key colour, ~60% subject - inside the sane band."""
    image = Image.new("RGB", (100, 100), key_colour)
    for x in range(100):
        for y in range(40, 100):
            image.putpixel((x, y), subject_colour)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_keyed_fraction_measures_the_share_matching_the_key():
    data = _subject_like_png()
    fraction = keyed_fraction(data, "0xFF00FF")
    assert 0.35 <= fraction <= 0.45


def test_keyed_fraction_in_band_passes_the_guard():
    fraction = keyed_fraction(_subject_like_png(), "0xFF00FF")
    check_keyed_fraction(fraction)  # must not raise


def test_keyed_fraction_guard_zero_is_the_opaque_rectangle_bug():
    """§1.5: a key that matches nothing (e.g. sampled key that does not
    actually appear in the delivered frame) composites as a solid
    rectangle, with exit code 0 and no other symptom. Zero must raise."""
    all_subject = Image.new("RGB", (40, 40), (10, 10, 10))
    buf = io.BytesIO()
    all_subject.save(buf, format="PNG")
    fraction = keyed_fraction(buf.getvalue(), "0xFF00FF")
    assert fraction == 0.0
    with pytest.raises(ParallaxKeyGuardError, match="matched nothing"):
        check_keyed_fraction(fraction)


def test_keyed_fraction_guard_near_100_percent_ate_the_subject():
    all_key = Image.new("RGB", (40, 40), (0xFF, 0x00, 0xFF))
    buf = io.BytesIO()
    all_key.save(buf, format="PNG")
    fraction = keyed_fraction(buf.getvalue(), "0xFF00FF")
    assert fraction == 1.0
    with pytest.raises(ParallaxKeyGuardError, match="ate the subject"):
        check_keyed_fraction(fraction)


def test_keyed_fraction_guard_distinguishes_the_two_failure_directions():
    """Both are invisible in logs (§4.5) - the messages must not be
    interchangeable, so whoever reads them knows which fix to reach for."""
    with pytest.raises(ParallaxKeyGuardError) as zero_exc:
        check_keyed_fraction(0.0)
    with pytest.raises(ParallaxKeyGuardError) as high_exc:
        check_keyed_fraction(0.95)
    assert str(zero_exc.value) != str(high_exc.value)
    assert "matched nothing" in str(zero_exc.value)
    assert "matched nothing" not in str(high_exc.value)


def test_keyed_fraction_guard_below_band_but_nonzero_also_raises():
    with pytest.raises(ParallaxKeyGuardError, match="below 0.15"):
        check_keyed_fraction(0.05)


def test_keyed_fraction_guard_band_boundaries_are_inclusive():
    check_keyed_fraction(0.15)
    check_keyed_fraction(0.85)


def test_keyed_fraction_guard_message_carries_shot_and_layer_when_given():
    with pytest.raises(ParallaxKeyGuardError, match=r"\(sh_01/subject\)"):
        check_keyed_fraction(0.0, shot_id="sh_01", layer_role="subject")
