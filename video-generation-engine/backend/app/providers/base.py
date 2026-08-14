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

from pydantic import BaseModel

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
    provider's own naive text-match confidence in [0, 1]; it is one input
    into the final ranking score (app/assets/ranking.py), never the
    selection score itself - quality, period match, licence, and reuse
    all factor in too (implementation guide, Phase M6 advice: "make
    ranking explicit and weighted, in one function")."""

    source_id: str
    source_url: str
    title: str
    licence: str
    relevance: float = 0.5
    author: str = ""
    width: int | None = None
    height: int | None = None


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
