"""Asset Planner agent (M5, fourth and final link in the chain). Fills
`asset_plan` for every shot - one LLM call per scene (batching that
scene's shots), so the reuse-before-generate ladder ordering stays scoped
to a reviewable number of shots per call. See
app/prompts/asset_planner/v1.md for the prompt specification.

Same scope boundary as the Shot Planner: a crash mid-loop re-plans every
scene on retry, since `GenerateTimelineStep` only checkpoints once per
planner stage.
"""

import asyncio
import uuid

from app.core.logging import get_logger
from app.planners.asset.schemas import AssetPlannerOutput, AssetPlanShotOutput
from app.planners.repair import run_structured_with_repair
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import (
    ASSET_LADDER,
    AssetPlan,
    AssetStrategy,
    CameraMovement,
    PreferredMediaType,
    Scene,
)
from app.utils.bounded_gather import bounded_gather, planner_concurrency

logger = get_logger(__name__)


def _build_user_content(scene: Scene) -> str:
    # `camera` is included because the prompt's own `preferred_type` rule
    # (app/prompts/asset_planner/v1.md) explicitly says to judge by "the
    # shot's camera movement" - before this fix that field was never sent
    # here at all, even though the Shot Planner (which sets it) always
    # runs before the Asset Planner, so the data existed and simply
    # wasn't passed along. Found 2026-08-18 while checking whether
    # `render_style` influences this decision (it doesn't - the real gap
    # was one level down, in what the Asset Planner could even see).
    shot_lines = "\n".join(
        f"- shot_id={s.id} | intent={s.intent.value} | framing={s.framing.value} | "
        f"camera={s.camera.movement.value} | prompt={s.prompt}"
        + (f" | secondary_prompt={s.secondary_prompt}" if s.secondary_prompt.strip() else "")
        for s in scene.shots
    )
    return (
        f"Scene: {scene.title} (historical/visual context already set by the Director)\n"
        f"Shots in this scene, in order:\n{shot_lines}\n\n"
        "Produce exactly one asset_plan per shot_id listed above, in the same order. "
        "For every split_frame shot, also produce one secondary_asset_plans entry "
        "with the same shot_id covering the BOTTOM panel (`secondary_prompt`). "
        "secondary_asset_plans is empty when this scene has no split_frame shot. "
        "Split-screen panels are stills (`preferred_type=image`); never video."
    )


def _plan_field_violations(p: AssetPlanShotOutput, *, label: str) -> list[str]:
    violations: list[str] = []
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
                f"{label}: search query {sq!r} is too long "
                f"({len(sq.split())} words) - search queries must be short "
                "keyword phrases (max 6 words), not descriptive sentences"
            )
    if not p.fallback_chain:
        violations.append(f"{label}: fallback_chain must not be empty")
        return violations
    if p.fallback_chain[0] != p.strategy:
        violations.append(f"{label}: fallback_chain must start with strategy {p.strategy.value}")
    indices = [ASSET_LADDER.index(step) for step in p.fallback_chain]
    if indices != sorted(indices):
        violations.append(
            f"{label}: fallback_chain must follow the canonical ladder order: "
            f"{[s.value for s in ASSET_LADDER]}"
        )
    if p.fallback_chain[-1] != AssetStrategy.GENERATE_IMAGE:
        violations.append(f"{label}: fallback_chain must end in generate_image")
    if not p.search_queries:
        violations.append(f"{label}: search_queries must not be empty")
    if not p.licence_requirements:
        violations.append(f"{label}: licence_requirements must not be empty")
    return violations


def _make_validator(scene: Scene):
    expected_ids = [s.id for s in scene.shots]
    split_ids = [s.id for s in scene.shots if s.camera.movement == CameraMovement.SPLIT_FRAME]

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
            violations.extend(_plan_field_violations(p, label=f"shot {p.shot_id}"))
            if p.shot_id in split_ids and p.preferred_type != PreferredMediaType.IMAGE:
                violations.append(
                    f"shot {p.shot_id}: split_frame panels must be image, not "
                    f"{p.preferred_type.value}"
                )

        secondary = output.secondary_asset_plans
        secondary_ids = [p.shot_id for p in secondary]
        if sorted(secondary_ids) != sorted(split_ids):
            violations.append(
                f"secondary_asset_plans must cover exactly the split_frame shot_ids "
                f"{split_ids} (got {secondary_ids})"
            )
        if len(secondary_ids) != len(set(secondary_ids)):
            violations.append("secondary_asset_plans shot_ids must be unique")
        for p in secondary:
            violations.extend(_plan_field_violations(p, label=f"shot {p.shot_id} secondary"))
            if p.preferred_type != PreferredMediaType.IMAGE:
                violations.append(
                    f"shot {p.shot_id} secondary: split_frame panels must be image, not "
                    f"{p.preferred_type.value}"
                )

        return violations

    return _validate


def _downgrade_to_image(plan: AssetPlan) -> AssetPlan:
    """Demote an over-cap video plan to image, keeping `strategy` and
    `fallback_chain` consistent with `preferred_type` - both feed
    `estimate_project_cost_cents` (app/assets/cost.py) independently of
    `preferred_type`, so leaving `strategy=GENERATE_VIDEO` on a plan
    whose `preferred_type` now says image would overstate the estimate."""
    strategy = (
        AssetStrategy.GENERATE_IMAGE
        if plan.strategy == AssetStrategy.GENERATE_VIDEO
        else plan.strategy
    )
    fallback_chain = [s for s in plan.fallback_chain if s != AssetStrategy.GENERATE_VIDEO]
    return plan.model_copy(
        update={
            "preferred_type": PreferredMediaType.IMAGE,
            "strategy": strategy,
            "fallback_chain": fallback_chain,
        }
    )


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

    async def plan(
        self, *, project_id: str, scenes: list[Scene], max_video_shots_per_project: int
    ) -> list[Scene]:
        system_prompt = load_prompt(self.name, self._PROMPT_VERSION)
        db_lock = asyncio.Lock()

        async def _one_scene(scene: Scene) -> Scene:
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
                db_lock=db_lock,
            )
            plans_by_id = {p.shot_id: _to_domain(p) for p in output.asset_plans}
            secondary_by_id = {p.shot_id: _to_domain(p) for p in output.secondary_asset_plans}
            new_shots = [
                shot.model_copy(
                    update={
                        "asset_plan": plans_by_id[shot.id],
                        "secondary_asset_plan": secondary_by_id.get(shot.id),
                    }
                )
                for shot in scene.shots
            ]
            return scene.model_copy(update={"shots": new_shots})

        gathered = await bounded_gather(scenes, _one_scene, concurrency=planner_concurrency())
        planned_scenes: list[Scene] = []
        for item in gathered:
            if isinstance(item, Exception):
                raise item
            planned_scenes.append(item)
        # Cap AFTER gather — same race as the shot cap (Track C §2.4). Each
        # scene is planned blind to every other scene's choices, so the
        # project-wide video count can only be known once every scene is
        # back. Rather than fail the whole run over it (the original A4
        # behaviour - the model was never asked to reduce its own count,
        # so failing just stopped the run before more got planned), the
        # excess is downgraded to image here, in scene/shot order, keeping
        # only the first `max_video_shots_per_project` video shots.
        video_shot_count = sum(
            1
            for scene in planned_scenes
            for shot in scene.shots
            if shot.asset_plan is not None
            and shot.asset_plan.preferred_type == PreferredMediaType.VIDEO
        )
        if video_shot_count > max_video_shots_per_project:
            logger.warning(
                "asset_planner.video_cap_exceeded_downgrading",
                extra={
                    "project_id": project_id,
                    "cap": max_video_shots_per_project,
                    "planned": video_shot_count,
                },
            )
            seen = 0
            downgraded_scenes: list[Scene] = []
            for scene in planned_scenes:
                new_shots = []
                for shot in scene.shots:
                    plan = shot.asset_plan
                    if plan is not None and plan.preferred_type == PreferredMediaType.VIDEO:
                        seen += 1
                        if seen > max_video_shots_per_project:
                            shot = shot.model_copy(
                                update={"asset_plan": _downgrade_to_image(plan)}
                            )
                    new_shots.append(shot)
                downgraded_scenes.append(scene.model_copy(update={"shots": new_shots}))
            planned_scenes = downgraded_scenes
        return planned_scenes
