"""Fake asset provider.

Always "finds" one candidate and returns a checkerboard image labelled with
the search terms, standing in for a real search-and-download from Wikimedia
/ Pexels / project assets (M6). Deterministic per query so DRY_RUN runs are
reproducible.
"""

import hashlib
import io
import textwrap

from PIL import Image, ImageDraw

from app.providers.base import AssetBytes, AssetCandidate, AssetQuery

_CELL = 64


def _checkerboard(width: int, height: int, seed: int) -> Image.Image:
    light = (60 + seed % 100, 60 + (seed * 3) % 100, 60 + (seed * 7) % 100)
    dark = tuple(max(0, c - 40) for c in light)
    image = Image.new("RGB", (width, height), color=light)
    draw = ImageDraw.Draw(image)
    for row, y in enumerate(range(0, height, _CELL)):
        for col, x in enumerate(range(0, width, _CELL)):
            if (row + col) % 2 == 1:
                draw.rectangle([x, y, x + _CELL, y + _CELL], fill=dark)
    return image


class FakeAssetProvider:
    """Stands in for any real AssetProvider (Wikimedia, Pexels, project
    library) during DRY_RUN and in unit tests."""

    def __init__(self, name: str = "fake_asset", rung: str = "historical_search") -> None:
        self.name = name
        self.rung = rung

    async def search(self, query: AssetQuery) -> list[AssetCandidate]:
        key = "|".join(query.search_terms) or query.shot_id
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        return [
            AssetCandidate(
                source_id=digest,
                source_url=f"fake://asset/{digest}",
                title=f"fake asset for {key}",
                licence="cc0",
                relevance=0.9,
                width=1080,
                height=1920,
            )
        ]

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        seed = int(candidate.source_id, 16) % 1000
        width, height = 1080, 1920
        image = _checkerboard(width, height, seed)
        draw = ImageDraw.Draw(image)
        label = "[STOCK/ARCHIVE]\n" + "\n".join(
            textwrap.wrap(f"source: {candidate.source_id}", width=28)
        )
        draw.multiline_text((40, 40), label, fill=(255, 255, 255), spacing=8)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return AssetBytes(content=buffer.getvalue(), content_type="image/png")
