"""`EmphasisPassStep` — K9 LLM pass + K10 dry-run attach + K3.

DB-free: `is_satisfied` / `run` touch `ctx.timeline_service.get_active`
and `append_version`, so a stub context is enough. The LLM path injects
a fake planner; dry-run (the default) stays lexical.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.planners.emphasis.planner import EmphasisPlanner
from app.planners.emphasis.schemas import (
    EmphasisCuePlanOutput,
    EmphasisPlannerOutput,
    EmphasisValuePlanOutput,
)
from app.planners.fragments import split_narration_fragments
from app.schemas.timeline import (
    EmphasisCue,
    EmphasisDevice,
    EmphasisRegister,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.workflow.steps import emphasis_pass
from app.workflow.steps.emphasis_pass import EmphasisPassStep
from tests.unit.planners.helpers import FakePlanningProvider


@pytest.fixture(autouse=True)
def _lexical_dry_run(monkeypatch):
    """This env's DRY_RUN is False; lexical tests must not hit the LLM path."""
    monkeypatch.setattr(settings, "dry_run", True)

# Seven fragments, cues on shots 0 / 3 / 6 so K3's gap of 3 keeps all three.
_FILM_NARRATION = (
    "Hyundai Creta dikhti hai har gali mein. "
    "Pehli baat yeh har gali mein khadi hai. "
    "Doosri baat parking bhi isi se bhari hai. "
    "2025 mein 2 lakh models bikhe. "
    "Teesri baat resale strong hai. "
    "Fourth, waiting period lambi hai. "
    "Lekin kya yeh safest hai?"
)

class _StubLlm:
    async def insert(self, **kwargs):
        return None


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


def _film() -> Timeline:
    fragments = split_narration_fragments(_FILM_NARRATION)
    shots = [
        Shot(
            id=f"sc_01_sh_{fragment.index:02d}",
            order=fragment.index - 1,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.5,
            narration_span=(fragment.start, fragment.end),
        )
        for fragment in fragments
    ]
    timeline = Timeline(
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
                narration_text=_FILM_NARRATION,
                duration_s=sum(s.duration_s for s in shots),
                shots=shots,
            )
        ],
    )
    timeline.metadata.render_style = "retention_fast"
    return timeline


class _Store:
    def __init__(self, timeline: Timeline | None) -> None:
        self.timeline = timeline
        self.owns: frozenset[str] | None = None

    async def get_active(self, project_id: str) -> Timeline | None:
        return self.timeline

    async def append_version(self, project_id, produced_by, transform, owns=frozenset()):
        assert produced_by is ProducedBy.EMPHASIS_PASS
        assert self.timeline is not None
        self.owns = owns
        self.timeline = transform(self.timeline.model_copy(deep=True))
        return self.timeline


def _ctx(timeline: Timeline | None) -> SimpleNamespace:
    store = _Store(timeline)
    return SimpleNamespace(
        project_id="p1",
        timeline_service=store,
        session=None,
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


async def test_no_pivot_word_is_not_satisfied():
    """K9 must still author stamps/counters when there is no turn word."""
    timeline = _timeline("every third SUV is a Creta", render_style="retention_fast")
    ctx = _ctx(timeline)
    step = EmphasisPassStep()
    assert not await step.is_satisfied(ctx)
    result = await step.run(ctx)
    assert result.outcome == "ok"
    assert ctx._store.timeline.all_shots()[0].emphasis_cue is None
    assert ctx._store.timeline.metadata.emphasis_pass_attempted is True
    assert await step.is_satisfied(ctx)


async def test_existing_pivot_cue_without_attempted_stamp_is_not_satisfied():
    """The K10 stub treated 'already has a pivot' as done. K9 must not."""
    timeline = _timeline("bike. lekin kya Creta", render_style="retention_fast")
    timeline.all_shots()[0].emphasis_cue = EmphasisCue(
        device=EmphasisDevice.PIVOT,
        anchor_fragment=1,
        text="लेकिन",
        text_register=EmphasisRegister.HI,
    )
    assert not await EmphasisPassStep().is_satisfied(_ctx(timeline))


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


def _planner_output() -> EmphasisPlannerOutput:
    return EmphasisPlannerOutput(
        cues=[
            EmphasisCuePlanOutput(
                shot_id="sc_01_sh_01",
                device="stamp",
                anchor_fragment=1,
                text="Hyundai",
                values=[],
                replaced_text="",
            ),
            EmphasisCuePlanOutput(
                shot_id="sc_01_sh_04",
                device="counter",
                anchor_fragment=4,
                text="SOLD IN A YEAR",
                values=[EmphasisValuePlanOutput(value=200000, unit="+", cited_fragment=4)],
                replaced_text="",
            ),
            EmphasisCuePlanOutput(
                shot_id="sc_01_sh_07",
                device="pivot",
                anchor_fragment=7,
                text="लेकिन",
                values=[],
                replaced_text="",
            ),
            EmphasisCuePlanOutput(
                shot_id="sc_01_sh_02",
                device="correction",
                anchor_fragment=2,
                text="claim",
                values=[],
                replaced_text="truth",
            ),
            EmphasisCuePlanOutput(
                shot_id="sc_01_sh_05",
                device="counter",
                anchor_fragment=5,
                text="FAKE",
                values=[EmphasisValuePlanOutput(value=999999, unit="", cited_fragment=5)],
                replaced_text="",
            ),
        ],
        accent="#00C8FF",
        pivot_ground="#5A00A8",
    )


async def test_real_run_maps_canned_cues_drops_correction_and_uncitable(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    provider = FakePlanningProvider(responses=[_planner_output()])
    planner = EmphasisPlanner(provider, _StubLlm())  # type: ignore[arg-type]
    ctx = _ctx(_film())
    ctx.project_id = str(uuid.uuid4())
    result = await EmphasisPassStep(planner=planner).run(ctx)
    assert result.outcome == "ok"
    shots = {shot.id: shot for shot in ctx._store.timeline.all_shots()}
    assert shots["sc_01_sh_01"].emphasis_cue.device is EmphasisDevice.STAMP
    assert shots["sc_01_sh_01"].emphasis_cue.text_register == "en"
    assert shots["sc_01_sh_04"].emphasis_cue.device is EmphasisDevice.COUNTER
    assert shots["sc_01_sh_04"].emphasis_cue.text_register == "en"
    assert shots["sc_01_sh_07"].emphasis_cue.device is EmphasisDevice.PIVOT
    assert shots["sc_01_sh_02"].emphasis_cue is None
    assert shots["sc_01_sh_05"].emphasis_cue is None
    palette = ctx._store.timeline.metadata.emphasis_palette
    assert palette is not None
    assert palette.accent == "#00C8FF"
    assert ctx._store.timeline.metadata.emphasis_pass_attempted is True
    assert ctx._store.owns is not None
    assert "metadata.emphasis_palette" in ctx._store.owns
