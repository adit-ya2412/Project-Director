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
only ever constructs the GENERATION providers its own permitted rungs
could need - the search-only pass never constructs `FalImageProvider`,
the generation-only pass never constructs the search/entity providers.
`OpenAIPlanningProvider` (`vision_provider`) is the one exception (M6.5,
A30): both passes construct it whenever this is a real run, since the
search pass needs it for its own question (A30, `check_candidate_
plausibility`) - the generation pass no longer has a live use for it
(motion_new_styles_and_long_form_videos.md Track A's A5, 2026-08-18: see
the note below), but is never permitted to search in the first place, so
this costs nothing there either.

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

Neither a standalone generated image nor a video's keyframe is checked
against the Director's `creative_context.constraints` any more - the
one-gate model (M6.5 gate redesign, 2026-08-16, extended to video by
motion_new_styles_and_long_form_videos.md Track A's A5 on 2026-08-18):
the human at the review gate is the check now, not an
automated vision call that could kill a shot outright on a false
positive (`generate_image_real`/`_generate_image_once` for images,
`_generate_keyframe_once` for a video's keyframe - both a single,
unchecked generate call, no retry). The OLD constraint-checked path
(`_generate_checked_image`/`_generate_checked_keyframe`,
bounded-retrying a violation per A13/A18 and raising `PermanentError` if
every attempt was still violating after
`settings.max_generation_attempts_per_shot` attempts) is kept, unwired,
not deleted - see those functions' own docstrings. Searched assets get
their OWN, narrower vision check (M6.5,
A16 -> A30 -> A30a): the top-ranked candidate per rung only, skipped for
an entity-curated hit, dropping the candidate (and the whole rung) when
it is CONFIDENTLY a different kind of subject entirely - never merely
because a specific named place/event can't be visually confirmed, which
measured live as an unanswerable question that cost two genuinely
correct images (see `app/assets/depiction_check.py`'s own docstring for
the full account). A different question
(`check_candidate_plausibility`, "is this confidently something else")
from the generation-side one above (`check_generated_image_constraints`,
"does this violate Y"), sharing only the provider and the `llm_call`
audit mechanism.

Search I/O (Commons/Pexels/entity/download) fans out across shots with
`bounded_gather` (`asset_search_concurrency`, default 8). Rank, vision
check, and bind stay serial in timeline order so C4's reuse window sees
earlier picks. Wikimedia's RateLimiter still caps Commons at 5 calls/s.

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

import asyncio
import hashlib
import uuid as uuid_module
from dataclasses import dataclass
from pathlib import Path

from app.assets.constraint_check import (
    build_revised_prompt,
    check_generated_image_constraints,
    seed_for_attempt,
    varied_seed,
)
from app.assets.cost import budget_cap_cents_for, check_budget, total_project_spend_cents
from app.assets.depiction_check import check_candidate_plausibility
from app.assets.focal import persist_vision_focal
from app.assets.focal_check import locate_subject_focal
from app.assets.ranking import rank_candidates, reuse_gaps_s, reuse_window_s
from app.assets.relevance import candidate_relevance, passes_relevance_gate
from app.assets.substrate_crop import center_crop_to_canvas
from app.assets.thumbnails import cached_video_frame, is_video_file, shot_frame_cache_path
from app.assets.validation import (
    mime_type_for_extension,
    validate_and_identify_image,
    validate_and_identify_video,
)
from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.core.logging import get_logger
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
from app.models.shot_binding import ShotBindingModel
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
from app.schemas.timeline import (
    AssetStrategy,
    CreativeContext,
    PreferredMediaType,
    Shot,
    ShotLayer,
)
from app.script.styles import (
    RenderFormat,
    resolve_generation_request_format,
    resolve_render_format,
)
from app.timeline.duration import compute_shot_start_times
from app.utils.bounded_gather import asset_search_concurrency, bounded_gather
from app.workflow.context import RunContext
from app.workflow.step import StepResult

logger = get_logger(__name__)

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


@dataclass
class _PrefetchedRung:
    """One search-rung's fetched, gated, hashed bytes — ranking happens
    later, in timeline order, so C4 reuse can see earlier picks."""

    strategy: AssetStrategy
    provider_name: str
    entity_provider_name: str | None
    entries: list[tuple[AssetCandidate, str, bytes, str]]


@dataclass
class _PendingShot:
    shot: Shot
    binding: ShotBindingModel
    needs_secondary: bool
    shot_start: float


def secondary_panel_done(shot: Shot, binding, *, done_states: frozenset[str]) -> bool:
    """R17: a split shot is not done while its bottom panel has neither
    media nor a recorded outcome. Null `secondary_state` means never
    attempted, which is not done."""
    if shot.secondary_asset_plan is None:
        return True
    if binding.secondary_asset_id is not None or binding.secondary_clip_id is not None:
        return True
    state = getattr(binding, "secondary_state", None)
    return state in done_states


def _raise_if_prefetch_failed(
    result: tuple[list[_PrefetchedRung], list[_PrefetchedRung] | None] | Exception,
) -> tuple[list[_PrefetchedRung], list[_PrefetchedRung] | None]:
    if isinstance(result, Exception):
        raise result
    return result


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


# FIXED 2026-08-18 (A8's bake-off, motion_new_styles_and_long_form_videos.md):
# see `styled_prompt`'s own docstring for the failure this bounds.
_MAX_VISUAL_STYLE_WORDS = 15


# Frozen historical default. Never read settings here — flipping
# `render_width/height` must not re-key every existing generate (§19.12).
_CACHE_KEY_BASELINE = (720, 1280)


def generation_prompt_hash(*parts: object, width: int, height: int) -> str:
    """Cache key for a generated image/clip. 720×1280 is omitted so
    existing rows stay hits (same trick as narration `speed != 1.0`).
    Non-baseline formats append `|WxH` (§19.1)."""
    digest = "|".join(str(p) for p in parts)
    if (width, height) != _CACHE_KEY_BASELINE:
        digest += f"|{width}x{height}"
    return hashlib.sha256(digest.encode()).hexdigest()


def styled_prompt(
    shot: Shot,
    creative_context: CreativeContext,
    *,
    frame: RenderFormat | None = None,
) -> str:
    """Renamed from `_styled_prompt` (P0, docs/plans/gate_panel_overrides.md,
    2026-09-08) so `app/assets/prompt_export.py` can call the exact same
    function the generation path calls, rather than re-deriving a shot's
    prompt a second time (R1). No other production module had ever
    imported a private, underscore-led name across a module boundary
    before this - `layer_styled_prompt` below is the sibling that already
    took this same step for the identical reason (`render.py`'s own
    render-time lookup needs it) - so exposing this one properly, rather
    than adding the first such private cross-module import, keeps that
    convention intact.

    `creative_context.visual_style` describes the WHOLE video's visual
    arc (ADR-010), often as an explicit multi-part sequence - the real
    m8_test_project's own value reads "black-and-white WWII coal
    mines... THEN muted-color South African refinery... ENDING WITH
    contemporary energy infrastructure". Appending that verbatim to a
    single shot's prompt reliably made Seedream generate a multi-panel
    collage of the whole arc (with garbled fake captions) instead of one
    photograph of the scene this shot actually describes - measured
    directly against a real project, not assumed: all 3 real shots in
    the bake-off failed identically before this fix.

    Two things were tried and REJECTED before this one, each verified
    against a real regeneration, not assumed to work from reasoning
    alone: an explicit "single photograph, no collage" instruction did
    NOT help (if anything, the output got MORE elaborate - diffusion-
    family image models are well known to handle negation poorly, and
    naming the failure mode ("collage") in the prompt just adds that
    concept as content); a "one photograph, one camera framing, one
    moment" positive reframing made the main scene more dominant but
    still left a sidebar strip of extra panels.

    **What actually worked, verified against the same real prompt:**
    bounding how much of `visual_style` is appended at all, mechanically
    (a fixed word count, language-agnostic - deliberately NOT a keyword
    search for connectives like "then"/"ending with", which is
    English-specific and would miss e.g. Hindi "फिर" in
    `hindi_test_project.json`'s own visual_style). The multi-era
    NARRATIVE is what triggers the collage, not phrasing choices within
    it - truncating to the first `_MAX_VISUAL_STYLE_WORDS` words leaves
    one coherent style clause instead of the full multi-subject arc, and
    a real regeneration with this exact truncation produced a single,
    clean, correctly-styled photograph. This is a mechanical bound, not
    a semantic one - it does not understand the text it's cutting, only
    where it's cutting it, and may need retuning if a future project's
    `visual_style` puts its multi-era sequencing earlier than 15 words
    in."""
    if not creative_context.visual_style:
        base = shot.prompt
    else:
        capped_style = " ".join(creative_context.visual_style.split()[:_MAX_VISUAL_STYLE_WORDS])
        base = f"{shot.prompt}, {capped_style}"
    # Portrait is today's default; appending would bust every existing
    # generated-image cache row. Landscape is the new format (§19.9).
    if frame is not None and frame.is_landscape:
        return f"{base} Composed for a landscape 16:9 frame."
    return base


async def generate_image_real(
    shot: Shot,
    binding,
    *,
    project_uuid: uuid_module.UUID,
    project_dir,
    image_provider: ImageProvider,
    clip_repo: GeneratedClipRepository,
    narration_repo: NarrationRepository,
    creative_context: CreativeContext,
    cap_cents: int | None = None,
    style: str | None = None,
    frame_aspect: str | None = None,
) -> tuple[GeneratedClipModel, bool]:
    """Module-level (not a step method) so both `ResolveAssetsStep` and
    the per-shot `/generate` endpoint call the identical path - one
    generation, no engine, no workflow trigger involved. Returns
    `(clip, cache_hit)` so a caller (the endpoint, Task 6) can report
    whether THIS call actually cost anything or reused an already-paid-for
    image - the workflow step ignores both, same as it always has."""
    frame = resolve_render_format(style, frame_aspect=frame_aspect)
    # F1a (illustrated_faceless.md §8.1): a GENERATION_ONLY style requests
    # a slightly oversized image here so `_generate_image_once` can crop
    # any substrate margin back off before persisting - a RETRIEVAL_LADDER
    # style gets `frame` back unchanged (byte-identical to before F1a).
    request_frame = resolve_generation_request_format(style, frame)
    prompt = styled_prompt(shot, creative_context, frame=frame)
    clip, cache_hit = await _generate_image_once(
        shot,
        base_prompt=prompt,
        project_uuid=project_uuid,
        project_dir=project_dir,
        width=request_frame.width,
        height=request_frame.height,
        model_id=settings.fal_image_model,
        image_provider=image_provider,
        clip_repo=clip_repo,
        narration_repo=narration_repo,
        cap_cents=cap_cents,
        canvas_width=frame.width,
        canvas_height=frame.height,
    )
    binding.clip_id = clip.id
    # Task 4 (2026-08-16): `asset_id` is explicitly cleared here, mirroring
    # `override_shot_asset`'s own symmetric clear of `clip_id` when IT
    # writes a binding. Before "generate and override are peers" (this
    # task), `generate_image_real` only ever ran against a binding that
    # never had `asset_id` set in the first place (the automatic
    # pipeline's own fallback-to-generation path, or a fresh `/generate`
    # call before any override), so this line was a no-op. Now that
    # `/shots/{id}/generate` may run on a shot a human previously
    # overrode, leaving a stale `asset_id` behind would be a real, silent
    # bug: `_resolve_bound_media_path` (and the identical rule in
    # `RenderStep`) resolve `asset_id` BEFORE `clip_id`, so a binding with
    # both set would keep serving the old overridden picture forever,
    # making a "generate after override" click look like it did nothing.
    binding.asset_id = None
    binding.state = "generated"
    binding.rung = AssetStrategy.GENERATE_IMAGE.value
    return clip, cache_hit


async def _generate_image_once(
    shot: Shot,
    *,
    base_prompt: str,
    project_uuid: uuid_module.UUID,
    project_dir,
    width: int,
    height: int,
    model_id: str,
    image_provider: ImageProvider,
    clip_repo: GeneratedClipRepository,
    narration_repo: NarrationRepository,
    cap_cents: int | None = None,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
) -> tuple[GeneratedClipModel, bool]:
    """F1a (illustrated_faceless.md §8.1, 2026-09-05): `canvas_width`/
    `canvas_height`, when given and different from the REQUESTED `width`/
    `height` below, are the style's real canvas - the caller
    (`generate_image_real`) asks for a style-scoped oversized `width`/
    `height` for a `GENERATION_ONLY` style
    (`resolve_generation_request_format`) and passes the true canvas here
    so the delivered bytes are centre-cropped
    (`app/assets/substrate_crop.py::center_crop_to_canvas`) back to it
    BEFORE anything is persisted or hashed downstream - the rest of the
    pipeline must see exactly the canvas size it has always seen. Both
    default to `None`, a no-op identical to this function's pre-F1a
    behaviour - every `RETRIEVAL_LADDER` style's call site never passes
    them, and `generate_image_real` itself only ever passes a DIFFERENT
    canvas than `width`/`height` for a `GENERATION_ONLY` style.

    `prompt_hash` below is keyed on the REQUESTED `width`/`height`, never
    on the canvas size - a decision, not an accident: the request size is
    a real generation input (the provider is asked for different bytes),
    so an existing `GENERATION_ONLY`-style cache row correctly MISSES the
    moment this oversize is introduced, exactly as it would for any other
    change to what is actually requested. The crop itself cannot cause
    two different images to share one hash: it is a pure function of the
    delivered bytes and the canvas size, and the canvas size is fixed by
    the style alone (never itself part of what varies call to call) - so
    a given hash still pins one exact request, and the same request
    (assuming a deterministic provider - already relied on everywhere else
    this cache is used, e.g. the seed/attempt-count arithmetic just above)
    always crops down to the same final bytes.

    Generates once - no retry, no constraint check. The human at the
    one gate is the check now, not an automated vision call that used to
    be able to kill a shot on a false positive (M6.5 -> gate redesign).
    Returns `(clip, cache_hit)` - Task 6 (2026-08-16): `cache_hit` is
    `True` exactly when the returned clip was already on file (a
    `prompt_hash` cache hit, this call spent nothing), `False` when a
    fresh paid generation happened. Callers that only care about the
    clip (the automatic pipeline step) can ignore the second element;
    `/shots/{id}/generate` uses it to report `cost_cents=0` on a cache
    hit rather than the clip row's ORIGINAL charge, which would make a
    free reuse look like a fresh spend.

    Task 3 (2026-08-16): the seed folds in how many `GeneratedClip` rows
    already exist for THIS shot (`GeneratedClipRepository.count_for_shot`),
    not just the project's fixed seed - a human clicking
    `POST /shots/{id}/generate` a second time on the same shot with an
    unchanged prompt must actually re-roll the image, not silently hit
    the cache (identical prompt + identical seed = identical
    `prompt_hash`) and get back the same free result, which is exactly
    what a "generate again" button must never do. Still fully
    DETERMINISTIC (I5, and the render fingerprint depends on it) -
    replaying the same sequence of clicks reproduces the same images,
    every time: the FIRST attempt for a shot (no prior clips) uses the
    bare project seed unchanged (matching A13's own attempt-0 convention
    and preserving the existing cache/dedup behaviour for the ordinary
    "generate once" case - most shots), and every attempt after that
    uses `varied_seed` (A13's deterministic, never-`random` seed
    variation - mirrored here rather than duplicated, see
    `app/assets/constraint_check.py`) keyed on the attempt COUNT, never
    on wall-clock time or `random`."""
    project_seed = _project_seed(str(project_uuid))
    attempt_index = await clip_repo.count_for_shot(project_uuid, shot.id)
    seed = project_seed if attempt_index == 0 else varied_seed(project_seed, attempt_index)

    prompt = base_prompt
    prompt_hash = generation_prompt_hash(prompt, model_id, seed, width=width, height=height)

    cached = await clip_repo.get_by_prompt_hash(prompt_hash)
    if cached is not None:
        return cached, True

    already_spent = await total_project_spend_cents(
        clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
    )
    check_budget(
        already_spent_cents=already_spent,
        additional_cents=settings.fal_image_cost_cents_estimate,
        cap_cents=cap_cents,
    )

    result = await image_provider.generate(
        ImageRequest(prompt=prompt, width=width, height=height, shot_id=shot.id, seed=seed)
    )
    ext, _width_px, _height_px = validate_and_identify_image(result.content)
    content = result.content
    if (
        canvas_width is not None
        and canvas_height is not None
        and (width, height) != (canvas_width, canvas_height)
    ):
        # F1a: crop the substrate margin off before anything downstream
        # ever sees these bytes, then re-derive `ext` from the CROPPED
        # content - a format-preserving crop should not change it, but
        # the persisted file's extension must describe the bytes actually
        # written, not the ones that arrived over the wire.
        content = center_crop_to_canvas(content, canvas_width, canvas_height)
        ext, _width_px, _height_px = validate_and_identify_image(content)
    path = project_dir / "clips" / f"{prompt_hash}.{ext}"
    path.write_bytes(content)
    clip = await clip_repo.insert(
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
    return clip, False


def layer_styled_prompt(
    shot: Shot,
    layer: ShotLayer,
    creative_context: CreativeContext,
    *,
    frame: RenderFormat | None = None,
) -> str:
    """F2b (illustrated_faceless.md §8.5, 2026-09-05): a layer's own
    styled prompt, through the IDENTICAL pipeline (`styled_prompt`) a
    shot's own primary prompt already gets - the `visual_style`
    truncation (the collage bug that function's own docstring measures)
    and the landscape suffix both apply to a layer exactly as they do to
    a shot, since a layer is generated as its own standalone image
    (`ShotLayer.prompt` is a planner-authored creative decision, canon
    3.1 - this function only executes it, never invents one). Built via
    the same `shot.model_copy(update={"prompt": ...})` swap
    `ResolveAssetsStep`'s own secondary-panel resolution already uses,
    not a parallel implementation."""
    layer_shot = shot.model_copy(update={"prompt": layer.prompt})
    return styled_prompt(layer_shot, creative_context, frame=frame)


def _layer_seed(project_seed: int, layer_index: int) -> int:
    """F2b: a fixed, deterministic per-layer seed variation (I5) -
    `varied_seed` reused rather than `_generate_image_once`'s own
    `count_for_shot`-based attempt numbering. A layer is generated
    exactly once per `(shot, layer_index)` by `ResolveAssetsStep` alone -
    there is no per-layer "generate again" endpoint the way a standalone
    shot image has (`POST /shots/{id}/generate`), so there is no attempt
    count to read. Layer 0 (background) keeps the bare project seed,
    matching every other rung's own attempt-0 convention; later layers
    vary from it deterministically - never `random`, never wall-clock."""
    return project_seed if layer_index == 0 else varied_seed(project_seed, layer_index)


def layer_prompt_hash(
    shot: Shot,
    layer: ShotLayer,
    *,
    layer_index: int,
    project_uuid: uuid_module.UUID,
    creative_context: CreativeContext,
    style: str | None = None,
    frame_aspect: str | None = None,
) -> str:
    """F2b: the exact cache key `generate_layer_image_real`/
    `_generate_layer_fake` each compute for one of a shot's `ShotLayer`s -
    exposed so `app/workflow/steps/render.py` can recompute the IDENTICAL
    hash to look an already-resolved layer clip up
    (`GeneratedClipRepository.get_by_prompt_hash`), rather than either
    module owning a second copy of this arithmetic (the R1 lesson every
    other `resolve_*` helper in this codebase already follows - "a single
    function neither call site can bypass is what makes that true").

    No per-layer binding column exists (`ShotBindingModel` gained none for
    this slice - see the plan's own log for why): a layer's resolved clip
    is found purely by recomputing this same hash, never by a stored
    foreign key. This only works because `ResolveAssetsStep` always runs
    before `RenderStep` in the pipeline and both read `settings`
    identically within one process - so the row this recomputes has
    always already been written (or cache-hit) by the time `render.py`
    looks it up.

    Real vs DRY_RUN diverge only in which `model_id`/seed are hashed -
    `settings.dry_run` is the one process-wide flag both sides read."""
    frame = resolve_render_format(style, frame_aspect=frame_aspect)
    request_frame = resolve_generation_request_format(style, frame)
    prompt = layer_styled_prompt(shot, layer, creative_context, frame=frame)
    if settings.dry_run:
        return generation_prompt_hash(
            prompt, "fake_image", width=request_frame.width, height=request_frame.height
        )
    project_seed = _project_seed(str(project_uuid))
    seed = _layer_seed(project_seed, layer_index)
    return generation_prompt_hash(
        prompt,
        settings.fal_image_model,
        seed,
        width=request_frame.width,
        height=request_frame.height,
    )


async def generate_layer_image_real(
    shot: Shot,
    layer: ShotLayer,
    *,
    layer_index: int,
    project_uuid: uuid_module.UUID,
    project_dir,
    image_provider: ImageProvider,
    clip_repo: GeneratedClipRepository,
    narration_repo: NarrationRepository,
    creative_context: CreativeContext,
    cap_cents: int | None = None,
    style: str | None = None,
    frame_aspect: str | None = None,
) -> tuple[GeneratedClipModel, bool]:
    """F2b (illustrated_faceless.md §8.5, 2026-09-05): one of a shot's
    `ShotLayer`s, generated exactly like a standalone shot image
    (`generate_image_real`) - same budget check
    (`check_budget`/`total_project_spend_cents`), same clip repository,
    same content hashing (`layer_prompt_hash`), same F1a substrate crop
    (§4.3: layers are paid generations and must be counted like any
    other, never a free or uncounted side channel). A dedicated entry
    point rather than a call into `generate_image_real` with a swapped
    prompt because the SEED differs (`_layer_seed`, not
    `_generate_image_once`'s own attempt-count convention - see that
    function's own docstring for why layers do not use it).

    **Never routes through the Asset Planner** (§3.2's reasoning
    generalised one level: `ShotLayer.asset_plan` is never authored - see
    that field's own docstring - so "generate this image" is the only
    acquisition path a layer ever has, decided in code, never asked of an
    LLM that was never given the choice in the first place)."""
    frame = resolve_render_format(style, frame_aspect=frame_aspect)
    request_frame = resolve_generation_request_format(style, frame)
    prompt = layer_styled_prompt(shot, layer, creative_context, frame=frame)
    prompt_hash = layer_prompt_hash(
        shot,
        layer,
        layer_index=layer_index,
        project_uuid=project_uuid,
        creative_context=creative_context,
        style=style,
        frame_aspect=frame_aspect,
    )

    cached = await clip_repo.get_by_prompt_hash(prompt_hash)
    if cached is not None:
        return cached, True

    already_spent = await total_project_spend_cents(
        clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
    )
    check_budget(
        already_spent_cents=already_spent,
        additional_cents=settings.fal_image_cost_cents_estimate,
        cap_cents=cap_cents,
    )

    project_seed = _project_seed(str(project_uuid))
    seed = _layer_seed(project_seed, layer_index)
    result = await image_provider.generate(
        ImageRequest(
            prompt=prompt,
            width=request_frame.width,
            height=request_frame.height,
            shot_id=shot.id,
            seed=seed,
        )
    )
    ext, _width_px, _height_px = validate_and_identify_image(result.content)
    content = result.content
    if (request_frame.width, request_frame.height) != (frame.width, frame.height):
        content = center_crop_to_canvas(content, frame.width, frame.height)
        ext, _width_px, _height_px = validate_and_identify_image(content)
    path = project_dir / "clips" / f"{prompt_hash}.{ext}"
    path.write_bytes(content)
    clip = await clip_repo.insert(
        project_id=project_uuid,
        shot_id=shot.id,
        provider=image_provider.name,
        model_id=settings.fal_image_model,
        prompt=prompt,
        prompt_hash=prompt_hash,
        duration_s=None,
        local_path=str(path),
        cost_cents=settings.fal_image_cost_cents_estimate,
    )
    return clip, False


async def _generate_layer_fake(
    shot: Shot,
    layer: ShotLayer,
    *,
    layer_index: int,
    project_uuid: uuid_module.UUID,
    project_dir,
    image_provider: ImageProvider,
    clip_repo: GeneratedClipRepository,
    creative_context: CreativeContext,
    style: str | None = None,
    frame_aspect: str | None = None,
) -> GeneratedClipModel:
    """DRY_RUN counterpart to `generate_layer_image_real` - mirrors
    `_generate_fake`'s own unchecked, cost-0 shape exactly:
    `FakeImageProvider` never spends anything real, so there is nothing
    to budget-check here, only a cache to populate (still through the
    same `layer_prompt_hash` every other layer path reads)."""
    frame = resolve_render_format(style, frame_aspect=frame_aspect)
    request_frame = resolve_generation_request_format(style, frame)
    prompt = layer_styled_prompt(shot, layer, creative_context, frame=frame)
    prompt_hash = layer_prompt_hash(
        shot,
        layer,
        layer_index=layer_index,
        project_uuid=project_uuid,
        creative_context=creative_context,
        style=style,
        frame_aspect=frame_aspect,
    )
    clip = await clip_repo.get_by_prompt_hash(prompt_hash)
    if clip is not None:
        return clip

    result = await image_provider.generate(
        ImageRequest(
            prompt=prompt, width=request_frame.width, height=request_frame.height, shot_id=shot.id
        )
    )
    content = result.content
    if (request_frame.width, request_frame.height) != (frame.width, frame.height):
        content = center_crop_to_canvas(content, frame.width, frame.height)
    path = project_dir / "clips" / f"{prompt_hash}.png"
    path.write_bytes(content)
    return await clip_repo.insert(
        project_id=project_uuid,
        shot_id=shot.id,
        provider=image_provider.name,
        model_id="fake-image-v1",
        prompt=prompt,
        prompt_hash=prompt_hash,
        duration_s=None,
        local_path=str(path),
        cost_cents=0,
    )


async def _generate_keyframe_once(
    shot: Shot,
    *,
    base_prompt: str,
    project_uuid: uuid_module.UUID,
    width: int,
    height: int,
    model_id: str,
    image_provider: ImageProvider,
    clip_repo: GeneratedClipRepository,
    narration_repo: NarrationRepository,
    cap_cents: int | None = None,
) -> ImageResult:
    """The video path's keyframe generation, brought onto the one-gate
    model (motion_new_styles_and_long_form_videos.md Track A's A5,
    2026-08-18): a single, unchecked generate call - no constraint check, no bounded
    retry - mirroring `_generate_image_once` above exactly, the identical
    treatment the standalone image path already got in the 2026-08-16
    gate redesign. Before this change a video shot's keyframe could still
    be killed outright by a constraint violation (the exact German-tank-
    shot failure that motivated the redesign in the first place) even
    though the standalone image path could not; this closes that gap
    rather than inventing a third behaviour for video specifically. The
    human at the review gate is the check now, for a keyframe exactly as
    it already is for a standalone image.

    Unlike `_generate_image_once`, a passing keyframe is still never
    persisted as its own `GeneratedClip` row - its cost is folded into
    the video job's own bundled estimate exactly as before this change
    (see `_generate_video_real`), so nothing double-counts."""
    project_seed = _project_seed(str(project_uuid))
    already_spent = await total_project_spend_cents(
        clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
    )
    check_budget(
        already_spent_cents=already_spent,
        additional_cents=settings.fal_image_cost_cents_estimate,
        cap_cents=cap_cents,
    )
    return await image_provider.generate(
        ImageRequest(
            prompt=base_prompt, width=width, height=height, shot_id=shot.id, seed=project_seed
        )
    )


async def poll_video_job(
    shot: Shot,
    binding,
    *,
    project_uuid: uuid_module.UUID,
    project_dir,
    video_provider: VideoProvider,
    clip_repo: GeneratedClipRepository,
) -> GeneratedClipModel | None:
    """Poll the in-flight video job for this shot exactly once - the
    submit-and-poll resume path M7 already built (`get_in_flight_for_
    shot` -> `poll` -> `in_progress`/`failed`/`completed`), extracted as
    its own module-level function (Track A's A6, motion_new_styles_and_
    long_form_videos.md, 2026-08-18) so both `ResolveAssetsStep`'s
    automatic pass (via `generate_video_real` below) and `GET /{project_
    id}/shots/{shot_id}/generate/video` call the IDENTICAL logic - never
    two implementations of "what does polling mean" drifting apart.

    `None` means there is nothing in flight for this shot at all - the
    workflow step's own caller falls through to `submit_video_generation`
    in that case (nothing submitted yet is exactly when a fresh
    submission is correct there); the GET endpoint's caller must NOT do
    that (a GET must never have the side effect of a fresh, paid
    submission - that is what POST is for) and 404s instead."""
    in_flight = await clip_repo.get_in_flight_for_shot(project_uuid, shot.id)
    if in_flight is None:
        return None

    assert in_flight.job_id is not None
    status = await video_provider.poll(in_flight.job_id)
    if status.state == "in_progress":
        return in_flight  # still going - binding stays "pending", a later call polls again
    if status.state == "failed":
        await clip_repo.mark_failed(in_flight, error=status.error or "video generation failed")
        binding.state = "failed"
        binding.last_error = status.error or "video generation failed"
        return in_flight

    assert status.content is not None
    path = project_dir / "clips" / f"{in_flight.prompt_hash}.mp4"
    path.write_bytes(status.content)
    await clip_repo.mark_completed(
        in_flight, local_path=str(path), duration_s=shot.duration_s, cost_cents=in_flight.cost_cents
    )
    binding.clip_id = in_flight.id
    binding.state = "generated"
    binding.rung = AssetStrategy.GENERATE_VIDEO.value
    return in_flight


async def submit_video_generation(
    shot: Shot,
    binding,
    *,
    project_uuid: uuid_module.UUID,
    project_dir,
    image_provider: ImageProvider,
    video_provider: VideoProvider,
    clip_repo: GeneratedClipRepository,
    narration_repo: NarrationRepository,
    creative_context: CreativeContext,
    cap_cents: int | None = None,
    style: str | None = None,
    frame_aspect: str | None = None,
) -> tuple[GeneratedClipModel, bool]:
    """`POST /{project_id}/shots/{shot_id}/generate/video`'s own logic
    (Track A's A6, 2026-08-18), module-level so the endpoint calls it
    directly - one generation, no engine, no workflow trigger involved,
    mirroring `generate_image_real`'s own reasoning exactly (a human at
    the review gate may click across several shots before approving
    anything; resuming the engine on each click would race the pipeline
    forward mid-review).

    Idempotent by construction rather than by a special case bolted on
    for the endpoint: a completed cache hit or an already-in-flight job
    for this shot is returned as-is - never a double submission, the
    same M7 invariant `poll_video_job` depends on - and only a shot with
    neither generates a fresh keyframe (`_generate_keyframe_once`, the
    one-gate model, A5) and submits it. Returns `(clip, is_fresh)` -
    `is_fresh` is `True` only when THIS call actually generated a
    keyframe and submitted a new job, the video-path equivalent of
    `generate_image_real`'s own `cache_hit` (inverted: that flag means
    "reused", this one means "the DECIDED-2026-08-18 blocking POST
    actually did the ~few-seconds keyframe generation just now" - see
    A6's own note in the plan for why that is unremarkable, not a design
    smell)."""
    frame = resolve_render_format(style, frame_aspect=frame_aspect)
    prompt = styled_prompt(shot, creative_context, frame=frame)
    prompt_hash = generation_prompt_hash(
        prompt, settings.fal_video_model, width=frame.width, height=frame.height
    )

    cached = await clip_repo.get_by_prompt_hash(prompt_hash)
    if cached is not None and cached.status == "completed":
        binding.clip_id = cached.id
        binding.state = "generated"
        binding.rung = AssetStrategy.GENERATE_VIDEO.value
        return cached, False

    in_flight = await clip_repo.get_in_flight_for_shot(project_uuid, shot.id)
    if in_flight is not None:
        binding.state = "pending"
        return in_flight, False

    # Fresh submission: an unchecked, single-attempt keyframe first (A5,
    # one-gate model), THEN the video job itself (submit-and-poll,
    # resumable).
    keyframe = await _generate_keyframe_once(
        shot,
        base_prompt=prompt,
        project_uuid=project_uuid,
        width=frame.width,
        height=frame.height,
        model_id=settings.fal_image_model,
        image_provider=image_provider,
        clip_repo=clip_repo,
        narration_repo=narration_repo,
        cap_cents=cap_cents,
    )
    if keyframe.hosted_url is None:
        raise PermanentError(
            f"{image_provider.name} did not return a hosted URL required for "
            "image-to-video generation"
        )

    # The keyframe's cost is folded into this one bundled estimate
    # (rather than tracked as its own row) precisely because a PASSING
    # keyframe attempt is never persisted separately above - see
    # `_generate_keyframe_once`'s docstring.
    estimated_cents = (
        settings.fal_image_cost_cents_estimate + settings.fal_video_cost_cents_estimate
    )
    already_spent = await total_project_spend_cents(
        clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
    )
    check_budget(
        already_spent_cents=already_spent,
        additional_cents=estimated_cents,
        cap_cents=cap_cents,
    )

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
    clip = await clip_repo.insert_pending(
        project_id=project_uuid,
        shot_id=shot.id,
        provider=video_provider.name,
        model_id=settings.fal_video_model,
        prompt=prompt,
        prompt_hash=prompt_hash,
        job_id=job_id,
        estimated_cost_cents=estimated_cents,
    )
    # binding.state stays "pending" (non-terminal) - a later call polls
    # the job above (`poll_video_job`) rather than resubmitting it.
    binding.state = "pending"
    return clip, True


async def generate_video_real(
    shot: Shot,
    binding,
    *,
    project_uuid: uuid_module.UUID,
    project_dir,
    image_provider: ImageProvider,
    video_provider: VideoProvider,
    clip_repo: GeneratedClipRepository,
    narration_repo: NarrationRepository,
    creative_context: CreativeContext,
    cap_cents: int | None = None,
    style: str | None = None,
    frame_aspect: str | None = None,
) -> None:
    """`ResolveAssetsStep`'s per-attempt entrypoint for a video shot -
    poll first (`poll_video_job`; advances a job already in flight from a
    prior attempt/process), and only submit fresh (`submit_video_
    generation`) when nothing is in flight. `poll_video_job` only ever
    matches a truly IN-FLIGHT row (`submitted`/`in_progress`), never a
    `completed` one, so a shot that is already done correctly falls
    through to `submit_video_generation`'s own cache-hit check instead of
    being polled - the ordering here does not depend on checking
    "already completed" twice."""
    polled = await poll_video_job(
        shot,
        binding,
        project_uuid=project_uuid,
        project_dir=project_dir,
        video_provider=video_provider,
        clip_repo=clip_repo,
    )
    if polled is not None:
        return
    await submit_video_generation(
        shot,
        binding,
        project_uuid=project_uuid,
        project_dir=project_dir,
        image_provider=image_provider,
        video_provider=video_provider,
        clip_repo=clip_repo,
        narration_repo=narration_repo,
        creative_context=creative_context,
        cap_cents=cap_cents,
        style=style,
        frame_aspect=frame_aspect,
    )


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
        if not all(
            bindings[s.id].state in self._done_states
            and secondary_panel_done(s, bindings[s.id], done_states=self._done_states)
            for s in shots
        ):
            return False
        # F2b, fixed 2026-09-05 after a real run produced ZERO layer
        # images: a shot's LAYERS have no binding row to read a state
        # from (see `layer_prompt_hash`'s docstring for why there is no
        # per-layer column), so a binding-only check reported this step
        # satisfied while every layer was still ungenerated - and because
        # `is_satisfied` short-circuits the whole step, `run()`'s own
        # `needs_layers` revisit never executed. That is not a narrow
        # window: the approval gate REQUIRES every shot resolved before
        # it will approve, so on the real path this branch is always
        # taken and layers could never generate at all. Measured on
        # project 8897321f: 9 primaries, 0 of 8 layers, 42c instead of
        # 74c, and a "parallax" film with no parallax in it - the
        # renderer's own missing-input degrade quietly produced stills.
        #
        # Checked the same way `render.py` finds an already-resolved
        # layer: recompute the identical `layer_prompt_hash` and look for
        # its clip. Gated on `_generation_permitted` so the search-only
        # pass is unaffected (layers are GENERATION_ONLY by construction,
        # never a search rung) - the same gate `run()`'s `needs_layers`
        # uses, so the two cannot disagree about what this pass owes.
        if not self._generation_permitted:
            return True
        clip_repo = GeneratedClipRepository(ctx.session)
        for shot in shots:
            for index, layer in enumerate(shot.layers):
                phash = layer_prompt_hash(
                    shot,
                    layer,
                    layer_index=index,
                    project_uuid=uuid_module.UUID(ctx.project_id),
                    creative_context=timeline.creative_context,
                    style=timeline.metadata.render_style,
                    frame_aspect=timeline.metadata.frame_aspect,
                )
                clip = await clip_repo.get_by_prompt_hash(phash)
                if clip is None or not clip.local_path or not Path(clip.local_path).exists():
                    return False
        return True

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
        # M6.5, A12/A30: `None` in DRY_RUN, same idiom as every other real
        # provider above - both `check_generated_image_constraints` (A12,
        # generated media) and `check_candidate_plausibility` (A30,
        # searched media) treat a `None` provider as "nothing to call".
        # Unlike the generation-only providers below, this one is needed
        # by BOTH passes now (A30 runs in the search pass, A12 in the
        # generation pass), so it is no longer gated on
        # `self._generation_permitted` - it is constructed whenever this
        # is a real (non-DRY_RUN) run at all.
        vision_provider: VisionConstraintProvider | None = (
            None if settings.dry_run else OpenAIPlanningProvider()
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
        cap_cents = budget_cap_cents_for(timeline)
        window_s = reuse_window_s(timeline.metadata.render_style)
        start_times = compute_shot_start_times(timeline.all_shots())
        used_at_s = await self._seed_used_at(
            binding_repo=binding_repo,
            asset_repo=asset_repo,
            project_uuid=project_uuid,
            timeline_version=timeline.version,
            start_times=start_times,
        )

        pending: list[_PendingShot] = []
        for shot in timeline.all_shots():
            binding = await binding_repo.get_or_create_pending(
                project_uuid, timeline.version, shot.id
            )
            needs_secondary = not secondary_panel_done(shot, binding, done_states=self._done_states)
            # illustrated_faceless.md F2b (2026-09-05): a shot's layers
            # have no binding column of their own (§3.2's generation-only
            # enforcement generalised - a layer never searches, so there
            # is no per-layer state machine to track, only "generate it,
            # cache-hit if it's already there" - see `_resolve_layers`).
            # So a shot whose PRIMARY binding is already terminal must
            # still be revisited here whenever it carries layers and this
            # pass permits generation - otherwise a crash between the
            # primary resolving and its layers generating would leave the
            # layers unresolved forever (the `continue` below would skip
            # this shot on every future run). Gated on
            # `self._generation_permitted` so the search-only pass never
            # touches a shot's layers at all - layers are GENERATION_ONLY
            # by construction, never a search rung.
            needs_layers = bool(shot.layers) and self._generation_permitted
            if binding.state in self._done_states and not needs_secondary and not needs_layers:
                continue
            pending.append(
                _PendingShot(
                    shot=shot,
                    binding=binding,
                    needs_secondary=needs_secondary,
                    shot_start=start_times.get(shot.id, 0.0),
                )
            )

        # Search I/O overlaps across shots; rank/bind below stays serial
        # so reuse_gap_s sees earlier picks in timeline order (C4).
        prefetched: (
            list[tuple[list[_PrefetchedRung], list[_PrefetchedRung] | None] | Exception] | None
        ) = None
        if (
            pending
            and not settings.dry_run
            and self._search_permitted
            and search_providers is not None
        ):
            db_lock = asyncio.Lock()

            async def _prefetch_pending(
                item: _PendingShot,
            ) -> tuple[list[_PrefetchedRung], list[_PrefetchedRung] | None]:
                primary = await self._prefetch_search_rungs(
                    item.shot,
                    search_providers=search_providers,
                    entity_provider=entity_provider,
                    creative_context=timeline.creative_context,
                    db_lock=db_lock,
                )
                secondary_rungs: list[_PrefetchedRung] | None = None
                if item.needs_secondary:
                    panel_shot = item.shot.model_copy(
                        update={
                            "prompt": item.shot.secondary_prompt,
                            "asset_plan": item.shot.secondary_asset_plan,
                        }
                    )
                    secondary_rungs = await self._prefetch_search_rungs(
                        panel_shot,
                        search_providers=search_providers,
                        entity_provider=entity_provider,
                        creative_context=timeline.creative_context,
                        db_lock=db_lock,
                    )
                return primary, secondary_rungs

            prefetched = await bounded_gather(
                pending,
                _prefetch_pending,
                concurrency=asset_search_concurrency(),
            )

        for index, item in enumerate(pending):
            shot = item.shot
            binding = item.binding
            needs_secondary = item.needs_secondary
            shot_start = item.shot_start
            try:
                if binding.state not in self._done_states and settings.dry_run:
                    await self._resolve_one_fake(
                        shot,
                        binding,
                        project_uuid=project_uuid,
                        project_dir=project_dir,
                        asset_provider=fake_asset_provider,
                        image_provider=image_provider,
                        asset_repo=asset_repo,
                        clip_repo=clip_repo,
                        style=timeline.metadata.render_style,
                        frame_aspect=timeline.metadata.frame_aspect,
                    )
                elif binding.state not in self._done_states:
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
                        reuse_gap_s=reuse_gaps_s(used_at_s, shot_start),
                        window_s=window_s,
                        cap_cents=cap_cents,
                        style=timeline.metadata.render_style,
                        frame_aspect=timeline.metadata.frame_aspect,
                        prefetched_rungs=(
                            None
                            if prefetched is None
                            else _raise_if_prefetch_failed(prefetched[index])[0]
                        ),
                    )
                    if used_hash is not None:
                        used_at_s.setdefault(used_hash, []).append(shot_start)
                if needs_secondary:
                    panel_shot = shot.model_copy(
                        update={
                            "prompt": shot.secondary_prompt,
                            "asset_plan": shot.secondary_asset_plan,
                        }
                    )
                    # R19: unattached ORM row, not a duck type. Same
                    # attribute surface as a real binding (`shot_id`
                    # included). Never `session.add`'d — flush would
                    # collide with the unique constraint.
                    scratch = ShotBindingModel(
                        project_id=project_uuid,
                        timeline_version=timeline.version,
                        shot_id=shot.id,
                        state="pending",
                    )
                    try:
                        if settings.dry_run:
                            await self._resolve_one_fake(
                                panel_shot,
                                scratch,
                                project_uuid=project_uuid,
                                project_dir=project_dir,
                                asset_provider=fake_asset_provider,
                                image_provider=image_provider,
                                asset_repo=asset_repo,
                                clip_repo=clip_repo,
                                style=timeline.metadata.render_style,
                                frame_aspect=timeline.metadata.frame_aspect,
                            )
                            used_hash = None
                        else:
                            used_hash = await self._resolve_one_real(
                                panel_shot,
                                scratch,
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
                                reuse_gap_s=reuse_gaps_s(used_at_s, shot_start),
                                window_s=window_s,
                                cap_cents=cap_cents,
                                style=timeline.metadata.render_style,
                                frame_aspect=timeline.metadata.frame_aspect,
                                prefetched_rungs=(
                                    None
                                    if prefetched is None
                                    else _raise_if_prefetch_failed(prefetched[index])[1]
                                ),
                            )
                        binding.secondary_asset_id = scratch.asset_id
                        binding.secondary_clip_id = scratch.clip_id
                        binding.secondary_state = scratch.state
                        binding.secondary_last_error = scratch.last_error
                        binding.cost_cents = (binding.cost_cents or 0) + (scratch.cost_cents or 0)
                        if used_hash is not None:
                            used_at_s.setdefault(used_hash, []).append(shot_start)
                    except TransientError as exc:
                        logger.warning(
                            "resolve_assets.secondary_transient",
                            extra={"shot_id": shot.id, "error": str(exc)},
                        )
                        binding.secondary_last_error = str(exc)
                    except Exception as exc:  # noqa: BLE001 - isolate, do not erase
                        logger.warning(
                            "resolve_assets.secondary_failed",
                            extra={"shot_id": shot.id, "error": str(exc)},
                        )
                        binding.secondary_state = "failed"
                        binding.secondary_last_error = str(exc)
                if shot.layers and self._generation_permitted:
                    # F2b: its own try/except, same isolation reasoning as
                    # the secondary-panel block above - a failed LAYER
                    # must never mark the whole shot `failed` (its primary
                    # media may already be perfectly good); it degrades
                    # that shot's parallax composite to a plain image
                    # instead (`should_composite_parallax`'s own
                    # missing-input rule), never the render itself.
                    try:
                        await self._resolve_layers(
                            shot,
                            project_uuid=project_uuid,
                            project_dir=project_dir,
                            image_provider=image_provider,
                            clip_repo=clip_repo,
                            narration_repo=narration_repo,
                            creative_context=timeline.creative_context,
                            cap_cents=cap_cents,
                            style=timeline.metadata.render_style,
                            frame_aspect=timeline.metadata.frame_aspect,
                        )
                    except TransientError as exc:
                        logger.warning(
                            "resolve_assets.layer_transient",
                            extra={"shot_id": shot.id, "error": str(exc)},
                        )
                    except Exception as exc:  # noqa: BLE001 - isolate, do not erase
                        logger.warning(
                            "resolve_assets.layer_failed",
                            extra={"shot_id": shot.id, "error": str(exc)},
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
        # rather than blocking the other fifty-nine. This is also what
        # makes A22 true: even if every shot's search raised, the step
        # still returns "ok" and the run reaches the approval gate.
        await self._prewarm_video_frames(ctx, timeline)
        return StepResult(outcome="ok")

    async def _prewarm_video_frames(self, ctx: RunContext, timeline) -> None:
        """§13.6: extract the review-gate still now, while this process
        is already doing media work. Failures are swallowed — a miss
        just means `GET /asset` extracts lazily, the way it always did.
        """
        project_uuid = uuid_module.UUID(ctx.project_id)
        bindings = await ShotBindingRepository(ctx.session).list_for_version(
            project_uuid, timeline.version
        )
        for binding in bindings:
            path: Path | None = None
            if binding.asset_id is not None:
                asset = await ctx.session.get(AssetModel, binding.asset_id)
                if asset is not None and asset.local_path:
                    path = Path(asset.local_path)
            elif binding.clip_id is not None:
                clip = await ctx.session.get(GeneratedClipModel, binding.clip_id)
                if clip is not None and clip.local_path:
                    path = Path(clip.local_path)
            if path is None or not path.exists() or not is_video_file(path):
                continue
            try:
                await cached_video_frame(
                    path,
                    shot_frame_cache_path(ctx.project_id, binding.shot_id),
                    ffmpeg_binary=settings.ffmpeg_binary,
                    ffprobe_binary=settings.ffprobe_binary,
                )
            except Exception:  # noqa: BLE001 - pre-warm must not fail the step
                continue

    async def _seed_used_at(
        self,
        *,
        binding_repo: ShotBindingRepository,
        asset_repo: AssetRepository,
        project_uuid: uuid_module.UUID,
        timeline_version: int,
        start_times: dict[str, float],
    ) -> dict[str, list[float]]:
        """C4: content_hash -> start times of already-resolved shots.

        Generated clips are not in this map (ranking is a search-pool
        penalty). A later shot's binding must not penalise an earlier
        one — `reuse_gaps_s` keeps only times strictly before the shot
        being ranked.
        """
        used_at: dict[str, list[float]] = {}
        bindings = await binding_repo.list_for_version(project_uuid, timeline_version)
        asset_ids = [b.asset_id for b in bindings if b.asset_id is not None]
        hash_by_id = await asset_repo.content_hashes_for_ids(asset_ids)
        for binding in bindings:
            if binding.asset_id is None:
                continue
            content_hash = hash_by_id.get(binding.asset_id)
            start = start_times.get(binding.shot_id)
            if content_hash is None or start is None:
                continue
            used_at.setdefault(content_hash, []).append(start)
        return used_at

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
        style: str | None = None,
        frame_aspect: str | None = None,
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
            style=style,
            frame_aspect=frame_aspect,
        )

    async def _prefetch_search_rungs(
        self,
        shot: Shot,
        *,
        search_providers: dict[AssetStrategy, AssetProvider],
        entity_provider: WikipediaEntityAssetProvider | None,
        creative_context: CreativeContext,
        db_lock: asyncio.Lock | None,
    ) -> list[_PrefetchedRung]:
        """Search + download + licence/relevance gates. No ranking — that
        needs reuse_gap_s from earlier binds, so it stays serial."""
        asset_plan = shot.asset_plan
        chain = asset_plan.fallback_chain if asset_plan else []
        licence_requirements = set(asset_plan.licence_requirements) if asset_plan else set()
        search_terms = (asset_plan.search_queries if asset_plan else []) or [shot.id]
        entity = (asset_plan.entity if asset_plan else "").strip()
        entity_candidates: list[AssetCandidate] = []
        entity_candidates_fetched = False
        rungs: list[_PrefetchedRung] = []

        for strategy in chain:
            if strategy not in _SEARCH_STRATEGIES:
                break
            if strategy not in self._permitted_strategies:
                continue
            if strategy not in search_providers:
                continue
            provider = search_providers[strategy]
            query = AssetQuery(
                search_terms=asset_plan.search_queries if asset_plan else [],
                preferred_type=asset_plan.preferred_type.value if asset_plan else "image",
                shot_id=shot.id,
                historical_period=creative_context.historical_period,
            )
            if strategy == AssetStrategy.PROJECT_ASSETS and db_lock is not None:
                async with db_lock:
                    candidates = await provider.search(query)
            else:
                candidates = await provider.search(query)

            entity_eligible_rung = strategy in _ENTITY_ELIGIBLE_STRATEGIES
            if entity and not entity_candidates_fetched and entity_eligible_rung:
                assert entity_provider is not None
                entity_candidates = await entity_provider.resolve_entity(entity)
                entity_candidates_fetched = True

            pool = candidates + (entity_candidates if entity_eligible_rung else [])
            eligible = (
                pool
                if strategy == AssetStrategy.PROJECT_ASSETS
                else [
                    c for c in pool if not licence_requirements or c.licence in licence_requirements
                ]
            )
            if not eligible:
                continue
            relevant = [
                c for c in eligible if passes_relevance_gate(candidate_relevance(search_terms, c))
            ]
            if not relevant:
                continue

            fetched_candidates: list[tuple[AssetCandidate, str, bytes, str]] = []
            for candidate in relevant[:_CANDIDATES_TO_FETCH_PER_RUNG]:
                fetched = await provider.fetch(candidate)
                content_hash = hashlib.sha256(fetched.content).hexdigest()
                fetched_candidates.append(
                    (candidate, content_hash, fetched.content, fetched.attribution)
                )

            seen_hashes: set[str] = set()
            deduped: list[tuple[AssetCandidate, str, bytes, str]] = []
            for entry in fetched_candidates:
                if entry[1] in seen_hashes:
                    continue
                seen_hashes.add(entry[1])
                deduped.append(entry)
            if not deduped:
                continue
            rungs.append(
                _PrefetchedRung(
                    strategy=strategy,
                    provider_name=provider.name,
                    entity_provider_name=(
                        entity_provider.name if entity_provider is not None else None
                    ),
                    entries=deduped,
                )
            )
        return rungs

    async def _pick_from_rungs(
        self,
        shot: Shot,
        binding,
        *,
        rungs: list[_PrefetchedRung],
        search_terms: list[str],
        project_uuid: uuid_module.UUID,
        project_dir,
        vision_provider: VisionConstraintProvider | None,
        asset_repo: AssetRepository,
        llm_call_repo: LlmCallRepository,
        creative_context: CreativeContext,
        reuse_gap_s: dict[str, float],
        window_s: float,
        style: str | None,
        frame_aspect: str | None,
    ) -> str | None:
        frame = resolve_render_format(style, frame_aspect=frame_aspect)
        for rung in rungs:
            ranked = rank_candidates(
                [(c, h) for c, h, _, _ in rung.entries],
                search_terms=search_terms,
                historical_period=creative_context.historical_period,
                reuse_gap_s=reuse_gap_s,
                window_s=window_s,
                shot_id=shot.id,
                target_width=frame.width,
                target_height=frame.height,
            )
            by_hash = {h: (c, content, attribution) for c, h, content, attribution in rung.entries}
            checked_top_candidate = False
            for rank_result in ranked:
                candidate, content, attribution = by_hash[rank_result.content_hash]
                existing = await asset_repo.get_by_content_hash(
                    project_uuid, rank_result.content_hash
                )
                if existing is not None:
                    binding.asset_id = existing.id
                    binding.state = "resolved"
                    binding.rung = rung.strategy.value
                    return rank_result.content_hash

                is_video_candidate = candidate.media_kind == "video"
                try:
                    if is_video_candidate:
                        ext, _width, _height = await validate_and_identify_video(
                            content, ffprobe_binary=settings.ffprobe_binary
                        )
                    else:
                        ext, _width, _height = validate_and_identify_image(content)
                except PermanentError:
                    continue

                vision_focal: tuple[float, float] | None = None
                if not checked_top_candidate and not is_video_candidate:
                    checked_top_candidate = True
                    if not candidate.entity_curated:
                        verdict = await check_candidate_plausibility(
                            provider=vision_provider,
                            llm_call_repo=llm_call_repo,
                            project_id=project_uuid,
                            image=content,
                            image_content_type=mime_type_for_extension(ext),
                            shot_prompt=shot.prompt,
                            search_subject=" / ".join(search_terms),
                        )
                        if verdict.confidently_wrong:
                            break
                        # OQ-2 (re-cut 2026-08-29): a SECOND call, on a
                        # stronger model. It used to ride along on the
                        # verdict above, whose cheap model returned a
                        # defaulted (0.5, 0.5) for 11 of 12 real assets -
                        # indistinguishable from a real centre answer, and
                        # written to disk as one. `None` here means "no
                        # usable answer"; the sidecar below records that
                        # honestly instead of inventing a centre.
                        vision_focal = await locate_subject_focal(
                            provider=vision_provider,
                            llm_call_repo=llm_call_repo,
                            project_id=project_uuid,
                            image=content,
                            image_content_type=mime_type_for_extension(ext),
                            shot_id=shot.id,
                        )

                path = project_dir / "assets" / f"{rank_result.content_hash}.{ext}"
                path.write_bytes(content)
                if vision_focal is not None:
                    persist_vision_focal(
                        project_dir / "assets",
                        rank_result.content_hash,
                        focal_x=vision_focal[0],
                        focal_y=vision_focal[1],
                        shot_id=shot.id,
                    )
                found_by = (
                    rung.entity_provider_name
                    if candidate.entity_curated and rung.entity_provider_name is not None
                    else rung.provider_name
                )
                asset = await asset_repo.insert(
                    project_id=project_uuid,
                    provider=found_by,
                    source_url=candidate.source_url,
                    type=candidate.media_kind,
                    local_path=str(path),
                    licence=candidate.licence,
                    attribution=attribution or candidate.author or None,
                    content_hash=rank_result.content_hash,
                    confidence=rank_result.score,
                )
                binding.asset_id = asset.id
                binding.state = "resolved"
                binding.rung = rung.strategy.value
                return rank_result.content_hash
        return None

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
        reuse_gap_s: dict[str, float],
        window_s: float,
        cap_cents: int | None = None,
        style: str | None = None,
        frame_aspect: str | None = None,
        prefetched_rungs: list[_PrefetchedRung] | None = None,
    ) -> str | None:
        """Walks the shot's fallback_chain across real search providers,
        restricted to `self._permitted_strategies`. Returns the
        content_hash it resolved to (for reuse-penalty tracking across
        the rest of this run), or None if it deferred to the generation
        pass or fell through to generation itself.

        `prefetched_rungs` is the search I/O already done in parallel
        across shots; ranking still happens here so reuse can see
        earlier picks. `None` means fetch now (generation pass, or a
        caller that did not prefetch).
        """
        asset_plan = shot.asset_plan
        search_terms = (asset_plan.search_queries if asset_plan else []) or [shot.id]

        if self._search_permitted:
            rungs = prefetched_rungs
            if rungs is None:
                assert search_providers is not None
                rungs = await self._prefetch_search_rungs(
                    shot,
                    search_providers=search_providers,
                    entity_provider=entity_provider,
                    creative_context=creative_context,
                    db_lock=None,
                )
            picked = await self._pick_from_rungs(
                shot,
                binding,
                rungs=rungs,
                search_terms=search_terms,
                project_uuid=project_uuid,
                project_dir=project_dir,
                vision_provider=vision_provider,
                asset_repo=asset_repo,
                llm_call_repo=llm_call_repo,
                creative_context=creative_context,
                reuse_gap_s=reuse_gap_s,
                window_s=window_s,
                style=style,
                frame_aspect=frame_aspect,
            )
            if picked is not None:
                return picked

        if not self._generation_permitted:
            # A5/A6/A21: this pass may only search - every permitted rung
            # came up empty (or none were permitted at all), so defer to
            # the paid pass rather than generate here.
            binding.state = "awaiting_generation"
            return None

        assert image_provider is not None and video_provider is not None
        is_video = bool(asset_plan and asset_plan.preferred_type == PreferredMediaType.VIDEO)
        if is_video:
            await generate_video_real(
                shot,
                binding,
                project_uuid=project_uuid,
                project_dir=project_dir,
                image_provider=image_provider,
                video_provider=video_provider,
                clip_repo=clip_repo,
                narration_repo=narration_repo,
                creative_context=creative_context,
                cap_cents=cap_cents,
                style=style,
                frame_aspect=frame_aspect,
            )
        else:
            await generate_image_real(
                shot,
                binding,
                project_uuid=project_uuid,
                project_dir=project_dir,
                image_provider=image_provider,
                clip_repo=clip_repo,
                narration_repo=narration_repo,
                creative_context=creative_context,
                cap_cents=cap_cents,
                style=style,
                frame_aspect=frame_aspect,
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
        style: str | None = None,
        frame_aspect: str | None = None,
    ) -> None:
        frame = resolve_render_format(style, frame_aspect=frame_aspect)
        # F1a: exercised in DRY_RUN too (not just real generation) - the
        # crop is a no-op quality-wise against `FakeImageProvider` (its
        # output never carries a substrate margin), but requesting the
        # oversized size and cropping back is the same mechanism either
        # way, so DRY_RUN/unit tests exercise the real dimension
        # arithmetic rather than a second, untested code path.
        request_frame = resolve_generation_request_format(style, frame)
        result = await image_provider.generate(
            ImageRequest(
                prompt=shot.prompt,
                width=request_frame.width,
                height=request_frame.height,
                shot_id=shot.id,
            )
        )
        content = result.content
        if (request_frame.width, request_frame.height) != (frame.width, frame.height):
            content = center_crop_to_canvas(content, frame.width, frame.height)
        prompt_hash = generation_prompt_hash(
            shot.prompt,
            image_provider.name,
            width=request_frame.width,
            height=request_frame.height,
        )
        clip = await clip_repo.get_by_prompt_hash(prompt_hash)
        if clip is None:
            path = project_dir / "clips" / f"{prompt_hash}.png"
            path.write_bytes(content)
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

    async def _resolve_layers(
        self,
        shot: Shot,
        *,
        project_uuid: uuid_module.UUID,
        project_dir,
        image_provider: ImageProvider | None,
        clip_repo: GeneratedClipRepository,
        narration_repo: NarrationRepository,
        creative_context: CreativeContext,
        cap_cents: int | None,
        style: str | None,
        frame_aspect: str | None,
    ) -> None:
        """F2b (illustrated_faceless.md §8.5, 2026-09-05): resolves every
        one of `shot.layers` to a real generated image - the ONLY
        acquisition path a layer ever takes (see `generate_layer_image_
        real`'s own docstring). No binding field is written here - a
        layer's resolved clip is found again purely by recomputing
        `layer_prompt_hash` (see that function's own docstring for why);
        the caller wraps this whole call in its own try/except so one
        failed layer degrades that shot's parallax rather than failing
        the shot's own, separately-resolved primary media."""
        if not shot.layers:
            return
        assert image_provider is not None
        for index, layer in enumerate(shot.layers):
            if settings.dry_run:
                await _generate_layer_fake(
                    shot,
                    layer,
                    layer_index=index,
                    project_uuid=project_uuid,
                    project_dir=project_dir,
                    image_provider=image_provider,
                    clip_repo=clip_repo,
                    creative_context=creative_context,
                    style=style,
                    frame_aspect=frame_aspect,
                )
            else:
                await generate_layer_image_real(
                    shot,
                    layer,
                    layer_index=index,
                    project_uuid=project_uuid,
                    project_dir=project_dir,
                    image_provider=image_provider,
                    clip_repo=clip_repo,
                    narration_repo=narration_repo,
                    creative_context=creative_context,
                    cap_cents=cap_cents,
                    style=style,
                    frame_aspect=frame_aspect,
                )

    # Track C §15 N4: this method and `_generate_checked_image_temp_old` /
    # `_generate_checked_image` / `_generate_checked_keyframe` below are
    # unreachable. Kept unwired (A5's "not deleted" precedent for the
    # constraint-checked generate path), not a fourth accidental leftover
    # — do not wire `check_budget` here; live callers already pass
    # `cap_cents`. See §15.8.

    async def _generate_image_real_old(
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
        # Superseded by module-level `generate_image_real` above, which
        # `_resolve_one_real` now calls instead. Kept, unwired, not deleted.
        prompt = styled_prompt(shot, creative_context)
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

    async def _generate_checked_image_temp_old(
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
        """Superseded by module-level `_generate_image_once` above. Kept,
        unwired, not deleted.

        Generates once, at the project's fixed seed - no retry, no
        constraint check. The human at the review gate is the check now,
        not an automated vision call that used to be able to kill a shot
        on a false positive (M6.5 -> gate redesign)."""
        project_seed = _project_seed(str(project_uuid))
        prompt = base_prompt
        prompt_hash = generation_prompt_hash(
            prompt, model_id, project_seed, width=width, height=height
        )

        cached = await clip_repo.get_by_prompt_hash(prompt_hash)
        if cached is not None:
            return cached

        already_spent = await total_project_spend_cents(
            clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
        )
        check_budget(
            already_spent_cents=already_spent,
            additional_cents=settings.fal_image_cost_cents_estimate,
        )

        result = await image_provider.generate(
            ImageRequest(
                prompt=prompt, width=width, height=height, shot_id=shot.id, seed=project_seed
            )
        )
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
            prompt_hash = generation_prompt_hash(prompt, model_id, seed, width=width, height=height)

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
        """Superseded 2026-08-18 (Track A's A5, one-gate model) by
        `_generate_keyframe_once` above, mirroring the 2026-08-16
        image-path precedent (`_generate_checked_image`) - kept, unwired,
        not deleted.

        The video path's A12/A13/A18 equivalent, for the KEYFRAME
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
            prompt_hash = generation_prompt_hash(prompt, model_id, seed, width=width, height=height)

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
