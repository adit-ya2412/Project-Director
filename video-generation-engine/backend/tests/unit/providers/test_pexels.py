"""PexelsAssetProvider tests via `httpx.MockTransport` - no real network,
but exercises the real request-building, response-parsing, and
error-mapping code."""

import httpx
import pytest

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import AssetCandidate, AssetQuery
from app.providers.pexels import PexelsAssetProvider

_QUERY = AssetQuery(search_terms=["oil derrick 1930s"], preferred_type="image", shot_id="sh_02")


def _pexels_response() -> dict:
    return {
        "photos": [
            {
                "id": 42,
                "width": 1920,
                "height": 1280,
                "alt": "vintage oil derrick",
                "photographer": "John Shutter",
                "src": {"original": "https://images.pexels.com/photos/42/original.jpg"},
            },
            {
                "id": 43,
                "width": 1200,
                "height": 800,
                "alt": "",
                "photographer": "Jane Lens",
                "src": {"original": "https://images.pexels.com/photos/43/original.jpg"},
            },
        ]
    }


async def test_search_parses_photos_and_always_uses_pexels_licence(monkeypatch):
    monkeypatch.setattr(settings, "pexels_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "fake-key"
        return httpx.Response(200, json=_pexels_response())

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(_QUERY)

    assert len(candidates) == 2
    assert all(c.licence == "pexels_licence" for c in candidates)
    assert candidates[0].title == "vintage oil derrick"
    assert candidates[1].title == "pexels photo 43"  # falls back when alt text is blank
    assert candidates[0].relevance > candidates[1].relevance


async def test_search_tries_each_term_separately_and_dedupes(monkeypatch):
    monkeypatch.setattr(settings, "pexels_api_key", "fake-key")
    seen_queries = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["query"])
        return httpx.Response(200, json=_pexels_response())

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    query = AssetQuery(
        search_terms=["oil derrick 1930s", "coal refinery"], preferred_type="image", shot_id="sh_02"
    )
    candidates = await provider.search(query)

    assert seen_queries == ["oil derrick 1930s", "coal refinery"]  # separate, never joined
    assert len(candidates) == 2  # same photo ids from both calls deduped, not doubled


async def test_search_without_api_key_raises_permanent_error(monkeypatch):
    monkeypatch.setattr(settings, "pexels_api_key", None)
    provider = PexelsAssetProvider()
    with pytest.raises(PermanentError, match="PEXELS_API_KEY"):
        await provider.search(_QUERY)


async def test_search_maps_401_to_permanent_error(monkeypatch):
    monkeypatch.setattr(settings, "pexels_api_key", "bad-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(PermanentError, match="rejected the API key"):
        await provider.search(_QUERY)


async def test_search_maps_5xx_to_transient_error(monkeypatch):
    monkeypatch.setattr(settings, "pexels_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(TransientError):
        await provider.search(_QUERY)


async def test_fetch_downloads_bytes_and_builds_attribution():
    candidate = AssetCandidate(
        source_id="42",
        source_url="https://images.pexels.com/photos/42/original.jpg",
        title="vintage oil derrick",
        licence="pexels_licence",
        author="John Shutter",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"fakebytes", headers={"content-type": "image/jpeg"})

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    result = await provider.fetch(candidate)

    assert result.content == b"fakebytes"
    assert result.attribution == "Photo by John Shutter on Pexels"
