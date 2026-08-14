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
    narration_start: int
    narration_end: int
    duration_s: float
    framing: Framing
    camera: ShotCameraOutput
    transition_out: ShotTransitionOutput
    prompt: str


class ShotPlannerOutput(BaseModel):
    shots: list[ShotPlanOutput]
