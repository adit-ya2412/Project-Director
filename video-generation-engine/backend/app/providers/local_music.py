"""Local curated music library provider (motion_new_styles_and_long_form_videos.md
§11 step 6, built 2026-08-18) - the real `MusicProvider` §5 of that plan
predicted: "the curated local music library (M4-M10) is adopted but not
built... timing is lucky." This is that library, now built.

## Where the files live, and how they got there

`storage/music_library/` holds 54 real, downloaded, `ffprobe`-verified
audio files organised `<mood>/<energy>/<file>.mp3` - a two-axis taxonomy
(§5.1: content mood x style energy) rather than the mood-only six-category
scheme originally proposed, closing the exact gap that section named
("there is no category a fast-cut video could use"). `manifest.json` in
the same directory is the single source of truth this provider reads -
every field on it (title/artist/source/licence/duration_s) was verified
against the real file, not asserted from a source page alone. `MANIFEST.md`
alongside it is the human-readable rendition of the same data.

## Why every track is returned, licence included

Unlike `OpenverseMusicProvider`, which gates NC/ND out of ITS OWN result
set (that module's own docstring: NoDerivatives conflicts with this
renderer's own bed/duck mixing under narration, which is a derivative by
definition; NonCommercial limits the finished video's use), this provider
does no licence filtering of its own - `search()` returns every candidate
in the library, NC/ND ones included, each carrying its correct `licence`
string. The existing gate in `SelectMusicStep._select`
(`c.licence in plan.licence_requirements`, when that list is non-empty) is
what a project can use to exclude them - left as a per-project decision,
not baked into this provider, per explicit instruction to include the
whole library in the pool. Worth remembering if that default is ever
revisited: the render's own bed/duck mix (`app/renderer/music.py`) creates
a derivative of whatever track is chosen - exactly what a CC BY-NC-ND
licence forbids. The 3 ND tracks in this library (see `MANIFEST.md`) are
not merely a policy risk; using one is a literal licence violation on
every render that selects it, not a theoretical one.

## No network call, ever

Unlike every other `MusicProvider`, `fetch()` reads bytes off local disk -
the whole reason this library was built was to stop depending on a live,
thin, sometimes-empty third-party search (Openverse's own docstring: "a
narrow music_plan legitimately finds nothing on a real search"). A local
file can never 404, rate-limit, or return zero results, so unlike
`OpenverseMusicProvider.search`, there is no per-term query loop here -
the whole library is always the candidate pool, and the actual match to
`query` happens downstream in `app/assets/music_ranking.py`, the same
term-overlap relevance every other provider's results are ranked by.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.errors import PermanentError
from app.providers.base import AudioBytes, MusicSearchQuery, TrackCandidate

_MANIFEST_FILENAME = "manifest.json"


@lru_cache(maxsize=1)
def _load_manifest(library_root: Path) -> tuple[dict, ...]:
    """Cached on `library_root` (not just call-with-no-args) so a test
    pointing `settings.music_library_root` at a fixed tmp_path gets its
    own cache entry rather than colliding with the real library's."""
    manifest_path = library_root / _MANIFEST_FILENAME
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PermanentError(f"music library manifest not found at {manifest_path}") from exc
    return tuple(json.loads(raw))


def _candidate(entry: dict) -> TrackCandidate:
    tag_words = f"{entry['mood']} {entry['energy']} {entry['tags']}"
    attribution = f'"{entry["title"]}" by {entry["artist"]} ({entry["source"]}, {entry["license"]})'
    return TrackCandidate(
        source_id=entry["file"],
        source_url=entry["source_url"],
        title=entry["title"],
        licence=entry["license"],
        author=entry["artist"],
        duration_s=entry["duration_s"],
        bpm=entry.get("bpm"),
        tags=tag_words,
        attribution=attribution,
    )


class LocalMusicProvider:
    name = "local"

    async def search(self, query: MusicSearchQuery) -> list[TrackCandidate]:
        return [_candidate(entry) for entry in _load_manifest(settings.music_library_root)]

    async def fetch(self, candidate: TrackCandidate) -> AudioBytes:
        path = settings.music_library_root / candidate.source_id
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise PermanentError(f"music library file missing on disk: {path}") from exc
        return AudioBytes(
            content=content, content_type="audio/mpeg", attribution=candidate.attribution
        )
