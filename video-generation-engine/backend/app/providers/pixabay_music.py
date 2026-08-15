"""Pixabay Music provider (M8, D6/21.1 - ladder-adjacent, the single audio
track).

## A verified, documented limitation - not a silent workaround

D6/21.1 in the implementation guide describes Pixabay Music as "free,
permissive, a real public API." That is true of Pixabay's IMAGE and
VIDEO search endpoints - it is NOT true of Music. Verified directly,
2026-08-15, not assumed:

- `GET https://pixabay.com/api/?key=...&q=piano` (images) and
  `GET https://pixabay.com/api/videos/?key=...&q=piano` (videos) both
  succeed with the real key already configured in this project's `.env`.
- `GET https://pixabay.com/api/music/?key=...` and
  `GET https://pixabay.com/api/audio/?key=...` return 404 and 403
  respectively - there is no music/audio search endpoint in that same
  key-based REST family.
- Pixabay's own API documentation (`https://pixabay.com/api/docs/`)
  lists exactly two endpoints: Images and Videos. Music/sound effects
  are a separate product on the Pixabay website with no published REST
  API at all - the same gap the design doc already correctly identified
  for Epidemic Sound (partner-gated) and Artlist (no public API), just
  not noticed for Pixabay itself.

Per the standing instruction to say so rather than silently work around
a wrong design decision: this is flagged here, in
`docs/13_Implementation_Guide.md`'s M8 step 4 implementation notes, and
in the step-4 report. It is NOT fixed by guessing at an undocumented
endpoint or scraping the website - both are fragile and likely against
Pixabay's terms.

## Why this class still exists, and what it actually does

`MUSIC_PROVIDER=pixabay` stays the configured default (changing it is a
separate decision this step does not make silently). This class is real,
`MusicProvider`-conformant scaffolding, ready to point at a working
endpoint the moment one exists (Pixabay adds one, or `MUSIC_PROVIDER`
switches to a provider that has one) - but `search` raises `PermanentError`
naming exactly this gap rather than pretending to call something that
was verified not to exist. That failure is NOT fatal to a real run:
`SelectMusicStep` catches it the same way it catches "the provider found
nothing" (A22's own precedent - a total provider failure must not block
anything), records `selection_attempted=True, selected_track=None`, and
the project renders silent-but-narrated, exactly the required behaviour
for "no suitable track" per this step's own scope.
"""

from app.core.errors import PermanentError
from app.providers.base import AudioBytes, MusicSearchQuery, TrackCandidate

_NO_PUBLIC_API_MESSAGE = (
    "Pixabay has no public Music/Audio search API (verified live 2026-08-15: "
    "https://pixabay.com/api/music/ -> 404, https://pixabay.com/api/audio/ -> 403; "
    "https://pixabay.com/api/docs/ documents only Images and Videos). This is a "
    "known, documented gap in the design decision, not a bug in this provider - "
    "see this module's own docstring."
)


class PixabayMusicProvider:
    name = "pixabay_music"

    async def search(self, query: MusicSearchQuery) -> list[TrackCandidate]:
        raise PermanentError(_NO_PUBLIC_API_MESSAGE)

    async def fetch(self, candidate: TrackCandidate) -> AudioBytes:
        raise PermanentError(_NO_PUBLIC_API_MESSAGE)
