"""Write only published BPM values into storage/music_library/manifest.json."""

from __future__ import annotations

import json
from pathlib import Path

_MANIFEST = Path(__file__).resolve().parents[1] / "storage" / "music_library" / "manifest.json"

# Incompetech page Tempo, ID3 TBP/TBPM, or the artist's own page.
# Nothing here is guessed or beat-detected.
_UPDATES = {
    "documentary_dark/ambient/dark_times.mp3": 48,
    "documentary_dark/mid/darkness_is_coming.mp3": 73,
    "documentary_dark/driving/epic_sci_fi_war_intense_trailer_tragedy.mp3": 130,
    "documentary_mystery/mid/spy_glass.mp3": 110,
    "documentary_mystery/mid/deadly_roulette.mp3": 104,
    "industrial/mid/industrial_music_box.mp3": 139,
    "historical_epic/mid/epic_cinematic.mp3": 175,
    "emotional/driving/epic_cinematic.mp3": 175,
    "emotional/driving/empires.mp3": 130,
}


def main() -> None:
    entries = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for entry in entries:
        if entry["file"] in _UPDATES:
            entry["bpm"] = _UPDATES[entry["file"]]
    _MANIFEST.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    filled = [e for e in entries if e.get("bpm")]
    print("with_bpm", len(filled), "still_null", len(entries) - len(filled))
    for entry in filled:
        print(f"  {entry['bpm']:>3}  {entry['file']}")


if __name__ == "__main__":
    main()
