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


def _timeline(shot_prompt: str = "a shot", sfx_cue: str | None = None) -> Timeline:
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt=shot_prompt,
        sfx_cue=sfx_cue,
    )
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
        "asset_content_hashes": {"sh_01": "hash-a"},
        "secondary_content_hashes": {"sh_01": "hash-b"},
        "narration_content_hashes": ["narr-1"],
        "music_content_hash": "music-1",
        "render_settings": _SETTINGS,
        "music_bed_gain_db": -14.0,
        "music_duck_gain_db": -20.0,
        "music_gain_offset_db": 0.0,
        "music_amix_normalize": 0,
        "loudness_normalize": True,
        "loudness_target_lufs": -16.0,
        "loudness_true_peak_db": -1.0,
        "narration_level_match": True,
        "burn_captions": False,
        "caption_font_hash": None,
        "cue_list_hash": None,
        "duck_envelope_hash": None,
        "watermark_enabled": False,
        "watermark_asset_hash": None,
        "watermark_params_hash": None,
        "burn_text_cards": False,
        "text_card_font_hash": None,
        "sfx_content_hashes": [],
        "sfx_gain_db": -8.0,
        "sfx_max_clip_s": 1.5,
        "sfx_diegetic_max_clip_s": 8.0,
        "sfx_diegetic_shot_carry_s": 0.25,
        "sfx_whoosh_enabled": True,
        "sfx_normalize_target_db": -8.0,
        "sfx_kind_gain_overrides_db": {},
        "sfx_diegetic_normalize_target_lufs": -23.0,
        "sfx_diegetic_loudness_min_duration_s": 1.5,
        "sfx_diegetic_duck_depth_db": 3.0,
        "ffmpeg_version": "ffmpeg version 9.0",
        "shot_focal": {"sh_01": ""},
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


def test_asset_content_hash_dict_construction_order_does_not_matter():
    """R16: keyed by shot_id, so inserting the mapping in a different
    order is still the same assignment."""
    assert _fingerprint(asset_content_hashes={"sh_01": "hash-a"}) == _fingerprint(
        asset_content_hashes={"sh_01": "hash-a"}
    )


def test_swapping_top_and_bottom_panels_changes_the_fingerprint():
    """R16: a sorted bag of hashes cannot tell the panels apart."""
    assert _fingerprint(
        asset_content_hashes={"sh_01": "hash-a"},
        secondary_content_hashes={"sh_01": "hash-b"},
    ) != _fingerprint(
        asset_content_hashes={"sh_01": "hash-b"},
        secondary_content_hashes={"sh_01": "hash-a"},
    )


def test_swapping_two_shots_assets_changes_the_fingerprint():
    """R16 also closes the pre-existing shot↔shot swap on locked shots."""
    shot_a = Shot(id="sh_a", order=0, intent=ShotIntent.EXPLAIN, duration_s=1.0)
    shot_b = Shot(id="sh_b", order=1, intent=ShotIntent.EXPLAIN, duration_s=1.0)
    scene = Scene(id="sc_01", order=0, title="Scene", duration_s=2.0, shots=[shot_a, shot_b])
    two = Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )
    assigned = {"sh_a": "hash-a", "sh_b": "hash-b"}
    swapped = {"sh_a": "hash-b", "sh_b": "hash-a"}
    assert _fingerprint(timeline=two, asset_content_hashes=assigned) != _fingerprint(
        timeline=two, asset_content_hashes=swapped
    )


def test_different_timeline_content_changes_the_fingerprint():
    assert _fingerprint(timeline=_timeline("a different shot")) != _fingerprint()


def test_different_asset_content_changes_the_fingerprint():
    assert _fingerprint(asset_content_hashes={"sh_01": "hash-c"}) != _fingerprint()


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


def test_music_gain_offset_changes_the_fingerprint():
    """Decision 7 (analysis.md, 2026-08-24): the uploaded track's dB offset
    changes mixed loudness, so moving it must miss every cached render -
    the exact R2 shape, applied to the per-track slider instead of config."""
    assert _fingerprint(music_gain_offset_db=0.0) != _fingerprint(music_gain_offset_db=-6.0)


def test_music_amix_normalize_changes_the_fingerprint():
    """OQ-1d: flipping amix normalize 0 vs 1 changes mixed samples, so it
    must miss every cached pre-fix mix (R2)."""
    assert _fingerprint(music_amix_normalize=0) != _fingerprint(music_amix_normalize=1)


def test_music_amix_normalize_is_in_the_fingerprint_payload():
    """Fails if the payload key is removed while the kwarg still exists —
    inspect the source so a silent drop cannot regress."""
    import inspect

    from app.renderer.fingerprint import compute_render_fingerprint

    source = inspect.getsource(compute_render_fingerprint)
    assert '"music_amix_normalize"' in source


def test_loudness_normalize_changes_the_fingerprint():
    """OQ-1a: toggling the loudness pass changes output samples (R2)."""
    assert _fingerprint(loudness_normalize=True) != _fingerprint(loudness_normalize=False)


def test_loudness_target_lufs_changes_the_fingerprint():
    assert _fingerprint(loudness_target_lufs=-16.0) != _fingerprint(loudness_target_lufs=-14.0)


def test_loudness_true_peak_db_changes_the_fingerprint():
    assert _fingerprint(loudness_true_peak_db=-1.0) != _fingerprint(loudness_true_peak_db=-2.0)


def test_loudness_lra_is_in_the_fingerprint_payload():
    import inspect

    from app.renderer.fingerprint import compute_render_fingerprint

    source = inspect.getsource(compute_render_fingerprint)
    assert '"loudness_lra"' in source


def test_loudness_target_lufs_is_in_the_fingerprint_payload():
    """Fails if the payload key is removed while the kwarg still exists."""
    import inspect

    from app.renderer.fingerprint import compute_render_fingerprint

    source = inspect.getsource(compute_render_fingerprint)
    assert '"loudness_target_lufs"' in source


def test_narration_level_match_changes_the_fingerprint():
    """OQ-1c: toggling per-scene narration gain match changes samples (R2)."""
    assert _fingerprint(narration_level_match=True) != _fingerprint(narration_level_match=False)


def test_narration_level_match_is_in_the_fingerprint_payload():
    """Fails if the payload key is removed while the kwarg still exists."""
    import inspect

    from app.renderer.fingerprint import compute_render_fingerprint

    source = inspect.getsource(compute_render_fingerprint)
    assert '"narration_level_match"' in source


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


def test_different_duck_envelope_changes_the_fingerprint():
    """OQ-1b: alignment-derived duck windows are not covered by scene
    structure; changing the envelope hash must miss the cache (R2)."""
    assert _fingerprint(duck_envelope_hash="duck-a") != _fingerprint(duck_envelope_hash="duck-b")
    assert _fingerprint(duck_envelope_hash=None) != _fingerprint(duck_envelope_hash="duck-a")


def test_duck_envelope_hash_is_in_the_fingerprint_payload():
    """Fails if the payload key is removed while the kwarg still exists."""
    import inspect

    from app.renderer.fingerprint import compute_render_fingerprint

    source = inspect.getsource(compute_render_fingerprint)
    assert '"duck_envelope_hash"' in source


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


def test_different_sfx_clip_hash_changes_the_fingerprint():
    """Plan §5.5 / §7: SFX clip bytes are a render input."""
    assert _fingerprint(sfx_content_hashes=["aaa"]) != _fingerprint(sfx_content_hashes=["bbb"])


def test_different_sfx_gain_changes_the_fingerprint():
    assert _fingerprint(sfx_gain_db=-8.0) != _fingerprint(sfx_gain_db=-4.0)


def test_different_sfx_max_clip_changes_the_fingerprint():
    """R12: `atrim` length is a mix input."""
    assert _fingerprint(sfx_max_clip_s=1.5) != _fingerprint(sfx_max_clip_s=3.0)


def test_different_sfx_cue_changes_the_fingerprint():
    """long_form_direction.md A8, R2: two timelines differing ONLY in a
    shot's `sfx_cue` must fingerprint differently, or the render cache
    would serve audio from a previous cue set. `sfx_cue` reaches the
    fingerprint via the ordinary timeline-content dump (no special-casing
    needed), same as any other Shot field."""
    assert _fingerprint(timeline=_timeline(sfx_cue="a Geiger counter clicking")) != _fingerprint(
        timeline=_timeline(sfx_cue="a church bell tolling")
    )
    assert _fingerprint(timeline=_timeline(sfx_cue=None)) != _fingerprint(
        timeline=_timeline(sfx_cue="a Geiger counter clicking")
    )


def test_different_diegetic_clip_content_hash_changes_the_fingerprint():
    """long_form_direction.md A8, R2: `SfxClipSelection.shot_id` and
    `content_hash` for a DIEGETIC clip reach the fingerprint through the
    ordinary `sfx_plan` dump inside the timeline document itself - not
    only through the redundant `sfx_content_hashes` list argument
    (`test_different_sfx_clip_hash_changes_the_fingerprint` above already
    covers that one). Two timelines whose ONLY difference is a generated
    cue's content hash must still fingerprint differently."""
    from app.schemas.timeline import SfxClipSelection, SfxKind, SfxPlan

    def _with_diegetic_clip(content_hash: str) -> Timeline:
        timeline = _timeline(sfx_cue="a Geiger counter clicking")
        timeline.sfx_plan = SfxPlan(
            clips=[
                SfxClipSelection(
                    kind=SfxKind.DIEGETIC,
                    provider="elevenlabs",
                    track_id="hash1",
                    source_url="",
                    licence="generated",
                    content_hash=content_hash,
                    shot_id="sh_01",
                )
            ]
        )
        return timeline

    assert _fingerprint(timeline=_with_diegetic_clip("aaa")) != _fingerprint(
        timeline=_with_diegetic_clip("bbb")
    )


def test_different_sfx_diegetic_max_clip_changes_the_fingerprint():
    """long_form_direction.md A8: diegetic's OWN ceiling is a real mix
    input, distinct from `sfx_max_clip_s` - it must invalidate the cache
    on its own even when the structural ceiling is unchanged."""
    assert _fingerprint(sfx_diegetic_max_clip_s=8.0) != _fingerprint(sfx_diegetic_max_clip_s=12.0)


def test_different_diegetic_loudness_changes_the_fingerprint():
    """A11 (long_form_direction.md, 2026-09-01): `SfxClipSelection.
    loudness_lufs` is a real mix input for a DIEGETIC clip, reached via
    the ordinary `sfx_plan` dump - same shape as
    `test_different_diegetic_clip_content_hash_changes_the_fingerprint`."""
    from app.schemas.timeline import SfxClipSelection, SfxKind, SfxPlan

    def _with_loudness(loudness_lufs: float | None) -> Timeline:
        timeline = _timeline(sfx_cue="a church bell tolling")
        timeline.sfx_plan = SfxPlan(
            clips=[
                SfxClipSelection(
                    kind=SfxKind.DIEGETIC,
                    provider="elevenlabs",
                    track_id="hash1",
                    source_url="",
                    licence="generated",
                    content_hash="aaa",
                    shot_id="sh_01",
                    loudness_lufs=loudness_lufs,
                )
            ]
        )
        return timeline

    assert _fingerprint(timeline=_with_loudness(-29.7)) != _fingerprint(
        timeline=_with_loudness(-23.5)
    )
    assert _fingerprint(timeline=_with_loudness(None)) != _fingerprint(
        timeline=_with_loudness(-29.7)
    )


def test_different_sfx_diegetic_normalize_target_changes_the_fingerprint():
    """A11: the loudness target is config-time, has nowhere else to live -
    same R2 shape as `sfx_normalize_target_db`."""
    assert _fingerprint(sfx_diegetic_normalize_target_lufs=-23.0) != _fingerprint(
        sfx_diegetic_normalize_target_lufs=-20.0
    )


def test_different_sfx_diegetic_loudness_min_duration_changes_the_fingerprint():
    """A11: the duration floor decides which of two gain paths a clip
    takes - a real mix input."""
    assert _fingerprint(sfx_diegetic_loudness_min_duration_s=1.5) != _fingerprint(
        sfx_diegetic_loudness_min_duration_s=2.0
    )


def test_different_sfx_diegetic_duck_depth_changes_the_fingerprint():
    """A11: the diegetic-cue duck depth is a real mix input to `mux_music`
    once any shot carries an `sfx_cue` - unconditional presence (R2), same
    as `music_bed_gain_db`/`music_duck_gain_db`."""
    assert _fingerprint(sfx_diegetic_duck_depth_db=3.0) != _fingerprint(
        sfx_diegetic_duck_depth_db=6.0
    )


def test_sfx_whoosh_gate_changes_the_fingerprint():
    """Decisions 5 + 5a (analysis.md, 2026-08-24): flipping the per-style
    WHOOSH gate changes which overlay events get mixed at all, so it must
    miss every cached render - same R2 shape as sfx_gain_db above."""
    assert _fingerprint(sfx_whoosh_enabled=True) != _fingerprint(sfx_whoosh_enabled=False)


def test_different_sfx_normalize_target_changes_the_fingerprint():
    """C3c (analysis.md, decision 5b): the normalization target changes
    every measured clip's volume factor - a cache-HIT here would serve the
    OLD loudness after retuning the target."""
    assert _fingerprint(sfx_normalize_target_db=-8.0) != _fingerprint(sfx_normalize_target_db=-12.0)


def test_sfx_kind_gain_override_changes_the_fingerprint():
    """C3c: a per-kind dB offset is a real mix input even when the dict
    shape (None -> value) is all that changed."""
    assert _fingerprint(sfx_kind_gain_overrides_db={}) != _fingerprint(
        sfx_kind_gain_overrides_db={"stinger": -3.0}
    )


def test_swapping_two_shots_focals_changes_the_fingerprint():
    """OQ-2 / R16: focal is an assignment keyed by shot_id — swapping
    two shots' focals must miss even with identical asset hashes."""
    shot_a = Shot(id="sh_a", order=0, intent=ShotIntent.EXPLAIN, duration_s=1.0)
    shot_b = Shot(id="sh_b", order=1, intent=ShotIntent.EXPLAIN, duration_s=1.0)
    scene = Scene(id="sc_01", order=0, title="Scene", duration_s=2.0, shots=[shot_a, shot_b])
    two = Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )
    hashes = {"sh_a": "hash-a", "sh_b": "hash-b"}
    assigned = {"sh_a": "0.200000,0.800000", "sh_b": "0.700000,0.300000"}
    swapped = {"sh_a": "0.700000,0.300000", "sh_b": "0.200000,0.800000"}
    assert _fingerprint(timeline=two, asset_content_hashes=hashes, shot_focal=assigned) != (
        _fingerprint(timeline=two, asset_content_hashes=hashes, shot_focal=swapped)
    )


def test_empty_focal_differs_from_resolved_centre():
    """Unresolved (`\"\"`) must not collide with an explicit centre
    resolve, so a later sidecar write cannot cache-HIT the gap."""
    assert _fingerprint(shot_focal={"sh_01": ""}) != _fingerprint(
        shot_focal={"sh_01": "0.500000,0.500000"}
    )


def test_shot_focal_is_in_the_fingerprint_payload():
    """Fails if the payload key is removed while the kwarg still exists."""
    import inspect

    from app.renderer.fingerprint import compute_render_fingerprint

    source = inspect.getsource(compute_render_fingerprint)
    assert '"shot_focal"' in source


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


def test_run_fingerprint_changes_with_secondary_asset_hash():
    assert _run_fp(secondary_content_hashes={"sh_01": "bot-a"}) != _run_fp(
        secondary_content_hashes={"sh_01": "bot-b"}
    )


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


def test_secondary_asset_hash_changes_the_shot_stream_fingerprint():
    """Split-screen bottom panel is a real encode input (R2 / §7)."""
    assert _shot_fp(secondary_asset_hash="") != _shot_fp(secondary_asset_hash="hash-b")


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


def test_split_panel_fit_changes_all_three_fingerprints(monkeypatch):
    """Padded-panel verdict is a pixel input. Letterbox vs fill must miss
    the full render, the per-run encode, and the shot-stream cache."""
    fill_full = _fingerprint()
    fill_run = _run_fp()
    fill_shot = _shot_fp()
    monkeypatch.setattr("app.renderer.fingerprint.SPLIT_PANEL_FIT", "letterbox")
    assert _fingerprint() != fill_full
    assert _run_fp() != fill_run
    assert _shot_fp() != fill_shot
