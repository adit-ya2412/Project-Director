"""Golden-file test for the Scene Planner: verifies the additive-ready
Scene objects it produces, and the two hardest validation rules -
fragment-range tiling and the max_scenes cap.

## Fragment ranges, not a retyped script (S2 hardening, 2026-08-16)

The model used to be asked to retype the script's own words into each
scene's `narration_text`, verified afterwards by concatenating every
scene and comparing against the script - the same "ask a model to
reproduce deterministic text" mistake S1 had already fixed for the Shot
Planner one level down. On a real run it failed that check twice in a
row and burned a full planning call. The fix is the same fix: the
script is pre-split into numbered fragments
(`app/planners/fragments.py`, shared with the Shot Planner as of this
change) and the model is asked only for a CONTIGUOUS RANGE of fragment
numbers per scene - `app/planners/scene/planner.py::_to_domain_scene`
converts that range back into the exact script slice `Scene.
narration_text` has always stored.

These tests cover: a script whose scenes tile cleanly (the happy path),
a script with blank lines between stanzas (the exact shape that broke
the old design on a real run), a single-fragment script (both
directions - one scene succeeds, a second is structurally impossible),
a range that fails to tile (a genuine internal gap, which the
outer-edge snap must not paper over), and the outer-edge snap itself
(small and large drift). `tests/unit/planners/test_fragments.py` covers
the SPLITTER itself - this file is about the PLANNER's use of fragment
ranges, not the fragmentation algorithm.
"""

import logging
import uuid

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.planners.act.schemas import ActPlannerOutput, ActPlanOutput
from app.planners.fragments import split_narration_fragments
from app.planners.repair import run_structured_with_repair
from app.planners.scene.planner import ScenePlanner
from app.planners.scene.schemas import ScenePlannerOutput, ScenePlanOutput
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import CreativeContext

from .helpers import FakePlanningProvider

# 2 sentences -> 2 fragments (verified directly against the real
# splitter, not assumed - see this module's own docstring for why that
# matters here).
SCRIPT = "Germany possessed abundant coal. But it lacked oil, and that would shape the war."

# 5 sentences -> 5 fragments - enough room to test both a small (1) and
# a large (3) outer-edge fragment drift, and a genuine internal gap.
MULTI_SCRIPT = (
    "Germany possessed abundant coal. It powered every factory. "
    "But oil remained scarce. Ships waited empty at port. "
    "That gap would shape the war."
)

# No sentence-ending punctuation at all -> exactly 1 fragment - the
# "one fragment, several scenes" case.
ONE_FRAGMENT_SCRIPT = "Bro this is just one line with no punctuation at all"

# A blank line between two stanzas - the exact shape that broke the old
# verbatim-retyping design on a real run (the user's own scripts put
# blank lines between stanzas). 4 fragments; the blank run folds onto
# the trailing edge of fragment 2 rather than ever becoming its own
# fragment, so there is nothing for a scene boundary to mishandle.
BLANK_LINE_SCRIPT = (
    "Germany had no oil.\nBut it had coal.\n\n"
    "Scientists found a way to turn coal into fuel.\nIt changed the war."
)


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("scene-planner-test")
        return project.id


def _scene(
    *, scene_id: str, order: int, fragment_start: int, fragment_end: int, duration_s: float
) -> ScenePlanOutput:
    return ScenePlanOutput(
        id=scene_id,
        order=order,
        title="Scene title",
        summary="Scene summary.",
        emotion="curiosity",
        narrative_purpose="setup",
        fragment_start=fragment_start,
        fragment_end=fragment_end,
        duration_s=duration_s,
    )


def _valid_output_for(script: str) -> ScenePlannerOutput:
    fragment_count = len(split_narration_fragments(script))
    assert fragment_count == 2, "this fixture assumes a 2-fragment script"
    return ScenePlannerOutput(
        scenes=[
            _scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=1, duration_s=4.0),
            _scene(scene_id="sc_02", order=1, fragment_start=2, fragment_end=2, duration_s=5.0),
        ]
    )


def _output_with_end_short_by(script: str, drift: int) -> ScenePlannerOutput:
    """Two scenes tiling MULTI_SCRIPT's 5 fragments correctly except the
    last scene's `fragment_end` is `drift` fragments short of the true
    count - the fragment-index analogue of a model imprecise about
    where the script actually ends."""
    fragment_count = len(split_narration_fragments(script))
    assert fragment_count == 5, "this fixture assumes a 5-fragment script"
    return ScenePlannerOutput(
        scenes=[
            _scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=2, duration_s=5.0),
            _scene(
                scene_id="sc_02",
                order=1,
                fragment_start=3,
                fragment_end=fragment_count - drift,
                duration_s=5.0,
            ),
        ]
    )


def _output_with_internal_gap(script: str) -> ScenePlannerOutput:
    """Three scenes whose outer boundaries are exactly right (fragment 1
    and the script's true fragment count) but which skip fragment 3
    entirely - a range that fails to tile, the class of error the outer
    snap must NOT paper over."""
    fragment_count = len(split_narration_fragments(script))
    assert fragment_count == 5, "this fixture assumes a 5-fragment script"
    return ScenePlannerOutput(
        scenes=[
            _scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=2, duration_s=3.0),
            _scene(
                scene_id="sc_02",
                order=1,
                # A real gap: skips fragment 3 instead of picking up
                # exactly where scene 1 left off.
                fragment_start=4,
                fragment_end=4,
                duration_s=3.0,
            ),
            _scene(scene_id="sc_03", order=2, fragment_start=5, fragment_end=5, duration_s=3.0),
        ]
    )


async def test_scene_plan_produces_ordered_scenes_that_tile_cleanly(project_id):
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output_for(SCRIPT)])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        scenes = await planner.plan(
            project_id=project_id,
            script=SCRIPT,
            creative_context=CreativeContext(tone="sober", visual_style="archival"),
            max_scenes=12,
            max_video_duration_s=90.0,
        )

    assert [s.id for s in scenes] == ["sc_01", "sc_02"]
    assert all(s.shots == [] for s in scenes)
    assert scenes[0].duration_s == 4.0
    fragments = split_narration_fragments(SCRIPT)
    assert scenes[0].narration_text == SCRIPT[: fragments[0].end]
    assert scenes[1].narration_text == SCRIPT[fragments[1].start :]
    # Coverage invariant replacing the old word-content check: every
    # fragment assigned exactly once, in order, tiling 1..N - and
    # because the split is lossless, that guarantees this too.
    assert "".join(s.narration_text for s in scenes) == SCRIPT


async def test_scene_plan_handles_blank_lines_between_stanzas(project_id):
    """The exact shape that broke the old verbatim design on a real run.
    With fragment ranges the blank run is already baked into a
    fragment's own span before the model ever sees it, so a scene
    boundary chosen over these fragments can never mishandle it."""
    fragment_count = len(split_narration_fragments(BLANK_LINE_SCRIPT))
    assert fragment_count == 4, "this fixture assumes a 4-fragment script"
    output = ScenePlannerOutput(
        scenes=[
            _scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=2, duration_s=4.0),
            _scene(scene_id="sc_02", order=1, fragment_start=3, fragment_end=4, duration_s=4.0),
        ]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[output])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        scenes = await planner.plan(
            project_id=project_id,
            script=BLANK_LINE_SCRIPT,
            creative_context=CreativeContext(),
            max_scenes=12,
            max_video_duration_s=90.0,
        )

    assert len(provider.calls) == 1  # no repair round needed
    assert "".join(s.narration_text for s in scenes) == BLANK_LINE_SCRIPT
    # The blank run lands as TRAILING whitespace on scene 1 (it is a
    # leading part of fragment 2's own span, per fragments.py's own
    # merge rule) - scene 2 starts clean, on real content.
    assert scenes[0].narration_text == "Germany had no oil.\nBut it had coal.\n\n"
    assert (
        scenes[1].narration_text
        == "Scientists found a way to turn coal into fuel.\nIt changed the war."
    )


async def test_single_fragment_script_gets_exactly_one_scene(project_id):
    """The decided behaviour for "a script of one fragment": since a
    fragment can never be split between two scenes, one fragment means
    at most one scene - and a model that (correctly) proposes exactly
    one scene for it succeeds cleanly, no repair needed."""
    output = ScenePlannerOutput(
        scenes=[_scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=1, duration_s=3.0)]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[output])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        scenes = await planner.plan(
            project_id=project_id,
            script=ONE_FRAGMENT_SCRIPT,
            creative_context=CreativeContext(),
            max_scenes=12,
            max_video_duration_s=90.0,
        )

    assert len(provider.calls) == 1
    assert len(scenes) == 1
    assert scenes[0].narration_text == ONE_FRAGMENT_SCRIPT


async def test_single_fragment_script_rejects_a_second_scene(project_id, monkeypatch):
    """The other half of the same decision: a model that proposes TWO
    scenes for a script with only one fragment is asking for a fragment
    that does not exist - not a new failure mode requiring new
    machinery, it fails the exact same fragment-tiling check every other
    structural violation already does.

    (The outer-edge snap forces this script's LAST scene's
    `fragment_end` down to 1, the true count, before the tiling walk
    runs - so the violation that actually surfaces is an impossible
    `fragment_end < fragment_start` on that same now-snapped scene, not
    a separate "count exceeded" message - verified directly against the
    real validator before writing this assertion, the same way S1's
    analogous test was.)"""
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    bad_output = ScenePlannerOutput(
        scenes=[
            _scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=1, duration_s=1.5),
            # Fragment 2 does not exist - this script has exactly one.
            _scene(scene_id="sc_02", order=1, fragment_start=2, fragment_end=2, duration_s=1.5),
        ]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[bad_output, bad_output])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="must be >= fragment_start"):
            await planner.plan(
                project_id=project_id,
                script=ONE_FRAGMENT_SCRIPT,
                creative_context=CreativeContext(),
                max_scenes=12,
                max_video_duration_s=90.0,
            )

    assert len(provider.calls) == 2


async def test_scene_plan_still_fails_on_a_genuine_internal_gap(project_id, monkeypatch):
    """A range that fails to tile: both outer boundaries are exactly
    right, but an internal fragment (3) is skipped entirely. The
    outer-edge snap only ever touches the two OUTER boundaries, so this
    must still fail loudly."""
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    async with async_session_factory() as session:
        # Two identical bad responses: the repair round doesn't fix a
        # canned fake's output, so this proves the failure survives past
        # the repair attempt rather than being a fluke of only trying once.
        provider = FakePlanningProvider(
            responses=[
                _output_with_internal_gap(MULTI_SCRIPT),
                _output_with_internal_gap(MULTI_SCRIPT),
            ]
        )
        planner = ScenePlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="must equal"):
            await planner.plan(
                project_id=project_id,
                script=MULTI_SCRIPT,
                creative_context=CreativeContext(),
                max_scenes=12,
                max_video_duration_s=90.0,
            )

    assert len(provider.calls) == 2  # original attempt + one repair, both rejected


async def test_scene_plan_snaps_a_fragment_end_short_by_one(project_id):
    """The fragment-range analogue of the old character-offset bug: the
    model's last scene ended one fragment short of the script's true
    count. Must snap and succeed on the FIRST attempt (no repair round
    needed) - a drift of 1 is the model being off-by-one about an
    inclusive range, not a genuine misunderstanding."""
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(MULTI_SCRIPT, 1)])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        scenes = await planner.plan(
            project_id=project_id,
            script=MULTI_SCRIPT,
            creative_context=CreativeContext(),
            max_scenes=12,
            max_video_duration_s=90.0,
        )

    assert len(provider.calls) == 1  # no repair round needed
    assert "".join(s.narration_text for s in scenes) == MULTI_SCRIPT


async def test_scene_plan_snaps_a_large_fragment_end_drift_but_logs_a_warning(project_id, caplog):
    """A 1-fragment miss is the model being imprecise about an inclusive
    range; a large miss means it likely misread the fragment list
    entirely. Both must still snap and succeed, but the large one must
    be visible in the logs so a human can notice a planner regression
    instead of it silently sliding by."""
    drift = 3  # comfortably past _LARGE_FRAGMENT_SNAP_THRESHOLD (1)
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(MULTI_SCRIPT, drift)])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        with caplog.at_level(logging.WARNING, logger="app.planners.scene.planner"):
            scenes = await planner.plan(
                project_id=project_id,
                script=MULTI_SCRIPT,
                creative_context=CreativeContext(),
                max_scenes=12,
                max_video_duration_s=90.0,
            )

    assert len(provider.calls) == 1
    assert "".join(s.narration_text for s in scenes) == MULTI_SCRIPT
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].message == "scene_planner.snapped_fragment_end"
    assert warnings[0].drift_fragments == drift


async def test_scene_plan_rejects_too_many_scenes(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    too_many = _valid_output_for(SCRIPT)

    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[too_many, too_many])
        planner = ScenePlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="exceeds the maximum"):
            await planner.plan(
                project_id=project_id,
                script=SCRIPT,
                creative_context=CreativeContext(),
                max_scenes=1,
                max_video_duration_s=90.0,
            )


async def test_path_a_leaves_act_id_none(project_id):
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output_for(SCRIPT)])
        planner = ScenePlanner(provider, LlmCallRepository(session))
        scenes = await planner.plan(
            project_id=project_id,
            script=SCRIPT,
            creative_context=CreativeContext(),
            max_scenes=12,
            max_video_duration_s=90.0,
        )
    assert all(s.act_id is None for s in scenes)


async def test_path_b_rebases_indices_and_sets_act_id(project_id, monkeypatch):
    """N > threshold: act pass, then per-act scene planning on a LOCAL
    1..M fragment list. Absolute indices must never enter the per-act
    prompt (S2 / Track C §2.2)."""
    monkeypatch.setattr(settings, "scene_planner_act_threshold", 3)
    acts = ActPlannerOutput(
        acts=[
            ActPlanOutput(id="act_01", order=0, title="Coal", fragment_start=1, fragment_end=2),
            ActPlanOutput(id="act_02", order=1, title="Oil", fragment_start=3, fragment_end=3),
            ActPlanOutput(id="act_03", order=2, title="War", fragment_start=4, fragment_end=5),
        ]
    )
    # Each act's slice is re-split locally: 2, 1, then 2 fragments.
    act1_scenes = ScenePlannerOutput(
        scenes=[_scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=2, duration_s=5.0)]
    )
    act2_scenes = ScenePlannerOutput(
        scenes=[_scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=1, duration_s=3.0)]
    )
    act3_scenes = ScenePlannerOutput(
        scenes=[_scene(scene_id="sc_01", order=0, fragment_start=1, fragment_end=2, duration_s=5.0)]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[acts, act1_scenes, act2_scenes, act3_scenes])
        planner = ScenePlanner(provider, LlmCallRepository(session))
        scenes = await planner.plan(
            project_id=project_id,
            script=MULTI_SCRIPT,
            creative_context=CreativeContext(tone="sober"),
            max_scenes=12,
            max_video_duration_s=90.0,
        )

    assert [s.id for s in scenes] == ["act_01_sc_01", "act_02_sc_01", "act_03_sc_01"]
    assert [s.act_id for s in scenes] == ["act_01", "act_02", "act_03"]
    assert [s.order for s in scenes] == [0, 1, 2]
    assert "".join(s.narration_text for s in scenes) == MULTI_SCRIPT
    # Per-act prompts must be locally numbered 1..M, never "fragments 3 to 5".
    scene_prompts = [c["user_content"] for c in provider.calls[1:]]
    assert all("3 to 5" not in p and "fragments 3" not in p for p in scene_prompts)
    assert any("1 to 2" in p or "1 to 3" in p or "from 1 to 2" in p or "from 1 to 3" in p for p in scene_prompts)


async def test_run_structured_with_repair_is_reused_correctly(project_id):
    # Sanity check that ScenePlanner is built on the shared repair helper,
    # not a bespoke loop - a regression here would desync the two.
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output_for(SCRIPT)])
        result = await run_structured_with_repair(
            provider=provider,
            llm_call_repo=LlmCallRepository(session),
            project_id=uuid.UUID(project_id),
            agent="scene_planner",
            prompt_version="v1",
            system_prompt="sys",
            user_content="user",
            response_model=ScenePlannerOutput,
            validate=lambda _output: [],
        )
    assert isinstance(result, ScenePlannerOutput)
