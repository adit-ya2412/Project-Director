"""ResolveAssetsStep with DRY_RUN=false: proves the real-search path's
hardest rules - the licence hard gate, content-hash dedup before ranking,
the within-project reuse penalty, complete provenance on stored assets,
and falling through to (fake) generation when every rung comes up empty.

No real network: the ladder's provider routing table
(`_real_search_providers`) is monkeypatched to fakes with canned
candidates - this tests the step's own ladder-walking, gating, dedup, and
ranking logic, not Wikimedia/Pexels's HTTP behaviour (that's covered by
the MockTransport-based provider tests instead).
"""

import io
import uuid as uuid_module

import pytest_asyncio
from PIL import Image

from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.base import AssetBytes, AssetCandidate
from app.providers.fakes.vision import FakeVisionConstraintProvider
from app.repositories.asset_repository import AssetRepository
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
        project = await repo.create("resolve-assets-real-test")
        return project.id


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (1080, 1920)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _shot(shot_id: str, *, licence_requirements: list[str], prompt: str = "a shot") -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt=prompt,
        asset_plan=AssetPlan(
            strategy=AssetStrategy.HISTORICAL_SEARCH,
            search_queries=["archival photo"],
            preferred_type=PreferredMediaType.IMAGE,
            fallback_chain=[AssetStrategy.HISTORICAL_SEARCH, AssetStrategy.GENERATE_IMAGE],
            licence_requirements=licence_requirements,
        ),
    )


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


class _FakeGenerationImageProvider:
    """Stands in for FalImageProvider (M7) - these tests are about the
    search/ladder path, not real generation; a real network call here
    would 404 (no fal.ai account is wired into tests)."""

    name = "fake_fal_image"

    async def generate(self, request):
        from app.providers.base import ImageResult

        return ImageResult(content=_png_bytes((1, 2, 3)), content_type="image/png")


class _FakeSearchProvider:
    def __init__(
        self,
        name: str,
        rung: str,
        candidates_by_shot: dict[str, list[AssetCandidate]],
        content_by_source_id: dict[str, bytes],
    ) -> None:
        self.name = name
        self.rung = rung
        self._candidates_by_shot = candidates_by_shot
        self._content_by_source_id = content_by_source_id

    async def search(self, query):
        return self._candidates_by_shot.get(query.shot_id, [])

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        return AssetBytes(
            content=self._content_by_source_id[candidate.source_id],
            content_type="image/png",
            attribution=f"attribution for {candidate.source_id}",
        )


def _patch_providers(monkeypatch, historical_provider) -> None:
    monkeypatch.setattr(
        resolve_assets_module,
        "_real_search_providers",
        lambda: {AssetStrategy.HISTORICAL_SEARCH: historical_provider},
    )
    monkeypatch.setattr(resolve_assets_module, "FalImageProvider", _FakeGenerationImageProvider)
    # `run()` unconditionally constructs an `OpenAIPlanningProvider()` for
    # M6.5's vision constraint check whenever DRY_RUN is off, even though
    # none of these shots set `creative_context.constraints` (so it's
    # never actually called - M6.5, A12, "zero constraints, zero calls").
    # A real `OpenAIPlanningProvider()`'s constructor itself requires an
    # API key to be configured, though, so this suite must patch it too
    # to stay genuinely key-independent rather than only "working" because
    # a real key happens to be set in a developer's local .env.
    monkeypatch.setattr(
        resolve_assets_module, "OpenAIPlanningProvider", FakeVisionConstraintProvider
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


async def test_licence_gate_rejects_non_matching_candidate_and_falls_back_to_generation(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot])

    provider = _FakeSearchProvider(
        "wikimedia",
        "historical_search",
        candidates_by_shot={
            "sh_01": [
                AssetCandidate(
                    source_id="a1",
                    source_url="http://example.test/a1",
                    title="a photo",
                    licence="cc_by",  # does not satisfy the shot's ["cc0"] requirement
                    relevance=1.0,
                    width=1080,
                    height=1920,
                )
            ]
        },
        content_by_source_id={"a1": _png_bytes((10, 20, 30))},
    )
    _patch_providers(monkeypatch, provider)

    await _run_step(project_id)
    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"  # licence-rejected -> fell through to generation
    assert binding.asset_id is None


async def test_relevance_gate_rejects_non_matching_candidate_and_falls_back_to_generation(
    project_id, monkeypatch
):
    """The real defect this fixes: a candidate with an acceptable licence
    but no genuine connection to the shot's search query (the actual title
    of a real wrong match from production) must be discarded before it is
    ever stored - exactly like the licence gate above, not merely
    deprioritised in ranking."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot])

    provider = _FakeSearchProvider(
        "wikimedia",
        "historical_search",
        candidates_by_shot={
            "sh_01": [
                AssetCandidate(
                    source_id="a1",
                    source_url="http://example.test/a1",
                    title="Cristo_crucificado.jpg",  # a real wrong match - unrelated subject
                    licence="cc0",  # licence is fine; relevance is what must reject this
                    relevance=1.0,  # the old, meaningless rank-position field
                    width=1080,
                    height=1920,
                )
            ]
        },
        content_by_source_id={"a1": _png_bytes((10, 20, 30))},
    )
    _patch_providers(monkeypatch, provider)

    await _run_step(project_id)
    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"  # relevance-rejected -> fell through to generation
    assert binding.asset_id is None


async def test_content_hash_dedup_collapses_duplicate_candidates(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot])

    same_bytes = _png_bytes((40, 50, 60))
    provider = _FakeSearchProvider(
        "wikimedia",
        "historical_search",
        candidates_by_shot={
            "sh_01": [
                AssetCandidate(
                    source_id="dupe-a",
                    source_url="http://example.test/dupe-a",
                    title="archival image, url A",
                    licence="cc0",
                    relevance=0.9,
                    width=1080,
                    height=1920,
                ),
                AssetCandidate(
                    source_id="dupe-b",
                    source_url="http://example.test/dupe-b",
                    title="archival image, url B",
                    licence="cc0",
                    relevance=0.8,
                    width=1080,
                    height=1920,
                ),
            ]
        },
        content_by_source_id={"dupe-a": same_bytes, "dupe-b": same_bytes},
    )
    _patch_providers(monkeypatch, provider)

    await _run_step(project_id)
    binding = await _binding(project_id, "sh_01")
    assert binding.state == "resolved"

    async with async_session_factory() as session:
        asset_repo = AssetRepository(session)
        stored_hashes = await asset_repo.list_content_hashes_for_project(
            uuid_module.UUID(project_id)
        )
    assert len(stored_hashes) == 1  # both candidates hashed to the same asset - one row, not two


async def test_reuse_penalty_avoids_repeating_the_same_asset_across_shots(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot_a = _shot("sh_01", licence_requirements=["cc0"])
    shot_b = _shot("sh_02", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot_a, shot_b])

    popular_bytes = _png_bytes((70, 80, 90))
    fresh_bytes = _png_bytes((100, 110, 120))
    provider = _FakeSearchProvider(
        "wikimedia",
        "historical_search",
        candidates_by_shot={
            "sh_01": [
                AssetCandidate(
                    source_id="popular",
                    source_url="http://example.test/popular",
                    title="archival popular photo",
                    licence="cc0",
                    relevance=1.0,
                    width=1080,
                    height=1920,
                )
            ],
            "sh_02": [
                AssetCandidate(
                    source_id="popular",
                    source_url="http://example.test/popular",
                    title="archival popular photo",
                    licence="cc0",
                    relevance=1.0,
                    width=1080,
                    height=1920,
                ),
                AssetCandidate(
                    source_id="fresh",
                    source_url="http://example.test/fresh",
                    title="archival fresh photo",
                    licence="cc0",
                    relevance=0.5,
                    width=1080,
                    height=1920,
                ),
            ],
        },
        content_by_source_id={"popular": popular_bytes, "fresh": fresh_bytes},
    )
    _patch_providers(monkeypatch, provider)

    await _run_step(project_id)
    binding_a = await _binding(project_id, "sh_01")
    binding_b = await _binding(project_id, "sh_02")

    # Shot B must land on a *different* asset than shot A despite "popular"
    # having the higher raw relevance - the reuse penalty outweighs it.
    assert binding_a.asset_id != binding_b.asset_id


async def test_provenance_is_complete_on_a_stored_asset(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot])

    provider = _FakeSearchProvider(
        "wikimedia",
        "historical_search",
        candidates_by_shot={
            "sh_01": [
                AssetCandidate(
                    source_id="prov",
                    source_url="http://example.test/prov.jpg",
                    title="an archival provenance-complete photo",
                    licence="cc0",
                    relevance=0.9,
                    author="Jane Photographer",
                    width=1080,
                    height=1920,
                )
            ]
        },
        content_by_source_id={"prov": _png_bytes((5, 6, 7))},
    )
    _patch_providers(monkeypatch, provider)

    await _run_step(project_id)
    binding = await _binding(project_id, "sh_01")
    assert binding.state == "resolved"

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.asset import AssetModel

        asset = (
            await session.execute(select(AssetModel).where(AssetModel.id == binding.asset_id))
        ).scalar_one()

    assert asset.source_url == "http://example.test/prov.jpg"
    assert asset.licence == "cc0"
    assert asset.attribution == "attribution for prov"
    assert asset.content_hash
    assert asset.confidence > 0
    assert asset.local_path is not None and asset.local_path.endswith(".png")


async def test_falls_back_to_generation_when_every_rung_is_empty(project_id, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot])

    provider = _FakeSearchProvider(
        "wikimedia", "historical_search", candidates_by_shot={}, content_by_source_id={}
    )
    _patch_providers(monkeypatch, provider)

    await _run_step(project_id)
    binding = await _binding(project_id, "sh_01")
    assert binding.state == "generated"
    assert binding.clip_id is not None
