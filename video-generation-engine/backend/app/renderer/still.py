"""Normalise a shot's resolved media to a single still frame the slideshow
renderer can actually loop.

`render_timeline` feeds every shot image to ffmpeg as `-loop 1 -t <dur> -i
<file>`. That is correct for a plain still (the `image2` demuxer accepts
`-loop`), but ffmpeg picks its demuxer from the file's CONTENT, and an
animated format gets a different demuxer that has no `loop` input option -
ffmpeg then aborts the whole render with "Option loop not found" before
producing a single frame. One animated GIF among a shot's assets therefore
takes down the entire video, not just its own shot.

This is not hypothetical: the asset ladder legitimately returns GIFs.
Wikimedia Commons stores plenty of maps and process diagrams as GIF, and
`app/assets/validation.py` accepts the format precisely because it IS a
valid image. The mismatch is in what the RENDERER can loop, not in what
the asset pipeline should collect - so the fix belongs here, converting
the first frame to a PNG, rather than upstream discarding otherwise good
archival material.

Deliberately conservative: anything already a plain, non-animated still is
passed through untouched (no re-encode, no quality loss, no wasted work).
Only formats that would break the loop get converted.
"""

import io
from pathlib import Path

from PIL import Image

from app.core.logging import get_logger
from app.renderer.slideshow import RenderSettings, run_ffmpeg

logger = get_logger(__name__)

# Formats ffmpeg's image2 demuxer loops happily when they hold a single
# frame. GIF is absent on purpose - even a single-frame GIF is opened by
# the gif demuxer, which rejects `-loop`.
_LOOPABLE_STILL_FORMATS = frozenset({"JPEG", "PNG", "BMP", "TIFF"})


def needs_normalising(path: Path) -> bool:
    """True if ffmpeg would refuse to `-loop` this file as a still."""
    try:
        with Image.open(path) as image:
            image_format = image.format
            is_animated = bool(getattr(image, "is_animated", False))
    except (OSError, ValueError):
        # Not something Pillow reads (e.g. a video clip from a stock
        # provider). It certainly isn't a loopable still, so let the
        # converter take its first frame.
        return True
    return is_animated or image_format not in _LOOPABLE_STILL_FORMATS


async def ensure_still_image(
    path: Path, *, shot_id: str, work_dir: Path, settings: RenderSettings
) -> Path:
    """`path` if it is already a loopable still, else a PNG of its first
    frame written into `work_dir`. The original asset file is never
    modified - it stays exactly as downloaded, with its content hash
    still describing its bytes."""
    if not needs_normalising(path):
        return path

    normalised = work_dir / f"{shot_id}_still.png"
    logger.info(
        "render.normalising_non_still_asset",
        extra={"shot_id": shot_id, "source": str(path), "target": str(normalised)},
    )
    # `-frames:v 1` takes the first frame and stops; `-update 1` tells the
    # image encoder it is writing one file rather than a numbered sequence.
    await run_ffmpeg(
        [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(normalised),
        ]
    )
    return normalised


def first_frame_png_bytes(content: bytes) -> bytes:
    """Pillow-only variant for callers holding bytes rather than a path
    (tests, and any future in-memory path). Same contract: first frame,
    PNG, flattened."""
    with Image.open(io.BytesIO(content)) as image:
        image.seek(0)
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()
