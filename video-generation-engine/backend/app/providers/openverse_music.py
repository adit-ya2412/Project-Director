"""Openverse music provider (M8, D6/21.2) - the real, working
`MusicProvider`.

`https://api.openverse.org/v1/audio/` is a free, public, KEYLESS search
API aggregating openly-licensed audio from Jamendo, Freesound and others
- verified live 2026-08-15 (`GET .../v1/audio/?q=...` succeeds with no
auth header at all). This is what `app/providers/pixabay_music.py`
cannot be: Pixabay has no equivalent endpoint at all (verified the same
day - see that module's own docstring).

## The licence gate is load-bearing here, not ceremonial

Openverse's unfiltered pool is dominated by `by-nc-nd` - unusable twice
over for this system: NoDerivatives conflicts with bedding-and-ducking a
track under narration (producing a mixed derivative of it), and
NonCommercial limits what the finished video can legally be used for.
Filtered at the QUERY (`license=cc0,by` - fewer wasted, unusable results)
and gated AGAIN on every RESPONSE (`_ACCEPTABLE_LICENCES`, below) - a
third-party API's own query-time filter is never trusted blindly, the
same discipline the licence gate already applies to every visual asset
provider.

## Expect thin, uneven results - and that this is normal

Verified live: `documentary ambient` -> 81 permissively-licensed
results; `tense drone` -> 46; `historical documentary` -> 2 (both room-
ambience field recordings, not music); `sombre orchestral` -> 0. A
narrow `music_plan` legitimately finds nothing on a real search - that
degrades to `selected_track=None, selection_attempted=True` in
`SelectMusicStep` exactly like a Pixabay provider outage would, and the
project renders silent-but-narrated. This is an expected outcome of a
free, thin catalogue, not an error path to special-case.

`by` requires attribution, and Openverse already hands back a precise,
ready-to-use sentence (licence version and URL included) in its own
`attribution` field - carried through on `TrackCandidate.attribution`
rather than reconstructed from `creator`/`license` here, since Openverse's
own text is more legally precise than anything this module would build.
"""

import httpx

from app.core.errors import PermanentError, TransientError
from app.providers.base import AudioBytes, MusicSearchQuery, TrackCandidate

_SEARCH_URL = "https://api.openverse.org/v1/audio/"
_PAGE_SIZE = 10
_ACCEPTABLE_LICENCES = frozenset({"cc0", "by"})


class OpenverseMusicProvider:
    name = "openverse"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` is None in production (real network); tests inject
        # an `httpx.MockTransport` to exercise request/response handling
        # without a real network call - same pattern as
        # `PexelsAssetProvider`/`WikimediaAssetProvider`.
        self._transport = transport

    async def search(self, query: MusicSearchQuery) -> list[TrackCandidate]:
        # Each search_term gets its own request rather than being joined
        # into one long string - the same lesson every other real search
        # provider in this codebase already learned (short keyword
        # phrases find real results; one long concatenated sentence does
        # not).
        terms = query.search_terms or [query.mood or "instrumental"]
        seen_ids: set[str] = set()
        candidates: list[TrackCandidate] = []
        for term in terms:
            for candidate in await self._search_one(term):
                if candidate.source_id in seen_ids:
                    continue
                seen_ids.add(candidate.source_id)
                candidates.append(candidate)
        return candidates

    async def _search_one(self, search_text: str) -> list[TrackCandidate]:
        params = {
            "q": search_text,
            "license": ",".join(sorted(_ACCEPTABLE_LICENCES)),
            "page_size": str(_PAGE_SIZE),
        }
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                response = await client.get(_SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"openverse search timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(
                    f"openverse search returned {exc.response.status_code}"
                ) from exc
            raise PermanentError(f"openverse search failed: {exc}") from exc

        candidates: list[TrackCandidate] = []
        for result in data.get("results", []):
            licence = (result.get("license") or "").lower()
            if licence not in _ACCEPTABLE_LICENCES:
                # Never trust the query-time filter alone (explicit
                # instruction: "gate again on the response") - a
                # licence-version mismatch, an API quirk, or a future
                # change on Openverse's side must never silently widen
                # what this provider is willing to hand back.
                continue
            url = result.get("url")
            if not url:
                continue
            tags = ", ".join(t.get("name", "") for t in (result.get("tags") or []) if t.get("name"))
            duration_ms = result.get("duration")
            candidates.append(
                TrackCandidate(
                    source_id=str(result.get("id", "")),
                    source_url=url,
                    title=result.get("title") or "",
                    licence=licence,
                    author=result.get("creator") or "",
                    duration_s=(duration_ms / 1000.0) if isinstance(duration_ms, int) else None,
                    tags=tags,
                    attribution=result.get("attribution") or "",
                )
            )
        return candidates

    async def fetch(self, candidate: TrackCandidate) -> AudioBytes:
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                response = await client.get(candidate.source_url, follow_redirects=True)
                response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"openverse fetch timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(
                    f"openverse fetch returned {exc.response.status_code}"
                ) from exc
            raise PermanentError(f"openverse fetch failed: {exc}") from exc

        content_type = response.headers.get("content-type", "audio/mpeg").split(";")[0]
        attribution = candidate.attribution or (
            f"{candidate.title} by {candidate.author}".strip()
            if candidate.author
            else candidate.title
        )
        return AudioBytes(
            content=response.content, content_type=content_type, attribution=attribution
        )
