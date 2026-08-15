"""`SelectMusicStep` (M8 step 4, D6/21.2) - selection recorded via
`append_version` into `Timeline.music_plan` (never a side table), the
hard licence gate, `check_budget` folded in, and the "never fails the
step" degrade-to-no-track guarantee (A22's own precedent, extended).

No real Pixabay call: `PixabayMusicProvider` is monkeypatched to a fake
with canned candidates, exactly the pattern
`test_resolve_assets_real.py` uses for Wikimedia/Pexels.
"""

import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.base import AudioBytes, MusicSearchQuery, TrackCandidate
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import MusicPlan, ProducedBy, Scene, Shot, ShotIntent
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps import select_music as select_music_module
from app.workflow.steps.select_music import SelectMusicStep


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("select-music-test")
        return project.id


def _make_ctx(project_id: str, session) -> RunContext:
    return RunContext(
        project_id=project_id,
        session=session,
        repo=PostgresProjectRepository(session),
        timeline_service=TimelineService(session),
    )


class _FakeMusicSearchProvider:
    name = "fake_pixabay_music"

    def __init__(self, candidates: list[TrackCandidate], content_by_id: dict[str, bytes]) -> None:
        self._candidates = candidates
        self._content_by_id = content_by_id
        self.search_calls: list[MusicSearchQuery] = []
        self.fetch_calls: list[str] = []

    async def search(self, query: MusicSearchQuery) -> list[TrackCandidate]:
        self.search_calls.append(query)
        return self._candidates

    async def fetch(self, candidate: TrackCandidate) -> AudioBytes:
        self.fetch_calls.append(candidate.source_id)
        return AudioBytes(
            content=self._content_by_id[candidate.source_id], content_type="audio/mpeg"
        )


class _RaisingMusicSearchProvider:
    name = "raising"

    async def search(self, query: MusicSearchQuery):
        raise RuntimeError("simulated total provider outage")

    async def fetch(self, candidate: TrackCandidate):
        raise RuntimeError("simulated total provider outage")


async def _make_wav_mp3_bytes(duration_s: float = 1.0) -> bytes:
    """A real, decodable MP3 - reuses the same ffmpeg-lavfi technique as
    the narration/render tests, via a temp file (this module's own
    provider fake returns bytes, not a path)."""
    import tempfile
    from pathlib import Path

    from tests.integration.test_narration_audio_concat import _make_sine_mp3

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.mp3"
        await _make_sine_mp3(path, duration_s)
        return path.read_bytes()


async def _seed_timeline_with_music_plan(
    project_id: str, *, licence_requirements: list[str]
) -> int:
    scene = Scene(
        id="sc_01",
        order=0,
        title="Scene",
        duration_s=3.0,
        shots=[Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)],
    )
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="a script")

        def _fill(base):
            base.scenes = [scene]
            base.music_plan = MusicPlan(
                mood="sombre",
                tempo="slow",
                search_terms=["documentary underscore", "wartime"],
                licence_requirements=licence_requirements,
            )
            return base

        appended = await service.append_version(
            project_id,
            produced_by=ProducedBy.DIRECTOR,
            transform=_fill,
            owns=frozenset({"scenes", "music_plan"}),
        )
        return appended.version


def _patch_pixabay(monkeypatch, provider) -> None:
    monkeypatch.setattr(select_music_module, "PixabayMusicProvider", lambda: provider)


async def test_no_music_plan_is_a_trivial_no_op(project_id):
    """A project with no music_plan at all (should not happen in
    practice - the Director always sets one) is simply not this step's
    problem - `is_satisfied` is True immediately, `run` never appends a
    version."""
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="s")

        ctx = _make_ctx(project_id, session)
        step = SelectMusicStep()
        assert await step.is_satisfied(ctx) is True
        result = await step.run(ctx)
        assert result.outcome == "ok"

        latest = await service.get_active(project_id)
    assert latest.version == 1  # create_initial's version only - nothing appended


async def test_dry_run_records_a_selection_via_the_fake_provider(project_id, monkeypatch):
    # Pinned explicitly, not relied on from the ambient .env (which has
    # DRY_RUN=false for real, paid live testing of other features) - this
    # suite's whole premise for THIS test is the fake path.
    monkeypatch.setattr(settings, "dry_run", True)
    version = await _seed_timeline_with_music_plan(project_id, licence_requirements=["cc0"])
    async with async_session_factory() as session:
        ctx = _make_ctx(project_id, session)
        step = SelectMusicStep()
        assert await step.is_satisfied(ctx) is False

        result = await step.run(ctx)
        assert result.outcome == "ok"

        timeline = await ctx.timeline_service.get_active(project_id)
    assert timeline.version == version + 1
    assert timeline.produced_by == ProducedBy.MUSIC_SELECTION
    assert timeline.music_plan.selection_attempted is True
    assert timeline.music_plan.selected_track is not None
    assert timeline.music_plan.selected_track.provider == "fake_music"


async def test_is_satisfied_true_after_a_completed_selection(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    await _seed_timeline_with_music_plan(project_id, licence_requirements=["cc0"])
    async with async_session_factory() as session:
        ctx = _make_ctx(project_id, session)
        step = SelectMusicStep()
        await step.run(ctx)
        assert await step.is_satisfied(ctx) is True


async def test_licence_gate_rejects_a_non_matching_candidate(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    await _seed_timeline_with_music_plan(project_id, licence_requirements=["cc0"])

    content = await _make_wav_mp3_bytes()
    provider = _FakeMusicSearchProvider(
        candidates=[
            TrackCandidate(
                source_id="t1",
                source_url="http://example.test/t1",
                title="documentary underscore, wartime",
                licence="pixabay_extended",  # not "cc0" - must be rejected
            )
        ],
        content_by_id={"t1": content},
    )
    _patch_pixabay(monkeypatch, provider)

    async with async_session_factory() as session:
        ctx = _make_ctx(project_id, session)
        result = await SelectMusicStep().run(ctx)
        assert result.outcome == "ok"
        timeline = await ctx.timeline_service.get_active(project_id)

    assert timeline.music_plan.selection_attempted is True
    assert timeline.music_plan.selected_track is None
    assert provider.fetch_calls == []  # never even downloaded a licence-rejected candidate


async def test_a_matching_candidate_is_selected_and_recorded_with_full_provenance(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)
    await _seed_timeline_with_music_plan(project_id, licence_requirements=["cc0"])

    content = await _make_wav_mp3_bytes()
    provider = _FakeMusicSearchProvider(
        candidates=[
            TrackCandidate(
                source_id="t1",
                source_url="http://example.test/t1.mp3",
                title="documentary underscore, wartime",
                licence="cc0",
                author="Test Composer",
            )
        ],
        content_by_id={"t1": content},
    )
    _patch_pixabay(monkeypatch, provider)

    async with async_session_factory() as session:
        ctx = _make_ctx(project_id, session)
        result = await SelectMusicStep().run(ctx)
        assert result.outcome == "ok"
        timeline = await ctx.timeline_service.get_active(project_id)

    selection = timeline.music_plan.selected_track
    assert selection is not None
    assert selection.track_id == "t1"
    assert selection.licence == "cc0"
    assert selection.source_url == "http://example.test/t1.mp3"
    assert selection.attribution == "Test Composer"
    assert selection.content_hash

    music_path = settings.storage_root / project_id / "music" / f"{selection.content_hash}.mp3"
    assert music_path.exists()
    assert music_path.read_bytes() == content


async def test_total_provider_failure_never_fails_the_step(project_id, monkeypatch):
    """A22's own precedent, extended: a total music-provider outage
    degrades to 'no suitable track', never blocks anything."""
    monkeypatch.setattr(settings, "dry_run", False)
    await _seed_timeline_with_music_plan(project_id, licence_requirements=["cc0"])
    _patch_pixabay(monkeypatch, _RaisingMusicSearchProvider())

    async with async_session_factory() as session:
        ctx = _make_ctx(project_id, session)
        result = await SelectMusicStep().run(ctx)
        assert result.outcome == "ok"
        timeline = await ctx.timeline_service.get_active(project_id)

    assert timeline.music_plan.selection_attempted is True
    assert timeline.music_plan.selected_track is None


async def test_the_real_pixabay_provider_is_the_honest_documented_limitation(
    project_id, monkeypatch
):
    """No monkeypatch here - proves the REAL `PixabayMusicProvider` (not
    a fake standing in for it) degrades to 'no suitable track' rather
    than crashing the step, exercising the documented, verified-live gap
    (see app/providers/pixabay_music.py's own docstring)."""
    monkeypatch.setattr(settings, "dry_run", False)
    await _seed_timeline_with_music_plan(project_id, licence_requirements=["cc0"])

    async with async_session_factory() as session:
        ctx = _make_ctx(project_id, session)
        result = await SelectMusicStep().run(ctx)
        assert result.outcome == "ok"
        timeline = await ctx.timeline_service.get_active(project_id)

    assert timeline.music_plan.selection_attempted is True
    assert timeline.music_plan.selected_track is None


async def test_budget_cap_blocks_a_fetch_and_degrades_to_no_track(project_id, monkeypatch):
    """`check_budget` folded in (M8 build order item 4) - a cap already
    exceeded blocks the fetch attempt, same as any other paid rung, and
    the step still degrades cleanly rather than failing."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "music_cost_cents_estimate", 5)
    monkeypatch.setattr(settings, "project_budget_cap_cents", 0)
    await _seed_timeline_with_music_plan(project_id, licence_requirements=["cc0"])

    content = await _make_wav_mp3_bytes()
    provider = _FakeMusicSearchProvider(
        candidates=[
            TrackCandidate(
                source_id="t1",
                source_url="http://example.test/t1",
                title="documentary underscore, wartime",
                licence="cc0",
            )
        ],
        content_by_id={"t1": content},
    )
    _patch_pixabay(monkeypatch, provider)

    async with async_session_factory() as session:
        ctx = _make_ctx(project_id, session)
        result = await SelectMusicStep().run(ctx)
        assert result.outcome == "ok"
        timeline = await ctx.timeline_service.get_active(project_id)

    assert timeline.music_plan.selected_track is None
    assert provider.fetch_calls == []  # budget check happens before the fetch attempt
