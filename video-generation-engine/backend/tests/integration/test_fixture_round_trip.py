"""R1 (2026-08-16): the fixture round-trip's entire purpose is "a restored
project needs nothing re-bought" - and until this test existed, nothing
checked that. `export_test_project.py`/`seed_test_project.py` had a
prior, ad-hoc check that only asserted rows existed after a restore; a
restore that produced zero bindings at the active version, no narration,
and 7 placeholder shots out of 19 still passed it, because it never
looked at whether those rows pointed at anything real.

This test seeds the real `hinglish_final_project` fixture - a genuine,
previously-live project, captured after narration and partial generation
- via the real CLI entrypoint (`scripts/seed_test_project.py`, invoked as
a subprocess exactly as a human would run it, not imported: importing it
directly would execute its module-level `os.chdir` in-process and leak a
changed cwd into the rest of this test session). It then proves,
directly against the restored database rows and a real ffmpeg render,
the three properties the fix was for:

1. Every shot's binding at the ACTIVE timeline version resolves to real
   media on disk (no shot silently downgraded to a placeholder).
2. Narration resolves (`RenderStep._resolve_narration_audio` returns real,
   existing audio paths, not `None`) - proof `produced_by` survived the
   restore, not just that `narration` rows exist.
3. Both `ResolveAssetsStep` passes and `NarrationStep` report
   `is_satisfied() == True` against the restored state - the exact
   question whose wrong answer was the costly part of R1: seeing "not
   satisfied" here is what made a restore quietly re-run paid resolution.
4. A real `render_video()` call (small dimensions, real ffmpeg, no
   network, no paid provider) succeeds and produces a video with BOTH a
   video and an audio stream - the end-to-end proof that the restored
   project is usable, not just that its rows look right in isolation.

Generated clips, narration audio, and one human-uploaded image (rung
`project_assets`, A8/A23 - it has no `source_url` either) are not
re-creatable from the fixture JSON alone, so their real bytes are
committed alongside the JSON under
`tests/fixtures/hinglish_final_project_media/` (~8.3MB: 1 uploaded image,
7 generated images, 6 narration clips, 1 music track) and copied into
this test's isolated storage before seeding, exactly mirroring what
already sits in the real project's `storage/` directory. See R1's entry
in docs/13_Implementation_Guide.md for the repo-size trade-off this
implies for every future fixture that carries generated/uploaded media.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from app.core.config import settings
from app.db.session import async_session_factory
from app.renderer.slideshow import RenderSettings
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import TERMINAL_STATES, ShotBindingRepository
from app.schemas.timeline import ProducedBy
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps.narration import NarrationStep
from app.workflow.steps.render import (
    _resolve_narration_audio,
    _resolved_path_and_hash,
    render_video,
)
from app.workflow.steps.resolve_assets import GENERATION_RUNGS, SEARCH_RUNGS, ResolveAssetsStep

_FIXTURE_NAME = "hinglish_final_project"
_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
_MEDIA_DIR = _FIXTURE_DIR / f"{_FIXTURE_NAME}_media"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _ffprobe_stream_types(path: Path) -> set[str]:
    result = subprocess.run(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "stream=codec_type",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return {s["codec_type"] for s in json.loads(result.stdout)["streams"]}


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


async def _seed_fixture(tmp_path: Path, project_id: str) -> None:
    """Copies the fixture's committed media into this test's isolated
    storage - restoring exactly what `storage/` already holds for the
    real project - then invokes the real CLI script as a subprocess, the
    same way a human restoring this project would. `STORAGE_ROOT` is
    overridden via the child process's environment (pydantic-settings
    reads env vars case-insensitively) rather than via `monkeypatch`,
    which only affects THIS process, not a subprocess."""
    for sub in ("assets", "clips", "narration", "music"):
        src = _MEDIA_DIR / sub
        if not src.exists():
            continue
        dest = tmp_path / project_id / sub
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            shutil.copy2(f, dest / f.name)

    result = subprocess.run(
        [sys.executable, "scripts/seed_test_project.py", "--force", "--fixture", _FIXTURE_NAME],
        cwd=str(_REPO_ROOT / "backend"),
        env={**os.environ, "STORAGE_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"seed failed:\nstdout={result.stdout}\nstderr={result.stderr}"


async def test_restored_project_is_renderable_without_rebuying_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)

    fixture = json.loads((_FIXTURE_DIR / f"{_FIXTURE_NAME}.json").read_text(encoding="utf-8"))
    project_id = fixture["project_id"]

    await _seed_fixture(tmp_path, project_id)

    async with async_session_factory() as session:
        timeline_service = TimelineService(session)
        timeline = await timeline_service.get_active(project_id)
        assert timeline is not None

        # R1's produced_by bug: hardcoding ASSET_PLANNER on restore made
        # `RenderStep._resolve_narration_audio` treat this timeline as
        # never reconciled, regardless of what the narration rows said.
        assert timeline.produced_by == ProducedBy.NARRATION
        assert timeline.status.value == "approved"

        shots = timeline.all_shots()
        binding_repo = ShotBindingRepository(session)
        bindings = {
            b.shot_id: b
            for b in await binding_repo.list_for_version(uuid.UUID(project_id), timeline.version)
        }

        # Property 1: every shot has a binding AT THE ACTIVE VERSION, and
        # every one of them resolves to a real file on disk - the exact
        # thing that was zero (bindings) and then 7-of-19 (placeholders)
        # before this fix.
        assert len(bindings) == len(shots), "every shot must have a binding at the active version"
        for shot in shots:
            binding = bindings[shot.id]
            assert (
                binding.state in TERMINAL_STATES
            ), f"shot {shot.id} binding is {binding.state!r}, not a finished state"
            path, content_hash = await _resolved_path_and_hash(session, binding)
            assert path is not None and path.exists(), (
                f"shot {shot.id} (state={binding.state}, rung={binding.rung}) has no real "
                "media - it would render as a placeholder"
            )
            assert content_hash is not None

        # Property 2: narration resolves to real, existing audio - proof
        # `produced_by` (not just the `narration` rows) survived the
        # restore.
        narration_pairs = await _resolve_narration_audio(session, timeline)
        assert narration_pairs is not None, "restored project must not render silently"
        assert len(narration_pairs) == len(timeline.scenes)
        for narration_path, _content_hash in narration_pairs:
            assert narration_path.exists()

        # Property 3: the exact question R1 got wrong. Both passes of
        # ResolveAssetsStep (search, then generation) and NarrationStep
        # must all already consider themselves DONE against the restored
        # state - `is_satisfied() == False` here is precisely what made a
        # restore silently re-run (and re-bill) planning/generation.
        ctx = _make_ctx(project_id, session)
        search_pass = ResolveAssetsStep(
            name="resolve_assets_search", permitted_strategies=SEARCH_RUNGS
        )
        generation_pass = ResolveAssetsStep(
            name="resolve_assets_generate", permitted_strategies=GENERATION_RUNGS
        )
        assert await search_pass.is_satisfied(ctx) is True
        assert await generation_pass.is_satisfied(ctx) is True
        assert await NarrationStep().is_satisfied(ctx) is True

        # Property 4: an actual render succeeds and is not silent - the
        # end-to-end proof, not just isolated preconditions. Small
        # dimensions purely for test speed; `render_video` is the same
        # function `RenderStep`/the draft endpoint call for real.
        render_settings = RenderSettings(
            width=360,
            height=640,
            fps=24,
            pixel_format=settings.render_pixel_format,
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
        )
        output_path = await render_video(
            ctx, timeline, render_settings, output_filename="round_trip_test.mp4"
        )
        await session.commit()

    assert output_path.exists()
    stream_types = _ffprobe_stream_types(output_path)
    assert stream_types == {
        "video",
        "audio",
    }, f"restored project rendered silently or without video: streams={stream_types}"


async def test_missing_generated_clip_fails_loudly_instead_of_placeholding(tmp_path):
    """The other half of R1's decision: if a generated clip's bytes are
    genuinely gone (unlike an asset, there is no `source_url` to recover
    them from, and regeneration would not reproduce the same image), the
    fixture round-trip must refuse to seed rather than silently restore a
    project that will render that shot as a placeholder."""
    fixture = json.loads((_FIXTURE_DIR / f"{_FIXTURE_NAME}.json").read_text(encoding="utf-8"))
    project_id = fixture["project_id"]

    # Everything except clips restores fine; clips are deliberately
    # withheld - this reproduces "the bytes are gone" without touching
    # the fixture.
    for sub in ("assets", "narration", "music"):
        src = _MEDIA_DIR / sub
        dest = tmp_path / project_id / sub
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            shutil.copy2(f, dest / f.name)

    result = subprocess.run(
        [sys.executable, "scripts/seed_test_project.py", "--force", "--fixture", _FIXTURE_NAME],
        cwd=str(_REPO_ROOT / "backend"),
        env={**os.environ, "STORAGE_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "generated clip" in result.stderr.lower() or "generated clip" in result.stdout.lower()
