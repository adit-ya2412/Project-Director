"""The real SFX library on disk — every manifest file exists and decodes."""

import subprocess

from app.assets.sfx_ranking import rank_sfx_candidates
from app.core.config import settings
from app.providers.local_sfx import _candidate, _load_manifest

_KINDS = frozenset({"whoosh", "stinger", "transition"})


def _entries() -> tuple[dict, ...]:
    _load_manifest.cache_clear()
    return _load_manifest(settings.sfx_library_root)


def test_real_sfx_library_has_three_kinds_and_decodable_files():
    entries = _entries()
    assert len(entries) >= 10
    kinds = {entry["kind"] for entry in entries}
    assert kinds == _KINDS
    for entry in entries:
        path = settings.sfx_library_root / entry["file"]
        assert path.is_file(), path
        result = subprocess.run(
            [
                settings.ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = float(result.stdout.strip())
        assert abs(duration - entry["duration_s"]) < 0.5, path
        assert 0.05 <= duration <= 4.5


def test_at_least_one_stinger_fits_the_mix_intact():
    """R15 residual: the library, not just the ranker, can satisfy the mix."""
    stingers = [entry for entry in _entries() if entry["kind"] == "stinger"]
    assert any(entry["duration_s"] <= settings.sfx_max_clip_s for entry in stingers)


def test_ranking_picks_an_intact_stinger_from_the_real_library():
    stingers = [_candidate(entry) for entry in _entries() if entry["kind"] == "stinger"]
    ranked = rank_sfx_candidates(
        stingers, query_terms=["stinger", "cinematic impact"]
    )
    assert ranked
    assert ranked[0].duration_s is not None
    assert ranked[0].duration_s <= settings.sfx_max_clip_s
