"""CLI for the OQ-0b contact sheet.

Read-only: writes one HTML file + sibling JPEG folder. No DB, no
STORAGE_ROOT, no render-path side effects.

    python scripts/render_contact_sheet.py --timeline TIMELINE.json --video VIDEO.mp4
        [--asset-hashes HASHES.json] [--output OUT.contact.html]

Default --output: <video>.contact.html next to the video (thumbnails in
<video>.contact/).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.renderer.contact_sheet import build_contact_sheet  # noqa: E402
from app.schemas.timeline import Timeline  # noqa: E402


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def _load_timeline(path: Path) -> Timeline:
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise SystemExit(f"timeline JSON must be an object: {path}")
    if "timeline_document" in raw and "timeline_id" not in raw:
        inner = raw["timeline_document"]
        if not isinstance(inner, dict):
            raise SystemExit(f"timeline_document must be an object: {path}")
        raw = inner
    try:
        return Timeline.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — surface validation clearly
        raise SystemExit(f"timeline validation failed for {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a read-only contact-sheet HTML page (midpoint thumbnails "
            "per shot) from a Timeline and finished video."
        )
    )
    parser.add_argument("--timeline", required=True, type=Path, help="Timeline JSON")
    parser.add_argument("--video", required=True, type=Path, help="Finished render mp4")
    parser.add_argument(
        "--asset-hashes",
        type=Path,
        default=None,
        help="JSON object {shot_id: identity}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Output HTML path. Default: <video>.contact.html next to the video "
            "(thumbnails in <video>.contact/)."
        ),
    )
    args = parser.parse_args(argv)

    timeline = _load_timeline(args.timeline)

    asset_ids = None
    if args.asset_hashes is not None:
        loaded = _load_json(args.asset_hashes)
        if not isinstance(loaded, dict):
            raise SystemExit("--asset-hashes must be a JSON object")
        asset_ids = {str(k): str(v) for k, v in loaded.items()}

    if args.output is not None:
        out_path = args.output
    else:
        out_path = args.video.with_name(args.video.stem + ".contact.html")

    written = build_contact_sheet(
        timeline,
        args.video,
        out_path,
        asset_ids=asset_ids,
    )
    print(f"wrote {written}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
