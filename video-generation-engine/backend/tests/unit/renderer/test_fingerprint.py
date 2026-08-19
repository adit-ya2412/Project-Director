"""`app/renderer/fingerprint.py` - pure, no ffmpeg/DB needed. Proves the
fingerprint is deterministic and genuinely sensitive to every real input
it's supposed to cover - a fingerprint that didn't change when narration
or music did would silently serve a stale render as if I5 held when it
didn't.
"""

from datetime import UTC, datetime

from app.renderer.fingerprint import (
    compute_render_fingerprint,
    compute_run_fingerprint,
    compute_shot_stream_fingerprint,
)
from app.renderer.slideshow import RenderSettings
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
    Transition,
    TransitionType,
)

_SETTINGS = RenderSettings(width=720, height=1280, fps=30, pixel_format="yuv420p")


def _timeline(shot_prompt: str = "a shot") -> Timeline:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt=shot_prompt)
    scene = Scene(id="sc_01", order=0, title="Scene", duration_s=3.0, shots=[shot])
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


def _fingerprint(**overrides) -> str:
    kwargs = {
        "timeline": _timeline(),
        "asset_content_hashes": ["hash-a", "hash-b"],
        "narration_content_hashes": ["narr-1"],
        "music_content_hash": "music-1",
        "render_settings": _SETTINGS,
        "music_bed_gain_db": -14.0,
        "music_duck_gain_db": -20.0,
        "burn_captions": False,
        "caption_font_hash": None,
        "cue_list_hash": None,
        "watermark_enabled": False,
        "watermark_asset_hash": None,
        "watermark_params_hash": None,
        "burn_text_cards": False,
        "text_card_font_hash": None,
        "ffmpeg_version": "ffmpeg version 9.0",
    }
    kwargs.update(overrides)
    return compute_render_fingerprint(**kwargs)


def test_identical_inputs_produce_identical_fingerprints():
    assert _fingerprint() == _fingerprint()


def test_approved_scenes_do_not_change_the_fingerprint():
    """R-C6: review-record click order is not a render input."""
    empty = _timeline()
    order_a = _timeline()
    order_a.metadata.approved_scenes = ["sc_01", "sc_02"]
    order_b = _timeline()
    order_b.metadata.approved_scenes = ["sc_02", "sc_01"]
    assert (
        _fingerprint(timeline=empty)
        == _fingerprint(timeline=order_a)
        == _fingerprint(timeline=order_b)
    )


def test_grade_style_still_changes_the_fingerprint():
    """R-C6's nested exclusion must not drop `grade_style` (parent R6)."""
    styled = _timeline()
    styled.metadata.grade_style = "retention_fast"
    assert _fingerprint(timeline=styled) != _fingerprint()


def test_asset_content_hash_order_does_not_matter():
    """Sorted internally (I5) - a binding resolution order difference
    must never change the fingerprint."""
    assert _fingerprint(asset_content_hashes=["hash-a", "hash-b"]) == _fingerprint(
        asset_content_hashes=["hash-b", "hash-a"]
    )


def test_different_timeline_content_changes_the_fingerprint():
    assert _fingerprint(timeline=_timeline("a different shot")) != _fingerprint()


def test_different_asset_content_changes_the_fingerprint():
    assert _fingerprint(asset_content_hashes=["hash-a", "hash-c"]) != _fingerprint()


def test_different_narration_changes_the_fingerprint():
    assert _fingerprint(narration_content_hashes=["narr-2"]) != _fingerprint()


def test_no_narration_changes_the_fingerprint():
    assert _fingerprint(narration_content_hashes=[]) != _fingerprint()


def test_different_music_changes_the_fingerprint():
    assert _fingerprint(music_content_hash="music-2") != _fingerprint()


def test_no_music_changes_the_fingerprint():
    assert _fingerprint(music_content_hash=None) != _fingerprint()


def test_different_render_dimensions_change_the_fingerprint():
    """The draft/final collision guard (M8 step 6) - width/height are
    part of the render settings hashed in, so the two modes can never
    share a fingerprint even for byte-identical Timeline content."""
    draft_settings = RenderSettings(width=480, height=854, fps=30, pixel_format="yuv420p")
    assert _fingerprint(render_settings=draft_settings) != _fingerprint()


def test_different_fps_changes_the_fingerprint():
    other = RenderSettings(width=720, height=1280, fps=24, pixel_format="yuv420p")
    assert _fingerprint(render_settings=other) != _fingerprint()


def test_different_ffmpeg_version_changes_the_fingerprint():
    assert _fingerprint(ffmpeg_version="ffmpeg version 8.0") != _fingerprint()


def test_different_bed_gain_changes_the_fingerprint():
    """R2: `music_bed_gain_db` is read from config at mux time, not from
    the Timeline - before this fix nothing here caught a change to it at
    all, so raising the bed gain and re-rendering silently served the
    OLD, quieter cached bytes back."""
    assert _fingerprint(music_bed_gain_db=-8.0) != _fingerprint()


def test_different_duck_gain_changes_the_fingerprint():
    """R2, the other half of the same defect."""
    assert _fingerprint(music_duck_gain_db=-26.0) != _fingerprint()


def test_burn_captions_toggle_changes_the_fingerprint():
    """A caption-off and caption-on render of the identical Timeline must
    never collide on one cache entry (docs/14_Captions_Plan.md §6/§8.5)."""
    assert _fingerprint(burn_captions=True) != _fingerprint(burn_captions=False)


def test_different_caption_font_changes_the_fingerprint():
    """Swapping the vendored font file must invalidate the cache even
    though nothing else about the render changed."""
    assert _fingerprint(burn_captions=True, caption_font_hash="font-hash-a") != _fingerprint(
        burn_captions=True, caption_font_hash="font-hash-b"
    )


def test_different_cue_list_changes_the_fingerprint():
    """Covers script edits, re-narration with a different voice, and any
    segmentation-rule change in one value (doc §6) - none of which are
    visible to `narration_content_hashes` (that hashes the AUDIO, not the
    derived cue list)."""
    assert _fingerprint(burn_captions=True, cue_list_hash="cues-a") != _fingerprint(
        burn_captions=True, cue_list_hash="cues-b"
    )


def test_watermark_toggle_changes_the_fingerprint():
    """A watermark-off and watermark-on render of the identical Timeline
    must never collide on one cache entry (watermark plan §4)."""
    assert _fingerprint(watermark_enabled=True) != _fingerprint(watermark_enabled=False)


def test_different_watermark_asset_changes_the_fingerprint():
    """Swapping the vendored logo file must invalidate the cache even
    though nothing else about the render changed - the exact R2 shape,
    applied to the watermark instead of the music gains."""
    assert _fingerprint(watermark_enabled=True, watermark_asset_hash="logo-hash-a") != _fingerprint(
        watermark_enabled=True, watermark_asset_hash="logo-hash-b"
    )


def test_different_watermark_params_changes_the_fingerprint():
    """Covers position/margin/width/opacity changes in one value - a
    watermark moved from bottom-right to top-right must invalidate the
    cache even though the logo file itself didn't change."""
    assert _fingerprint(watermark_enabled=True, watermark_params_hash="params-a") != _fingerprint(
        watermark_enabled=True, watermark_params_hash="params-b"
    )


def test_burn_text_cards_toggle_changes_the_fingerprint():
    """A text-card-off and text-card-on render of the identical Timeline
    must never collide on one cache entry (motion_new_styles_and_long_
    form_videos.md §2.6, 2026-08-17) - `burn_text_cards` is a config
    toggle, not Timeline content, exactly the R2 shape."""
    assert _fingerprint(burn_text_cards=True) != _fingerprint(burn_text_cards=False)


def test_different_text_card_font_changes_the_fingerprint():
    """Swapping the vendored font file must invalidate the cache even
    though nothing else about the render changed - same reasoning as
    `test_different_caption_font_changes_the_fingerprint` above, applied
    to the text-card font hash instead."""
    assert _fingerprint(burn_text_cards=True, text_card_font_hash="font-hash-a") != _fingerprint(
        burn_text_cards=True, text_card_font_hash="font-hash-b"
    )


def test_bookkeeping_fields_never_affect_the_fingerprint():
    """Two DIFFERENT projects/versions with byte-identical scene content
    must fingerprint identically - this is what makes cross-project
    render reuse possible at all, not just same-project resume, and it
    can never cause a false hit since none of these fields reach a
    single rendered pixel."""

    def _other_bookkeeping_timeline() -> Timeline:
        shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt="a shot")
        scene = Scene(id="sc_01", order=0, title="Scene", duration_s=3.0, shots=[shot])
        return Timeline(
            timeline_id="a-totally-different-timeline-id",
            project_id="a-totally-different-project-id",
            version=7,
            parent_version=6,
            produced_by=ProducedBy.NARRATION,
            status=TimelineStatus.APPROVED,
            created_at=datetime(2030, 5, 5, tzinfo=UTC),
            scenes=[scene],
        )

    assert _fingerprint() == _fingerprint(timeline=_other_bookkeeping_timeline())


def _run_fp(**overrides) -> str:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=2.0)
    kwargs = {
        "shots": [shot],
        "shot_content_hashes": {"sh_01": "hash-a"},
        "render_settings": _SETTINGS,
        "ffmpeg_version": "ffmpeg version 7.1.5",
    }
    kwargs.update(overrides)
    return compute_run_fingerprint(**kwargs)


def test_identical_runs_produce_identical_run_fingerprints():
    assert _run_fp() == _run_fp()


def test_run_fingerprint_changes_with_shot_duration():
    other = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    assert _run_fp(shots=[other]) != _run_fp()


def test_run_fingerprint_changes_with_asset_hash():
    assert _run_fp(shot_content_hashes={"sh_01": "hash-b"}) != _run_fp()


def test_run_fingerprint_asset_order_is_the_run_order():
    """Not sorted: swapping two shots' media must miss, unlike the
    full-render hash which sorts globally."""
    a = Shot(id="sh_a", order=0, intent=ShotIntent.EXPLAIN, duration_s=1.0)
    b = Shot(id="sh_b", order=1, intent=ShotIntent.EXPLAIN, duration_s=1.0)
    hashes = {"sh_a": "ha", "sh_b": "hb"}
    swapped = {"sh_a": "hb", "sh_b": "ha"}
    assert _run_fp(shots=[a, b], shot_content_hashes=hashes) != _run_fp(
        shots=[a, b], shot_content_hashes=swapped
    )


def test_run_fingerprint_does_not_collide_with_full_render_hash():
    assert _run_fp() != _fingerprint()


def _shot_fp(**overrides) -> str:
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=2.0)
    kwargs = {
        "shot": shot,
        "asset_hash": "hash-a",
        "render_settings": _SETTINGS,
        "ffmpeg_version": "ffmpeg version 7.1.5",
    }
    kwargs.update(overrides)
    return compute_shot_stream_fingerprint(**kwargs)


def test_identical_shots_produce_identical_stream_fingerprints():
    assert _shot_fp() == _shot_fp()


def test_shot_stream_fingerprint_ignores_transition_out():
    """C3 (d): a dissolve-duration edit must reuse the intermediate."""
    cut = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )
    dissolve = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        transition_out=Transition(type=TransitionType.DISSOLVE, duration_s=0.5),
    )
    assert _shot_fp(shot=cut) == _shot_fp(shot=dissolve)


def test_shot_stream_fingerprint_changes_with_camera():
    moving = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        camera=Camera(movement=CameraMovement.SLOW_ZOOM),
    )
    assert _shot_fp(shot=moving) != _shot_fp()
