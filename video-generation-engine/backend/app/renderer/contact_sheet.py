"""Read-only per-render contact sheet (OQ-0b).

One HTML page + sibling JPEG folder: one midpoint thumbnail per shot,
annotated for review. Must not be imported from the render path, must not
write the DB, and must not mutate the Timeline.
"""

from __future__ import annotations

import html
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.timeline import Shot, Timeline, TransitionType
from app.timeline.duration import compute_shot_start_times

logger = get_logger(__name__)

_NARRATION_EXCERPT_CHARS = 80
_THUMB_JPEG_Q = "3"


def _aspect_css(timeline: Timeline) -> str:
    """CSS aspect-ratio from Timeline metadata (`9:16` → `9 / 16`)."""
    raw = timeline.metadata.aspect_ratio or "9:16"
    if ":" in raw:
        w, _, h = raw.partition(":")
        return f"{w.strip()} / {h.strip()}"
    return "9 / 16"


def _shot_midpoints(timeline: Timeline) -> dict[str, float]:
    """Midpoint of each shot on the rendered clock (D5 overlap-aware).

    ``start + duration_s / 2`` where ``start`` comes from
    ``compute_shot_start_times`` — never a naive cumulative sum of
    ``duration_s``.
    """
    shots = timeline.all_shots()
    starts = compute_shot_start_times(shots)
    return {shot.id: starts[shot.id] + float(shot.duration_s) / 2.0 for shot in shots}


def _duration_gte_shot_ids(shots: list[Shot]) -> set[str]:
    """Same hazard rule as OQ-0a ``duration_gte_shot`` (outgoing or incoming)."""
    flagged: set[str] = set()
    for index, shot in enumerate(shots):
        tr = shot.transition_out
        if tr.type == TransitionType.CUT or tr.duration_s <= 0.0:
            continue
        next_shot = shots[index + 1] if index + 1 < len(shots) else None
        compared = shot
        if next_shot is not None and next_shot.duration_s < shot.duration_s:
            compared = next_shot
        if tr.duration_s >= compared.duration_s:
            flagged.add(shot.id)
    return flagged


def _scene_for_shot(timeline: Timeline) -> dict[str, Any]:
    """Map shot_id → owning Scene (for narration_text)."""
    out: dict[str, Any] = {}
    for scene in timeline.scenes:
        for shot in scene.shots:
            out[shot.id] = scene
    return out


def _narration_excerpt(scene: Any, shot: Shot) -> str:
    text = getattr(scene, "narration_text", "") or ""
    span = shot.narration_span
    if span is not None:
        start, end = int(span[0]), int(span[1])
        start = max(0, min(start, len(text)))
        end = max(start, min(end, len(text)))
        text = text[start:end]
    text = " ".join(text.split())
    if len(text) <= _NARRATION_EXCERPT_CHARS:
        return text
    return text[: _NARRATION_EXCERPT_CHARS - 1].rstrip() + "…"


def _reuse_info(
    shots: list[Shot],
    asset_ids: Mapping[str, str] | None,
) -> dict[str, dict[str, Any]]:
    """Per shot: identity + whether that identity appeared on an earlier shot."""
    if asset_ids is None:
        return {}
    seen: dict[str, str] = {}
    out: dict[str, dict[str, Any]] = {}
    for shot in shots:
        identity = asset_ids.get(shot.id)
        if identity is None:
            out[shot.id] = {"identity": None, "reused": False}
            continue
        reused = identity in seen
        out[shot.id] = {"identity": identity, "reused": reused}
        if identity not in seen:
            seen[identity] = shot.id
    return out


def _extract_frame(
    video_path: Path,
    timestamp_s: float,
    dest: Path,
    *,
    ffmpeg_binary: str,
) -> bool:
    # Input seek (-ss before -i): decode only up to the target frame.
    # Per-shot call keeps Windows command-line limits out of the picture.
    args = [
        ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, timestamp_s):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        _THUMB_JPEG_Q,
        "-update",
        "1",
        str(dest),
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not dest.is_file():
        err = (result.stderr or "").strip() or f"ffmpeg exit {result.returncode}"
        logger.warning("contact_sheet.frame_extract_failed t=%s dest=%s err=%s", timestamp_s, dest, err)
        return False
    return True


def _thumbs_dir_for_html(output_html: Path) -> Path:
    # final.contact.html → final.contact/
    stem = output_html.name
    if stem.endswith(".contact.html"):
        folder_name = stem[: -len(".html")]
    else:
        folder_name = output_html.stem + ".contact"
    return output_html.parent / folder_name


def _render_html(
    *,
    timeline: Timeline,
    shots: list[Shot],
    midpoints: dict[str, float],
    flagged: set[str],
    reuse: dict[str, dict[str, Any]],
    thumb_rel: dict[str, str],
    video_path: Path,
    aspect_css: str,
) -> str:
    scene_by_shot = _scene_for_shot(timeline)
    cells: list[str] = []
    for shot in shots:
        cam = shot.camera
        tr = shot.transition_out
        flag_cls = " cell-flagged" if shot.id in flagged else ""
        narr = _narration_excerpt(scene_by_shot[shot.id], shot)
        reuse_row = reuse.get(shot.id)
        if reuse_row is None:
            asset_line = ""
        else:
            ident = reuse_row["identity"]
            if ident is None:
                asset_line = '<div class="meta">asset: —</div>'
            else:
                reused_lbl = "yes" if reuse_row["reused"] else "no"
                short = ident if len(ident) <= 24 else ident[:21] + "…"
                asset_line = (
                    f'<div class="meta">asset: {html.escape(short)} (reused: {reused_lbl})</div>'
                )
        img_rel = thumb_rel.get(shot.id, "")
        img_html = (
            f'<img src="{html.escape(img_rel)}" alt="{html.escape(shot.id)}" />'
            if img_rel
            else '<div class="missing">no frame</div>'
        )
        cells.append(
            f'<article class="cell{flag_cls}" id="{html.escape(shot.id)}">'
            f"{img_html}"
            f'<div class="id">{html.escape(shot.id)}</div>'
            f'<div class="meta">t={midpoints[shot.id]:.2f}s · '
            f"{shot.duration_s:.2f}s</div>"
            f'<div class="meta">{html.escape(cam.movement.value)} / '
            f"{html.escape(cam.direction.value)} / "
            f"{cam.intensity:.2f}</div>"
            f'<div class="meta">out: {html.escape(tr.type.value)} '
            f"{tr.duration_s:.2f}s</div>"
            f"{asset_line}"
            f'<div class="narr">{html.escape(narr) if narr else "—"}</div>'
            "</article>"
        )

    title = f"Contact sheet — {timeline.timeline_id} v{timeline.version} ({len(shots)} shots)"
    body = "\n".join(cells)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
:root {{ font-family: system-ui, sans-serif; color: #1a1a1a; background: #f4f4f4; }}
body {{ margin: 0; padding: 1rem 1.25rem 3rem; }}
header {{ margin-bottom: 1rem; }}
header h1 {{ font-size: 1.15rem; margin: 0 0 0.35rem; }}
header p {{ margin: 0; color: #555; font-size: 0.9rem; }}
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem;
}}
.cell {{
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 6px;
  padding: 0.5rem;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}}
.cell-flagged {{
  border-color: #c0392b;
  box-shadow: 0 0 0 2px rgba(192,57,43,0.35);
  background: #fff8f7;
}}
.cell img {{
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: {aspect_css};
  object-fit: cover;
  background: #222;
  border-radius: 3px;
}}
.cell .missing {{
  aspect-ratio: {aspect_css};
  background: #333;
  color: #aaa;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  border-radius: 3px;
}}
.cell .id {{ font-weight: 650; margin-top: 0.4rem; font-size: 0.95rem; }}
.cell .meta {{ font-size: 0.75rem; color: #444; margin-top: 0.15rem; }}
.cell .narr {{
  font-size: 0.75rem;
  color: #222;
  margin-top: 0.35rem;
  line-height: 1.3;
  min-height: 2.4em;
}}
.legend {{ font-size: 0.8rem; color: #666; margin-top: 0.5rem; }}
.legend .swatch {{
  display: inline-block;
  width: 0.85em;
  height: 0.85em;
  border: 2px solid #c0392b;
  background: #fff8f7;
  vertical-align: -0.1em;
  margin-right: 0.25em;
}}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p>video: {html.escape(str(video_path))} · midpoints on rendered clock (D5)</p>
  <p class="legend"><span class="swatch"></span>
    flagged: transition_out.duration_s ≥ compared shot duration (OQ-0a rule)</p>
</header>
<div class="grid">
{body}
</div>
</body>
</html>
"""


def build_contact_sheet(
    timeline: Timeline,
    video_path: Path,
    output_html: Path,
    *,
    asset_ids: Mapping[str, str] | None = None,
    ffmpeg_binary: str | None = None,
) -> Path:
    """Write ``output_html`` and a sibling JPEG folder; return the HTML path.

    Frames are extracted at each shot's rendered midpoint. Thumbnails live
    beside the HTML (e.g. ``final.contact/`` next to ``final.contact.html``)
    so a large project does not embed megabytes of base64.
    """
    ffmpeg = ffmpeg_binary or settings.ffmpeg_binary
    video_path = Path(video_path)
    output_html = Path(output_html)
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")

    shots = timeline.all_shots()
    midpoints = _shot_midpoints(timeline)
    flagged = _duration_gte_shot_ids(shots)
    reuse = _reuse_info(shots, asset_ids)

    thumbs_dir = _thumbs_dir_for_html(output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    thumb_rel: dict[str, str] = {}
    for shot in shots:
        dest = thumbs_dir / f"{shot.id}.jpg"
        ok = _extract_frame(
            video_path,
            midpoints[shot.id],
            dest,
            ffmpeg_binary=ffmpeg,
        )
        if ok:
            thumb_rel[shot.id] = f"{thumbs_dir.name}/{shot.id}.jpg"

    html_text = _render_html(
        timeline=timeline,
        shots=shots,
        midpoints=midpoints,
        flagged=flagged,
        reuse=reuse,
        thumb_rel=thumb_rel,
        video_path=video_path,
        aspect_css=_aspect_css(timeline),
    )
    output_html.write_text(html_text, encoding="utf-8")
    logger.info(
        "contact_sheet.wrote",
        extra={
            "html": str(output_html),
            "shots": len(shots),
            "flagged": len(flagged),
            "thumbs_dir": str(thumbs_dir),
        },
    )
    return output_html
