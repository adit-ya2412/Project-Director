"""K3 — `enforce_emphasis_rules`. Pure, no DB, no LLM."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.timeline import (
    EmphasisCue,
    EmphasisDevice,
    EmphasisRegister,
    EmphasisValue,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.script.styles import (
    resolve_emphasis_max_cues_per_minute,
    resolve_emphasis_min_shot_gap,
)
from app.timeline.duration import compute_timeline_duration
from app.timeline.emphasis_rules import enforce_emphasis_rules, shot_blocks_emphasis_cue
from app.timeline.pivot import attach_pivot_cue, detect_pivot


def _cue(**overrides) -> EmphasisCue:
    fields = {
        "device": EmphasisDevice.STAMP,
        "anchor_fragment": 1,
        "text": "2025",
        "text_register": EmphasisRegister.EN,
    }
    fields.update(overrides)
    return EmphasisCue(**fields)


def _pivot() -> EmphasisCue:
    return _cue(
        device=EmphasisDevice.PIVOT,
        text="लेकिन",
        text_register=EmphasisRegister.HI,
    )


def _counter(value: int, cited_fragment: int) -> EmphasisCue:
    return _cue(
        device=EmphasisDevice.COUNTER,
        text="SOLD IN A YEAR",
        values=[EmphasisValue(value=value, cited_fragment=cited_fragment)],
    )


def _shot(
    shot_id: str = "sh_01",
    *,
    order: int = 0,
    duration_s: float = 2.0,
    **overrides,
) -> Shot:
    fields = {
        "id": shot_id,
        "order": order,
        "intent": ShotIntent.EXPLAIN,
        "duration_s": duration_s,
        "narration_span": (0, 1),
    }
    fields.update(overrides)
    return Shot(**fields)


def _timeline(
    shots: list[Shot],
    *,
    narration_text: str = "hello there.",
) -> Timeline:
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[
            Scene(
                id="sc_01",
                order=0,
                title="hook",
                narration_text=narration_text,
                duration_s=sum(s.duration_s for s in shots),
                shots=shots,
            )
        ],
    )


def _enforce(
    timeline: Timeline,
    *,
    min_shot_gap: int | None = None,
    max_cues_per_minute: float | None = None,
) -> Timeline:
    return enforce_emphasis_rules(
        timeline,
        min_shot_gap=min_shot_gap,
        max_cues_per_minute=max_cues_per_minute,
    )


def _cues(timeline: Timeline) -> list[EmphasisDevice | None]:
    return [
        shot.emphasis_cue.device if shot.emphasis_cue is not None else None
        for shot in timeline.all_shots()
    ]


def test_validator_refuses_text_card_and_cue_together():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _shot(text_card="THE MYTH", emphasis_cue=_pivot())


def test_detect_and_attach_on_a_text_card_pivot_shot_yield_no_cue():
    text = "hello lekin there. but later"
    shot = _shot(text_card="TITLE", narration_span=(0, len(text)))
    timeline = _timeline([shot], narration_text=text)
    assert detect_pivot(timeline) is None
    attached = attach_pivot_cue(timeline)
    assert attached.all_shots()[0].emphasis_cue is None
    assert attached.all_shots()[0].text_card == "TITLE"


def test_enforce_drops_a_cue_poked_onto_a_text_card_shot():
    """Schema refuses to construct both; the pass still corrects assignment.

    Poke after Timeline construction: wrapping the illegal Shot in a
    Scene re-runs the validator and would raise before the pass ran.
    """
    original = _timeline([_shot(text_card="TITLE")])
    original.all_shots()[0].emphasis_cue = _cue()
    assert shot_blocks_emphasis_cue(original.all_shots()[0]) == "text_card"
    out = _enforce(original)
    assert out.all_shots()[0].emphasis_cue is None
    assert out.all_shots()[0].text_card == "TITLE"
    assert original.all_shots()[0].emphasis_cue is not None


def test_picture_is_graphic_true_drops_the_cue_false_keeps_it():
    graphic = _timeline([_shot(picture_is_graphic=True, emphasis_cue=_cue())])
    plain = _timeline([_shot(picture_is_graphic=False, emphasis_cue=_cue())])
    assert _enforce(graphic).all_shots()[0].emphasis_cue is None
    kept = _enforce(plain).all_shots()[0].emphasis_cue
    assert kept is not None
    assert kept.device is EmphasisDevice.STAMP


def test_picture_is_graphic_defaults_to_false():
    assert _shot().picture_is_graphic is False


def test_graphic_on_the_pivot_shot_means_the_reel_has_none():
    text = "hello lekin there. but later"
    shot = _shot(picture_is_graphic=True, narration_span=(0, len(text)))
    timeline = _timeline([shot], narration_text=text)
    assert detect_pivot(timeline) is None
    assert attach_pivot_cue(timeline).all_shots()[0].emphasis_cue is None


def test_counter_uncitable_value_is_dropped():
    narration = "nice car, no figure here."
    shot = _shot(emphasis_cue=_counter(200000, cited_fragment=1), narration_span=(0, len(narration)))
    out = _enforce(_timeline([shot], narration_text=narration))
    assert out.all_shots()[0].emphasis_cue is None


@pytest.mark.parametrize(
    "narration",
    [
        "200000 sold this year.",
        "2,00,000 sold this year.",
        "2 lakh sold this year.",
    ],
)
def test_counter_citable_value_is_kept(narration: str):
    shot = _shot(
        emphasis_cue=_counter(200000, cited_fragment=1),
        narration_span=(0, len(narration)),
    )
    out = _enforce(_timeline([shot], narration_text=narration))
    cue = out.all_shots()[0].emphasis_cue
    assert cue is not None
    assert cue.device is EmphasisDevice.COUNTER
    assert cue.values[0].value == 200000


@pytest.mark.parametrize(
    ("narration", "value"),
    [
        # Hindi, spelled out — coefficient and scale both in Devanagari.
        ("दो लाख SUVs bik gayi.", 200_000),
        ("पाँच लाख गाड़ियाँ sold.", 500_000),
        ("price भी दस लाख से कम.", 1_000_000),
        # bare Devanagari number word, no scale
        ("Safety rating में पाँच stars.", 5),
        # English, spelled out
        ("two lakh SUVs sold.", 200_000),
        ("five crore views.", 50_000_000),
        ("ten thousand bookings.", 10_000),
        # decimal coefficient
        ("2.5 lakh cars.", 250_000),
        # multi-word Hindi numeral, parsed by `caption_romanizer.numerals`
        ("दो हजार छब्बीस में launch.", 2026),
    ],
)
def test_spelled_out_and_decimal_values_are_cited(narration: str, value: int):
    """Review 2026-09-09: the matcher read digits only, so a narration
    that spells the number out dropped the cue with `rule=
    values_citation` — which reads in the log as "the model invented a
    number" when the script said it plainly.
    """
    shot = _shot(
        emphasis_cue=_counter(value, cited_fragment=1),
        narration_span=(0, len(narration)),
    )
    out = _enforce(_timeline([shot], narration_text=narration))
    cue = out.all_shots()[0].emphasis_cue
    assert cue is not None
    assert cue.values[0].value == value


@pytest.mark.parametrize(
    ("narration", "value"),
    [
        # a number stated nowhere in the fragment
        ("दो लाख SUVs bik gayi.", 300_000),
        ("two lakh SUVs sold.", 400_000),
        # the coefficient alone is not a citation of the product
        ("दो लाख SUVs bik gayi.", 2),
        # nor is the scale word alone
        ("two lakh SUVs sold.", 100_000),
        # a multi-word Hindi numeral states its WHOLE value: `दो हजार
        # छब्बीस` is 2026, not also 2000 or 26 (the §11 defect in the
        # other direction — a merged run reported as a partial number)
        ("दो हजार छब्बीस में launch.", 2_000),
        ("दो हजार छब्बीस में launch.", 26),
    ],
)
def test_the_rule_still_has_teeth_on_a_genuine_miss(narration: str, value: int):
    """A spelled-out pair is read as ONE value and consumed: citing its
    coefficient or its scale word by itself is still a miss, and a
    number the fragment never states is still a miss.
    """
    shot = _shot(
        emphasis_cue=_counter(value, cited_fragment=1),
        narration_span=(0, len(narration)),
    )
    out = _enforce(_timeline([shot], narration_text=narration))
    assert out.all_shots()[0].emphasis_cue is None


def test_an_out_of_range_cited_fragment_is_a_miss():
    narration = "दो लाख SUVs bik gayi."
    shot = _shot(
        emphasis_cue=_counter(200_000, cited_fragment=9),
        narration_span=(0, len(narration)),
    )
    out = _enforce(_timeline([shot], narration_text=narration))
    assert out.all_shots()[0].emphasis_cue is None


def test_one_miss_among_several_values_drops_the_whole_cue():
    narration = "दो लाख SUVs bik gayi."
    cue = _cue(
        device=EmphasisDevice.COUNTER,
        text="SOLD IN A YEAR",
        values=[
            EmphasisValue(value=200_000, cited_fragment=1),
            EmphasisValue(value=999, cited_fragment=1),
        ],
    )
    shot = _shot(emphasis_cue=cue, narration_span=(0, len(narration)))
    out = _enforce(_timeline([shot], narration_text=narration))
    assert out.all_shots()[0].emphasis_cue is None


def test_empty_values_on_a_pivot_are_not_a_citation_failure():
    shot = _shot(emphasis_cue=_pivot())
    assert shot.emphasis_cue is not None
    assert shot.emphasis_cue.values == []
    out = _enforce(_timeline([shot]))
    assert out.all_shots()[0].emphasis_cue is not None
    assert out.all_shots()[0].emphasis_cue.device is EmphasisDevice.PIVOT


def test_at_most_one_cue_per_shot_is_structural():
    shot = _shot(emphasis_cue=_cue())
    assert shot.emphasis_cue is not None
    assert not isinstance(shot.emphasis_cue, list)


def _reel(devices: dict[int, EmphasisDevice], n_shots: int) -> Timeline:
    """`n_shots` shots in film order, cues only where `devices` says."""
    shots: list[Shot] = []
    for i in range(n_shots):
        device = devices.get(i)
        if device is EmphasisDevice.PIVOT:
            cue: EmphasisCue | None = _pivot()
        elif device is not None:
            cue = _cue(text=f"S{i}")
        else:
            cue = None
        shots.append(_shot(f"sh_{i:02d}", order=i, emphasis_cue=cue))
    return _timeline(shots)


@pytest.mark.parametrize(
    ("distance", "second_survives"),
    [(1, False), (2, False), (3, True), (4, True)],
)
def test_min_gap_is_an_index_distance_so_distance_equal_to_the_gap_survives(
    distance: int,
    second_survives: bool,
):
    """The boundary the first implementation got wrong (review 2026-09-09).

    Every pre-review min_gap test used two ADJACENT shots (distance 1),
    so nothing pinned distance == `min_shot_gap`. The pass counted
    "shots seen since the keeper", which read a distance of `d` as
    `d - 1` and made the effective gap 4 at `min_shot_gap=3`. The rule
    is an index distance: kept when `i - last_kept_index >= gap`.
    """
    out = _enforce(
        _reel({0: EmphasisDevice.STAMP, distance: EmphasisDevice.STAMP}, distance + 1),
        min_shot_gap=3,
    )
    kept = [i for i, device in enumerate(_cues(out)) if device is not None]
    assert kept == ([0, distance] if second_survives else [0])


def test_stamp_then_pivot_at_exactly_the_gap_keeps_both():
    """The pivot rescue must not fire when the stamp was never inside the gap."""
    out = _enforce(
        _reel({0: EmphasisDevice.STAMP, 3: EmphasisDevice.PIVOT}, 4),
        min_shot_gap=3,
    )
    assert _cues(out) == [
        EmphasisDevice.STAMP,
        None,
        None,
        EmphasisDevice.PIVOT,
    ]


def test_two_pivots_inside_the_gap_are_both_kept():
    out = _enforce(
        _reel({0: EmphasisDevice.PIVOT, 1: EmphasisDevice.PIVOT}, 2),
        min_shot_gap=3,
    )
    assert _cues(out) == [EmphasisDevice.PIVOT, EmphasisDevice.PIVOT]


def test_a_dropped_cue_does_not_restart_the_gap():
    """The gap runs from the last KEPT index, so collisions do not ratchet.

    Shot 3 is distance 3 from the surviving cue on shot 0 and survives,
    even though shot 2's dropped cue is closer.
    """
    out = _enforce(
        _reel(dict.fromkeys(range(4), EmphasisDevice.STAMP), 4),
        min_shot_gap=3,
    )
    assert _cues(out) == [EmphasisDevice.STAMP, None, None, EmphasisDevice.STAMP]


def test_retention_fast_knobs_measure_12_cues_per_minute_on_a_full_reel():
    """The band comment's arithmetic, pinned through the real resolvers.

    20 shots x 1.75s = 35.0s; gap 3 keeps shots 0, 3, ... 18 = 7 cues =
    12.00/min, exactly the 12.0/min cap. Before the index-distance fix
    the same reel measured 8.57/min, below the plan's 8-12/min band and
    nowhere near the cap the comment calls the ceiling.
    """
    shots = [
        _shot(f"sh_{i:02d}", order=i, duration_s=1.75, emphasis_cue=_cue(text=f"S{i}"))
        for i in range(20)
    ]
    out = _enforce(
        _timeline(shots),
        min_shot_gap=resolve_emphasis_min_shot_gap("retention_fast"),
        max_cues_per_minute=resolve_emphasis_max_cues_per_minute("retention_fast"),
    )
    kept = [shot.id for shot in out.all_shots() if shot.emphasis_cue is not None]
    duration_s = compute_timeline_duration(out.all_shots())
    assert kept == ["sh_00", "sh_03", "sh_06", "sh_09", "sh_12", "sh_15", "sh_18"]
    assert duration_s == pytest.approx(35.0)
    assert len(kept) * 60.0 / duration_s == pytest.approx(12.0)


def test_adjacent_stamps_second_dropped_at_min_gap_3():
    shots = [
        _shot("sh_a", order=0, emphasis_cue=_cue(text="A")),
        _shot("sh_b", order=1, emphasis_cue=_cue(text="B")),
    ]
    out = _enforce(_timeline(shots), min_shot_gap=3)
    assert _cues(out) == [EmphasisDevice.STAMP, None]


def test_pivot_inside_a_stamp_gap_stamp_yields_pivot_kept():
    shots = [
        _shot("sh_a", order=0, emphasis_cue=_cue()),
        _shot("sh_b", order=1, emphasis_cue=_pivot()),
    ]
    out = _enforce(_timeline(shots), min_shot_gap=3)
    assert _cues(out) == [None, EmphasisDevice.PIVOT]


def test_lone_pivot_is_never_dropped_for_density():
    shot = _shot(emphasis_cue=_pivot(), duration_s=2.0)
    out = _enforce(
        _timeline([shot]),
        min_shot_gap=3,
        max_cues_per_minute=0.1,
    )
    cue = out.all_shots()[0].emphasis_cue
    assert cue is not None
    assert cue.device is EmphasisDevice.PIVOT


def test_rate_cap_drops_extra_stamps_and_keeps_the_pivot():
    # 6 shots × 1s = 6s. 10 cues/min → allowed = 1.0. The pivot takes
    # that slot; every stamp is a non-pivot in film order and drops.
    shots = [
        _shot("sh_0", order=0, duration_s=1.0, emphasis_cue=_cue(text="0")),
        _shot("sh_1", order=1, duration_s=1.0, emphasis_cue=_cue(text="1")),
        _shot("sh_2", order=2, duration_s=1.0, emphasis_cue=_cue(text="2")),
        _shot("sh_3", order=3, duration_s=1.0, emphasis_cue=_cue(text="3")),
        _shot("sh_4", order=4, duration_s=1.0, emphasis_cue=_pivot()),
        _shot("sh_5", order=5, duration_s=1.0),
    ]
    out = _enforce(_timeline(shots), max_cues_per_minute=10.0)
    assert _cues(out) == [None, None, None, None, EmphasisDevice.PIVOT, None]


def test_rate_cap_keeps_earliest_stamps_that_still_fit_with_the_pivot():
    # 6s, 20/min → allowed = 2.0. One stamp + the pivot fit; the rest drop.
    shots = [
        _shot("sh_0", order=0, duration_s=1.0, emphasis_cue=_cue(text="0")),
        _shot("sh_1", order=1, duration_s=1.0, emphasis_cue=_cue(text="1")),
        _shot("sh_2", order=2, duration_s=1.0, emphasis_cue=_cue(text="2")),
        _shot("sh_3", order=3, duration_s=1.0, emphasis_cue=_pivot()),
        _shot("sh_4", order=4, duration_s=1.0),
        _shot("sh_5", order=5, duration_s=1.0),
    ]
    out = _enforce(_timeline(shots), max_cues_per_minute=20.0)
    assert _cues(out) == [
        EmphasisDevice.STAMP,
        None,
        None,
        EmphasisDevice.PIVOT,
        None,
        None,
    ]


def test_input_timeline_is_not_mutated():
    shots = [
        _shot("sh_a", order=0, emphasis_cue=_cue(text="A")),
        _shot("sh_b", order=1, emphasis_cue=_cue(text="B")),
    ]
    original = _timeline(shots)
    original_first = original.all_shots()[0].emphasis_cue
    original_second = original.all_shots()[1].emphasis_cue
    out = _enforce(original, min_shot_gap=3)
    assert out is not original
    assert original.all_shots()[0].emphasis_cue is original_first
    assert original.all_shots()[1].emphasis_cue is original_second
    assert original_second is not None
    assert out.all_shots()[1].emphasis_cue is None
