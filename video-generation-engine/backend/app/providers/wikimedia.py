"""Wikimedia Commons provider (M6, ladder rungs `historical_search` and
`public_domain` - Commons hosts both historical archives and general
public-domain media, so one provider serves both rungs). No API key
required, but a descriptive User-Agent is mandatory per Wikimedia's API
terms - a generic one gets blocked (implementation guide, Phase M6
advice).
"""

import re

import httpx

from app.assets.rate_limit import RateLimiter
from app.core.config import settings
from app.core.errors import TransientError
from app.providers.base import AssetBytes, AssetCandidate, AssetQuery

_HTML_TAG_RE = re.compile(r"<[^>]+>")

_LICENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"public domain|pd-", re.IGNORECASE), "public_domain"),
    (re.compile(r"cc0", re.IGNORECASE), "cc0"),
    (re.compile(r"cc[\s-]?by", re.IGNORECASE), "cc_by"),
]


def _strip_html(value: str) -> str:
    return _HTML_TAG_RE.sub("", value).strip()


def _normalise_licence(license_short_name: str) -> str:
    for pattern, licence in _LICENCE_PATTERNS:
        if pattern.search(license_short_name):
            return licence
    return "unknown"


class WikimediaAssetProvider:
    name = "wikimedia"

    def __init__(
        self, rung: str = "historical_search", transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.rung = rung
        self._rate_limiter = RateLimiter(settings.wikimedia_rate_limit_per_second)
        # `transport` is None in production (real network); tests inject an
        # `httpx.MockTransport` to exercise this class's request/response
        # handling without a real network call.
        self._transport = transport

    async def search(self, query: AssetQuery) -> list[AssetCandidate]:
        search_text = " ".join(query.search_terms) or query.shot_id
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {search_text}",
            "gsrnamespace": "6",  # File namespace
            "gsrlimit": "10",
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|user",
            "format": "json",
            "formatversion": "2",
        }
        await self._rate_limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                response = await client.get(
                    settings.wikimedia_api_url,
                    params=params,
                    headers={"User-Agent": settings.wikimedia_user_agent},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"wikimedia search timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(
                    f"wikimedia search returned {exc.response.status_code}"
                ) from exc
            raise TransientError(f"wikimedia search failed: {exc}") from exc

        pages = data.get("query", {}).get("pages", [])
        candidates: list[AssetCandidate] = []
        for rank, page in enumerate(pages):
            imageinfo_list = page.get("imageinfo") or []
            if not imageinfo_list:
                continue
            info = imageinfo_list[0]
            extmetadata = info.get("extmetadata", {})
            licence = _normalise_licence(extmetadata.get("LicenseShortName", {}).get("value", ""))
            artist = _strip_html(extmetadata.get("Artist", {}).get("value", "")) or info.get(
                "user", ""
            )
            candidates.append(
                AssetCandidate(
                    source_id=str(page.get("pageid", page.get("title", ""))),
                    source_url=info.get("url", ""),
                    title=page.get("title", ""),
                    licence=licence,
                    relevance=max(0.3, 1.0 - 0.05 * rank),
                    author=artist,
                    width=info.get("width"),
                    height=info.get("height"),
                )
            )
        return candidates

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        await self._rate_limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                response = await client.get(
                    candidate.source_url,
                    headers={"User-Agent": settings.wikimedia_user_agent},
                    follow_redirects=True,
                )
                response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"wikimedia fetch timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(
                    f"wikimedia fetch returned {exc.response.status_code}"
                ) from exc
            raise TransientError(f"wikimedia fetch failed: {exc}") from exc

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        attribution = f"{candidate.author}, via Wikimedia Commons".strip(", ")
        return AssetBytes(
            content=response.content, content_type=content_type, attribution=attribution
        )
