"""Request/response shapes for `POST /{project_id}/script/preflight`
(motion_new_styles_and_long_form_videos.md, Track D). Kept separate from
`app/api/projects.py`'s own inline request models (matching that file's
own precedent for anything beyond a couple of fields, e.g. `Timeline`
living in `app/schemas/timeline.py` rather than inline)."""

from pydantic import BaseModel


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
