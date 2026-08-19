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
    # Hard, stepped zoom-in snaps rather than a continuous ramp -
    # motion_new_styles_and_long_form_videos.md step 0 (2026-08-17):
    # verified pixel-correct against a real archival photo and watched
    # by a human against real production output before being promoted
    # from a renderer-only spike to a real, planner-choosable movement
    # (canon 3.1/§2.2 - camera decisions are written into the Timeline
    # by the planner, never applied by the renderer from a style alone).
    PUNCH_IN = "punch_in"


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
    # Added 2026-08-17 (motion_new_styles_and_long_form_videos.md §2.6,
    # Tier 2) - deliberately two, not the ~50 `xfade` actually supports
    # (plan's own restraint principle: a documentary that whip-pans
    # between archival photographs stops reading as a documentary).
    # Values are real `xfade` transition names, verified directly against
    # this ffmpeg build's own filter help output and a real render
    # against real archival photos (a genuine wipe, a genuine dip through
    # black), not assumed from memory - passed straight through
    # unchanged at `slideshow.py`'s xfade call site, exactly like
    # DISSOLVE/FADE above, so no renderer code changed to add these.
    WIPE_LEFT = "wipeleft"
    DIP_TO_BLACK = "fadeblack"


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
    # Text card (motion_new_styles_and_long_form_videos.md §2.6, Tier 2,
    # 2026-08-17) - a structural title/heading overlay for THIS shot,
    # never dialogue captions (those come from narration timing, D2, and
    # stay entirely separate - `app/renderer/captions.py`). `None`/empty
    # means no card, the common case for almost every shot. A per-shot
    # field, not a global render toggle: the planner's own decision to
    # set text on a shot IS the toggle - matching how `prompt`/`camera`
    # are already per-shot creative decisions (I1), not a channel-wide
    # setting like the watermark. Shown for this shot's own on-screen
    # window (`duration_s`, via `compute_shot_start_times` - the
    # RENDERED-timeline clock, not narration timing, since a title card is
    # tied to which shot is on screen, not to spoken words) with a fixed
    # fade in/out - see `app/renderer/text_cards.py`.
    text_card: str | None = None


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
    # Track C C1 / §11 Q3: set by hierarchical (Path B) scene planning
    # when N > 70. None for every project below that threshold and every
    # timeline that predates this field. Music (C7) groups by this.
    act_id: str | None = None


class TimelineMetadata(BaseModel):
    language: str = "en"
    aspect_ratio: str = "9:16"
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    total_duration_s: float = Field(default=0.0, ge=0.0)
    # `None` falls back to `settings.elevenlabs_voice_id` (NarrationStep's
    # own read). A human sets this directly via `POST
    # /projects/{id}/narration/retry` (N1, 2026-08-15) to redo narration
    # with a different voice - that endpoint's own docstring covers why
    # this was previously write-only-never-written (nothing wrote it, so
    # nothing could differ from the one global default) and what makes
    # switching voices safe (the narration cache is keyed on voice_id
    # too, so a previously-used voice is never re-synthesised).
    voice_id: str | None = None
    # Set once, permanently, by `NarrationStep`'s own reconciliation
    # (never reset by anything downstream) the moment every shot's
    # `duration_s` is replaced with a real, measured spoken duration
    # rather than a planner's pre-audio estimate (M8 hardening,
    # 2026-08-16 - "A26 is a deadlock in practice"). `Timeline
    # .validate_constraints` reads this directly to decide whether
    # `min_shot_duration_s`/`max_shot_duration_s` still apply - see that
    # method's own docstring for why this is a persistent flag on the
    # Timeline rather than a check against the CURRENT version's
    # `produced_by`: `produced_by` only describes the version that JUST
    # landed, so a later version (a human override, a music retry, a
    # narration-voice retry - anything at all) would otherwise fall back
    # out of the narration-produced case and get re-judged against
    # planning heuristics that measured reality has no obligation to
    # satisfy. This field is what makes the exemption survive every
    # later version, forever, the same way `voice_id` survives past the
    # version that set it.
    narration_locked: bool = False
    # `None` means "no style chosen yet, or predates this field" - falls
    # back to `settings.default_render_style` everywhere this is read
    # (`app/script/styles.py::resolve_constraint_bundle`), so an existing
    # Timeline (every fixture, every test written before 2026-08-17)
    # resolves to EXACTLY the constraint bundle and prompt it always used
    # (motion_new_styles_and_long_form_videos.md, Track B). Set once, at
    # `TimelineService.create_initial` time, from `project.render_style`
    # (itself set at project creation, before any planning starts) -
    # never changed by a later version, the same "survives every later
    # version, forever" shape `voice_id` and `narration_locked` already
    # use above, because it must be known before the Shot Planner ever
    # runs, not discovered mid-plan.
    render_style: str | None = None
    # R5 fix (motion_new_styles_and_long_form_videos.md §13.5, "R5",
    # 2026-08-18, user-confirmed scenario): §2.1's table promised the
    # grade stays freely changeable ("re-render is cheap"), separately
    # from the planner-facing levels that freeze at planning start - but
    # the implementation had only ONE field (`render_style` above) and
    # ONE freeze for all three levels, so the grade - the cheapest,
    # fastest-to-iterate knob in the whole style system - was in practice
    # the most locked. `grade_style` is that missing second, independent
    # knob: `None` means "use whatever `render_style`'s own grade is"
    # (the common case - most projects never touch this), a non-`None`
    # value OVERRIDES the grade `app/renderer/grading.py::
    # grade_filter_fragment` applies, without touching `render_style`
    # itself or anything planner-facing. Settable via `POST
    # /{project_id}/grade` at ANY time, including after planning and
    # after a render - deliberately NOT behind the freeze check
    # `render_style`/`script` have, since that check exists to protect
    # planning inputs, and this is never one. Already covered by the
    # render fingerprint (I5) the same way `render_style` is - part of
    # `metadata`, which is not in `_TIMELINE_BOOKKEEPING_FIELDS` - so a
    # grade change is correctly detected as needing a re-render.
    grade_style: str | None = None
    # Track C C5 / §6 / Q6: scene ids the human has approved at the
    # review gate. Empty on every timeline that predates this field and
    # on every project that has not been reviewed yet. The set is
    # monotonic — once a scene id is present it stays (no un-approve,
    # no reverse edge in the workflow). Written by
    # `POST /{project_id}/scenes/{scene_id}/approve` and stamped for
    # every remaining scene by `POST /{project_id}/timeline/approve`
    # (the flat Approve button is sugar over the same field). Scene
    # approval is a review record, not a lock: it does not freeze a
    # scene against later regenerate/override (A25/A20 stay the lock).
    # The engine gate (`AwaitApprovalStep`) still checks document
    # `status == APPROVED` only; that stamp happens when
    # `POST /timeline/approve` succeeds, which also fills this list.
    approved_scenes: list[str] = Field(default_factory=list)


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


class ActMusicBed(BaseModel):
    """Track C C7: one bed for one act. Empty `act_beds` on MusicPlan
    means Path A (one bed for the video, `selected_track` only)."""

    act_id: str
    selected_track: MusicTrackSelection | None = None


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
    # Track C C7: one bed per act when `Scene.act_id` is set (Path B,
    # N > 70). Empty on Path A and every timeline that predates this
    # field, so existing projects keep a single `selected_track`. The
    # renderer concatenates these in list order; consecutive acts must
    # not share a track when any alternative exists (select_music).
    act_beds: list[ActMusicBed] = Field(default_factory=list)


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
    #
    # Two categories, not one flat list (M8 hardening, 2026-08-16 - "A26
    # is a deadlock in practice"):
    #
    # - STRUCTURAL INVARIANTS always hold, at every version, forever:
    #   total video duration, scene/shot counts, duplicate ids. Nothing
    #   about narration, a human override, or any other later version
    #   ever has a legitimate reason to exceed these - they describe the
    #   shape of a renderable Timeline, not a creative estimate.
    # - PLANNING-TIME HEURISTICS are a different kind of thing:
    #   `min_shot_duration_s`/`max_shot_duration_s` exist to keep a
    #   PLANNER's pre-audio duration guesses inside a sane creative
    #   range before any real narration exists to measure against. Once
    #   `NarrationStep` has reconciled a shot's `duration_s` to real,
    #   measured spoken time (D1 - narration is the master clock), that
    #   number is a fact, not an estimate, and re-applying a planning
    #   heuristic to it is a category error - "कैसे?" genuinely takes
    #   0.615s to speak, and no amount of re-validation makes that
    #   number wrong. The M8 build already reached exactly this
    #   conclusion once (open decision: "let per-shot duration exceed
    #   its cap - the cap is a planning heuristic, the narration is
    #   real") but only wired the exemption into
    #   `GenerateTimelineStep._is_fully_planned`'s own
    #   `produced_by == NARRATION` check - which describes the version
    #   that JUST landed, not the Timeline's own history, so ANY later
    #   version (a human override, a music retry, a narration-voice
    #   retry) fell straight back out of the exemption and re-failed
    #   against measured reality. `self.metadata.narration_locked`
    #   (persistent, set once by `NarrationStep`, never reset) is what
    #   makes the exemption survive every later version instead of only
    #   the one immediately after narration - see that field's own
    #   docstring.

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
        errors.extend(
            self._validate_structural_invariants(
                max_video_duration_s=max_video_duration_s,
                max_shots_per_project=max_shots_per_project,
                max_scenes=max_scenes,
            )
        )
        if not self.metadata.narration_locked:
            errors.extend(
                self._validate_planning_time_shot_bounds(
                    min_shot_duration_s=min_shot_duration_s,
                    max_shot_duration_s=max_shot_duration_s,
                )
            )
        return errors

    def _validate_structural_invariants(
        self, *, max_video_duration_s: float, max_shots_per_project: int, max_scenes: int
    ) -> list[str]:
        """Always enforced, at every version, narration-locked or not -
        these describe the shape of a renderable Timeline, never a
        creative estimate a later measurement can legitimately override."""
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

        ids = self.shot_ids()
        if len(ids) != len(set(ids)):
            errors.append("duplicate shot ids found across scenes")

        return errors

    def _validate_planning_time_shot_bounds(
        self, *, min_shot_duration_s: float, max_shot_duration_s: float
    ) -> list[str]:
        """Only meaningful before real narration exists to measure
        against - skipped entirely once `self.metadata.narration_locked`
        is set. Never called directly by anything outside
        `validate_constraints` itself; kept as its own method so the
        category split above is a real code boundary, not just a
        comment."""
        errors: list[str] = []
        for shot in self.all_shots():
            if not (min_shot_duration_s <= shot.duration_s <= max_shot_duration_s):
                errors.append(
                    f"shot {shot.id} duration_s={shot.duration_s} outside "
                    f"[{min_shot_duration_s}, {max_shot_duration_s}]"
                )
        return errors
