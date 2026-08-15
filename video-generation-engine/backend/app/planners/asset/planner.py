"""Asset Planner agent (M5, fourth and final link in the chain). Fills
`asset_plan` for every shot - one LLM call per scene (batching that
scene's shots), so the reuse-before-generate ladder ordering stays scoped
to a reviewable number of shots per call. See
app/prompts/asset_planner/v1.md for the prompt specification.

Same scope boundary as the Shot Planner: a crash mid-loop re-plans every
scene on retry, since `GenerateTimelineStep` only checkpoints once per
planner stage.
"""

import uuid

from app.planners.asset.schemas import AssetPlannerOutput, AssetPlanShotOutput
from app.planners.repair import run_structured_with_repair
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import ASSET_LADDER, AssetPlan, AssetStrategy, Scene


def _build_user_content(scene: Scene) -> str:
    shot_lines = "\n".join(
        f"- shot_id={s.id} | intent={s.intent.value} | framing={s.framing.value} | prompt={s.prompt}"
        for s in scene.shots
    )
    return (
        f"Scene: {scene.title} (historical/visual context already set by the Director)\n"
        f"Shots in this scene, in order:\n{shot_lines}\n\n"
        "Produce exactly one asset_plan per shot_id listed above, in the same order."
    )


def _make_validator(scene: Scene):
    expected_ids = [s.id for s in scene.shots]

    def _validate(output: AssetPlannerOutput) -> list[str]:
        violations: list[str] = []
        plans = output.asset_plans

        got_ids = [p.shot_id for p in plans]
        if got_ids != expected_ids:
            violations.append(
                f"asset_plans must cover exactly these shot_ids, in this order: {expected_ids} "
                f"(got {got_ids})"
            )

        for p in plans:
            if p.shot_id not in expected_ids:
                continue
            for sq in p.search_queries:
                # Real archive search engines (Wikimedia Commons, stock
                # APIs) match short, title-like keyword phrases - a
                # natural-language sentence reliably returns zero results
                # even when it accurately describes real, findable
                # archival material (verified empirically: a 9-word
                # descriptive phrase found nothing on Commons for a
                # subject that a 2-word keyword query found instantly).
                if len(sq.split()) > 6:
                    violations.append(
                        f"shot {p.shot_id}: search query {sq!r} is too long "
                        f"({len(sq.split())} words) - search queries must be short "
                        "keyword phrases (max 6 words), not descriptive sentences"
                    )
            if not p.fallback_chain:
                violations.append(f"shot {p.shot_id}: fallback_chain must not be empty")
                continue
            if p.fallback_chain[0] != p.strategy:
                violations.append(
                    f"shot {p.shot_id}: fallback_chain must start with strategy {p.strategy.value}"
                )
            indices = [ASSET_LADDER.index(step) for step in p.fallback_chain]
            if indices != sorted(indices):
                violations.append(
                    f"shot {p.shot_id}: fallback_chain must follow the canonical ladder order: "
                    f"{[s.value for s in ASSET_LADDER]}"
                )
            if p.fallback_chain[-1] != AssetStrategy.GENERATE_IMAGE:
                violations.append(f"shot {p.shot_id}: fallback_chain must end in generate_image")
            if not p.search_queries:
                violations.append(f"shot {p.shot_id}: search_queries must not be empty")
            if not p.licence_requirements:
                violations.append(f"shot {p.shot_id}: licence_requirements must not be empty")

        return violations

    return _validate


def _to_domain(p: AssetPlanShotOutput) -> AssetPlan:
    return AssetPlan(
        entity=p.entity,
        strategy=p.strategy,
        search_queries=p.search_queries,
        preferred_type=p.preferred_type,
        fallback_chain=p.fallback_chain,
        licence_requirements=p.licence_requirements,
    )


class AssetPlanner:
    name = "asset_planner"
    _PROMPT_VERSION = "v1"

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(self, *, project_id: str, scenes: list[Scene]) -> list[Scene]:
        system_prompt = load_prompt(self.name, self._PROMPT_VERSION)
        planned_scenes: list[Scene] = []

        for scene in scenes:
            output = await run_structured_with_repair(
                provider=self._provider,
                llm_call_repo=self._llm_call_repo,
                project_id=uuid.UUID(project_id),
                agent=self.name,
                prompt_version=self._PROMPT_VERSION,
                system_prompt=system_prompt,
                user_content=_build_user_content(scene),
                response_model=AssetPlannerOutput,
                validate=_make_validator(scene),
            )
            plans_by_id = {p.shot_id: _to_domain(p) for p in output.asset_plans}
            new_shots = [
                shot.model_copy(update={"asset_plan": plans_by_id[shot.id]}) for shot in scene.shots
            ]
            planned_scenes.append(scene.model_copy(update={"shots": new_shots}))

        return planned_scenes
