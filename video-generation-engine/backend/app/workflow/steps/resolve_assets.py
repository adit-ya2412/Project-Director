"""Step 3: resolve or generate media for every shot.

Stand-in for the Asset Resolver (M6) and Media Generator (M7) collapsed
into one step, since only fakes exist for either yet. Each shot gets its
own `ShotBinding` row - this table IS the media generation work queue,
and per-shot failure isolation (Principle 10) is enforced here: one shot
failing marks that binding `failed` and processing continues with the
rest, never aborting the whole step.

Reuse-before-generate (Creative Philosophy Principle 8) and both
dedup caches (Asset.content_hash per-project, GeneratedClip.prompt_hash
globally - ladder rung 0) are wired for real here, even though the
providers underneath are fakes - M6/M7 swap the provider, not this shape.
"""

import hashlib
import uuid as uuid_module

from app.core.config import settings
from app.core.errors import TransientError
from app.providers.base import AssetQuery, ImageRequest
from app.providers.fakes.asset import FakeAssetProvider
from app.providers.fakes.image import FakeImageProvider
from app.repositories.asset_repository import AssetRepository
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.shot_binding_repository import TERMINAL_STATES, ShotBindingRepository
from app.schemas.timeline import AssetStrategy, Shot
from app.workflow.context import RunContext
from app.workflow.step import StepResult

_SEARCH_STRATEGIES = {
    AssetStrategy.PROJECT_ASSETS,
    AssetStrategy.HISTORICAL_SEARCH,
    AssetStrategy.PUBLIC_DOMAIN,
    AssetStrategy.STOCK_SEARCH,
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
        asset_provider = FakeAssetProvider()
        project_dir = settings.storage_root / ctx.project_id
        (project_dir / "assets").mkdir(parents=True, exist_ok=True)
        (project_dir / "clips").mkdir(parents=True, exist_ok=True)

        for shot in timeline.all_shots():
            binding = await binding_repo.get_or_create_pending(
                project_uuid, timeline.version, shot.id
            )
            if binding.state in TERMINAL_STATES:
                continue  # already resolved on a prior attempt/run

            try:
                await self._resolve_one(
                    shot,
                    binding,
                    project_uuid=project_uuid,
                    project_dir=project_dir,
                    asset_provider=asset_provider,
                    image_provider=image_provider,
                    asset_repo=asset_repo,
                    clip_repo=clip_repo,
                )
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

    async def _resolve_one(
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
                best = max(candidates, key=lambda c: c.score)
                fetched = await asset_provider.fetch(best)
                content_hash = hashlib.sha256(fetched.content).hexdigest()

                asset = await asset_repo.get_by_content_hash(project_uuid, content_hash)
                if asset is None:
                    path = project_dir / "assets" / f"{content_hash}.png"
                    path.write_bytes(fetched.content)
                    asset = await asset_repo.insert(
                        project_id=project_uuid,
                        provider=asset_provider.name,
                        source_url=None,
                        type="image",
                        local_path=str(path),
                        licence=best.licence,
                        attribution=None,
                        content_hash=content_hash,
                        confidence=best.score,
                    )
                binding.asset_id = asset.id
                binding.state = "resolved"
                binding.rung = strategy.value
                return
            # Fell through the search rung with nothing found - generate.

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
