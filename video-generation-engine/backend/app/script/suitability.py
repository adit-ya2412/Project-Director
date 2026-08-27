"""Suitability check (plan §3.1, §3.7): an LLM verdict on whether a
script's subject/tone suits a given style. WARNS, never blocks - see
`StyleSuitabilityVerdict`'s own docstring for why blocking on a model's
taste about someone's own script is the wrong default (unlike the
feasibility check in `preflight.py`, which blocks because it is
arithmetic, not opinion).

Deliberately NOT a fifth planner - it never writes to the Timeline, has
no `append_version` call anywhere near it, and does not participate in
the Director/Scene/Shot/Asset chain. Its closest relative is
`app/assets/depiction_check.py`: an LLM-backed verdict that only ever
informs a human, following the same "provider `None` short-circuits" and
"record the call, return the parsed verdict" shape - the difference is
this checks a whole SCRIPT against a STYLE description, in one plain-text
call, rather than an image against a fixed constraint list, so it uses
`PlanningLLMProvider.structured_complete` directly rather than a
dedicated vision protocol method.

**Recomputed every call, never cached or persisted** (plan §3.5.4,
decided 2026-08-17) - no table shape in this codebase fits `(script_hash,
style) -> verdict`, and the check only ever runs on a genuine user-
initiated request (the free arithmetic check in `preflight.py` is what
runs on every keystroke), so the cost is one cheap call per real request,
not per edit.
"""

import uuid

from app.core.config import settings
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider, StyleSuitabilityVerdict
from app.repositories.llm_call_repository import LlmCallRepository

_AGENT_NAME = "script_suitability"
_PROMPT_VERSION = "v1"

_STYLE_DESCRIPTIONS = {
    "documentary_archival": (
        "slow, measured pacing; long holds; a gentle Ken Burns drift across "
        "still photographs. Suits factual, historical, or process-driven "
        "material with a real archival visual record."
    ),
    "retention_fast": (
        "rapid cuts, punch-in zoom snaps, driving pace. Suits punchy, "
        "energetic, promotional, or explainer content; a poor fit for "
        "solemn or weighty subject matter."
    ),
    "stillness": (
        "long static holds, no camera motion, deliberate quiet. Suits "
        "content whose power is in restraint - memorial, reflection, "
        "understatement."
    ),
    # Feature B (style_extensions.md §4) / prompt_fixes.md §3.1: the 4th
    # style shipped in STYLE_PACING_BANDS and this dict was not updated,
    # so `.get(style, style)` fed the model its own name as a description
    # and it fabricated a verdict. Keep in lockstep with
    # STYLE_PACING_BANDS - test_suitability.py asserts the two sets match.
    "archival_montage": (
        "harder-cut archival montage in 9:16, with frequent full-frame "
        "text cards as chapter markers. Suits historical or process-driven "
        "material that has a real archival visual record but wants punchier "
        "rhythm than long-form documentary; a poor fit for solemn memorial, "
        "or for purely promotional content with no archival character."
    ),
}


def _description_for(style: str) -> str:
    """Loud on an unknown style - never fall back to the name itself.
    By the time this is called, `style` is a STYLE_PACING_BANDS key
    (the preflight endpoint 400s otherwise), so a miss here is a
    registry/descriptions drift, not a typo. Raising is what makes
    style #5 fail in review instead of shipping a fabricated verdict
    (prompt_fixes.md §3.1)."""
    try:
        return _STYLE_DESCRIPTIONS[style]
    except KeyError:
        raise KeyError(
            f"no suitability description for style {style!r} - "
            f"known: {sorted(_STYLE_DESCRIPTIONS)}"
        ) from None


async def check_suitability(
    script: str,
    style: str,
    *,
    provider: PlanningLLMProvider | None,
    llm_call_repo: LlmCallRepository,
    project_id: str,
) -> StyleSuitabilityVerdict | None:
    """`None` means "no verdict computed" - the caller's UI shows nothing
    for this half of the pre-flight rather than a fabricated opinion.
    Two legitimate no-call cases, the same shape `_resolve_narration_
    audio`/`_resolve_music_track` already established for DRY_RUN
    (app/workflow/steps/render.py): `settings.dry_run` (no fake
    implementation of `structured_complete` exists in this codebase for
    an arbitrary new response model - the fake planning path
    (`FakeTimelinePlanner`) bypasses individual LLM calls entirely by
    loading a canned fixture Timeline, which has nothing to offer here),
    and `provider is None` (no real provider was constructed - mirrors
    `check_candidate_plausibility`'s own `provider is None` no-call
    case exactly)."""
    if settings.dry_run or provider is None or not script.strip():
        return None

    system_prompt = load_prompt(_AGENT_NAME, _PROMPT_VERSION)
    style_description = _description_for(style)
    user_content = (
        f"Style under consideration: {style}\n"
        f"Style description: {style_description}\n\n"
        f"Script:\n\n{script}"
    )
    completion = await provider.structured_complete(
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=StyleSuitabilityVerdict,
    )
    await llm_call_repo.insert(
        project_id=uuid.UUID(project_id),
        agent=_AGENT_NAME,
        prompt_version=_PROMPT_VERSION,
        model=completion.model,
        request=completion.request,
        response=completion.response,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )
    verdict = completion.parsed
    assert isinstance(verdict, StyleSuitabilityVerdict)
    return verdict
