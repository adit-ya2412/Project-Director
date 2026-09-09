"""K7-lite compositor seam. No Chromium — the remotion invoke is stubbed."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.renderer.compositor import (
    PIVOT_HOLD_S,
    OverlayCue,
    collect_pivot_overlay_cues,
    emphasis_cue_content_hash,
    overlay_input_hash,
    render_or_reuse_emphasis_overlay,
)
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


def _timeline_with_pivot(*, offset_s: float = 0.4, duration_s: float = 2.0) -> Timeline:
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        narration_span=(0, 20),
        emphasis_cue=EmphasisCue(
            device=EmphasisDevice.PIVOT,
            anchor_fragment=1,
            text="लेकिन",
            text_register=EmphasisRegister.HI,
            offset_s=offset_s,
        ),
    )
    scene = Scene(id="sc_01", order=0, title="t", duration_s=duration_s, shots=[shot])
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.NARRATION,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


def test_collect_pivot_uses_resolved_offset_and_spike_hold():
    cues = collect_pivot_overlay_cues(_timeline_with_pivot(offset_s=0.4), fps=30)
    assert len(cues) == 1
    cue = cues[0]
    assert cue.device == "pivot"
    assert cue.text == "लेकिन"
    assert cue.text_register == "hi"
    assert cue.offset_s == 0.4
    assert cue.shot_id == "sh_01"
    assert cue.treatment == "slab"
    assert cue.start_frame == round(0.4 * 30)
    assert cue.end_frame - cue.start_frame == round(PIVOT_HOLD_S * 30)
    assert PIVOT_HOLD_S == 0.91


def test_collect_ignores_unknown_devices_and_empty_timelines():
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=1.0)
    scene = Scene(id="sc_01", order=0, title="t", duration_s=1.0, shots=[shot])
    timeline = Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )
    assert collect_pivot_overlay_cues(timeline, fps=30) == []


def test_hold_is_clamped_to_the_remaining_shot():
    cues = collect_pivot_overlay_cues(
        _timeline_with_pivot(offset_s=1.7, duration_s=2.0), fps=30
    )
    assert len(cues) == 1
    # 0.3s remaining, not the full 0.91s hold.
    assert cues[0].end_frame - cues[0].start_frame == round(0.3 * 30)


async def test_cache_hit_on_second_call_does_not_reinvoke(tmp_path: Path):
    calls: list[Path] = []

    async def fake_invoke(props_path: Path, output_path: Path) -> None:
        calls.append(output_path)
        output_path.write_bytes(b"fake-prores")

    cues = [
        OverlayCue(
            device="pivot",
            text="लेकिन",
            text_register="hi",
            offset_s=0.4,
            start_frame=12,
            end_frame=39,
        )
    ]
    kwargs = dict(
        project_id="proj-1",
        cues=cues,
        width=720,
        height=1280,
        fps=30,
        duration_in_frames=90,
        storage_root=tmp_path,
        invoke=fake_invoke,
    )
    first = await render_or_reuse_emphasis_overlay(**kwargs)
    second = await render_or_reuse_emphasis_overlay(**kwargs)
    assert first == second
    assert first.exists()
    assert first.read_bytes() == b"fake-prores"
    assert len(calls) == 1


def test_overlay_input_hash_changes_when_a_cue_changes():
    font = "abc"
    base = dict(width=720, height=1280, fps=30, duration_in_frames=90, font_hash=font)
    a = [
        OverlayCue(
            device="pivot",
            text="लेकिन",
            text_register="hi",
            offset_s=0.4,
            start_frame=12,
            end_frame=39,
        )
    ]
    b = [
        OverlayCue(
            device="pivot",
            text="मगर",
            text_register="hi",
            offset_s=0.4,
            start_frame=12,
            end_frame=39,
        )
    ]
    assert overlay_input_hash(cues=a, **base) != overlay_input_hash(cues=b, **base)


def test_emphasis_cue_content_hash_is_none_when_empty():
    assert emphasis_cue_content_hash([]) is None
    one = [
        OverlayCue(
            device="pivot",
            text="लेकिन",
            text_register="hi",
            offset_s=0.4,
            start_frame=12,
            end_frame=39,
        )
    ]
    assert emphasis_cue_content_hash(one) is not None
    shifted = [
        OverlayCue(
            device="pivot",
            text="लेकिन",
            text_register="hi",
            offset_s=1.2,
            start_frame=36,
            end_frame=63,
        )
    ]
    assert emphasis_cue_content_hash(one) != emphasis_cue_content_hash(shifted)


def test_treatment_change_misses_emphasis_and_overlay_hashes():
    """K4: a plate-driven treatment flip must rerender, not reuse the
    cached overlay / final.mp4. cue_list_hash remains captions."""
    font = "abc"
    base = dict(width=720, height=1280, fps=30, duration_in_frames=90, font_hash=font)
    slab = OverlayCue(
        device="pivot",
        text="लेकिन",
        text_register="hi",
        offset_s=0.4,
        start_frame=12,
        end_frame=39,
        shot_id="sh_01",
        treatment="slab",
    )
    light = replace(slab, treatment="light")
    dark = replace(slab, treatment="dark")
    assert emphasis_cue_content_hash([slab]) != emphasis_cue_content_hash([light])
    assert emphasis_cue_content_hash([slab]) != emphasis_cue_content_hash([dark])
    assert overlay_input_hash(cues=[slab], **base) != overlay_input_hash(
        cues=[light], **base
    )
    assert overlay_input_hash(cues=[slab], **base) != overlay_input_hash(
        cues=[dark], **base
    )
