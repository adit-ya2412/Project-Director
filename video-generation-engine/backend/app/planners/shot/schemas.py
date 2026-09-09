"""API-facing output schema for the Shot Planner. See
app/planners/director/schemas.py for why every field is required and
default-free (OpenAI structured-output strict mode)."""

from pydantic import BaseModel

from app.schemas.timeline import (
    CameraDirection,
    CameraMovement,
    Framing,
    LayerRole,
    RevealDirection,
    ShotIntent,
    TransitionType,
)


class ShotCameraOutput(BaseModel):
    movement: CameraMovement
    direction: CameraDirection
    intensity: float


class ShotTransitionOutput(BaseModel):
    type: TransitionType
    duration_s: float


class ShotLayerOutput(BaseModel):
    """One plane of a `parallax` shot (illustrated_faceless.md §2.2/F2a).
    Mirrors `Shot.layers`' own `ShotLayer` shape, narrowed to what the
    Shot Planner actually authors: `asset_plan`/`drift_x`/`drift_y`/
    `scale` stay resolver/Asset-Planner concerns, the same way top-level
    `Shot.asset_plan` is never on `ShotPlanOutput` either -
    `app/planners/shot/planner.py::_to_domain_shot` always sets it to
    `None` today, and F2's own log names filling a layer's `asset_plan`
    from a planner as later scope, not this one.

    `enter_on_fragment` (F4, illustrated_faceless.md §2/F4): a 1-indexed
    fragment number - the SAME idiom `ShotPlanOutput.fragment_start`/
    `fragment_end` already use, and for the identical reason (see that
    field's own docstring) - naming the fragment whose words this layer
    should fade in on, or the SENTINEL `0` for "present for the whole
    shot" (by far the common case, even among parallax shots). Required,
    with no Python-level default, exactly like `role`/`prompt` above and
    like `text_card`/`sfx_cue` on `ShotPlanOutput` one level up: this
    class docstring's own module header explains why (OpenAI structured-
    output strict mode requires every field in `required`, and pydantic
    drops a defaulted field from `required` when generating the JSON
    schema - a field the model is never asked for cannot be range-checked
    or converted to `None`, it simply never arrives). `app/planners/shot/
    planner.py::_to_domain_shot` normalises `0 -> None` when building the
    domain `ShotLayer`, exactly like `s.text_card.strip() or None` there.
    Range-checked against the OWNING SHOT's own `fragment_start`/
    `fragment_end` in `_make_validator` (not here): a layer cannot see its
    parent shot's fragment range, so that check can only happen where
    both are in scope - the shot-level output, not the layer's own nested
    model."""

    role: LayerRole
    prompt: str
    enter_on_fragment: int


class ShotPlanOutput(BaseModel):
    id: str
    order: int
    intent: ShotIntent
    intent_text: str
    # 1-indexed, INCLUSIVE fragment numbers (M5 hardening, 2026-08-15) -
    # NOT character offsets. See app/planners/shot/fragments.py's own
    # docstring for why: three separate incidents of a model doing
    # unreliable character arithmetic (cross-scene shot ids, the outer
    # narration boundary, internal boundaries splitting mid-word and
    # mid-grapheme-cluster) are all one root cause - a deterministic
    # structural fact was being delegated to a language model. A shot
    # names the CONTIGUOUS RANGE of numbered fragments it covers
    # ("fragments 1 to 2"); app/planners/shot/planner.py converts that
    # range back into the exact character span `Shot.narration_span`
    # has always stored - this field changes what the model is asked
    # for, never what the Timeline persists.
    fragment_start: int
    fragment_end: int
    duration_s: float
    framing: Framing
    camera: ShotCameraOutput
    transition_out: ShotTransitionOutput
    prompt: str
    # Bottom panel of a split_frame shot. Empty string on every other
    # movement (OpenAI strict mode: required, never omitted).
    secondary_prompt: str
    # Full-frame text card for THIS shot (Feature B, style_extensions.md
    # §4.4): a short structural title/heading the renderer burns over the
    # shot's own on-screen window (`Shot.text_card`,
    # app/renderer/text_cards.py - render side pre-exists this field).
    # Empty string on almost every shot (OpenAI strict mode: required,
    # never omitted) - which shots carry one is a per-style creative
    # decision, driven by style fragments like archival_montage.md.
    text_card: str
    # long_form_direction.md A8 (2026-09-01): a phrase naming a sound the
    # STORY wants at this shot's start ("faint Geiger counter clicking,
    # sparse and distant"), or the empty string (OpenAI strict mode:
    # required, never omitted) for the vast majority of shots -
    # `app/planners/shot/planner.py::_to_domain_shot` empty-string-to-None
    # normalises it, same convention as `text_card` above.
    sfx_cue: str
    # retention_fast_kinetic_text.md K12: True iff this shot's picture's
    # job is to DISPLAY INFORMATION (chart/graph/diagram/infographic/
    # dashboard/table/map-with-data), not to show a scene. False for the
    # vast majority. Required, no Python default: OpenAI structured-
    # output strict mode (see this module's docstring) drops a defaulted
    # field from `required`, and a field the model is never asked for
    # cannot land on `Shot`. Domain `Shot.picture_is_graphic` already
    # defaults False so a stored timeline without the field still loads.
    picture_is_graphic: bool
    # illustrated_faceless.md F2a (2026-09-05): the two planes of a
    # `movement: parallax` shot (background then subject) - `[]` on
    # every other movement (OpenAI strict mode: required, never omitted;
    # no `minItems` here per this file's own docstring rule - quantity
    # checks belong in `_make_validator` below, never the schema).
    # `app/planners/shot/planner.py::_to_domain_shot` converts each entry
    # to a `ShotLayer`.
    layers: list[ShotLayerOutput]
    # illustrated_faceless.md F5 (2026-09-05): a progressive reveal of
    # THIS SHOT'S OWN picture - a bar climbing, an arrow drawing itself -
    # for the rare shot whose picture is a chart/diagram (the shots this
    # style's own `parallax` bullet already tells the planner to SKIP
    # parallax on: "a flat graphic, a chart... nothing to separate").
    # `RevealDirection.NONE` (required, OpenAI strict mode - see this
    # module's own docstring) is the sentinel for "no reveal", the
    # overwhelming majority of shots even in this style.
    # `reveal_start_fragment`/`reveal_end_fragment` are `0` (sentinel,
    # same convention as `ShotLayerOutput.enter_on_fragment`) whenever
    # `reveal_direction` is `NONE`; both must be non-zero, contiguous, and
    # within THIS shot's own `fragment_start`/`fragment_end` otherwise -
    # checked in `_make_validator` (a layer/shot cannot see its own
    # fragment range from inside the nested output; the shot-level
    # output is where both are already in scope, the same reasoning
    # `ShotLayerOutput.enter_on_fragment`'s own docstring gives).
    reveal_direction: RevealDirection
    reveal_start_fragment: int
    reveal_end_fragment: int


class ShotPlannerOutput(BaseModel):
    shots: list[ShotPlanOutput]
