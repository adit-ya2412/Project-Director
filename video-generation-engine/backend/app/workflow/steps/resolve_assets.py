"""Step: resolve or generate media for every shot.

One class, two pipeline positions (M6.5, A5/A21). `ResolveAssetsStep` is
parameterised by `permitted_strategies` - which rungs of the asset ladder
(canon 3.1) it is allowed to use - and instantiated TWICE in
`app.workflow.engine.DEFAULT_PIPELINE`, under two distinct `name`s:

- `resolve_assets_search` (rungs 1-4, free): runs BEFORE the approval
  gate. Search costs nothing, so I6 permits it, and this is what makes
  the risky acquisition step supervised at the moment fixing it is still
  free (A5) - the human reaches approval having already seen what was
  found, with the found-vs-will-generate distinction visible via
  `GET /progress`.
- `resolve_assets_generate` (rungs 5-6, paid): runs AFTER the approval
  gate, after narration (A6/A7) - narration is cheap and validates real
  duration; a script that blows the 90s cap must fail there, before
  dollars of generation are spent on a video that cannot ship.

Not two step classes: the ladder walk, relevance gate, licence gate, hash
dedup, budget checks, and per-shot failure isolation are all shared, and
two classes would duplicate that logic and let it drift. `is_satisfied`
is pass-specific (A21) - "search finished" and "generation finished" are
different questions, encoded as `self._done_states` below. A shot the
search pass could not resolve is marked `awaiting_generation`, not
`failed` - that state is deliberately excluded from `TERMINAL_STATES`
(see `app/repositories/shot_binding_repository.py`), so the search
pass's own `is_satisfied` treats it as done while the generation pass's
does not.

DRY_RUN=true: unchanged in spirit since M4 - `FakeAssetProvider`/
`FakeImageProvider` always find/produce something, so the fallback chain
and the real generation path below are never exercised. DRY_RUN never
constructs a vision-constraint provider either (`None`, same idiom as
`video_provider`) - the fake path never does real generation, so there is
nothing to check (M6.5, A12); this is also what keeps the walking-
skeleton e2e test passing with zero API keys. Each pass instance also
only ever constructs the providers ITS OWN permitted rungs could need -
the search-only pass never constructs `FalImageProvider`/
`OpenAIPlanningProvider`, the generation-only pass never constructs the
search/entity providers.

DRY_RUN=false: real search (M6, rungs 1-4) walks the shot's full
`asset_plan.fallback_chain`, restricted to whichever rungs THIS pass
permits; a miss on every permitted search rung, when generation is not
permitted this pass, defers the shot (`awaiting_generation`) rather than
falling through to generation (A6 - generation only ever happens in the
post-approval pass). When generation IS permitted, a search miss (or a
pass with no search rungs permitted at all) falls through to real
generation (M7, rungs 5-6) via fal.ai. Image generation (`fal-ai/
bytedance/seedream/v4/text-to-image` by default) is a bounded synchronous
poll - Seedream is fast. Video generation (`fal-ai/kling-video/o3/
standard/image-to-video` by default) is image-to-video: a keyframe is
generated first via the same image provider, then fed into Kling, and
the video job itself uses a real submit-once/poll-once-per-attempt
pattern so an in-flight job survives a process restart rather than being
resubmitted (implementation guide, Phase M7 advice).

Every generated image (standalone, or a video's keyframe) is checked
against the Director's `creative_context.constraints` before it ships
(M6.5, A12) - `_generate_checked_image`/`_generate_checked_keyframe`,
bounded-retrying a violation per A13/A18 and raising `PermanentError`
(caught below, same as any other per-shot failure) if every attempt is
still violating after `settings.max_generation_attempts_per_shot`
attempts. Searched assets are never checked (A16 defers that).

Per-shot failure isolation (Principle 10) is enforced throughout: one
shot failing (or hitting the budget cap, or exhausting its constraint
retries) marks that binding `failed` and processing continues with the
rest, never aborting the whole step. This is also what makes A22 true for
the search pass without any extra code: a shot whose EVERY search call
raises still only ever marks that ONE binding `failed` (or leaves it
`pending` for a retryable `TransientError`) - the step itself always
returns `outcome="ok"`, so a total outage of every search provider still
reaches the approval gate, showing nothing was found rather than
blocking on it.
"""

import hashlib
import uuid as uuid_module

from app.assets.constraint_check import (
    build_revised_prompt,
    check_generated_image_constraints,
    seed_for_attempt,
)
from app.assets.cost import check_budget, total_project_spend_cents
from app.assets.ranking import rank_candidates
from app.assets.relevance import candidate_relevance, passes_relevance_gate
from app.assets.validation import validate_and_identify_image
from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.models.generated_clip import GeneratedClipModel
from app.providers.base import (
    AssetCandidate,
    AssetProvider,
    AssetQuery,
    ImageProvider,
    ImageRequest,
    ImageResult,
    VideoProvider,
    VideoRequest,
    VisionConstraintProvider,
)
from app.providers.fakes.asset import FakeAssetProvider
from app.providers.fakes.image import FakeImageProvider
from app.providers.fal_image import FalImageProvider
from app.providers.fal_video import FalVideoProvider
from app.providers.local_assets import LocalProjectAssetProvider
from app.providers.openai_provider import OpenAIPlanningProvider
from app.providers.pexels import PexelsAssetProvider
from app.providers.wikimedia import WikimediaAssetProvider, WikipediaEntityAssetProvider
from app.repositories.asset_repository import AssetRepository
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.narration_repository import NarrationRepository
from app.repositories.shot_binding_repository import TERMINAL_STATES, ShotBindingRepository
from app.schemas.timeline import AssetStrategy, CreativeContext, PreferredMediaType, Shot
from app.workflow.context import RunContext
from app.workflow.step import StepResult

_SEARCH_STRATEGIES = frozenset(
    {
        AssetStrategy.PROJECT_ASSETS,
        AssetStrategy.HISTORICAL_SEARCH,
        AssetStrategy.PUBLIC_DOMAIN,
        AssetStrategy.STOCK_SEARCH,
    }
)
_GENERATION_STRATEGIES = frozenset({AssetStrategy.GENERATE_VIDEO, AssetStrategy.GENERATE_IMAGE})
# Entity retrieval (M6.5, A1/A2) only makes sense for the two Wikimedia-
# backed rungs - Pexels and project uploads have no notion of a Wikipedia
# article or Commons category to resolve against.
_ENTITY_ELIGIBLE_STRATEGIES = frozenset(
    {AssetStrategy.HISTORICAL_SEARCH, AssetStrategy.PUBLIC_DOMAIN}
)
_CANDIDATES_TO_FETCH_PER_RUNG = 5

# The canonical ladder split (implementation guide, M6.5 build order + A5):
# rungs 1-4 are free and run before approval; rungs 5-6 cost real money and
# run after. `app.workflow.engine.DEFAULT_PIPELINE` instantiates one
# `ResolveAssetsStep` per set.
SEARCH_RUNGS = _SEARCH_STRATEGIES
GENERATION_RUNGS = _GENERATION_STRATEGIES


def _real_search_providers(
    *, asset_repo: AssetRepository, project_uuid: uuid_module.UUID
) -> dict[AssetStrategy, AssetProvider]:
    return {
        AssetStrategy.PROJECT_ASSETS: LocalProjectAssetProvider(asset_repo, project_uuid),
        AssetStrategy.HISTORICAL_SEARCH: WikimediaAssetProvider(rung="historical_search"),
        AssetStrategy.PUBLIC_DOMAIN: WikimediaAssetProvider(rung="public_domain"),
        AssetStrategy.STOCK_SEARCH: PexelsAssetProvider(),
    }


def _project_seed(project_id: str) -> int:
    """A fixed seed per project (implementation guide, Phase M7 advice:
    "use a fixed seed per project... prefer stylistic consistency over
    per-shot quality") - deterministic from the project id, so every
    generated image/keyframe in a project shares a seed without needing
    to persist one separately."""
    return int(hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:8], 16)


def _styled_prompt(shot: Shot, creative_context: CreativeContext) -> str:
    if creative_context.visual_style:
        return f"{shot.prompt}, {creative_context.visual_style}"
    return shot.prompt


class ResolveAssetsStep:
    retryable = True
    max_attempts = 3

    def __init__(self, *, name: str, permitted_strategies: frozenset[AssetStrategy]) -> None:
        self.name = name
        self._permitted_strategies = permitted_strategies
        self._search_permitted = bool(permitted_strategies & _SEARCH_STRATEGIES)
        self._generation_permitted = bool(permitted_strategies & _GENERATION_STRATEGIES)
        # A21: "search finished" and "generation finished" are different
        # questions. The search pass additionally treats
        # `awaiting_generation` as done - it IS done, with search; the
        # generation pass must not, since that state is exactly its own
        # work queue.
        self._done_states = (
            TERMINAL_STATES
            if self._generation_permitted
            else TERMINAL_STATES | {"awaiting_generation"}
        )

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
        return all(bindings[s.id].state in self._done_states for s in shots)

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to resolve assets for")

        project_uuid = uuid_module.UUID(ctx.project_id)
        binding_repo = ShotBindingRepository(ctx.session)
        asset_repo = AssetRepository(ctx.session)
        clip_repo = GeneratedClipRepository(ctx.session)
        narration_repo = NarrationRepository(ctx.session)
        llm_call_repo = LlmCallRepository(ctx.session)

        project_dir = settings.storage_root / ctx.project_id
        (project_dir / "assets").mkdir(parents=True, exist_ok=True)
        (project_dir / "clips").mkdir(parents=True, exist_ok=True)

        # Every provider below is constructed only if THIS pass's
        # permitted rungs could ever need it - the search pass never
        # touches fal.ai/OpenAI, the generation pass never touches
        # Wikimedia/Pexels/entity retrieval.
        fake_asset_provider = (
            FakeAssetProvider() if settings.dry_run and self._search_permitted else None
        )
        search_providers = (
            _real_search_providers(asset_repo=asset_repo, project_uuid=project_uuid)
            if (not settings.dry_run and self._search_permitted)
            else None
        )
        # A1/A2 (M6.5): entity -> images is a deterministic lookup, not a
        # search rung - one instance, reused across every shot in this run
        # (its own rate limiter is per-instance, same discipline as the
        # search providers above).
        entity_provider = (
            WikipediaEntityAssetProvider()
            if (not settings.dry_run and self._search_permitted)
            else None
        )
        # M6.5, A12: `None` in DRY_RUN, same idiom as every other real
        # provider above - `check_generated_image_constraints` treats a
        # `None` provider as "nothing to call", so DRY_RUN never
        # constructs an OpenAI client and never needs an API key.
        vision_provider: VisionConstraintProvider | None = (
            (None if settings.dry_run else OpenAIPlanningProvider())
            if self._generation_permitted
            else None
        )
        image_provider: ImageProvider | None = (
            (FakeImageProvider() if settings.dry_run else FalImageProvider())
            if self._generation_permitted
            else None
        )
        video_provider: VideoProvider | None = (
            (None if settings.dry_run else FalVideoProvider())
            if self._generation_permitted
            else None
        )
        already_used_hashes = await asset_repo.list_content_hashes_for_project(project_uuid)

        for shot in timeline.all_shots():
            binding = await binding_repo.get_or_create_pending(
                project_uuid, timeline.version, shot.id
            )
            if binding.state in self._done_states:
                continue  # already decided by this pass on a prior attempt/run

            try:
                if settings.dry_run:
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
                    used_hash = await self._resolve_one_real(
                        shot,
                        binding,
                        project_uuid=project_uuid,
                        project_dir=project_dir,
                        search_providers=search_providers,
                        entity_provider=entity_provider,
                        image_provider=image_provider,
                        video_provider=video_provider,
                        vision_provider=vision_provider,
                        asset_repo=asset_repo,
                        clip_repo=clip_repo,
                        narration_repo=narration_repo,
                        llm_call_repo=llm_call_repo,
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
        # rather than blocking the other fifty-nine. This is also what
        # makes A22 true: even if every shot's search raised, the step
        # still returns "ok" and the run reaches the approval gate.
        return StepResult(outcome="ok")

    async def _resolve_one_fake(
        self,
        shot: Shot,
        binding,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        asset_provider: FakeAssetProvider | None,
        image_provider: ImageProvider | None,
        asset_repo: AssetRepository,
        clip_repo: GeneratedClipRepository,
    ) -> None:
        strategy = shot.asset_plan.strategy if shot.asset_plan else AssetStrategy.GENERATE_IMAGE

        if strategy in _SEARCH_STRATEGIES and self._search_permitted:
            assert asset_provider is not None
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
            # Fell through the search rung with nothing found.

        if not self._generation_permitted:
            # A5/A6/A21: this pass may only search - defer to the paid
            # pass rather than generate.
            binding.state = "awaiting_generation"
            return

        assert image_provider is not None
        await self._generate_fake(
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
        search_providers: dict[AssetStrategy, AssetProvider] | None,
        entity_provider: WikipediaEntityAssetProvider | None,
        image_provider: ImageProvider | None,
        video_provider: VideoProvider | None,
        vision_provider: VisionConstraintProvider | None,
        asset_repo: AssetRepository,
        clip_repo: GeneratedClipRepository,
        narration_repo: NarrationRepository,
        llm_call_repo: LlmCallRepository,
        creative_context: CreativeContext,
        already_used_hashes: set[str],
    ) -> str | None:
        """Walks the shot's fallback_chain across real search providers,
        restricted to `self._permitted_strategies`. Returns the
        content_hash it resolved to (for reuse-penalty tracking across
        the rest of this run), or None if it deferred to the generation
        pass or fell through to generation itself."""
        asset_plan = shot.asset_plan
        chain = asset_plan.fallback_chain if asset_plan else []
        licence_requirements = set(asset_plan.licence_requirements) if asset_plan else set()

        search_terms = (asset_plan.search_queries if asset_plan else []) or [shot.id]
        entity = (asset_plan.entity if asset_plan else "").strip()
        # Fetched at most once per shot, at the first Wikimedia-backed rung
        # reached in the chain - reused as-is on any later rung (A1/A2,
        # M6.5): the entity itself doesn't change between rungs, so
        # re-fetching would just repeat the same network call for no
        # benefit.
        entity_candidates: list[AssetCandidate] = []
        entity_candidates_fetched = False

        if self._search_permitted:
            assert search_providers is not None
            for strategy in chain:
                if strategy not in _SEARCH_STRATEGIES:
                    break  # reached a generation rung in the chain - stop searching
                if strategy not in self._permitted_strategies:
                    continue  # not one of THIS pass's permitted rungs - try the next

                provider = search_providers[strategy]
                query = AssetQuery(
                    search_terms=asset_plan.search_queries if asset_plan else [],
                    preferred_type=asset_plan.preferred_type.value if asset_plan else "image",
                    shot_id=shot.id,
                    historical_period=creative_context.historical_period,
                )
                candidates = await provider.search(query)

                # Only merged in on the Wikimedia-backed rungs, not on
                # every rung the fallback chain happens to reach
                # afterwards: `fetch` below is called on *this rung's*
                # provider, and a candidate's bytes must be downloaded
                # with the Wikimedia User-Agent Commons requires
                # (implementation guide, M6 notes - a generic UA is
                # silently blocklisted by upload.wikimedia.org) rather
                # than whatever the current provider (e.g. Pexels)
                # happens to send.
                entity_eligible_rung = strategy in _ENTITY_ELIGIBLE_STRATEGIES
                if entity and not entity_candidates_fetched and entity_eligible_rung:
                    assert entity_provider is not None
                    entity_candidates = await entity_provider.resolve_entity(entity)
                    entity_candidates_fetched = True

                # Entity-sourced candidates are pooled with the free-text
                # ones from here on and run through the exact same gates
                # - NOT exempted from either. An earlier version of this
                # step skipped the relevance gate for entity candidates on
                # the theory that a human filing an image under a subject
                # makes it relevant by construction; measured against the
                # live API, that premise is false (see
                # WikipediaEntityAssetProvider's docstring - a Wikipedia
                # article legitimately embeds off-topic images alongside
                # the one that actually matches a given shot). A bad
                # entity guess must fail exactly as gracefully as a bad
                # free-text query: fall through to the next rung, not win
                # by default.
                pool = candidates + (entity_candidates if entity_eligible_rung else [])

                # Licence is a hard gate, never a ranking factor
                # (implementation guide, Phase M6 advice) - a candidate
                # whose licence isn't acceptable is discarded outright,
                # not deprioritised. `project_assets` is exempt (M6.5,
                # A23 only ever names the relevance gate for uploads):
                # `licence_requirements` is written by the Asset Planner
                # with no visibility into whether an upload even exists
                # for this project (A3), so it can never have been chosen
                # with a human's own upload in mind - requiring an
                # uploaded photo to happen to satisfy a licence string
                # written for searching Wikimedia/Pexels would be an
                # arbitrary rejection of media the human already vetted
                # themselves by choosing to supply it.
                eligible = (
                    pool
                    if strategy == AssetStrategy.PROJECT_ASSETS
                    else [
                        c
                        for c in pool
                        if not licence_requirements or c.licence in licence_requirements
                    ]
                )
                if not eligible:
                    continue

                # Relevance is a hard gate too, same principle, applied
                # identically to every candidate regardless of source: a
                # candidate whose title/description has no genuine term
                # overlap with what the shot actually asked for is
                # discarded here, before it is ever downloaded or ranked -
                # never merely deprioritised (see app/assets/relevance.py
                # for the real production failures this is fixing - a
                # query returning a crucifixion painting or a Portuguese
                # railway station scored a perfect "relevance" of 1.0
                # under the old rank-position-only field).
                relevant = [
                    c
                    for c in eligible
                    if passes_relevance_gate(candidate_relevance(search_terms, c))
                ]
                if not relevant:
                    continue  # nothing on this rung is actually about the subject

                fetched_candidates: list[tuple[AssetCandidate, str, bytes, str]] = []
                for candidate in relevant[:_CANDIDATES_TO_FETCH_PER_RUNG]:
                    fetched = await provider.fetch(candidate)
                    content_hash = hashlib.sha256(fetched.content).hexdigest()
                    fetched_candidates.append(
                        (candidate, content_hash, fetched.content, fetched.attribution)
                    )

                # Dedupe by content hash before ranking - the same image
                # can arrive under different URLs, and must not be ranked
                # as two separate options.
                seen_hashes: set[str] = set()
                deduped: list[tuple[AssetCandidate, str, bytes, str]] = []
                for entry in fetched_candidates:
                    if entry[1] in seen_hashes:
                        continue
                    seen_hashes.add(entry[1])
                    deduped.append(entry)

                ranked = rank_candidates(
                    [(c, h) for c, h, _, _ in deduped],
                    search_terms=search_terms,
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
                    # Provenance reflects how this candidate was actually
                    # found (M6.5) - `entity_provider.name`
                    # ("wikipedia_entity") for an entity-curated hit,
                    # `provider.name` ("wikimedia") for a free-text one,
                    # even though both were fetched through the same
                    # rung's WikimediaAssetProvider instance above.
                    found_by = (
                        entity_provider.name
                        if candidate.entity_curated and entity_provider is not None
                        else provider.name
                    )
                    asset = await asset_repo.insert(
                        project_id=project_uuid,
                        provider=found_by,
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

        if not self._generation_permitted:
            # A5/A6/A21: this pass may only search - every permitted rung
            # came up empty (or none were permitted at all), so defer to
            # the paid pass rather than generate here.
            binding.state = "awaiting_generation"
            return None

        assert image_provider is not None and video_provider is not None
        is_video = bool(asset_plan and asset_plan.preferred_type == PreferredMediaType.VIDEO)
        if is_video:
            await self._generate_video_real(
                shot,
                binding,
                project_uuid=project_uuid,
                project_dir=project_dir,
                image_provider=image_provider,
                video_provider=video_provider,
                vision_provider=vision_provider,
                clip_repo=clip_repo,
                narration_repo=narration_repo,
                llm_call_repo=llm_call_repo,
                creative_context=creative_context,
            )
        else:
            await self._generate_image_real(
                shot,
                binding,
                project_uuid=project_uuid,
                project_dir=project_dir,
                image_provider=image_provider,
                vision_provider=vision_provider,
                clip_repo=clip_repo,
                narration_repo=narration_repo,
                llm_call_repo=llm_call_repo,
                creative_context=creative_context,
            )
        return None

    async def _generate_fake(
        self,
        shot: Shot,
        binding,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        image_provider: ImageProvider,
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

    async def _generate_image_real(
        self,
        shot: Shot,
        binding,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        image_provider: ImageProvider,
        vision_provider: VisionConstraintProvider | None,
        clip_repo: GeneratedClipRepository,
        narration_repo: NarrationRepository,
        llm_call_repo: LlmCallRepository,
        creative_context: CreativeContext,
    ) -> None:
        prompt = _styled_prompt(shot, creative_context)
        clip = await self._generate_checked_image(
            shot,
            base_prompt=prompt,
            project_uuid=project_uuid,
            project_dir=project_dir,
            width=settings.render_width,
            height=settings.render_height,
            model_id=settings.fal_image_model,
            image_provider=image_provider,
            vision_provider=vision_provider,
            llm_call_repo=llm_call_repo,
            clip_repo=clip_repo,
            narration_repo=narration_repo,
            constraints=creative_context.constraints,
        )
        binding.clip_id = clip.id
        binding.state = "generated"
        binding.rung = AssetStrategy.GENERATE_IMAGE.value

    async def _generate_checked_image(
        self,
        shot: Shot,
        *,
        base_prompt: str,
        project_uuid: uuid_module.UUID,
        project_dir,
        width: int,
        height: int,
        model_id: str,
        image_provider: ImageProvider,
        vision_provider: VisionConstraintProvider | None,
        llm_call_repo: LlmCallRepository,
        clip_repo: GeneratedClipRepository,
        narration_repo: NarrationRepository,
        constraints: list[str],
    ) -> GeneratedClipModel:
        """A12/A13/A18 (M6.5): generates an image and checks it against
        the Director's `constraints`, bounded-retrying a violation up to
        `settings.max_generation_attempts_per_shot` attempts total -
        attempt 0 at the project's fixed seed, subsequent attempts with
        the constraints violated SO FAR appended as explicit negative
        directives (A18 - a deterministic, de-duplicated rebuild, never a
        second LLM call - see `build_revised_prompt`), the seed varying
        only on the LAST attempt the configured cap allows (A13's second
        lever, never `random` - see `seed_for_attempt`).

        Every FRESH attempt is persisted immediately - `status=
        "completed"` if it passed, `"rejected"` if it didn't - so a
        rejected attempt's cost still counts against the budget cap
        (checked fresh before every fresh attempt, never bypassed)
        without ever being served back out as a reusable cache hit (the
        cache-hit check below only ever trusts `status == "completed"`).
        A cached `"rejected"` row for this EXACT attempt (prompt+model+
        seed) - found on a resumed run after a crash - is neither
        regenerated nor re-billed: its `violated_constraint` is recovered
        directly (a real column, not parsed out of `error`'s free text)
        and folded into the next attempt's revision, so a resume can
        never double-pay for (or silently lose the cost of) an attempt
        already known to fail. The seed is folded into `prompt_hash`
        (unlike the pre-M6.5 formula) because it is a genuine generation
        input - same prompt, different seed, different image - and
        because the de-duplicated revision means two different attempts
        CAN legitimately produce byte-identical prompt text (the same
        single constraint violated twice running revises to the same
        prompt both times), which must not collapse onto the same cache
        entry.

        Returns the winning `GeneratedClipModel`. Raises `PermanentError`
        naming the violated constraint if every attempt is exhausted
        still violating it - the caller's existing per-shot isolation
        (Principle 10, in `run()`) turns that into a `failed` binding
        with the reason in `last_error` (A14/A19); nothing here ever
        ships a violating image."""
        project_seed = _project_seed(str(project_uuid))
        violated_constraints: list[str] = []
        last_violation = ""

        for attempt in range(settings.max_generation_attempts_per_shot):
            seed = seed_for_attempt(
                project_seed, attempt, settings.max_generation_attempts_per_shot
            )
            prompt = build_revised_prompt(base_prompt, violated_constraints)
            prompt_hash = hashlib.sha256(f"{prompt}|{model_id}|{seed}".encode()).hexdigest()

            cached = await clip_repo.get_by_prompt_hash(prompt_hash)
            if cached is not None:
                if cached.status == "completed":
                    return cached
                # "rejected": this exact attempt already ran (and already
                # violated a constraint) in a prior run - recover it, do
                # not re-generate or re-bill it.
                assert cached.violated_constraint is not None
                last_violation = cached.error or cached.violated_constraint
                if cached.violated_constraint not in violated_constraints:
                    violated_constraints.append(cached.violated_constraint)
                continue

            already_spent = await total_project_spend_cents(
                clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
            )
            check_budget(
                already_spent_cents=already_spent,
                additional_cents=settings.fal_image_cost_cents_estimate,
            )

            result = await image_provider.generate(
                ImageRequest(prompt=prompt, width=width, height=height, shot_id=shot.id, seed=seed)
            )
            verdict = await check_generated_image_constraints(
                provider=vision_provider,
                llm_call_repo=llm_call_repo,
                project_id=project_uuid,
                image=result.content,
                image_content_type=result.content_type,
                shot_prompt=shot.prompt,
                constraints=constraints,
            )

            if not verdict.violated:
                ext, _width_px, _height_px = validate_and_identify_image(result.content)
                path = project_dir / "clips" / f"{prompt_hash}.{ext}"
                path.write_bytes(result.content)
                return await clip_repo.insert(
                    project_id=project_uuid,
                    shot_id=shot.id,
                    provider=image_provider.name,
                    model_id=model_id,
                    prompt=prompt,
                    prompt_hash=prompt_hash,
                    duration_s=None,
                    local_path=str(path),
                    cost_cents=settings.fal_image_cost_cents_estimate,
                )

            # Violated - bill it and record it (never free, never
            # silent), but never shipped and never a reusable cache entry.
            await clip_repo.insert(
                project_id=project_uuid,
                shot_id=shot.id,
                provider=image_provider.name,
                model_id=model_id,
                prompt=prompt,
                prompt_hash=prompt_hash,
                duration_s=None,
                local_path=None,
                cost_cents=settings.fal_image_cost_cents_estimate,
                status="rejected",
                violated_constraint=verdict.violated_constraint,
                error=f"violated constraint {verdict.violated_constraint!r}: {verdict.reason}",
            )
            last_violation = (
                f"violated constraint {verdict.violated_constraint!r}: {verdict.reason}"
            )
            if verdict.violated_constraint not in violated_constraints:
                violated_constraints.append(verdict.violated_constraint)

        raise PermanentError(
            f"shot {shot.id} generation blocked after "
            f"{settings.max_generation_attempts_per_shot} attempts - still violates a "
            f"Director constraint: {last_violation}"
        )

    async def _generate_checked_keyframe(
        self,
        shot: Shot,
        *,
        base_prompt: str,
        project_uuid: uuid_module.UUID,
        width: int,
        height: int,
        model_id: str,
        image_provider: ImageProvider,
        vision_provider: VisionConstraintProvider | None,
        llm_call_repo: LlmCallRepository,
        clip_repo: GeneratedClipRepository,
        narration_repo: NarrationRepository,
        constraints: list[str],
    ) -> ImageResult:
        """The video path's A12/A13/A18 equivalent, for the KEYFRAME
        only - "check the keyframe, not the clip: it's already an image
        and it's what determines the content." Unlike
        `_generate_checked_image`, a PASSING attempt is not persisted as
        its own `GeneratedClip` row here - `_generate_video_real` folds
        the keyframe's cost into the video job's own row
        (`estimated_cents`), exactly as it did before this change, so
        nothing double-counts. A REJECTED attempt IS persisted (billed,
        recorded, never reused) - both because it must count against the
        budget cap on its own, and because a rejected keyframe's bytes
        are never used for anything downstream, so there is no
        cache-hit/hosted_url conflict for that branch (a *passing*
        keyframe's `hosted_url` is ephemeral and provider-specific, which
        is exactly why it is never persisted or reused as a cache hit).

        Raises `PermanentError` naming the violated constraint if every
        attempt is exhausted still violating it, same as the image
        path. Same resume discipline as `_generate_checked_image`: a
        cached `"rejected"` row for this exact attempt is recovered
        (via the real `violated_constraint` column), never regenerated
        or re-billed."""
        project_seed = _project_seed(str(project_uuid))
        violated_constraints: list[str] = []
        last_violation = ""

        for attempt in range(settings.max_generation_attempts_per_shot):
            seed = seed_for_attempt(
                project_seed, attempt, settings.max_generation_attempts_per_shot
            )
            prompt = build_revised_prompt(base_prompt, violated_constraints)
            prompt_hash = hashlib.sha256(f"{prompt}|{model_id}|{seed}".encode()).hexdigest()

            cached = await clip_repo.get_by_prompt_hash(prompt_hash)
            if cached is not None:
                # Only ever a "rejected" row here - a passing keyframe
                # attempt is never persisted on its own (see docstring).
                assert cached.violated_constraint is not None
                last_violation = cached.error or cached.violated_constraint
                if cached.violated_constraint not in violated_constraints:
                    violated_constraints.append(cached.violated_constraint)
                continue

            already_spent = await total_project_spend_cents(
                clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
            )
            check_budget(
                already_spent_cents=already_spent,
                additional_cents=settings.fal_image_cost_cents_estimate,
            )

            result = await image_provider.generate(
                ImageRequest(prompt=prompt, width=width, height=height, shot_id=shot.id, seed=seed)
            )
            verdict = await check_generated_image_constraints(
                provider=vision_provider,
                llm_call_repo=llm_call_repo,
                project_id=project_uuid,
                image=result.content,
                image_content_type=result.content_type,
                shot_prompt=shot.prompt,
                constraints=constraints,
            )
            if not verdict.violated:
                return result

            await clip_repo.insert(
                project_id=project_uuid,
                shot_id=shot.id,
                provider=image_provider.name,
                model_id=model_id,
                prompt=prompt,
                prompt_hash=prompt_hash,
                duration_s=None,
                local_path=None,
                cost_cents=settings.fal_image_cost_cents_estimate,
                status="rejected",
                violated_constraint=verdict.violated_constraint,
                error=f"violated constraint {verdict.violated_constraint!r}: {verdict.reason}",
            )
            last_violation = (
                f"violated constraint {verdict.violated_constraint!r}: {verdict.reason}"
            )
            if verdict.violated_constraint not in violated_constraints:
                violated_constraints.append(verdict.violated_constraint)

        raise PermanentError(
            f"shot {shot.id} keyframe generation blocked after "
            f"{settings.max_generation_attempts_per_shot} attempts - still violates a "
            f"Director constraint: {last_violation}"
        )

    async def _generate_video_real(
        self,
        shot: Shot,
        binding,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        image_provider: ImageProvider,
        video_provider: VideoProvider,
        vision_provider: VisionConstraintProvider | None,
        clip_repo: GeneratedClipRepository,
        narration_repo: NarrationRepository,
        llm_call_repo: LlmCallRepository,
        creative_context: CreativeContext,
    ) -> None:
        prompt = _styled_prompt(shot, creative_context)
        prompt_hash = hashlib.sha256(f"{prompt}|{settings.fal_video_model}".encode()).hexdigest()

        cached = await clip_repo.get_by_prompt_hash(prompt_hash)
        if cached is not None and cached.status == "completed":
            binding.clip_id = cached.id
            binding.state = "generated"
            binding.rung = AssetStrategy.GENERATE_VIDEO.value
            return

        # Resume path: an in-flight job for this shot already exists from
        # a prior attempt/process - poll it, never resubmit (implementation
        # guide, Phase M7 advice).
        in_flight = await clip_repo.get_in_flight_for_shot(project_uuid, shot.id)
        if in_flight is not None:
            assert in_flight.job_id is not None
            status = await video_provider.poll(in_flight.job_id)
            if status.state == "in_progress":
                return  # still going - binding stays "pending", a later run polls again
            if status.state == "failed":
                await clip_repo.mark_failed(
                    in_flight, error=status.error or "video generation failed"
                )
                binding.state = "failed"
                binding.last_error = status.error or "video generation failed"
                return
            assert status.content is not None
            path = project_dir / "clips" / f"{prompt_hash}.mp4"
            path.write_bytes(status.content)
            await clip_repo.mark_completed(
                in_flight,
                local_path=str(path),
                duration_s=shot.duration_s,
                cost_cents=in_flight.cost_cents,
            )
            binding.clip_id = in_flight.id
            binding.state = "generated"
            binding.rung = AssetStrategy.GENERATE_VIDEO.value
            return

        # Fresh submission: a constraint-checked keyframe first (A12/A13 -
        # bounded, synchronous, may itself take up to
        # settings.max_generation_attempts_per_shot attempts), THEN the
        # video job itself (submit-and-poll, resumable).
        keyframe = await self._generate_checked_keyframe(
            shot,
            base_prompt=prompt,
            project_uuid=project_uuid,
            width=settings.render_width,
            height=settings.render_height,
            model_id=settings.fal_image_model,
            image_provider=image_provider,
            vision_provider=vision_provider,
            llm_call_repo=llm_call_repo,
            clip_repo=clip_repo,
            narration_repo=narration_repo,
            constraints=creative_context.constraints,
        )
        if keyframe.hosted_url is None:
            raise PermanentError(
                f"{image_provider.name} did not return a hosted URL required for "
                "image-to-video generation"
            )

        # The keyframe's cost is folded into this one bundled estimate
        # (rather than tracked as its own row) precisely because a
        # PASSING keyframe attempt is never persisted separately above -
        # see `_generate_checked_keyframe`'s docstring. A rejected
        # attempt along the way was already billed on its own.
        estimated_cents = (
            settings.fal_image_cost_cents_estimate + settings.fal_video_cost_cents_estimate
        )
        already_spent = await total_project_spend_cents(
            clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
        )
        check_budget(already_spent_cents=already_spent, additional_cents=estimated_cents)

        job_id = await video_provider.submit(
            VideoRequest(
                prompt=prompt,
                image_url=keyframe.hosted_url,
                duration_s=shot.duration_s,
                shot_id=shot.id,
            )
        )
        # Persisted immediately, before anything else - if the process
        # crashes right after this, the job is still findable on resume.
        await clip_repo.insert_pending(
            project_id=project_uuid,
            shot_id=shot.id,
            provider=video_provider.name,
            model_id=settings.fal_video_model,
            prompt=prompt,
            prompt_hash=prompt_hash,
            job_id=job_id,
            estimated_cost_cents=estimated_cents,
        )
        # binding.state stays "pending" (non-terminal) - a later run of
        # this step polls the job above rather than resubmitting it.
