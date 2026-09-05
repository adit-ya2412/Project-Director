"""F1a: deterministic substrate crop (illustrated_faceless.md §8.1,
2026-09-05).

Real stills from a `GENERATION_ONLY` style periodically come back with an
off-white paper margin at the frame edge - sometimes with a signature mark
or a stamp. Two rounds of prompt wording tried to remove it (§1.7,
`P-IF-F1-fixes`) and both failed on a real render; §4.10 records why a
third rewording is a poor bet. The fix here is not linguistic: request the
image slightly oversized
(`app/script/styles.py::resolve_generation_request_format`) and centre-crop
it back to the style's exact canvas, in code, before anything is
persisted - a margin sitting at the edge falls outside the frame by
construction, regardless of what the prompt says.

`center_crop_to_canvas` below is the crop itself: pure, deterministic (I5)
- a function of the delivered bytes and the target canvas alone, no RNG,
no wall-clock. It does not decide WHETHER to crop or by how much (that is
`resolve_generation_request_format`'s job, style-scoped); it only ever
performs the one operation once a caller has already decided a crop is
needed.
"""

import io

from PIL import Image


def center_crop_to_canvas(image_bytes: bytes, canvas_width: int, canvas_height: int) -> bytes:
    """Crop `image_bytes` to exactly `canvas_width`x`canvas_height`,
    centred. Raises `ValueError` if the delivered image is smaller than
    the canvas in either dimension - a caller asking for an oversized
    request (`resolve_generation_request_format`) should never hit this,
    so surfacing it loudly beats silently cropping something meaningless.

    Preserves the original image's format (PNG/JPEG/etc.) rather than
    forcing one, so the caller's own `validate_and_identify_image` still
    determines the persisted file's real extension from the CROPPED
    bytes, exactly as it already does for the uncropped path.

    Deterministic and side-effect-free: the same bytes and the same
    target canvas always produce the same output, every time - this is
    what makes it safe to run against provider bytes that are themselves
    only as deterministic as the provider call that produced them (an
    existing, system-wide assumption this function does not add to).
    """
    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
        if width < canvas_width or height < canvas_height:
            raise ValueError(
                f"delivered image ({width}x{height}) is smaller than the canvas "
                f"({canvas_width}x{canvas_height}) it must be centre-cropped to - the "
                "request must ask for an image at least as large as the canvas in both "
                "dimensions (illustrated_faceless.md F1a)"
            )
        left = (width - canvas_width) // 2
        top = (height - canvas_height) // 2
        cropped = image.crop((left, top, left + canvas_width, top + canvas_height))
        buffer = io.BytesIO()
        cropped.save(buffer, format=image.format or "PNG")
        return buffer.getvalue()
