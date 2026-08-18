"""Pexels provider (M6, ladder rung `stock_search`). Free tier is
generous; requires PEXELS_API_KEY.

## Video (A7, motion_new_styles_and_long_form_videos.md, 2026-08-18)

`search()` branches on `query.preferred_type`: `"video"` hits Pexels'
separate `/videos/search` endpoint instead of `/v1/search`, returning
`AssetCandidate`s with `media_kind="video"` - the cheapest motion in the
system (free tier, no API-key-per-request cost the way Kling has),
positioned below paid generation on the ladder exactly where `stock_
search` already sits (canon 3.1's "reuse before generate"). This is the
rung that proves the A1/A2 motion-clip renderer path against a REAL
downloaded clip rather than only a synthetic ffmpeg test clip, at zero
spend - `render_timeline`'s own classification (`app/renderer/motion.py`)
needs no changes at all to handle it: it classifies by the FILE CONTENT
it finds at `asset.local_path`, never by this provider's own `media_kind`
field (that field only exists so `ResolveAssetsStep` knows how to
VALIDATE and TYPE the downloaded bytes before they ever reach a render).

⚠ **The exact `/videos/search` response shape below is implemented from
Pexels' documented API structure, not verified against a live call** -
no `PEXELS_API_KEY` is configured in this development environment, so
there was nothing to check it against (the same class of assumption
flagged for the ElevenLabs speed parameter elsewhere in this plan).
Verify against a real response before trusting this in production.
"""

import httpx

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import AssetBytes, AssetCandidate, AssetQuery

_SEARCH_URL = "https://api.pexels.com/v1/search"
_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
_PER_PAGE = 10
# Preference order for which rendition of a Pexels video to actually
# download - "hd" is generous enough for this renderer's own working
# canvas (Ken Burns already upscales to WORKING_CANVAS_SCALE=1.6x target)
# without "uhd"'s multi-hundred-MB downloads for a shot that plays for a
# few seconds.
_VIDEO_QUALITY_PREFERENCE = ("hd", "sd", "uhd")


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

        # A7: which endpoint/parser this call uses, decided ONCE per
        # `search()` call from the query's own `preferred_type` - every
        # candidate this call returns shares the same `media_kind`
        # because of that, never a mix (see `AssetCandidate.media_kind`'s
        # own docstring for why that still isn't inferred at the call
        # site downstream).
        search_one = self._search_one_video if query.preferred_type == "video" else self._search_one

        # Each search_term gets its own request rather than being joined
        # into one long string - see WikimediaAssetProvider.search for why
        # (a shared lesson: real archive/search APIs favour short keyword
        # phrases over one concatenated sentence-length query).
        terms = query.search_terms or [query.shot_id]
        seen_ids: set[str] = set()
        candidates: list[AssetCandidate] = []
        for term in terms:
            for candidate in await search_one(term):
                if candidate.source_id in seen_ids:
                    continue
                seen_ids.add(candidate.source_id)
                candidates.append(candidate)
        return candidates

    async def _get_json(self, url: str, params: dict[str, str]) -> dict:
        """The request + error-mapping every search endpoint below
        shares - split out when video search was added (A7) rather than
        duplicated a second time."""
        # `search()` already checked this is set before calling here; the
        # assert just carries that guarantee across the method boundary
        # for mypy (a `str | None` header value doesn't type-check).
        assert settings.pexels_api_key is not None
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                response = await client.get(
                    url, params=params, headers={"Authorization": settings.pexels_api_key}
                )
                response.raise_for_status()
                return response.json()
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

    async def _search_one(self, search_text: str) -> list[AssetCandidate]:
        data = await self._get_json(_SEARCH_URL, {"query": search_text, "per_page": str(_PER_PAGE)})

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

    async def _search_one_video(self, search_text: str) -> list[AssetCandidate]:
        data = await self._get_json(
            _VIDEO_SEARCH_URL, {"query": search_text, "per_page": str(_PER_PAGE)}
        )

        candidates: list[AssetCandidate] = []
        for rank, video in enumerate(data.get("videos", [])):
            video_file = _pick_video_file(video.get("video_files", []))
            if video_file is None:
                continue  # no downloadable mp4 rendition - skip, don't crash the whole search
            user = video.get("user") or {}
            candidates.append(
                AssetCandidate(
                    source_id=str(video.get("id", "")),
                    source_url=video_file.get("link", ""),
                    title=_video_title(video),
                    licence="pexels_licence",
                    relevance=max(0.3, 1.0 - 0.05 * rank),
                    author=user.get("name", ""),
                    width=video_file.get("width"),
                    height=video_file.get("height"),
                    media_kind="video",
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

        is_video = candidate.media_kind == "video"
        default_content_type = "video/mp4" if is_video else "image/jpeg"
        content_type = response.headers.get("content-type", default_content_type).split(";")[0]
        label = "Video" if is_video else "Photo"
        attribution = f"{label} by {candidate.author} on Pexels".strip()
        return AssetBytes(
            content=response.content, content_type=content_type, attribution=attribution
        )


def _pick_video_file(video_files: list[dict]) -> dict | None:
    """Pexels serves several renditions per video (sd/hd/uhd, sometimes
    more than one file per quality tier) - picks the first `video/mp4`
    file at the most-preferred quality available (`_VIDEO_QUALITY_
    PREFERENCE`), or `None` if this video has no mp4 rendition at all
    (skip it, don't crash the whole search over one odd entry)."""
    mp4_files = [f for f in video_files if f.get("file_type") == "video/mp4"]
    if not mp4_files:
        return None
    by_quality: dict[str, dict] = {}
    for f in mp4_files:
        by_quality.setdefault(f.get("quality", ""), f)
    for quality in _VIDEO_QUALITY_PREFERENCE:
        if quality in by_quality:
            return by_quality[quality]
    return mp4_files[0]


def _video_title(video: dict) -> str:
    """Pexels' video search response has no `alt` text field the way
    photos do - the closest available signal is the descriptive slug
    embedded in the video's own page `url`
    (".../video/aerial-view-of-a-city-1234567/" -> "aerial view of a
    city"), which the relevance gate (app/assets/relevance.py) can at
    least compare against the shot's search terms. Falls back to a
    generic label when the URL doesn't parse as expected, mirroring the
    photo path's own blank-`alt` fallback."""
    url = video.get("url", "") or ""
    video_id = str(video.get("id", ""))
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    parts = slug.split("-")
    if parts and parts[-1].isdigit():
        parts = parts[:-1]  # the trailing numeric id Pexels appends to every slug
    title = " ".join(parts).strip()
    return title or f"pexels video {video_id}"
