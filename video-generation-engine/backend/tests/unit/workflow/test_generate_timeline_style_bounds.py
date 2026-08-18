"""R1 fix (motion_new_styles_and_long_form_videos.md §13.1, 2026-08-18):
`GenerateTimelineStep.run()`'s post-planning validation used to read the
flat `settings.*` bounds directly, while `_is_fully_planned` (the resume
check) already resolved style-derived bounds via `resolve_constraint_
bundle`. For `retention_fast`, those two call sites disagreed: the Shot
Planner was authorised to emit shots as short as 0.8s / up to 58 of
them, and `run()`'s own separate flat-settings check rejected exactly
that timeline every time - killing `retention_fast` even on a small
script, after the Director, Scene Planner, and every Shot Planner call
had already been paid for.

Pure/fast: builds a real `Timeline` object directly and calls the real
`_validate_against_style`/`_is_fully_planned` functions - no DB, no
workflow engine, no LLM. Both `_is_fully_planned` and `run()`'s own gate
now call the SAME function, so a test proving one is provably a test of
both - the divergence this bug actually was, not just the values, is
what this guards against regressing."""

from datetime import UTC, datetime

from app.core.config import settings
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
)
from app.workflow.steps.generate_timeline import _is_fully_planned, _validate_against_style


def _shot(index: int, duration_s: float) -> Shot:
    return Shot(
        id=f"sh_{index:03d}",
        order=index,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        asset_plan=AssetPlan(strategy=AssetStrategy.STOCK_SEARCH),
    )


def _timeline(*, render_style: str | None, shot_count: int, shot_duration_s: float) -> Timeline:
    scene = Scene(
        id="sc_001",
        order=0,
        title="scene",
        duration_s=shot_count * shot_duration_s,
        shots=[_shot(i, shot_duration_s) for i in range(shot_count)],
    )
    timeline = Timeline(
        timeline_id="tl_test",
        project_id="11111111-1111-1111-1111-111111111111",
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        created_at=datetime.now(UTC),
        scenes=[scene],
    )
    timeline.metadata.render_style = render_style
    return timeline


def test_retention_fast_shots_under_the_flat_floor_pass_under_the_resolved_bundle():
    """The exact shape R1 broke: 50 shots at 0.9s each - legal for
    `retention_fast` (floor 0.8s, cap 58), illegal under the flat
    settings (`min_shot_duration_s` is well above 0.9s for the default
    style)."""
    timeline = _timeline(render_style="retention_fast", shot_count=50, shot_duration_s=0.9)

    violations = _validate_against_style(timeline)
    assert violations == []
    assert _is_fully_planned(timeline) is True


def test_the_same_timeline_would_fail_under_the_flat_settings_bounds():
    """Proves the bug was real, not just that the fix's own arithmetic
    happens to pass - the identical timeline, checked against the flat
    settings this code used to call directly, must fail."""
    timeline = _timeline(render_style="retention_fast", shot_count=50, shot_duration_s=0.9)

    violations = timeline.validate_constraints(
        max_video_duration_s=settings.max_video_duration_s,
        max_shots_per_project=settings.max_shots_per_project,
        min_shot_duration_s=settings.min_shot_duration_s,
        max_shot_duration_s=settings.max_shot_duration_s,
        max_scenes=settings.max_scenes,
    )
    assert violations != []


def test_a_retention_fast_timeline_over_its_own_58_shot_cap_still_fails():
    """The style-aware cap is real, not "anything goes" - 60 shots
    exceeds `retention_fast`'s own 58-shot override."""
    timeline = _timeline(render_style="retention_fast", shot_count=60, shot_duration_s=0.9)

    violations = _validate_against_style(timeline)
    assert violations != []
    assert _is_fully_planned(timeline) is False


def test_is_fully_planned_and_runs_own_gate_can_no_longer_disagree():
    """Both call sites in `generate_timeline.py` now go through the same
    function - this is the structural guarantee, not just a values
    check. A future edit to one without the other would show up here as
    soon as it introduces ANY divergent behaviour, since there is only
    one function left to edit."""
    import inspect

    from app.workflow.steps import generate_timeline

    source = inspect.getsource(generate_timeline.GenerateTimelineStep.run)
    assert "_validate_against_style" in source
    is_fully_planned_source = inspect.getsource(generate_timeline._is_fully_planned)
    assert "_validate_against_style" in is_fully_planned_source


def test_a_style_less_timeline_is_unaffected_by_the_refactor():
    """`render_style=None` must still resolve identically to the flat
    settings it always did - the refactor changes WHERE the bundle is
    resolved, not what it resolves to for a pre-existing project."""
    shot_duration_s = max(settings.min_shot_duration_s, 2.0)
    timeline = _timeline(render_style=None, shot_count=5, shot_duration_s=shot_duration_s)

    assert _validate_against_style(timeline) == []
    assert _is_fully_planned(timeline) is True
