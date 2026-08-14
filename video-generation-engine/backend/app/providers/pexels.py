"""Pexels provider (M6, ladder rung `stock_search`). Free tier is
generous; requires PEXELS_API_KEY."""

import httpx

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import AssetBytes, AssetCandidate, AssetQuery

_SEARCH_URL = "https://api.pexels.com/v1/search"
_PER_PAGE = 10


class PexelsAssetProvider:
    name = "pexels"
    rung = "stock_search"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` is None in production (real network); tests inject
        # an `httpx.MockTransport` to exercise request/response handling
        # without a real network call.
        self._transport = transport

    async def search(self, query: AssetQuery) -> list[AssetCandidate]:
        if not settings.pexels_api_key:
            raise PermanentError("PEXELS_API_KEY is not configured")

        # Each search_term gets its own request rather than being joined
        # into one long string - see WikimediaAssetProvider.search for why
        # (a shared lesson: real archive/search APIs favour short keyword
        # phrases over one concatenated sentence-length query).
        terms = query.search_terms or [query.shot_id]
        seen_ids: set[str] = set()
        candidates: list[AssetCandidate] = []
        for term in terms:
            for candidate in await self._search_one(term):
                if candidate.source_id in seen_ids:
                    continue
                seen_ids.add(candidate.source_id)
                candidates.append(candidate)
        return candidates

    async def _search_one(self, search_text: str) -> list[AssetCandidate]:
        # `search()` already checked this is set before calling here; the
        # assert just carries that guarantee across the method boundary
        # for mypy (a `str | None` header value doesn't type-check).
        assert settings.pexels_api_key is not None
        params = {"query": search_text, "per_page": str(_PER_PAGE)}
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={"Authorization": settings.pexels_api_key},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"pexels search timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(f"pexels search returned {exc.response.status_code}") from exc
            if exc.response.status_code in (401, 403):
                raise PermanentError(
                    f"pexels rejected the API key: {exc.response.status_code}"
                ) from exc
            raise TransientError(f"pexels search failed: {exc}") from exc

        candidates: list[AssetCandidate] = []
        for rank, photo in enumerate(data.get("photos", [])):
            src = photo.get("src", {})
            candidates.append(
                AssetCandidate(
                    source_id=str(photo.get("id", "")),
                    source_url=src.get("original", src.get("large", "")),
                    title=photo.get("alt", "") or f"pexels photo {photo.get('id', '')}",
                    licence="pexels_licence",
                    relevance=max(0.3, 1.0 - 0.05 * rank),
                    author=photo.get("photographer", ""),
                    width=photo.get("width"),
                    height=photo.get("height"),
                )
            )
        return candidates

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                response = await client.get(candidate.source_url, follow_redirects=True)
                response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"pexels fetch timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(f"pexels fetch returned {exc.response.status_code}") from exc
            raise TransientError(f"pexels fetch failed: {exc}") from exc

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        attribution = f"Photo by {candidate.author} on Pexels".strip()
        return AssetBytes(
            content=response.content, content_type=content_type, attribution=attribution
        )
