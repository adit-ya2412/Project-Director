"""Downloaded-asset validation (implementation guide, Phase M6 advice:
"validate what you downloaded. Content-type, magic bytes, dimensions, and
a size cap. A 400 MB TIFF or an HTML error page saved as .jpg will blow
up FFmpeg in M8 with an incomprehensible error.").

Every asset a search provider hands back gets its content-type verified
by magic bytes here, never trusted from the provider's declared
content-type or file extension - both are attacker/provider-controlled.
"""

import asyncio
import io
import json
import tempfile
from pathlib import Path

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


async def validate_and_identify_video(
    content: bytes, *, ffprobe_binary: str = "ffprobe"
) -> tuple[str, int, int]:
    """Video counterpart to `validate_and_identify_image` (A7,
    motion_new_styles_and_long_form_videos.md, 2026-08-18) - Pillow
    cannot open a video container at all, so this shells out to ffprobe
    instead, applying the same "positively confirm a real video stream
    with a positive duration" discipline `app/renderer/motion.py::probe_
    media` already established for A1 (a separate function, not reused
    directly: that one classifies a file already resolved on disk against
    a STILL/MOTION choice; this one validates freshly downloaded bytes
    against a pass/fail choice, and needs width/height besides).

    Returns `("mp4", width, height)` for genuinely valid video bytes;
    raises `PermanentError` for anything else. `mp4` is hard-coded rather
    than derived from ffprobe's own container name - every video source
    this codebase downloads from today (Pexels, Kling) serves mp4, and
    getting this wrong would only ever affect the file EXTENSION on disk,
    never playback."""
    if len(content) > settings.max_download_bytes:
        raise PermanentError(
            f"downloaded asset is {len(content)} bytes, exceeding the "
            f"{settings.max_download_bytes} byte cap"
        )

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        args = [
            ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type,duration,width,height:format=duration",
            "-of",
            "json",
            str(tmp_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise PermanentError(
                f"downloaded content is not a valid video: {stderr.decode(errors='replace')}"
            )
        try:
            data = json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise PermanentError(f"downloaded content is not a valid video: {exc}") from exc

        streams = data.get("streams") or []
        if not streams or streams[0].get("codec_type") != "video":
            raise PermanentError("downloaded content has no video stream")
        stream = streams[0]

        raw_duration = stream.get("duration") or (data.get("format") or {}).get("duration")
        try:
            duration = float(raw_duration) if raw_duration is not None else 0.0
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            raise PermanentError("downloaded video has no positive duration")

        width, height = stream.get("width"), stream.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            raise PermanentError("downloaded video has no readable dimensions")
        return "mp4", width, height
    finally:
        tmp_path.unlink(missing_ok=True)


_AUDIO_EXTENSION_BY_FORMAT = {
    "mp3": "mp3",
    "wav": "wav",
    "flac": "flac",
    "ogg": "ogg",
    "oga": "ogg",
    "m4a": "m4a",
}


async def validate_and_identify_audio(
    content: bytes, *, ffprobe_binary: str = "ffprobe"
) -> tuple[str, float]:
    """Audio counterpart to `validate_and_identify_video` above (analysis.md
    C1, decisions 6a/6b) - Pillow cannot open an audio container either,
    so this shells out to ffprobe with the same "positively confirm a real
    audio stream with a positive duration" discipline. Length is NEVER a
    rejection reason here (decision 6a/6b: accept any duration and let the
    caller warn) - only undecodable bytes or an unsupported format are.

    Returns `(file_extension, duration_seconds)`; raises `PermanentError`
    for anything else. The extension comes from ffprobe's own
    `format_name` (unlike video's hard-coded mp4, audio genuinely arrives
    in several containers), mapped through `_AUDIO_EXTENSION_BY_FORMAT` -
    it decides only what the file is NAMED on disk, never whether ffmpeg
    can read it back (it already proved it can). A video container carrying
    an audio stream (.mp4/.mov) maps to `m4a` - its audio is decodable all
    the same, which is the only thing the renderer ever does with it."""
    if len(content) > settings.max_download_bytes:
        raise PermanentError(
            f"uploaded file is {len(content)} bytes, exceeding the "
            f"{settings.max_download_bytes} byte cap"
        )

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        args = [
            ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type,duration:format=duration,format_name",
            "-of",
            "json",
            str(tmp_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise PermanentError(
                f"uploaded content is not decodable audio: {stderr.decode(errors='replace')}"
            )
        try:
            data = json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise PermanentError(f"uploaded content is not decodable audio: {exc}") from exc

        streams = data.get("streams") or []
        if not streams or streams[0].get("codec_type") != "audio":
            raise PermanentError("uploaded content has no audio stream")

        raw_duration = (data.get("format") or {}).get("duration") or streams[0].get("duration")
        try:
            duration = float(raw_duration) if raw_duration is not None else 0.0
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            raise PermanentError("uploaded audio has no positive duration")

        raw_format_name = (data.get("format") or {}).get("format_name") or ""
        for token in raw_format_name.split(","):
            extension = _AUDIO_EXTENSION_BY_FORMAT.get(token.strip().lower())
            if extension is not None:
                return extension, duration

        raise PermanentError(
            f"unsupported audio format {raw_format_name!r} - supported: " "mp3, wav, m4a, ogg, flac"
        )
    finally:
        tmp_path.unlink(missing_ok=True)
