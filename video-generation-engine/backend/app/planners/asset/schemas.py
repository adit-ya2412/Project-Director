"""API-facing output schema for the Asset Planner. See
app/planners/director/schemas.py for why every field is required and
default-free (OpenAI structured-output strict mode)."""

from pydantic import BaseModel

from app.schemas.timeline import AssetStrategy, PreferredMediaType


class AssetPlanShotOutput(BaseModel):
    shot_id: str
    # The named real-world subject this shot depicts (M6.5, A1) - e.g.
    # "Leuna-Werke", "Fischer-Tropsch process", "Sasol". Required (like
    # every field here, for OpenAI structured-output strict mode) but must
    # be allowed to be the empty string: a generic scene-setting shot with
    # no single nameable subject should say so honestly rather than invent
    # one. See app/prompts/asset_planner/v1.md for the worked examples.
    entity: str
    strategy: AssetStrategy
    search_queries: list[str]
    preferred_type: PreferredMediaType
    fallback_chain: list[AssetStrategy]
    licence_requirements: list[str]


class AssetPlannerOutput(BaseModel):
    asset_plans: list[AssetPlanShotOutput]
    # Bottom-panel plans for split_frame shots only. Empty when the
    # scene has none. Same shot_id as the matching primary plan
    # (OpenAI strict mode: required, never omitted).
    secondary_asset_plans: list[AssetPlanShotOutput]
