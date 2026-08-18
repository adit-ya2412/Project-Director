"""Request/response shapes for `POST /{project_id}/script/preflight`
(motion_new_styles_and_long_form_videos.md, Track D). Kept separate from
`app/api/projects.py`'s own inline request models (matching that file's
own precedent for anything beyond a couple of fields, e.g. `Timeline`
living in `app/schemas/timeline.py` rather than inline)."""

from pydantic import BaseModel, Field


class ScriptPreflightRequest(BaseModel):
    """Stateless by design (plan §3.5.3): script and style travel in the
    request body, nothing is read from or written to persisted project
    state. This is what makes it safe to call on every keystroke or
    style change without creating a new `ScriptModel` version each
    time."""

    script: str
    style: str


class FragmentEstimateOut(BaseModel):
    index: int
    text: str
    estimated_duration_s: float


class BreakSuggestionOut(BaseModel):
    offset: int
    mark: str
    preview_before: str
    preview_after: str
    reason: str


class StyleSuitabilityOut(BaseModel):
    suitable: bool
    reason: str


class ScriptPreflightResponse(BaseModel):
    style: str
    # Feasibility (blocking, deterministic) - plan §3.1.
    passed: bool
    violations: list[str]
    fragment_count: int
    estimated_total_duration_s: float
    estimated_average_shot_duration_s: float
    fragments: list[FragmentEstimateOut]
    # Level 2 (plan §3.2) - only populated when `passed` is False; a
    # feasible script has nothing to suggest breaking.
    suggested_breaks: list[BreakSuggestionOut]
    # Suitability (warning, LLM judgement) - `None` means no verdict was
    # computed (DRY_RUN, or no LLM provider configured), never a
    # fabricated opinion (`app/script/suitability.py`'s own docstring).
    suitability: StyleSuitabilityOut | None


class ScriptRewriteRequest(BaseModel):
    """Stateless by default, mirroring `ScriptPreflightRequest` (plan
    §3.5.3) - `script`/`style` travel in the request, so a rewrite can be
    tried against draft text before it's ever uploaded. `persist=True`
    is the one deliberate exception: it's the explicit "yes, use this"
    action after a human has reviewed the diff (§3.3's own real
    safeguard) - never persisted automatically just because the
    mechanical backstops passed."""

    script: str
    style: str
    persist: bool = False


class RewriteFeasibilityOut(BaseModel):
    passed: bool
    violations: list[str]
    fragment_count: int
    estimated_total_duration_s: float
    estimated_average_shot_duration_s: float


class ScriptRewriteResponse(BaseModel):
    # `False` only when no rewrite was attempted at all (DRY_RUN, no
    # provider, or empty script) - `app/script/rewrite.py::rewrite_script`'s
    # own `None`-return case.
    attempted: bool
    # Backstop verdict (§3.3) - `False` means the model's own output
    # failed a mechanical check (a changed number, a dropped entity, or a
    # no-op for pacing) and was REJECTED, never persisted regardless of
    # `persist`.
    accepted: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
    rewritten_script: str = ""
    original_fragment_count: int = 0
    rewritten_fragment_count: int = 0
    feasibility: RewriteFeasibilityOut | None = None
    # `True` only when `persist=True` was requested AND `accepted` was
    # `True` - see the endpoint's own docstring for the freeze check this
    # still goes through.
    persisted: bool = False
