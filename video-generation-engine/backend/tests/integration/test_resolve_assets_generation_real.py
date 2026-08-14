"""ResolveAssetsStep's real generation path (M7): image generation
(bounded synchronous poll), video generation (submit-and-poll, resumable
across a simulated crash), the generation cache (rung 0), and the budget
cap. No real fal.ai call: `FalImageProvider`/`FalVideoProvider` are
monkeypatched to fakes with canned responses, the same pattern used for
the M5 planners and the M6 search providers.
"""

import io
import uuid as uuid_module

import pytest_asyncio
from PIL import Image

from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.base import ImageResult, VideoJobStatus
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    PreferredMediaType,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
)
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps import resolve_assets as resolve_assets_module
from app.workflow.steps.resolve_assets import ResolveAssetsStep


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("resolve-assets-generation-test")
        return project.id


def _shot(shot_id: str, *, preferred_type: PreferredMediaType, duration_s: float = 4.0) -> Shot:
    strategy = (
        AssetStrategy.GENERATE_VIDEO
        if preferred_type == PreferredMediaType.VIDEO
        else AssetStrategy.GENERATE_IMAGE
    )
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        prompt="a coal mine",
        asset_plan=AssetPlan(
            strategy=strategy,
            preferred_type=preferred_type,
            fallback_chain=[strategy],
        ),
    )


def _png_bytes(
    color: tuple[int, int, int] = (10, 20, 30), size: tuple[int, int] = (1080, 1920)
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


async def _seed_timeline(project_id: str, shots: list[Shot]) -> None:
    scene = Scene(
        id="sc_01", order=0, title="Scene", duration_s=sum(s.duration_s for s in shots), shots=shots
    )
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="a script")

        def _fill(base):
            base.scenes = [scene]
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_fill,
            owns=frozenset({"scenes", "creative_context", "metadata"}),
        )


class _FakeImageProvider:
    name = "fal_image"

    def __init__(self, results: list[ImageResult] | None = None) -> None:
        self._results = list(results or [])
        self.calls: list = []

    async def generate(self, request):
        self.calls.append(request)
        return self._results.pop(0)


class _FakeVideoProvider:
    name = "fal_video"

    def __init__(
        self, submit_job_id: str = "job-1", poll_result: VideoJobStatus | None = None
    ) -> None:
        self.submit_calls: list = []
        self.poll_calls: list[str] = []
        self._submit_job_id = submit_job_id
        self._poll_result = poll_result

    async def submit(self, request) -> str:
        self.submit_calls.append(request)
        return self._submit_job_id

    async def poll(self, job_id: str) -> VideoJobStatus:
        self.poll_calls.append(job_id)
        assert self._poll_result is not None
        return self._poll_result


def _patch_providers(monkeypatch, *, image_provider=None, video_provider=None) -> None:
    monkeypatch.setattr(resolve_assets_module, "FalImageProvider", lambda: image_provider)
    monkeypatch.setattr(resolve_assets_module, "FalVideoProvider", lambda: video_provider)


async def _run_step(project_id: str) -> None:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        result = await ResolveAssetsStep().run(ctx)
        assert result.outcome == "ok"
        await session.commit()


async def _binding(project_id: str, shot_id: str):
    async with async_session_factory() as session:
        repo = ShotBindingRepository(session)
        return await repo.get(uuid_module.UUID(project_id), 2, shot_id)


async def test_image_generation_happy_path(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot])

    image_provider = _FakeImageProvider(
        results=[ImageResult(content=_png_bytes(), content_type="image/png")]
    )
    _patch_providers(
        monkeypatch, image_provider=image_provider, video_provider=_FakeVideoProvider()
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"
    assert binding.clip_id is not None

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        spent = await clip_repo.total_cost_cents_for_project(uuid_module.UUID(project_id))
    assert spent == settings.fal_image_cost_cents_estimate


async def test_video_generation_fresh_submission_leaves_binding_pending(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.VIDEO)
    await _seed_timeline(project_id, [shot])

    image_provider = _FakeImageProvider(
        results=[
            ImageResult(
                content=b"keyframe-bytes",
                content_type="image/jpeg",
                hosted_url="http://fal.example/kf.jpg",
            )
        ]
    )
    video_provider = _FakeVideoProvider(submit_job_id="job-fresh")
    _patch_providers(monkeypatch, image_provider=image_provider, video_provider=video_provider)

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "pending"  # not terminal - the job is still in flight
    assert len(video_provider.submit_calls) == 1
    assert video_provider.submit_calls[0].image_url == "http://fal.example/kf.jpg"

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        in_flight = await clip_repo.get_in_flight_for_shot(uuid_module.UUID(project_id), "sh_01")
    assert in_flight is not None
    assert in_flight.job_id == "job-fresh"
    assert in_flight.status == "submitted"


async def test_video_generation_resume_still_in_progress_does_not_resubmit(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.VIDEO)
    await _seed_timeline(project_id, [shot])

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        await clip_repo.insert_pending(
            project_id=uuid_module.UUID(project_id),
            shot_id="sh_01",
            provider="fal_video",
            model_id=settings.fal_video_model,
            prompt="a coal mine",
            prompt_hash="deadbeef",
            job_id="job-existing",
            estimated_cost_cents=54,
        )
        await session.commit()

    video_provider = _FakeVideoProvider(poll_result=VideoJobStatus(state="in_progress"))
    _patch_providers(
        monkeypatch, image_provider=_FakeImageProvider(), video_provider=video_provider
    )

    await _run_step(project_id)

    assert video_provider.poll_calls == ["job-existing"]
    binding = await _binding(project_id, "sh_01")
    assert binding.state == "pending"


async def test_video_generation_resume_completed_downloads_and_resolves(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.VIDEO)
    await _seed_timeline(project_id, [shot])

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        await clip_repo.insert_pending(
            project_id=uuid_module.UUID(project_id),
            shot_id="sh_01",
            provider="fal_video",
            model_id=settings.fal_video_model,
            prompt="a coal mine",
            prompt_hash="deadbeef2",
            job_id="job-existing-2",
            estimated_cost_cents=54,
        )
        await session.commit()

    video_provider = _FakeVideoProvider(
        poll_result=VideoJobStatus(
            state="completed", content=b"fake-video-bytes", content_type="video/mp4"
        )
    )
    _patch_providers(
        monkeypatch, image_provider=_FakeImageProvider(), video_provider=video_provider
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"
    assert binding.clip_id is not None

    async with async_session_factory() as session:
        from app.models.generated_clip import GeneratedClipModel

        clip = await session.get(GeneratedClipModel, binding.clip_id)
    assert clip.status == "completed"
    assert clip.local_path is not None
    assert clip.duration_s == shot.duration_s


async def test_budget_cap_blocks_generation(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "project_budget_cap_cents", 0)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot])

    image_provider = _FakeImageProvider(
        results=[ImageResult(content=b"fake-image-bytes", content_type="image/jpeg")]
    )
    _patch_providers(
        monkeypatch, image_provider=image_provider, video_provider=_FakeVideoProvider()
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "failed"
    assert "budget cap" in binding.last_error
    assert image_provider.calls == []  # never even attempted the paid call


async def test_generation_cache_hit_skips_a_fresh_call(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot])

    styled_prompt = "a coal mine"  # no visual_style set on this timeline's creative_context
    import hashlib

    prompt_hash = hashlib.sha256(f"{styled_prompt}|{settings.fal_image_model}".encode()).hexdigest()

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        cached = await clip_repo.insert(
            project_id=uuid_module.UUID(project_id),
            shot_id="sh_01",
            provider="fal_image",
            model_id=settings.fal_image_model,
            prompt=styled_prompt,
            prompt_hash=prompt_hash,
            duration_s=None,
            local_path="/tmp/already-generated.jpg",
            cost_cents=4,
        )
        cached_id = cached.id
        await session.commit()

    image_provider = _FakeImageProvider(results=[])  # would raise IndexError if ever called
    _patch_providers(
        monkeypatch, image_provider=image_provider, video_provider=_FakeVideoProvider()
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"
    assert binding.clip_id == cached_id
    assert image_provider.calls == []
