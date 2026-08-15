"""`Timeline.validate_constraints` (M8 hardening, 2026-08-16 - "A26 is a
deadlock in practice"). Pure, fast, no network, no DB - `validate_constraints`
is a plain method on the Timeline model.

The bug this fixes: `GenerateTimelineStep._is_fully_planned` used to
exempt shot-duration bounds only when the ACTIVE version's own
`produced_by == NARRATION` - which describes the version that just
landed, not the Timeline's history, so any LATER version (a human
override, a music retry, a narration-voice retry) fell back out of the
exemption and re-failed against planning-time heuristics that measured,
real narration has no obligation to satisfy. `Timeline.metadata
.narration_locked` is a persistent flag, set once by `NarrationStep` and
never reset, that `validate_constraints` itself reads directly - so the
exemption survives every later version, not just one.

`tests/integration/test_narration_locked_constraints.py` proves the same
property through the real mechanism end to end (`TimelineService
.append_version` + `GenerateTimelineStep.is_satisfied`, on a throwaway
project) - this file is about the pure validation logic in isolation.
"""

from datetime import UTC, datetime

from app.schemas.timeline import (
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineMetadata,
    TimelineStatus,
)

_BOUNDS = {
    "max_video_duration_s": 90.0,
    "max_shots_per_project": 40,
    "min_shot_duration_s": 1.5,
    "max_shot_duration_s": 8.0,
    "max_scenes": 12,
}


def _timeline(
    *,
    narration_locked: bool = False,
    produced_by: ProducedBy = ProducedBy.HUMAN,
    shots: list[Shot] | None = None,
    total_duration_s: float = 0.0,
) -> Timeline:
    shots = (
        shots
        if shots is not None
        else [Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)]
    )
    scene = Scene(
        id="sc_01", order=0, title="t", duration_s=sum(s.duration_s for s in shots), shots=shots
    )
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=produced_by,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
        metadata=TimelineMetadata(
            total_duration_s=total_duration_s, narration_locked=narration_locked
        ),
    )


def test_a_short_shot_still_fails_before_narration_has_locked_durations():
    """The planning-time case must still work exactly as before - a
    shot duration outside the configured bounds is a real violation
    right up until narration measures reality."""
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=0.615)
    t = _timeline(narration_locked=False, shots=[shot], total_duration_s=0.615)
    violations = t.validate_constraints(**_BOUNDS)
    assert any("duration_s=0.615" in v for v in violations)


def test_narration_locked_exempts_a_short_shot_on_the_narration_version_itself():
    """The case that already worked before this fix, via the old
    `produced_by == NARRATION` special case - still works, now via the
    persistent flag instead."""
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=0.615)
    t = _timeline(
        narration_locked=True,
        produced_by=ProducedBy.NARRATION,
        shots=[shot],
        total_duration_s=0.615,
    )
    assert t.validate_constraints(**_BOUNDS) == []


def test_narration_locked_exempts_a_short_shot_on_a_later_human_version():
    """THE EXACT REPORTED BUG: a version produced by something other
    than NARRATION (a human override, in the real incident) built on
    top of an already narration-locked timeline. Before this fix, the
    old `produced_by == NARRATION` check would have missed this
    entirely, since `produced_by` here is HUMAN, not NARRATION."""
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=0.615)
    t = _timeline(
        narration_locked=True, produced_by=ProducedBy.HUMAN, shots=[shot], total_duration_s=0.615
    )
    assert t.validate_constraints(**_BOUNDS) == []


def test_narration_locked_exempts_float_noise_at_the_boundary():
    """The second real case from the same incident: 1.498s against a
    1.5s floor - two milliseconds of float noise, not a creative
    violation. Not fixed by widening the bound or adding an epsilon
    (explicitly rejected) - fixed by not re-applying the planning bound
    to measured reality at all."""
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=1.498)
    t = _timeline(
        narration_locked=True, produced_by=ProducedBy.HUMAN, shots=[shot], total_duration_s=1.498
    )
    assert t.validate_constraints(**_BOUNDS) == []


def test_structural_invariants_stay_enforced_even_when_narration_locked():
    """The exemption is narrow - only the per-shot duration BOUNDS
    check is skipped. Duplicate shot ids, too many shots, too many
    scenes, and the total video duration cap all still apply, since
    narration reconciling durations never has a legitimate reason to
    produce any of these."""
    dup_shots = [
        Shot(id="dup", order=0, intent=ShotIntent.EXPLAIN, duration_s=0.6),
        Shot(id="dup", order=1, intent=ShotIntent.EXPLAIN, duration_s=0.6),
    ]
    t = _timeline(
        narration_locked=True, produced_by=ProducedBy.HUMAN, shots=dup_shots, total_duration_s=1.2
    )
    violations = t.validate_constraints(**_BOUNDS)
    assert any("duplicate shot ids" in v for v in violations)


def test_total_video_duration_cap_stays_enforced_even_when_narration_locked():
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=0.6)
    t = _timeline(narration_locked=True, produced_by=ProducedBy.HUMAN, shots=[shot])
    t.metadata.total_duration_s = 999.0  # narration reconciliation would have raised on this
    violations = t.validate_constraints(**_BOUNDS)
    assert any("total_duration_s" in v for v in violations)


def test_max_shots_per_project_stays_enforced_even_when_narration_locked():
    shots = [
        Shot(id=f"sh_{i:02d}", order=i, intent=ShotIntent.EXPLAIN, duration_s=0.6) for i in range(3)
    ]
    t = _timeline(narration_locked=True, produced_by=ProducedBy.HUMAN, shots=shots)
    violations = t.validate_constraints(
        max_video_duration_s=90.0,
        max_shots_per_project=2,  # 3 shots exceeds this
        min_shot_duration_s=0.1,
        max_shot_duration_s=8.0,
        max_scenes=12,
    )
    assert any("exceeds max_shots_per_project" in v for v in violations)
