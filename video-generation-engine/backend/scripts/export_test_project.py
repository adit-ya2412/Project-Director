"""Snapshot a project's planned state into a committed fixture, so it can
be restored later with `seed_test_project.py` and never re-planned.

    python scripts/export_test_project.py <project_id> <fixture_name>

e.g.  python scripts/export_test_project.py 35290b04-... hindi_test_project

Planning is the expensive, non-deterministic part of this pipeline: a
5-scene script costs ~11 real OpenAI calls through the Director -> Scene
-> Shot -> Asset chain, and produces creative output that is never
reproducible verbatim. Once a run produces a timeline worth keeping,
snapshot it here rather than re-buying it every time the shared dev
database gets truncated by the test suite (see `seed_test_project.py`'s
docstring for why that happens routinely).

Exports the active timeline plus, if the project has progressed that far,
its `asset` rows (with full provenance, so the bytes can be re-fetched)
and `shot_binding` rows. A project snapshotted before approval simply has
neither, which is fine - it restores to exactly the state it was in.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
os.chdir(_BACKEND.parent)  # STORAGE_ROOT is relative - see seed_test_project.py

from app.db.session import async_session_factory  # noqa: E402

FIXTURE_DIR = _BACKEND / "tests" / "fixtures"


async def main(project_id: str, fixture_name: str) -> None:
    async with async_session_factory() as session:
        project = (
            await session.execute(
                text("SELECT name FROM project WHERE id = :pid"), {"pid": project_id}
            )
        ).fetchone()
        if project is None:
            raise SystemExit(f"project {project_id} not found")

        script = (
            await session.execute(
                text(
                    "SELECT content, language FROM script WHERE project_id = :pid "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"pid": project_id},
            )
        ).fetchone()
        if script is None:
            raise SystemExit(f"project {project_id} has no script to export")

        timeline = (
            await session.execute(
                text(
                    "SELECT version, document FROM timeline_version WHERE project_id = :pid "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"pid": project_id},
            )
        ).fetchone()
        if timeline is None:
            raise SystemExit(f"project {project_id} has no timeline to export")

        assets = (
            await session.execute(
                text(
                    "SELECT id, provider, source_url, type, local_path, licence, attribution, "
                    "content_hash, confidence FROM asset WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).fetchall()
        bindings = (
            await session.execute(
                text(
                    "SELECT shot_id, state, rung, asset_id, timeline_version FROM shot_binding "
                    "WHERE project_id = :pid ORDER BY shot_id"
                ),
                {"pid": project_id},
            )
        ).fetchall()

    hash_by_asset_id = {str(a.id): a.content_hash for a in assets}
    fixture = {
        "project_id": project_id,
        "name": project.name,
        "script": script.content,
        "language": script.language,
        "timeline_version": timeline.version,
        "timeline_document": timeline.document,
        "assets": [
            {
                "provider": a.provider,
                "source_url": a.source_url,
                "type": a.type,
                "licence": a.licence,
                "attribution": a.attribution,
                "content_hash": a.content_hash,
                "confidence": a.confidence,
                "filename": a.local_path.replace("\\", "/").rsplit("/", 1)[-1],
            }
            for a in assets
        ],
        "bindings": [
            {
                "shot_id": b.shot_id,
                "state": b.state,
                "rung": b.rung,
                "timeline_version": b.timeline_version,
                "asset_content_hash": hash_by_asset_id.get(str(b.asset_id)) if b.asset_id else None,
            }
            for b in bindings
        ],
    }

    out = FIXTURE_DIR / f"{fixture_name}.json"
    out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    scenes = fixture["timeline_document"].get("scenes", [])
    shots = sum(len(s.get("shots", [])) for s in scenes)
    print(f"wrote {out.relative_to(_BACKEND)}")
    print(
        f"  timeline v{timeline.version}, {len(scenes)} scenes, {shots} shots, "
        f"{len(fixture['assets'])} assets, {len(fixture['bindings'])} bindings"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("fixture_name", help="written to tests/fixtures/<name>.json")
    args = parser.parse_args()
    asyncio.run(main(args.project_id, args.fixture_name))
