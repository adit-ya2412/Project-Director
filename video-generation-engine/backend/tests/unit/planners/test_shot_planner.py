"""Golden-file test for the Shot Planner: verifies fragment-range
coverage, per-scene looping, and the running max_shots_per_project cap.

## Fragment ranges, not character offsets (M5 hardening, 2026-08-15)

Three separate incidents of the Shot Planner doing unreliable character
arithmetic (cross-scene shot-id collisions, the outer narration boundary
off by four characters killing a live run, and internal boundaries
splitting mid-word/mid-grapheme-cluster) converged on one fix: the model
is no longer asked for `narration_start`/`narration_end` character
offsets at all. It is handed a scene's narration pre-split into numbered
fragments (`app/planners/shot/fragments.py`) and asked only for a
CONTIGUOUS RANGE of fragment numbers per shot - a far more natural
judgement, and one where a mid-word or mid-grapheme split is
structurally impossible rather than something to detect and repair.

These tests cover the OUTER-edge fragment snap (kept as a backstop, the
same reasoning as its character-offset predecessor - a small drift is
the model being off-by-one about an inclusive range, a large one
suggests it misread the fragment list entirely), a genuine internal gap
still failing loudly, and the new fragment-count-exceeded case (a scene
cannot have more shots than fragments - see
`app/planners/shot/fragments.py`'s own docstring for why that is not a
new rule, just this same tiling check).

`app/planners/shot/fragments.py`'s own tests
(`tests/unit/planners/test_fragments.py`) cover the SPLITTER itself
(the Latin/Devanagari word- and grapheme-safety, the long-sentence
subdivision) - this file is about the PLANNER's use of fragment ranges,
not the fragmentation algorithm.
"""

import logging

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.planners.shot.fragments import split_narration_fragments
from app.planners.shot.planner import ShotPlanner
from app.planners.shot.schemas import (
    ShotCameraOutput,
    ShotPlannerOutput,
    ShotPlanOutput,
    ShotTransitionOutput,
)
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    CameraDirection,
    CameraMovement,
    CreativeContext,
    Framing,
    Scene,
    ShotIntent,
    TransitionType,
)

from .helpers import FakePlanningProvider

# 2 sentences -> 2 fragments (verified directly against the real
# splitter, not assumed - see this module's own docstring for why that
# matters here).
NARRATION = "Germany possessed abundant coal. It fueled every furnace in the Ruhr."

# 5 sentences -> 5 fragments - enough room to test both a small (1) and
# a large (3) outer-edge fragment drift, and a genuine internal gap.
MULTI_NARRATION = (
    "Germany possessed abundant coal. It powered every factory. "
    "But oil remained scarce. Ships waited empty at port. "
    "That gap would shape the war."
)

# No sentence-ending punctuation at all -> exactly 1 fragment - the
# "one fragment, several shots" case.
ONE_FRAGMENT_NARRATION = "Bro this is just one line with no punctuation at all"


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("shot-planner-test")
        return project.id


def _scene(scene_id: str = "sc_01", duration_s: float = 4.0, narration: str = NARRATION) -> Scene:
    return Scene(
        id=scene_id, order=0, title="Coal wealth", narration_text=narration, duration_s=duration_s
    )


def _shot(
    *,
    shot_id: str,
    order: int,
    fragment_start: int,
    fragment_end: int,
    duration_s: float,
) -> ShotPlanOutput:
    return ShotPlanOutput(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        intent_text="text",
        fragment_start=fragment_start,
        fragment_end=fragment_end,
        duration_s=duration_s,
        framing=Framing.WIDE,
        camera=ShotCameraOutput(
            movement=CameraMovement.STATIC, direction=CameraDirection.NONE, intensity=0.0
        ),
        transition_out=ShotTransitionOutput(type=TransitionType.CUT, duration_s=0.0),
        prompt="archival photograph",
    )


def _valid_output_for(scene: Scene) -> ShotPlannerOutput:
    # Raw ids deliberately do NOT encode the scene - this mirrors what the
    # real model does (reuses the same simple pattern for every scene,
    # since each call only ever sees one scene). Global uniqueness comes
    # from ShotPlanner namespacing by scene_id, not from this id.
    fragment_count = len(split_narration_fragments(scene.narration_text))
    assert fragment_count == 2, "this fixture assumes a 2-fragment scene"
    half = scene.duration_s / 2
    return ShotPlannerOutput(
        shots=[
            _shot(shot_id="sh_01", order=0, fragment_start=1, fragment_end=1, duration_s=half),
            _shot(shot_id="sh_02", order=1, fragment_start=2, fragment_end=2, duration_s=half),
        ]
    )


def _output_with_end_short_by(scene: Scene, drift: int) -> ShotPlannerOutput:
    """Two shots tiling MULTI_NARRATION's 5 fragments correctly except
    the last shot's `fragment_end` is `drift` fragments short of the
    true count - the fragment-index analogue of the real bug report
    (144 vs 140 characters, now 5 vs 5-drift fragments). Durations sum
    exactly to the scene's own `duration_s` (10.0) so the ONLY violation
    a wrong drift can produce is the fragment one under test - a
    mismatched duration sum would trigger an unrelated repair round and
    break the "no repair round needed" assertions these fixtures feed."""
    fragment_count = len(split_narration_fragments(scene.narration_text))
    assert fragment_count == 5, "this fixture assumes a 5-fragment scene"
    return ShotPlannerOutput(
        shots=[
            _shot(shot_id="sh_01", order=0, fragment_start=1, fragment_end=2, duration_s=5.0),
            _shot(
                shot_id="sh_02",
                order=1,
                fragment_start=3,
                fragment_end=fragment_count - drift,
                duration_s=5.0,
            ),
        ]
    )


def _output_with_internal_gap(scene: Scene) -> ShotPlannerOutput:
    """Three shots whose outer boundaries are exactly right (fragment 1
    and the scene's true fragment count) but which skip fragment 3
    entirely - the class of error the snap must NOT paper over."""
    fragment_count = len(split_narration_fragments(scene.narration_text))
    assert fragment_count == 5, "this fixture assumes a 5-fragment scene"
    return ShotPlannerOutput(
        shots=[
            _shot(shot_id="sh_01", order=0, fragment_start=1, fragment_end=2, duration_s=1.5),
            _shot(
                shot_id="sh_02",
                order=1,
                # A real gap: skips fragment 3 instead of picking up
                # exactly where shot 1 left off.
                fragment_start=4,
                fragment_end=4,
                duration_s=1.5,
            ),
            _shot(shot_id="sh_03", order=2, fragment_start=5, fragment_end=5, duration_s=1.5),
        ]
    )


async def test_shot_plan_snaps_a_fragment_end_short_by_one(project_id):
    """The fragment-range analogue of the real bug: the model's last
    shot ended one fragment short of the scene's true count. Must snap
    and succeed on the FIRST attempt (no repair round needed) - a drift
    of 1 is the model being off-by-one about an inclusive range, not a
    genuine misunderstanding."""
    scene = _scene(narration=MULTI_NARRATION, duration_s=10.0)
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(scene, 1)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
        )

    assert len(provider.calls) == 1  # no repair round needed
    shots = planned[0].shots
    assert shots[0].narration_span[0] == 0
    assert shots[-1].narration_span[1] == len(scene.narration_text)


async def test_shot_plan_still_fails_on_a_genuine_internal_gap(project_id, monkeypatch):
    """The snap only ever touches the two OUTER fragment boundaries. A
    gap between two INTERNAL shots (a skipped fragment) is a real
    structural error and must still fail loudly, even though both outer
    boundaries are correct in this output."""
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene(narration=MULTI_NARRATION, duration_s=10.0)
    async with async_session_factory() as session:
        # Two identical bad responses: the repair round doesn't fix a
        # canned fake's output, so this proves the failure survives past
        # the repair attempt rather than being a fluke of only trying once.
        provider = FakePlanningProvider(
            responses=[_output_with_internal_gap(scene), _output_with_internal_gap(scene)]
        )
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="must equal"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert len(provider.calls) == 2  # original attempt + one repair, both rejected


async def test_shot_plan_snaps_a_large_fragment_end_drift_but_logs_a_warning(project_id, caplog):
    """A 1-fragment miss is the model being imprecise about an inclusive
    range; a large miss means it likely misread the fragment list
    entirely. Both must still snap and succeed - the render still needs
    a video - but the large one must be visible in the logs so a human
    can notice a planner regression instead of it silently sliding by."""
    scene = _scene(narration=MULTI_NARRATION, duration_s=10.0)
    drift = 3  # comfortably past _LARGE_FRAGMENT_SNAP_THRESHOLD (1)
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(scene, drift)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with caplog.at_level(logging.WARNING, logger="app.planners.shot.planner"):
            planned = await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert len(provider.calls) == 1
    assert planned[0].shots[-1].narration_span[1] == len(scene.narration_text)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].message == "shot_planner.snapped_fragment_end"
    assert warnings[0].drift_fragments == drift


async def test_shot_plan_snaps_a_small_fragment_end_drift_without_a_warning(project_id, caplog):
    """A 1-fragment drift must stay a quiet, routine correction - not
    something that spams the logs on every ordinary, slightly-imprecise
    model output."""
    scene = _scene(narration=MULTI_NARRATION, duration_s=10.0)
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_output_with_end_short_by(scene, 1)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with caplog.at_level(logging.INFO, logger="app.planners.shot.planner"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert not any(r.levelno == logging.WARNING for r in caplog.records)
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert info_records[0].drift_fragments == 1


async def test_shot_plan_fills_shots_covering_the_full_narration(project_id):
    scene = _scene()
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output_for(scene)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.5,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
        )

    shots = planned[0].shots
    assert [s.id for s in shots] == ["sc_01_sh_01", "sc_01_sh_02"]
    fragments = split_narration_fragments(scene.narration_text)
    assert shots[0].narration_span == (fragments[0].start, fragments[0].end)
    assert shots[-1].narration_span[1] == len(scene.narration_text)
    assert all(s.asset_plan is None for s in shots)


async def test_shot_plan_loops_once_per_scene(project_id):
    scene_a = _scene("sc_01")
    scene_b = _scene("sc_02")
    async with async_session_factory() as session:
        provider = FakePlanningProvider(
            responses=[_valid_output_for(scene_a), _valid_output_for(scene_b)]
        )
        planner = ShotPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene_a, scene_b],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.5,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
        )

    assert len(provider.calls) == 2
    # Both scenes' fake responses reuse the same raw ids ("sh_01", "sh_02")
    # - exactly what the real model does, since each call is blind to the
    # other scenes. Namespacing by scene_id must still keep them globally
    # unique across scenes.
    assert [s.id for s in planned[0].shots] == ["sc_01_sh_01", "sc_01_sh_02"]
    assert [s.id for s in planned[1].shots] == ["sc_02_sh_01", "sc_02_sh_02"]
    all_ids = [s.id for scene in planned for s in scene.shots]
    assert len(all_ids) == len(set(all_ids))


async def test_shot_plan_enforces_project_wide_shot_cap(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[_valid_output_for(scene)])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="max_shots_per_project"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.5,
                max_shot_duration_s=8.0,
                max_shots_per_project=1,  # the fixture produces 2 shots
            )


async def test_one_fragment_scene_gets_exactly_one_shot(project_id):
    """The decided behaviour for "a scene of one fragment": since a
    fragment can never be split between two shots, one fragment means at
    most one shot - and a model that (correctly) proposes exactly one
    shot for it succeeds cleanly, no repair needed."""
    scene = _scene(narration=ONE_FRAGMENT_NARRATION, duration_s=3.0)
    output = ShotPlannerOutput(
        shots=[
            _shot(shot_id="sh_01", order=0, fragment_start=1, fragment_end=1, duration_s=3.0),
        ]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[output])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        planned = await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
        )

    assert len(provider.calls) == 1
    shots = planned[0].shots
    assert len(shots) == 1
    assert shots[0].narration_span == (0, len(scene.narration_text))


async def test_one_fragment_scene_rejects_a_second_shot(project_id, monkeypatch):
    """The other half of the same decision: a model that proposes TWO
    shots for a scene with only one fragment is asking for a fragment
    that does not exist (or to split fragment 1 between two shots,
    which the schema does not represent at all) - this is not a new
    failure mode requiring new machinery, it fails the exact same
    fragment-tiling check every other structural violation already does,
    and is fed back for repair exactly the same way.

    (The outer-edge snap forces this scene's LAST shot's `fragment_end`
    down to 1, the true count, before the tiling walk runs - so the
    violation that actually surfaces here is an impossible
    `fragment_end < fragment_start` on that same now-snapped shot, not a
    separate "count exceeded" message. `test_shot_plan_rejects_a_shot_
    whose_own_range_exceeds_the_fragment_count` below covers that
    other message directly, on a scene with enough fragments that the
    outer snap does not also touch the offending shot.)"""
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene(narration=ONE_FRAGMENT_NARRATION, duration_s=3.0)
    bad_output = ShotPlannerOutput(
        shots=[
            _shot(shot_id="sh_01", order=0, fragment_start=1, fragment_end=1, duration_s=1.5),
            # Fragment 2 does not exist - this scene has exactly one.
            _shot(shot_id="sh_02", order=1, fragment_start=2, fragment_end=2, duration_s=1.5),
        ]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[bad_output, bad_output])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="must be >= fragment_start"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert len(provider.calls) == 2


async def test_shot_plan_rejects_a_shot_whose_own_range_exceeds_the_fragment_count(
    project_id, monkeypatch
):
    """The "exceeds this scene's fragment count" message directly, on a
    MIDDLE shot the outer-edge snap never touches (only the first
    shot's start and the last shot's end are ever snapped) - proving
    that specific, clearer diagnostic fires when a non-edge shot is the
    one claiming a fragment that does not exist."""
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene(narration=MULTI_NARRATION, duration_s=10.0)  # 5 real fragments
    bad_output = ShotPlannerOutput(
        shots=[
            _shot(shot_id="sh_01", order=0, fragment_start=1, fragment_end=1, duration_s=2.0),
            # Fragment 8 does not exist - only 5 fragments in this scene.
            _shot(shot_id="sh_02", order=1, fragment_start=2, fragment_end=8, duration_s=2.0),
            _shot(shot_id="sh_03", order=2, fragment_start=9, fragment_end=5, duration_s=2.0),
        ]
    )
    async with async_session_factory() as session:
        provider = FakePlanningProvider(responses=[bad_output, bad_output])
        planner = ShotPlanner(provider, LlmCallRepository(session))

        with pytest.raises(PermanentError, match="exceeds this scene's fragment count"):
            await planner.plan(
                project_id=project_id,
                scenes=[scene],
                creative_context=CreativeContext(),
                min_shot_duration_s=1.0,
                max_shot_duration_s=8.0,
                max_shots_per_project=40,
            )

    assert len(provider.calls) == 2
