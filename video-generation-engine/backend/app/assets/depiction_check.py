"""Vision-verification of SEARCHED assets (M6.5, A16 -> A30 - see
docs/13_Implementation_Guide.md, Phase M6.5). A16 deferred this pending
evidence from A1/A2 (entity retrieval); A30 resolves it narrowly, against
that evidence: the 7 shots still wrong on the A17 benchmark are shots
whose candidate pool contains nothing genuinely on-topic at all, so
vision verification cannot conjure a better photograph - it cannot fix
retrieval. Its value is different: detecting that the best candidate a
rung produced is STILL wrong, so `ResolveAssetsStep` drops it and falls
through the ladder (to the next rung, or eventually to generation/a
human) instead of confidently shipping a confident-looking wrong answer.
An honest miss beats a confident wrong answer.

Scope, per A30 exactly:
  - the TOP-ranked candidate only, never a whole pool (one call, not N) -
    enforced by the CALLER (`ResolveAssetsStep`), not here; this module
    just answers the question for whatever single candidate it's handed.
  - skipped entirely for an entity-curated candidate (A2) - a human
    already curated those; re-checking them would let an automated
    heuristic second-guess a human curation the same way A24 refuses to
    let it second-guess an override. Also enforced by the caller (this
    module has no notion of `entity_curated` at all).
  - a failure drops the candidate; it never fails the shot (per-shot
    isolation, Principle 10, same as every other gate here).

Same `None`-provider/DRY_RUN idiom as `app/assets/constraint_check.py`,
and the same `llm_call` audit path - this is a sibling module, not a
rewrite, because the question it asks ("does this depict X") is
genuinely different from constraint_check's ("does this violate Y"), per
A30's own scope: a shared prompt would blur two different judgements.
"""

import uuid

from app.providers.base import DepictionCheckRequest, DepictionVerdict, VisionConstraintProvider
from app.repositories.llm_call_repository import LlmCallRepository

_DEPICTS = DepictionVerdict(depicts=True, reason="")

_AGENT_NAME = "depiction_check"
_PROMPT_VERSION = "v1"


async def check_candidate_depicts_subject(
    *,
    provider: VisionConstraintProvider | None,
    llm_call_repo: LlmCallRepository,
    project_id: uuid.UUID,
    image: bytes,
    image_content_type: str,
    shot_prompt: str,
    search_subject: str,
) -> DepictionVerdict:
    """Checks whether `image` genuinely depicts `search_subject`. Two
    legitimate no-call cases, mirroring `check_generated_image_constraints`
    exactly: `provider is None` (DRY_RUN, or no vision model configured -
    the caller decides once, by which object it constructs) and
    `search_subject` blank (nothing to check the image against - a shot
    with no search terms at all, which should not happen in practice but
    is handled the same refuse-to-guess way rather than crashing)."""
    if provider is None or not search_subject.strip():
        return _DEPICTS

    completion = await provider.check_depiction(
        DepictionCheckRequest(
            image=image,
            image_content_type=image_content_type,
            shot_prompt=shot_prompt,
            search_subject=search_subject,
        )
    )
    await llm_call_repo.insert(
        project_id=project_id,
        agent=_AGENT_NAME,
        prompt_version=_PROMPT_VERSION,
        model=completion.model,
        request=completion.request,
        response=completion.response,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )
    verdict = completion.parsed
    # The provider's own contract (real or fake) is to return exactly
    # this model via `response_format=DepictionVerdict` - not re-derived
    # or re-validated here, just narrowed for the type checker.
    assert isinstance(verdict, DepictionVerdict)
    return verdict
