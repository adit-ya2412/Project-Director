"""Provider protocols.

Every external integration implements one of these (ADR-003). Core business
logic depends only on these interfaces, never on a concrete SDK. All network
IO, subprocess execution, and filesystem writes to external content live
behind this boundary (implementation guide section 5, "the providers/
firewall").

M0 only needs ImagePlanningProvider and AssetSearchProvider — enough to
prove the render pipeline. VideoProvider, NarrationProvider, MusicProvider,
and LLMProvider are added in M5-M8 as their phases land.
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, Field

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


@dataclass(frozen=True)
class StructuredCompletion:
    """A validated structured response plus everything the caller needs
    to persist an `llm_call` audit row (implementation guide, Phase M5
    advice: "record every LLM exchange"). `parsed` is already validated
    against the caller's Pydantic model - callers never see raw JSON."""

    parsed: BaseModel
    model: str
    request: dict
    response: dict
    input_tokens: int | None
    output_tokens: int | None


class PlanningLLMProvider(Protocol):
    """The one interface every planning agent (Director, Scene/Shot/Asset
    Planner) depends on - never a concrete OpenAI/Anthropic SDK type
    (ADR-003). Swapping the planning LLM is a new class behind this
    Protocol, not a change to any planner."""

    name: str

    async def structured_complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_model: type[ResponseModelT],
        seed: int | None = None,
    ) -> StructuredCompletion: ...


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    width: int
    height: int
    shot_id: str
    seed: int | None = None


@dataclass(frozen=True)
class ImageResult:
    """Bytes are what get persisted (Invariant I2 - the Timeline itself
    never holds a path or URL). `hosted_url`, when a provider sets it, is
    a provider-hosted URL for the *same* bytes - never stored, only
    reused within one request as the source keyframe for image-to-video
    generation (M7) so the image doesn't need re-uploading."""

    content: bytes
    content_type: str = "image/png"
    hosted_url: str | None = None


class ImageProvider(Protocol):
    name: str

    async def generate(self, request: ImageRequest) -> ImageResult: ...


@dataclass(frozen=True)
class VideoRequest:
    """Image-to-video: every model behind this protocol takes a source
    keyframe, not just a text prompt - the keyframe is generated via an
    `ImageProvider` first (M7's Kling model is `image-to-video`)."""

    prompt: str
    image_url: str
    duration_s: float
    shot_id: str


@dataclass(frozen=True)
class VideoJobStatus:
    state: str  # "in_progress" | "completed" | "failed"
    content: bytes | None = None
    content_type: str = "video/mp4"
    error: str | None = None


class VideoProvider(Protocol):
    """Submit/poll, not request-response (implementation guide, Phase M7
    advice: "video generation is submit-and-poll... this is exactly why
    the workflow engine must survive process restarts"). `submit` returns
    a job id to persist immediately; `poll` is called once per attempt,
    never blocks until completion."""

    name: str

    async def submit(self, request: VideoRequest) -> str: ...
    async def poll(self, job_id: str) -> VideoJobStatus: ...


@dataclass(frozen=True)
class AssetQuery:
    search_terms: list[str]
    preferred_type: str
    shot_id: str
    historical_period: str = ""


@dataclass(frozen=True)
class AssetCandidate:
    """Search-result metadata only — no bytes yet (M6). `relevance` is the
    provider's own naive rank-based confidence in [0, 1] (purely the
    result's position in that provider's response) - kept for logging and
    for the DRY_RUN fake-provider path, but it is NOT what the real search
    path gates or ranks on, since a result's position says nothing about
    whether it depicts the requested subject (a crucifixion painting
    returned first still scores 1.0 here). The real search path
    (`ResolveAssetsStep._resolve_one_real`) computes genuine relevance from
    `title`/`description` text via `app/assets/relevance.py` and treats it
    as a hard gate before ranking - never a ranking nudge (implementation
    guide, Phase M6 advice, same principle as the licence check).

    `description` is the richest text a provider can offer beyond the
    title - Wikimedia's `extmetadata` carries `ImageDescription`/
    `ObjectName`, Pexels supplies `alt` (folded into `title` there, since
    it's Pexels' only text field)."""

    source_id: str
    source_url: str
    title: str
    licence: str
    relevance: float = 0.5
    author: str = ""
    width: int | None = None
    height: int | None = None
    description: str = ""
    # Set by entity-based retrieval only (M6.5, A2) - a Wikipedia article's
    # own images or a Commons category's file members, resolved by
    # deterministic lookup from the Asset Planner's `entity` field, never
    # by keyword search. A human already filed this image under that exact
    # subject, so `app/assets/ranking.py` ranks it ahead of free-text
    # search hits for the same shot, and `ResolveAssetsStep` skips the
    # relevance gate for it - relevant by construction, not by term
    # overlap (see app/providers/wikimedia.py:WikipediaEntityAssetProvider).
    entity_curated: bool = False
    # "image" | "video" (A7, motion_new_styles_and_long_form_videos.md,
    # 2026-08-18) - defaults to "image" so every EXISTING provider
    # (Wikimedia, project uploads, entity retrieval - none of which serve
    # video) needs no change at all. `PexelsAssetProvider` is the one
    # provider that sets this to "video", and only when it actually
    # searched its video endpoint - never inferred from the query's
    # `preferred_type`, since a video-preferred shot's fallback_chain can
    # still legitimately reach an IMAGE-only rung first (reuse-before-
    # generate applies regardless of media type).
    media_kind: str = "image"


@dataclass(frozen=True)
class AssetBytes:
    content: bytes
    content_type: str = "image/png"
    attribution: str = ""


class AssetProvider(Protocol):
    name: str
    rung: str

    async def search(self, query: AssetQuery) -> list[AssetCandidate]: ...
    async def fetch(self, candidate: AssetCandidate) -> AssetBytes: ...


@dataclass(frozen=True)
class NarrationRequest:
    """One TTS request (M8, D1). Cache keys and `Shot.narration_span`
    stay per-scene; RV-Q10 may set `text` to several contiguous scenes
    joined by a newline, which `NarrationStep` splits back into one
    alignment per scene before `narration_fit` sees them. `scene_id` is
    the first scene in that request (tracing), not a cache key.

    `voice_id`/`model`/`output_format`/`speed` are explicit fields here
    rather than baked into the provider instance (contrast
    `FalImageProvider`, which reads its model id from settings) -
    together with `text` they are the inputs the cache key hashes on
    (`elevenlabs.compute_narration_content_hash`). A per-project voice
    (`Timeline.metadata.voice_id`) or language can vary the first three
    independently of any global default; `speed` is style-owned
    (parent plan §2.1 — 1.2 on `retention_fast`, 1.0 elsewhere).

    `language_code` (ISO 639-1) is optional and defaults to None (field
    omitted entirely) - it hints the model's language for code-switched
    scripts (2026-08-24, hinglish_voice_probe.py). None keeps existing
    cache rows valid, same convention as `speed`'s 1.0 default.
    """

    text: str
    voice_id: str
    model: str
    output_format: str
    scene_id: str
    speed: float = 1.0
    language_code: str | None = None


@dataclass(frozen=True)
class NarrationResult:
    """`alignment` is ElevenLabs' RAW, un-normalized character-level
    timing object - three parallel arrays (`characters`,
    `character_start_times_seconds`, `character_end_times_seconds`) whose
    indices correspond 1:1 with the submitted `request.text`. See
    `providers/elevenlabs.py` for why the *normalized* alignment the same
    response also contains is never used. `character_count` is the billed
    length of the submitted text - recorded so a later step can fold TTS
    spend into the project budget cap the same way `generated_clip.
    cost_cents` already does."""

    content: bytes
    alignment: dict
    character_count: int
    content_type: str = "audio/mpeg"


class NarrationProvider(Protocol):
    name: str

    async def synthesize(self, request: NarrationRequest) -> NarrationResult: ...


class ConstraintVerdict(BaseModel):
    """Vision check verdict for one generated image against the
    Director's `creative_context.constraints` (M6.5, A12) - a structured
    output, not free text, same discipline as every other planner
    response. Lives here (not in `app/assets/`) so both the OpenAI
    provider (which must produce it) and `app/assets/constraint_check.py`
    (which interprets it) can import it without an upward import from
    providers into assets (section 5, "dependency rule")."""

    violated: bool
    # Exact text of the violated constraint (as written in
    # `creative_context.constraints`), or "" when `violated` is False.
    violated_constraint: str
    # Why, in the model's own words - or "" when `violated` is False.
    reason: str


@dataclass(frozen=True)
class ConstraintCheckRequest:
    """Input to a vision constraint check (M6.5, A12). Generated media
    only - a searched asset never reaches this (it asks "does this
    violate a fixed constraint", not "does this depict the subject" -
    see `DepictionCheckRequest`/A30 for the searched-asset equivalent,
    A16 resolved)."""

    image: bytes
    image_content_type: str
    shot_prompt: str
    constraints: list[str]


class StyleSuitabilityVerdict(BaseModel):
    """Suitability half of the script pre-flight
    (motion_new_styles_and_long_form_videos.md §3.1, §3.7) - a judgement
    call (subject/tone/style fit), deliberately NOT a boolean pass/fail
    like a feasibility check: `suitable=False` alone is a wall with no
    argument available, and the plan's own reasoning for WARNING here
    rather than BLOCKING (unlike the feasibility check) is that a user
    must be able to disagree with a reason, never merely be told no.

    `suitable`/`reason` mirrors `DepictionVerdict.confidently_wrong`/
    `reason`'s shape exactly - same discipline, a different question
    (subject/tone fit for a whole SCRIPT against a STYLE, never a single
    image against a fixed constraint list)."""

    suitable: bool
    reason: str


class DepictionVerdict(BaseModel):
    """Vision check verdict for a SEARCHED candidate (M6.5, A16 -> A30 ->
    A30a) - a different question from `ConstraintVerdict` ("does this
    violate a fixed list of hard constraints") and deliberately its own
    type rather than a constraint-shaped workaround.

    `confidently_wrong`, not `depicts` (A30's original field name,
    renamed under A30a): measured live against the Hindi fixture, asking
    the model to CONFIRM a specific subject ("does this depict X")
    rejected two genuinely correct images - a real Bundesarchiv Leuna
    photograph and a real Fischer-Tropsch diagram - because nothing in
    the pixels can confirm a specific NAMED place or event; that identity
    lives in an archive's catalogue metadata, which no vision model can
    see. `confidently_wrong` asks the answerable, asymmetric question
    instead: is this image CONFIDENTLY a different KIND of subject
    entirely (a map instead of a photograph, a modern scene instead of
    archival material, an unrelated event)? Default bias is toward
    keeping - a false reject costs a real, usable image; a false accept
    costs one image a human still sees and can override at the approval
    gate. The field name itself is deliberately asymmetric (not
    `plausible: bool` inverted) so a caller can never mis-read which
    direction is the safe default.

    `reason` is always populated - useful for understanding either
    outcome, and this check has no "steady state" where an empty reason
    is expected.

    ⚠ `focal_x` / `focal_y` USED TO LIVE HERE (OQ-2) and were REMOVED
    2026-08-29 after a live bake-off (output_quality_pass.md §14). Two
    separate reasons, either of which is sufficient:

    1. They carried defaults of 0.5, so a model that answered the
       plausibility question and ignored the location one produced a
       silent, confident "dead centre" that `persist_vision_focal` then
       wrote to disk labelled `focal_source="vision"`. 11 of 12 real
       backfilled sidecars were exactly (0.50, 0.50). A default that is
       indistinguishable from an answer is not a default, it is a lie.
    2. Measured on real assets, `settings.openai_vision_model`
       (gpt-4o-mini) CANNOT localise a subject - it put the aim on the
       kart instead of the driver, on the wrong car of two, and on empty
       track beside the pack. No prompt shape rescued it; a 3x3 grid
       enum made it worse. Subject location is a genuinely harder task
       than the yes/no plausibility gate and needs a stronger model.

    Location now has its own request/verdict pair (`SubjectFocalRequest`
    / `SubjectFocal`) and its own model setting, so the A30a-calibrated
    plausibility gate keeps running on the cheap model it was calibrated
    against."""

    confidently_wrong: bool
    reason: str


@dataclass(frozen=True)
class DepictionCheckRequest:
    """Input to a depiction check (M6.5, A30). Searched candidates only -
    the top-ranked candidate per rung a shot's ladder walk would
    otherwise accept, never a generated image (that's `ConstraintCheckRequest`'s
    job) and never a whole candidate pool (A30: one call, the top
    candidate only)."""

    image: bytes
    image_content_type: str
    shot_prompt: str
    # What the candidate is being checked against - the shot's own
    # search terms joined into one string, NOT the entity (A30 skips
    # entity-curated candidates entirely, so this function never runs
    # for those in the first place).
    search_subject: str


class SubjectFocal(BaseModel):
    """Where the main visible subject sits (OQ-2, re-cut 2026-08-29).

    ⚠ **No field has a default, deliberately.** The predecessor put
    `focal_x: float = 0.5` on `DepictionVerdict`, so an unanswered
    question became a confident centre. Here an unanswered question is a
    validation error the caller can see and log, and the caller falls
    back to centre EXPLICITLY with `focal_source="fallback"`.

    `subject` and `subject_location_words` are not decoration - they are
    the reason this works. Measured in the same bake-off: asking for
    coordinates alone gets 0.5,0.5; forcing the model to NAME the subject
    and describe its position in words BEFORE emitting numbers produces
    real, varied answers. Keep the field order - it is the ordering of a
    structured response that does the work."""

    subject: str = Field(description="The single most important subject, named in 2-6 words.")
    subject_location_words: str = Field(
        description="Where that subject sits, in words, e.g. 'upper left', 'centre right'."
    )
    focal_x: float = Field(ge=0.0, le=1.0, description="0=left, 1=right.")
    focal_y: float = Field(ge=0.0, le=1.0, description="0=top, 1=bottom.")


@dataclass(frozen=True)
class SubjectFocalRequest:
    """Input to a subject-location call. Deliberately carries no search
    terms or shot prompt: unlike the depiction gate, this asks a question
    about the PIXELS ONLY ("what is the main thing and where is it"), so
    feeding it the intended subject would invite it to report where the
    subject was SUPPOSED to be rather than where anything actually is."""

    image: bytes
    image_content_type: str


class VisionConstraintProvider(Protocol):
    """Checks one image against either a fixed list of hard creative
    constraints (`check_constraints`, M6.5 A12, generated media only) or
    against whether it is CONFIDENTLY a different kind of subject than a
    shot's search called for (`check_depiction`, M6.5 A30/A30a, searched
    media only) - vision-capable
    structured output, the same call shape as
    `PlanningLLMProvider.structured_complete` but with an image attached.
    Kept as its own Protocol rather than methods added to
    `PlanningLLMProvider`: not every LLM swap needs vision, and not every
    planning call needs an image - a text-only provider would otherwise
    have to stub out methods it can't implement. Both methods share one
    concrete provider (`OpenAIPlanningProvider`) and one `llm_call` audit
    path (`app/assets/constraint_check.py`, `app/assets/depiction_check.py`)
    - they ask genuinely different questions, so they get their own
    prompt and verdict shape each, per A30's own scope."""

    name: str

    async def check_constraints(self, request: ConstraintCheckRequest) -> StructuredCompletion: ...
    async def check_depiction(self, request: DepictionCheckRequest) -> StructuredCompletion: ...
    async def locate_subject(self, request: SubjectFocalRequest) -> StructuredCompletion: ...


@dataclass(frozen=True)
class MusicSearchQuery:
    """The music-selection step's input (M8, D6/21.2) - the primitive
    fields a search needs out of `Timeline.music_plan`, not the whole
    Pydantic object. Mirrors `AssetQuery`'s own precedent of taking only
    what a provider needs rather than a Timeline-shaped object, which
    keeps `providers/` decoupled from IR schema churn (`music_plan` may
    grow fields - e.g. `selected_track` - that a search call has no
    business seeing)."""

    mood: str
    tempo: str
    energy_arc: str
    search_terms: list[str]


@dataclass(frozen=True)
class TrackCandidate:
    """Search-result metadata only - no bytes yet, same split as
    `AssetCandidate`/`AssetBytes` for visual assets. `relevance` is the
    provider's own naive confidence (kept for logging/the fake path,
    never what the real ranking gates or ranks on - see
    `AssetCandidate`'s own docstring for why a provider's self-reported
    relevance is not trustworthy)."""

    source_id: str
    source_url: str
    title: str
    licence: str
    relevance: float = 0.5
    author: str = ""
    duration_s: float | None = None
    # Published tempo when a source recorded one (manifest / ID3 / the
    # Incompetech page). None means unknown — never a guessed value.
    # Ranked by `music_ranking.target_bpm_for_mean_shot_duration`.
    bpm: int | None = None
    tags: str = ""
    # A provider-supplied, ready-to-use attribution string, when it has
    # one (Openverse does - a precise, licence-version-and-URL-correct
    # sentence, better than anything this codebase would reconstruct
    # from `author`/`licence` alone). Empty when a provider has nothing
    # better than `author` to offer - `fetch()` falls back to building
    # one from that, the same pattern `PexelsAssetProvider.fetch` uses.
    attribution: str = ""


@dataclass(frozen=True)
class AudioBytes:
    content: bytes
    content_type: str = "audio/mpeg"
    attribution: str = ""


class MusicProvider(Protocol):
    """One background-music search+fetch (M8, D6) - the audio-track
    equivalent of `AssetProvider`. Unlike the visual ladder, this is not
    a rung with a fallback chain; one provider, selected via
    `settings.music_provider`, either finds a track or it doesn't."""

    name: str

    async def search(self, query: MusicSearchQuery) -> list[TrackCandidate]: ...
    async def fetch(self, candidate: TrackCandidate) -> AudioBytes: ...


@dataclass(frozen=True)
class SoundEffectRequest:
    """One text-to-sound generation request (long_form_direction.md A8,
    2026-09-01) - the generation-ladder equivalent of `ImageRequest`.
    Deliberately no `seed` field: ElevenLabs' `/v1/sound-generation`
    documents none (P-LF-A8-GEN-GATE), so I5 comes entirely from the
    mandatory prompt-hash cache (`providers/elevenlabs.py::
    compute_sfx_generation_hash`), never from a generation input."""

    text: str
    duration_seconds: float


@dataclass(frozen=True)
class SoundEffectResult:
    """Bytes are what get persisted (I2), exactly like `ImageResult`."""

    content: bytes
    content_type: str = "audio/mpeg"


class SoundEffectProvider(Protocol):
    """Text-to-sound generation (long_form_direction.md A8) - one call,
    no polling (unlike `VideoProvider`'s submit/poll shape): ElevenLabs'
    sound-generation endpoint is synchronous, same request/response shape
    as `ImageProvider.generate`."""

    name: str

    async def generate(self, request: SoundEffectRequest) -> SoundEffectResult: ...
