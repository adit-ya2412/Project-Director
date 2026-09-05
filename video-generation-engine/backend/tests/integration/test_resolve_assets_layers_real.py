"""F2b (illustrated_faceless.md §8.5, 2026-09-05): `ResolveAssetsStep`
actually resolving `Shot.layers` to real generated images - the DB-backed
half of F2b's own generation path that `tests/unit/workflow/
test_layer_generation.py`'s pure-function tests cannot exercise (budget
check, clip repository, content hashing). Mirrors
`test_resolve_assets_generation_real.py`'s own shape exactly: no real
fal.ai call, `FalImageProvider` monkeypatched to a fake with canned
responses, a real Postgres project/timeline seeded per test (never
truncated - see `conftest.py`).
"""

import io
import uuid as uuid_module

import pytest_asyncio
from PIL import Image

from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.base import ImageResult
from app.providers.fakes.vision import FakeVisionConstraintProvider
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    CreativeContext,
    LayerRole,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
)
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.steps import resolve_assets as resolve_assets_module
from app.workflow.steps.resolve_assets import GENERATION_RUNGS, ResolveAssetsStep, layer_prompt_hash


def _generation_step() -> ResolveAssetsStep:
    return ResolveAssetsStep(name="resolve_assets_generate", permitted_strategies=GENERATION_RUNGS)


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("resolve-assets-layers-test")
        return project.id


def _parallax_shot(shot_id: str = "sh_01") -> Shot:
    from app.schemas.timeline import Camera, CameraMovement

    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=4.0,
        prompt="a quiet room",
        camera=Camera(movement=CameraMovement.PARALLAX),
        layers=[
            ShotLayer(role=LayerRole.BACKGROUND, prompt="an empty room"),
            ShotLayer(role=LayerRole.SUBJECT, prompt="a seated figure on a magenta field"),
        ],
    )


class _FixedSizeFakeImageProvider:
    """Returns a canned PNG regardless of the requested size - matches
    `test_resolve_assets_generation_real.py`'s own fake exactly, for
    tests that don't care about F1a's crop."""

    name = "fal_image"

    def __init__(self, colour: tuple[int, int, int] = (10, 20, 30)) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (1080, 1920), color=colour).save(buffer, format="PNG")
        self._content = buffer.getvalue()
        self.calls: list = []

    async def generate(self, request):
        self.calls.append(request)
        return ImageResult(content=self._content, content_type="image/png")


class _RequestSizedFakeImageProvider:
    """Returns a PNG at EXACTLY the requested width/height, like a real
    provider does - needed to prove F1a's oversize+crop actually applies
    to a layer image end to end (the crop only does anything when the
    delivered bytes really are the oversized size that was asked for)."""

    name = "fal_image"

    def __init__(self) -> None:
        self.calls: list = []

    async def generate(self, request):
        self.calls.append(request)
        buffer = io.BytesIO()
        Image.new("RGB", (request.width, request.height), color=(50, 60, 70)).save(
            buffer, format="PNG"
        )
        return ImageResult(content=buffer.getvalue(), content_type="image/png")


class _UnusedFakeVideoProvider:
    """Never actually called by any test in this file (every shot here
    is an image) - `ResolveAssetsStep._resolve_one_real`'s own
    `assert image_provider is not None and video_provider is not None`
    still requires a real object here regardless, mirroring
    `test_resolve_assets_generation_real.py`'s own `_FakeVideoProvider`."""

    name = "fal_video"

    async def submit(self, request):
        raise AssertionError("not exercised by this test file")

    async def poll(self, job_id):
        raise AssertionError("not exercised by this test file")


def _patch_providers(monkeypatch, *, image_provider) -> None:
    monkeypatch.setattr(resolve_assets_module, "FalImageProvider", lambda: image_provider)
    monkeypatch.setattr(resolve_assets_module, "FalVideoProvider", _UnusedFakeVideoProvider)
    monkeypatch.setattr(
        resolve_assets_module, "OpenAIPlanningProvider", lambda: FakeVisionConstraintProvider()
    )


async def _seed_timeline(
    project_id: str, shots: list[Shot], *, render_style: str | None = None
) -> None:
    scene = Scene(
        id="sc_01", order=0, title="Scene", duration_s=sum(s.duration_s for s in shots), shots=shots
    )
    async with async_session_factory() as session:
        service = TimelineService(session)
        await service.create_initial(project_id, script="a script")

        def _fill(base):
            base.scenes = [scene]
            base.creative_context = CreativeContext()
            if render_style is not None:
                base.metadata.render_style = render_style
            return base

        await service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_fill,
            owns=frozenset({"scenes", "creative_context", "metadata"}),
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


async def _spend(project_id: str) -> int:
    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        return await clip_repo.total_cost_cents_for_project(uuid_module.UUID(project_id))


async def test_both_layers_generate_as_separate_billed_clips(project_id, monkeypatch):
    """§4.3: layers are paid generations and must be counted like any
    other - the shot's own primary image PLUS its two layers, three
    separate charges (never a free or uncounted side channel for the
    layers)."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _parallax_shot()
    await _seed_timeline(project_id, [shot])
    image_provider = _FixedSizeFakeImageProvider()
    _patch_providers(monkeypatch, image_provider=image_provider)

    await _run_step(project_id)

    assert len(image_provider.calls) == 3  # primary + background + subject
    assert await _spend(project_id) == 3 * settings.fal_image_cost_cents_estimate

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        for index, layer in enumerate(shot.layers):
            phash = layer_prompt_hash(
                shot,
                layer,
                layer_index=index,
                project_uuid=uuid_module.UUID(project_id),
                creative_context=CreativeContext(),
            )
            clip = await clip_repo.get_by_prompt_hash(phash)
            assert clip is not None
            assert clip.local_path is not None


async def test_a_second_run_is_a_free_cache_hit_not_a_second_charge(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _parallax_shot()
    await _seed_timeline(project_id, [shot])
    image_provider = _FixedSizeFakeImageProvider()
    _patch_providers(monkeypatch, image_provider=image_provider)

    await _run_step(project_id)
    first_spend = await _spend(project_id)
    await _run_step(project_id)
    second_spend = await _spend(project_id)

    assert first_spend == 3 * settings.fal_image_cost_cents_estimate
    assert second_spend == first_spend  # no re-charge on an already-cached layer


async def test_budget_cap_stops_the_second_layer_and_isolates_the_shot(project_id, monkeypatch):
    """The §4.3 cap becomes LIVE (illustrated_faceless.md §8.5): once a
    layer generation is a real charge, `check_budget` gates it exactly
    like any other paid generation. The cap here leaves room for exactly
    the shot's own primary image plus its background layer (2x the
    per-image estimate) - the subject layer is what pushes past it, and
    that failure is isolated to the layer (never the whole shot, never
    the whole step)."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(
        settings, "project_budget_cap_cents", 2 * settings.fal_image_cost_cents_estimate
    )
    shot = _parallax_shot()
    await _seed_timeline(project_id, [shot])
    image_provider = _FixedSizeFakeImageProvider()
    _patch_providers(monkeypatch, image_provider=image_provider)

    await _run_step(project_id)  # must not raise - the cap failure is caught, not propagated

    assert await _spend(project_id) == 2 * settings.fal_image_cost_cents_estimate
    assert len(image_provider.calls) == 2  # primary + background; subject blocked before its call

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        bg_hash = layer_prompt_hash(
            shot,
            shot.layers[0],
            layer_index=0,
            project_uuid=uuid_module.UUID(project_id),
            creative_context=CreativeContext(),
        )
        subject_hash = layer_prompt_hash(
            shot,
            shot.layers[1],
            layer_index=1,
            project_uuid=uuid_module.UUID(project_id),
            creative_context=CreativeContext(),
        )
        assert await clip_repo.get_by_prompt_hash(bg_hash) is not None
        assert await clip_repo.get_by_prompt_hash(subject_hash) is None


async def test_dry_run_layers_are_free_and_still_cached(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    shot = _parallax_shot()
    await _seed_timeline(project_id, [shot])
    # DRY_RUN never constructs FalImageProvider - ResolveAssetsStep uses
    # FakeImageProvider internally, no patching needed here at all.

    await _run_step(project_id)

    assert await _spend(project_id) == 0
    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        for index, layer in enumerate(shot.layers):
            phash = layer_prompt_hash(
                shot,
                layer,
                layer_index=index,
                project_uuid=uuid_module.UUID(project_id),
                creative_context=CreativeContext(),
            )
            clip = await clip_repo.get_by_prompt_hash(phash)
            assert clip is not None
            assert clip.cost_cents == 0


async def test_f1a_crop_applies_to_layer_images_too(project_id, monkeypatch):
    """F1a's own explicit ask: a subject layer's margin is the WORSE case
    (colorkey will not remove off-white, it composites as a pale
    rectangle INSIDE the frame) - so the crop must apply to layers, not
    only the shot's own primary image. Proven here by actually running
    layer generation for a `GENERATION_ONLY` style against a provider
    that honours the requested (oversized) size, then checking the
    PERSISTED file is exactly the canvas size, not the oversized request."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _parallax_shot()
    await _seed_timeline(project_id, [shot], render_style="illustrated_risograph")
    image_provider = _RequestSizedFakeImageProvider()
    _patch_providers(monkeypatch, image_provider=image_provider)

    await _run_step(project_id)

    assert len(image_provider.calls) == 3  # primary + background + subject
    # Every request (primary AND both layers) asked for something LARGER
    # than the canvas - F1a applies to the shot's own image too.
    for call in image_provider.calls:
        assert call.width > 720
        assert call.height > 1280

    async with async_session_factory() as session:
        clip_repo = GeneratedClipRepository(session)
        for index, layer in enumerate(shot.layers):
            phash = layer_prompt_hash(
                shot,
                layer,
                layer_index=index,
                project_uuid=uuid_module.UUID(project_id),
                creative_context=CreativeContext(),
                style="illustrated_risograph",
            )
            clip = await clip_repo.get_by_prompt_hash(phash)
            assert clip is not None
            assert clip.local_path is not None
            with Image.open(clip.local_path) as persisted:
                # Persisted bytes are exactly the canvas the rest of the
                # pipeline expects - never the oversized request size.
                assert persisted.size == (720, 1280)
