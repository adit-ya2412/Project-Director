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
    # M8 step 4 (D6/I1): music selection is a deterministic acquisition
    # step, not an AI planner's creative judgement (I4) and not a human
    # action either - its own category, matching the precedent NARRATION
    # already set (a step, not a planner or a person, can legitimately
    # produce a Timeline version).
    MUSIC_SELECTION = "music_selection"


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
    # A human override (M6.5, A9/A10/A24/A25) sets this via an
    # `append_version` with `produced_by=HUMAN`. It lives on the Shot
    # itself, not only on the ShotBinding, so it is part of the immutable
    # decision record (I1/I2 - "this shot's asset is locked" is a
    # creative decision, not media) and auditable from the Timeline
    # alone. Two consequences, both required by A25 (decided by the
    # user, 2026-08-15: "lock wins, my photo is always in the plan, and
    # the plan should include it in the shot"):
    #   1. `TimelineService._carry_forward_bindings` carries a locked
    #      shot's binding forward UNCONDITIONALLY, exempting it from
    #      A20's normal drop-on-change rule - see that module.
    #   2. `TimelineService.append_version` refuses (raises
    #      `PermanentError`) any later version that changes a locked
    #      shot's `prompt` or `asset_plan` - "always in the plan" is made
    #      literally true by making it impossible for a re-plan to drift
    #      away from the image a human already chose, not merely
    #      detected after the fact.
    asset_locked: bool = False


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


class MusicTrackSelection(BaseModel):
    """The chosen track's PROVENANCE, never its bytes (I2) - M8 D6/21.2.
    Mirrors `Asset`'s own provenance fields exactly (provider, source_url,
    licence, attribution, content_hash), so the same "record the
    selection, never the media" discipline the visual asset ladder
    already follows applies here too. The audio itself lives at
    `storage/{project}/music/{content_hash}.mp3` (D3)."""

    provider: str
    track_id: str
    source_url: str
    licence: str
    attribution: str = ""
    content_hash: str


class MusicPlan(BaseModel):
    mood: str = ""
    tempo: str = ""
    energy_arc: EnergyArc = EnergyArc.FLAT
    search_terms: list[str] = Field(default_factory=list)
    licence_requirements: list[str] = Field(default_factory=list)
    # Both fields below are set to a real outcome only by `SelectMusicStep`
    # (`produced_by=MUSIC_SELECTION`), never by the Director (which only
    # ever writes the fields above). `selected_track` is the decision
    # itself (D6/I1 - the Timeline is the only source of truth for it);
    # `selection_attempted` is what makes "no suitable track was found" a
    # distinct, resumable state from "not yet tried" WITHOUT a side table
    # (M8's own closed decision: the track lives in the Timeline, not a
    # side table - and by the same reasoning, so does the fact that a
    # search for one was made). A human MAY reset both back to their
    # "not yet tried" values (`POST /projects/{id}/music/retry`, M8
    # hardening 2026-08-15) to request a fresh attempt - the same
    # correctability principle every other automated asset choice in
    # M6.5 already has - optionally overriding `search_terms` in the same
    # call, since a miss is often the terms themselves being wrong.
    selected_track: MusicTrackSelection | None = None
    selection_attempted: bool = False


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
