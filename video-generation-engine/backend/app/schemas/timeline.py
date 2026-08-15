"""The Timeline Intermediate Representation (IR).

The canonical data structure exchanged between every planning component and
consumed by every execution component. See docs/07_Timeline_IR.md and
docs/13_Implementation_Guide.md section 6.1.

Rules encoded here:
  - schema_version is checked on load (unknown version fails loudly).
  - No media, no file paths, no URLs — only creative decisions (Invariant I2).
  - IDs are caller-supplied and must stay stable across versions; this module
    does not mint them.
  - Hard numeric limits (D7) are enforced by `Timeline.validate_constraints`,
    not baked into field constraints, so the limits stay configurable.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"


class TimelineStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class ProducedBy(StrEnum):
    DIRECTOR = "director"
    SCENE_PLANNER = "scene_planner"
    SHOT_PLANNER = "shot_planner"
    ASSET_PLANNER = "asset_planner"
    NARRATION = "narration"
    HUMAN = "human"


class ShotIntent(StrEnum):
    INTRODUCE = "introduce"
    EXPLAIN = "explain"
    COMPARE = "compare"
    REVEAL = "reveal"
    CONTRAST = "contrast"
    EMPHASIZE = "emphasize"
    TRANSITION = "transition"


class Framing(StrEnum):
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE = "close"
    SPLIT = "split"


class CameraMovement(StrEnum):
    STATIC = "static"
    SLOW_ZOOM = "slow_zoom"
    SLOW_PUSH = "slow_push"
    PULL_BACK = "pull_back"
    PAN = "pan"
    SPLIT_FRAME = "split_frame"


class CameraDirection(StrEnum):
    IN = "in"
    OUT = "out"
    LEFT = "left"
    RIGHT = "right"
    NONE = "none"


class TransitionType(StrEnum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE = "fade"


class PreferredMediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class AssetStrategy(StrEnum):
    PROJECT_ASSETS = "project_assets"
    HISTORICAL_SEARCH = "historical_search"
    PUBLIC_DOMAIN = "public_domain"
    STOCK_SEARCH = "stock_search"
    GENERATE_VIDEO = "generate_video"
    GENERATE_IMAGE = "generate_image"


# The asset acquisition ladder, canonical order (implementation guide 3.1).
# fallback_chain must be a subsequence of this list, in this order.
ASSET_LADDER: list[AssetStrategy] = [
    AssetStrategy.PROJECT_ASSETS,
    AssetStrategy.HISTORICAL_SEARCH,
    AssetStrategy.PUBLIC_DOMAIN,
    AssetStrategy.STOCK_SEARCH,
    AssetStrategy.GENERATE_VIDEO,
    AssetStrategy.GENERATE_IMAGE,
]


class EnergyArc(StrEnum):
    FLAT = "flat"
    BUILD = "build"
    FALL = "fall"
    BUILD_FALL = "build_fall"


class Camera(BaseModel):
    movement: CameraMovement = CameraMovement.STATIC
    direction: CameraDirection = CameraDirection.NONE
    intensity: float = Field(default=0.15, ge=0.0, le=1.0)


class Transition(BaseModel):
    type: TransitionType = TransitionType.CUT
    duration_s: float = Field(default=0.0, ge=0.0)


class AssetPlan(BaseModel):
    # The real-world subject a Wikipedia article would be titled after
    # ("Leuna-Werke", "Fischer-Tropsch process", "Sasol") - world knowledge
    # only the planner has (M6.5, A1). Deliberately allowed to be empty: a
    # generic scene-setting shot ("a wartime fuel depot") legitimately has
    # no such entity, and a deterministic lookup step (A2) only ever fires
    # when this is non-empty - it never invents one.
    entity: str = ""
    strategy: AssetStrategy
    search_queries: list[str] = Field(default_factory=list)
    preferred_type: PreferredMediaType = PreferredMediaType.IMAGE
    fallback_chain: list[AssetStrategy] = Field(default_factory=list)
    licence_requirements: list[str] = Field(default_factory=list)

    @field_validator("fallback_chain")
    @classmethod
    def _fallback_chain_is_ladder_subsequence(
        cls, chain: list[AssetStrategy]
    ) -> list[AssetStrategy]:
        indices = [ASSET_LADDER.index(step) for step in chain]
        if indices != sorted(indices):
            raise ValueError(
                "fallback_chain must follow the canonical asset ladder order: "
                f"{[s.value for s in ASSET_LADDER]}"
            )
        return chain


class Shot(BaseModel):
    id: str
    order: int
    intent: ShotIntent
    intent_text: str = ""
    narration_span: tuple[int, int] | None = None
    duration_s: float = Field(gt=0.0)
    framing: Framing = Framing.WIDE
    camera: Camera = Field(default_factory=Camera)
    transition_out: Transition = Field(default_factory=Transition)
    prompt: str = ""
    asset_plan: AssetPlan | None = None


class Scene(BaseModel):
    id: str
    order: int
    title: str
    summary: str = ""
    emotion: str = ""
    narrative_purpose: str = ""
    narration_text: str = ""
    duration_s: float = Field(ge=0.0)
    shots: list[Shot] = Field(default_factory=list)


class TimelineMetadata(BaseModel):
    language: str = "en"
    aspect_ratio: str = "9:16"
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    total_duration_s: float = Field(default=0.0, ge=0.0)
    voice_id: str | None = None


class MusicPlan(BaseModel):
    mood: str = ""
    tempo: str = ""
    energy_arc: EnergyArc = EnergyArc.FLAT
    search_terms: list[str] = Field(default_factory=list)
    licence_requirements: list[str] = Field(default_factory=list)


class CreativeContext(BaseModel):
    """Shared context across planning agents (ADR-010). Additive only —
    a later planner may fill a null field but must not overwrite a
    populated one."""

    tone: str = ""
    visual_style: str = ""
    historical_period: str = ""
    audience: str = ""
    camera_language: str = ""
    colour_palette: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class Timeline(BaseModel):
    schema_version: str = SCHEMA_VERSION
    timeline_id: str
    project_id: str
    version: int = Field(ge=1)
    parent_version: int | None = None
    produced_by: ProducedBy
    status: TimelineStatus = TimelineStatus.DRAFT
    created_at: datetime

    metadata: TimelineMetadata = Field(default_factory=TimelineMetadata)
    creative_context: CreativeContext = Field(default_factory=CreativeContext)
    music_plan: MusicPlan | None = None
    scenes: list[Scene] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Timeline schema_version {v!r}; "
                f"this build only understands {SCHEMA_VERSION!r}"
            )
        return v

    @model_validator(mode="after")
    def _parent_precedes_version(self) -> Timeline:
        if self.parent_version is not None and self.parent_version >= self.version:
            raise ValueError("parent_version must be strictly less than version")
        return self

    # -- convenience -----------------------------------------------------

    def all_shots(self) -> list[Shot]:
        return [shot for scene in self.scenes for shot in scene.shots]

    def shot_ids(self) -> list[str]:
        return [shot.id for shot in self.all_shots()]

    # -- hard constraints (D7) --------------------------------------------

    def validate_constraints(
        self,
        *,
        max_video_duration_s: float,
        max_shots_per_project: int,
        min_shot_duration_s: float,
        max_shot_duration_s: float,
        max_scenes: int,
    ) -> list[str]:
        """Return a list of human-readable violations (empty = valid).

        Deliberately returns errors rather than raising, so a caller (the
        planner repair loop) can decide what to do with them.
        """
        errors: list[str] = []

        if self.metadata.total_duration_s > max_video_duration_s:
            errors.append(
                f"total_duration_s {self.metadata.total_duration_s} exceeds "
                f"max_video_duration_s {max_video_duration_s}"
            )

        if len(self.scenes) > max_scenes:
            errors.append(f"{len(self.scenes)} scenes exceeds max_scenes {max_scenes}")

        shots = self.all_shots()
        if len(shots) > max_shots_per_project:
            errors.append(
                f"{len(shots)} shots exceeds max_shots_per_project {max_shots_per_project}"
            )

        for shot in shots:
            if not (min_shot_duration_s <= shot.duration_s <= max_shot_duration_s):
                errors.append(
                    f"shot {shot.id} duration_s={shot.duration_s} outside "
                    f"[{min_shot_duration_s}, {max_shot_duration_s}]"
                )

        ids = self.shot_ids()
        if len(ids) != len(set(ids)):
            errors.append("duplicate shot ids found across scenes")

        return errors
