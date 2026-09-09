"""K7-lite compositor seam. No Chromium — the remotion invoke is stubbed."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.renderer.compositor import (
    PIVOT_HOLD_S,
    OverlayCue,
    _overlay_props,
    collect_pivot_overlay_cues,
    emphasis_cue_content_hash,
    overlay_input_hash,
    pivot_band,
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
    cues = collect_pivot_overlay_cues(
        _timeline_with_pivot(offset_s=0.4), fps=30, width=720, height=1280
    )
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
    assert collect_pivot_overlay_cues(timeline, fps=30, width=720, height=1280) == []


def test_hold_is_clamped_to_the_remaining_shot():
    cues = collect_pivot_overlay_cues(
        _timeline_with_pivot(offset_s=1.7, duration_s=2.0),
        fps=30,
        width=720,
        height=1280,
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


# --------------------------------------------------------------------------
# Review finding 3 (2026-09-09): the band is resolved in Python, travels
# through the props, and `Pivot.tsx` draws from it. These tests pin the
# CONTRACT — the shape and the numbers the TSX reads — because that is
# the half of the mirror Python can still assert on. The drift itself is
# no longer possible: the TSX holds no production layout constants to
# drift away from. What is left to protect is the props key names, which
# a rename here would break silently on the TypeScript side.


def test_band_is_resolved_python_side_and_matches_the_measured_box():
    cues = collect_pivot_overlay_cues(
        _timeline_with_pivot(offset_s=0.4), fps=30, width=720, height=1280
    )
    band = cues[0].band
    assert band is not None
    # The reference-canvas geometry every K4 luma measurement was taken
    # through: top 380, height 132 + 2*18, full width.
    assert (band.left, band.top, band.width, band.height) == (0, 380, 720, 168)
    assert (band.font_size, band.pad) == (132, 18)
    assert band.box_on(720, 1280) == (0, 380, 720, 548)
    assert band == pivot_band(720, 1280)


def test_band_scales_with_the_canvas_and_refuses_degenerate_ones():
    tall = pivot_band(1080, 1920)
    assert tall is not None
    assert tall.font_size == round(132 * 1080 / 720)
    assert tall.top == round(380 * 1920 / 1280)
    assert pivot_band(0, 1280) is None
    assert pivot_band(720, 0) is None


def test_band_box_on_a_differently_shaped_plate_keeps_the_canvas_fraction():
    """`shot_images` holds the raw asset, not a canvas-sized frame. The
    band must map by its fraction of the canvas; recomputing it from the
    asset's own dimensions made the band height wrong on any asset whose
    aspect differed from the canvas."""
    band = pivot_band(720, 1280)
    assert band is not None
    box = band.box_on(1920, 1080)
    assert box is not None
    x0, y0, x1, y1 = box
    assert (x0, x1) == (0, 1920)
    assert y0 == round(380 / 1280 * 1080)
    # Endpoints are rounded independently, so the height can land one
    # pixel off the rounded fraction. That is the right trade: y0 and y1
    # each match the canvas fraction exactly.
    assert abs((y1 - y0) - 168 / 1280 * 1080) <= 1
    assert band.box_on(0, 0) is None


def test_overlay_props_carry_the_band_in_the_shape_the_tsx_reads():
    cues = collect_pivot_overlay_cues(
        _timeline_with_pivot(offset_s=0.4), fps=30, width=720, height=1280
    )
    props = _overlay_props(cues, width=720, height=1280, fps=30, duration_in_frames=90)
    band = props["cues"][0]["band"]
    # camelCase, and exactly these keys: `PivotBandProps` in Pivot.tsx.
    assert set(band) == {"left", "top", "width", "fontSize", "pad"}
    assert band == {"left": 0, "top": 380, "width": 720, "fontSize": 132, "pad": 18}
    # `height` stays out of the props on purpose — see
    # `PivotBand.as_props` for why the drawn and measured heights are
    # allowed to differ.
    assert "height" not in band


def test_a_moved_band_misses_the_overlay_cache_and_the_render_fingerprint():
    """The band's constants are CODE. Editing them moves the drawn band,
    so both caches must miss — otherwise a cached final.mp4 is served
    with the band in its old place and nothing errors (the plan's own
    fingerprint warning)."""
    base = dict(width=720, height=1280, fps=30, duration_in_frames=90, font_hash="abc")
    cue = OverlayCue(
        device="pivot",
        text="लेकिन",
        text_register="hi",
        offset_s=0.4,
        start_frame=12,
        end_frame=39,
        shot_id="sh_01",
        band=pivot_band(720, 1280),
    )
    moved = replace(cue, band=replace(cue.band, top=300))
    assert emphasis_cue_content_hash([cue]) != emphasis_cue_content_hash([moved])
    assert overlay_input_hash(cues=[cue], **base) != overlay_input_hash(
        cues=[moved], **base
    )
    bandless = replace(cue, band=None)
    assert emphasis_cue_content_hash([cue]) != emphasis_cue_content_hash([bandless])
    assert overlay_input_hash(cues=[cue], **base) != overlay_input_hash(
        cues=[bandless], **base
    )
