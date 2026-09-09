"""API-facing output schema for the emphasis pass (K9).

See `app/planners/director/schemas.py` for why every field is required
and default-free (OpenAI structured-output strict mode). Quantity
checks — one cue per shot, devices in {stamp, counter, pivot},
fragment in range, shot exists — live in the planner's `validate()`,
never this schema.

`device` is a plain string, not `EmphasisDevice`. The domain enum is
deliberately wide so a later device cannot churn stored timelines
(retention_fast_kinetic_text.md Decision 8). Constraining it here
would either narrow that enum or hide an unknown value from the
mapper, which must drop `correction`/`meter`/`comparison`/`question`
without failing the run.

`text_register` is not on this model. Decision 4 is a fixed role
table, derived in code: a field the model could pick would be
"mixed at random".
"""

from pydantic import BaseModel


class EmphasisValuePlanOutput(BaseModel):
    value: int
    # Empty string means none. Required (OpenAI strict mode); the
    # mapper normalises `""` to `None`, same convention as `text_card`.
    unit: str
    cited_fragment: int


class EmphasisCuePlanOutput(BaseModel):
    shot_id: str
    device: str
    # 1-indexed, never seconds. K2 resolves `offset_s` later.
    anchor_fragment: int
    text: str
    # Empty list on stamp/pivot. One cited value on a v1 counter.
    values: list[EmphasisValuePlanOutput]
    # Unused in v1 (correction is not authored). Always emit `""`.
    replaced_text: str


class EmphasisPlannerOutput(BaseModel):
    cues: list[EmphasisCuePlanOutput]
    # `#RRGGBB`. Invalid / near-white pivot_ground is dropped in the
    # mapper (band fallback), not a schema failure.
    accent: str
    pivot_ground: str
