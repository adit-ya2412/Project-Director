"""`LocalMusicProvider` tests against a small fake manifest/library under
`tmp_path` - never the real 411MB library (that's `test_music_library
_integrity.py`'s job, in integration/, against the real files)."""

import json

import pytest

from app.core.config import settings
from app.core.errors import PermanentError
from app.providers.base import MusicSearchQuery
from app.providers.local_music import LocalMusicProvider, _load_manifest

_QUERY = MusicSearchQuery(
    mood="sombre", tempo="slow", energy_arc="flat", search_terms=["documentary"]
)


def _write_fake_library(tmp_path, entries: list[dict]) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
    for entry in entries:
        file_path = tmp_path / entry["file"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"fake-audio-bytes-" + entry["file"].encode())


def _entry(file: str = "documentary_dark/ambient/track.mp3", **overrides) -> dict:
    base = {
        "file": file,
        "title": "A Track",
        "artist": "Some Artist",
        "source": "pixabay",
        "source_url": "https://pixabay.com/music/a-track-1/",
        "license": "pixabay_content_license",
        "mood": "documentary_dark",
        "energy": "ambient",
        "bpm": None,
        "duration_s": 120.5,
        "tags": "dark ambient documentary",
    }
    base.update(overrides)
    return base


async def test_search_returns_every_track_in_the_manifest(tmp_path, monkeypatch):
    _write_fake_library(tmp_path, [_entry(), _entry(file="industrial/mid/other.mp3")])
    monkeypatch.setattr(settings, "music_library_root", tmp_path)
    _load_manifest.cache_clear()

    candidates = await LocalMusicProvider().search(_QUERY)

    assert {c.source_id for c in candidates} == {
        "documentary_dark/ambient/track.mp3",
        "industrial/mid/other.mp3",
    }


async def test_search_maps_manifest_fields_onto_the_candidate(tmp_path, monkeypatch):
    _write_fake_library(tmp_path, [_entry(bpm=90)])
    monkeypatch.setattr(settings, "music_library_root", tmp_path)
    _load_manifest.cache_clear()

    candidates = await LocalMusicProvider().search(_QUERY)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "A Track"
    assert candidate.author == "Some Artist"
    assert candidate.licence == "pixabay_content_license"
    assert candidate.duration_s == 120.5
    assert candidate.bpm == 90
    assert "documentary_dark" in candidate.tags
    assert "ambient" in candidate.tags
    assert "documentary" in candidate.tags  # the entry's own free-text tags
    assert candidate.attribution == '"A Track" by Some Artist (pixabay, pixabay_content_license)'


async def test_search_includes_restricted_licence_tracks_without_filtering(tmp_path, monkeypatch):
    """This provider does no licence gating of its own - unlike
    `OpenverseMusicProvider`, which excludes NC/ND from its own result
    set (see that module's docstring). Filtering is `SelectMusicStep`'s
    job, via `plan.licence_requirements` - the provider's job is only to
    report what's really in the library, licence included."""
    _write_fake_library(tmp_path, [_entry(license="cc-by-nc-nd-4.0")])
    monkeypatch.setattr(settings, "music_library_root", tmp_path)
    _load_manifest.cache_clear()

    candidates = await LocalMusicProvider().search(_QUERY)

    assert candidates[0].licence == "cc-by-nc-nd-4.0"


async def test_fetch_reads_real_bytes_off_disk(tmp_path, monkeypatch):
    _write_fake_library(tmp_path, [_entry()])
    monkeypatch.setattr(settings, "music_library_root", tmp_path)
    _load_manifest.cache_clear()

    candidates = await LocalMusicProvider().search(_QUERY)
    result = await LocalMusicProvider().fetch(candidates[0])

    assert result.content == b"fake-audio-bytes-documentary_dark/ambient/track.mp3"
    assert result.content_type == "audio/mpeg"
    assert result.attribution == candidates[0].attribution


async def test_search_raises_a_permanent_error_when_the_manifest_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "music_library_root", tmp_path)  # empty dir, no manifest.json
    _load_manifest.cache_clear()

    with pytest.raises(PermanentError):
        await LocalMusicProvider().search(_QUERY)


async def test_fetch_raises_a_permanent_error_when_the_file_is_missing(tmp_path, monkeypatch):
    entries = [_entry()]
    (tmp_path / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
    # Deliberately never write the actual audio file.
    monkeypatch.setattr(settings, "music_library_root", tmp_path)
    _load_manifest.cache_clear()

    candidates = await LocalMusicProvider().search(_QUERY)
    with pytest.raises(PermanentError):
        await LocalMusicProvider().fetch(candidates[0])
