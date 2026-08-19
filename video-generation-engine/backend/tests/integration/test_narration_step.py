"""NarrationStep (M8 step 2): fresh synthesis + reconciliation, the
cache-hit path (no re-pay across projects), resumability (no
re-synthesis, no duplicate `append_version` on a second run), the budget
cap (both narration's own spend and its folding into the SAME cap
`ResolveAssetsStep` already checks), and the over-`MAX_VIDEO_DURATION_S`
loud failure.

Track C C2: disk-fallback after a DB wipe, unique-by-hash gather,
ElevenLabs concurrency cap 3, and the Starter per-character cost.

No real ElevenLabs call: `ElevenLabsNarrationProvider` is monkeypatched to
a queued fake with canned alignments, exactly the pattern
`test_resolve_assets_generation_real.py` uses for fal.ai.
"""

import asyncio
import json
import uuid as uuid_module

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.assets.cost import total_project_spend_cents
from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.models.narration import NarrationModel
from app.providers.base import NarrationRequest, NarrationResult
from app.repositories.generated_clip_repository import GeneratedClipRepository
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
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.engine import WorkflowEngine
from app.workflow.steps import narration as narration_module
from app.workflow.steps.narration import NarrationStep

_TEXT = "Hello world"
_VOICE_ID = "voice_abc"


def _uniform_alignment(text: str, chars_per_second: float = 10.0) -> dict:
    return {
        "characters": list(text),
        "character_start_times_seconds": [i / chars_per_second for i in range(len(text))],
        "character_end_times_seconds": [(i + 1) / chars_per_second for i in range(len(text))],
    }


def _shot(shot_id: str, order: int, span: tuple[int, int]) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        narration_span=span,
        duration_s=3.0,  # planner's estimate - reconciliation overwrites this
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )


class _FakeElevenLabsProvider:
    name = "elevenlabs"

    def __init__(self, alignment_by_scene: dict[str, dict], *, delay_s: float = 0.0) -> None:
        self._alignment_by_scene = alignment_by_scene
        self._delay_s = delay_s
        self.calls: list[NarrationRequest] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def synthesize(self, request: NarrationRequest) -> NarrationResult:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.calls.append(request)
        try:
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
            if request.scene_id not in self._alignment_by_scene:
                raise PermanentError(f"no canned alignment for {request.scene_id}")
            alignment = self._alignment_by_scene[request.scene_id]
            return NarrationResult(
                content=f"fake-audio:{request.scene_id}".encode(),
                alignment=alignment,
                character_count=len(request.text),
            )
        finally:
            self.in_flight -= 1


def _patch_provider(monkeypatch, provider: _FakeElevenLabsProvider) -> None:
    monkeypatch.setattr(narration_module, "ElevenLabsNarrationProvider", lambda: provider)


def _content_hash_for(text: str, voice_id: str) -> str:
    from app.providers.elevenlabs import compute_narration_content_hash

    return compute_narration_content_hash(
        text=text,
        voice_id=voice_id,
        model=settings.elevenlabs_model,
        output_format=settings.elevenlabs_output_format,
    )


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("narration-step-test")
        return project.id


def _single_shot_scene(scene_id: str, order: int, text: str) -> Scene:
    return Scene(
        id=scene_id,
        order=order,
        title=f"Scene {order}",
        narration_text=text,
        duration_s=3.0,
        shots=[_shot(f"sh_{order:02d}", 0, (0, len(text)))],
    )


async def _seed_approved_scenes(project_id: str, scenes: list[Scene]) -> int:
    script = "".join(s.narration_text for s in scenes)
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script=script)

        def _fill(base):
            base.scenes = list(scenes)
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_fill,
            owns=frozenset({"scenes", "metadata"}),
        )
        await service.approve(project_id, appended.version)
        return appended.version


async def _seed_approved_timeline(project_id: str, shots: list[Shot]) -> int:
    scene = Scene(
        id="sc_01",
        order=0,
        title="Scene",
        narration_text=_TEXT,
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
    )
    return await _seed_approved_scenes(project_id, [scene])


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


async def test_fresh_synthesis_reconciles_durations_and_approves_new_version(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)
    monkeypatch.setattr(settings, "elevenlabs_cost_cents_per_character", 1.0)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    seeded_version = await _seed_approved_timeline(project_id, shots)

    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        ctx = _make_ctx(project_id, session)
        result = await NarrationStep().run(ctx)
        await session.commit()

    assert result.outcome == "ok"
    assert len(provider.calls) == 1  # one request for the one scene
    assert provider.calls[0].voice_id == _VOICE_ID

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)

    assert timeline.version == seeded_version + 1
    assert timeline.produced_by == ProducedBy.NARRATION
    assert timeline.status.value == "approved"  # narration approves its own version

    shots_by_id = {s.id: s for s in timeline.all_shots()}
    # "Hello"(0-4) onset=0.0 to next shot's onset(char 5)=0.5 -> 0.5s;
    # " world"(5-10) onset=0.5 to scene end (1.1) -> 0.6s. Hard cut, so
    # compute_timeline_duration doesn't subtract anything.
    assert shots_by_id["sh_01"].duration_s == pytest.approx(0.5)
    assert shots_by_id["sh_02"].duration_s == pytest.approx(0.6)
    assert timeline.metadata.total_duration_s == pytest.approx(1.1)

    content_hash = _content_hash_for(_TEXT, _VOICE_ID)
    async with async_session_factory() as session:
        narration_repo = NarrationRepository(session)
        row = await narration_repo.get_by_content_hash(content_hash)
        assert row is not None
        assert row.cost_cents == len(_TEXT)  # 1 cent/char, monkeypatched above
        spent = await narration_repo.total_cost_cents_for_project(uuid_module.UUID(project_id))
    assert spent == len(_TEXT)
    narration_dir = settings.storage_root / project_id / "narration"
    assert (narration_dir / f"{content_hash}.mp3").is_file()
    sidecar = narration_dir / f"{content_hash}.alignment.json"
    assert sidecar.is_file()
    assert set(json.loads(sidecar.read_text(encoding="utf-8"))) >= {
        "characters",
        "character_start_times_seconds",
        "character_end_times_seconds",
    }


async def test_resume_does_not_resynthesize_or_append_a_duplicate_version(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    await _seed_approved_timeline(project_id, shots)

    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})

    # "Process 1": runs NarrationStep once, via the engine (so is_satisfied
    # is exercised exactly the way a real resume would use it).
    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        ctx = _make_ctx(project_id, session)
        await WorkflowEngine(ctx, steps=[NarrationStep()]).run()

    async with async_session_factory() as session:
        after_first = await TimelineService(session).get_active(project_id)
    version_after_first = after_first.version
    assert after_first.produced_by == ProducedBy.NARRATION

    # "Process 2": a completely fresh engine. Must skip NarrationStep via
    # is_satisfied() rather than re-running it - a second run must not
    # re-synthesize (no second provider call) or append v(N+2).
    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        ctx = _make_ctx(project_id, session)
        await WorkflowEngine(ctx, steps=[NarrationStep()]).run()

    assert len(provider.calls) == 1  # never called a second time

    async with async_session_factory() as session:
        after_second = await TimelineService(session).get_active(project_id)
    assert after_second.version == version_after_first  # no duplicate version


async def test_cache_hit_across_projects_never_calls_the_provider_again(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]

    async with async_session_factory() as session:
        project_a = await PostgresProjectRepository(session).create("narration-cache-a")
    async with async_session_factory() as session:
        project_b = await PostgresProjectRepository(session).create("narration-cache-b")

    await _seed_approved_timeline(project_a.id, shots)
    await _seed_approved_timeline(project_b.id, shots)  # identical scene text

    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        await NarrationStep().run(_make_ctx(project_a.id, session))
        await session.commit()

    assert len(provider.calls) == 1

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_b.id, session))
        await session.commit()

    assert result.outcome == "ok"
    assert len(provider.calls) == 1  # project B hit the GLOBAL content-hash cache


async def test_budget_cap_blocks_narration_before_any_paid_call(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)
    monkeypatch.setattr(settings, "elevenlabs_cost_cents_per_character", 1.0)
    monkeypatch.setattr(settings, "project_budget_cap_cents", 0)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    seeded_version = await _seed_approved_timeline(project_id, shots)

    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "failed"
    assert "budget cap" in result.error
    assert provider.calls == []  # never even attempted the paid call

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
    assert timeline.version == seeded_version  # no version was appended


async def test_narration_spend_counts_against_the_shared_budget_cap(project_id, monkeypatch):
    """Proves the M8 open decision ("does TTS count against the budget
    cap?") is real, not aspirational: after narration spends money,
    `total_project_spend_cents` - the same helper ResolveAssetsStep's
    generation calls check against - sees it."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)
    monkeypatch.setattr(settings, "elevenlabs_cost_cents_per_character", 5.0)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    await _seed_approved_timeline(project_id, shots)

    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})
    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()
    assert result.outcome == "ok"

    expected_cost = round(len(_TEXT) * 5.0)
    async with async_session_factory() as session:
        spend = await total_project_spend_cents(
            clip_repo=GeneratedClipRepository(session),
            narration_repo=NarrationRepository(session),
            project_id=uuid_module.UUID(project_id),
        )
    assert spend == expected_cost > 0


async def test_reconciled_duration_exceeding_max_video_duration_fails_loudly_without_persisting(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)
    monkeypatch.setattr(settings, "max_video_duration_s", 1.0)  # scene's real total is 1.1s

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    seeded_version = await _seed_approved_timeline(project_id, shots)

    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "failed"
    assert "exceeding" in result.error
    assert "shorten the script" in result.error

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
    assert timeline.version == seeded_version  # no narration version was appended

    # The synthesis itself was NOT wasted - it's cached globally, so a
    # human shortening the script and re-running only re-pays for scenes
    # whose text actually changed.
    async with async_session_factory() as session:
        row = await NarrationRepository(session).get_by_content_hash(
            _content_hash_for(_TEXT, _VOICE_ID)
        )
    assert row is not None


async def test_no_voice_configured_fails_cleanly(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", None)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    await _seed_approved_timeline(project_id, shots)

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))

    assert result.outcome == "failed"
    assert "no narration voice configured" in result.error


async def test_dry_run_uses_the_fake_provider_and_still_reconciles(project_id, monkeypatch):
    """DRY_RUN keeps costing zero and touching no real provider, but
    still exercises real reconciliation end to end (implementation guide
    4.1: fakes are kept forever, not skipped)."""
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    seeded_version = await _seed_approved_timeline(project_id, shots)

    async with async_session_factory() as session:
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok"

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
        spend = await total_project_spend_cents(
            clip_repo=GeneratedClipRepository(session),
            narration_repo=NarrationRepository(session),
            project_id=uuid_module.UUID(project_id),
        )

    assert timeline.version == seeded_version + 1
    assert timeline.produced_by == ProducedBy.NARRATION
    assert spend == 0  # DRY_RUN is free - no check_budget call is even reached
    for shot in timeline.all_shots():
        assert shot.duration_s > 0


def test_elevenlabs_cost_matches_starter_multilingual_v2_rate():
    """Track C §3.3: ₹8.80/1K ≈ 0.0103 ¢/char, not the old 0.018 guess."""
    assert settings.elevenlabs_cost_cents_per_character == pytest.approx(0.0103)


async def test_disk_fallback_restores_row_without_resynthesizing(project_id, monkeypatch):
    """§3.3: pytest truncates `narration` but leaves the mp3. The sidecar
    lets the next run re-insert the row instead of re-paying ElevenLabs."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    await _seed_approved_timeline(project_id, shots)
    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()
    assert result.outcome == "ok"
    assert len(provider.calls) == 1

    content_hash = _content_hash_for(_TEXT, _VOICE_ID)
    async with async_session_factory() as session:
        await session.execute(
            delete(NarrationModel).where(NarrationModel.content_hash == content_hash)
        )
        await session.commit()

    async with async_session_factory() as session:
        assert await NarrationRepository(session).get_by_content_hash(content_hash) is None

    # is_satisfied is True (timeline already produced_by=NARRATION), so
    # call the synthesis path directly on a fresh un-narrated version.
    async with async_session_factory() as session:
        service = TimelineService(session)
        timeline = await service.get_active(project_id)
        assert timeline is not None

        def _unlock(base):
            base.metadata.narration_locked = False
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.ASSET_PLANNER,
            transform=_unlock,
            owns=frozenset({"metadata"}),
        )
        await session.commit()

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok"
    assert len(provider.calls) == 1  # disk fallback, not a second paid call

    async with async_session_factory() as session:
        row = await NarrationRepository(session).get_by_content_hash(content_hash)
    assert row is not None
    assert row.alignment["characters"] == list(_TEXT)


async def test_mp3_without_sidecar_still_resynthesizes(project_id, monkeypatch):
    """Legacy files written before C2 have no alignment sidecar, so the
    bytes on disk are not enough to rebuild the row."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    shots = [_shot("sh_01", 0, (0, 5)), _shot("sh_02", 1, (5, 11))]
    await _seed_approved_timeline(project_id, shots)

    content_hash = _content_hash_for(_TEXT, _VOICE_ID)
    narration_dir = settings.storage_root / project_id / "narration"
    narration_dir.mkdir(parents=True, exist_ok=True)
    (narration_dir / f"{content_hash}.mp3").write_bytes(b"legacy-mp3-no-sidecar")

    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})
    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok"
    assert len(provider.calls) == 1
    assert (narration_dir / f"{content_hash}.alignment.json").is_file()


async def test_identical_scene_text_synthesizes_once(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    scenes = [
        _single_shot_scene("sc_01", 0, _TEXT),
        _single_shot_scene("sc_02", 1, _TEXT),
    ]
    await _seed_approved_scenes(project_id, scenes)
    # Only sc_01 is canned: a second call keyed on sc_02 would fail.
    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment(_TEXT)})

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok"
    assert len(provider.calls) == 1
    assert provider.calls[0].scene_id == "sc_01"

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
    assert len(timeline.scenes) == 2
    assert all(s.shots[0].duration_s > 0 for s in timeline.scenes)


async def test_tts_concurrency_never_exceeds_elevenlabs_cap(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)
    monkeypatch.setattr(settings, "narration_concurrency", 3)

    texts = [f"Scene text number {i} here" for i in range(4)]
    scenes = [_single_shot_scene(f"sc_{i:02d}", i, text) for i, text in enumerate(texts)]
    await _seed_approved_scenes(project_id, scenes)

    provider = _FakeElevenLabsProvider(
        {scene.id: _uniform_alignment(scene.narration_text) for scene in scenes},
        delay_s=0.08,
    )
    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "ok"
    assert len(provider.calls) == 4
    assert provider.max_in_flight <= 3
    assert provider.max_in_flight == 3


async def test_one_scene_tts_failure_fails_the_whole_step(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "elevenlabs_voice_id", _VOICE_ID)

    scenes = [
        _single_shot_scene("sc_01", 0, "First scene text"),
        _single_shot_scene("sc_02", 1, "Second scene text"),
    ]
    seeded_version = await _seed_approved_scenes(project_id, scenes)
    provider = _FakeElevenLabsProvider({"sc_01": _uniform_alignment("First scene text")})

    async with async_session_factory() as session:
        _patch_provider(monkeypatch, provider)
        result = await NarrationStep().run(_make_ctx(project_id, session))
        await session.commit()

    assert result.outcome == "failed"
    assert "no canned alignment for sc_02" in result.error

    async with async_session_factory() as session:
        timeline = await TimelineService(session).get_active(project_id)
    assert timeline.version == seeded_version
    # The successful sibling is cached; a retry only re-pays sc_02.
    async with async_session_factory() as session:
        row = await NarrationRepository(session).get_by_content_hash(
            _content_hash_for("First scene text", _VOICE_ID)
        )
    assert row is not None
