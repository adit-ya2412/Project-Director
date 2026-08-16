"""ResolveAssetsStep's real generation path (M7): image generation
(bounded synchronous poll), video generation (submit-and-poll, resumable
across a simulated crash), the generation cache (rung 0), and the budget
cap. Director-constraint enforcement (a vision check, bounded
regeneration on a violation, formerly A12/A13/A18, a terminal `failed`
binding naming the constraint once every attempt is exhausted, A14/A19)
was REMOVED from IMAGE generation in the M6.5 -> gate redesign
(2026-08-16) - a human at the one review gate is the check now, see
`test_image_generation_never_checks_director_constraints_even_when_configured`
below - but remains FULLY INTACT for VIDEO generation (out of scope for
that redesign; `test_video_keyframe_is_checked_not_the_final_clip` is
unchanged and still proves it). No real fal.ai/OpenAI call:
`FalImageProvider`/`FalVideoProvider`/`OpenAIPlanningProvider` are
monkeypatched to fakes with canned responses, the same pattern used for
the M5 planners and the M6 search providers.
"""

import hashlib
import io
import uuid as uuid_module

import pytest_asyncio
from PIL import Image

from app.assets.constraint_check import varied_seed
from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.base import ConstraintVerdict, ImageResult, VideoJobStatus
from app.providers.fakes.vision import FakeVisionConstraintProvider
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    CreativeContext,
    PreferredMediaType,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
)
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps import resolve_assets as resolve_assets_module
from app.workflow.steps.resolve_assets import (
    GENERATION_RUNGS,
    ResolveAssetsStep,
    _project_seed,
    generate_image_real,
)


def _generation_step() -> ResolveAssetsStep:
    return ResolveAssetsStep(name="resolve_assets_generate", permitted_strategies=GENERATION_RUNGS)


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
        result = await _generation_step().run(ctx)
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
    # Task 3 (2026-08-16): the seed folds in how many `GeneratedClip` rows
    # already exist for THIS shot (`GeneratedClipRepository.count_for_shot`).
    # This test pre-seeds ONE row below, BEFORE the real step ever runs -
    # so by the time `_generate_image_once` computes its own seed,
    # `count_for_shot` already reads 1 (the row inserted here), and it
    # derives `varied_seed(project_seed, 1)`, not the bare project seed.
    # The pre-seeded row's `prompt_hash` has to be computed identically,
    # or this test would prove nothing - a seed mismatch would silently
    # MISS the cache and generate afresh, rather than exercising the
    # cache-hit path this test is named for.
    seed = varied_seed(_project_seed(project_id), 1)
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


async def test_image_generation_never_checks_director_constraints_even_when_configured(
    project_id, monkeypatch
):
    """M6.5 -> gate redesign (2026-08-16): the Director-constraint vision
    check and its bounded retry loop (formerly A12/A13/A18) were REMOVED
    from IMAGE generation - a human at the one review gate is the check
    now, not an automated vision call that could kill a legitimate shot
    on a false positive (the real failure that motivated the removal: a
    documentary's German tanks bearing insignia, rejected outright with
    no human ever seeing the image or the objection - see
    docs/13_Implementation_Guide.md's F5a). `generate_image_real` (which
    `_resolve_one_real` now calls for every image shot) takes no
    `vision_provider`/`constraints` at all - this proves the negative
    end to end, not just by inspecting the signature: even with
    `creative_context.constraints` non-empty and a real vision provider
    configured that would flag EVERY image as violating them, generation
    still ships on the FIRST attempt, at the project's fixed seed, and
    the vision provider is never consulted. (`test_dry_run_never_
    constructs_a_vision_provider`/`test_empty_constraints_makes_zero_
    vision_calls` above cover the two cheaper "obviously no call" cases -
    this is the one case those do not: a vision provider that WOULD
    object, constraints that ARE configured, and still no check, because
    the code path to call it no longer exists for images.) The retry-
    loop-specific tests this replaces (one retry same seed, a second
    violation varying the seed, a third exhausting the cap into
    `failed`) all asserted mechanism that no longer exists in the image
    path; `test_video_keyframe_is_checked_not_the_final_clip` below is
    the still-valid, still-untouched proof that the identical mechanism
    remains fully intact for VIDEO generation, which this task does not
    touch.
    """
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot], constraints=["no Nazi symbols"])

    image_provider = _FakeImageProvider(
        results=[ImageResult(content=_png_bytes(), content_type="image/png")]
    )
    vision_provider = FakeVisionConstraintProvider(
        verdicts=[
            ConstraintVerdict(
                violated=True, violated_constraint="no Nazi symbols", reason="a swastika is visible"
            )
        ]
    )  # would fail the shot immediately if ever actually consulted
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

    assert len(image_provider.calls) == 1  # exactly one attempt - no retry loop
    assert image_provider.calls[0].seed == _project_seed(project_id)
    assert vision_provider.calls == []  # never consulted at all for images

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        spent = await clip_repo.total_cost_cents_for_project(uuid_module.UUID(project_id))
    assert spent == settings.fal_image_cost_cents_estimate  # exactly one attempt billed


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


async def test_repeated_explicit_generation_varies_the_seed_and_produces_a_new_clip(
    project_id, monkeypatch
):
    """Task 3 (2026-08-16): `POST /shots/{id}/generate` calls
    `generate_image_real` directly, OUTSIDE `ResolveAssetsStep`'s own
    once-per-shot-per-run loop - a human sitting at the one review gate
    may click "generate" on the SAME shot, with the SAME prompt, more
    than once, and expect a genuinely different picture each time, not
    the identical, free, first result served back from the cache
    (unchanged prompt + unchanged seed = unchanged `prompt_hash`). The
    seed now folds in `GeneratedClipRepository.count_for_shot` - this
    proves both halves: the FIRST call still lands on the bare project
    seed unchanged (preserving the ordinary "generate once" cache/dedup
    behaviour `test_generation_cache_hit_skips_a_fresh_call` above
    depends on), and the SECOND call on the same shot varies it, via a
    real, fresh call to the image provider (never a cache hit) at a
    DIFFERENT `prompt_hash`, producing a genuinely new `GeneratedClip`
    row."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", preferred_type=PreferredMediaType.IMAGE)
    await _seed_timeline(project_id, [shot])

    image_provider = _FakeImageProvider(
        results=[
            ImageResult(content=_png_bytes((1, 1, 1)), content_type="image/png"),
            ImageResult(content=_png_bytes((2, 2, 2)), content_type="image/png"),
        ]
    )
    project_uuid = uuid_module.UUID(project_id)
    project_seed = _project_seed(project_id)
    project_dir = settings.storage_root / project_id
    (project_dir / "clips").mkdir(parents=True, exist_ok=True)

    async def _generate_once():
        async with async_session_factory() as session:
            binding = await ShotBindingRepository(session).get_or_create_pending(
                project_uuid, 2, "sh_01"
            )
            clip, cache_hit = await generate_image_real(
                shot,
                binding,
                project_uuid=project_uuid,
                project_dir=project_dir,
                image_provider=image_provider,
                clip_repo=GeneratedClipRepository(session),
                narration_repo=NarrationRepository(session),
                creative_context=CreativeContext(),
            )
            await session.commit()
        return clip, cache_hit

    first_clip, first_cache_hit = await _generate_once()
    assert first_cache_hit is False
    assert image_provider.calls[0].seed == project_seed

    second_clip, second_cache_hit = await _generate_once()
    assert second_cache_hit is False  # a genuine second generation, not a replay
    assert second_clip.id != first_clip.id
    assert len(image_provider.calls) == 2  # both attempts really hit the provider
    assert image_provider.calls[1].seed != project_seed  # varied, not repeated

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        spent = await clip_repo.total_cost_cents_for_project(project_uuid)
        count = await clip_repo.count_for_shot(project_uuid, "sh_01")
    assert spent == 2 * settings.fal_image_cost_cents_estimate  # both attempts billed
    assert count == 2
