"""Act Planner (Track C C1 Path B). Groups the full fragment list into
3–7 contiguous acts. Same tiling interface as the Scene Planner, one
level coarser — 206 fragments into 5 acts, not 65 scenes."""

import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.planners.act.schemas import ActPlannerOutput, ActPlanOutput
from app.planners.fragments import NarrationFragment, split_narration_fragments
from app.planners.repair import run_structured_with_repair
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import CreativeContext

AGENT = "act_planner"
PROMPT_VERSION = "v1"
_LARGE_FRAGMENT_SNAP_THRESHOLD = 1

logger = get_logger(__name__)


def _snap_fragment_boundaries(acts: list[ActPlanOutput], fragment_count: int) -> None:
    if not acts:
        return
    first = acts[0]
    if first.fragment_start != 1:
        first.fragment_start = 1
    last = acts[-1]
    if last.fragment_end != fragment_count:
        last.fragment_end = fragment_count


def _build_user_content(
    fragments: list[NarrationFragment],
    creative_context: CreativeContext,
    *,
    min_acts: int,
    max_acts: int,
) -> str:
    numbered = "\n".join(f"{f.index}. {f.text}" for f in fragments)
    return (
        f"Script, split into {len(fragments)} numbered fragments:\n"
        f"{numbered}\n\n"
        f"Assign each act a CONTIGUOUS RANGE of these fragment numbers via "
        f"`fragment_start`/`fragment_end` (both inclusive). Every fragment from 1 to "
        f"{len(fragments)} must be covered, in order, by exactly one act.\n\n"
        "Director's creative context:\n"
        f"- tone: {creative_context.tone}\n"
        f"- visual_style: {creative_context.visual_style}\n"
        f"- historical_period: {creative_context.historical_period}\n"
        f"- audience: {creative_context.audience}\n\n"
        f"Constraints: produce between {min_acts} and {max_acts} acts (inclusive)."
    )


def _make_validator(fragments: list[NarrationFragment], *, min_acts: int, max_acts: int):
    fragment_count = len(fragments)

    def _validate(output: ActPlannerOutput) -> list[str]:
        violations: list[str] = []
        acts = output.acts
        if not acts:
            violations.append("acts must not be empty")
            return violations
        if not (min_acts <= len(acts) <= max_acts):
            violations.append(
                f"{len(acts)} acts is outside the allowed range [{min_acts}, {max_acts}]"
            )
        ids = [a.id for a in acts]
        if len(ids) != len(set(ids)):
            violations.append("act ids must be unique")
        expected_order = list(range(len(acts)))
        if [a.order for a in acts] != expected_order:
            violations.append(f"act order fields must be exactly {expected_order}, in list order")

        _snap_fragment_boundaries(acts, fragment_count)
        cursor = 1
        for a in acts:
            if a.fragment_start != cursor:
                violations.append(
                    f"act {a.id} fragment_start ({a.fragment_start}) must equal {cursor}"
                )
            if a.fragment_end < a.fragment_start:
                violations.append(f"act {a.id} fragment_end must be >= fragment_start")
            if a.fragment_end > fragment_count:
                violations.append(f"act {a.id} fragment_end exceeds fragment count {fragment_count}")
            cursor = a.fragment_end + 1
        if cursor != fragment_count + 1:
            violations.append(
                f"the last act's fragment_end must equal the script's fragment count "
                f"({fragment_count})"
            )
        return violations

    return _validate


class Act:
    """In-memory act: id, title, and the script slice it owns."""

    def __init__(self, *, id: str, order: int, title: str, start: int, end: int, script_slice: str):
        self.id = id
        self.order = order
        self.title = title
        self.start = start
        self.end = end
        self.script_slice = script_slice


class ActPlanner:
    name = AGENT

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(
        self,
        *,
        project_id: str,
        script: str,
        creative_context: CreativeContext,
        min_acts: int | None = None,
        max_acts: int | None = None,
    ) -> list[Act]:
        min_acts = min_acts if min_acts is not None else settings.min_acts
        max_acts = max_acts if max_acts is not None else settings.max_acts
        fragments = split_narration_fragments(script)
        output = await run_structured_with_repair(
            provider=self._provider,
            llm_call_repo=self._llm_call_repo,
            project_id=uuid.UUID(project_id),
            agent=AGENT,
            prompt_version=PROMPT_VERSION,
            system_prompt=load_prompt(AGENT, PROMPT_VERSION),
            user_content=_build_user_content(
                fragments, creative_context, min_acts=min_acts, max_acts=max_acts
            ),
            response_model=ActPlannerOutput,
            validate=_make_validator(fragments, min_acts=min_acts, max_acts=max_acts),
        )
        acts: list[Act] = []
        for a in output.acts:
            start = fragments[a.fragment_start - 1].start
            end = fragments[a.fragment_end - 1].end
            acts.append(
                Act(
                    id=a.id,
                    order=a.order,
                    title=a.title,
                    start=start,
                    end=end,
                    script_slice=script[start:end],
                )
            )
        return acts
