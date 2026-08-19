"""Narration alignment sidecar (Track C C2 / §3.3).

The mp3 on disk is not enough to rebuild a wiped `narration` row —
alignment lives in JSONB. These helpers are the other half of the
filename. No DB, no provider.
"""

import json

from app.workflow.steps.narration import (
    _ensure_alignment_sidecar,
    _read_alignment_sidecar,
    _write_alignment_sidecar,
)


def _alignment(text: str = "Hi") -> dict:
    return {
        "characters": list(text),
        "character_start_times_seconds": [0.0, 0.1],
        "character_end_times_seconds": [0.1, 0.2],
    }


def test_round_trip_alignment_sidecar(tmp_path):
    mp3 = tmp_path / "abc.mp3"
    mp3.write_bytes(b"audio")
    original = _alignment()
    _write_alignment_sidecar(mp3, original)
    assert _read_alignment_sidecar(mp3) == original


def test_missing_or_empty_sidecar_returns_none(tmp_path):
    mp3 = tmp_path / "abc.mp3"
    mp3.write_bytes(b"audio")
    assert _read_alignment_sidecar(mp3) is None
    sidecar = tmp_path / "abc.alignment.json"
    sidecar.write_text("", encoding="utf-8")
    assert _read_alignment_sidecar(mp3) is None


def test_malformed_sidecar_returns_none(tmp_path):
    mp3 = tmp_path / "abc.mp3"
    mp3.write_bytes(b"audio")
    (tmp_path / "abc.alignment.json").write_text("{not-json", encoding="utf-8")
    assert _read_alignment_sidecar(mp3) is None
    (tmp_path / "abc.alignment.json").write_text(json.dumps({"characters": []}), encoding="utf-8")
    assert _read_alignment_sidecar(mp3) is None


def test_ensure_does_not_overwrite_existing(tmp_path):
    mp3 = tmp_path / "abc.mp3"
    mp3.write_bytes(b"audio")
    _write_alignment_sidecar(mp3, _alignment("Hi"))
    _ensure_alignment_sidecar(mp3, _alignment("No"))
    assert _read_alignment_sidecar(mp3)["characters"] == ["H", "i"]


def test_ensure_is_noop_when_mp3_missing(tmp_path):
    mp3 = tmp_path / "abc.mp3"
    _ensure_alignment_sidecar(mp3, _alignment())
    assert not (tmp_path / "abc.alignment.json").exists()
