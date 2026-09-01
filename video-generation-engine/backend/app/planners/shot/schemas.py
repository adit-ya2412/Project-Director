"""API-facing output schema for the Shot Planner. See
app/planners/director/schemas.py for why every field is required and
default-free (OpenAI structured-output strict mode)."""

from pydantic import BaseModel

from app.schemas.timeline import (
    CameraDirection,
    CameraMovement,
    Framing,
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


class ShotPlannerOutput(BaseModel):
    shots: list[ShotPlanOutput]
