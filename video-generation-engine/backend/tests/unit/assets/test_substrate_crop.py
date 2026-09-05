"""F1a: `center_crop_to_canvas` (illustrated_faceless.md §8.1, 2026-09-05)
- pure, no DB, no network."""

import io

import pytest
from PIL import Image

from app.assets.substrate_crop import center_crop_to_canvas


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
