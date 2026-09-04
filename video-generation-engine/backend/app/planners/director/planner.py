"""Director agent (M5, first link in the Director -> Scene Planner ->
Shot Planner -> Asset Planner chain). Sets creative_context and
music_plan for the whole project - nothing else. See
app/prompts/director/v1.md for the prompt specification."""

import uuid

from app.planners.director.schemas import DirectorOutput
from app.planners.repair import run_structured_with_repair
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import CreativeContext, MusicPlan
from app.script.styles import PicturePath, resolve_picture_path

AGENT = "director"
PROMPT_VERSION = "v1"
# illustrated_faceless.md P-IF-F1-review3: NOT a style-name fragment (that
# would need duplicating for every future generation-only world, exactly
# the duplication P-IF-F1-review removed one level down). Keyed on
# `resolve_picture_path` - the same one resolver every other call site
# reads through (§3.2) - so one block covers `illustrated_risograph`
# today and any later generation-only style for free.
_GENERATION_ONLY_PROMPT_VERSION = "generation_only"


def _system_prompt_for(render_style: str | None) -> str:
    """The base Director prompt, plus the generation-only override block
    when (and only when) `render_style` resolves to `PicturePath.
    GENERATION_ONLY` (illustrated_faceless.md P-IF-F1-review3). Pulled out
    as its own pure function - no provider, no DB, no repair loop - so the
    composition itself is directly testable, the same way `load_style_
    fragment` is tested at the loader level for the Shot Planner (`tests/
    unit/planners/test_illustrated_risograph_fragment.py`).

    `render_style=None` (every caller before this fix, and the four
    retrieval styles) must return `load_prompt(AGENT, PROMPT_VERSION)`
    completely unchanged - that byte-identity is the regression this fix
    must not risk."""
    system_prompt = load_prompt(AGENT, PROMPT_VERSION)
    if resolve_picture_path(render_style) is PicturePath.GENERATION_ONLY:
        system_prompt = f"{system_prompt}\n\n{load_prompt(AGENT, _GENERATION_ONLY_PROMPT_VERSION)}"
    return system_prompt


def _validate(output: DirectorOutput) -> list[str]:
    violations: list[str] = []
    ctx = output.creative_context
    for field_name in ("tone", "visual_style", "historical_period", "audience", "camera_language"):
        if not getattr(ctx, field_name).strip():
            violations.append(f"creative_context.{field_name} must not be empty")
    # Q6: `colour_palette` is not collected. The grade is `STYLE_GRADES`
    # keyed on the style name; a Director-written palette was never read.

    plan = output.music_plan
    if not plan.mood.strip():
        violations.append("music_plan.mood must not be empty")
    if not plan.tempo.strip():
        violations.append("music_plan.tempo must not be empty")
    if not plan.search_terms:
        violations.append("music_plan.search_terms must not be empty")

    return violations


class DirectorPlanner:
    name = AGENT

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(
        self, *, project_id: str, script: str, render_style: str | None = None
    ) -> tuple[CreativeContext, MusicPlan]:
        # illustrated_faceless.md P-IF-F1-review3, the same defect
        # P-IF-F1-review2 fixed in script_suitability: the base prompt's
        # "Documentary default" and its provenance-flavoured constraints
        # ("licensed footage", "consent is documented") are wrong for a
        # style that never retrieves anything - and those constraints do
        # not stop at planning, they are later checked by a vision model
        # against every generated image (`check_generated_image_
        # constraints`), where they are inapplicable at best and inverted
        # at worst, and a rejection is still billed regardless. See
        # `_system_prompt_for` for the composition itself.
        system_prompt = _system_prompt_for(render_style)
        output = await run_structured_with_repair(
            provider=self._provider,
            llm_call_repo=self._llm_call_repo,
            project_id=uuid.UUID(project_id),
            agent=AGENT,
            prompt_version=PROMPT_VERSION,
            system_prompt=system_prompt,
            user_content=f"Script:\n\n{script}",
            response_model=DirectorOutput,
            validate=_validate,
        )
        creative_context = CreativeContext(**output.creative_context.model_dump())
        music_plan = MusicPlan(**output.music_plan.model_dump())
        return creative_context, music_plan
