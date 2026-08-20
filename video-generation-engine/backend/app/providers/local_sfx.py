"""Local curated SFX library (parent plan §5.5). Same shape as
`LocalMusicProvider`: manifest + files on disk, no network at fetch.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.errors import PermanentError
from app.providers.base import AudioBytes, MusicSearchQuery, TrackCandidate

_MANIFEST_FILENAME = "manifest.json"


@lru_cache(maxsize=1)
def _load_manifest(library_root: Path) -> tuple[dict, ...]:
    manifest_path = library_root / _MANIFEST_FILENAME
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PermanentError(f"sfx library manifest not found at {manifest_path}") from exc
    return tuple(json.loads(raw))


def _candidate(entry: dict) -> TrackCandidate:
    tag_words = f"{entry['kind']} {entry.get('tags') or ''}"
    attribution = entry.get("attribution") or (
        f'"{entry["title"]}" by {entry["artist"]} ({entry["source"]}, {entry["license"]})'
    )
    return TrackCandidate(
        source_id=entry["file"],
        source_url=entry["source_url"],
        title=entry["title"],
        licence=entry["license"],
        author=entry["artist"],
        duration_s=entry["duration_s"],
        tags=tag_words,
        attribution=attribution,
    )


class LocalSfxProvider:
    name = "local_sfx"

    async def search(self, query: MusicSearchQuery) -> list[TrackCandidate]:
        kind = (query.mood or "").strip()
        entries = _load_manifest(settings.sfx_library_root)
        if kind:
            entries = tuple(e for e in entries if e.get("kind") == kind)
        return [_candidate(entry) for entry in entries]

    async def fetch(self, candidate: TrackCandidate) -> AudioBytes:
        path = settings.sfx_library_root / candidate.source_id
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise PermanentError(f"sfx library file missing on disk: {path}") from exc
        return AudioBytes(
            content=content, content_type="audio/mpeg", attribution=candidate.attribution
        )
