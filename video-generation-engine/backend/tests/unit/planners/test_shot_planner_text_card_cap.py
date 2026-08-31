"""`_cap_text_cards` — the project-wide text-card spacing pass.

Third instance of prompt_fixes.md §2.1's rule (a whole-video rate that
no per-scene call can see), after `max_video_shots_per_project` and the
glitch cap. Pure, no DB, no LLM — run with `--noconftest`.

Measured origin: real run d3a4d00d produced 17 cards across 39 shots
(~1 per 2.3) against a prompt asking for "roughly one every four to six
shots", because 10 scenes averaging ~4 shots each independently emitted
about one apiece — and 17 cards meant 17 stinger SFX hits.
"""

import pytest

from app.core.config import settings
from app.planners.shot.planner import _cap_text_cards
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    Scene,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)


def _shot(idx: int, card: str | None, *, id_prefix: str = "") -> Shot:
    return Shot(
        id=f"{id_prefix}sh_{idx:02d}",
        order=idx,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
        text_card=card,
    )


def _scene(sid: str, cards: list[str | None]) -> Scene:
    # id_prefix keeps shot ids unique ACROSS scenes (not just within one) -
    # needed so A7's chapter-card tests can name one shot precisely via
    # `chapter_shot_ids` without an accidental id collision with another
    # scene's shot of the same index.
    return Scene(
        id=sid,
        order=0,
        title=sid,
        duration_s=float(2 * len(cards)),
        shots=[_shot(i, c, id_prefix=f"{sid}_") for i, c in enumerate(cards)],
    )


def _cards(scenes: list[Scene]) -> list[str]:
    return [s.text_card for sc in scenes for s in sc.shots if (s.text_card or "").strip()]


def test_cards_closer_than_the_gap_are_cleared():
    # Adjacent cards: only the first survives at any gap >= 1.
    scenes = [_scene("sc_01", ["A", "B", "C", None, None])]
    assert _cards(_cap_text_cards(scenes, min_gap=4)) == ["A"]


def test_spacing_is_enforced_across_scene_boundaries_not_per_scene():
    """The whole point: two scenes that are each individually reasonable
    (one card apiece) are still too dense together when the scenes are
    short. A per-scene rule cannot see this; this pass can."""
    scenes = [_scene("sc_01", ["A", None]), _scene("sc_02", ["B", None])]
    # Only 2 shots separate A and B -> B is cleared at min_gap=4.
    assert _cards(_cap_text_cards(scenes, min_gap=4)) == ["A"]


def test_a_card_far_enough_away_is_kept():
    scenes = [_scene("sc_01", ["A", None, None, None, None, "B"])]
    assert _cards(_cap_text_cards(scenes, min_gap=4)) == ["A", "B"]


def test_already_sparse_cards_are_untouched():
    """The cap only ever trims genuine excess — a timeline already
    inside the intended rate must pass through byte-identical."""
    scenes = [_scene("sc_01", ["A", None, None, None, None, None, "B"])]
    out = _cap_text_cards(scenes, min_gap=4)
    assert _cards(out) == ["A", "B"]
    assert [s.text_card for s in out[0].shots] == [s.text_card for s in scenes[0].shots]


def test_shots_without_cards_are_never_modified():
    scenes = [_scene("sc_01", [None, None, "A", None])]
    out = _cap_text_cards(scenes, min_gap=4)
    assert [s.id for s in out[0].shots] == [s.id for s in scenes[0].shots]
    assert _cards(out) == ["A"]


def test_whitespace_only_card_is_not_treated_as_a_card():
    """`"   "` must not consume the spacing budget and block a real card
    that follows — the planner maps blank to None, but a stray string
    should behave identically here."""
    scenes = [_scene("sc_01", ["   ", "REAL", None])]
    assert _cards(_cap_text_cards(scenes, min_gap=4)) == ["REAL"]


def test_zero_or_negative_gap_disables_the_cap():
    scenes = [_scene("sc_01", ["A", "B", "C"])]
    assert _cards(_cap_text_cards(scenes, min_gap=0)) == ["A", "B", "C"]


def test_the_real_d3a4d00d_distribution_lands_inside_the_intended_rate():
    """Regression against the measurement that motivated this pass: the
    real per-scene card counts from d3a4d00d (10 scenes / 39 shots / 17
    cards) must come out at roughly one per four-to-six shots."""
    per_scene = [
        (4, [0]),  # sc_01: 1 card
        (3, [0, 1]),  # sc_02: 2
        (7, [0, 1, 2, 3]),  # sc_03: 4
        (4, [0, 1]),  # sc_04: 2
        (3, [0, 1]),  # sc_05: 2
        (4, [0]),  # sc_06: 1
        (4, [0, 1]),  # sc_07: 2
        (2, []),  # sc_08: 0
        (4, [0, 1]),  # sc_09: 2
        (4, [0]),  # sc_10: 1
    ]
    scenes = []
    for i, (n_shots, card_idx) in enumerate(per_scene):
        scenes.append(
            _scene(f"sc_{i:02d}", [f"c{i}_{j}" if j in card_idx else None for j in range(n_shots)])
        )

    total_shots = sum(n for n, _ in per_scene)
    assert total_shots == 39
    assert len(_cards(scenes)) == 17  # the measured "before"

    kept = _cards(_cap_text_cards(scenes, min_gap=settings.text_card_min_shot_gap))
    assert len(kept) < 17
    # One per >= 4 shots, i.e. inside the prompt's own "four to six".
    assert total_shots / len(kept) >= 4.0


def test_configured_gap_is_the_low_end_of_the_prompts_range():
    """The prompt asks for one card every four to six shots; the cap is
    set to the LOW end so it only trims genuine excess rather than
    fighting the style's intent."""
    assert settings.text_card_min_shot_gap == 4


@pytest.mark.parametrize("gap", [1, 2, 4, 8])
def test_no_two_kept_cards_are_ever_closer_than_the_gap(gap):
    """The invariant, at several gaps: whatever survives must satisfy
    the spacing rule."""
    scenes = [_scene("sc_01", [f"c{i}" for i in range(20)])]
    out = _cap_text_cards(scenes, min_gap=gap)
    positions = [i for i, s in enumerate(out[0].shots) if (s.text_card or "").strip()]
    for a, b in zip(positions, positions[1:], strict=False):
        assert b - a >= gap


# ---------------------------------------------------------------------------
# A7 (long_form_direction.md §3): chapter cards outrank ordinary cards.
# ---------------------------------------------------------------------------


def test_the_a7_collision_keeps_the_chapter_card_and_drops_the_ordinary_one():
    """The exact bug reproduced in P-LF-A4's log entry: act 1's last
    scene puts an ordinary card on its final shot; act 2's first scene
    (an act opener) puts a chapter card on its own first shot, one shot
    later - inside `min_gap=4`. Before A7 the chapter card was the one
    silently cleared. After A7 it must be the ordinary one."""
    act1_last_scene = _scene("act01_sc03", [None, None, "1929: The Crash"])
    act2_first_scene = _scene("act02_sc01", ["Act Two: Recovery", None, None])
    scenes = [act1_last_scene, act2_first_scene]
    chapter_shot_ids = frozenset({act2_first_scene.shots[0].id})

    out = _cap_text_cards(scenes, min_gap=4, chapter_shot_ids=chapter_shot_ids)

    assert out[0].shots[2].text_card is None  # the ordinary card yielded
    assert out[1].shots[0].text_card == "Act Two: Recovery"  # the chapter card survived
    assert _cards(out) == ["Act Two: Recovery"]


def test_a_chapter_card_is_never_cleared_even_far_below_the_gap():
    """Adjacent shots (gap of 0), the tightest possible collision: the
    chapter card still survives and the ordinary one is still the one
    dropped."""
    scene = _scene("act01_sc01", ["ordinary", "Chapter One"])
    chapter_shot_ids = frozenset({scene.shots[1].id})

    out = _cap_text_cards([scene], min_gap=4, chapter_shot_ids=chapter_shot_ids)

    assert out[0].shots[0].text_card is None
    assert out[0].shots[1].text_card == "Chapter One"


def test_an_ordinary_card_shortly_after_a_chapter_card_still_yields_as_before():
    """The reverse direction needs no special-casing: the chapter card
    is already 'kept' by the time the ordinary one downstream is
    checked, so the pre-existing spacing rule already makes it yield -
    this pins that down as a real behaviour, not an assumption."""
    scene = _scene("act01_sc01", ["Chapter One", None, "ordinary"])
    chapter_shot_ids = frozenset({scene.shots[0].id})

    out = _cap_text_cards([scene], min_gap=4, chapter_shot_ids=chapter_shot_ids)

    assert out[0].shots[0].text_card == "Chapter One"
    assert out[0].shots[2].text_card is None


def test_two_chapter_cards_within_the_gap_are_both_kept():
    """§3 A7: 'two chapter cards cannot realistically collide ... but
    assert the behaviour rather than assuming it.' Decision made here:
    a chapter card is NEVER cleared, full stop - so if two ever do land
    within `min_gap`, both survive rather than the second silently
    losing to the first."""
    scene = _scene("act01_sc01", ["Chapter One", "Chapter Two"])
    chapter_shot_ids = frozenset({scene.shots[0].id, scene.shots[1].id})

    out = _cap_text_cards([scene], min_gap=4, chapter_shot_ids=chapter_shot_ids)

    assert _cards(out) == ["Chapter One", "Chapter Two"]


def test_ordinary_only_spacing_is_unchanged_when_there_are_no_chapter_cards():
    """Regression guard: with `chapter_shot_ids` at its default (empty),
    every shot is an ordinary shot and A7's new branch never activates -
    the outcome must match the pre-A7 spacing rule exactly."""
    scenes = [_scene("sc_01", ["A", "B", "C", None, None])]
    assert _cards(_cap_text_cards(scenes, min_gap=4)) == ["A"]

    scenes = [_scene("sc_01", ["A", None, None, None, None, "B"])]
    assert _cards(_cap_text_cards(scenes, min_gap=4)) == ["A", "B"]


def test_path_a_project_with_no_acts_is_byte_identical_to_pre_a7_behaviour():
    """Path A projects (<=70 fragments) never set `act_id`, so
    `ShotPlanner.plan()` never populates `chapter_shot_ids` for them
    (it stays empty - see `plan()`'s own comment). Re-run the real
    measured d3a4d00d distribution (the pre-A7 regression fixture above)
    with no chapter ids at all and pin the exact surviving cards, not
    just a count, to nail down 'byte-identical' rather than 'close
    enough'."""
    per_scene = [
        (4, [0]),
        (3, [0, 1]),
        (7, [0, 1, 2, 3]),
        (4, [0, 1]),
        (3, [0, 1]),
        (4, [0]),
        (4, [0, 1]),
        (2, []),
        (4, [0, 1]),
        (4, [0]),
    ]
    scenes = [
        _scene(f"sc_{i:02d}", [f"c{i}_{j}" if j in card_idx else None for j in range(n_shots)])
        for i, (n_shots, card_idx) in enumerate(per_scene)
    ]

    without_a7 = _cards(_cap_text_cards(scenes, min_gap=settings.text_card_min_shot_gap))
    with_empty_chapter_ids = _cards(
        _cap_text_cards(
            scenes,
            min_gap=settings.text_card_min_shot_gap,
            chapter_shot_ids=frozenset(),
        )
    )
    assert with_empty_chapter_ids == without_a7
    assert with_empty_chapter_ids == [
        "c0_0",
        "c1_1",
        "c2_3",
        "c3_1",
        "c5_0",
        "c6_1",
        "c8_0",
    ]
