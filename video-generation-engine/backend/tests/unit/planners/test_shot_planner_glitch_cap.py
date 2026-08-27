"""prompt_fixes.md §3.2: post-gather glitch cap.

The Shot Planner runs one LLM call per scene, so "at most one glitch per
video" cannot be enforced in the prompt. `_cap_glitch_transitions` is
the deterministic corrective pass: keep the first glitch in scene/shot
order, downgrade the rest to CUT.

Pure - no DB, no LLM, `--noconftest`-safe. Own file so it does not share
test_shot_planner.py's async_session_factory (which errors under
--noconftest).
"""

from app.planners.shot.planner import _GLITCH_TYPES, _cap_glitch_transitions
from app.schemas.timeline import (
    Scene,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)


def _shot(shot_id: str, order: int, transition: TransitionType) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        prompt="archival photograph",
        transition_out=Transition(
            type=transition,
            duration_s=0.0 if transition == TransitionType.CUT else 0.4,
        ),
    )


def _scene(scene_id: str, order: int, transitions: list[TransitionType]) -> Scene:
    shots = [_shot(f"{scene_id}_sh_{i+1:02d}", i, t) for i, t in enumerate(transitions)]
    return Scene(
        id=scene_id,
        order=order,
        title=scene_id,
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
    )


def _types(scenes: list[Scene]) -> list[list[TransitionType]]:
    return [[shot.transition_out.type for shot in scene.shots] for scene in scenes]


def test_first_glitch_survives_later_ones_become_cut():
    scenes = [
        _scene("sc_01", 0, [TransitionType.CUT, TransitionType.GLITCH_SHIFT]),
        _scene("sc_03", 1, [TransitionType.GLITCH_TEAR]),
        _scene("sc_05", 2, [TransitionType.DISSOLVE, TransitionType.GLITCH_JITTER]),
    ]
    capped = _cap_glitch_transitions(scenes)
    assert _types(capped) == [
        [TransitionType.CUT, TransitionType.GLITCH_SHIFT],
        [TransitionType.CUT],
        [TransitionType.DISSOLVE, TransitionType.CUT],
    ]
    # Downgraded glitches are a real cut, not a zero-duration leftover.
    assert capped[1].shots[0].transition_out.duration_s == 0.0
    assert capped[2].shots[1].transition_out.duration_s == 0.0


def test_a_single_glitch_timeline_is_untouched():
    scenes = [
        _scene("sc_01", 0, [TransitionType.CUT, TransitionType.DISSOLVE]),
        _scene("sc_02", 1, [TransitionType.GLITCH_TEAR, TransitionType.CUT]),
    ]
    original = _types(scenes)
    capped = _cap_glitch_transitions(scenes)
    assert _types(capped) == original
    assert capped[1].shots[0].transition_out.type == TransitionType.GLITCH_TEAR
    assert capped[1].shots[0].transition_out.duration_s == 0.4


def test_non_glitch_transitions_are_never_modified():
    scenes = [
        _scene(
            "sc_01",
            0,
            [
                TransitionType.CUT,
                TransitionType.DISSOLVE,
                TransitionType.FADE,
                TransitionType.WIPE_LEFT,
                TransitionType.DIP_TO_BLACK,
            ],
        )
    ]
    original = _types(scenes)
    assert _types(_cap_glitch_transitions(scenes)) == original


def test_two_glitches_in_the_same_scene_keep_only_the_first():
    scenes = [
        _scene(
            "sc_01",
            0,
            [TransitionType.GLITCH_SHIFT, TransitionType.CUT, TransitionType.GLITCH_JITTER],
        )
    ]
    capped = _cap_glitch_transitions(scenes)
    assert _types(capped) == [[TransitionType.GLITCH_SHIFT, TransitionType.CUT, TransitionType.CUT]]


def test_glitch_type_set_is_exactly_the_three_custom_values():
    assert {
        TransitionType.GLITCH_SHIFT,
        TransitionType.GLITCH_TEAR,
        TransitionType.GLITCH_JITTER,
    } == _GLITCH_TYPES
