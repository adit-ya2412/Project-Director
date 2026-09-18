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

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.colour import hex_luma

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
    # Leftover item 2 / §5.5: SFX palette acquisition, same D6 shape as
    # music — a step, not a planner or a person.
    SFX_SELECTION = "sfx_selection"
    # caption_romanization.md §3.2: the display-text pass that fills
    # `Scene.caption_text`. A step, not a planner-chain link — it runs
    # after SelectSfx and BEFORE Narration so the active version is
    # overwritten by `produced_by=NARRATION` before anything renders.
    # Backfill of an already-narrated project re-stamps NARRATION
    # instead of this value (render.py refuses to mux audio unless the
    # active version is NARRATION).
    CAPTION_ROMANIZATION = "caption_romanization"
    # retention_fast_kinetic_text.md K10: the lexical pivot-attach pass.
    # Same placement rule as CAPTION_ROMANIZATION — it appends BEFORE
    # NarrationStep so the active version at render is still NARRATION.
    # `is_satisfied` must NOT key off this value; Narration overwrites it.
    EMPHASIS_PASS = "emphasis_pass"


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
    # illustrated_faceless.md F2 (2026-09-04): the planner's request for
    # two-layer parallax (§1.4's measured finding - background and
    # subject drifting at different rates, "the register Ken Burns
    # structurally cannot reach"). Canon 3.1/§2.2: this is a value the
    # PLANNER writes into the Timeline, never something the renderer
    # invents from a style alone - the renderer (`app/renderer/
    # parallax.py`) only executes the drift/scale numbers a shot's own
    # `Shot.layers` (`ShotLayer`) already carry. `camera.direction` and
    # `camera.intensity` are NOT consulted for this movement, the same
    # way `PUNCH_IN` above does not consult `direction` - each layer's
    # own `drift_x`/`drift_y`/`scale` carries the motion instead. F2
    # ships the schema and the renderer module only; nothing in this
    # slice wires a Shot Planner prompt to author `layers` alongside
    # this value (see `Shot.layers`'s own docstring), so a shot carrying
    # this movement with empty `layers` is a legitimate, if useless,
    # state for now - not guarded against here, matching how a
    # `SPLIT_FRAME` shot with an empty `secondary_prompt` already
    # degrades to the plain static path rather than erroring.
    PARALLAX = "parallax"


class CameraDirection(StrEnum):
    IN = "in"
    OUT = "out"
    LEFT = "left"
    RIGHT = "right"
    # Vertical PAN (A5, long_form_direction.md §3) - the mirror of
    # LEFT/RIGHT onto `y`, legal only on a landscape canvas (a tall
    # subject on a wide frame - a standing portrait, an engraving, a
    # full-page plate). The Shot Planner's validator rejects UP/DOWN on a
    # portrait canvas (`_make_validator`), the same "fail loudly rather
    # than render with nowhere to go" reasoning A5's plan section states.
    # DOWN means the camera reveals the frame moving downward (pans from
    # the top of the image toward the bottom - the natural reading-order
    # default, mirroring PAN's own RIGHT default for horizontal travel);
    # UP is the reverse (pans from the bottom toward the top). See
    # `build_zoompan_expression`'s PAN branch for the exact mirror.
    UP = "up"
    DOWN = "down"
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
    # Added 2026-08-26 (style_extensions.md §5, Feature C) - unlike
    # WIPE_LEFT/DIP_TO_BLACK above, these are NOT real `xfade` transition
    # names passed straight through: `xfade` has no true digital-
    # corruption effect (verified by testing its full slice/pixelize
    # candidate set against real archival photos, §5's P-C1 - none of
    # them read as "glitch"). These three are custom filter fragments
    # (`rgbashift` channel-split + `noise` grain, layered around a plain
    # `xfade=fade`) built and visually verified against real archival
    # photos at real render resolution (§5's P-C2) - `slideshow.py`
    # branches on these three specifically to emit that fragment instead
    # of the single-line `xfade=transition=X` construction every other
    # value here gets. All three are RGB-shift + noise; they differ only
    # in what's layered on top:
    GLITCH_SHIFT = "glitch_shift"  # channel-split + noise alone (P-C2 "v1")
    GLITCH_TEAR = "glitch_tear"  # + horizontal band displacement ("v2")
    GLITCH_JITTER = "glitch_jitter"  # + a bounded positional wobble ("v3")


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


class RevealDirection(StrEnum):
    """F5 (illustrated_faceless.md §2/F5, 2026-09-05): the direction a
    shot's OWN finished picture wipes into view over time - element
    ANIMATION, not layer compositing. A generated illustration is a
    single flat PNG (no bar/arrow OBJECT inside it to move, only pixels),
    and this format has already ruled out per-shot AI image-to-video on
    cost (Verdict, §2.4's arithmetic), so "a bar growing" or "an arrow
    drawing itself" can only ever mean the FINISHED graphic progressively
    revealed out of the shot's own substrate colour - the "wipe" in the
    plan's own "grow, draw, wipe" phrasing, and the only one of the three
    actually achievable on a generated still. `NONE` (the default on
    every shot, mirroring `CameraDirection.NONE`) means no reveal at all
    - by far the common case, even on this style.

    Two members, not more - the minimum set the plan's own two named
    examples need: a bar CLIMBING from its own baseline needs its reveal
    to sweep upward from the bottom of the frame; an arrow or line
    DRAWING itself needs its reveal to sweep left across the frame (the
    reading-order default, the same convention `CameraDirection.RIGHT`
    already carries for `PAN`). A wipe sweeping the other two ways
    (top-down, right-to-left) has no named use case in this plan and is
    left unbuilt rather than spun up on spec."""

    NONE = "none"
    BOTTOM_TO_TOP = "bottom_to_top"
    LEFT_TO_RIGHT = "left_to_right"


class EmphasisDevice(StrEnum):
    """On-screen punctuation device (retention_fast_kinetic_text.md).
    Enum is the full v1 set so later devices do not churn the model
    (Decision 8). K9 v1 authors `pivot`, `stamp`, and `counter`; the
    compositor renders those three (K11). Other devices are ignored
    until they have a renderer."""

    STAMP = "stamp"
    COUNTER = "counter"
    METER = "meter"
    COMPARISON = "comparison"
    CORRECTION = "correction"
    PIVOT = "pivot"
    QUESTION = "question"


class EmphasisRegister(StrEnum):
    """On-screen script. Fixed by the role table, not a per-cue planner
    choice — pivot is Devanagari (`hi`)."""

    HI = "hi"
    EN = "en"


class EmphasisValue(BaseModel):
    """One plotted number on a data device. `cited_fragment` is what
    makes the honesty rule enforceable (K8); unused for pivot."""

    value: int
    unit: str | None = None
    cited_fragment: int = Field(ge=1)


class EmphasisCue(BaseModel):
    """One kinetic-text beat on a shot (retention_fast_kinetic_text.md K1).

    Creative decisions only (canon 3.1): which word, which device, which
    register, which text. No colours, no positions, no pixels. Timing is
    a fragment INDEX (`anchor_fragment`); `offset_s` is the resolved
    half, filled by `resolve_emphasis_cue_offsets` once real alignment
    exists — the same split `ShotLayer.enter_on_fragment` /
    `enter_offset_s` already uses (F4). A model cannot predict a duration
    that does not exist yet.

    `anchor_fragment` is required: a cue with no word cannot be timed.
    """

    device: EmphasisDevice
    # WHICH WORD — 1-indexed, never seconds. Required (no default).
    anchor_fragment: int = Field(ge=1)
    text: str = Field(min_length=1)
    # `text_register`, never bare `register`: that name shadows
    # `ABCMeta.register`, inherited here via `BaseModel`, and pydantic
    # emits a UserWarning on every single import of this module. Not
    # `script` either - in this codebase "script" is already the
    # narration screenplay (the `script` table, `Project.script`), so it
    # would be genuinely ambiguous on a cue that means "which alphabet".
    text_register: EmphasisRegister
    values: list[EmphasisValue] = Field(default_factory=list)
    replaced_text: str | None = None
    # Seconds from THIS SHOT's start. Default 0.0 until K2 fills it
    # from alignment; never authored by the planner. K17: the seconds
    # to the anchored WORD, found by locating `text` inside
    # `anchor_fragment` — not to the fragment's own onset, which on a
    # one-fragment-per-shot reel is 0.0 for every cue ever rendered
    # (`app/timeline/narration_fit.py`'s own K17 section).
    offset_s: float = 0.0


class LayerRole(StrEnum):
    """One plane's depth role in a parallax composite (illustrated_
    faceless.md §2.2/F2). F2 uses exactly two, in this order -
    BACKGROUND then SUBJECT (`app/renderer/parallax.py`'s F2 builder
    rejects anything else); FOREGROUND is carried here now because §2.2
    names all three as the eventual shape, but is not yet legal in a
    two-layer F2 shot - F3 is what adds it."""

    BACKGROUND = "background"
    SUBJECT = "subject"
    FOREGROUND = "foreground"


class ShotLayer(BaseModel):
    """One plane of a parallax composite (illustrated_faceless.md
    §2.2/F2) - a role, a generation prompt, its own asset plan, and its
    own drift/scale. Mirrors `Shot.prompt`/`Shot.asset_plan`'s own
    creative-decision-only shape (I2 - no media, no paths, no URLs):
    this describes what to generate, never the resulting image bytes,
    which are resolved and hashed elsewhere exactly like a shot's
    primary/secondary asset already is.

    **Deliberately NOT unified with `secondary_prompt`/
    `secondary_asset_plan`** (§6 Q1, decided 2026-09-04): those composite
    two PANELS, each occupying part of the frame, for `split_frame`. A
    layer composites a PLANE that fills the WHOLE frame, generated on a
    key colour and chroma-keyed so the planes stack with transparency
    (`app/renderer/parallax.py`). Both pairs share a "prompt + asset_plan
    describes one more picture for this shot" shape because that shape
    already exists in the schema, not because the two operations are the
    same one - Q1's verdict is that they sit BESIDE each other, and
    `Shot`'s own mutual-exclusion validator below is what keeps a shot
    from ever being half in each system.

    `drift_x`/`drift_y` (px) are this layer's own linear travel over the
    shot's full `duration_s`, ported from `parallax_probe.py::_drift`.
    `scale` is how much larger than the render canvas this layer is
    generated/scaled to, so there is real picture to drift across
    without exposing an edge - `parallax_probe.py`'s own measured "scale
    must COVER the output" rule (`_OVER = 1.2`), the same reasoning
    `long_form_direction.md` §4.7 already states for PAN applied to a
    new axis. Every field here is a planner-authored creative decision
    (canon 3.1) the renderer only executes, never invents."""

    role: LayerRole
    prompt: str = ""
    asset_plan: AssetPlan | None = None
    drift_x: float = 0.0
    drift_y: float = 0.0
    # Must exceed 1.0 - see the class docstring's "scale must COVER the
    # output" note. 1.2 matches parallax_probe.py's own measured default.
    scale: float = Field(default=1.2, gt=1.0)
    # illustrated_faceless.md F4 (2026-09-05): the SAME 1-indexed,
    # INCLUSIVE fragment idiom `ShotPlanOutput.fragment_start`/
    # `fragment_end` already uses (see that field's own docstring, adopted
    # after three incidents of character-offset arithmetic failing),
    # applied one level in, to a single layer's own entry. A model cannot
    # reliably predict a duration that does not exist yet (narration is
    # measured AFTER planning - `app/planners/fragments.py`'s own thesis),
    # but CAN judge which fragment's words a reveal should land on - the
    # real time then falls out of measured narration deterministically,
    # exactly as `narration_span` already does for a whole shot.
    #
    # `None` (the default) means "present for the whole shot" - today's
    # behaviour on every layer that predates this field and every layer
    # that never sets it (§3.1). Mirrors `ShotLayerOutput.enter_on_fragment`
    # (`app/planners/shot/schemas.py`, planner-facing) except for the `0`
    # sentinel that file's own docstring explains (OpenAI structured-output
    # strict mode forbids a default/optional field); this domain schema
    # carries no such constraint and uses a real `None`.
    #
    # A `background` layer must never set this - see `Shot`'s own
    # `_background_layer_never_carries_an_entry` validator below for why
    # and where that is enforced.
    enter_on_fragment: int | None = None
    # The RESOLVED half of the pair above: a float offset in SECONDS from
    # this shot's own start, at which this layer's alpha ramp should begin
    # (`app/renderer/parallax.py`). Mirrors `narration_span`'s own split
    # between a planner-authored character range (a creative decision, I2)
    # and the measured seconds that fall out of it once real narration
    # timing exists - resolved at the SAME seam `Shot.duration_s` is
    # itself fitted to narration
    # (`app/timeline/narration_fit.py::resolve_layer_entry_offsets`), never
    # at render time (§4.1/R2 - this is exactly the gap F2's own log
    # named and left open: "layer drift was left a resolver concern, no
    # resolver was written, and every drift shipped as 0.0"). Default
    # `0.0` = present from the start, matching `enter_on_fragment`'s own
    # `None` default and every layer that predates this field.
    enter_offset_s: float = 0.0


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
    # Split-screen second panel (plan §2.6). Empty/`None` on every
    # non-split shot and every Timeline that predates this field.
    # `prompt` is the TOP panel, `secondary_prompt` the BOTTOM; the
    # renderer composites them when `camera.movement == split_frame`
    # and both assets resolved. One still and no second asset is the
    # pre-split static path, never a fake split of one photograph.
    secondary_prompt: str = ""
    secondary_asset_plan: AssetPlan | None = None
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
    # retention_fast_kinetic_text.md K1: at most one kinetic-text cue
    # on this shot. `None` is today's behaviour exactly (§3.1 isolation):
    # every existing timeline and every style that never sets this field
    # renders as it always did. A single optional field, not a list —
    # K3's "at most one cue per shot" is then structural. Mutually
    # exclusive with a non-empty `text_card` (measured: a stacked
    # correction on a title card was unreadable).
    emphasis_cue: EmphasisCue | None = None
    # retention_fast_kinetic_text.md K3: planner-authored "this picture
    # is already a graphic" (option 1 of the three ways to create the
    # signal — not a prompt grep, not vision). The planner wrote the
    # prompt that ASKED for an infographic, so it knows at authoring
    # time. Shot-level so the enforcement pass does not depend on
    # `asset_plan` being present. Default False is today's behaviour
    # exactly (§3.1 isolation): constructing a shot the way every
    # pre-K3 style does (no kwarg) yields False, and a missing field
    # on a stored timeline cannot start dropping cues. K8 (data
    # graphics) reuses this same signal at the opposite polarity —
    # "is this a data shot? then DRAW it" — and is the higher-value
    # consumer; K3 only *enforces* it. K12 is the Shot Planner wiring:
    # `ShotPlanOutput.picture_is_graphic` (required bool, no default)
    # maps through `_to_domain_shot`. The flag describes what the
    # planner INTENDED to acquire; a Pexels result or a human upload
    # via override was never described by the planner, so this field
    # cannot speak for those.
    picture_is_graphic: bool = False
    # long_form_direction.md A8 (2026-09-01): a planner-authored phrase
    # naming a sound the STORY wants at this shot's start ("faint Geiger
    # counter clicking, sparse and distant") - never style-derived (canon
    # 3.1: the planner decides WHAT sound and WHERE; the renderer only
    # executes). `None`/empty is the overwhelming majority of shots - this
    # is for a beat that genuinely turns on a sound, not decoration. A
    # workflow step (`GenerateDiegeticSfxStep`, post-approval, paid) turns
    # a non-empty cue into a real generated clip
    # (`SfxClipSelection(kind=DIEGETIC, shot_id=this shot's id, ...)` on
    # `Timeline.sfx_plan.clips`); `derive_sfx_events` emits one `DIEGETIC`
    # event at this shot's start for every shot that has one. Placement is
    # the shot's start in v1 - word-relative placement via
    # `narration_span` is a later slice (open question 1, §3 A8).
    sfx_cue: str | None = None
    # illustrated_faceless.md F2 (2026-09-04): parallax planes for this
    # shot (`ShotLayer` - see its own docstring for the role/drift/scale
    # shape and why this sits BESIDE `secondary_prompt`/
    # `secondary_asset_plan` rather than reusing them, §6 Q1). Empty on
    # EVERY shot before this field and on every non-parallax shot after
    # it - this is the isolation mechanism (§3.1): empty means today's
    # rendering behaviour exactly, on every existing style, not a
    # convention a caller must remember to honour. See
    # `_layers_and_split_screen_are_mutually_exclusive` below for the
    # one thing that IS enforced.
    layers: list[ShotLayer] = Field(default_factory=list)
    # illustrated_faceless.md F5 (2026-09-05): a progressive reveal of
    # THIS SHOT'S OWN primary picture - element ANIMATION on a flat
    # generated still, not a parallax plane. Deliberately NOT on
    # `ShotLayer`: F2's own layer mechanism exists to separate a picture
    # into depth planes, and the shots F5 targets (a chart, a diagram - a
    # "flat graphic... nothing to separate", per this style's own
    # `parallax` bullet) are exactly the shots this style's fragment
    # tells the planner to SKIP parallax on. A layer-shaped mechanism
    # could never reach the shots it was built for, so this sits on the
    # SHOT itself and acts on the static-image render path
    # (`app/renderer/slideshow.py`), matching `text_card`/`sfx_cue`'s own
    # shot-level (not layer-level) shape immediately above.
    #
    # Same two-field split as `ShotLayer.enter_on_fragment`/
    # `enter_offset_s` (F4), extended from a fragment-anchored POINT (a
    # layer's entry) to a fragment-anchored WINDOW (this shot's own
    # reveal, start fragment through end fragment) - a reveal has both a
    # start AND a completion, and F5 clamps both inside the shot's own
    # duration (see `app/timeline/narration_fit.py::resolve_element_
    # reveals`), not merely the one instant F4's entry clamps.
    # `None` (the default) means no reveal at all - by far the common
    # case, and every shot that predates this field (§3.1).
    reveal_direction: RevealDirection | None = None
    # Planner-authored, 1-indexed, INCLUSIVE fragment numbers - the
    # SAME idiom `ShotPlanOutput.fragment_start`/`fragment_end` and
    # `ShotLayer.enter_on_fragment` already use, for the identical reason
    # (`app/planners/fragments.py`'s own thesis: a model can judge WHICH
    # fragment's words a reveal should track, never predict a duration in
    # seconds that does not exist until narration is measured). Both
    # `None` together with `reveal_direction is None` (§3.1 default);
    # both set together whenever a reveal is requested - enforced below
    # (`_reveal_fields_are_all_or_nothing`). Range-checked against the
    # OWNING SHOT's own `fragment_start`/`fragment_end` in the Shot
    # Planner's own `_make_validator` (not here) - the identical reason
    # `ShotLayerOutput.enter_on_fragment`'s own docstring gives: this
    # schema no longer carries fragment numbers by the time it exists.
    reveal_start_fragment: int | None = None
    reveal_end_fragment: int | None = None
    # The RESOLVED half of the pair above: seconds from this shot's own
    # start at which the reveal begins, and how many seconds it takes to
    # complete - both fitted to measured narration at the SAME seam
    # `Shot.duration_s` itself is fitted at
    # (`app/timeline/narration_fit.py::resolve_element_reveals`), never
    # at render time (§4.1/R2). Default `0.0`/`0.0` on every shot that
    # predates this field and every shot with no reveal, mirroring
    # `enter_offset_s`'s own "0.0 = present from the start" default -
    # here, "0.0 = nothing to reveal" (the renderer never reads either
    # field unless `reveal_direction is not None`).
    reveal_start_offset_s: float = 0.0
    reveal_duration_s: float = 0.0

    @model_validator(mode="after")
    def _layers_and_split_screen_are_mutually_exclusive(self) -> Shot:
        """§6 Q1, binding: `layers` and split-screen's `secondary_prompt`/
        `secondary_asset_plan` are two different compositing operations
        (planes vs. panels) that happen to share a data shape - they may
        legitimately never converge, but no shot may ever be half in
        each system. Checked both directions, matching the shape of
        every other cross-field Timeline invariant in this module."""
        if self.layers and (self.secondary_prompt or self.secondary_asset_plan is not None):
            raise ValueError(
                "Shot.layers and secondary_prompt/secondary_asset_plan are "
                "mutually exclusive (illustrated_faceless.md §6 Q1): layers "
                "composite PLANES (each fills the frame, keyed) and "
                "split-screen composites PANELS (each occupies part of the "
                "frame) - a shot may use one system or the other, never both."
            )
        return self

    @model_validator(mode="after")
    def _background_layer_never_carries_an_entry(self) -> Shot:
        """F4 (illustrated_faceless.md, 2026-09-05): a `background` layer
        is the ground the shot stands on, not something that arrives
        partway through it - fading it in would mean fading in from
        nothing, over nothing. Enforced here, at the domain schema, rather
        than only in the Shot Planner's own output validator
        (`_make_validator`'s `is_parallax` block, `app/planners/shot/
        planner.py`) for the same reason `_layers_and_split_screen_are_
        mutually_exclusive` above is: a `Timeline` is also read back from
        storage and reached by hand-edited/future code paths that never
        pass through the planner at all, and this is the one place both
        of those go through. `app/renderer/parallax.py` also rejects a
        non-zero `enter_offset_s` on a background layer at composite time
        - belt and suspenders, matching this module's existing practice
        of not trusting a single upstream check (`validate_two_layer_shot`
        re-checks role order there too, even though this exact invariant
        already guarantees it structurally)."""
        for layer in self.layers:
            if layer.role is LayerRole.BACKGROUND and layer.enter_on_fragment is not None:
                raise ValueError(
                    "a background layer must never carry enter_on_fragment "
                    "(illustrated_faceless.md F4): it is the ground the shot "
                    "stands on, and fading it in would mean fading in from "
                    "nothing"
                )
        return self

    @model_validator(mode="after")
    def _reveal_fields_are_all_or_nothing(self) -> Shot:
        """F5 (illustrated_faceless.md, 2026-09-05): `reveal_direction`,
        `reveal_start_fragment`, and `reveal_end_fragment` describe ONE
        creative decision and must arrive together or not at all -
        enforced here (not only in the Shot Planner's own
        `_make_validator`) for the same "a Timeline is also read back
        from storage" reason `_background_layer_never_carries_an_entry`
        above already gives. The RANGE check (does the window fall
        inside this shot's own fragment_start/fragment_end) cannot live
        here - by the time a domain `Shot` exists, fragment numbers have
        already been converted into `narration_span`, the identical
        reason `enter_on_fragment` is not range-checked at this level
        either."""
        fields_set = (
            self.reveal_direction is not None,
            self.reveal_start_fragment is not None,
            self.reveal_end_fragment is not None,
        )
        if len(set(fields_set)) != 1:
            raise ValueError(
                "reveal_direction/reveal_start_fragment/reveal_end_fragment "
                "(illustrated_faceless.md F5) must all be set or all be None - "
                "a reveal is one creative decision, not three independent ones"
            )
        if (
            self.reveal_start_fragment is not None
            and self.reveal_end_fragment is not None
            and self.reveal_end_fragment < self.reveal_start_fragment
        ):
            raise ValueError(
                "reveal_end_fragment must be >= reveal_start_fragment "
                "(illustrated_faceless.md F5)"
            )
        return self

    @model_validator(mode="after")
    def _reveal_requires_static_camera(self) -> Shot:
        """F5 (illustrated_faceless.md, 2026-09-05): a reveal wipes this
        shot's own picture into view over time - it IS this shot's
        motion. A moving camera on top of it would need the wipe's mask
        to track a `zoompan`/`crop` expression that itself changes every
        frame, which is unbuilt and unverified (see the plan's own F5
        log entry for why this was refused rather than attempted).
        Refusing the combination outright matches this schema's own
        precedent of refusing rather than silently reconciling two
        compositing ideas that were never designed to agree
        (`_layers_and_split_screen_are_mutually_exclusive` above)."""
        if self.reveal_direction is not None and self.camera.movement != CameraMovement.STATIC:
            raise ValueError(
                "a shot with reveal_direction set must use camera.movement="
                "static (illustrated_faceless.md F5): a reveal is this shot's "
                "own motion, and a moving camera on top of it is refused, not "
                f"composited - got movement={self.camera.movement.value}"
            )
        return self

    @model_validator(mode="after")
    def _emphasis_cue_and_text_card_are_mutually_exclusive(self) -> Shot:
        """K3 (retention_fast_kinetic_text.md), measured: a stacked cue
        on a title card was unreadable. Enforced here so a Timeline read
        back from storage cannot carry both, matching the other
        cross-field refusals in this class. `None`/empty `text_card` is
        the common case and is not a conflict."""
        if self.emphasis_cue is not None and self.text_card:
            raise ValueError(
                "Shot.text_card and Shot.emphasis_cue are mutually exclusive "
                "(retention_fast_kinetic_text.md K3): a title card and a "
                "kinetic cue stacked on the same shot were measured "
                "unreadable"
            )
        return self


# narration_tone_tags.md: the eleven_v3 audio tags a scene may carry.
#
# Verified 2026-09-17 against ElevenLabs' own documentation
# (elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices).
# `serious` was in an earlier draft of this list and is NOT documented -
# it was removed. That mattered: Phase 1c measured `[serious]` shifting
# the read 15.4%, the largest delta of any tag probed, which looked like
# proof it worked. The deliberately-invented `[dramatic]` shifted it 5.8%
# on the same line. Bracketed text perturbs delivery whether or not the
# tag is real, so measured effect is not evidence of support and this
# list must stay tied to the docs.
#
# DELIVERY TONES ONLY, which is narrower than what the docs list. The
# published set also includes one-shot vocal sounds ([laughs], [sighs],
# [clears throat]), sound effects ([gunshot], [applause]) and pauses
# ([short pause]). Those are performances at a moment, not a manner of
# speaking that holds across a scene - prefixing [laughs] to a scene
# inserts a laugh, it does not make the scene laughing. This field
# colours a whole scene's read, so it takes only the tags that can.
#
# The docs note "there are likely many more effective tags beyond this
# list", so additions are expected - but each wants checking against the
# docs rather than against how it sounds, for the reason above.
NARRATION_TONES: frozenset[str] = frozenset(
    {
        "excited",
        "curious",
        "sarcastic",
        "mischievously",
        "happy",
        "sad",
        "angry",
        "annoyed",
        "appalled",
        "thoughtful",
        "surprised",
        "whispers",
    }
)


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
    # Romanized, single-script rendering of `narration_text` for CAPTIONS
    # ONLY (caption_romanization.md). None = not romanized; captions fall
    # back to `narration_text` verbatim, i.e. today's behaviour.
    # NEVER sent to TTS and NEVER indexed by `Shot.narration_span` — those
    # both belong to `narration_text`, whose offsets must stay stable.
    # Do not put this on Shot: cue segmentation slices scene-level text
    # by character span; a per-shot field would need its own offset
    # mapping and re-introduce the coordinate problem the plan avoids.
    caption_text: str | None = None
    # caption_romanization.md §10.3: how many CONSECUTIVE `narration_text`
    # words each whitespace-delimited token of `caption_text` replaces, in
    # order. `None` (every timeline predating this field, and any scene
    # the romanizer left in the plain 1:1 shape) means "one display word
    # per narration word" — today's path, byte-identical output. A group
    # `> 1` exists only to collapse a spelled-out Hindi number
    # (`उन्नीस सौ इकतीस`, 3 words) into one digit token (`1931`) so
    # captions match the text cards' numerals. `sum(caption_word_groups)`
    # must equal the narration word count and `len(caption_word_groups)`
    # must equal the `caption_text` word count — both re-checked in
    # `app/renderer/captions.py` at read time, never trusted from
    # storage alone.
    caption_word_groups: list[int] | None = None
    # narration_tone_tags.md: the eleven_v3 audio tag steering THIS
    # scene's delivery, stored bare (`excited`, not `[excited]`). None =
    # the voice's default read, i.e. every timeline predating this field.
    # Set per scene at the approval gate, after the first narration pass
    # has been heard, and refused once a timeline is approved.
    #
    # NOT named `tone`: `CreativeContext.tone` below is a project-wide
    # planning concept and the collision would be permanent.
    #
    # Deliberately NEVER written into `narration_text`. The tag is
    # prefixed only when the TTS request is built
    # (`timeline/narration_batch.py`) and stripped back out of the
    # returned alignment, so captions and `Shot.narration_span` keep the
    # clean 1:1 character contract they already depend on. It IS part of
    # the narration cache key - see `compute_narration_content_hash`.
    narration_tone: str | None = None

    @field_validator("narration_tone")
    @classmethod
    def _known_tone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        tone = value.strip().lower()
        if tone not in NARRATION_TONES:
            raise ValueError(
                f"unknown narration tone {value!r}; expected one of "
                f"{', '.join(sorted(NARRATION_TONES))}. An unsupported tag is "
                "absorbed silently by eleven_v3 - no error, not spoken, but it "
                "still perturbs the read - so a typo here would be invisible."
            )
        return tone


# retention_fast_kinetic_text.md K5: `#` + 6 hex digits. Empty string is
# not "unset" — that is `None` on the metadata fields below.
_EMPHASIS_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# retention_fast_kinetic_text.md K5 review finding, 2026-09-09. The
# brightest Rec. 601 luma an authored `pivot_ground` may have.
#
# WHY THE PIVOT NEEDS THIS AND NOTHING ELSE DOES. `compositor/src/
# Pivot.tsx` draws the pivot's type `color: WHITE` unconditionally, and
# that is correct by design: the band IS the type's ground, so the
# plate's luma is irrelevant and K4 deliberately does not intervene.
# The consequence is that this ONE colour decides the pivot's contrast
# by itself. K4's `apply_emphasis_treatments` cannot rescue a bad choice
# because it measures the plate UNDER the cue, not the band's own fill.
# Measured through the schema before this guard existed, a
# `pivot_ground` of `#FFFFFF` (luma 255.0), `#FAFAFA` (250.0) or
# `#FFF8F0` (249.2) was accepted and rendered white-on-white.
#
# Unreachable today — nothing authors a palette, so every reel resolves
# to the style band pair. It is here BEFORE K9 (the LLM emphasis pass)
# starts authoring palettes, which is the point of a guardrail.
#
# THE MEASUREMENT BEHIND 140.0. The number is the WCAG 3:1 large-text
# contrast floor for `#FFFFFF` type, converted into this project's
# Rec. 601 scale. 3:1 and not 4.5:1 because the pivot type is 132px at
# 700-weight on a 720-wide canvas — large text by any definition; and
# because 4.5:1 would reject the SHIPPED DEFAULT (`#FF2E2E` measures
# 3.70:1), which is the strongest evidence available that 3:1 is the
# operative floor here. Two ramps were computed over sRGB
# (tmp/k5_pivot_luma/sweep_luma.py) and the boundary was then rendered
# through real Chromium (tmp/k5_pivot_luma/verify_pivot_luma.py):
#
#   neutral grey ramp   last ground at/above 3:1 = grey 148  (luma 148.0)
#   saturated red ramp  last ground at/above 3:1 = #FF5D5D   (luma 141.0)
#   #FF2E2E (shipped)   luma 108.5   3.70:1   — valid, 31.5 units spare
#   #5A00A8 (reviewed)  luma  46.1  10.50:1   — valid, 94 units spare
#   #FFC300 (accent)    luma 190.7   1.61:1   — see the accent note below
#
# 140.0 sits below BOTH crossings: below the neutral one by 8 units and
# just below the shipped default's own hue family, which is the
# pessimistic of the two. Rounded down, never up — rounding up would
# put the limit past a measured failure.
#
# WHAT THIS NUMBER IS NOT. It is not `DARK_MIN_LUMA` (180.0) from
# `app/renderer/emphasis_contrast.py`, and it must not be "unified" with
# it later. That constant answers the opposite polarity — "is this
# surface bright enough that NEAR-BLACK type is safe?" — and a neutral
# ground at luma 180 measures 2.07:1 against white, well under the
# large-text floor. Nor is it `LIGHT_MAX_LUMA` (175.0), which would
# reject `#FF2E2E` at 108.5 only if it were still 105: that threshold
# judges a PHOTOGRAPHIC PLATE that bare type has to survive, where a
# mean hides a range; a band fill is one flat known colour, so it can
# be held to the contrast figure itself rather than to a conservative
# margin.
#
# KNOWN IMPRECISION, recorded rather than hidden. Rec. 601 luma of
# gamma-encoded values is a PROXY for perceived contrast, and it
# disagrees with WCAG by up to ~50 units at the 3:1 line: `#00AE00`
# (luma 102.1) is already at 2.98:1 and this guard admits it, while
# `#C37BC9` (luma 153.4) is exactly 3.00:1 and this guard rejects it. No
# single Rec. 601 threshold can be both hue-exact and admit `#FF2E2E`
# at 108.5, because a pure green crosses the floor BELOW the shipped
# default. The choice is deliberate: one scale the whole feature speaks,
# tuned to the hue family actually in use, catching the failure that
# prompted the finding (a near-white band) with 100+ units to spare.
#
# THIS CONSTANT IS COUPLED TO `Pivot.tsx`. It is only correct while the
# pivot's type is unconditionally white. If the type ever becomes a K4
# treatment, this limit stops being a limit and becomes a band — change
# both together or delete this.
PIVOT_GROUND_MAX_LUMA = 140.0


class EmphasisPalette(BaseModel):
    """The per-project kinetic-text colour pair (K5, decision 7).

    `accent` is the stamp rule and the counter digits/meter.
    `pivot_ground` is the pivot band's fill. White (`#FFFFFF`) and ink
    (`#0A0A0B`) are K4 treatments, not palette, and do not live here.

    `pivot_ground` carries a legibility ceiling the `accent` does NOT
    — see `PIVOT_GROUND_MAX_LUMA` above for the measurement, and
    `_pivot_ground_must_carry_white_type` for which resolution paths it
    guards and why the accent is exempt.
    """

    accent: str
    pivot_ground: str

    @field_validator("accent", "pivot_ground")
    @classmethod
    def _hex_rrggbb(cls, value: str) -> str:
        if not _EMPHASIS_HEX.fullmatch(value):
            raise ValueError("must be a #RRGGBB hex colour")
        return value.upper()

    @field_validator("pivot_ground")
    @classmethod
    def _pivot_ground_must_carry_white_type(cls, value: str) -> str:
        """Reject a band fill the pivot's white type disappears into.

        Runs after `_hex_rrggbb` (pydantic applies same-field validators
        in definition order), so `value` is already `#RRGGBB` and
        uppercased.

        WHY THE ACCENT IS NOT CHECKED HERE. Accent type is drawn on a
        surface K4 measures and adapts — a stamp rule or counter digits
        sit over the plate or over the slab, and
        `apply_emphasis_treatments` picks light / dark / slab for them.
        A light accent is therefore K4's problem, and a ceiling on it
        here would be a second contrast system fighting the first (the
        exact thing K5 is forbidden to become). The pivot is the one
        device whose ground is authored rather than measured, which is
        why it is the one field with a limit.

        WHY THE SCHEMA AND NOT THE RESOLVER. This is the only place that
        stops the illegible pair from being CONSTRUCTED — by a planner,
        by a human override, by an API payload or by a test. Every
        resolution path ends in an `EmphasisPalette(...)` call, so one
        validator guards all of them:

        - `TimelineMetadata.emphasis_palette` — K9's authoring target,
          the path this guard exists for;
        - `TimelineMetadata.emphasis_palette_override` — the human
          override, exactly as capable of being wrong;
        - the pair `resolve_emphasis_palette` builds from
          `settings.emphasis_pivot_ground` (the channel default) and
          from `StylePacingBand.emphasis_pivot_ground` (the style band)
          — both plain `str | None` fields that nothing else validates,
          so an illegible channel default now RAISES when RenderStep
          resolves the palette instead of silently shipping an invisible
          pivot. That is loud, but it is not startup-loud: `settings`
          only holds the string, so the failure surfaces at the first
          render that has an overlay cue. Accepted — an invisible pivot
          that renders "successfully" is strictly worse than a render
          that stops — but do not describe it as validated at boot,
          because it is not.

        One consequence worth naming: a stored timeline that already
        carried an illegible palette would now fail to LOAD rather than
        render wrong. No such document exists — nothing authors palettes
        yet, which is why this landed before K9 rather than after.
        """
        luma = hex_luma(value)
        if luma > PIVOT_GROUND_MAX_LUMA:
            raise ValueError(
                f"pivot_ground {value} has Rec.601 luma {luma:.1f}, above the "
                f"{PIVOT_GROUND_MAX_LUMA:.1f} limit: the pivot band's type is "
                "drawn #FFFFFF unconditionally (the band IS its ground, so "
                "K4's plate contrast cannot rescue it), so white type would be "
                "illegible on a fill this bright. Pick a darker band fill"
            )
        return value


class TimelineMetadata(BaseModel):
    language: str = "en"
    aspect_ratio: str = "9:16"
    resolution: tuple[int, int] = (720, 1280)
    # Stillness-only. `9:16` is a vertical Ken Burns reel; `16:9` / None
    # is the default landscape contemplative frame. Frozen at create_initial.
    frame_aspect: str | None = None
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
    # `None` falls back to `settings.elevenlabs_language_code` (itself
    # None - no hint - by default). A human sets this directly via
    # `POST /projects/{id}/narration/retry-language` (2026-08-24, same
    # shape as `voice_id`/N1 just above) for a project whose script
    # code-switches languages (Hindi/Hinglish) and needs ElevenLabs'
    # `language_code` hint to stop stalling at script-switch boundaries
    # - see `providers/elevenlabs.py`'s `compute_narration_content_hash`
    # docstring for why this is safe to flip experimentally (same cache-
    # key argument `voice_id` already makes).
    language_code: str | None = None
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
    # caption_romanization.md §3.5: True once `RomanizeCaptionsStep` (or
    # the backfill path) has attempted the display-text pass, whether
    # every scene got a `caption_text` or some were left None after
    # repair failed. None on every timeline that predates this field
    # (additive fill).
    #
    # What this actually guards is PARTIAL success (RV-R2, plan §8.3).
    # A scene whose validator could not be satisfied stays `caption_text
    # = None` with its Devanagari intact, so `_nothing_to_romanize` is
    # False forever. Without this flag every later RESUME would re-run
    # the LLM over the whole timeline and append another no-op version.
    # It is NOT protecting against an in-run retry loop: the engine
    # checks `is_satisfied` once, before the step (`engine.py:184-186`),
    # and never re-checks after the step returns "ok" - an earlier
    # version of this comment claimed otherwise.
    caption_romanization_attempted: bool | None = None
    # retention_fast_kinetic_text.md K9/K10: True once EmphasisPassStep
    # has attempted the pass (LLM or dry-run lexical), whether any cue
    # was written. None on every timeline that predates this field.
    # `is_satisfied` keys off this stamp (and narration_locked / style),
    # not "already has a pivot cue" and not "no pivot word" — those
    # skipped stamps and counters. It is NOT a substitute for
    # produced_by — Narration overwrites that.
    emphasis_pass_attempted: bool | None = None
    # retention_fast_kinetic_text.md K5 / decision 7: the per-project
    # kinetic-text palette, authored once and recorded. `None` means
    # unset — stored timelines without the key load as None and the
    # resolver falls through to channel, then the style band. Empty
    # strings are rejected on `EmphasisPalette`, not treated as unset.
    # Precedence (resolved in `resolve_emphasis_palette`, never here):
    # human override > planner-authored > channel default > style band.
    # K9 is the eventual authoring home; this slice only records.
    emphasis_palette: EmphasisPalette | None = None
    # Human override of the pair above, same "two optional fields so
    # precedence is explicit on a single version" shape as
    # `grade_style` vs `render_style`. A later HUMAN `append_version`
    # is not required to win — setting this field on the current
    # document is enough.
    emphasis_palette_override: EmphasisPalette | None = None


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

    # Decision 7 (analysis.md, 2026-08-24): per-track loudness offset in dB
    # a human set at upload time (`POST /{id}/music/upload`'s slider).
    # 0.0 for every provider-selected track, so old timelines and auto
    # selections are byte-identical in behaviour. Applied ON TOP of the
    # style's `music_bed_gain_db` at mux time and hashed into the render
    # fingerprint - moving the slider must miss the cache (R2).
    gain_offset_db: float = 0.0


class ActMusicBed(BaseModel):
    """Track C C7: one bed for one act. Empty `act_beds` on MusicPlan
    means Path A (one bed for the video, `selected_track` only)."""

    act_id: str
    selected_track: MusicTrackSelection | None = None


class SfxKind(StrEnum):
    """One palette slot (plan §5.5). Placement is derived from Timeline
    events; the kind only names which clip to overlay."""

    WHOOSH = "whoosh"  # punch-in
    STINGER = "stinger"  # text card
    TRANSITION = "transition"  # non-cut xfade
    # long_form_direction.md A8 (2026-09-01): the one CONTENT-driven kind -
    # placement comes from `Shot.sfx_cue` being set, not from an editing
    # event. Unlike the three structural kinds above (one shared clip per
    # kind for the whole video), a DIEGETIC clip is per-SHOT - each cue is
    # a different sound, generated (ElevenLabs `/v1/sound-generation`),
    # never searched. See `SfxClipSelection.shot_id`.
    DIEGETIC = "diegetic"


class SfxClipSelection(BaseModel):
    """Provenance of one SFX clip, never its bytes (I2). Same shape as
    `MusicTrackSelection`. Audio at `storage/{project}/sfx/{hash}.mp3`."""

    kind: SfxKind
    provider: str
    track_id: str
    source_url: str
    licence: str
    attribution: str = ""
    content_hash: str
    # C3c/C3d (analysis.md, decision 5b): the clip's MEASURED peak
    # loudness (dBFS, ffmpeg volumedetect at selection/upload time) and
    # real length (ffprobe). Both None on every pre-C3c timeline and
    # under DRY_RUN; None means the renderer falls back to the flat
    # `sfx_gain_db` and a head-trim - exactly yesterday's behaviour.
    # Storing them here puts them inside the hashed timeline document,
    # so a re-measured/re-selected clip invalidates the render cache
    # through existing plumbing (no new fingerprint inputs for these).
    peak_dbfs: float | None = None
    duration_s: float | None = None
    # long_form_direction.md A8: which Shot this DIEGETIC clip belongs to.
    # `None` for every WHOOSH/STINGER/TRANSITION clip (one shared clip per
    # kind - `by_kind` lookup in `render.py::_sfx_overlays` is unchanged
    # for those). Set for DIEGETIC clips only, since `SfxPlan.clips` can
    # hold several different DIEGETIC entries (one per distinct cue) and
    # the renderer must know which shot's event each one answers -
    # `render.py` builds a `shot_id -> clip` map for DIEGETIC lookups
    # instead of the single-clip-per-kind map structural kinds use.
    shot_id: str | None = None
    # long_form_direction.md A11 (2026-09-01): the clip's MEASURED
    # integrated loudness (LUFS, `app/renderer/audio.py::
    # measure_integrated_lufs` - the same ebur128 machinery OQ-1a's final
    # mix already uses), for DIEGETIC clips only. Peak normalisation
    # measures the wrong thing for a cue with a 25-27dB crest (a bell's
    # decay, a Geiger click against near-silence): matching the single
    # loudest instant leaves the audible BODY of the sound tens of dB
    # below a bed matched the same way. `None` for every WHOOSH/STINGER/
    # TRANSITION clip (peak normalisation is correct for those - transient
    # punctuation by design, unchanged by this field's existence) and for
    # every pre-A11 DIEGETIC clip/DRY_RUN fake; `None` means the renderer
    # falls back to the same peak-based path the structural kinds use
    # (`app/assets/sfx_levels.py::diegetic_effective_gain_db`). Measured
    # once at generation time and persisted here - never re-measured at
    # render time (I5) - so it rides into the render fingerprint for free
    # via the ordinary timeline document dump, exactly like `peak_dbfs`
    # and `duration_s` already do.
    loudness_lufs: float | None = None


class SfxPlan(BaseModel):
    """Creative palette + acquired clips (plan §5.5, D6/21.2).

    Queries are the creative half (which kinds of sounds). `clips` and
    `selection_attempted` are filled by `SelectSfxStep` (the three
    structural kinds, pre-approval, searched/free). DIEGETIC clips are
    filled separately by `GenerateDiegeticSfxStep` (post-approval, paid,
    generated) and appended onto the same `clips` list rather than a
    second list - `render.py` already discriminates by `kind`/`shot_id`.
    Placement is NOT stored here — the renderer derives offsets from
    punch-ins, text cards, transitions, and (A8) `Shot.sfx_cue` already on
    the Timeline.
    """

    queries: dict[str, list[str]] = Field(default_factory=dict)
    licence_requirements: list[str] = Field(default_factory=list)
    clips: list[SfxClipSelection] = Field(default_factory=list)
    selection_attempted: bool = False
    # long_form_direction.md A8: shot ids whose diegetic cue generation
    # was attempted and failed (a transient provider error persisted
    # across the bounded step retries, a permanent one, or a budget cap
    # hit) - terminal, like a `failed` ShotBinding, so a resumed run does
    # not hammer the API again for a cue already known not to work this
    # run. That shot simply plays with no diegetic sound (build item 6:
    # "one cue failing must not kill the run").
    diegetic_failed_shot_ids: list[str] = Field(default_factory=list)


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
    # Kept so timelines that predates Q6 still load. The Director no
    # longer writes it; the grade is `STYLE_GRADES` keyed on style name.
    colour_palette: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class Act(BaseModel):
    """long_form_direction.md A3 (2026-08-31): a chapter-level creative
    decision - the title `ActPlanOutput` (`app/planners/act/schemas.py`)
    produces and Path B scene planning used to discard once `act_id` was
    stamped onto each Scene (`app/planners/scene/planner.py::
    _plan_hierarchical`). `id` is the same id that appears in
    `Scene.act_id`; `order` mirrors `ActPlanOutput.order`. Kept as its
    own Timeline-level list rather than denormalised onto every Scene -
    the title belongs to the act, and the I1/I2 "immutable decision
    record" argument that already governs a locked asset (`Shot.
    asset_locked`) applies here exactly as well. See `Timeline.acts`'s
    own docstring for the emptiness convention."""

    id: str
    order: int
    title: str


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
    sfx_plan: SfxPlan | None = None
    scenes: list[Scene] = Field(default_factory=list)
    # long_form_direction.md A3 (2026-08-31): written by hierarchical
    # (Path B) scene planning when N > 70, alongside the `act_id` it
    # already stamps onto each Scene - see `Act`'s own docstring for why
    # this lives here rather than on Scene. Empty on every Path A project
    # (<=70 fragments, every `Scene.act_id` is None) and on every
    # timeline that predates this field - the same "empty means Path A or
    # older" convention `Scene.act_id` itself already documents.
    acts: list[Act] = Field(default_factory=list)

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
