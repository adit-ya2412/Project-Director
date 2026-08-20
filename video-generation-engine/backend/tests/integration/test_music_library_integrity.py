"""Verifies the REAL curated music library on disk
(`storage/music_library/`, §11 step 6, 2026-08-18) - not a fake, because
the whole point of this library existing is that every file in it is
real, downloaded, decodable audio at the path its own manifest claims.
No network call, but genuinely exercises `ffprobe` against 54 real
files, so this belongs in integration/, not unit/."""

import subprocess

from app.core.config import settings
from app.providers.local_music import _load_manifest

_EXPECTED_MOODS = frozenset(
    {
        "documentary_dark",
        "documentary_mystery",
        "documentary_ambient",
        "industrial",
        "historical_epic",
        "emotional",
    }
)
_EXPECTED_ENERGIES = frozenset({"ambient", "mid", "driving"})


def _manifest() -> tuple[dict, ...]:
    _load_manifest.cache_clear()
    return _load_manifest(settings.music_library_root)


def test_the_real_manifest_has_all_54_slots_across_every_mood_and_energy():
    entries = _manifest()
    assert len(entries) == 54

    counts: dict[tuple[str, str], int] = {}
    for entry in entries:
        assert entry["mood"] in _EXPECTED_MOODS
        assert entry["energy"] in _EXPECTED_ENERGIES
        key = (entry["mood"], entry["energy"])
        counts[key] = counts.get(key, 0) + 1

    for mood in _EXPECTED_MOODS:
        for energy in _EXPECTED_ENERGIES:
            assert counts.get((mood, energy), 0) == 3, f"{mood}/{energy} should have 3 tracks"


def test_every_manifest_file_exists_and_is_real_decodable_audio():
    entries = _manifest()
    for entry in entries:
        path = settings.music_library_root / entry["file"]
        assert path.is_file(), f"missing file: {path}"

        result = subprocess.run(
            [
                settings.ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 2, f"{path}: unexpected ffprobe output {result.stdout!r}"
        format_name, duration_str = lines
        assert "mp3" in format_name
        # The manifest's own recorded duration was computed the same way at
        # build time - this catches the file having been silently replaced
        # or corrupted since, not just "does ffprobe accept it at all".
        assert abs(float(duration_str) - entry["duration_s"]) < 0.5, path


def test_published_bpm_values_are_positive_integers_or_null():
    """Leftover item 6: BPM is typed in from a published source, never
    guessed. Null remains valid (drones, unpublished Pixabay pages)."""
    for entry in _manifest():
        bpm = entry.get("bpm")
        if bpm is None:
            continue
        assert isinstance(bpm, int) and bpm > 0, entry["file"]


def test_every_manifest_entry_has_a_distinct_file_path():
    """`historical_epic/mid/epic_cinematic.mp3` and
    `emotional/driving/epic_cinematic.mp3` are two separate on-disk COPIES
    of the same source track (it genuinely fits both cells) - so file
    PATHS must still all be unique; a repeated path would mean a
    copy-paste manifest bug, not a deliberate dual-fit."""
    entries = _manifest()
    files = [entry["file"] for entry in entries]
    assert len(files) == len(set(files))
