"""API-facing output schema for the Scene Planner. See
app/planners/director/schemas.py for why every field is required and
default-free (OpenAI structured-output strict mode)."""

from pydantic import BaseModel


class ScenePlanOutput(BaseModel):
    id: str
    order: int
    title: str
    summary: str
    emotion: str
    narrative_purpose: str
    narration_text: str
    duration_s: float


class ScenePlannerOutput(BaseModel):
    scenes: list[ScenePlanOutput]
