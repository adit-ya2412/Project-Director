"""CLI for the OQ-0a render metrics report.

Read-only: writes one JSON file (or stdout). No DB, no STORAGE_ROOT, no
render-path side effects.

    python scripts/render_metrics.py --timeline TIMELINE.json [--video VIDEO.mp4]
        [--asset-hashes HASHES.json] [--alignment ALIGN.json]
        [--narration FILE [FILE ...]] [--cues CUES.json]
        [--output OUT.json]

Default --output: <video>.metrics.json next to the video when --video is
set; otherwise <timeline>.metrics.json next to the timeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.renderer.metrics import build_render_metrics_report  # noqa: E402
from app.schemas.timeline import Timeline  # noqa: E402


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def _load_timeline(path: Path) -> Timeline:
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise SystemExit(f"timeline JSON must be an object: {path}")
    # Fixture exports sometimes wrap the document.
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
            "Build a read-only render metrics JSON report from a Timeline "
            "and optional finished video / alignment / cues."
        )
    )
    parser.add_argument("--timeline", required=True, type=Path, help="Timeline JSON")
    parser.add_argument("--video", type=Path, default=None, help="Finished render mp4")
    parser.add_argument(
        "--asset-hashes",
        type=Path,
        default=None,
        help="JSON object {shot_id: identity}",
    )
    parser.add_argument(
        "--alignment",
        type=Path,
        default=None,
        help="JSON list of alignment objects, one per scene in timeline order",
    )
    parser.add_argument(
        "--narration",
        nargs="+",
        type=Path,
        default=None,
        help="Per-scene narration audio files, timeline order",
    )
    parser.add_argument(
        "--cues",
        type=Path,
        default=None,
        help="JSON list of {text, start_s, end_s}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Output JSON path. Default: <video>.metrics.json next to the video; "
            "if no video, <timeline>.metrics.json next to the timeline."
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

    alignment_by_scene = None
    if args.alignment is not None:
        loaded = _load_json(args.alignment)
        if not isinstance(loaded, list):
            raise SystemExit("--alignment must be a JSON list")
        alignment_by_scene = loaded

    caption_cues = None
    if args.cues is not None:
        loaded = _load_json(args.cues)
        if not isinstance(loaded, list):
            raise SystemExit("--cues must be a JSON list")
        caption_cues = loaded

    report = build_render_metrics_report(
        timeline,
        args.video,
        asset_ids=asset_ids,
        scene_narration_paths=args.narration,
        alignment_by_scene=alignment_by_scene,
        caption_cues=caption_cues,
    )

    if args.output is not None:
        out_path = args.output
    elif args.video is not None:
        out_path = args.video.with_name(args.video.stem + ".metrics.json")
    else:
        out_path = args.timeline.with_name(args.timeline.stem + ".metrics.json")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
        fh.write("\n")
    print(f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
