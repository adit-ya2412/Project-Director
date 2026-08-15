"""WikipediaEntityAssetProvider tests via `httpx.MockTransport` - no real
network, but exercises the real request-routing (English Wikipedia search
+ REST media-list, then a Commons imageinfo batch fetch), the still-image
filter, and error-mapping code.

M6.5, A1/A2, revised after a live-API measurement (see the provider's own
docstring): a Commons-category route was tried and dropped - categories
are broad filing buckets keyed on the word, not the article's subject, and
one measured run surfaced a non-image `.ogg` file plus several off-topic
photos through it. Only the article-images route remains. A second live
measurement also found that skipping the relevance gate for these
candidates let off-topic "curated" images (a jet engine embedded in a
Fischer-Tropsch article, for instance) win outright - so this class no
longer claims relevance for its results at all; gating is entirely
`ResolveAssetsStep`'s job now, identical to free-text candidates.
"""

import httpx
import pytest

from app.core.errors import TransientError
from app.providers.wikimedia import WikipediaEntityAssetProvider


def _imageinfo_response(titles: list[str], *, start_pageid: int) -> dict:
    return {
        "query": {
            "pages": [
                {
                    "pageid": start_pageid + i,
                    "title": title,
                    "imageinfo": [
                        {
                            "url": f"https://upload.wikimedia.org/wikipedia/commons/{title}",
                            "width": 1024,
                            "height": 768,
                            "user": "ArchiveUploader",
                            "extmetadata": {
                                "LicenseShortName": {"value": "Public domain"},
                                "Artist": {"value": "Jane Archivist"},
                            },
                        }
                    ],
                }
                for i, title in enumerate(titles)
            ]
        }
    }


def _handler_factory(
    *,
    article_title: str | None = "Leuna works",
    media_list_status: int = 200,
    media_list_items: list[dict] | None = None,
):
    if media_list_items is None:
        media_list_items = [
            {"type": "image", "title": "File:Article_Image_A.jpg"},
            {"type": "image", "title": "File:Article_Image_B.jpg"},
            {"type": "TemplateStyles", "title": "not an image"},
        ]

    async def handler(request: httpx.Request) -> httpx.Response:
        url = request.url

        if url.host == "en.wikipedia.org" and url.path == "/w/api.php":
            assert url.params["list"] == "search"
            assert url.params["srnamespace"] == "0"
            hits = [{"title": article_title}] if article_title else []
            return httpx.Response(200, json={"query": {"search": hits}})

        if url.host == "en.wikipedia.org" and url.path.startswith("/api/rest_v1/page/media-list/"):
            if media_list_status == 404:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json={"items": media_list_items})

        if url.host == "commons.wikimedia.org" and url.params.get("prop") == "imageinfo":
            titles = url.params["titles"].split("|")
            return httpx.Response(200, json=_imageinfo_response(titles, start_pageid=10))

        raise AssertionError(f"unexpected request: {url}")

    return handler


async def test_resolve_entity_returns_the_articles_own_images():
    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(_handler_factory()))
    candidates = await provider.resolve_entity("Leuna-Werke")

    assert len(candidates) == 2  # the two image items, not the TemplateStyles one
    assert all(c.entity_curated for c in candidates)
    assert all(c.licence == "public_domain" for c in candidates)


async def test_resolve_entity_is_a_noop_for_an_empty_entity():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call should be made for an empty entity")

    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(handler))
    assert await provider.resolve_entity("") == []
    assert await provider.resolve_entity("   ") == []


async def test_resolve_entity_returns_empty_when_no_article_matches():
    handler = _handler_factory(article_title=None)
    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(handler))
    assert await provider.resolve_entity("a very obscure made-up thing") == []


async def test_resolve_entity_treats_a_missing_media_list_as_empty_not_an_error():
    handler = _handler_factory(media_list_status=404)
    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(handler))
    assert await provider.resolve_entity("Leuna-Werke") == []


async def test_media_list_filters_out_non_image_items():
    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(_handler_factory()))
    candidates = await provider.resolve_entity("Leuna-Werke")
    titles = {c.title for c in candidates}
    assert "not an image" not in titles


async def test_still_image_filter_excludes_vector_and_non_raster_formats():
    """A live measurement found the category route surfacing a non-image
    `.ogg` file; the article-images route's own `type == "image"` field
    already excludes audio/video, but not vector/logo formats - this is
    the second, explicit floor (M6.5 fix)."""
    handler = _handler_factory(
        media_list_items=[
            {"type": "image", "title": "File:Real_Photo.jpg"},
            {"type": "image", "title": "File:Some_Logo.svg"},
        ]
    )
    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.resolve_entity("Leuna-Werke")

    assert len(candidates) == 1
    assert candidates[0].title == "File:Real_Photo.jpg"


async def test_search_maps_5xx_to_transient_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(TransientError):
        await provider.resolve_entity("Leuna-Werke")


async def test_fetch_delegates_to_the_same_commons_download_logic():
    from app.providers.base import AssetCandidate

    candidate = AssetCandidate(
        source_id="10",
        source_url="https://upload.wikimedia.org/wikipedia/commons/x.jpg",
        title="File:x.jpg",
        licence="public_domain",
        entity_curated=True,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "User-Agent" in request.headers
        return httpx.Response(
            200, content=b"\xff\xd8fakejpegbytes", headers={"content-type": "image/jpeg"}
        )

    provider = WikipediaEntityAssetProvider(transport=httpx.MockTransport(handler))
    result = await provider.fetch(candidate)
    assert result.content == b"\xff\xd8fakejpegbytes"
