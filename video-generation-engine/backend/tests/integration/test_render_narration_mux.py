"""RenderStep's M8 step-3 wiring: narration muxed onto the finished silent
video in one final pass, and the explicit silent-render decision for the
projects that must NOT get audio (DRY_RUN, and any timeline that was
never reconciled by `NarrationStep`).

No real ElevenLabs call and no `FakeNarrationProvider` bytes (those are
not decodable audio - see its docstring): real, small MP3 files are
synthesised locally with ffmpeg at known durations, exactly like
`test_narration_audio_concat.py`, then inserted into the `narration`
table the way `NarrationStep` would have left them, so `RenderStep` can
be exercised without ever calling out to ElevenLabs or spending money.
"""

import json
import subprocess
import uuid as uuid_module

import pytest
import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.elevenlabs import compute_narration_content_hash
from app.repositories.narration_repository import NarrationRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)
from app.timeline.duration import compute_timeline_duration
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps.render import RenderStep

from .test_narration_audio_concat import _make_sine_mp3, _stream_duration

_VOICE_ID = "voice_render_mux_test"

# Four scenes (three boundaries) at deliberately non-round durations - the
# same "more than two scenes" discipline as the concat-drift test, applied
# here to the full RenderStep path instead of `mux_narration` in isolation.
_SCENE_DURATIONS_S = [0.937, 1.256, 0.842, 1.118]


def _ffprobe_streams(path) -> list[dict]:
    args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "stream=codec_type,duration",
        str(path),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["streams"]


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("render-narration-mux-test")
        return project.id


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


async def _seed_narrated_timeline(
    project_id: str, *, scene_durations: list[float], voice_id: str
) -> tuple[int, float]:
    """Builds a timeline that already LOOKS like `NarrationStep` finished
    with it: one scene per shot, hard cuts only (so D5 subtracts nothing
    and the timeline's total is exactly the sum of the shots' durations),
    `produced_by=NARRATION`, and a matching real `narration` row per scene
    whose audio file's TRUE ffprobed duration is what `scene_durations`
    asked for. Returns (version, expected_total_duration_s).
    """
    scenes: list[Scene] = []
    true_durations: list[float] = []
    narration_dir = settings.storage_root / project_id / "narration"
    narration_dir.mkdir(parents=True, exist_ok=True)

    async with async_session_factory() as session:
        narration_repo = NarrationRepository(session)
        for i, requested_duration in enumerate(scene_durations):
            scene_id = f"sc_{i:02d}"
            shot_id = f"sh_{i:02d}"
            text = f"Scene number {i} narration text."

            mp3_path = narration_dir / f"_source_{i}.mp3"
            await _make_sine_mp3(mp3_path, requested_duration)
            true_duration = _stream_duration(mp3_path, "audio")
            true_durations.append(true_duration)

            content_hash = compute_narration_content_hash(
                text=text,
                voice_id=voice_id,
                model=settings.elevenlabs_model,
                output_format=settings.elevenlabs_output_format,
            )
            final_path = narration_dir / f"{content_hash}.mp3"
            final_path.write_bytes(mp3_path.read_bytes())

            await narration_repo.insert(
                project_id=uuid_module.UUID(project_id),
                scene_id=scene_id,
                provider="test-fixture",
                voice_id=voice_id,
                model_id=settings.elevenlabs_model,
                output_format=settings.elevenlabs_output_format,
                text=text,
                content_hash=content_hash,
                local_path=str(final_path),
                alignment={
                    "characters": [],
                    "character_start_times_seconds": [],
                    "character_end_times_seconds": [],
                },
                character_count=len(text),
                cost_cents=0,
            )

            shot = Shot(
                id=shot_id,
                order=0,
                intent=ShotIntent.EXPLAIN,
                duration_s=true_duration,
                transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
            )
            scenes.append(
                Scene(
                    id=scene_id,
                    order=i,
                    title=f"Scene {i}",
                    narration_text=text,
                    duration_s=true_duration,
                    shots=[shot],
                )
            )
        await session.commit()

    expected_total = compute_timeline_duration([s.shots[0] for s in scenes])

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base):
            base.scenes = scenes
            base.metadata.total_duration_s = expected_total
            base.metadata.voice_id = None  # forces settings.elevenlabs_voice_id fallback
            # long_form_direction.md A8 fix: `_resolve_narration_rows` now
            # gates on this flag (not `produced_by` alone, which does not
            # survive a later version - see that function's own updated
            # docstring), mirroring exactly what `NarrationStep` itself
            # always sets alongside `produced_by=NARRATION`.
            base.metadata.narration_locked = True
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.NARRATION,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        await service.approve(project_id, appended.version)
        return appended.version, expected_total


async def test_render_step_mux_produces_audio_and_video_matching_the_timeline(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    _, expected_total = await _seed_narrated_timeline(
        project_id, scene_durations=_SCENE_DURATIONS_S, voice_id=_VOICE_ID
    )

    async with async_session_factory() as session:
        result = await RenderStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok", result.error

    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).get(project_id)

    streams = _ffprobe_streams(project.video_path)
    by_type = {s["codec_type"]: float(s["duration"]) for s in streams}

    assert set(by_type) == {"video", "audio"}  # real narration -> real mux, not silent

    # The core proof (brief: "measure the streams separately... not just
    # the container's format=duration"): audio keeps its full, exact,
    # sample-accurate length - the sum of the four scenes' TRUE decoded
    # narration durations - regardless of the video's own quantisation.
    # Narration is the master clock (D1); it is never trimmed to fit.
    assert by_type["audio"] == pytest.approx(expected_total, abs=0.005)

    # Audio stays on the 5 ms band (sample-accurate narration clock).
    # Video cannot: this fixture is four hard-cut runs of non-round
    # narration durations, each frame-quantised, then concat-copied.
    # The old 50 ms band hid the §14.1 tpad bug here as +0.180 s
    # (4.333 vs 4.153). After (frames-1)/fps the residual is ~80 ms
    # of quantisation-plus-concat, not an extra decoded frame.
    # The 5 ms / 3.40 s exactness proof lives in
    # test_static_tpad_duration_is_frame_exact — that is the test
    # that fails if someone reverts the `- 1`. This band only has
    # to fail the pre-fix 180 ms regression.
    assert by_type["video"] == pytest.approx(expected_total, abs=0.10)


async def test_dry_run_render_step_stays_silent_even_though_narration_rows_exist(
    project_id, monkeypatch
):
    """DRY_RUN's FakeNarrationProvider bytes are not decodable audio (its
    own docstring says so) - RenderStep must recognise DRY_RUN and skip
    muxing entirely rather than handing ffmpeg an undecodable file."""
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    # dry_run=False while seeding, so real ffmpeg-decodable files land in
    # the narration table - proving RenderStep's silence in the next
    # assertion is a deliberate DRY_RUN check, not just "no rows found".
    monkeypatch.setattr(settings, "dry_run", False)
    await _seed_narrated_timeline(
        project_id, scene_durations=_SCENE_DURATIONS_S[:2], voice_id=_VOICE_ID
    )

    monkeypatch.setattr(settings, "dry_run", True)
    async with async_session_factory() as session:
        result = await RenderStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok", result.error

    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).get(project_id)

    streams = _ffprobe_streams(project.video_path)
    assert {s["codec_type"] for s in streams} == {"video"}  # silent - no audio track


async def test_render_step_stays_silent_when_timeline_was_never_narrated(project_id, monkeypatch):
    """An older project, or a pipeline run with `NarrationStep` skipped:
    the active timeline's `produced_by` is never `narration`, so there is
    no guarantee its durations were reconciled against real spoken audio -
    RenderStep must render silently rather than guess."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    shot = Shot(
        id="sh_00",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=1.0,
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    scene = Scene(
        id="sc_00", order=0, title="Scene", narration_text="text", duration_s=1.0, shots=[shot]
    )

    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="unused")

        def _fill(base):
            base.scenes = [scene]
            base.metadata.total_duration_s = 1.0
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,  # NOT narration
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        await service.approve(project_id, appended.version)

    async with async_session_factory() as session:
        result = await RenderStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok", result.error

    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).get(project_id)

    streams = _ffprobe_streams(project.video_path)
    assert {s["codec_type"] for s in streams} == {"video"}
