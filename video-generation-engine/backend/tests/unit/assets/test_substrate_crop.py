"""F1a: `center_crop_to_canvas` (illustrated_faceless.md §8.1, 2026-09-05)
and `fit_upload_to_canvas` (gate_panel_overrides.md P1 CORRECTION) -
pure, no DB, no network."""

import io

import pytest
from PIL import Image

from app.assets.substrate_crop import center_crop_to_canvas, fit_upload_to_canvas


def _png(width: int, height: int, colour=(10, 20, 30)) -> bytes:
    image = Image.new("RGB", (width, height), color=colour)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_output_is_exactly_the_canvas_size():
    cropped = center_crop_to_canvas(_png(749, 1331), 720, 1280)
    with Image.open(io.BytesIO(cropped)) as image:
        assert image.size == (720, 1280)


def test_crop_is_centred():
    """A marker pixel placed exactly at the source's centre must land at
    the cropped image's own centre too - proves this is a CENTRE crop,
    not top-left or any other anchor."""
    width, height = 749, 1331
    image = Image.new("RGB", (width, height), color=(0, 0, 0))
    marker = (255, 255, 255)
    image.putpixel((width // 2, height // 2), marker)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    cropped = center_crop_to_canvas(buffer.getvalue(), 720, 1280)
    with Image.open(io.BytesIO(cropped)) as out:
        cw, ch = out.size
        left = (width - cw) // 2
        top = (height - ch) // 2
        expected = (width // 2 - left, height // 2 - top)
        assert out.getpixel(expected) == marker


def test_deterministic_same_bytes_same_canvas_same_output():
    """I5: no RNG, no wall-clock - the crop is a pure function of its
    inputs."""
    source = _png(749, 1331)
    first = center_crop_to_canvas(source, 720, 1280)
    second = center_crop_to_canvas(source, 720, 1280)
    assert first == second


def test_no_op_when_source_already_equals_the_canvas():
    """Retrieval styles never call this at all (§8.1's isolation), but
    the function itself is well-defined at zero oversize too - a crop
    with nothing to trim returns pixel-identical content."""
    source = _png(720, 1280)
    cropped = center_crop_to_canvas(source, 720, 1280)
    with Image.open(io.BytesIO(source)) as before, Image.open(io.BytesIO(cropped)) as after:
        assert before.size == after.size
        assert list(before.getdata()) == list(after.getdata())


def test_raises_when_source_is_smaller_than_the_canvas():
    with pytest.raises(ValueError, match="smaller than the canvas"):
        center_crop_to_canvas(_png(700, 1280), 720, 1280)
    with pytest.raises(ValueError, match="smaller than the canvas"):
        center_crop_to_canvas(_png(720, 1200), 720, 1280)


def test_preserves_the_original_format():
    buffer = io.BytesIO()
    Image.new("RGB", (749, 1331), color=(1, 2, 3)).save(buffer, format="JPEG")
    cropped = center_crop_to_canvas(buffer.getvalue(), 720, 1280)
    with Image.open(io.BytesIO(cropped)) as image:
        assert image.format == "JPEG"
        assert image.size == (720, 1280)


# --- fit_upload_to_canvas (gate_panel_overrides.md P1 CORRECTION) --------


def test_fit_output_is_exactly_the_canvas_size():
    # Cover != canvas on purpose: caller derives cover from
    # resolve_generation_request_format; never hardcode 0.08 here (§4.5).
    fitted = fit_upload_to_canvas(
        _png(1536, 2688),
        cover_width=778,
        cover_height=1383,
        canvas_width=720,
        canvas_height=1280,
    )
    with Image.open(io.BytesIO(fitted)) as image:
        assert image.size == (720, 1280)


def test_fit_scales_rather_than_taking_a_tiny_centre_window():
    """A large off-aspect source (Qwen-shaped stand-in) must be scaled to
    cover, not windowed: bare centre-crop of the same bytes yields a
    different frame, and a centre block survives the cover-then-crop."""
    from PIL import ImageDraw

    width, height = 1536, 2688
    canvas_w, canvas_h = 720, 1280
    cover_w, cover_h = 778, 1383
    image = Image.new("RGB", (width, height), color=(0, 0, 255))
    draw = ImageDraw.Draw(image)
    # Left half red so a scale-vs-window difference is visible in bytes.
    draw.rectangle([0, 0, width // 2 - 1, height - 1], fill=(255, 0, 0))
    # Large centre block — survives LANCZOS, must remain after fit.
    cx, cy = width // 2, height // 2
    draw.rectangle([cx - 80, cy - 80, cx + 80, cy + 80], fill=(0, 255, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    source = buffer.getvalue()

    bare = center_crop_to_canvas(source, canvas_w, canvas_h)
    fitted = fit_upload_to_canvas(
        source,
        cover_width=cover_w,
        cover_height=cover_h,
        canvas_width=canvas_w,
        canvas_height=canvas_h,
    )
    assert bare != fitted
    with Image.open(io.BytesIO(fitted)) as out:
        assert out.size == (canvas_w, canvas_h)
        assert out.getpixel((out.size[0] // 2, out.size[1] // 2)) == (0, 255, 0)


def test_fit_cover_size_comes_from_the_caller():
    """Passing cover == canvas vs a larger cover changes the scale step;
    both still land on canvas size. Proves cover is an input, not an
    internal constant."""
    from PIL import ImageDraw

    image = Image.new("RGB", (400, 800), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 199, 799], fill=(255, 0, 0))
    draw.rectangle([200, 0, 399, 799], fill=(0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    source = buffer.getvalue()
    tight = fit_upload_to_canvas(
        source, cover_width=720, cover_height=1280, canvas_width=720, canvas_height=1280
    )
    loose = fit_upload_to_canvas(
        source, cover_width=800, cover_height=1422, canvas_width=720, canvas_height=1280
    )
    with Image.open(io.BytesIO(tight)) as a, Image.open(io.BytesIO(loose)) as b:
        assert a.size == (720, 1280)
        assert b.size == (720, 1280)
    # Different cover margins → different persisted bytes after the crop.
    assert tight != loose


def test_fit_is_deterministic():
    source = _png(1536, 2688)
    kwargs = dict(
        cover_width=778, cover_height=1383, canvas_width=720, canvas_height=1280
    )
    assert fit_upload_to_canvas(source, **kwargs) == fit_upload_to_canvas(source, **kwargs)


def test_fit_does_not_stretch_one_axis_to_cover():
    """A wide source covering a taller target must scale uniformly.
    Independent max(cover, ceil) on each axis used to squash 7x10 → 3x5
    before the canvas crop (aspect 0.7 → 0.6)."""
    from PIL import ImageDraw

    image = Image.new("RGB", (70, 100), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Vertical midline marker — survives only if scale is uniform.
    draw.line([(35, 0), (35, 99)], fill=(255, 255, 255), width=3)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    fitted = fit_upload_to_canvas(
        buffer.getvalue(),
        cover_width=30,
        cover_height=40,
        canvas_width=30,
        canvas_height=40,
    )
    with Image.open(io.BytesIO(fitted)) as out:
        assert out.size == (30, 40)
        # Midline of a uniformly scaled 70x100 into a 30x40 cover-then-crop
        # stays near x=15. A stretched 30x50-style scale would shift it.
        whites = [x for x in range(30) if out.getpixel((x, 20))[0] > 200]
        assert whites, "midline marker missing after fit"
        mid = sum(whites) / len(whites)
        assert 12 <= mid <= 18


def test_fit_upscales_a_small_image_instead_of_raising():
    """Bare center_crop rejects undersized sources; fit must upscale so a
    phone-photo / chat-UI download still lands on canvas."""
    with pytest.raises(ValueError, match="smaller than the canvas"):
        center_crop_to_canvas(_png(64, 48), 720, 1280)
    fitted = fit_upload_to_canvas(
        _png(64, 48),
        cover_width=720,
        cover_height=1280,
        canvas_width=720,
        canvas_height=1280,
    )
    with Image.open(io.BytesIO(fitted)) as image:
        assert image.size == (720, 1280)
