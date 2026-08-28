"""`RomanizeCaptionsStep.is_satisfied` — the skip logic, pinned.

This is the most dangerous piece of the caption romanization feature
(caption_romanization.md §3.2 / §8.6): it decides whether a resume
appends a timeline version to a project that may already be narrated
and approved. Every clause is load-bearing, and the
`narration_locked` one existed only as prose in a docstring.

DB-free by construction: `is_satisfied` touches nothing but
`ctx.timeline_service.get_active`, so a stub context is enough and §4's
no-database rule is not in the way. Run with `--noconftest`.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.timeline import (
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.workflow.steps.romanize_captions import RomanizeCaptionsStep

_DEVANAGARI = "एक Indian guru जिसके पास 90 Rolls-Royce थीं।"
_ROMANIZED = "ek Indian guru jiske paas 90 Rolls-Royce theen."
_LATIN = "One Indian guru who owned 90 Rolls-Royces."


def _scene(scene_id: str, narration_text: str, caption_text: str | None = None) -> Scene:
    return Scene(
        id=scene_id,
        order=0,
        title="t",
        narration_text=narration_text,
        duration_s=3.0,
        caption_text=caption_text,
        shots=[Shot(id=f"{scene_id}_sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)],
    )


def _timeline(scenes: list[Scene], **metadata) -> Timeline:
    timeline = Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.SCENE_PLANNER,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=scenes,
    )
    for key, value in metadata.items():
        setattr(timeline.metadata, key, value)
    return timeline


@pytest.fixture(autouse=True)
def _real_run(monkeypatch):
    """`is_satisfied` short-circuits to True under DRY_RUN, and
    `settings.dry_run` comes from the repo `.env`. Pin it so every
    assertion below describes the step's real-run logic rather than
    whatever the developer's environment happens to be set to."""
    monkeypatch.setattr(settings, "dry_run", False)


def _ctx(timeline: Timeline | None) -> SimpleNamespace:
    """The whole surface `is_satisfied` uses: one awaitable lookup."""

    async def get_active(project_id: str) -> Timeline | None:
        return timeline

    return SimpleNamespace(
        project_id="p1",
        timeline_service=SimpleNamespace(get_active=get_active),
    )


async def test_attempted_is_satisfied_even_with_a_scene_the_validator_could_not_romanize():
    # The partial-failure guard (§8.3). sc_01 came back clean; sc_02's
    # candidate failed the word-count validator, so it keeps
    # caption_text=None with its Devanagari intact and
    # `needs_romanization` stays True for it forever. Without the
    # `attempted` stamp every later resume would re-run the LLM over the
    # whole timeline and append another no-op version.
    timeline = _timeline(
        [
            _scene("sc_01", _DEVANAGARI, _ROMANIZED),
            _scene("sc_02", _DEVANAGARI, None),
        ],
        caption_romanization_attempted=True,
    )
    assert await RomanizeCaptionsStep().is_satisfied(_ctx(timeline))


async def test_latin_only_project_is_satisfied_without_calling_the_llm():
    # No Devanagari anywhere, so there is nothing a display string could
    # improve. English-script projects must never pay for this step.
    timeline = _timeline([_scene("sc_01", _LATIN)])
    assert await RomanizeCaptionsStep().is_satisfied(_ctx(timeline))


async def test_narration_locked_devanagari_project_is_skipped_not_romanized():
    # THE LANDMINE. This project predates the step: it has Devanagari,
    # has never been attempted, and would genuinely benefit — but it is
    # already through NarrationStep. Appending a version here is
    # destructive, not cosmetic: `append_version` always writes
    # status=DRAFT (re-opening the approval gate) and, unless the new
    # version is re-stamped produced_by=NARRATION,
    # `render.py::_resolve_narration_rows` returns None and the video
    # ships SILENT with no error anywhere. So a DEFAULT_PIPELINE resume
    # must report satisfied and do nothing; these projects are romanized
    # through `backfill_caption_romanization`, which re-stamps NARRATION
    # and re-approves.
    timeline = _timeline(
        [_scene("sc_01", _DEVANAGARI)],
        narration_locked=True,
        caption_romanization_attempted=None,
    )
    assert await RomanizeCaptionsStep().is_satisfied(_ctx(timeline))


async def test_fresh_devanagari_project_is_not_satisfied_so_the_step_runs():
    # The case the step exists for: mixed-script narration, no display
    # text, no narration yet. Nothing here is at risk from appending a
    # version, so the pass must actually run.
    timeline = _timeline(
        [_scene("sc_01", _DEVANAGARI)],
        narration_locked=False,
        caption_romanization_attempted=None,
    )
    assert not await RomanizeCaptionsStep().is_satisfied(_ctx(timeline))


async def test_no_active_timeline_is_satisfied():
    # Matches the early return: there is nothing to inspect, and `run`
    # would only fail the step. Leave it to whichever step owns creating
    # the timeline.
    assert await RomanizeCaptionsStep().is_satisfied(_ctx(None))


async def test_dry_run_reports_satisfied_so_render_only_is_not_blocked(monkeypatch):
    # RV-R3. Under DRY_RUN the pass is not applicable, but reporting
    # "not done yet" is not a harmless way to say so:
    # `render_precondition_gap` walks DEFAULT_PIPELINE and returns the
    # FIRST step reporting unsatisfied, which `render_only` turns into a
    # 409. A step that could never report satisfied under DRY_RUN would
    # block render-only forever for every dry-run Devanagari project.
    monkeypatch.setattr(settings, "dry_run", True)
    timeline = _timeline([_scene("sc_01", _DEVANAGARI)])
    assert await RomanizeCaptionsStep().is_satisfied(_ctx(timeline))


async def test_dry_run_skip_is_live_not_stored_so_a_real_run_still_romanizes(monkeypatch):
    # The reason the DRY_RUN skip reads `settings` instead of stamping
    # `caption_romanization_attempted`: the SAME timeline, untouched,
    # must go back to needing the pass the moment DRY_RUN is off. A
    # stored stamp would have locked this project out permanently.
    timeline = _timeline([_scene("sc_01", _DEVANAGARI)])
    step = RomanizeCaptionsStep()

    monkeypatch.setattr(settings, "dry_run", True)
    assert await step.is_satisfied(_ctx(timeline))

    monkeypatch.setattr(settings, "dry_run", False)
    assert not await step.is_satisfied(_ctx(timeline))
    assert timeline.metadata.caption_romanization_attempted is None
