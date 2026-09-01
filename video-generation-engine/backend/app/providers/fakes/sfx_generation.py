"""Fake diegetic-SFX generation provider (long_form_direction.md A8,
DRY_RUN path).

Same idiom as `FakeMusicProvider`/`FakeNarrationProvider`: deterministic
from the request text (I5 applies to fakes too), and the returned "audio"
is a literal fake byte string, not decodable media - `GenerateDiegeticSfxStep`
skips ffprobe/peak-measurement under DRY_RUN for the identical reason
`SelectSfxStep`/`SelectMusicStep` already do, so nothing here needs to be
real audio.
"""

from app.providers.base import SoundEffectRequest, SoundEffectResult


class FakeSoundEffectProvider:
    name = "fake_sfx_generation"

    async def generate(self, request: SoundEffectRequest) -> SoundEffectResult:
        content = f"fake-sfx-audio:{request.text}:{request.duration_seconds}".encode()
        return SoundEffectResult(content=content, content_type="audio/mpeg")
