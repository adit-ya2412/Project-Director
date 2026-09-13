"""Remove leaked test-fixture projects from the shared dev database.

The project list is the same Postgres the UI reads. pytest / probe runs
that hit a real session leave `*-test` rows (and a few known probe
names) that sort onto the home screen. This uses the production
`delete_project` path — FK order, cross-project clip-cache release,
storage rmtree — one project at a time.

    python scripts/purge_test_projects.py           # delete
    python scripts/purge_test_projects.py --dry-run # list only

Does NOT match a name that merely contains "test" (the real film
`Radar and WW2 (camera-vocab test)` style). Suffix `-test` only, plus
the handful of probe names that never got that suffix.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# scripts/ is not the app root; allow `python scripts/purge_test_projects.py`
# from backend/ the same way seed_test_project.py is invoked.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.project import ProjectModel
from app.projects.deletion import delete_project

# Probe leftovers that never used the `-test` suffix. Exact name match only.
_PROBE_NAMES = frozenset(
    {
        "narration-cache-a",
        "narration-cache-b",
        "k9-emphasis-live",
        "k12-picture-is-graphic-replan",
    }
)


def is_leaked_test_project(name: str) -> bool:
    lowered = name.strip().lower()
    return lowered.endswith("-test") or lowered in _PROBE_NAMES


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print matches and keepers; do not delete",
    )
    args = parser.parse_args()

    async with async_session_factory() as session:
        rows = (
            (await session.execute(select(ProjectModel).order_by(ProjectModel.created_at.desc())))
            .scalars()
            .all()
        )

    leaked = [p for p in rows if is_leaked_test_project(p.name)]
    keepers = [p for p in rows if not is_leaked_test_project(p.name)]

    print(f"{len(rows)} projects: {len(leaked)} leaked, {len(keepers)} keep")
    for p in leaked:
        print(f"  DELETE {p.status:20} {p.id}  {p.name}")
    print("keep:")
    for p in keepers:
        print(f"  KEEP   {p.status:20} {p.id}  {p.name}")

    if args.dry_run:
        print("dry-run: nothing deleted")
        return 0

    failures = 0
    for p in leaked:
        async with async_session_factory() as session:
            try:
                summary = await delete_project(session, str(p.id))
            except Exception as exc:
                failures += 1
                print(f"  FAIL   {p.id}  {p.name}: {type(exc).__name__}: {exc}")
                continue
            if summary is None:
                print(f"  MISS   {p.id}  {p.name}")
                continue
            print(f"  GONE   {p.id}  {p.name}")

    print(f"deleted {len(leaked) - failures}/{len(leaked)}; failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
