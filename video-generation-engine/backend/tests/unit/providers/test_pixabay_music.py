"""`PixabayMusicProvider` (M8, D6/21.1) - proves it stays honest about
being non-functional. Verified live 2026-08-15 that Pixabay has no
public Music/Audio search API at all (only Images and Videos) - see the
provider's own module docstring for the exact endpoints checked. This
class exists as real, protocol-conformant scaffolding for if that ever
changes, not as a working provider today."""

import pytest

from app.core.errors import PermanentError
from app.providers.base import MusicSearchQuery, TrackCandidate
from app.providers.pixabay_music import PixabayMusicProvider

_QUERY = MusicSearchQuery(mood="sombre", tempo="slow", energy_arc="flat", search_terms=["ambient"])


async def test_search_raises_naming_the_documented_gap():
    provider = PixabayMusicProvider()
    with pytest.raises(PermanentError, match="no public Music/Audio search API"):
        await provider.search(_QUERY)


async def test_fetch_raises_naming_the_documented_gap():
    provider = PixabayMusicProvider()
    candidate = TrackCandidate(
        source_id="x", source_url="https://pixabay.com/x", title="x", licence="cc0"
    )
    with pytest.raises(PermanentError, match="no public Music/Audio search API"):
        await provider.fetch(candidate)
