"""Fake image provider.

Draws the shot's prompt text onto a solid-colour PNG instead of calling a
paid image generation API. Colour is derived deterministically from the
prompt so repeated runs are visually identical (Invariant I5 applies to
fakes too — DRY_RUN mode must be reproducible).

This is not throwaway scaffolding: it stays forever as the DRY_RUN
implementation and as the fast, free unit-test double (implementation
guide section 4.1).
"""

import hashlib
import io
import textwrap

from PIL import Image, ImageDraw

from app.providers.base import ImageRequest, ImageResult


def _colour_for(prompt: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    # Keep it in a muted, readable range rather than full RGB noise.
    r = 40 + digest[0] % 120
    g = 40 + digest[1] % 120
    b = 40 + digest[2] % 120
    return (r, g, b)


class FakeImageProvider:
    name = "fake_image"

    async def generate(self, request: ImageRequest) -> ImageResult:
        colour = _colour_for(request.prompt)
        image = Image.new("RGB", (request.width, request.height), color=colour)
        draw = ImageDraw.Draw(image)

        label = f"[GENERATED]\nshot: {request.shot_id}\n\n" + "\n".join(
            textwrap.wrap(request.prompt, width=28)
        )
        text_colour = (255, 255, 255)
        margin = 40
        draw.multiline_text((margin, margin), label, fill=text_colour, spacing=8)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return ImageResult(content=buffer.getvalue(), content_type="image/png")
