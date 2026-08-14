"""API-facing output schema for the Asset Planner. See
app/planners/director/schemas.py for why every field is required and
default-free (OpenAI structured-output strict mode)."""

from pydantic import BaseModel

from app.schemas.timeline import AssetStrategy, PreferredMediaType


class AssetPlanShotOutput(BaseModel):
    shot_id: str
    strategy: AssetStrategy
    search_queries: list[str]
    preferred_type: PreferredMediaType
    fallback_chain: list[AssetStrategy]
    licence_requirements: list[str]


class AssetPlannerOutput(BaseModel):
    asset_plans: list[AssetPlanShotOutput]
