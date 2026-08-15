"""Director-constraint enforcement on generated media (M6.5, A12-A14,
A18-A19 - see docs/13_Implementation_Guide.md, Phase M6.5). The vision
model returns a verdict; this module and its caller (`ResolveAssetsStep`)
decide what happens next - the model never touches state, IO, or money
(I4). Generated media only: a searched asset never reaches THIS check -
it asks "does this violate a fixed constraint", a question that only
makes sense for something the system itself produced. A searched asset
gets its own, different vision check now (A16 resolved as A30 - "does
this genuinely depict the subject") - see `app/assets/depiction_check.py`.

Two independent ways to make zero calls, both legitimate:
- `constraints` is empty - most projects' `creative_context.constraints`
  is non-empty (the Director writes it once, shared by every shot), but
  an empty list is a real possibility and there is no vision question to
  ask when there's nothing to check against.
- `provider` is None - the same idiom `ResolveAssetsStep` already uses
  for `image_provider`/`video_provider`/`entity_provider` (`None if
  settings.dry_run else RealThing()`), so DRY_RUN (or "no vision model
  configured") never has to be special-cased here; the caller decides
  once, by which object it constructs, and this module just honours
  whatever it's handed.
"""

import hashlib
import uuid

from app.providers.base import ConstraintCheckRequest, ConstraintVerdict, VisionConstraintProvider
from app.repositories.llm_call_repository import LlmCallRepository

_NOT_VIOLATED = ConstraintVerdict(violated=False, violated_constraint="", reason="")

_AGENT_NAME = "constraint_check"
_PROMPT_VERSION = "v1"


async def check_generated_image_constraints(
    *,
    provider: VisionConstraintProvider | None,
    llm_call_repo: LlmCallRepository,
    project_id: uuid.UUID,
    image: bytes,
    image_content_type: str,
    shot_prompt: str,
    constraints: list[str],
) -> ConstraintVerdict:
    """Checks one generated image against `constraints` (A12). Recorded
    via `llm_call_repo` exactly like every other model call
    (implementation guide, Phase M5 advice: "record every LLM exchange")
    - but only when a call actually happened; the two no-call cases above
    return the same unconditional "not violated" verdict without
    touching the repository at all."""
    if not constraints or provider is None:
        return _NOT_VIOLATED

    completion = await provider.check_constraints(
        ConstraintCheckRequest(
            image=image,
            image_content_type=image_content_type,
            shot_prompt=shot_prompt,
            constraints=constraints,
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
    # this model via `response_format=ConstraintVerdict` - not re-derived
    # or re-validated here, just narrowed for the type checker.
    assert isinstance(verdict, ConstraintVerdict)
    return verdict


def build_revised_prompt(base_prompt: str, violated_constraints: list[str]) -> str:
    """A18: the "revised prompt" is a deterministic function of the base
    prompt and the constraints violated SO FAR - never a second LLM call
    to rewrite it. Rebuilt from `base_prompt` fresh every time (rather
    than appending onto whatever the previous attempt's prompt already
    was), for two reasons:

    - **Deduplication.** De-duplicated here (order of first appearance
      preserved), not just trusted from the caller - if the same
      constraint is violated twice running, it appears in the appended
      block once, not twice. Repeating an identical instruction to an
      image model is not a stronger instruction, just a longer prompt.
    - **A clean resume path.** Because this is a pure function of
      `(base_prompt, violated_constraints)`, a caller that recovers
      `violated_constraints` from persisted state (a prior attempt's
      stored verdict, not string-parsed back out of a free-text error
      column - see `GeneratedClipModel.violated_constraint`) can
      reconstruct the exact same prompt a fresh run would have produced,
      without replaying every attempt in order.

    `violated_constraints` empty (attempt 0) returns `base_prompt`
    unchanged."""
    if not violated_constraints:
        return base_prompt
    distinct: list[str] = []
    for constraint in violated_constraints:
        if constraint not in distinct:
            distinct.append(constraint)
    directives = "\n".join(f"- {c}" for c in distinct)
    return (
        f"{base_prompt}\n\nHard constraints - the image must NOT show or imply any of:\n"
        f"{directives}"
    )


def seed_for_attempt(project_seed: int, attempt: int, max_attempts: int) -> int:
    """A13's two regeneration levers, in order: attempt 0 is always the
    project's fixed seed (M7's per-project stylistic consistency). The
    varied-seed lever - the SECOND lever, only used once the first
    (revised prompt, SAME seed) has already failed - fires on the LAST
    attempt the configured cap allows, whatever that cap is.

    Deliberately not a hardcoded attempt index: at the default
    `max_attempts=3` that's attempt 2, but hardcoding "2" would silently
    stop the seed from ever varying if the cap were configured to 2 - the
    loop would only ever reach attempts 0 and 1, both "less than 2", and
    the second lever would quietly never fire. Deriving the switchover
    from `max_attempts` itself keeps the two levers meaningful at any
    configured cap (bounded below at 1, so attempt 0 - which must always
    get the project seed - is never itself past the switchover)."""
    switchover = max(max_attempts - 1, 1)
    if attempt < switchover:
        return project_seed
    return varied_seed(project_seed, attempt)


def varied_seed(project_seed: int, attempt: int) -> int:
    """A13's second regeneration lever - a deterministically varied seed,
    never `random`. Derived from the project seed and the attempt index,
    so re-running the exact same shot/attempt after a crash lands on the
    identical seed (replayable, I5-adjacent), while still genuinely
    differing from the project's normal fixed seed - trading away M7's
    per-project stylistic consistency only once the first lever (revised
    prompt, SAME seed) has already failed once."""
    return int(hashlib.sha256(f"{project_seed}:{attempt}".encode()).hexdigest()[:8], 16)
