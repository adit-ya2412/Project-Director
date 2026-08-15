"""Fake music provider (M8, D6 DRY_RUN path).

Always finds exactly one deterministic, canned track - so DRY_RUN still
exercises `SelectMusicStep`'s real selection logic (search, licence gate,
ranking, recording the choice via `append_version`) end to end, rather
than skipping the feature entirely. The returned "audio" is a literal
fake byte string, not decodable media - same idiom and same reason as
`FakeNarrationProvider`: DRY_RUN's contract is "zero spend, always
produces something runnable", and muxing undecodable bytes would crash
the render rather than degrade gracefully. So `RenderStep` skips the
music-mux pass entirely under DRY_RUN, exactly like it already skips
narration muxing - see that step's own docstring.
"""

from app.providers.base import AudioBytes, MusicSearchQuery, TrackCandidate


class FakeMusicProvider:
    name = "fake_music"

    async def search(self, query: MusicSearchQuery) -> list[TrackCandidate]:
        key = "|".join(query.search_terms) or query.mood or "fake-track"
        return [
            TrackCandidate(
                source_id="fake-track-1",
                source_url=f"fake://music/{key}",
                title=f"fake track for {key}",
                licence="cc0",
                relevance=0.9,
                duration_s=30.0,
                tags=key,
            )
        ]

    async def fetch(self, candidate: TrackCandidate) -> AudioBytes:
        content = f"fake-music-audio:{candidate.source_id}".encode()
        return AudioBytes(content=content, content_type="audio/mpeg", attribution="")
