"""ResolveAssetsStep's real generation path (M7): image generation
(bounded synchronous poll), video generation (submit-and-poll, resumable
across a simulated crash), the generation cache (rung 0), the budget cap,
and (M6.5) Director-constraint enforcement on generated media - a vision
check, bounded regeneration on a violation (A12/A13/A18), and a terminal
`failed` binding naming the constraint once every attempt is exhausted
(A14/A19). No real fal.ai/OpenAI call: `FalImageProvider`/
`FalVideoProvider`/`OpenAIPlanningProvider` are monkeypatched to fakes
with canned responses, the same pattern used for the M5 planners and the
M6 search providers.
"""

import hashlib
import io
import uuid as uuid_module

import pytest_asyncio
from PIL import Image

from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.base import ConstraintVerdict, ImageResult, VideoJobStatus
from app.providers.fakes.vision import FakeVisionConstraintProvider
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
from app.workflow.steps.resolve_assets import ResolveAssetsStep, _project_seed


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


async def _seed_timeline(
    project_id: str, shots: list[Shot], *, constraints: list[str] | None = None
) -> None:
    scene = Scene(
        id="sc_01", order=0, title="Scene", duration_s=sum(s.duration_s for s in shots), shots=shots
    )
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="a script")

        def _fill(base):
            base.scenes = [scene]
            if constraints is not None:
                base.creative_context.constraints = constraints
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


def _patch_providers(
    monkeypatch, *, image_provider=None, video_provider=None, vision_provider=None
) -> None:
    monkeypatch.setattr(resolve_assets_module, "FalImageProvider", lambda: image_provider)
    monkeypatch.setattr(resolve_assets_module, "FalVideoProvider", lambda: video_provider)
    # Always patched, even when a test doesn't care about constraints -
    # `run()` unconditionally constructs `OpenAIPlanningProvider()` in
    # real (non-DRY_RUN) mode, and this suite must never touch a real
    # OpenAI client. Shots with no `creative_context.constraints` never
    # actually call it (M6.5, A12 - zero constraints, zero calls), so the
    # default fake here is inert for every test that doesn't opt in.
    resolved_vision_provider = (
        vision_provider if vision_provider is not None else FakeVisionConstraintProvider()
    )
    monkeypatch.setattr(
        resolve_assets_module, "OpenAIPlanningProvider", lambda: resolved_vision_provider
    )


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
    # M6.5: the seed is now part of the hash (see resolve_assets._generate_checked_image's
    # docstring) - attempt 1 and attempt 2 of a bounded regeneration can share
    # identical prompt text, and must not collapse onto the same cache entry.
    seed = _project_seed(project_id)
    prompt_hash = hashlib.sha256(
        f"{styled_prompt}|{settings.fal_image_model}|{seed}".encode()
    ).hexdigest()

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


# --- M6.5: Director-constraint enforcement on generated media ---------------


async def test_dry_run_never_constructs_a_vision_provider(project_id, monkeypatch):
    """The hard requirement: DRY_RUN must pass with zero API keys
    configured. Constraints being present in the timeline must not matter
    - the fake generation path never checks them at all."""
    monkeypatch.setattr(settings, "dry_run", True)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    def _raise():
        raise AssertionError("OpenAIPlanningProvider must not be constructed under DRY_RUN")

    monkeypatch.setattr(resolve_assets_module, "OpenAIPlanningProvider", _raise)

    await _run_step(project_id)  # would raise if the vision provider were ever constructed

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"


async def test_empty_constraints_makes_zero_vision_calls(project_id, monkeypatch):
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=[])  # explicit empty, real mode

    monkeypatch.setattr(settings, "dry_run", False)
    image_provider = _FakeImageProvider(
        results=[ImageResult(content=_png_bytes(), content_type="image/png")]
    )
    vision_provider = FakeVisionConstraintProvider(
        verdicts=[ConstraintVerdict(violated=True, violated_constraint="x", reason="x")]
    )  # would fail the shot immediately if ever actually called
    _patch_providers(
        monkeypatch,
        image_provider=image_provider,
        video_provider=_FakeVideoProvider(),
        vision_provider=vision_provider,
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"
    assert vision_provider.calls == []


async def test_constraint_violation_triggers_one_retry_with_revised_prompt_same_seed(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    image_provider = _FakeImageProvider(
        results=[
            ImageResult(content=_png_bytes((1, 1, 1)), content_type="image/png"),
            ImageResult(content=_png_bytes((2, 2, 2)), content_type="image/png"),
        ]
    )
    vision_provider = FakeVisionConstraintProvider(
        verdicts=[
            ConstraintVerdict(
                violated=True, violated_constraint="no Nazi symbols", reason="a swastika is visible"
            ),
            ConstraintVerdict(violated=False, violated_constraint="", reason=""),
        ]
    )
    _patch_providers(
        monkeypatch,
        image_provider=image_provider,
        video_provider=_FakeVideoProvider(),
        vision_provider=vision_provider,
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"
    assert binding.clip_id is not None

    assert len(image_provider.calls) == 2  # exactly one retry, not an unbounded loop
    first_call, second_call = image_provider.calls
    assert first_call.seed == second_call.seed  # A13: same seed on the first retry
    assert first_call.prompt != second_call.prompt  # A18: revised, not identical
    assert "no Nazi symbols" in second_call.prompt  # the violated constraint, appended verbatim

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.generated_clip import GeneratedClipModel

        clips = (
            (
                await session.execute(
                    select(GeneratedClipModel).where(
                        GeneratedClipModel.project_id == uuid_module.UUID(project_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    statuses = sorted(c.status for c in clips)
    assert statuses == ["completed", "rejected"]  # the violated attempt still billed and recorded
    rejected = next(c for c in clips if c.status == "rejected")
    assert rejected.local_path is None  # never written to disk, never shipped
    completed = next(c for c in clips if c.status == "completed")
    assert completed.id == binding.clip_id

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        spent = await clip_repo.total_cost_cents_for_project(uuid_module.UUID(project_id))
    assert spent == 2 * settings.fal_image_cost_cents_estimate  # both attempts billed


async def test_second_violation_retries_with_a_varied_seed(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    image_provider = _FakeImageProvider(
        results=[
            ImageResult(content=_png_bytes((1, 1, 1)), content_type="image/png"),
            ImageResult(content=_png_bytes((2, 2, 2)), content_type="image/png"),
            ImageResult(content=_png_bytes((3, 3, 3)), content_type="image/png"),
        ]
    )
    verdict = ConstraintVerdict(
        violated=True, violated_constraint="no Nazi symbols", reason="a swastika is visible"
    )
    vision_provider = FakeVisionConstraintProvider(
        verdicts=[
            verdict,
            verdict,
            ConstraintVerdict(violated=False, violated_constraint="", reason=""),
        ]
    )
    _patch_providers(
        monkeypatch,
        image_provider=image_provider,
        video_provider=_FakeVideoProvider(),
        vision_provider=vision_provider,
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"

    assert len(image_provider.calls) == 3  # attempt 0, 1 (same seed), 2 (varied seed)
    first, second, third = image_provider.calls
    assert first.seed == second.seed  # A13: attempt 1 keeps the project's fixed seed
    assert third.seed != first.seed  # A13: attempt 2 varies it - the second, later lever
    assert first.seed == _project_seed(project_id)


async def test_third_violation_marks_the_shot_failed_and_never_ships(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    image_provider = _FakeImageProvider(
        results=[
            ImageResult(content=_png_bytes((1, 1, 1)), content_type="image/png"),
            ImageResult(content=_png_bytes((2, 2, 2)), content_type="image/png"),
            ImageResult(content=_png_bytes((3, 3, 3)), content_type="image/png"),
        ]
    )
    verdict = ConstraintVerdict(
        violated=True, violated_constraint="no Nazi symbols", reason="a swastika is visible"
    )
    vision_provider = FakeVisionConstraintProvider(verdicts=[verdict])  # always violated
    _patch_providers(
        monkeypatch,
        image_provider=image_provider,
        video_provider=_FakeVideoProvider(),
        vision_provider=vision_provider,
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "failed"  # A14/A19: terminal fallback is a human, never a silent ship
    assert binding.clip_id is None
    assert "no Nazi symbols" in binding.last_error

    assert len(image_provider.calls) == 3  # hard cap - never a fourth attempt

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.generated_clip import GeneratedClipModel

        clips = (
            (
                await session.execute(
                    select(GeneratedClipModel).where(
                        GeneratedClipModel.project_id == uuid_module.UUID(project_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(clips) == 3
    assert all(c.status == "rejected" for c in clips)  # nothing ever marked completed

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        spent = await clip_repo.total_cost_cents_for_project(uuid_module.UUID(project_id))
    assert spent == 3 * settings.fal_image_cost_cents_estimate  # every attempt still billed


async def test_video_keyframe_is_checked_not_the_final_clip(project_id, monkeypatch):
    """A12's own framing: 'check the keyframe, not the clip'."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.VIDEO)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    image_provider = _FakeImageProvider(
        results=[
            ImageResult(
                content=b"rejected-keyframe",
                content_type="image/jpeg",
                hosted_url="http://fal.example/rejected.jpg",
            ),
            ImageResult(
                content=b"good-keyframe",
                content_type="image/jpeg",
                hosted_url="http://fal.example/good.jpg",
            ),
        ]
    )
    vision_provider = FakeVisionConstraintProvider(
        verdicts=[
            ConstraintVerdict(
                violated=True, violated_constraint="no Nazi symbols", reason="a swastika is visible"
            ),
            ConstraintVerdict(violated=False, violated_constraint="", reason=""),
        ]
    )
    video_provider = _FakeVideoProvider(submit_job_id="job-checked")
    _patch_providers(
        monkeypatch,
        image_provider=image_provider,
        video_provider=video_provider,
        vision_provider=vision_provider,
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "pending"  # fresh video submission - not terminal yet

    assert len(image_provider.calls) == 2  # the rejected keyframe attempt, then the good one
    # The video job was only ever submitted with the PASSING keyframe's URL -
    # the rejected keyframe never reached Kling.
    assert len(video_provider.submit_calls) == 1
    assert video_provider.submit_calls[0].image_url == "http://fal.example/good.jpg"

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.generated_clip import GeneratedClipModel

        clips = (
            (
                await session.execute(
                    select(GeneratedClipModel).where(
                        GeneratedClipModel.project_id == uuid_module.UUID(project_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    # One rejected keyframe row (billed on its own) plus one submitted video
    # row (which bundles the passing keyframe's cost - see
    # `_generate_checked_keyframe`'s docstring for why that one isn't a
    # separate row).
    assert sorted(c.status for c in clips) == ["rejected", "submitted"]


async def test_resume_from_a_rejected_attempt_does_not_regenerate_or_rebill(
    project_id, monkeypatch
):
    """The real defect a live review caught: an earlier version of this
    retry loop only short-circuited on a `status == "completed"` cache
    hit, so a resumed run whose attempt 0 was already recorded as
    `"rejected"` would regenerate AND re-check it - paying twice for the
    same attempt while recording the cost only once (or, depending on
    exactly where a resume lands, not at all). A rejected attempt must be
    recognised from its cached row and skipped entirely - no fresh
    `image_provider.generate` call, no fresh vision check, no new billing
    - advancing straight to the next attempt using the constraint it
    already violated."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    project_seed = _project_seed(project_id)
    attempt_0_hash = hashlib.sha256(
        f"a coal mine|{settings.fal_image_model}|{project_seed}".encode()
    ).hexdigest()

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        await clip_repo.insert(
            project_id=uuid_module.UUID(project_id),
            shot_id="sh_01",
            provider="fal_image",
            model_id=settings.fal_image_model,
            prompt="a coal mine",
            prompt_hash=attempt_0_hash,
            duration_s=None,
            local_path=None,
            cost_cents=settings.fal_image_cost_cents_estimate,
            status="rejected",
            violated_constraint="no Nazi symbols",
            error="violated constraint 'no Nazi symbols': a swastika is visible",
        )
        await session.commit()

    # Only ONE canned result - if attempt 0 were wrongly regenerated, this
    # provider would be asked for a second image it doesn't have.
    image_provider = _FakeImageProvider(
        results=[ImageResult(content=_png_bytes((9, 9, 9)), content_type="image/png")]
    )
    # Only ONE verdict needed for the same reason - attempt 0's verdict is
    # recovered from the cached row, never re-requested from the vision
    # model.
    vision_provider = FakeVisionConstraintProvider(
        verdicts=[ConstraintVerdict(violated=False, violated_constraint="", reason="")]
    )
    _patch_providers(
        monkeypatch,
        image_provider=image_provider,
        video_provider=_FakeVideoProvider(),
        vision_provider=vision_provider,
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"

    assert len(image_provider.calls) == 1  # attempt 0 was NOT regenerated
    assert len(vision_provider.calls) == 1  # attempt 0 was NOT re-checked
    only_call = image_provider.calls[0]
    assert only_call.seed == project_seed  # still the first-lever seed
    assert "no Nazi symbols" in only_call.prompt  # revised using the recovered constraint

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        spent = await clip_repo.total_cost_cents_for_project(uuid_module.UUID(project_id))
    # The pre-seeded rejected row's cost, plus exactly one fresh attempt -
    # never double-billed for attempt 0, never silently un-billed either.
    assert spent == 2 * settings.fal_image_cost_cents_estimate


async def test_a_lower_configured_attempt_cap_still_varies_the_seed(project_id, monkeypatch):
    """The regression a live review caught in the switchover logic: a
    hardcoded `attempt < 2` check is correct only at the default cap of
    3 - configuring the cap down to 2 must not silently disable the
    varied-seed lever."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "max_generation_attempts_per_shot", 2)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    image_provider = _FakeImageProvider(
        results=[
            ImageResult(content=_png_bytes((1, 1, 1)), content_type="image/png"),
            ImageResult(content=_png_bytes((2, 2, 2)), content_type="image/png"),
        ]
    )
    vision_provider = FakeVisionConstraintProvider(
        verdicts=[
            ConstraintVerdict(
                violated=True, violated_constraint="no Nazi symbols", reason="a swastika is visible"
            ),
            ConstraintVerdict(violated=False, violated_constraint="", reason=""),
        ]
    )
    _patch_providers(
        monkeypatch,
        image_provider=image_provider,
        video_provider=_FakeVideoProvider(),
        vision_provider=vision_provider,
    )

    await _run_step(project_id)

    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"

    assert len(image_provider.calls) == 2  # the full (smaller) cap was available
    first, second = image_provider.calls
    project_seed = _project_seed(project_id)
    assert first.seed == project_seed
    # With only 2 total attempts allowed, attempt 1 IS the last attempt -
    # the varied-seed lever must fire here, not silently stay on the
    # project seed.
    assert second.seed != project_seed
