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


class ShotPlannerOutput(BaseModel):
    shots: list[ShotPlanOutput]
