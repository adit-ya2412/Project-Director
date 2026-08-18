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


def _pexels_video_response() -> dict:
    return {
        "videos": [
            {
                "id": 857195,
                "width": 1920,
                "height": 1080,
                "url": "https://www.pexels.com/video/aerial-view-of-a-city-857195/",
                "user": {"name": "Ruvim Miksanskiy"},
                "video_files": [
                    {
                        "quality": "hd",
                        "file_type": "video/mp4",
                        "width": 1280,
                        "height": 720,
                        "link": "https://videos.pexels.com/video-files/857195/857195-hd.mp4",
                    },
                    {
                        "quality": "sd",
                        "file_type": "video/mp4",
                        "width": 640,
                        "height": 360,
                        "link": "https://videos.pexels.com/video-files/857195/857195-sd.mp4",
                    },
                ],
            },
            {
                "id": 857196,
                "width": 1920,
                "height": 1080,
                "url": "https://www.pexels.com/video/some-other-clip-857196/",
                "user": {"name": "Someone Else"},
                # No mp4 rendition at all - must be skipped, not crash the search.
                "video_files": [
                    {
                        "quality": "hd",
                        "file_type": "video/webm",
                        "link": "https://videos.pexels.com/video-files/857196/857196-hd.webm",
                    }
                ],
            },
        ]
    }


async def test_video_search_hits_the_videos_endpoint_and_picks_the_hd_rendition(monkeypatch):
    monkeypatch.setattr(settings, "pexels_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "/videos/search" in str(request.url)
        return httpx.Response(200, json=_pexels_video_response())

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    query = AssetQuery(search_terms=["aerial city"], preferred_type="video", shot_id="sh_01")
    candidates = await provider.search(query)

    # The webm-only video has no mp4 rendition and is dropped.
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.media_kind == "video"
    assert candidate.source_url == "https://videos.pexels.com/video-files/857195/857195-hd.mp4"
    assert candidate.width == 1280 and candidate.height == 720  # the HD file's own dimensions
    assert candidate.title == "aerial view of a city"
    assert candidate.author == "Ruvim Miksanskiy"
    assert candidate.licence == "pexels_licence"


async def test_image_search_never_touches_the_video_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "pexels_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "/videos/search" not in str(request.url)
        return httpx.Response(200, json=_pexels_response())

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(_QUERY)  # preferred_type="image"
    assert all(c.media_kind == "image" for c in candidates)


async def test_video_title_falls_back_when_the_url_has_no_slug():
    from app.providers.pexels import _video_title

    assert _video_title({"id": 42, "url": ""}) == "pexels video 42"


async def test_fetch_downloads_video_bytes_and_labels_attribution_as_video():
    candidate = AssetCandidate(
        source_id="857195",
        source_url="https://videos.pexels.com/video-files/857195/857195-hd.mp4",
        title="aerial view of a city",
        licence="pexels_licence",
        author="Ruvim Miksanskiy",
        media_kind="video",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"fake-video-bytes", headers={"content-type": "video/mp4"}
        )

    provider = PexelsAssetProvider(transport=httpx.MockTransport(handler))
    result = await provider.fetch(candidate)

    assert result.content == b"fake-video-bytes"
    assert result.content_type == "video/mp4"
    assert result.attribution == "Video by Ruvim Miksanskiy on Pexels"


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
