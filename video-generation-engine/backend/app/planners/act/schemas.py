"""Structured output for the Act Planner (Track C C1 Path B). Same
strict-mode rules as the Scene Planner: every field required, no
defaults."""

from pydantic import BaseModel


class ActPlanOutput(BaseModel):
    id: str
    order: int
    title: str
    fragment_start: int
    fragment_end: int


class ActPlannerOutput(BaseModel):
    acts: list[ActPlanOutput]
