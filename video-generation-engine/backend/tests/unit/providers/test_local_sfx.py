"""LocalSfxProvider against a fake library under tmp_path."""

import json

from app.core.config import settings
from app.providers.base import MusicSearchQuery
from app.providers.local_sfx import LocalSfxProvider, _load_manifest


def _write_library(tmp_path, entries: list[dict]) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
    for entry in entries:
        path = tmp_path / entry["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-sfx-" + entry["file"].encode())


def _entry(kind: str, file: str) -> dict:
    return {
        "file": file,
        "title": kind,
        "artist": "x",
        "source": "openverse",
        "source_url": "https://example.test/x",
        "license": "cc0",
        "kind": kind,
        "duration_s": 0.5,
        "tags": kind,
    }


async def test_search_filters_to_the_requested_kind(tmp_path, monkeypatch):
    _write_library(
        tmp_path,
        [
            _entry("whoosh", "whoosh/a.mp3"),
            _entry("stinger", "stinger/b.mp3"),
        ],
    )
    monkeypatch.setattr(settings, "sfx_library_root", tmp_path)
    _load_manifest.cache_clear()
    query = MusicSearchQuery(
        mood="whoosh", tempo="", energy_arc="flat", search_terms=["whoosh"]
    )
    candidates = await LocalSfxProvider().search(query)
    assert [c.source_id for c in candidates] == ["whoosh/a.mp3"]
