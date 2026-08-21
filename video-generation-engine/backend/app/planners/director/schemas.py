"""API-facing output schema for the Director agent. Deliberately separate
from `app.schemas.timeline.CreativeContext`/`MusicPlan`: those carry
Timeline-IR concerns (defaults, additive-merge semantics); this is only
what we force the model to return.

No length/range constraints and no optional/default fields here
(implementation guide, Timeline IR docstring: numeric/size limits are
enforced by validation after the fact, never baked into the schema) -
OpenAI's structured-output strict mode only supports a narrow subset of
JSON Schema: no `minItems`, and every property must be in `required`
(a field with a default is omitted from `required` by pydantic, which
strict mode rejects). Every field below is therefore required and
default-free; the model must always emit it, even as an empty list.
Quantity checks live in this planner's `validate()` callback instead.
"""

from pydantic import BaseModel

from app.schemas.timeline import EnergyArc


class DirectorCreativeContext(BaseModel):
    tone: str
    visual_style: str
    historical_period: str
    audience: str
    camera_language: str
    constraints: list[str]


class DirectorMusicPlan(BaseModel):
    mood: str
    tempo: str
    energy_arc: EnergyArc
    search_terms: list[str]
    licence_requirements: list[str]


class DirectorOutput(BaseModel):
    creative_context: DirectorCreativeContext
    music_plan: DirectorMusicPlan
