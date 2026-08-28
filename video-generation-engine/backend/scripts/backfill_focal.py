"""Write OQ-2 focal sidecars for already-bound still assets (RV-Q4).

    python scripts/backfill_focal.py <project_id>          # preview
    python scripts/backfill_focal.py <project_id> --apply  # vision + write

Sidecars are only created at bind time in ResolveAssetsStep. The
58f0a5e6 fixture (and every project resolved before OQ-2) has none, so
`resolve_shot_focals` returns None and Ken Burns stays centre-aimed.
This script re-runs the depiction vision question over those stills,
keyed by content hash, AFTER the RV-Q1 crop-space fix — do not backfill
focals that would be consumed in original-image space.

Preview lists missing sidecars and does not call the model. --apply
costs one vision call per missing still.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.assets.focal import (  # noqa: E402
    DEFAULT_FOCAL,
    persist_vision_focal,
    read_focal_sidecar,
    write_focal_sidecar,
)
from app.assets.focal_check import locate_subject_focal  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.providers.openai_provider import OpenAIPlanningProvider  # noqa: E402
from app.repositories.llm_call_repository import LlmCallRepository  # noqa: E402
from app.schemas.timeline import Timeline  # noqa: E402


async def _rows(project_id: str) -> tuple[Timeline, Path, list[dict]]:
    async with async_session_factory() as session:
        timeline_row = (
            await session.execute(
                text(
                    "SELECT document FROM timeline_version WHERE project_id = CAST(:pid AS uuid) "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"pid": project_id},
            )
        ).fetchone()
        if timeline_row is None:
            raise SystemExit(f"no timeline for project {project_id}")
        timeline = Timeline.model_validate(timeline_row[0])

        assets = (
            await session.execute(
                text(
                    "SELECT a.content_hash, a.local_path, a.type, sb.shot_id "
                    "FROM shot_binding sb "
                    "JOIN asset a ON a.id = sb.asset_id "
                    "WHERE sb.project_id = CAST(:pid AS uuid) "
                    "AND sb.timeline_version = :ver "
                    "AND sb.asset_id IS NOT NULL"
                ),
                {"pid": project_id, "ver": timeline.version},
            )
        ).fetchall()
    assets_dir = settings.storage_root / project_id / "assets"
    rows = [
        {
            "content_hash": r[0],
            "local_path": r[1],
            "type": r[2],
            "shot_id": r[3],
        }
        for r in assets
    ]
    return timeline, assets_dir, rows


def _shot_by_id(timeline: Timeline) -> dict:
    return {shot.id: shot for shot in timeline.all_shots()}



async def _locate_with_retry(
    *,
    llm_call_repo,
    provider,
    project_id,
    content: bytes,
    mime: str,
    shot_id: str,
    attempts: int = 5,
):
    """`locate_subject_focal` with exponential backoff.

    The first real run of this script died at 12 of 34 assets on an
    OpenAI 429 (tokens-per-minute), with no retry - so a backfill of any
    real project could not complete unattended. `locate_subject_focal`
    swallows provider errors into `None`, which is right for the render
    path (never fail a run over a camera hint) and wrong here, where a
    rate limit is worth waiting out rather than permanently recording a
    fallback sidecar. So: retry on `None`, with a ceiling, then give up
    and let the caller write an honest miss.
    """
    delay = 2.0
    for attempt in range(1, attempts + 1):
        focal = await locate_subject_focal(
            provider=provider,
            llm_call_repo=llm_call_repo,
            project_id=project_id,
            image=content,
            image_content_type=mime,
            shot_id=shot_id,
        )
        if focal is not None:
            return focal
        if attempt < attempts:
            print(f"      retry {attempt}/{attempts - 1} in {delay:.0f}s ({shot_id})")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
    return None


async def main(project_id: str, *, apply: bool) -> int:
    timeline, assets_dir, rows = await _rows(project_id)
    shots = _shot_by_id(timeline)
    seen: set[str] = set()
    missing: list[dict] = []
    for row in rows:
        if row["type"] != "image":
            continue
        h = row["content_hash"]
        if h in seen:
            continue
        seen.add(h)
        if read_focal_sidecar(assets_dir, h) is not None:
            continue
        missing.append(row)

    print(f"{len(seen)} distinct stills, {len(missing)} missing a focal sidecar")
    for row in missing:
        print(f"  {row['shot_id']}  {row['content_hash'][:12]}…")
    if not apply or not missing:
        return 0

    provider = OpenAIPlanningProvider()
    async with async_session_factory() as session:
        llm_call_repo = LlmCallRepository(session)
        for row in missing:
            shot = shots.get(row["shot_id"])
            path = Path(row["local_path"]) if row["local_path"] else None
            if shot is None or path is None or not path.is_file():
                print(f"skip {row['shot_id']}: no file or shot")
                continue
            # No search terms are passed any more: the focal call asks
            # about the PIXELS only, deliberately (SubjectFocalRequest).
            content = path.read_bytes()
            suffix = path.suffix.lower().lstrip(".") or "jpg"
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(
                suffix, "image/jpeg"
            )
            focal = await _locate_with_retry(
                llm_call_repo=llm_call_repo,
                provider=provider,
                project_id=uuid.UUID(str(timeline.project_id)),
                content=content,
                mime=mime,
                shot_id=row["shot_id"],
            )
            if focal is None:
                # Record the miss rather than inventing a centre that
                # later reads as a real answer (the exact bug this
                # backfill's first run shipped).
                write_focal_sidecar(
                    assets_dir,
                    row["content_hash"],
                    focal_x=DEFAULT_FOCAL[0],
                    focal_y=DEFAULT_FOCAL[1],
                    source="fallback",
                )
                print(f"MISS  {row['content_hash'][:12]}... no usable focal; wrote fallback")
            else:
                persist_vision_focal(
                    assets_dir,
                    row["content_hash"],
                    focal_x=focal[0],
                    focal_y=focal[1],
                    shot_id=row["shot_id"],
                )
                print(f"wrote {row['content_hash'][:12]}... focal=({focal[0]:.3f},{focal[1]:.3f})")
        await session.commit()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.project_id, apply=args.apply)))
