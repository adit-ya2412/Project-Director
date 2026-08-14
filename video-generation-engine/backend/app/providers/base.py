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
from typing import Protocol


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    width: int
    height: int
    shot_id: str


@dataclass(frozen=True)
class ImageResult:
    """Bytes only — never a path or URL persisted into the Timeline
    (Invariant I2). The caller decides where to store the bytes."""

    content: bytes
    content_type: str = "image/png"


class ImageProvider(Protocol):
    name: str

    async def generate(self, request: ImageRequest) -> ImageResult: ...


@dataclass(frozen=True)
class AssetQuery:
    search_terms: list[str]
    preferred_type: str
    shot_id: str


@dataclass(frozen=True)
class AssetCandidate:
    source_id: str
    score: float
    licence: str = "unknown"


@dataclass(frozen=True)
class AssetBytes:
    content: bytes
    content_type: str = "image/png"


class AssetProvider(Protocol):
    name: str
    rung: str

    async def search(self, query: AssetQuery) -> list[AssetCandidate]: ...
    async def fetch(self, candidate: AssetCandidate) -> AssetBytes: ...
