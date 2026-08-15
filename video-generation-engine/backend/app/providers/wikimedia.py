"""Wikimedia Commons search provider (M6, ladder rungs `historical_search`
and `public_domain` - Commons hosts both historical archives and general
public-domain media, so one provider serves both rungs), plus
`WikipediaEntityAssetProvider` (M6.5, A1/A2) - entity-name -> images
resolution by deterministic lookup, never an LLM tool call, restricted to
a Wikipedia article's own images (see that class's docstring for why a
Commons-category route was tried, measured, and dropped). Both classes
live in one file because they are the same external service family
(Wikimedia Foundation APIs: en.wikipedia.org + commons.wikimedia.org)
behind the same provider firewall (ADR-003), sharing the same User-Agent
requirement, rate limiter, and licence/HTML-metadata parsing.

No API key required for either class, but a descriptive User-Agent is
mandatory per Wikimedia's API terms - a generic one gets blocked
(implementation guide, Phase M6 advice).
"""

import re
import urllib.parse

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


def _imageinfo_page_to_candidate(
    page: dict, *, rank: int, entity_curated: bool
) -> AssetCandidate | None:
    """Shared MediaWiki `imageinfo` page -> `AssetCandidate` mapping, used
    by both `WikimediaAssetProvider.search` (free-text) and
    `WikipediaEntityAssetProvider` (entity lookup) - the response shape is
    identical either way (verified live: an entity-resolved File page's
    `imageinfo`/`extmetadata` looks exactly like a Commons search hit's),
    only the request that produced the page list differs."""
    imageinfo_list = page.get("imageinfo") or []
    if not imageinfo_list:
        return None
    info = imageinfo_list[0]
    extmetadata = info.get("extmetadata", {})
    licence = _normalise_licence(extmetadata.get("LicenseShortName", {}).get("value", ""))
    artist = _strip_html(extmetadata.get("Artist", {}).get("value", "")) or info.get("user", "")
    # ImageDescription/ObjectName are far richer than the filename alone -
    # a real relevance signal for `app/assets/relevance.py` to match
    # against, not just the bare title.
    description = " ".join(
        _strip_html(extmetadata.get(field, {}).get("value", ""))
        for field in ("ImageDescription", "ObjectName")
    ).strip()
    return AssetCandidate(
        source_id=str(page.get("pageid", page.get("title", ""))),
        source_url=info.get("url", ""),
        title=page.get("title", ""),
        licence=licence,
        relevance=max(0.3, 1.0 - 0.05 * rank),
        author=artist,
        width=info.get("width"),
        height=info.get("height"),
        description=description,
        entity_curated=entity_curated,
    )


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
        # Each search_term is tried as its OWN request rather than joined
        # into one string: Commons' search index matches short, title-like
        # keyword phrases, and a single request built by concatenating
        # every term together (or even one overly long term on its own)
        # reliably returns zero results even for subjects that genuinely
        # have real archival photos on Commons - verified empirically
        # against the live API before this fix.
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
        candidates = [
            candidate
            for rank, page in enumerate(pages)
            if (candidate := _imageinfo_page_to_candidate(page, rank=rank, entity_curated=False))
            is not None
        ]
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


# Only the top hit is used - a lookup is not a judgement (M6.5, A2): no
# heuristic here decides which article is "really" the right one, the
# search API's own top-ranked result is taken directly, same as a human
# typing the entity name into Wikipedia's search box and following the
# first result.
_ENTITY_SEARCH_LIMIT = 1
# Bounds how many files come back before this shot's normal licence/
# relevance gate / dedup / fetch cap
# (`ResolveAssetsStep._CANDIDATES_TO_FETCH_PER_RUNG`) ever sees them - one
# MediaWiki batch request well under its titles limit, not a quality
# decision.
_MAX_ARTICLE_IMAGES = 10
# Matches WikimediaAssetProvider's own `filetype:bitmap` search restriction
# - a raster still image only. The REST media-list endpoint's own
# `type == "image"` field already excludes audio/video, but not vector
# formats (SVG logos/diagrams) or, in principle, anything else a renderer
# can't composite as a photograph; this is a second, explicit floor so
# "whatever survives is renderable" doesn't rely on upstream tagging alone.
_STILL_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "webp"})


def _is_still_image_title(title: str) -> bool:
    extension = title.rsplit(".", 1)[-1].lower() if "." in title else ""
    return extension in _STILL_IMAGE_EXTENSIONS


class WikipediaEntityAssetProvider:
    """Entity -> images resolution (M6.5, A1/A2). The Asset Planner names a
    real-world subject ("Leuna-Werke") as world knowledge only it has;
    turning that name into images is a lookup, not a judgement, so it runs
    here as deterministic code - never an LLM tool call (I4 stands, A3).

    Resolve the entity to an English Wikipedia article via full-text
    search, then take that article's own images via the REST media-list
    endpoint (`/api/rest_v1/page/media-list/{title}`) - checked live
    against the real API rather than guessed: `action=query&generator=
    images` (the "obvious" MediaWiki way) also returns page UI chrome no
    curator ever placed in the article (`Commons-logo.svg`, edit-icon
    SVGs); the REST media-list endpoint returns only images actually
    embedded in the rendered page, each with the editor's own caption.

    **A Commons-category route (`list=categorymembers`) was tried and
    measured, then deliberately removed** - record this so nobody re-adds
    it without re-measuring: a Commons category is a broad filing bucket
    keyed on the *word*, not the *article's subject* - `Category:Ruhr`
    (the entity is the industrial region) surfaced river-purification
    documents, a power station, and a non-image `.ogg` file, because
    "Ruhr" the category is about the *river*. `Category:Leuna-Werke`
    similarly surfaced an unrelated 2011 village snapshot. Article images
    are curated by an editor to illustrate that specific article; category
    membership is filed on a shared word and is not the same kind of
    signal. Only the article-images route survived measurement.

    Every candidate is marked `entity_curated=True` for
    `app/assets/ranking.py` to use as a modest ranking signal - not a
    relevance-gate bypass (an early version of this provider skipped the
    relevance gate for these candidates on the theory that curation
    implies relevance; measured against the live API, that premise is
    false - a Wikipedia article on Fischer-Tropsch legitimately embeds a
    jet engine photo and a chemist's portrait alongside the reactor photo
    that actually matches a shot, all "curated" for that article, only one
    of them on-topic for any given shot. `ResolveAssetsStep` runs these
    through the exact same licence gate, relevance gate, and content-hash
    dedup as every free-text candidate)."""

    name = "wikipedia_entity"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._rate_limiter = RateLimiter(settings.wikimedia_rate_limit_per_second)
        # `fetch()` just downloads a Commons-hosted file by URL - identical
        # to WikimediaAssetProvider's, whether the search that found it was
        # free-text or entity-based. Reused rather than duplicated.
        self._commons = WikimediaAssetProvider(transport=transport)

    async def resolve_entity(self, entity: str) -> list[AssetCandidate]:
        """Empty `entity` (the common case - most shots have no single
        nameable subject, per the prompt) is a no-op, not an error: this
        method is only ever worth calling when the Asset Planner actually
        named something."""
        if not entity.strip():
            return []
        return await self._article_images(entity)

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        return await self._commons.fetch(candidate)

    async def _get_json(self, url: str, params: dict) -> dict:
        await self._rate_limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                response = await client.get(
                    url, params=params, headers={"User-Agent": settings.wikimedia_user_agent}
                )
                response.raise_for_status()
                return response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"wikipedia entity lookup timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(
                    f"wikipedia entity lookup returned {exc.response.status_code}"
                ) from exc
            raise TransientError(f"wikipedia entity lookup failed: {exc}") from exc

    async def _resolve_article_title(self, entity: str) -> str | None:
        data = await self._get_json(
            settings.wikipedia_search_api_url,
            {
                "action": "query",
                "list": "search",
                "srsearch": entity,
                "srnamespace": "0",
                "srlimit": str(_ENTITY_SEARCH_LIMIT),
                "format": "json",
                "formatversion": "2",
            },
        )
        hits = data.get("query", {}).get("search", [])
        return str(hits[0]["title"]) if hits else None

    async def _article_images(self, entity: str) -> list[AssetCandidate]:
        title = await self._resolve_article_title(entity)
        if title is None:
            return []

        # REST path segment, not a query param - MediaWiki's own convention
        # is spaces-as-underscores, percent-encoded (verified live).
        encoded_title = urllib.parse.quote(title.replace(" ", "_"), safe="")
        await self._rate_limiter.wait()
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                response = await client.get(
                    f"{settings.wikipedia_media_list_api_url}/{encoded_title}",
                    headers={"User-Agent": settings.wikimedia_user_agent},
                )
                if response.status_code == 404:
                    return []  # no media-list for this title (rare) - not an error
                response.raise_for_status()
                data = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"wikipedia media-list timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(
                    f"wikipedia media-list returned {exc.response.status_code}"
                ) from exc
            raise TransientError(f"wikipedia media-list failed: {exc}") from exc

        file_titles = [
            item["title"]
            for item in data.get("items", [])
            if item.get("type") == "image"
            and str(item.get("title", "")).startswith("File:")
            and _is_still_image_title(str(item.get("title", "")))
        ][:_MAX_ARTICLE_IMAGES]
        if not file_titles:
            return []

        # A single batch request for every title from this article - well
        # under MediaWiki's per-request titles limit at `_MAX_ARTICLE_IMAGES`.
        data = await self._get_json(
            settings.wikimedia_api_url,
            {
                "action": "query",
                "titles": "|".join(file_titles),
                "prop": "imageinfo",
                "iiprop": "url|size|extmetadata|user",
                "format": "json",
                "formatversion": "2",
            },
        )
        pages = data.get("query", {}).get("pages", [])
        return [
            candidate
            for rank, page in enumerate(pages)
            if (candidate := _imageinfo_page_to_candidate(page, rank=rank, entity_curated=True))
            is not None
        ]
