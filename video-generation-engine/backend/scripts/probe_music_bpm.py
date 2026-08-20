"""Dump ffprobe format tags that might carry a published BPM."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.providers.local_music import _load_manifest  # noqa: E402


def main() -> None:
    root = settings.music_library_root
    entries = _load_manifest(root)
    print("library", root)
    print("count", len(entries), "with_bpm", sum(1 for e in entries if e.get("bpm")))
    for entry in entries:
        path = root / entry["file"]
        result = subprocess.run(
            [
                settings.ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "format_tags",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        try:
            tags = json.loads(result.stdout).get("format", {}).get("tags", {}) or {}
        except json.JSONDecodeError:
            tags = {"_raw": result.stdout[:200]}
        interesting = {
            key: value
            for key, value in tags.items()
            if any(token in key.lower() for token in ("bpm", "tempo", "tbp", "comment", "title"))
        }
        print(
            f"{str(entry.get('bpm')):>5} | {entry['source']:12} | "
            f"{entry['title'][:48]:48} | {interesting}"
        )


if __name__ == "__main__":
    main()
