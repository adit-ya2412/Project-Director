"""K3 — `enforce_emphasis_rules`. Pure, no DB, no LLM."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.planners.caption_romanizer import numerals
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
    resolve_emphasis_hook_min_shot_gap,
    resolve_emphasis_hook_s,
    resolve_emphasis_max_cues_per_minute,
    resolve_emphasis_min_shot_gap,
)
from app.timeline.duration import compute_shot_start_times, compute_timeline_duration
from app.timeline.emphasis_rules import (
    _ROMAN_NEEDS_SCALE,
    _ROMAN_NUMBER_WORDS,
    _ROMAN_SCALE_WORDS,
    _ROMAN_TO_DEVANAGARI,
    enforce_emphasis_rules,
    shot_blocks_emphasis_cue,
)
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
    hook_s: float | None = None,
    hook_min_shot_gap: int | None = None,
) -> Timeline:
    return enforce_emphasis_rules(
        timeline,
        min_shot_gap=min_shot_gap,
        max_cues_per_minute=max_cues_per_minute,
        hook_s=hook_s,
        hook_min_shot_gap=hook_min_shot_gap,
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
        # Romanised Hindi — the form this pipeline's narration actually
        # uses (reviewed 2026-09-09, one transliteration layer under the
        # first review). Bare unit, and unit as the coefficient of the
        # lakh/crore tier.
        ("do lakh SUVs bik gayi.", 200_000),
        ("Do lakh. Yeh number bada hai.", 200_000),
        ("das lakh se kam price.", 1_000_000),
        ("paanch stars mila.", 5),
        ("paanch karod views.", 50_000_000),
        ("chaar jobs karni padin.", 4),
        # the two real sentences from the live K9 script
        ("2025 mein 2 lakh models bikhe", 200_000),
        ("Safety rating mein paanch stars", 5),
        # decimal coefficient
        ("2.5 lakh cars.", 250_000),
        # multi-word Hindi numeral, parsed by `caption_romanizer.numerals`
        ("दो हजार छब्बीस में launch.", 2026),
        # K19: compound tiers multiply (was summed to 10011000 / 10200000)
        ("ग्यारह हज़ार करोड़", 110_000_000_000),
        ("दो लाख करोड़", 2_000_000_000_000),
        # K19 measured coupling: after `_parse_run` refuses multiplier-only
        # `हज़ार करोड़` / `लाख करोड़`, those words are not consumed by
        # `find_numeral_runs`, so K3's pair reader still product-multiplies
        # scale*scale. Pin the measured products; do not rewrite the pair
        # reader in this slice.
        ("हज़ार करोड़", 10_000_000_000),
        ("लाख करोड़", 1_000_000_000_000),
        # K19.1: pending units then bigger tier (was 260002000 / 5000001000 /
        # 500010000 under the current-vs-total branches)
        ("दो हज़ार छब्बीस करोड़", 20_260_000_000),
        ("एक हज़ार पांच सौ करोड़", 15_000_000_000),
        ("दस हज़ार पचास करोड़", 100_500_000_000),
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
        # the romanised twins of the two rows above (2026-09-09): the
        # `sau`/`hazaar` tier is not read at all, precisely so that a
        # remainder the Latin table does not know cannot be silently
        # dropped off the number — `do hazaar chhabbis` is 2026, and
        # citing 2000 for it would be a forged citation, not a lenience
        ("do hazaar chhabbis mein launch hui.", 2_000),
        ("unnis sau ikatees mein janm hua.", 1_900),
        ("43 hazaar 391 rupaye.", 43_000),
        ("do hazaar chhabbis mein launch hui.", 26),
        # a romanised coefficient with no scale beside it
        ("do SUVs bik gayi.", 200_000),
        ("das lakh se kam price.", 10),
        ("paanch stars mila.", 500_000),
        # a bare scale word carries no coefficient, so it states nothing
        # — before this was measured, `lakh ka sawaal` cited 100000, and
        # so did `do lakh` (the reader fell through the unknown `do` and
        # read `lakh` alone)
        ("lakh ka sawaal hai.", 100_000),
        ("do lakh SUVs bik gayi.", 100_000),
        # digits are still bounded: `2025` does not state `202`
        ("saal 2025 mein.", 202),
        # K19: old wrong compound sums must not cite; new products only
        ("ग्यारह हज़ार करोड़", 10_011_000),
        ("दो लाख करोड़", 10_200_000),
        # K19: pre-fix invented multiplier-only merges must not cite
        ("हज़ार करोड़", 10_001_000),
        ("लाख करोड़", 10_100_000),
        # K19.1: old wrong pending-units compounds must not cite
        ("दो हज़ार छब्बीस करोड़", 260_002_000),
        ("एक हज़ार पांच सौ करोड़", 5_000_001_000),
        ("दस हज़ार पचास करोड़", 500_010_000),
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


@pytest.mark.parametrize(
    ("narration", "value"),
    [
        # `do` is English "do" and `so` is English "so" — a matcher that
        # read this sentence as 2 or as 100 would CERTIFY a number the
        # narration never stated, which is worse than the drop the
        # romanised reading removes, because honesty is the whole point
        # of the rule. `so` for सौ is not in the table at all: the guard
        # for a colliding spelling is "a scale word must sit next to
        # it", and `do so` would satisfy it.
        ("I do think so, it is fine.", 2),
        ("I do think so, it is fine.", 100),
        ("Woh do so ka matlab samjha.", 200),
        # ordinary English words that are also transliterations
        ("The char marks on the wood were deep.", 4),
        ("The bees were loud that afternoon.", 20),
        ("She sat on the tin roof.", 7),
        ("She sat on the tin roof.", 3),
        # `sath` is साथ, "with", far more often than सात, "seven"
        ("Woh mere sath thi.", 7),
    ],
)
def test_romanised_collisions_with_ordinary_words_are_never_cited(narration: str, value: int):
    """The half of the romanised fix that matters most.

    Reviewed 2026-09-09. Do not weaken or delete these: a false CITATION
    silently certifies a number as spoken, and the log line
    `rule=values_citation` only ever appears when a cue is DROPPED — a
    forged match is invisible. A drop is recoverable; a forgery is not.
    """
    shot = _shot(
        emphasis_cue=_counter(value, cited_fragment=1),
        narration_span=(0, len(narration)),
    )
    out = _enforce(_timeline([shot], narration_text=narration))
    assert out.all_shots()[0].emphasis_cue is None


def test_every_romanised_spelling_resolves_through_caption_numerals():
    """The romanised table declares SPELLINGS; the values come from
    `caption_romanizer.numerals`, which stays the single source of truth
    for what a Hindi number word means. `_roman_tables` raises at import
    if a spelling's Devanagari side is not in that table — this pins the
    reuse so a respelling there cannot quietly narrow the matcher.
    """
    assert _ROMAN_TO_DEVANAGARI
    for roman, devanagari in _ROMAN_TO_DEVANAGARI.items():
        assert numerals.word_value(devanagari) is not None, roman
    assert _ROMAN_NUMBER_WORDS["paanch"] == numerals.word_value("पाँच") == 5
    assert _ROMAN_NUMBER_WORDS["das"] == numerals.word_value("दस") == 10
    assert _ROMAN_SCALE_WORDS["karod"] == numerals.word_value("करोड़") == 10_000_000
    # Every guarded spelling must BE a spelling in the table. An entry
    # here that the table does not carry is a dead guard, which means
    # the table's real spelling of that colliding word is being read
    # bare — the forging risk, not a coverage one.
    assert set(_ROMAN_TO_DEVANAGARI) >= _ROMAN_NEEDS_SCALE
    # Absent on purpose, measured: `so` would forge 200 out of "do so",
    # and the `sau`/`hazaar` tier reads years short (`do hazaar
    # chhabbis` -> 2000).
    for withheld in ("so", "sau", "hazaar", "hajaar", "hazar"):
        assert withheld not in _ROMAN_TO_DEVANAGARI


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


def test_retention_fast_knobs_measure_hook_plus_body_on_a_full_reel():
    """K14 band arithmetic, pinned through the real resolvers.

    20 shots x 1.75s = 35.0s. Hook (start < 5.0) is shots 0,1,2; hook
    gap 1 keeps all three. Review finding 2: the body gap counts from
    the last kept BODY cue, so the first body shot (3, start 5.25) is
    kept instead of being pushed away by the hook keeper at 2, and the
    body then runs 6,9,12,15,18 → 9 cues. Body-only cap allows
    12 * 30/60 = 6 body cues and exactly 6 are kept, so the cap does not
    bite. Pre-finding-2 this kept 8 (body 5,8,11,14,17); pre-K14 uniform
    gap 3 kept 7.
    """
    shots = [
        _shot(f"sh_{i:02d}", order=i, duration_s=1.75, emphasis_cue=_cue(text=f"S{i}"))
        for i in range(20)
    ]
    out = _enforce(
        _timeline(shots),
        min_shot_gap=resolve_emphasis_min_shot_gap("retention_fast"),
        max_cues_per_minute=resolve_emphasis_max_cues_per_minute("retention_fast"),
        hook_s=resolve_emphasis_hook_s("retention_fast"),
        hook_min_shot_gap=resolve_emphasis_hook_min_shot_gap("retention_fast"),
    )
    kept = [shot.id for shot in out.all_shots() if shot.emphasis_cue is not None]
    duration_s = compute_timeline_duration(out.all_shots())
    assert kept == [
        "sh_00",
        "sh_01",
        "sh_02",
        "sh_03",
        "sh_06",
        "sh_09",
        "sh_12",
        "sh_15",
        "sh_18",
    ]
    assert duration_s == pytest.approx(35.0)
    assert resolve_emphasis_hook_s("retention_fast") == 5.0
    assert resolve_emphasis_hook_min_shot_gap("retention_fast") == 1


def test_hook_gap_1_keeps_three_consecutive_stamps_uniform_gap_3_would_drop():
    """Shots 0,1,2 at 1.75s start at 0 / 1.75 / 3.5 — all inside a 5s hook."""
    shots = [
        _shot(f"sh_{i}", order=i, duration_s=1.75, emphasis_cue=_cue(text=f"S{i}"))
        for i in range(3)
    ]
    with_hook = _enforce(
        _timeline(shots),
        min_shot_gap=3,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _cues(with_hook) == [
        EmphasisDevice.STAMP,
        EmphasisDevice.STAMP,
        EmphasisDevice.STAMP,
    ]
    without = _enforce(_timeline(shots), min_shot_gap=3)
    assert _cues(without) == [EmphasisDevice.STAMP, None, None]


def test_hook_membership_is_by_start_time_not_index():
    """Short first shots: starts 0 / 1.0 / 2.0 are all in a 5s hook, so
    hook gap 1 keeps all three. Long first shot of 6s: only shot 0
    (start 0) is in the hook — shots 1 and 2 at 6.0 / 7.0 are body, so
    shot 1 is kept as the FIRST body cue (review finding 2: the hook
    keeper does not reach across the boundary) and shot 2, one shot
    after that body keeper, still drops under gap 3. The third cue is
    what distinguishes the two memberships now.
    """
    short = [
        _shot(f"sh_{i}", order=i, duration_s=1.0, emphasis_cue=_cue(text=f"S{i}"))
        for i in range(3)
    ]
    short_starts = compute_shot_start_times(short)
    assert short_starts == {"sh_0": 0.0, "sh_1": 1.0, "sh_2": 2.0}
    short_out = _enforce(
        _timeline(short),
        min_shot_gap=3,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _cues(short_out) == [
        EmphasisDevice.STAMP,
        EmphasisDevice.STAMP,
        EmphasisDevice.STAMP,
    ]

    long = [
        _shot("sh_0", order=0, duration_s=6.0, emphasis_cue=_cue(text="S0")),
        _shot("sh_1", order=1, duration_s=1.0, emphasis_cue=_cue(text="S1")),
        _shot("sh_2", order=2, duration_s=1.0, emphasis_cue=_cue(text="S2")),
    ]
    long_starts = compute_shot_start_times(long)
    assert long_starts == {"sh_0": 0.0, "sh_1": 6.0, "sh_2": 7.0}
    long_out = _enforce(
        _timeline(long),
        min_shot_gap=3,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _cues(long_out) == [EmphasisDevice.STAMP, EmphasisDevice.STAMP, None]


def test_body_adjacent_stamps_after_the_first_body_cue_still_drop():
    """Body gap 3 still applies BETWEEN body cues.

    Hook keeps 0,1,2. Shot 3 (start 5.25) is the first body cue and is
    kept — review finding 2: the hook keeper at 2 no longer reaches
    across the boundary. Shots 4 and 5 are one and two shots after that
    body keeper, so gap 3 still drops them; shot 6 is exactly 3 after
    and survives. This is the assertion that used to read "shot 3
    drops"; the teeth (adjacent body cues drop) moved one shot along.
    """
    shots = [
        _shot(f"sh_{i}", order=i, duration_s=1.75, emphasis_cue=_cue(text=f"S{i}"))
        for i in range(7)
    ]
    out = _enforce(
        _timeline(shots),
        min_shot_gap=3,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _cues(out) == [
        EmphasisDevice.STAMP,
        EmphasisDevice.STAMP,
        EmphasisDevice.STAMP,
        EmphasisDevice.STAMP,
        None,
        None,
        EmphasisDevice.STAMP,
    ]


def test_body_only_rate_cap_does_not_strip_a_dense_hook():
    """K14.2 no-op guard: 5s hook with 3 cues + body at 12/min must not
    be stripped by applying 12.0 to the whole reel.

    30s reel, hook_s=5 → body 25s → allowed body = 12 * 25/60 = 5.
    Three hook stamps + five body stamps spaced by gap 3 all survive;
    a whole-reel 12/min cap on 30s would allow only 6 and strip the hook.
    """
    # 6×1s hook-ish shots (0..5) but only first 5s is hook → shots 0..4
    # start < 5; shot 5 starts at 5.0 → body. Then more body shots.
    shots = [
        _shot(f"sh_{i:02d}", order=i, duration_s=1.0, emphasis_cue=_cue(text=f"S{i}"))
        for i in range(30)
    ]
    # Place cues on hook 0,1,2 and body 5,8,11,14,17 (gap 3 from last
    # hook keeper at 2 → first body keeper at 5).
    keep_idx = {0, 1, 2, 5, 8, 11, 14, 17}
    for i, shot in enumerate(shots):
        if i not in keep_idx:
            shot.emphasis_cue = None
    out = _enforce(
        _timeline(shots),
        min_shot_gap=3,
        max_cues_per_minute=12.0,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    kept = [shot.id for shot in out.all_shots() if shot.emphasis_cue is not None]
    assert kept == [
        "sh_00",
        "sh_01",
        "sh_02",
        "sh_05",
        "sh_08",
        "sh_11",
        "sh_14",
        "sh_17",
    ]
    # Whole-reel 12/min on 30s would allow only 6 — proving body-only
    # is what let all 8 survive.
    whole_reel = _enforce(
        _timeline(
            [
                _shot(
                    f"sh_{i:02d}",
                    order=i,
                    duration_s=1.0,
                    emphasis_cue=_cue(text=f"S{i}") if i in keep_idx else None,
                )
                for i in range(30)
            ]
        ),
        max_cues_per_minute=12.0,
    )
    whole_kept = [s.id for s in whole_reel.all_shots() if s.emphasis_cue is not None]
    assert len(whole_kept) == 6
    assert len(kept) == 8


# The shot shape of the watched `retention_fast` reel (34dd1ee1):
# 12 shots, 24.68s. Starts 0.00 / 2.82 / 5.54 / 7.15 / 8.84 / 10.65 /
# 12.75 / 15.16 / 17.09 / 19.13 / 21.09 / 22.92, so a 5.0s hook holds
# shot starts 0 and 1 only.
_WATCHED_REEL_DURATIONS = [
    2.82,
    2.72,
    1.61,
    1.69,
    1.81,
    2.10,
    2.41,
    1.93,
    2.04,
    1.96,
    1.83,
    1.76,
]


def _watched_reel(authored: dict[int, EmphasisCue]) -> Timeline:
    return _timeline(
        [
            _shot(
                f"sh{i:02d}",
                order=i,
                duration_s=duration,
                emphasis_cue=authored.get(i),
            )
            for i, duration in enumerate(_WATCHED_REEL_DURATIONS)
        ],
        narration_text="hello there. लेकिन there.",
    )


def _kept_ids(timeline: Timeline) -> list[str]:
    return [shot.id for shot in timeline.all_shots() if shot.emphasis_cue is not None]


def test_first_body_cue_survives_a_hook_cue():
    """Review finding 2, the exact case that exposed it.

    Authored on shots 0 and 2 of the watched reel: shot 2 starts at
    5.54s, outside the 5.0s hook, and is 2 shots after the hook cue on
    shot 0. Before the fix the body gap counted from that hook keeper
    and dropped it, leaving `authored [0,2] -> kept sh00` and a 6.02s
    hole immediately after the hook. Now the body gap counts from the
    last kept BODY cue — there is none — so shot 2 is kept.
    """
    out = _enforce(
        _watched_reel({0: _cue(text="A"), 2: _cue(text="B")}),
        min_shot_gap=3,
        max_cues_per_minute=12.0,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _kept_ids(out) == ["sh00", "sh02"]


def test_hook_cue_is_not_evicted_by_a_pivot_in_the_body():
    """The pivot still outranks, but only inside its own regime.

    Hook stamps on shots 0 and 1, pivot on shot 2 (first body shot).
    Before the fix the pivot was "inside the gap" of the hook keeper at
    1 and evicted it, so a body pivot ate a hook cue. The pivot is still
    kept; the hook cue is no longer the price.
    """
    out = _enforce(
        _watched_reel({0: _cue(text="A"), 1: _cue(text="B"), 2: _pivot()}),
        min_shot_gap=3,
        max_cues_per_minute=12.0,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _kept_ids(out) == ["sh00", "sh01", "sh02"]
    assert out.all_shots()[2].emphasis_cue is not None
    assert out.all_shots()[2].emphasis_cue.device is EmphasisDevice.PIVOT


def test_body_stamp_still_yields_to_a_body_pivot_inside_the_gap():
    """Unchanged guarantee: a non-pivot yields to a pivot genuinely
    inside the gap, now measured between two BODY cues (shots 3 and 4,
    one apart, both outside the 5.0s hook)."""
    out = _enforce(
        _watched_reel({3: _cue(text="A"), 4: _pivot()}),
        min_shot_gap=3,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _kept_ids(out) == ["sh04"]


def test_two_body_pivots_inside_the_gap_are_both_kept():
    out = _enforce(
        _watched_reel({3: _pivot(), 4: _pivot()}),
        min_shot_gap=3,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _kept_ids(out) == ["sh03", "sh04"]


def test_lone_late_pivot_survives_hook_and_cap_across_the_boundary():
    """A lone pivot on the last shot is kept even though it is the only
    cue in the body and the body-only cap allows fewer than one."""
    out = _enforce(
        _watched_reel({11: _pivot()}),
        min_shot_gap=3,
        max_cues_per_minute=0.1,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _kept_ids(out) == ["sh11"]


def test_hook_capacity_bounds_what_enforcement_can_keep_in_the_hook():
    """Review finding 1 measured on the watched reel: only two shots
    start inside a 5.0s hook, so a third authored hook cue lands on a
    BODY shot (5.54s) and is kept as the first body cue rather than as a
    third hook cue. Authoring must not ask for three (see
    `planners/emphasis/planner._hook_capacity`).
    """
    reel = _watched_reel({0: _cue(text="A"), 1: _cue(text="B"), 2: _cue(text="C")})
    starts = compute_shot_start_times(reel.all_shots())
    in_hook = [shot_id for shot_id, start in starts.items() if start < 5.0]
    assert in_hook == ["sh00", "sh01"]
    out = _enforce(
        reel,
        min_shot_gap=3,
        max_cues_per_minute=12.0,
        hook_s=5.0,
        hook_min_shot_gap=1,
    )
    assert _kept_ids(out) == ["sh00", "sh01", "sh02"]


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
