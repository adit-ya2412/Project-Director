"""The search-only `ResolveAssetsStep` pass (`resolve_assets_search`,
rungs 1-4 - M6.5, A5/A21) with DRY_RUN=false: proves the real-search
path's hardest rules - the licence hard gate, content-hash dedup before
ranking, the within-project reuse penalty, complete provenance on stored
assets, deferring to the paid pass (`awaiting_generation`, never
generating directly - A6) when every permitted rung comes up empty, and
a total provider failure still returning a clean step outcome rather
than blocking the approval gate (A22).

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
from app.workflow.steps.resolve_assets import SEARCH_RUNGS, ResolveAssetsStep


def _search_step() -> ResolveAssetsStep:
    return ResolveAssetsStep(name="resolve_assets_search", permitted_strategies=SEARCH_RUNGS)


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


class _RaisingSearchProvider:
    """A22: stands in for a search rung that is entirely down (e.g.
    Wikimedia unreachable) - every call raises, never returns."""

    name = "wikimedia"
    rung = "historical_search"

    async def search(self, query):
        raise RuntimeError("simulated total provider outage")

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        raise RuntimeError("simulated total provider outage")


def _patch_providers(monkeypatch, historical_provider) -> None:
    monkeypatch.setattr(
        resolve_assets_module,
        "_real_search_providers",
        lambda: {AssetStrategy.HISTORICAL_SEARCH: historical_provider},
    )
    # `run()` unconditionally constructs an `OpenAIPlanningProvider()` for
    # M6.5's vision constraint check whenever the pass permits generation
    # and DRY_RUN is off - the search-only pass never permits generation
    # (`self._generation_permitted` is False), so it never even
    # constructs one; this patch is kept anyway as a defensive guard
    # against that assumption ever quietly changing, so this suite stays
    # genuinely key-independent rather than "working" only because a real
    # key happens to be set in a developer's local .env.
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
        result = await _search_step().run(ctx)
        assert result.outcome == "ok"
        await session.commit()


async def _binding(project_id: str, shot_id: str):
    async with async_session_factory() as session:
        repo = ShotBindingRepository(session)
        return await repo.get(uuid_module.UUID(project_id), 2, shot_id)


async def test_licence_gate_rejects_non_matching_candidate_and_defers_to_generation(
    project_id, monkeypatch
):
    """M6.5, A5/A6/A21: this is the search-ONLY pass - it must never
    generate, even as a fallback. A licence-rejected candidate defers the
    shot to the paid pass (`awaiting_generation`), which is the intended
    behaviour change from the pre-reorder single-pass step (which used to
    fall all the way through to a real `generate_image` call here)."""
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
    assert binding.state == "awaiting_generation"  # licence-rejected -> deferred, not generated
    assert binding.asset_id is None
    assert binding.clip_id is None


async def test_relevance_gate_rejects_non_matching_candidate_and_defers_to_generation(
    project_id, monkeypatch
):
    """The real defect this fixes: a candidate with an acceptable licence
    but no genuine connection to the shot's search query (the actual title
    of a real wrong match from production) must be discarded before it is
    ever stored - exactly like the licence gate above, not merely
    deprioritised in ranking. Deferred to the paid pass, same as the
    licence-gate case - the search-only pass never generates."""
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
    assert binding.state == "awaiting_generation"  # relevance-rejected -> deferred, not generated
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


async def test_defers_to_generation_when_every_rung_is_empty(project_id, monkeypatch):
    """M6.5, A5/A6: the search-only pass never generates - a shot every
    permitted rung came up empty for is left `awaiting_generation` for the
    paid pass to pick up after approval, not silently generated here."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot])

    provider = _FakeSearchProvider(
        "wikimedia", "historical_search", candidates_by_shot={}, content_by_source_id={}
    )
    _patch_providers(monkeypatch, provider)

    await _run_step(project_id)
    binding = await _binding(project_id, "sh_01")
    assert binding.state == "awaiting_generation"
    assert binding.clip_id is None
    assert binding.asset_id is None


async def test_total_search_provider_failure_never_blocks_the_gate(project_id, monkeypatch):
    """A22: a total failure of the pre-approval search pass must not
    block the approval gate. Every call to the only permitted rung raises
    - the step must still return outcome="ok" (per-shot isolation,
    Principle 10), not propagate the exception and fail the whole run."""
    monkeypatch.setattr(settings, "dry_run", False)
    shot = _shot("sh_01", licence_requirements=["cc0"])
    await _seed_timeline(project_id, [shot])

    _patch_providers(monkeypatch, _RaisingSearchProvider())

    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        ctx = RunContext(
            project_id=project_id,
            session=session,
            repo=repo,
            timeline_service=TimelineService(session),
        )
        result = await _search_step().run(ctx)
        await session.commit()

    # The step itself completes cleanly - this is what lets the engine
    # proceed straight to the approval gate regardless of how badly
    # search went, exactly like a licence/relevance rejection or an empty
    # rung: never a step-level failure, only ever a per-shot one.
    assert result.outcome == "ok"

    binding = await _binding(project_id, "sh_01")
    # A generic (non-Transient) exception from every rung marks the ONE
    # shot failed - it does not propagate up and fail the whole pass, and
    # it does not silently invent a resolved/generated asset either.
    assert binding.state == "failed"
    assert binding.asset_id is None
    assert binding.clip_id is None
