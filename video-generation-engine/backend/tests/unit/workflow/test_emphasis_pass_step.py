"""`EmphasisPassStep` — K10 attach only, no LLM.

DB-free: `is_satisfied` / `run` touch `ctx.timeline_service.get_active`
and `append_version`, so a stub context is enough.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas.timeline import (
    EmphasisDevice,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.workflow.steps import emphasis_pass
from app.workflow.steps.emphasis_pass import EmphasisPassStep


def _scene(narration_text: str, *, text_card: str | None = None) -> Scene:
    return Scene(
        id="sc_01",
        order=0,
        title="t",
        narration_text=narration_text,
        duration_s=3.0,
        shots=[
            Shot(
                id="sh_01",
                order=0,
                intent=ShotIntent.EXPLAIN,
                duration_s=3.0,
                narration_span=(0, len(narration_text)),
                text_card=text_card,
            )
        ],
    )


def _timeline(narration_text: str, **metadata) -> Timeline:
    timeline = Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[_scene(narration_text)],
    )
    for key, value in metadata.items():
        setattr(timeline.metadata, key, value)
    return timeline


class _Store:
    def __init__(self, timeline: Timeline | None) -> None:
        self.timeline = timeline

    async def get_active(self, project_id: str) -> Timeline | None:
        return self.timeline

    async def append_version(self, project_id, produced_by, transform, owns=frozenset()):
        assert produced_by is ProducedBy.EMPHASIS_PASS
        assert self.timeline is not None
        self.timeline = transform(self.timeline.model_copy(deep=True))
        return self.timeline


def _ctx(timeline: Timeline | None) -> SimpleNamespace:
    store = _Store(timeline)
    return SimpleNamespace(
        project_id="p1",
        timeline_service=store,
        _store=store,
    )


async def test_retention_fast_with_a_pivot_word_is_not_satisfied_then_run_attaches():
    timeline = _timeline("bike. lekin kya Creta", render_style="retention_fast")
    ctx = _ctx(timeline)
    step = EmphasisPassStep()
    assert not await step.is_satisfied(ctx)
    result = await step.run(ctx)
    assert result.outcome == "ok"
    attached = ctx._store.timeline
    cue = attached.all_shots()[0].emphasis_cue
    assert cue is not None
    assert cue.device is EmphasisDevice.PIVOT
    assert cue.text == "लेकिन"
    assert cue.text_register == "hi"
    assert attached.metadata.emphasis_pass_attempted is True
    assert await step.is_satisfied(ctx)


async def test_other_styles_are_satisfied_and_run_writes_no_cue():
    timeline = _timeline("bike. lekin kya Creta", render_style="documentary_archival")
    ctx = _ctx(timeline)
    step = EmphasisPassStep()
    assert await step.is_satisfied(ctx)
    result = await step.run(ctx)
    assert result.outcome == "ok"
    assert ctx._store.timeline.all_shots()[0].emphasis_cue is None


async def test_unset_style_is_satisfied_no_cue():
    timeline = _timeline("bike. lekin kya Creta")  # render_style defaults None
    assert await EmphasisPassStep().is_satisfied(_ctx(timeline))


async def test_no_pivot_word_is_satisfied_no_cue():
    timeline = _timeline("every third SUV is a Creta", render_style="retention_fast")
    ctx = _ctx(timeline)
    step = EmphasisPassStep()
    assert await step.is_satisfied(ctx)
    assert timeline.all_shots()[0].emphasis_cue is None


async def test_already_attached_is_satisfied():
    timeline = _timeline("bike. lekin kya Creta", render_style="retention_fast")
    ctx = _ctx(timeline)
    step = EmphasisPassStep()
    await step.run(ctx)
    assert await step.is_satisfied(ctx)


async def test_no_active_timeline_is_satisfied():
    assert await EmphasisPassStep().is_satisfied(_ctx(None))


async def test_graphic_covering_the_pivot_word_ends_with_no_cue():
    """K3: detect uses the shared blocker, so a graphic on the turn is
    no pivot; run still stamps the attempt. Attach never writes the cue.
    """
    timeline = _timeline("bike. lekin kya Creta", render_style="retention_fast")
    timeline.all_shots()[0].picture_is_graphic = True
    ctx = _ctx(timeline)
    step = EmphasisPassStep()
    result = await step.run(ctx)
    assert result.outcome == "ok"
    assert ctx._store.timeline.all_shots()[0].emphasis_cue is None
    assert ctx._store.timeline.metadata.emphasis_pass_attempted is True


async def test_the_resolved_band_knobs_arrive_in_the_right_parameters(monkeypatch):
    """A swap at the call site would otherwise be silent (review 2026-09-09).

    `min_shot_gap` and `max_cues_per_minute` are both plain numbers and
    `min_shot_gap > 0` happily accepts 12.0, so passing 12.0 as the gap
    and 3 as the rate cap raises nothing and drops a different set of
    cues. Pin the values (and their types) as actually passed.
    """
    captured: dict[str, object] = {}
    real = emphasis_pass.enforce_emphasis_rules

    def _spy(timeline, *, min_shot_gap, max_cues_per_minute):
        captured["min_shot_gap"] = min_shot_gap
        captured["max_cues_per_minute"] = max_cues_per_minute
        return real(
            timeline,
            min_shot_gap=min_shot_gap,
            max_cues_per_minute=max_cues_per_minute,
        )

    monkeypatch.setattr(emphasis_pass, "enforce_emphasis_rules", _spy)
    ctx = _ctx(_timeline("bike. lekin kya Creta", render_style="retention_fast"))
    result = await EmphasisPassStep().run(ctx)
    assert result.outcome == "ok"
    assert captured == {"min_shot_gap": 3, "max_cues_per_minute": 12.0}
    # `3 == 3.0` and `12.0 == 12`, so equality alone would not catch a
    # swap of two numerically-equal knobs; the shapes differ.
    assert isinstance(captured["min_shot_gap"], int)
    assert isinstance(captured["max_cues_per_minute"], float)


async def test_narration_locked_is_skipped_so_a_resume_cannot_drop_audio():
    timeline = _timeline(
        "bike. lekin kya Creta",
        render_style="retention_fast",
        narration_locked=True,
    )
    ctx = _ctx(timeline)
    step = EmphasisPassStep()
    assert await step.is_satisfied(ctx)
    result = await step.run(ctx)
    assert result.outcome == "ok"
    assert ctx._store.timeline.all_shots()[0].emphasis_cue is None
