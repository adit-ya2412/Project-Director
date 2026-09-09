"""K7-lite compositor seam. No Chromium — the remotion invoke is stubbed."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.renderer.compositor import (
    COUNTER_HOLD_S,
    PIVOT_HOLD_S,
    STAMP_HOLD_S,
    OverlayCue,
    OverlayValue,
    _overlay_props,
    collect_emphasis_overlay_cues,
    counter_band,
    emphasis_cue_content_hash,
    overlay_input_hash,
    pivot_band,
    render_or_reuse_emphasis_overlay,
    stamp_band,
)
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
    cues = collect_emphasis_overlay_cues(
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


def _timeline_from_shots(shots: list[Shot]) -> Timeline:
    duration_s = sum(shot.duration_s for shot in shots)
    scene = Scene(id="sc_01", order=0, title="t", duration_s=duration_s, shots=shots)
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.NARRATION,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


def _cue(
    device: EmphasisDevice,
    *,
    text: str,
    text_register: EmphasisRegister = EmphasisRegister.HI,
    offset_s: float = 0.0,
    values: list[EmphasisValue] | None = None,
) -> EmphasisCue:
    return EmphasisCue(
        device=device,
        anchor_fragment=1,
        text=text,
        text_register=text_register,
        offset_s=offset_s,
        values=values or [],
    )


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
    assert collect_emphasis_overlay_cues(timeline, fps=30, width=720, height=1280) == []


def test_hold_is_clamped_to_the_remaining_shot():
    cues = collect_emphasis_overlay_cues(
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
    cues = collect_emphasis_overlay_cues(
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
    cues = collect_emphasis_overlay_cues(
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
    assert props["cues"][0]["values"] == []


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


# --------------------------------------------------------------------------
# K11: stamp + counter collection, holds, values, hashes, props contract.


def test_collect_emits_stamp_and_counter_not_only_pivot():
    """Stamp is not an 'unknown device'. Correction/question still are."""
    shots = [
        Shot(
            id="sh_pivot",
            order=0,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            emphasis_cue=_cue(EmphasisDevice.PIVOT, text="लेकिन"),
        ),
        Shot(
            id="sh_stamp",
            order=1,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            emphasis_cue=_cue(
                EmphasisDevice.STAMP, text="2025", text_register=EmphasisRegister.EN
            ),
        ),
        Shot(
            id="sh_counter",
            order=2,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            emphasis_cue=_cue(
                EmphasisDevice.COUNTER,
                text="SOLD IN A YEAR",
                text_register=EmphasisRegister.EN,
                values=[EmphasisValue(value=200000, unit="lakh", cited_fragment=4)],
            ),
        ),
        Shot(
            id="sh_correction",
            order=3,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            emphasis_cue=_cue(EmphasisDevice.CORRECTION, text="झूठ"),
        ),
        Shot(
            id="sh_question",
            order=4,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            emphasis_cue=_cue(
                EmphasisDevice.QUESTION, text="REALLY?", text_register=EmphasisRegister.EN
            ),
        ),
    ]
    cues = collect_emphasis_overlay_cues(
        _timeline_from_shots(shots), fps=30, width=720, height=1280
    )
    assert [cue.device for cue in cues] == ["pivot", "stamp", "counter"]
    stamp = cues[1]
    assert stamp.text == "2025"
    assert stamp.band is not None
    assert (stamp.band.left, stamp.band.top, stamp.band.width) == (0, 320, 720)
    assert stamp.band.font_size == 190
    assert stamp.values == ()
    counter = cues[2]
    assert counter.values == (OverlayValue(value=200000, unit="lakh", cited_fragment=4),)
    assert counter.band is not None
    assert (counter.band.left, counter.band.top, counter.band.width) == (150, 300, 420)
    assert counter.band.font_size == 116


def test_counter_hold_is_not_the_pivot_hold():
    """Pinned from the spike windows: year 2.69–3.55 = 0.86s, counter
    3.60–4.90 = 1.30s, pivot 4.94–5.85 = 0.91s. A shared hold would
    clip the counter or linger the stamp."""
    assert STAMP_HOLD_S == 0.86
    assert COUNTER_HOLD_S == 1.30
    assert PIVOT_HOLD_S == 0.91
    assert COUNTER_HOLD_S != PIVOT_HOLD_S
    assert STAMP_HOLD_S != PIVOT_HOLD_S
    stamp = collect_emphasis_overlay_cues(
        _timeline_from_shots(
            [
                Shot(
                    id="sh_stamp",
                    order=0,
                    intent=ShotIntent.EXPLAIN,
                    duration_s=3.0,
                    emphasis_cue=_cue(
                        EmphasisDevice.STAMP,
                        text="2025",
                        text_register=EmphasisRegister.EN,
                    ),
                )
            ]
        ),
        fps=30,
        width=720,
        height=1280,
    )[0]
    counter = collect_emphasis_overlay_cues(
        _timeline_from_shots(
            [
                Shot(
                    id="sh_counter",
                    order=0,
                    intent=ShotIntent.EXPLAIN,
                    duration_s=3.0,
                    emphasis_cue=_cue(
                        EmphasisDevice.COUNTER,
                        text="lakh",
                        text_register=EmphasisRegister.EN,
                        values=[EmphasisValue(value=200000, unit="lakh", cited_fragment=1)],
                    ),
                )
            ]
        ),
        fps=30,
        width=720,
        height=1280,
    )[0]
    assert stamp.end_frame - stamp.start_frame == round(STAMP_HOLD_S * 30)
    assert counter.end_frame - counter.start_frame == round(COUNTER_HOLD_S * 30)


def test_counter_with_empty_values_is_dropped(caplog):
    """A counter with no target is a planner bug. Drawing 0→0 is worse
    than dropping it; do not crash the render."""
    shots = [
        Shot(
            id="sh_counter",
            order=0,
            intent=ShotIntent.EXPLAIN,
            duration_s=3.0,
            emphasis_cue=_cue(
                EmphasisDevice.COUNTER,
                text="lakh",
                text_register=EmphasisRegister.EN,
                values=[],
            ),
        )
    ]
    with caplog.at_level("INFO"):
        cues = collect_emphasis_overlay_cues(
            _timeline_from_shots(shots), fps=30, width=720, height=1280
        )
    assert cues == []
    assert any(
        record.message == "compositor.counter_skipped_empty_values"
        for record in caplog.records
    )


def test_stamp_and_counter_round_trip_into_overlay_props():
    stamp = OverlayCue(
        device="stamp",
        text="2025",
        text_register="en",
        offset_s=0.0,
        start_frame=81,
        end_frame=107,
        shot_id="sh_stamp",
        treatment="light",
        band=stamp_band(720, 1280),
        values=(),
    )
    counter = OverlayCue(
        device="counter",
        text="SOLD IN A YEAR",
        text_register="en",
        offset_s=0.0,
        start_frame=108,
        end_frame=147,
        shot_id="sh_counter",
        treatment="slab",
        band=counter_band(720, 1280),
        values=(OverlayValue(value=200000, unit="lakh", cited_fragment=4),),
    )
    props = _overlay_props(
        [stamp, counter], width=720, height=1280, fps=30, duration_in_frames=210
    )
    stamp_props, counter_props = props["cues"]
    assert stamp_props["device"] == "stamp"
    assert stamp_props["treatment"] == "light"
    assert stamp_props["values"] == []
    assert stamp_props["band"] == {
        "left": 0,
        "top": 320,
        "width": 720,
        "fontSize": 190,
        "pad": 14,
    }
    assert counter_props["device"] == "counter"
    assert counter_props["treatment"] == "slab"
    assert counter_props["values"] == [
        {"value": 200000, "unit": "lakh", "citedFragment": 4}
    ]
    assert counter_props["band"] == {
        "left": 150,
        "top": 300,
        "width": 420,
        "fontSize": 116,
        "pad": 16,
    }


def test_target_number_change_misses_both_hashes():
    """Load-bearing: editing a counter's target must not serve a cached
    final.mp4 that still counts to the old figure."""
    base = dict(width=720, height=1280, fps=30, duration_in_frames=90, font_hash="abc")
    cue = OverlayCue(
        device="counter",
        text="lakh",
        text_register="en",
        offset_s=0.0,
        start_frame=0,
        end_frame=39,
        shot_id="sh_01",
        treatment="slab",
        band=counter_band(720, 1280),
        values=(OverlayValue(value=200000, unit="lakh", cited_fragment=4),),
    )
    other_value = replace(
        cue, values=(OverlayValue(value=300000, unit="lakh", cited_fragment=4),)
    )
    other_unit = replace(
        cue, values=(OverlayValue(value=200000, unit=None, cited_fragment=4),)
    )
    other_cite = replace(
        cue, values=(OverlayValue(value=200000, unit="lakh", cited_fragment=5),)
    )
    assert emphasis_cue_content_hash([cue]) != emphasis_cue_content_hash([other_value])
    assert overlay_input_hash(cues=[cue], **base) != overlay_input_hash(
        cues=[other_value], **base
    )
    assert emphasis_cue_content_hash([cue]) != emphasis_cue_content_hash([other_unit])
    assert overlay_input_hash(cues=[cue], **base) != overlay_input_hash(
        cues=[other_unit], **base
    )
    assert emphasis_cue_content_hash([cue]) != emphasis_cue_content_hash([other_cite])
    assert overlay_input_hash(cues=[cue], **base) != overlay_input_hash(
        cues=[other_cite], **base
    )


def test_stamp_vs_pivot_device_misses_both_hashes():
    """A cached pivot overlay must not serve a stamp of the same word."""
    base = dict(width=720, height=1280, fps=30, duration_in_frames=90, font_hash="abc")
    pivot = OverlayCue(
        device="pivot",
        text="2025",
        text_register="en",
        offset_s=0.0,
        start_frame=0,
        end_frame=27,
        shot_id="sh_01",
        treatment="slab",
        band=pivot_band(720, 1280),
    )
    stamp = replace(pivot, device="stamp", band=stamp_band(720, 1280))
    assert emphasis_cue_content_hash([pivot]) != emphasis_cue_content_hash([stamp])
    assert overlay_input_hash(cues=[pivot], **base) != overlay_input_hash(
        cues=[stamp], **base
    )
