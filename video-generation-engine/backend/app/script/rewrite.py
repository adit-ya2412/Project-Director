"""Level 3 of the script pre-flight (plan §3.2/§3.3): the actual phrasing
rewrite - splits long sentences (or inserts punctuation) so a fast
style's punctuation-based pacing floor can be reached, for the cases
where levels 1-2 (suggest-only re-punctuation, `app/script/
suggestions.py`) are not enough because the sentences themselves, not
just their punctuation, are too long. Scope is deliberately the
TIGHTEST of the three levels (§3.3): same facts, same order, same
claims - only sentence length and rhythm change.

This module never touches persistence - see `app/api/projects.py`'s
`POST /{project_id}/script/rewrite` endpoint for how an ACCEPTED
`RewriteResult.rewritten_script` becomes a new `ScriptModel` row with
`source="rewritten"` (§3.5, `ProjectRepository.append_rewritten_script`).
Never runs under DRY_RUN or with no provider - same `None`-means-
"nothing to show" convention `check_suitability` already established.

## Why deterministic backstops, not trust in the model (§3.3)

"Your content is historical and there is no fact-check step anywhere in
this pipeline" (§3.3's own warning) - a rewrite is the one place in this
whole system where a model's OWN WORDS could silently replace the
user's, so this is the one place a backstop REJECTS a result outright
rather than merely flagging it for review:

- **numeric tokens preserved as a multiset** - a rewrite that drops or
  invents a number (a date, a percentage, a count) changed a fact, not
  just a rhythm, no matter how fluent the result reads.
- **capitalised entities preserved, as a SET, not a multiset** - a
  legitimate rephrase may swap a second mention of a name for a pronoun,
  so mention COUNT is allowed to change; the name disappearing entirely
  is what would mean the subject itself got lost. A small stoplist of
  common sentence-initial words (`_COMMON_CAPITALIZED_WORDS`) is
  excluded, because re-splitting sentences legitimately creates or
  removes capitalised words like "The"/"It" at new sentence starts -
  without the stoplist, ordinary rephrasing would trip this check
  constantly on words that were never real entities.
- **fragment count actually increased** - if `split_narration_fragments`
  finds the same number of fragments (or fewer), the rewrite changed
  wording without changing the one thing this feature exists to change;
  reject it as a no-op rather than accept a pointless diff.

**These are backstops, not proof** (§3.3's own honesty) - a rewrite can
preserve every number and name and still shift emphasis or nuance. The
side-by-side diff shown to the user, not this function, is the real
safeguard; the checks below only catch mechanical, unambiguous failures
a human skimming a diff might not think to check for (a swapped digit,
a dropped clause that was the only mention of a name).
"""

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.core.config import settings
from app.planners.fragments import split_narration_fragments
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.script.preflight import FeasibilityResult, check_feasibility
from app.script.styles import get_pacing_band

_AGENT_NAME = "script_rewrite"
_PROMPT_VERSION = "v1"

_NUMERIC_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*")
_CAPITALIZED_WORD_RE = re.compile(r"\b[A-Z][A-Za-z]*(?:-[A-Z][A-Za-z]*)*\b")
# Common words that are capitalised only because they start A sentence,
# not because they name anything - excluded so re-splitting sentences
# (which legitimately moves where these land) doesn't produce false
# "entity dropped" rejections. Not exhaustive by design - this is a noise
# filter for the common case, not a grammar model.
_COMMON_CAPITALIZED_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "he",
        "she",
        "they",
        "we",
        "i",
        "you",
        "but",
        "and",
        "so",
        "or",
        "yet",
        "nor",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "as",
        "of",
        "to",
        "from",
        "however",
        "also",
        "then",
        "there",
        "here",
        "when",
        "while",
        "after",
        "before",
        "because",
        "although",
        "since",
        "if",
    }
)


class ScriptRewriteOutput(BaseModel):
    rewritten_script: str


@dataclass(frozen=True)
class RewriteResult:
    """`accepted=False` still carries the attempted rewrite and WHY it
    was rejected - the caller shows the reasons, it never silently
    discards a failed attempt (§3.3: "a model rewriting ... can silently
    introduce a wrong date ... nothing downstream would catch it" - this
    is that catch, made visible rather than swallowed)."""

    rewritten_script: str
    accepted: bool
    rejection_reasons: list[str] = field(default_factory=list)
    original_fragment_count: int = 0
    rewritten_fragment_count: int = 0
    feasibility: FeasibilityResult | None = None


def _numeric_tokens(text: str) -> Counter:
    return Counter(_NUMERIC_TOKEN_RE.findall(text))


def _capitalized_entities(text: str) -> set[str]:
    return {
        word
        for word in _CAPITALIZED_WORD_RE.findall(text)
        if word.lower() not in _COMMON_CAPITALIZED_WORDS
    }


def _validate_rewrite(original: str, rewritten: str) -> list[str]:
    """The three backstops from §3.3, in the order they're most likely
    to catch a real problem: a changed fact first, a lost or invented
    entity second, a no-op rewrite last."""
    reasons: list[str] = []

    original_numbers = _numeric_tokens(original)
    rewritten_numbers = _numeric_tokens(rewritten)
    if original_numbers != rewritten_numbers:
        missing = sorted((original_numbers - rewritten_numbers).elements())
        added = sorted((rewritten_numbers - original_numbers).elements())
        detail = []
        if missing:
            detail.append(f"missing: {missing}")
        if added:
            detail.append(f"added: {added}")
        reasons.append(f"numeric tokens changed ({'; '.join(detail)})")

    original_entities = _capitalized_entities(original)
    rewritten_entities = _capitalized_entities(rewritten)
    dropped_entities = original_entities - rewritten_entities
    invented_entities = rewritten_entities - original_entities
    if dropped_entities:
        reasons.append(f"capitalised entities dropped: {sorted(dropped_entities)}")
    if invented_entities:
        reasons.append(f"capitalised entities invented: {sorted(invented_entities)}")

    original_fragments = len(split_narration_fragments(original))
    rewritten_fragments = len(split_narration_fragments(rewritten))
    if rewritten_fragments <= original_fragments:
        reasons.append(
            f"fragment count did not increase ({original_fragments} -> {rewritten_fragments}) "
            "- rewrite was a no-op for pacing purposes"
        )

    return reasons


async def rewrite_script(
    script: str,
    style: str,
    *,
    provider: PlanningLLMProvider | None,
    llm_call_repo: LlmCallRepository,
    project_id: str,
) -> RewriteResult | None:
    """`None` means "no rewrite was attempted at all" (DRY_RUN, no
    provider configured, or an empty script) - the caller's UI shows
    nothing for this feature rather than a fabricated result, same
    convention as `check_suitability`. A rewrite that WAS attempted
    always returns a `RewriteResult`, accepted or not - see that
    dataclass's own docstring."""
    if settings.dry_run or provider is None or not script.strip():
        return None

    system_prompt = load_prompt(_AGENT_NAME, _PROMPT_VERSION)
    band = get_pacing_band(style)
    target = (
        f"~{band.target_shot_duration_s:.2f}s per shot"
        if band.target_shot_duration_s is not None
        else "no specific pacing target for this style"
    )
    user_content = f"Style: {style} (target: {target})\n\nScript:\n\n{script}"

    completion = await provider.structured_complete(
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=ScriptRewriteOutput,
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
    output = completion.parsed
    assert isinstance(output, ScriptRewriteOutput)
    rewritten = output.rewritten_script

    reasons = _validate_rewrite(script, rewritten)

    return RewriteResult(
        rewritten_script=rewritten,
        accepted=not reasons,
        rejection_reasons=reasons,
        original_fragment_count=len(split_narration_fragments(script)),
        rewritten_fragment_count=len(split_narration_fragments(rewritten)),
        feasibility=check_feasibility(rewritten, style),
    )
