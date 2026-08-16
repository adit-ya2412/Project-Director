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
    # 1-indexed, INCLUSIVE fragment numbers into the SCRIPT's own
    # fragment list (S2, 2026-08-16) - NOT the scene's retyped
    # `narration_text`. See app/planners/fragments.py's own docstring for
    # why: the Scene Planner used to be asked to reproduce the script's
    # words verbatim per scene, and a concatenation check caught it
    # failing to do so (dropped/added/reordered words) - the same
    # "delegate a deterministic structural fact to a language model"
    # mistake S1 had already fixed for the Shot Planner. A scene names
    # the CONTIGUOUS RANGE of numbered script fragments it covers
    # ("fragments 1 to 3"); app/planners/scene/planner.py converts that
    # range back into the exact `narration_text` slice `Scene.
    # narration_text` has always stored - this field changes what the
    # model is asked for, never what the Timeline persists.
    fragment_start: int
    fragment_end: int
    duration_s: float


class ScenePlannerOutput(BaseModel):
    scenes: list[ScenePlanOutput]
