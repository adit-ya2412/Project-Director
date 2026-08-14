"""WikimediaAssetProvider tests via `httpx.MockTransport` - no real
network, but exercises the real request-building, response-parsing, and
error-mapping code."""

import httpx
import pytest

from app.core.errors import TransientError
from app.providers.base import AssetQuery
from app.providers.wikimedia import WikimediaAssetProvider

_QUERY = AssetQuery(search_terms=["coal mine 1936"], preferred_type="image", shot_id="sh_01")


def _commons_search_response() -> dict:
    return {
        "query": {
            "pages": [
                {
                    "pageid": 111,
                    "title": "File:Ruhr_coal_mine_1936.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/ruhr.jpg",
                            "width": 1920,
                            "height": 1080,
                            "user": "ArchiveUploader",
                            "extmetadata": {
                                "LicenseShortName": {"value": "Public domain"},
                                "Artist": {"value": '<a href="#">Jane Archivist</a>'},
                            },
                        }
                    ],
                },
                {
                    "pageid": 222,
                    "title": "File:Ruhr_factory_1938.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/factory.jpg",
                            "width": 800,
                            "height": 600,
                            "user": "SomeUser",
                            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}},
                        }
                    ],
                },
            ]
        }
    }


async def test_search_parses_candidates_and_normalises_licences():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "User-Agent" in request.headers
        return httpx.Response(200, json=_commons_search_response())

    provider = WikimediaAssetProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(_QUERY)

    assert len(candidates) == 2
    first, second = candidates
    assert first.licence == "public_domain"
    assert first.author == "Jane Archivist"  # HTML stripped
    assert first.width == 1920 and first.height == 1080
    assert second.licence == "cc_by"
    # Earlier search hits rank higher (first result outranks second).
    assert first.relevance > second.relevance


async def test_search_skips_pages_with_no_imageinfo():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"query": {"pages": [{"pageid": 1, "title": "File:x.jpg"}]}}
        )

    provider = WikimediaAssetProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(_QUERY)
    assert candidates == []


async def test_search_tries_each_term_separately_and_dedupes():
    """The Asset Planner emits several distinct short keyword phrases per
    shot (never one concatenated sentence) - each must become its own
    request, with results merged and deduped by pageid rather than joined
    into one query string (verified live: a concatenated or overly long
    query reliably returns zero results even when short keyword terms
    find real archival photos)."""
    seen_queries = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["gsrsearch"])
        if "Leuna Werke" in request.url.params["gsrsearch"]:
            return httpx.Response(200, json=_commons_search_response())
        return httpx.Response(200, json={"query": {"pages": []}})

    provider = WikimediaAssetProvider(transport=httpx.MockTransport(handler))
    query = AssetQuery(
        search_terms=["Leuna Werke", "Fischer-Tropsch"], preferred_type="image", shot_id="sh_01"
    )
    candidates = await provider.search(query)

    assert len(seen_queries) == 2  # one request per term, never joined
    assert not any("Fischer-Tropsch Leuna Werke" in q for q in seen_queries)
    assert len(candidates) == 2  # from the "Leuna Werke" term only


async def test_search_maps_5xx_to_transient_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    provider = WikimediaAssetProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(TransientError):
        await provider.search(_QUERY)


async def test_fetch_downloads_bytes_and_builds_attribution():
    from app.providers.base import AssetCandidate

    candidate = AssetCandidate(
        source_id="111",
        source_url="https://upload.wikimedia.org/wikipedia/commons/ruhr.jpg",
        title="File:Ruhr_coal_mine_1936.jpg",
        licence="public_domain",
        author="Jane Archivist",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"\xff\xd8fakejpegbytes", headers={"content-type": "image/jpeg"}
        )

    provider = WikimediaAssetProvider(transport=httpx.MockTransport(handler))
    result = await provider.fetch(candidate)

    assert result.content == b"\xff\xd8fakejpegbytes"
    assert result.content_type == "image/jpeg"
    assert result.attribution == "Jane Archivist, via Wikimedia Commons"


async def test_fetch_maps_timeout_to_transient_error():
    from app.providers.base import AssetCandidate

    candidate = AssetCandidate(
        source_id="111", source_url="https://upload.wikimedia.org/x.jpg", title="x", licence="cc0"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    provider = WikimediaAssetProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(TransientError):
        await provider.fetch(candidate)
