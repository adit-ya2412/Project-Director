"""Placeholder image for a shot whose asset/clip never resolved.

Keeps a render completing even when one shot's media failed (Principle
10: failure is per-task, not per-project) - a 59-shot video with one
gap is far more useful than no video at all.
"""

import io

from PIL import Image, ImageDraw


def render_placeholder(shot_id: str, width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(30, 30, 30))
    draw = ImageDraw.Draw(image)
    draw.multiline_text(
        (40, 40),
        f"[MISSING MEDIA]\nshot: {shot_id}",
        fill=(200, 60, 60),
        spacing=8,
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
