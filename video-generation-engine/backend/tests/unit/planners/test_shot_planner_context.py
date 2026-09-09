"""long_form_direction.md A6 (2026-08-31): act + canvas context threaded
into `_build_user_content` (`app/planners/shot/planner.py`). A5
(2026-08-31) later DECOUPLED the two families - see the update below.

A6 originally gated both context families together on whether the SCENE
has a resolvable act (`act` is not `None`): Path A projects (<=70
fragments) never stamp `Scene.act_id` (see that field's own docstring),
so they never reached the `act is not None` branch and their user
content stayed BYTE-IDENTICAL to what this function produced before A6.

A5's own §3 instruction is explicit that this pairing was the plan's
fault, not A6's, and that A5 "must decouple them": canvas resolution has
nothing to do with act presence (A5's vertical-pan gate needs the canvas
line on every project, not just Path B, since a SHORT 16:9
`documentary_archival` project is Path A too). So as of A5, canvas
context is emitted whenever a `RenderFormat` is resolved - unconditional
in practice, since `ShotPlanner.plan()` always resolves one - independent
of `act`. Path A's byte-identity property is deliberately broken by this:
its user content becomes "today's string plus exactly one canvas line",
still asserted exactly below (`test_path_a_scene_with_no_act_ignores_ordinal_and_opens_act_args`
and the plan()-level test after it). Act-only fields (`act`, ordinal,
opens-act) are unaffected and still gate on `act is not None` alone.

No prompt wording changed for A6 itself; A5 is the first slice whose
prompt (`app/prompts/shot_planner/v1.md`) actually reads this canvas
line.

The first group of tests below calls `_build_user_content` directly -
pure, no DB, no LLM, matching the plan's own "unit tests on
`_build_user_content`" acceptance line. The last group goes through
`ShotPlanner.plan()` with a `FakePlanningProvider` (same shape as
`test_shot_planner.py`) to prove the new `acts`/`frame_aspect` params
actually get threaded from the real entry point into that function -
own file per `test_shot_planner_glitch_cap.py`'s convention of keeping
DB-touching async tests separate from pure ones.
"""

import pytest_asyncio

from app.db.session import async_session_factory
from app.planners.fragments import split_narration_fragments
from app.planners.shot.planner import ShotPlanner, _build_user_content
from app.planners.shot.schemas import (
    ShotCameraOutput,
    ShotPlannerOutput,
    ShotPlanOutput,
    ShotTransitionOutput,
)
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    Act,
    CameraDirection,
    CameraMovement,
    CreativeContext,
    Framing,
    RevealDirection,
    Scene,
    ShotIntent,
    TransitionType,
)
from app.script.styles import RenderFormat

from .helpers import FakePlanningProvider

# 2 sentences -> 2 fragments, verified directly against the real splitter
# (see this module's docstring's sibling in test_shot_planner.py for why
# that verification matters here rather than being assumed).
NARRATION = "Germany possessed abundant coal. It fueled every furnace in the Ruhr."

_CTX = CreativeContext(
    historical_period="1930s Germany",
    visual_style="archival monochrome",
    camera_language="static and slow push, no whip pans",
)


def _scene(scene_id: str = "sc_01", order: int = 0, act_id: str | None = None) -> Scene:
    return Scene(
        id=scene_id,
        order=order,
        title="Coal wealth",
        narrative_purpose="establish the resource",
        emotion="wonder",
        narration_text=NARRATION,
        duration_s=4.0,
        act_id=act_id,
    )


# ---------------------------------------------------------------------------
# Pure tests: _build_user_content called directly, no DB, no LLM.
# ---------------------------------------------------------------------------


def _base_expected(scene: Scene, *, camera_line: str) -> str:
    """Reassembles the pre-A6 literal output by hand, from the same
    pieces `_build_user_content` used before this slice - the "exact
    expected string, not an approximation" the task asks for."""
    fragments = split_narration_fragments(scene.narration_text)
    numbered = "\n".join(f"{f.index}. {f.text}" for f in fragments)
    return (
        f"Scene: {scene.title}\n"
        f"Narrative purpose: {scene.narrative_purpose}\n"
        f"Emotion: {scene.emotion}\n"
        f"Target scene duration_s: {scene.duration_s}\n"
        f"This scene's narration, split into {len(fragments)} numbered fragments:\n"
        f"{numbered}\n\n"
        f"Assign each shot a CONTIGUOUS RANGE of these fragment numbers via "
        f"`fragment_start`/`fragment_end` (both inclusive) - never a character offset, "
        f"and never split a single fragment between two shots. Every fragment from 1 to "
        f"{len(fragments)} must be covered, in order, by exactly one shot. This scene can "
        f"therefore have AT MOST {len(fragments)} shot(s).\n\n"
        "Director's creative context:\n"
        f"- historical_period: {_CTX.historical_period}\n"
        f"- visual_style: {_CTX.visual_style}\n"
        f"{camera_line}"
    )


def test_path_a_scene_user_content_is_byte_identical_to_pre_a6_output():
    """The exact scenario the plan's A6 'Ends in' line names: a Path A
    scene (no act_id, so `act` is never resolved) must produce user
    content with NOT ONE extra byte versus before this slice - no act
    lines, no canvas line, nothing."""
    scene = _scene(act_id=None)
    fragments = split_narration_fragments(scene.narration_text)

    actual = _build_user_content(scene, _CTX, fragments, suppress_camera_language=False)

    expected = _base_expected(scene, camera_line=f"- camera_language: {_CTX.camera_language}\n")
    assert actual == expected
    assert "Long-form context" not in actual
    assert "act:" not in actual
    assert "canvas:" not in actual


def test_path_a_scene_with_no_act_gets_exactly_one_canvas_line_but_ignores_ordinal_and_opens_act():
    """A5 (long_form_direction.md §3) DECOUPLES canvas from act presence
    on purpose - see this file's module docstring. A Path A scene
    (`act=None`) now DOES receive a canvas line whenever `render_format`
    is resolved: "today's string plus exactly one canvas line", still
    asserted exactly below, per A5's own instruction to update this A6
    byte-identity test rather than delete it. `act_ordinal`/`opens_act`
    remain act-only and are still ignored when `act` is `None` - only
    `render_format` was decoupled from the gate."""
    scene = _scene(act_id=None)
    fragments = split_narration_fragments(scene.narration_text)

    actual = _build_user_content(
        scene,
        _CTX,
        fragments,
        suppress_camera_language=False,
        act=None,
        act_ordinal=(2, 5),
        opens_act=True,
        render_format=RenderFormat(width=1280, height=720),
    )

    expected = (
        _base_expected(scene, camera_line=f"- camera_language: {_CTX.camera_language}\n")
        + "\n"
        + "Long-form context:\n"
        + "- canvas: 1280x720 (16:9)\n"
    )
    assert actual == expected
    assert "act:" not in actual
    assert "act position" not in actual
    assert "opens this act" not in actual


def test_path_b_scene_that_opens_an_act_gets_act_and_canvas_context():
    scene = _scene(scene_id="act_02_sc_01", order=3, act_id="act_02")
    fragments = split_narration_fragments(scene.narration_text)
    act = Act(id="act_02", order=1, title="Oil")

    actual = _build_user_content(
        scene,
        _CTX,
        fragments,
        suppress_camera_language=False,
        act=act,
        act_ordinal=(2, 5),
        opens_act=True,
        render_format=RenderFormat(width=1280, height=720),
    )

    base = _base_expected(scene, camera_line=f"- camera_language: {_CTX.camera_language}\n")
    expected = (
        base
        + "\n"
        + "Long-form context:\n"
        + "- act: Oil\n"
        + "- act position: act 2 of 5\n"
        + "- opens this act: yes\n"
        + "- canvas: 1280x720 (16:9)\n"
    )
    assert actual == expected


def test_path_b_scene_mid_act_has_act_context_but_opens_act_is_false():
    scene = _scene(scene_id="act_02_sc_02", order=4, act_id="act_02")
    fragments = split_narration_fragments(scene.narration_text)
    act = Act(id="act_02", order=1, title="Oil")

    actual = _build_user_content(
        scene,
        _CTX,
        fragments,
        suppress_camera_language=False,
        act=act,
        act_ordinal=(2, 5),
        opens_act=False,
        render_format=RenderFormat(width=1280, height=720),
    )

    assert "- act: Oil\n" in actual
    assert "- act position: act 2 of 5\n" in actual
    assert "- opens this act: no\n" in actual
    assert "- opens this act: yes\n" not in actual


def test_landscape_canvas_line_reports_1280x720_16_9():
    scene = _scene(scene_id="act_01_sc_01", order=0, act_id="act_01")
    fragments = split_narration_fragments(scene.narration_text)
    act = Act(id="act_01", order=0, title="Coal")

    actual = _build_user_content(
        scene,
        _CTX,
        fragments,
        act=act,
        act_ordinal=(1, 3),
        opens_act=True,
        render_format=RenderFormat(width=1280, height=720),
    )
    assert "- canvas: 1280x720 (16:9)\n" in actual


def test_portrait_canvas_line_reports_720x1280_9_16():
    scene = _scene(scene_id="act_01_sc_01", order=0, act_id="act_01")
    fragments = split_narration_fragments(scene.narration_text)
    act = Act(id="act_01", order=0, title="Coal")

    actual = _build_user_content(
        scene,
        _CTX,
        fragments,
        act=act,
        act_ordinal=(1, 3),
        opens_act=True,
        render_format=RenderFormat(width=720, height=1280),
    )
    assert "- canvas: 720x1280 (9:16)\n" in actual


def test_suppress_camera_language_still_omits_camera_line_with_act_context_present():
    """Q6's suppression must still work exactly as before, independent
    of whether act/canvas context is also present."""
    scene = _scene(scene_id="act_01_sc_01", order=0, act_id="act_01")
    fragments = split_narration_fragments(scene.narration_text)
    act = Act(id="act_01", order=0, title="Coal")

    actual = _build_user_content(
        scene,
        _CTX,
        fragments,
        suppress_camera_language=True,
        act=act,
        act_ordinal=(1, 3),
        opens_act=True,
        render_format=RenderFormat(width=1280, height=720),
    )
    assert "camera_language:" not in actual
    assert _CTX.camera_language not in actual
    # act/canvas context is unaffected by camera suppression
    assert "- act: Coal\n" in actual
    assert "- canvas: 1280x720 (16:9)\n" in actual


def test_suppress_camera_language_false_still_shows_camera_line_with_act_context_present():
    scene = _scene(scene_id="act_01_sc_01", order=0, act_id="act_01")
    fragments = split_narration_fragments(scene.narration_text)
    act = Act(id="act_01", order=0, title="Coal")

    actual = _build_user_content(
        scene,
        _CTX,
        fragments,
        suppress_camera_language=False,
        act=act,
        act_ordinal=(1, 3),
        opens_act=True,
        render_format=RenderFormat(width=1280, height=720),
    )
    assert f"- camera_language: {_CTX.camera_language}\n" in actual
    assert "- act: Coal\n" in actual


# ---------------------------------------------------------------------------
# Wiring tests: through the real ShotPlanner.plan() entry point, proving
# the new `acts`/`frame_aspect` params reach _build_user_content the way
# generate_timeline.py's real call site now threads them.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("shot-planner-test")
        return project.id


def _shot_output(
    shot_id: str, order: int, fragment_start: int, fragment_end: int
) -> ShotPlanOutput:
    return ShotPlanOutput(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        intent_text="text",
        fragment_start=fragment_start,
        fragment_end=fragment_end,
        duration_s=2.0,
        framing=Framing.WIDE,
        camera=ShotCameraOutput(
            movement=CameraMovement.STATIC, direction=CameraDirection.NONE, intensity=0.0
        ),
        transition_out=ShotTransitionOutput(type=TransitionType.CUT, duration_s=0.0),
        prompt="archival photograph",
        secondary_prompt="",
        text_card="",
        sfx_cue="",
        picture_is_graphic=False,
        layers=[],
        reveal_direction=RevealDirection.NONE,
        reveal_start_fragment=0,
        reveal_end_fragment=0,
    )


def _valid_output() -> ShotPlannerOutput:
    return ShotPlannerOutput(
        shots=[
            _shot_output("sh_01", 0, 1, 1),
            _shot_output("sh_02", 1, 2, 2),
        ]
    )


async def test_plan_gives_a_path_a_project_a_canvas_line_but_no_act_context(project_id):
    """A5 (long_form_direction.md §3): `plan()` now resolves
    `render_format` UNCONDITIONALLY (not only when a scene has an act -
    A6's original gate), so even a Path A project (no `acts` passed - the
    real Path A call shape, `timeline.acts` is `[]` there) receives
    exactly one canvas line. This is the plan's own accepted, one-time
    byte-identity break affecting all 19 shipped shorts (A5's own §7 log
    entry has the trade). Act context ('- act:', ordinal, opens-act) is
    still absent - only canvas was decoupled from the gate.

    `render_style="documentary_archival"` was chosen when this test was
    written (A6) because that style had no fragment yet, so
    `suppress_camera_language` was `False`. A4 (long_form_direction.md
    §3) gave `documentary_archival` its own fragment
    (`app/prompts/shot_planner_styles/documentary_archival.md`), so
    `suppress_camera_language` is now `True` for this style too (Q6:
    `suppress_camera_language=style_fragment is not None` in
    `ShotPlanner.plan`) - updated to match, the same way A1 changed this
    for `stillness` elsewhere."""
    scene = _scene(act_id=None)
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        planner = ShotPlanner(provider, LlmCallRepository(session))
        await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=_CTX,
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
            max_parallax_layers_per_project=100,
            render_style="documentary_archival",
        )
    user = provider.calls[0]["user_content"]
    fragments = split_narration_fragments(scene.narration_text)
    expected = _build_user_content(
        scene,
        _CTX,
        fragments,
        suppress_camera_language=True,
        render_format=RenderFormat(width=1280, height=720),
    )
    assert user == expected
    assert "- canvas: 1280x720 (16:9)\n" in user
    assert "- act:" not in user
    assert "act position" not in user
    assert "opens this act" not in user


async def test_plan_threads_acts_and_frame_aspect_into_act_opening_scene(project_id):
    scene_open = _scene(scene_id="act_02_sc_01", order=0, act_id="act_02")
    acts = [
        Act(id="act_01", order=0, title="Coal"),
        Act(id="act_02", order=1, title="Oil"),
        Act(id="act_03", order=2, title="War"),
    ]
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        planner = ShotPlanner(provider, LlmCallRepository(session))
        await planner.plan(
            project_id=project_id,
            scenes=[scene_open],
            creative_context=_CTX,
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
            max_parallax_layers_per_project=100,
            render_style="documentary_archival",
            acts=acts,
            frame_aspect=None,
        )
    user = provider.calls[0]["user_content"]
    assert "- act: Oil\n" in user
    assert "- act position: act 2 of 3\n" in user
    assert "- opens this act: yes\n" in user
    assert "- canvas: 1280x720 (16:9)\n" in user


async def test_plan_marks_a_second_scene_in_the_same_act_as_not_opening_it(project_id):
    scene_open = _scene(scene_id="act_02_sc_01", order=0, act_id="act_02")
    scene_mid = _scene(scene_id="act_02_sc_02", order=1, act_id="act_02")
    acts = [
        Act(id="act_01", order=0, title="Coal"),
        Act(id="act_02", order=1, title="Oil"),
        Act(id="act_03", order=2, title="War"),
    ]
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output(), _valid_output()])
        planner = ShotPlanner(provider, LlmCallRepository(session))
        await planner.plan(
            project_id=project_id,
            scenes=[scene_open, scene_mid],
            creative_context=_CTX,
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
            max_parallax_layers_per_project=100,
            render_style="documentary_archival",
            acts=acts,
            frame_aspect=None,
        )
    # Both scenes reuse the same fixture title/narration, so distinguish
    # by which call saw "opens this act: yes" vs "no" - order of dispatch
    # is not guaranteed by bounded_gather, so check the SET of opens-flags
    # seen across the two calls, not position.
    opens_flags = {"- opens this act: yes\n" in c["user_content"] for c in provider.calls}
    assert opens_flags == {True, False}
    for c in provider.calls:
        assert "- act: Oil\n" in c["user_content"]
        assert "- act position: act 2 of 3\n" in c["user_content"]


async def test_plan_uses_stillness_portrait_reel_canvas_when_frame_aspect_is_9_16(project_id):
    scene_open = _scene(scene_id="act_01_sc_01", order=0, act_id="act_01")
    acts = [Act(id="act_01", order=0, title="Coal")]
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output()])
        planner = ShotPlanner(provider, LlmCallRepository(session))
        await planner.plan(
            project_id=project_id,
            scenes=[scene_open],
            creative_context=_CTX,
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
            max_parallax_layers_per_project=100,
            render_style="stillness",
            acts=acts,
            frame_aspect="9:16",
        )
    user = provider.calls[0]["user_content"]
    assert "- canvas: 720x1280 (9:16)\n" in user
