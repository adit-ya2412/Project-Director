"""R3 (2026-08-16): the STRUCTURAL half of "render-only is incapable of
invoking a paid provider" - pure, no DB, no asyncio. `render_precondition_gap`
itself needs a real DB-backed `RunContext` (every step's `is_satisfied`
queries the database) and is proven separately in
`tests/integration/test_render_only.py`; what belongs here is the part
that never touches the database at all: what `RENDER_ONLY_STEPS`
actually CONTAINS, and that this list - not a runtime check - is what
`WorkflowEngine.run()` is limited to.
"""

from app.workflow.engine import DEFAULT_PIPELINE
from app.workflow.render_only import _NOT_A_PRECONDITION, RENDER_ONLY_STEPS
from app.workflow.steps.complete import CompleteStep
from app.workflow.steps.render import RenderStep


def test_render_only_steps_contains_only_render_and_complete():
    """The actual safety property R3 rests on: `WorkflowEngine.run()`
    only ever iterates `self._steps` (app/workflow/engine.py) - a list
    containing nothing but `RenderStep` and `CompleteStep` (which only
    ever flips `project.status`, see the constant's own comment) cannot,
    by construction, reach `GenerateTimelineStep`/`ResolveAssetsStep`/
    `SelectMusicStep`/`NarrationStep`, whatever a precondition check does
    or does not catch first."""
    assert len(RENDER_ONLY_STEPS) == 2
    assert isinstance(RENDER_ONLY_STEPS[0], RenderStep)
    assert isinstance(RENDER_ONLY_STEPS[1], CompleteStep)


def test_render_only_steps_is_not_the_default_pipelines_own_instance():
    """A fresh instance, not one borrowed from `DEFAULT_PIPELINE` - both
    are stateless, so this is a clarity guarantee (this list must never
    be read as "whatever the full pipeline happens to be doing today"),
    not a correctness requirement on `WorkflowStep` itself."""
    default_render_step = next(s for s in DEFAULT_PIPELINE if s.name == "render")
    assert RENDER_ONLY_STEPS[0] is not default_render_step


def test_romanize_captions_sits_between_select_sfx_and_narration():
    """caption_romanization.md §3.2 (b): own step, before Narration so
    the version it appends is overwritten by `produced_by=NARRATION`
    before anything renders."""
    names = [step.name for step in DEFAULT_PIPELINE]
    assert names.index("select_sfx") + 1 == names.index("romanize_captions")
    assert names.index("romanize_captions") + 1 == names.index("narration")


def test_every_paid_or_planning_step_is_excluded_from_the_precondition_check():
    """Every step in the real pipeline other than "render" itself and
    "complete" (which only marks a project COMPLETED after a render
    already happened) must be a precondition `render_precondition_gap`
    checks - if a new step were ever added to `DEFAULT_PIPELINE` without
    updating this set, this test catches it rather than silently letting
    the render-only endpoint skip checking it."""
    pipeline_step_names = {step.name for step in DEFAULT_PIPELINE}
    assert {"render", "complete"} == _NOT_A_PRECONDITION
    assert pipeline_step_names >= _NOT_A_PRECONDITION
    precondition_names = pipeline_step_names - _NOT_A_PRECONDITION
    # Every real pipeline step ahead of render (planning, both resolve_assets
    # passes, music selection, both human gates, narration) is a real
    # precondition - none of this pipeline's own stages are silently exempt.
    assert precondition_names == {
        "generate_timeline",
        "resolve_assets_search",
        "select_music",
        "select_sfx",
        "romanize_captions",
        "await_approval",
        "narration",
        "resolve_assets_generate",
        # A8 (long_form_direction.md, 2026-09-01). `render_precondition_gap`
        # already covers this automatically - it walks `DEFAULT_PIPELINE` and
        # skips only `_NOT_A_PRECONDITION`, so no production change was needed
        # when the step was added. It IS a real precondition: a project with
        # `sfx_cue` shots whose generation never ran would otherwise render
        # with the diegetic layer silently absent. This assertion is the
        # canary the docstring above describes, and it fired exactly as
        # designed - updating it is the acknowledgement, not a workaround.
        "generate_diegetic_sfx",
        "await_review",
    }
