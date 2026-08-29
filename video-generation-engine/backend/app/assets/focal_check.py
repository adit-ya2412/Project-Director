"""Subject-location call (OQ-2, re-cut 2026-08-29 — output_quality_pass.md §14).

Mirrors `app/assets/depiction_check.py`: one provider call, one `llm_call`
audit row, one narrow verdict. Separate from the depiction gate on
purpose — see `SubjectFocal` in `app/providers/base.py` for the measured
reasons (the cheap model cannot localise; the gate's A30a calibration
must not move underneath it).

## Refuse to guess, rather than return a centre

`check_candidate_plausibility` has a safe default (`confidently_wrong=
False` — keep the image, a human sees it at the approval gate). This has
no equivalent: there is no safe fabricated coordinate. A silent
`(0.5, 0.5)` is exactly the bug this re-cut exists to remove, because the
renderer treats it as "no focal given" and the sidecar records it as a
vision answer. So every failure here returns `None`, and the CALLER
writes an explicit fallback sidecar and logs it.
"""

from __future__ import annotations

import uuid

from app.assets.llm_pricing import attach_llm_call_pricing
from app.core.errors import PermanentError, TransientError
from app.core.logging import get_logger
from app.providers.base import SubjectFocal, SubjectFocalRequest, VisionConstraintProvider
from app.repositories.llm_call_repository import LlmCallRepository

logger = get_logger(__name__)

_AGENT_NAME = "subject_focal"
# v1: name the subject -> describe its position in words -> emit numbers.
_PROMPT_VERSION = "v1"


async def locate_subject_focal(
    *,
    provider: VisionConstraintProvider | None,
    llm_call_repo: LlmCallRepository,
    project_id: uuid.UUID,
    image: bytes,
    image_content_type: str,
    shot_id: str | None = None,
) -> tuple[float, float] | None:
    """`(focal_x, focal_y)` in 0..1, or `None` when no usable answer.

    `None` on: no provider (DRY_RUN / fakes), a transient or permanent
    provider error, a refusal, or a response that fails `SubjectFocal`'s
    own validation (which has no defaults, so an unanswered question
    lands here rather than becoming a centre).
    """
    if provider is None:
        return None

    locate = getattr(provider, "locate_subject", None)
    if locate is None:
        # A vision provider from before this call existed (or a fake that
        # only implements the gate). Not an error — just no focal.
        logger.info(
            "focal.provider_cannot_locate",
            extra={"shot_id": shot_id, "provider": getattr(provider, "name", "?")},
        )
        return None

    try:
        completion = await locate(
            SubjectFocalRequest(image=image, image_content_type=image_content_type)
        )
    except (TransientError, PermanentError) as exc:
        logger.warning(
            "focal.locate_failed",
            extra={"shot_id": shot_id, "error": str(exc)[:300]},
        )
        return None

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

    parsed = completion.parsed
    if not isinstance(parsed, SubjectFocal):
        logger.warning("focal.unexpected_verdict_type", extra={"shot_id": shot_id})
        return None

    logger.info(
        "focal.located",
        extra={
            "shot_id": shot_id,
            "subject": parsed.subject[:80],
            "where": parsed.subject_location_words[:80],
            "focal_x": parsed.focal_x,
            "focal_y": parsed.focal_y,
        },
    )
    return (parsed.focal_x, parsed.focal_y)
