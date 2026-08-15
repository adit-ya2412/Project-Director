"""Downloaded-asset validation (implementation guide, Phase M6 advice:
"validate what you downloaded. Content-type, magic bytes, dimensions, and
a size cap. A 400 MB TIFF or an HTML error page saved as .jpg will blow
up FFmpeg in M8 with an incomprehensible error.").

Every asset a search provider hands back gets its content-type verified
by magic bytes here, never trusted from the provider's declared
content-type or file extension - both are attacker/provider-controlled.
"""

import io

from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.errors import PermanentError

_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}
_EXTENSION_BY_FORMAT = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
    "BMP": "bmp",
    "TIFF": "tiff",
}
_MIME_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}


def mime_type_for_extension(extension: str) -> str:
    """The one place a file extension maps to a MIME type - used wherever
    validated image bytes need a real content-type for something other
    than ffmpeg (e.g. a vision API's base64 data URL, M6.5 A30). Falls
    back to `image/png` for anything not in the map rather than raising -
    callers here already hold bytes `validate_and_identify_image` proved
    are a real, supported image; an unrecognised extension at this point
    is a gap in this table, not a reason to fail an otherwise-valid asset."""
    return _MIME_BY_EXTENSION.get(extension.lower(), "image/png")


def validate_and_identify_image(content: bytes) -> tuple[str, int, int]:
    """Returns (file_extension, width, height) for genuinely valid image
    bytes. Raises `PermanentError` for anything else - an oversized
    download or corrupt/unsupported content is never worth retrying."""
    if len(content) > settings.max_download_bytes:
        raise PermanentError(
            f"downloaded asset is {len(content)} bytes, exceeding the "
            f"{settings.max_download_bytes} byte cap"
        )

    try:
        probe = Image.open(io.BytesIO(content))
        probe.verify()  # magic-byte / structural check; invalidates `probe` for further use
        image = Image.open(io.BytesIO(content))
        width, height = image.size
        image_format = image.format
    except (UnidentifiedImageError, OSError) as exc:
        raise PermanentError(f"downloaded content is not a valid image: {exc}") from exc

    if image_format not in _ALLOWED_FORMATS:
        raise PermanentError(f"unsupported image format {image_format!r}")

    return _EXTENSION_BY_FORMAT[image_format], width, height
