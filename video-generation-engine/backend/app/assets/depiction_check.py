"""Vision-verification of SEARCHED assets (M6.5, A16 -> A30 -> A30a - see
docs/13_Implementation_Guide.md, Phase M6.5). A16 deferred this pending
evidence from A1/A2 (entity retrieval); A30 resolved it narrowly against
that evidence; A30a recalibrated it after A30's own live measurement
showed it asking a question the model cannot actually answer.

## What changed, and why (A30a)

A30, as first built, asked "does this image genuinely depict the SPECIFIC
subject searched for". Measured live against the real Hindi fixture (a
real control run, the check forced to always pass, isolating its exact
effect from ranking/relevance): it correctly eliminated all 5
unambiguously wrong picks in the benchmark's regression table (a Greek
topographic map, 2016 costumed re-enactor photos, a burning torpedoed
ship, a derelict Polish coal elevator, generic depot buildings with no
tanks) - but it ALSO dropped two genuinely correct images, a real
Bundesarchiv Leuna photograph and a real Fischer-Tropsch process diagram.
Read the model's own recorded reasoning for those two rejections: in both
cases it said, in effect, "nothing in this image specifically confirms
this is THAT named place/process." That is true, and it is also not a
question pixels can ever answer - the identity of a specific named
industrial site lives in an archive's catalogue metadata (a filename, a
caption), which a vision model never sees. Asking it to verify that
identity anyway does not add signal; it just converts "we don't actually
know" into a confident-sounding, costly "no".

A30a asks a narrower, genuinely answerable question instead:
`check_candidate_plausibility` - is this image CONFIDENTLY wrong on
visible, CHECKABLE subject-matter facts (which region/country a map
shows, which general type of object/vehicle/structure is present,
whether the material is genuinely archival or a modern/re-enactment
scene)? An unverifiable-but-plausible SPECIFIC identity (this industrial
photograph really is Leuna, versus merely similar to it) is not a reason
to reject - that passes now. The bias is deliberate and asymmetric: a
false reject permanently discards a real, usable archival image before a
human ever sees it; a false accept only costs one image a human still
sees at the approval gate and can override (A9/A24) - the cheaper
mistake to make by design.

Two calibration passes were needed, not one - measured, not guessed on
the second try either. The FIRST A30a wording ("is this confidently a
different kind of subject") correctly restored both dropped-but-correct
images, but ALSO let two of the five originally-eliminated wrong picks
back in: the model accepted a map of Greece as "consistent with the
general theme of a resource map" (true of maps in general, false of
THIS one's actual content) and accepted photos of modern re-enactors on
motorcycles as "plausibly relat[ing] to wartime Germany" despite showing
no tanks at all - vague thematic resemblance, exactly what the ORIGINAL
A30 prompt correctly refused to accept, quietly returning under looser
wording. See `app/providers/openai_provider.py:check_depiction`'s own
docstring for the full two-round account and the concrete positive/
negative examples the prompt was rewritten with to fix it.

Scope, unchanged from A30:
  - the TOP-ranked candidate only, never a whole pool (one call, not N) -
    enforced by the CALLER (`ResolveAssetsStep`), not here; this module
    just answers the question for whatever single candidate it's handed.
  - skipped entirely for an entity-curated candidate (A2) - a human
    already curated those; re-checking them would let an automated
    heuristic second-guess a human curation the same way A24 refuses to
    let it second-guess an override. Also enforced by the caller (this
    module has no notion of `entity_curated` at all).
  - a rejection drops the candidate; it never fails the shot (per-shot
    isolation, Principle 10, same as every other gate here).

Same `None`-provider/DRY_RUN idiom as `app/assets/constraint_check.py`,
and the same `llm_call` audit path - this is a sibling module, not a
rewrite, because the question it asks ("is this confidently something
else") is genuinely different from constraint_check's ("does this
violate a fixed rule"), per A30's own scope: a shared prompt would blur
two different judgements.
"""

import uuid

from app.assets.llm_pricing import attach_llm_call_pricing
from app.providers.base import DepictionCheckRequest, DepictionVerdict, VisionConstraintProvider
from app.repositories.llm_call_repository import LlmCallRepository

# Not confidently wrong is the safe default (A30a) - both no-call cases
# below mean "nothing to check against", which must never itself become
# a reason to drop a candidate.
_NOT_CONFIDENTLY_WRONG = DepictionVerdict(confidently_wrong=False, reason="")

_AGENT_NAME = "depiction_check"
# v3: same A30a plausibility question, plus OQ-2 subject focal_x/focal_y.
_PROMPT_VERSION = "v3"


async def check_candidate_plausibility(
    *,
    provider: VisionConstraintProvider | None,
    llm_call_repo: LlmCallRepository,
    project_id: uuid.UUID,
    image: bytes,
    image_content_type: str,
    shot_prompt: str,
    search_subject: str,
) -> DepictionVerdict:
    """Checks whether `image` is CONFIDENTLY a different kind of subject
    than `shot_prompt` describes (A30a) - not whether it specifically
    confirms `search_subject`'s named identity, which is an unanswerable
    question from pixels alone (see module docstring). Two legitimate
    no-call cases, mirroring `check_generated_image_constraints` exactly:
    `provider is None` (DRY_RUN, or no vision model configured - the
    caller decides once, by which object it constructs) and
    `search_subject` blank (nothing to check the image against - a shot
    with no search terms at all, which should not happen in practice but
    is handled the same refuse-to-guess way rather than crashing)."""
    if provider is None or not search_subject.strip():
        return _NOT_CONFIDENTLY_WRONG

    completion = await provider.check_depiction(
        DepictionCheckRequest(
            image=image,
            image_content_type=image_content_type,
            shot_prompt=shot_prompt,
            search_subject=search_subject,
        )
    )
    request, pricing = attach_llm_call_pricing(
        model=completion.model,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        request=completion.request,
    )
    await llm_call_repo.insert(
        project_id=project_id,
        agent=_AGENT_NAME,
        prompt_version=_PROMPT_VERSION,
        model=completion.model,
        request=request,
        response=completion.response,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        cost_cents=pricing.cost_cents,
        input_usd_per_1m=pricing.input_usd_per_1m,
        output_usd_per_1m=pricing.output_usd_per_1m,
    )
    verdict = completion.parsed
    # The provider's own contract (real or fake) is to return exactly
    # this model via `response_format=DepictionVerdict` - not re-derived
    # or re-validated here, just narrowed for the type checker.
    assert isinstance(verdict, DepictionVerdict)
    return verdict
