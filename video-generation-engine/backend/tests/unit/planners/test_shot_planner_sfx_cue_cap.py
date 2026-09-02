"""`_cap_sfx_cues` — the project-wide `sfx_cue` rate + repetition pass.

long_form_direction.md A14. Same class of pass as `_cap_glitch_transitions`
and `_cap_text_cards`: the Shot Planner is called ONCE PER SCENE and
cannot see cues emitted by other scenes, so a whole-video rate/repetition
target cannot be enforced in the prompt alone. Pure, no DB, no LLM — run
with `--noconftest`.

Measured origin: a real 3-scene probe of "The nuclear lake" produced 4
cues across 10 shots (one every 2.5, target one every six to ten), three
of the four near-identical wind:

    faint wind across open water
    faint wind across open steppe
    distant heavy explosion rumble
    faint wind across open steppe
"""

import pytest

from app.core.config import settings
from app.planners.shot.planner import (
    _SFX_CUE_DUPLICATE_THRESHOLD,
    _cap_sfx_cues,
    _sfx_cues_are_near_duplicates,
)
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    Scene,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)


def _shot(idx: int, cue: str | None, *, id_prefix: str = "") -> Shot:
    return Shot(
        id=f"{id_prefix}sh_{idx:02d}",
        order=idx,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
        sfx_cue=cue,
    )


def _scene(sid: str, cues: list[str | None]) -> Scene:
    return Scene(
        id=sid,
        order=0,
        title=sid,
        duration_s=float(2 * len(cues)),
        shots=[_shot(i, c, id_prefix=f"{sid}_") for i, c in enumerate(cues)],
    )


def _cues(scenes: list[Scene]) -> list[str]:
    return [s.sfx_cue for sc in scenes for s in sc.shots if (s.sfx_cue or "").strip()]


# ---------------------------------------------------------------------------
# Minimum shot gap
# ---------------------------------------------------------------------------


def test_cues_closer_than_the_gap_are_cleared():
    scenes = [
        _scene(
            "sc_01",
            ["engine roar", "crowd murmuring", "bell tolling", None, None, None, None],
        )
    ]
    # engine roar / crowd murmuring / bell tolling are mutually distinct
    # content, so only the GAP mechanism is in play here.
    out = _cap_sfx_cues(scenes)
    assert _cues(out) == ["engine roar"]


def test_spacing_is_enforced_across_scene_boundaries_not_per_scene():
    """The whole point: two scenes that are each individually reasonable
    (one cue apiece) are still too dense together when the scenes are
    short. A per-scene rule cannot see this; this pass can."""
    scenes = [
        _scene("sc_01", ["engine roar", None]),
        _scene("sc_02", ["crowd murmuring", None]),
    ]
    # Only 2 shots separate the two cues -> well under the configured gap.
    assert _cues(_cap_sfx_cues(scenes)) == ["engine roar"]


def test_a_cue_far_enough_away_is_kept():
    gap = settings.sfx_cue_min_shot_gap
    cues: list[str | None] = ["engine roar"] + [None] * gap + ["crowd murmuring"]
    scenes = [_scene("sc_01", cues)]
    assert _cues(_cap_sfx_cues(scenes)) == ["engine roar", "crowd murmuring"]


def test_a_project_with_no_cues_is_unaffected():
    scenes = [_scene("sc_01", [None, None, None]), _scene("sc_02", [None])]
    out = _cap_sfx_cues(scenes)
    assert _cues(out) == []
    # Byte-identical: no shot was even model_copy'd with a changed value.
    for sc, orig_sc in zip(out, scenes, strict=True):
        assert [s.sfx_cue for s in sc.shots] == [s.sfx_cue for s in orig_sc.shots]


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------


def test_near_duplicate_wind_cues_collide_even_far_apart_in_shot_count():
    """The real probe's own failure: two wind cues far enough apart to
    both clear the gap must still collide on CONTENT."""
    gap = settings.sfx_cue_min_shot_gap
    cues: list[str | None] = (
        ["faint wind across open water"]
        + [None] * gap
        + ["faint wind across open steppe"]
    )
    scenes = [_scene("sc_01", cues)]
    assert _cues(_cap_sfx_cues(scenes)) == ["faint wind across open water"]


def test_the_real_probe_distribution_lands_inside_the_intended_rate():
    """Reproduces the real 3-scene probe's own cue TEXTS, packed into 10
    shots at the same rate it was measured at (4 cues, one every 2.5) -
    the flat shot-index spacing between scenes isn't recorded by the
    plan, so this pins the invariant that matters: the cap must always
    strictly reduce a repetitive, too-dense attempt, at most one wind
    cue may survive, and no two survivors are closer than the gap."""
    gap = settings.sfx_cue_min_shot_gap
    cues: list[str | None] = [None] * 10
    cues[0] = "faint wind across open water"
    cues[3] = "faint wind across open steppe"
    cues[6] = "distant heavy explosion rumble"
    cues[8] = "faint wind across open steppe"
    scenes = [_scene("sc_01", cues)]

    out = _cap_sfx_cues(scenes)
    survivors = _cues(out)

    assert survivors.count("faint wind across open water") == 1
    assert "faint wind across open steppe" not in survivors
    # No two survivors are closer than the configured gap.
    positions = [i for i, s in enumerate(out[0].shots) if (s.sfx_cue or "").strip()]
    for a, b in zip(positions, positions[1:], strict=False):
        assert b - a >= gap
    # 10 shots and at most 2 survivors -> at least one cue per 5 shots,
    # inside (or better than) the "six to ten" target's low end once the
    # duplicate is removed; strictly fewer than the raw 4 attempted.
    assert len(survivors) < 4


def test_genuinely_different_cues_all_survive_when_spaced_out():
    gap = settings.sfx_cue_min_shot_gap
    cues: list[str | None] = []
    for c in ["machinery hum", "crowd murmuring", "bell tolling"]:
        cues.append(c)
        cues.extend([None] * gap)
    scenes = [_scene("sc_01", cues)]
    assert _cues(_cap_sfx_cues(scenes)) == ["machinery hum", "crowd murmuring", "bell tolling"]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("faint wind across open water", "faint wind across open steppe", True),
        ("machinery hum", "crowd murmuring", False),
        ("faint dog barking", "faint chime tinkling", False),
        ("bell tolling", "bell tolling", True),
        ("distant heavy explosion rumble", "faint wind across open steppe", False),
    ],
)
def test_near_duplicate_threshold_matches_and_distinguishes_real_examples(a, b, expected):
    assert _sfx_cues_are_near_duplicates(a, b) is expected


def test_duplicate_threshold_is_calibrated_between_the_real_collision_and_a_real_near_miss():
    """Pin the two numbers the threshold was chosen from, so a future
    change to the threshold has to look at this test."""
    collision = _sfx_cues_are_near_duplicates(
        "faint wind across open water", "faint wind across open steppe"
    )
    near_miss = _sfx_cues_are_near_duplicates("machinery hum", "crowd murmuring")
    assert collision is True
    assert near_miss is False
    assert _SFX_CUE_DUPLICATE_THRESHOLD == 0.5


# ---------------------------------------------------------------------------
# Shots without cues are never touched; the pass is otherwise inert
# ---------------------------------------------------------------------------


def test_shots_without_cues_are_never_modified():
    scenes = [_scene("sc_01", [None, None, "engine roar", None])]
    out = _cap_sfx_cues(scenes)
    assert [s.id for s in out[0].shots] == [s.id for s in scenes[0].shots]
    assert _cues(out) == ["engine roar"]


def test_whitespace_only_cue_is_not_treated_as_a_cue():
    scenes = [_scene("sc_01", ["   ", "engine roar", None])]
    assert _cues(_cap_sfx_cues(scenes)) == ["engine roar"]


def test_configured_gap_is_the_low_end_of_the_arithmetic_that_targets_six_to_ten():
    assert settings.sfx_cue_min_shot_gap == 6


# ---------------------------------------------------------------------------
# Logging distinguishes gap-drops from duplicate-drops (A14's own
# complaint about `_cap_text_cards`' original single `cleared` count).
# ---------------------------------------------------------------------------


def test_log_distinguishes_gap_drops_from_duplicate_drops(caplog):
    gap = settings.sfx_cue_min_shot_gap
    scenes = [
        _scene(
            "sc_01",
            [
                "faint wind across open water",  # kept
                "crowd murmuring",  # cleared: too close (gap)
                *([None] * (gap - 1)),
                "faint wind across open steppe",  # cleared: duplicate
            ],
        )
    ]
    with caplog.at_level("WARNING"):
        _cap_sfx_cues(scenes)

    records = [r for r in caplog.records if r.message == "shot_planner.sfx_cues_too_dense_trimmed"]
    assert len(records) == 1
    record = records[0]
    assert record.cleared_gap == 1
    assert record.cleared_duplicate == 1
    assert record.kept == 1
