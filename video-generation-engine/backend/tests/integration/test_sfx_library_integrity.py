"""The real SFX library on disk — every manifest file exists and decodes."""

import subprocess

from app.core.config import settings
from app.providers.local_sfx import _load_manifest

_KINDS = frozenset({"whoosh", "stinger", "transition"})


def test_real_sfx_library_has_three_kinds_and_decodable_files():
    _load_manifest.cache_clear()
    entries = _load_manifest(settings.sfx_library_root)
    assert len(entries) >= 6
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
