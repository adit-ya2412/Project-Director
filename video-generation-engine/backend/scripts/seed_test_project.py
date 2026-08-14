"""Recreate the M8 test project from a committed fixture — no LLM calls,
no asset search, no generation, no cost.

    python scripts/seed_test_project.py [--force]

Why this exists: `tests/conftest.py`'s `clean_database` fixture truncates
every table before every test, and it runs against the *same* Postgres the
dev server uses (docs/12_Testing_Strategy.md — there is no separate test
database). So running the test suite destroys any manually-built project.
The M8 test project took real OpenAI planning calls and real archival
asset resolution to build; this script restores it in seconds instead.

What it restores (project id is fixed, so on-disk storage paths stay
valid): the project row, its script, a v1 + v2 timeline via the real
`TimelineService` (then approved, matching the state it was left in), all
13 `asset` rows with full provenance, and the 13 `shot_binding` rows that
map each shot to its asset.

Asset *bytes* are not in the fixture (storage/ is gitignored). Any file
missing from disk is re-downloaded from its recorded `source_url` — all
of them are free Wikimedia Commons URLs — and its content hash is
verified against the fixture before it is accepted, so a silently changed
upstream file fails loudly rather than corrupting the fixture.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
# `STORAGE_ROOT` defaults to the relative "./storage", which the app resolves
# against the process's cwd - and the server is always launched from the repo
# root. Run from anywhere else and the same relative path silently points at a
# different directory, so asset rows would reference files that exist nowhere
# the server will look. Anchor to the repo root explicitly.
os.chdir(_BACKEND.parent)

from app.core.config import settings  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.models.asset import AssetModel  # noqa: E402
from app.models.script import ScriptModel  # noqa: E402
from app.models.shot_binding import ShotBindingModel  # noqa: E402
from app.schemas.timeline import ProducedBy, Timeline  # noqa: E402
from app.timeline.service import TimelineService  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "m8_test_project.json"


async def _download(url: str, expected_hash: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(
            url, headers={"User-Agent": settings.wikimedia_user_agent}
        )
        response.raise_for_status()
    content = response.content
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_hash:
        raise SystemExit(
            f"content hash mismatch for {url}\n"
            f"  expected {expected_hash}\n  got      {actual}\n"
            "The upstream file changed. Do not silently accept it — re-export "
            "the fixture deliberately if this is expected."
        )
    return content


async def main(force: bool) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pid = fixture["project_id"]
    pid_uuid = uuid.UUID(pid)

    async with async_session_factory() as session:
        exists = (
            await session.execute(
                text("SELECT 1 FROM project WHERE id = :pid"), {"pid": pid}
            )
        ).fetchone()
        if exists and not force:
            print(f"project {pid} already exists — nothing to do (use --force to recreate)")
            return
        if exists:
            # workflow_step_attempt is the one child table that does NOT carry
            # project_id - it FKs to workflow_run.id - so it has to go first,
            # via its parent.
            await session.execute(
                text(
                    "DELETE FROM workflow_step_attempt WHERE workflow_run_id IN "
                    "(SELECT id FROM workflow_run WHERE project_id = :pid)"
                ),
                {"pid": pid},
            )
            for table in (
                "shot_binding",
                "asset",
                "generated_clip",
                "timeline_version",
                "script",
                "llm_call",
                "domain_event",
                "workflow_run",
                "render",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE project_id = :pid"), {"pid": pid}
                )
            await session.execute(text("DELETE FROM project WHERE id = :pid"), {"pid": pid})
            await session.commit()
            print(f"removed existing project {pid}")

        await session.execute(
            text(
                "INSERT INTO project (id, name, status) VALUES (:pid, :name, 'created')"
            ),
            {"pid": pid, "name": fixture["name"]},
        )
        session.add(
            ScriptModel(
                project_id=pid_uuid,
                content=fixture["script"],
                language=fixture.get("language", "en"),
                version=1,
            )
        )
        await session.commit()

        # Timeline through the real service — append_version is the only
        # legal writer of a version (Invariant I3), fixture restore included.
        parsed = Timeline.model_validate(fixture["timeline_document"])
        svc = TimelineService(session)
        await svc.create_initial(pid, fixture["script"])

        def _apply(base: Timeline) -> Timeline:
            base.metadata = parsed.metadata
            base.creative_context = parsed.creative_context
            base.music_plan = parsed.music_plan
            base.scenes = parsed.scenes
            return base

        appended = await svc.append_version(
            pid,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_apply,
            owns=frozenset({"metadata", "creative_context", "music_plan", "scenes"}),
        )
        await svc.approve(pid, appended.version)

        assets_dir = settings.storage_root / pid / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        asset_id_by_hash: dict[str, uuid.UUID] = {}
        downloaded = 0

        for a in fixture["assets"]:
            path = assets_dir / a["filename"]
            if not path.exists():
                path.write_bytes(await _download(a["source_url"], a["content_hash"]))
                downloaded += 1
            model = AssetModel(
                project_id=pid_uuid,
                provider=a["provider"],
                source_url=a["source_url"],
                type=a["type"],
                local_path=str(path),
                licence=a["licence"],
                attribution=a["attribution"],
                content_hash=a["content_hash"],
                confidence=a["confidence"],
            )
            session.add(model)
            await session.flush()
            asset_id_by_hash[a["content_hash"]] = model.id

        for b in fixture["bindings"]:
            session.add(
                ShotBindingModel(
                    project_id=pid_uuid,
                    timeline_version=b["timeline_version"],
                    shot_id=b["shot_id"],
                    state=b["state"],
                    rung=b["rung"],
                    asset_id=asset_id_by_hash.get(b["asset_content_hash"]),
                )
            )
        await session.commit()

    print(f"seeded project {pid}")
    print(f"  timeline v{appended.version} (approved), {len(fixture['assets'])} assets "
          f"({downloaded} re-downloaded), {len(fixture['bindings'])} bindings")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="delete and recreate if it already exists"
    )
    asyncio.run(main(parser.parse_args().force))
