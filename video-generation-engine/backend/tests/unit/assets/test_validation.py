"""Unit tests for downloaded-asset validation - pure, no DB, no network
(implementation guide, Phase M6 advice: "validate what you downloaded")."""

import io

import pytest
from PIL import Image

from app.assets.validation import validate_and_identify_image
from app.core.config import settings
from app.core.errors import PermanentError


def _image_bytes(fmt: str, size: tuple[int, int] = (640, 480)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


def test_valid_png_returns_extension_and_dimensions():
    ext, width, height = validate_and_identify_image(_image_bytes("PNG", (800, 600)))
    assert ext == "png"
    assert (width, height) == (800, 600)


def test_valid_jpeg_returns_jpg_extension():
    ext, _width, _height = validate_and_identify_image(_image_bytes("JPEG"))
    assert ext == "jpg"


def test_oversized_content_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "max_download_bytes", 10)
    with pytest.raises(PermanentError, match="byte cap"):
        validate_and_identify_image(_image_bytes("PNG"))


def test_garbage_bytes_are_rejected():
    with pytest.raises(PermanentError, match="not a valid image"):
        validate_and_identify_image(b"this is not an image, it is an HTML error page")


def test_unsupported_format_is_rejected():
    with pytest.raises(PermanentError, match="unsupported image format"):
        validate_and_identify_image(_image_bytes("PPM"))
