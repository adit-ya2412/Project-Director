"""`OpenverseMusicProvider` tests via `httpx.MockTransport` - no real
network, but exercises the real request-building, response-parsing, and
licence re-gating code. Mirrors test_pexels.py's pattern exactly."""

import httpx

from app.providers.base import MusicSearchQuery, TrackCandidate
from app.providers.openverse_music import OpenverseMusicProvider

_QUERY = MusicSearchQuery(
    mood="sombre", tempo="slow", energy_arc="build", search_terms=["documentary underscore"]
)


def _openverse_response(results: list[dict]) -> dict:
    return {
        "result_count": len(results),
        "page_count": 1,
        "page_size": 10,
        "page": 1,
        "results": results,
    }


def _result(
    result_id: str,
    licence: str,
    *,
    url: str = "https://cdn.example.test/track.mp3",
    title: str = "A track",
    creator: str = "Some Artist",
    duration_ms: int | None = 120_000,
    attribution: str = "",
    tags: list[str] | None = None,
) -> dict:
    return {
        "id": result_id,
        "title": title,
        "license": licence,
        "creator": creator,
        "url": url,
        "duration": duration_ms,
        "attribution": attribution,
        "tags": [{"name": t} for t in (tags or [])],
    }


async def test_search_sends_the_query_and_the_licence_filter(monkeypatch):
    seen_params = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_params["q"] = request.url.params["q"]
        seen_params["license"] = request.url.params["license"]
        return httpx.Response(200, json=_openverse_response([]))

    provider = OpenverseMusicProvider(transport=httpx.MockTransport(handler))
    await provider.search(_QUERY)

    assert seen_params["q"] == "documentary underscore"
    assert set(seen_params["license"].split(",")) == {"cc0", "by"}


async def test_search_parses_a_permissively_licensed_result():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_openverse_response(
                [
                    _result(
                        "abc123",
                        "by",
                        title="Cinematic Documentary Ambient",
                        creator="UNIVERSFIELD",
                        duration_ms=226_235,
                        attribution='"Cinematic Documentary Ambient" by UNIVERSFIELD is licensed under CC BY 4.0.',
                        tags=["ambient", "documentary"],
                    )
                ]
            ),
        )

    provider = OpenverseMusicProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(_QUERY)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_id == "abc123"
    assert candidate.licence == "by"
    assert candidate.author == "UNIVERSFIELD"
    assert candidate.duration_s == 226.235
    assert "ambient" in candidate.tags
    assert candidate.attribution.startswith('"Cinematic Documentary Ambient"')


async def test_search_re_gates_on_the_response_never_trusting_the_api_filter_alone():
    """The licence gate is load-bearing, not ceremonial (explicit
    instruction) - a `by-nc-nd` result slipping through the query filter
    (a real, dominant licence in Openverse's unfiltered pool) must still
    be discarded here."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_openverse_response(
                [
                    _result("nc-nd-track", "by-nc-nd"),
                    _result("ok-track", "cc0"),
                ]
            ),
        )

    provider = OpenverseMusicProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(_QUERY)

    assert [c.source_id for c in candidates] == ["ok-track"]


async def test_search_skips_results_with_no_download_url():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openverse_response([_result("no-url", "cc0", url="")]))

    provider = OpenverseMusicProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(_QUERY)
    assert candidates == []


async def test_search_tries_each_term_separately_and_dedupes():
    seen_queries = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["q"])
        return httpx.Response(200, json=_openverse_response([_result("same-id", "cc0")]))

    provider = OpenverseMusicProvider(transport=httpx.MockTransport(handler))
    query = MusicSearchQuery(
        mood="sombre", tempo="slow", energy_arc="flat", search_terms=["term one", "term two"]
    )
    candidates = await provider.search(query)

    assert seen_queries == ["term one", "term two"]
    assert len(candidates) == 1  # same id from both calls deduped, not doubled


async def test_fetch_downloads_bytes_and_prefers_the_providers_own_attribution():
    candidate = TrackCandidate(
        source_id="abc123",
        source_url="https://cdn.example.test/track.mp3",
        title="A track",
        licence="by",
        author="Some Artist",
        attribution='"A track" by Some Artist is licensed under CC BY 4.0.',
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"fake-audio-bytes", headers={"content-type": "audio/mpeg"}
        )

    provider = OpenverseMusicProvider(transport=httpx.MockTransport(handler))
    result = await provider.fetch(candidate)

    assert result.content == b"fake-audio-bytes"
    assert result.attribution == candidate.attribution


async def test_fetch_falls_back_to_title_and_author_when_no_attribution_string():
    candidate = TrackCandidate(
        source_id="abc123",
        source_url="https://cdn.example.test/track.mp3",
        title="A track",
        licence="cc0",
        author="Some Artist",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"fake-audio-bytes", headers={"content-type": "audio/mpeg"}
        )

    provider = OpenverseMusicProvider(transport=httpx.MockTransport(handler))
    result = await provider.fetch(candidate)

    assert result.attribution == "A track by Some Artist"
