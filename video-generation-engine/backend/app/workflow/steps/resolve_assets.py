"""Step 3: resolve or generate media for every shot.

DRY_RUN=true: unchanged since M4 - `FakeAssetProvider` always finds
something on the shot's primary strategy, so the fallback chain is never
actually exercised.

DRY_RUN=false (M6): real search across the ladder's search rungs -
`project_assets` (stub, no upload feature yet - always empty),
`historical_search` + `public_domain` (Wikimedia Commons, one provider
serves both), `stock_search` (Pexels) - walking the shot's full
`asset_plan.fallback_chain` in order until a licence-passing candidate
survives. Generation rungs (`generate_video`/`generate_image`) still
route through the fake image provider regardless of DRY_RUN - M7 hasn't
landed real media generation yet, so a real search miss falls through to
the same fake DRY_RUN uses. Real search is image-only for now; a shot
whose `preferred_type` is `video` still only gets real image candidates
(no real video search provider exists yet).

Per-shot failure isolation (Principle 10) is enforced here: one shot
failing marks that binding `failed` and processing continues with the
rest, never aborting the whole step.
"""

import hashlib
import uuid as uuid_module

from app.assets.ranking import rank_candidates
from app.assets.validation import validate_and_identify_image
from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import AssetCandidate, AssetProvider, AssetQuery, ImageRequest
from app.providers.fakes.asset import FakeAssetProvider
from app.providers.fakes.image import FakeImageProvider
from app.providers.local_assets import LocalProjectAssetProvider
from app.providers.pexels import PexelsAssetProvider
from app.providers.wikimedia import WikimediaAssetProvider
from app.repositories.asset_repository import AssetRepository
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.shot_binding_repository import TERMINAL_STATES, ShotBindingRepository
from app.schemas.timeline import AssetStrategy, CreativeContext, Shot
from app.workflow.context import RunContext
from app.workflow.step import StepResult

_SEARCH_STRATEGIES = {
    AssetStrategy.PROJECT_ASSETS,
    AssetStrategy.HISTORICAL_SEARCH,
    AssetStrategy.PUBLIC_DOMAIN,
    AssetStrategy.STOCK_SEARCH,
}
_CANDIDATES_TO_FETCH_PER_RUNG = 5


def _real_search_providers() -> dict[AssetStrategy, AssetProvider]:
    return {
        AssetStrategy.PROJECT_ASSETS: LocalProjectAssetProvider(),
        AssetStrategy.HISTORICAL_SEARCH: WikimediaAssetProvider(rung="historical_search"),
        AssetStrategy.PUBLIC_DOMAIN: WikimediaAssetProvider(rung="public_domain"),
        AssetStrategy.STOCK_SEARCH: PexelsAssetProvider(),
    }


class ResolveAssetsStep:
    name = "resolve_assets"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return False
        binding_repo = ShotBindingRepository(ctx.session)
        bindings = {
            b.shot_id: b
            for b in await binding_repo.list_for_version(
                uuid_module.UUID(ctx.project_id), timeline.version
            )
        }
        shots = timeline.all_shots()
        if len(bindings) < len(shots):
            return False
        return all(bindings[s.id].state in TERMINAL_STATES for s in shots)

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to resolve assets for")

        project_uuid = uuid_module.UUID(ctx.project_id)
        binding_repo = ShotBindingRepository(ctx.session)
        asset_repo = AssetRepository(ctx.session)
        clip_repo = GeneratedClipRepository(ctx.session)

        image_provider = FakeImageProvider()
        project_dir = settings.storage_root / ctx.project_id
        (project_dir / "assets").mkdir(parents=True, exist_ok=True)
        (project_dir / "clips").mkdir(parents=True, exist_ok=True)

        fake_asset_provider = FakeAssetProvider() if settings.dry_run else None
        search_providers = None if settings.dry_run else _real_search_providers()
        already_used_hashes = await asset_repo.list_content_hashes_for_project(project_uuid)

        for shot in timeline.all_shots():
            binding = await binding_repo.get_or_create_pending(
                project_uuid, timeline.version, shot.id
            )
            if binding.state in TERMINAL_STATES:
                continue  # already resolved on a prior attempt/run

            try:
                if settings.dry_run:
                    assert fake_asset_provider is not None
                    await self._resolve_one_fake(
                        shot,
                        binding,
                        project_uuid=project_uuid,
                        project_dir=project_dir,
                        asset_provider=fake_asset_provider,
                        image_provider=image_provider,
                        asset_repo=asset_repo,
                        clip_repo=clip_repo,
                    )
                else:
                    assert search_providers is not None
                    used_hash = await self._resolve_one_real(
                        shot,
                        binding,
                        project_uuid=project_uuid,
                        project_dir=project_dir,
                        search_providers=search_providers,
                        image_provider=image_provider,
                        asset_repo=asset_repo,
                        clip_repo=clip_repo,
                        creative_context=timeline.creative_context,
                        already_used_hashes=already_used_hashes,
                    )
                    if used_hash is not None:
                        already_used_hashes.add(used_hash)
            except TransientError as exc:
                # Leave state as "pending" (not terminal) - eligible for
                # another attempt on a future run, without failing the
                # whole step over one shot.
                binding.last_error = str(exc)
                binding.attempts += 1
            except Exception as exc:  # noqa: BLE001 - per-shot isolation (Principle 10)
                binding.state = "failed"
                binding.last_error = str(exc)
                binding.attempts += 1

        await ctx.session.flush()
        # Per-shot failures do not fail the step (Principle 10) - the
        # render step gives a failed/pending shot a placeholder image
        # rather than blocking the other fifty-nine.
        return StepResult(outcome="ok")

    async def _resolve_one_fake(
        self,
        shot: Shot,
        binding,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        asset_provider: FakeAssetProvider,
        image_provider: FakeImageProvider,
        asset_repo: AssetRepository,
        clip_repo: GeneratedClipRepository,
    ) -> None:
        strategy = shot.asset_plan.strategy if shot.asset_plan else AssetStrategy.GENERATE_IMAGE

        if strategy in _SEARCH_STRATEGIES:
            query = AssetQuery(
                search_terms=shot.asset_plan.search_queries if shot.asset_plan else [],
                preferred_type=(
                    shot.asset_plan.preferred_type.value if shot.asset_plan else "image"
                ),
                shot_id=shot.id,
            )
            candidates = await asset_provider.search(query)
            if candidates:
                best = max(candidates, key=lambda c: c.relevance)
                fetched = await asset_provider.fetch(best)
                content_hash = hashlib.sha256(fetched.content).hexdigest()

                asset = await asset_repo.get_by_content_hash(project_uuid, content_hash)
                if asset is None:
                    path = project_dir / "assets" / f"{content_hash}.png"
                    path.write_bytes(fetched.content)
                    asset = await asset_repo.insert(
                        project_id=project_uuid,
                        provider=asset_provider.name,
                        source_url=best.source_url,
                        type="image",
                        local_path=str(path),
                        licence=best.licence,
                        attribution=fetched.attribution or None,
                        content_hash=content_hash,
                        confidence=best.relevance,
                    )
                binding.asset_id = asset.id
                binding.state = "resolved"
                binding.rung = strategy.value
                return
            # Fell through the search rung with nothing found - generate.

        await self._generate(
            shot,
            binding,
            project_uuid=project_uuid,
            project_dir=project_dir,
            image_provider=image_provider,
            clip_repo=clip_repo,
        )

    async def _resolve_one_real(
        self,
        shot: Shot,
        binding,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        search_providers: dict[AssetStrategy, AssetProvider],
        image_provider: FakeImageProvider,
        asset_repo: AssetRepository,
        clip_repo: GeneratedClipRepository,
        creative_context: CreativeContext,
        already_used_hashes: set[str],
    ) -> str | None:
        """Walks the shot's fallback_chain across real search providers.
        Returns the content_hash it resolved to (for reuse-penalty
        tracking across the rest of this run), or None if it fell through
        to generation."""
        asset_plan = shot.asset_plan
        chain = asset_plan.fallback_chain if asset_plan else []
        licence_requirements = set(asset_plan.licence_requirements) if asset_plan else set()

        for strategy in chain:
            if strategy not in _SEARCH_STRATEGIES:
                break  # reached a generation rung in the chain - stop searching

            provider = search_providers[strategy]
            query = AssetQuery(
                search_terms=asset_plan.search_queries if asset_plan else [],
                preferred_type=asset_plan.preferred_type.value if asset_plan else "image",
                shot_id=shot.id,
                historical_period=creative_context.historical_period,
            )
            candidates = await provider.search(query)

            # Licence is a hard gate, never a ranking factor (implementation
            # guide, Phase M6 advice) - a candidate whose licence isn't
            # acceptable is discarded outright, not deprioritised.
            eligible = [
                c
                for c in candidates
                if not licence_requirements or c.licence in licence_requirements
            ]
            if not eligible:
                continue

            fetched_candidates: list[tuple[AssetCandidate, str, bytes, str]] = []
            for candidate in eligible[:_CANDIDATES_TO_FETCH_PER_RUNG]:
                fetched = await provider.fetch(candidate)
                content_hash = hashlib.sha256(fetched.content).hexdigest()
                fetched_candidates.append(
                    (candidate, content_hash, fetched.content, fetched.attribution)
                )

            # Dedupe by content hash before ranking - the same image can
            # arrive under different URLs, and must not be ranked as two
            # separate options.
            seen_hashes: set[str] = set()
            deduped: list[tuple[AssetCandidate, str, bytes, str]] = []
            for entry in fetched_candidates:
                if entry[1] in seen_hashes:
                    continue
                seen_hashes.add(entry[1])
                deduped.append(entry)

            ranked = rank_candidates(
                [(c, h) for c, h, _, _ in deduped],
                historical_period=creative_context.historical_period,
                already_used_hashes=frozenset(already_used_hashes),
                shot_id=shot.id,
            )

            by_hash = {h: (c, content, attribution) for c, h, content, attribution in deduped}
            for rank_result in ranked:
                candidate, content, attribution = by_hash[rank_result.content_hash]

                existing = await asset_repo.get_by_content_hash(
                    project_uuid, rank_result.content_hash
                )
                if existing is not None:
                    binding.asset_id = existing.id
                    binding.state = "resolved"
                    binding.rung = strategy.value
                    return rank_result.content_hash

                try:
                    ext, _width, _height = validate_and_identify_image(content)
                except PermanentError:
                    continue  # this candidate's bytes are bad - try the next-ranked one

                path = project_dir / "assets" / f"{rank_result.content_hash}.{ext}"
                path.write_bytes(content)
                asset = await asset_repo.insert(
                    project_id=project_uuid,
                    provider=provider.name,
                    source_url=candidate.source_url,
                    type="image",
                    local_path=str(path),
                    licence=candidate.licence,
                    attribution=attribution or candidate.author or None,
                    content_hash=rank_result.content_hash,
                    confidence=rank_result.score,
                )
                binding.asset_id = asset.id
                binding.state = "resolved"
                binding.rung = strategy.value
                return rank_result.content_hash

            # Every fetched candidate in this rung failed validation -
            # move on to the next strategy in the fallback chain.

        await self._generate(
            shot,
            binding,
            project_uuid=project_uuid,
            project_dir=project_dir,
            image_provider=image_provider,
            clip_repo=clip_repo,
        )
        return None

    async def _generate(
        self,
        shot: Shot,
        binding,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        image_provider: FakeImageProvider,
        clip_repo: GeneratedClipRepository,
    ) -> None:
        result = await image_provider.generate(
            ImageRequest(
                prompt=shot.prompt,
                width=settings.render_width,
                height=settings.render_height,
                shot_id=shot.id,
            )
        )
        prompt_hash = hashlib.sha256(f"{shot.prompt}|{image_provider.name}".encode()).hexdigest()
        clip = await clip_repo.get_by_prompt_hash(prompt_hash)
        if clip is None:
            path = project_dir / "clips" / f"{prompt_hash}.png"
            path.write_bytes(result.content)
            clip = await clip_repo.insert(
                project_id=project_uuid,
                shot_id=shot.id,
                provider=image_provider.name,
                model_id="fake-image-v1",
                prompt=shot.prompt,
                prompt_hash=prompt_hash,
                duration_s=None,
                local_path=str(path),
                cost_cents=0,
            )
        binding.clip_id = clip.id
        binding.state = "generated"
        binding.rung = AssetStrategy.GENERATE_IMAGE.value
