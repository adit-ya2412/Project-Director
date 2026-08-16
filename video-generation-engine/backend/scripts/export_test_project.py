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
its `asset` rows (with full provenance, so the bytes can be re-fetched),
its `generated_clip` rows (AI-generated media, referenced by whichever
`shot_binding` rows point at one - there is no source_url to re-fetch
these from, see `seed_test_project.py`'s handling), and `shot_binding`
rows. A project snapshotted before approval simply has none of these,
which is fine - it restores to exactly the state it was in.

`shot_binding` is exported at the ACTIVE version ONLY (R1 fix, 2026-08-16):
`ShotBinding` rows are versioned per `(project_id, timeline_version,
shot_id)`, and this project's own version history typically carries
several superseded copies of essentially the same binding (A11/A20 carry-
forward re-persists one at every version whose prompt/asset_plan didn't
change - see `app/timeline/service.py::_carry_forward_bindings`).
Exporting every version this project ever had - the original bug -
produced a fixture whose bindings were unusable the moment
`seed_test_project.py` recreated the timeline (necessarily renumbered
from 1, since `TimelineService.append_version` always counts from
whatever `create_initial` starts at): none of the old version numbers
exist in the restored project, so the active timeline had zero bindings
and `ResolveAssetsStep` silently re-resolved (and re-billed) everything.
The fixture deliberately does NOT record which version these bindings
came from either - see `seed_test_project.py`'s docstring for why
REMAPPING onto the freshly restored version, not preserving the original
number, is the fix.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import bindparam, text

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
        # Active version ONLY (see module docstring) - a project that has
        # been re-planned or re-narrated several times carries superseded
        # bindings at every earlier version, and those are not what a
        # restore should bring back.
        bindings = (
            await session.execute(
                text(
                    "SELECT shot_id, state, rung, asset_id, clip_id FROM shot_binding "
                    "WHERE project_id = :pid AND timeline_version = :version ORDER BY shot_id"
                ),
                {"pid": project_id, "version": timeline.version},
            )
        ).fetchall()
        # Generated media (M7 ladder rungs 5-6) has no source_url - unlike
        # a searched/uploaded asset, its bytes cannot be re-fetched from
        # anywhere once gone, so `seed_test_project.py` needs the full
        # provenance here, not just a hash. Only the clips this export's
        # own bindings actually reference - never every clip the project
        # ever generated (a rejected constraint-check attempt, or a clip
        # from a version this export is deliberately not restoring).
        clip_ids = [b.clip_id for b in bindings if b.clip_id is not None]
        clips = (
            (
                await session.execute(
                    text(
                        "SELECT id, shot_id, provider, model_id, prompt, prompt_hash, "
                        "duration_s, local_path, cost_cents FROM generated_clip "
                        "WHERE id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": clip_ids},
                )
            ).fetchall()
            if clip_ids
            else []
        )
        # Narration is exported in full, alignment included: unlike an asset
        # (re-fetchable from source_url) TTS output cannot be reproduced for
        # free, and its character-level alignment is what the master clock
        # reads. Losing these rows means re-paying ElevenLabs to regenerate
        # data we already own.
        narrations = (
            await session.execute(
                text(
                    "SELECT scene_id, provider, voice_id, model_id, output_format, text, "
                    "content_hash, local_path, alignment, character_count, cost_cents "
                    "FROM narration WHERE project_id = :pid ORDER BY scene_id"
                ),
                {"pid": project_id},
            )
        ).fetchall()

    hash_by_asset_id = {str(a.id): a.content_hash for a in assets}
    # `prompt_hash` (not the row's `id`) is the stable identity a restore
    # can key on - it's the same global dedup key `ResolveAssetsStep`
    # already cache-hits against, so an id that only ever existed in the
    # exporting database is never round-tripped as if it meant something.
    prompt_hash_by_clip_id = {str(c.id): c.prompt_hash for c in clips}
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
        "clips": [
            {
                "shot_id": c.shot_id,
                "provider": c.provider,
                "model_id": c.model_id,
                "prompt": c.prompt,
                "prompt_hash": c.prompt_hash,
                "duration_s": c.duration_s,
                "cost_cents": c.cost_cents,
                "filename": c.local_path.replace("\\", "/").rsplit("/", 1)[-1],
            }
            for c in clips
        ],
        # No `timeline_version` here (R1 fix) - every binding above was
        # already filtered to the single active version this fixture
        # captures, and `seed_test_project.py` remaps them onto whatever
        # version the restore actually produces rather than trusting a
        # number that a renumbered restore cannot honour. A binding
        # carries at most one of `asset_content_hash`/`clip_prompt_hash`,
        # matching `ShotBindingModel` itself only ever populating one of
        # `asset_id`/`clip_id` per row.
        "bindings": [
            {
                "shot_id": b.shot_id,
                "state": b.state,
                "rung": b.rung,
                "asset_content_hash": hash_by_asset_id.get(str(b.asset_id)) if b.asset_id else None,
                "clip_prompt_hash": (
                    prompt_hash_by_clip_id.get(str(b.clip_id)) if b.clip_id else None
                ),
            }
            for b in bindings
        ],
        "narrations": [
            {
                "scene_id": n.scene_id,
                "provider": n.provider,
                "voice_id": n.voice_id,
                "model_id": n.model_id,
                "output_format": n.output_format,
                "text": n.text,
                "content_hash": n.content_hash,
                "filename": n.local_path.replace("\\", "/").rsplit("/", 1)[-1],
                "alignment": n.alignment,
                "character_count": n.character_count,
                "cost_cents": n.cost_cents,
            }
            for n in narrations
        ],
    }

    out = FIXTURE_DIR / f"{fixture_name}.json"
    out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    scenes = fixture["timeline_document"].get("scenes", [])
    shots = sum(len(s.get("shots", [])) for s in scenes)
    print(f"wrote {out.relative_to(_BACKEND)}")
    print(
        f"  timeline v{timeline.version}, {len(scenes)} scenes, {shots} shots, "
        f"{len(fixture['assets'])} assets, {len(fixture['clips'])} generated clips, "
        f"{len(fixture['bindings'])} bindings, {len(fixture['narrations'])} narration segments"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument("fixture_name", help="written to tests/fixtures/<name>.json")
    args = parser.parse_args()
    asyncio.run(main(args.project_id, args.fixture_name))
