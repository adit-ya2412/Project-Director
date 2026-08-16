"""Recreate the M8 test project from a committed fixture — no LLM calls,
no asset search, no generation, no cost.

    python scripts/seed_test_project.py [--fixture NAME] [--force]

`--fixture` names a file in `tests/fixtures/` (default: `m8_test_project`),
produced by `scripts/export_test_project.py`. A fixture snapshotted before
approval simply carries no assets or bindings and restores to exactly that
state.

Why this exists: `tests/conftest.py`'s `clean_database` fixture truncates
every table before every test, and it runs against the *same* Postgres the
dev server uses (docs/12_Testing_Strategy.md — there is no separate test
database). So running the test suite destroys any manually-built project.
The M8 test project took real OpenAI planning calls and real archival
asset resolution to build; this script restores it in seconds instead.

What it restores (project id is fixed, so on-disk storage paths stay
valid): the project row, its script, a v1 + v2 timeline via the real
`TimelineService` (then approved, matching the state it was left in), all
`asset` rows with full provenance, every `generated_clip` the fixture's
bindings reference, the `narration` rows whose audio is still on disk,
and the `shot_binding` rows that map each shot to its media.

## Versions are REMAPPED, never preserved (R1, 2026-08-16)

`TimelineService.append_version` always numbers from whatever
`create_initial` starts a project at - there is no way to ask it for "v11"
without first replaying the ten versions that came before it, which this
script does not have and should not need. So a restored project's active
version is whatever `create_initial` + one `append_version` call actually
produces (today: v2), which essentially NEVER equals the version the
fixture was originally captured at.

The bug this fixes: every `shot_binding` row is keyed on `(project_id,
timeline_version, shot_id)`, and the original script inserted the
fixture's bindings at their ORIGINAL `timeline_version` - a number that,
after the renumbering above, no longer names any version this project
actually has. Measured on a real restore, bindings landed at versions
5-11 while the restored project only ever reached v1-v2, so the ACTIVE
timeline had zero bindings. `ResolveAssetsStep` (which looks up bindings
at the active version - see its own docstring) read that as "nothing
resolved yet" and started resolving from scratch, including paid OpenAI
vision calls - exactly the re-buy this script exists to prevent.

The fix remaps every binding onto `appended.version` (whatever that
actually is) rather than preserving the number it was exported at.
Remapping was chosen over preserving the original numbers because
preserving them would mean either (a) bypassing `TimelineService` to
force-insert a specific version number, which reintroduces the "no other
code path may touch this table directly" hazard `TimelineService`'s own
docstring warns about, for a purely cosmetic benefit, or (b) replaying
every intermediate version this script has no record of, which is not
recoverable from a fixture that (deliberately, see
`export_test_project.py`) only ever captures the FINAL state. Remapping
costs nothing real: nothing downstream cares what number the active
version happens to be, only that bindings/narration/clips all agree on
it - which is exactly what `TimelineService`'s own `append_version` +
`_carry_forward_bindings` machinery already guarantees for every OTHER
version transition in this codebase. A fixture also stays more readable
this way - no version arithmetic to keep in sync with `create_initial`'s.

`produced_by` on the restored version is likewise taken from the
fixture's own `timeline_document`, not hardcoded - a fixture snapshotted
after `NarrationStep` (`produced_by=narration`) must come back stamped
`narration`, or `RenderStep._resolve_narration_audio` (which reads that
exact field to decide whether narration is safe to mux - see its own
docstring) treats the restore as an unreconciled timeline and renders
silently even though the narration rows and audio files are right there.

## Generated clips: restored if the bytes are still on disk, never regenerated

Same reasoning as the upload case below, applied to AI-generated media
(M7, ladder rungs 5-6): there is no `source_url` to re-fetch a generated
image/video from, and unlike a deterministic re-download, regenerating it
would not reproduce it - image/video generation is provider-side
non-deterministic even at this project's fixed seed (implementation
guide, Phase M7 advice), so "regenerate" would silently ship DIFFERENT
media under the same `prompt_hash`, not restore what was actually
reviewed and approved. A missing clip file is therefore a loud
`SystemExit`, not a quietly-skipped row: letting the shot fall back to a
placeholder is deciding, on the restorer's behalf, that a worse video is
acceptable - a decision this script has no business making silently.

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

import app.models  # noqa: E402,F401 - registers every model on Base.metadata
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.models.asset import AssetModel  # noqa: E402
from app.models.generated_clip import GeneratedClipModel  # noqa: E402
from app.models.narration import NarrationModel  # noqa: E402
from app.models.script import ScriptModel  # noqa: E402
from app.models.shot_binding import ShotBindingModel  # noqa: E402
from app.schemas.timeline import ProducedBy, Timeline  # noqa: E402
from app.timeline.service import TimelineService  # noqa: E402

FIXTURE_DIR = _BACKEND / "tests" / "fixtures"


async def _download(url: str, expected_hash: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": settings.wikimedia_user_agent})
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


async def main(force: bool, fixture_name: str) -> None:
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    if not fixture_path.exists():
        available = sorted(p.stem for p in FIXTURE_DIR.glob("*_test_project.json"))
        raise SystemExit(f"no fixture {fixture_path.name} - available: {available}")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    pid = fixture["project_id"]
    pid_uuid = uuid.UUID(pid)

    async with async_session_factory() as session:
        exists = (
            await session.execute(text("SELECT 1 FROM project WHERE id = :pid"), {"pid": pid})
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
            # Derived from the schema, never hand-listed: every table that
            # carries project_id, deleted children-first (sorted_tables is
            # parents-first, so reverse it). A hand-maintained list silently
            # goes stale the moment a phase adds a table - `narration` was
            # already missing from one, and the failure surfaces as an
            # opaque foreign-key violation rather than "you forgot a table".
            for table in (
                t.name
                for t in reversed(Base.metadata.sorted_tables)
                if "project_id" in t.columns and t.name != "project"
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE project_id = :pid"), {"pid": pid}
                )
            await session.execute(text("DELETE FROM project WHERE id = :pid"), {"pid": pid})
            await session.commit()
            print(f"removed existing project {pid}")

        await session.execute(
            text("INSERT INTO project (id, name, status) VALUES (:pid, :name, 'created')"),
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

        # Taken from the fixture, not hardcoded (R1 fix) - see module
        # docstring. Getting this wrong doesn't fail loudly: it silently
        # changes whether `RenderStep` believes narration was reconciled.
        produced_by = ProducedBy(fixture["timeline_document"]["produced_by"])
        appended = await svc.append_version(
            pid,
            produced_by=produced_by,
            transform=_apply,
            owns=frozenset({"metadata", "creative_context", "music_plan", "scenes"}),
        )
        # Restore the approval state it was snapshotted in, rather than
        # always approving: a fixture captured at the approval gate must
        # come back sitting AT that gate, or seeding it would silently skip
        # the human-in-the-loop step (ADR-008) the next run depends on.
        was_approved = fixture["timeline_document"].get("status") == "approved"
        if was_approved:
            await svc.approve(pid, appended.version)

        assets_dir = settings.storage_root / pid / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        asset_id_by_hash: dict[str, uuid.UUID] = {}
        downloaded = 0

        for a in fixture["assets"]:
            path = assets_dir / a["filename"]
            if not path.exists():
                if not a.get("source_url"):
                    # M6.5: a human upload (ladder rung `project_assets`,
                    # A8/A23) has no external URL its bytes can be
                    # re-fetched from - unlike every Wikimedia/Pexels
                    # asset above, which this loop can always recover for
                    # free. `storage/` is gitignored, so an upload's bytes
                    # simply do not exist anywhere this script can reach
                    # once they are gone from disk. Fail loudly rather
                    # than silently writing a row that points at nothing
                    # (the render would then fail much later, deep inside
                    # ffmpeg, for a reason that has nothing to do with the
                    # actual defect) - re-upload the file to the source
                    # project and re-export the fixture instead.
                    raise SystemExit(
                        f"asset {a['filename']!r} (provider={a['provider']!r}) has no "
                        "source_url and is missing on disk - this is a human upload "
                        "(M6.5, A8/A23), whose bytes cannot be re-downloaded from "
                        "anywhere. The fixture round-trip does not support restoring "
                        "uploaded assets; re-upload the file to the source project and "
                        "re-export the fixture."
                    )
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

        # Generated media (M7, ladder rungs 5-6) - restored only if the
        # bytes are still on disk. See module docstring for why a missing
        # clip is a loud failure rather than a skipped row like narration
        # below: unlike TTS (re-synthesisable, just at a cost) or a
        # Wikimedia asset (deterministically re-downloadable), a
        # regenerated image/video is not the SAME image/video, so there is
        # no safe degraded path - only "restore what was actually approved"
        # or "say so and stop".
        clips_dir = settings.storage_root / pid / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        clip_id_by_prompt_hash: dict[str, uuid.UUID] = {}
        for c in fixture.get("clips", []):
            path = clips_dir / c["filename"]
            if not path.exists():
                raise SystemExit(
                    f"generated clip {c['filename']!r} (shot {c['shot_id']!r}, "
                    f"prompt_hash={c['prompt_hash']!r}) is missing on disk - storage/ "
                    "is gitignored and generated media has no source_url to recover "
                    "it from, and regenerating it would not reproduce it (M7 "
                    "generation is provider-side non-deterministic even at this "
                    "project's fixed seed). The fixture round-trip does not support "
                    "restoring generated media whose bytes are gone; regenerate it "
                    "(paid) in the source project and re-export the fixture."
                )
            clip_model = GeneratedClipModel(
                project_id=pid_uuid,
                shot_id=c["shot_id"],
                provider=c["provider"],
                model_id=c["model_id"],
                prompt=c["prompt"],
                prompt_hash=c["prompt_hash"],
                duration_s=c["duration_s"],
                local_path=str(path),
                cost_cents=c["cost_cents"],
            )
            session.add(clip_model)
            await session.flush()
            clip_id_by_prompt_hash[c["prompt_hash"]] = clip_model.id

        # Narration rows come back only when their audio file still exists:
        # the row is a cache entry pointing AT that file, so restoring one
        # without the other would make NarrationStep skip synthesis and then
        # hand the renderer a path to nothing. TTS is not re-fetchable the
        # way an asset is (it costs money and is not byte-reproducible), so
        # a missing file is reported, not silently worked around.
        narration_dir = settings.storage_root / pid / "narration"
        restored_narrations = 0
        missing_audio: list[str] = []
        for n in fixture.get("narrations", []):
            audio_path = narration_dir / n["filename"]
            if not audio_path.exists():
                missing_audio.append(n["scene_id"])
                continue
            session.add(
                NarrationModel(
                    project_id=pid_uuid,
                    scene_id=n["scene_id"],
                    provider=n["provider"],
                    voice_id=n["voice_id"],
                    model_id=n["model_id"],
                    output_format=n["output_format"],
                    text=n["text"],
                    content_hash=n["content_hash"],
                    local_path=str(audio_path),
                    alignment=n["alignment"],
                    character_count=n["character_count"],
                    cost_cents=n["cost_cents"],
                )
            )
            restored_narrations += 1

        # Remapped onto the version this restore actually produced, never
        # the version the fixture happened to record (R1 fix - see module
        # docstring for why remapping, not preserving, is the right call).
        # The `.get(..., fixture["timeline_version"])` below additionally
        # makes this loop tolerant of a fixture exported by the OLD,
        # buggy `export_test_project.py`, which wrote every superseded
        # copy of a binding at its own original version: filtering to
        # just the one that matches the fixture's own recorded active
        # version recovers exactly the set a correct export would have
        # produced, without needing to re-export anything.
        active_version = fixture["timeline_version"]
        for b in fixture["bindings"]:
            if b.get("timeline_version", active_version) != active_version:
                continue
            asset_id = asset_id_by_hash.get(b["asset_content_hash"])
            clip_id = clip_id_by_prompt_hash.get(b.get("clip_prompt_hash"))
            # A binding whose fixture-recorded state claims resolved media
            # ("resolved"/"generated") but that could not be matched to
            # either an asset or a clip above is exactly the silent-
            # placeholder trap this fix exists to close (see R1) - most
            # likely an old-format fixture that predates clip export
            # entirely. Fail loudly rather than write a binding that will
            # render a placeholder for a shot the fixture says has real
            # media.
            if b["state"] in {"resolved", "generated"} and asset_id is None and clip_id is None:
                raise SystemExit(
                    f"binding {b['shot_id']!r} is {b['state']!r} but no asset or clip "
                    "could be restored for it - this fixture cannot be seeded without "
                    "silently downgrading that shot to a placeholder. Re-export the "
                    "fixture with a version of export_test_project.py that captures "
                    "generated_clip provenance, or accept the shot will regenerate."
                )
            session.add(
                ShotBindingModel(
                    project_id=pid_uuid,
                    timeline_version=appended.version,
                    shot_id=b["shot_id"],
                    state=b["state"],
                    rung=b["rung"],
                    asset_id=asset_id,
                    clip_id=clip_id,
                )
            )
        await session.commit()

    print(f"seeded project {pid} from {fixture_path.name}")
    print(
        f"  timeline v{appended.version} ({produced_by.value}, "
        f"{'approved' if was_approved else 'draft'}), "
        f"{len(fixture['assets'])} assets ({downloaded} re-downloaded), "
        f"{len(fixture.get('clips', []))} generated clips, "
        f"{len(fixture['bindings'])} bindings, {restored_narrations} narration segments"
    )
    if missing_audio:
        print(
            f"  WARNING: no audio on disk for scene(s) {missing_audio} - those rows were "
            "skipped, so the next run will re-synthesise (and re-pay for) them"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="delete and recreate if it already exists"
    )
    parser.add_argument(
        "--fixture",
        default="m8_test_project",
        help="fixture name in tests/fixtures/ (default: m8_test_project)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.force, args.fixture))
