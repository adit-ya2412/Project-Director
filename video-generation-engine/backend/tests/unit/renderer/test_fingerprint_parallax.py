"""`app/renderer/fingerprint.py`'s F2 coverage for `Shot.layers`
(illustrated_faceless.md §2.2/F2, R2 - "the likeliest way this ships
broken").

Kept in its OWN file rather than extended into `test_fingerprint.py`:
that file's own `_fingerprint()` helper is missing the (unrelated,
uncommitted) `sfx_diegetic_shot_carry_s` kwarg `compute_render_
fingerprint` already requires, so every test in it currently fails
with a `missing 1 required keyword-only argument` `TypeError` - a
PRE-EXISTING failure from A15 work on this branch, not this task's to
fix (per the brief). This file builds its own complete, correct kwargs
so it is not coupled to that unrelated breakage, and a NEW failure here
is unambiguously this task's own regression, never confusable with the
known one (different file, different error shape - `TypeError` vs an
assertion here).
"""

from datetime import UTC, datetime

from app.renderer.fingerprint import (
    compute_render_fingerprint,
    compute_run_fingerprint,
    compute_shot_stream_fingerprint,
)
from app.renderer.slideshow import RenderSettings
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    Camera,
    LayerRole,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
    Timeline,
    TimelineStatus,
)

_SETTINGS = RenderSettings(width=720, height=1280, fps=30, pixel_format="yuv420p")


def _timeline(layers: list[ShotLayer] | None = None) -> Timeline:
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="a shot",
        layers=layers or [],
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


def _two_layers(*, subject_drift_x: float = 110.0) -> list[ShotLayer]:
    return [
        ShotLayer(
            role=LayerRole.BACKGROUND,
            prompt="a hagwon classroom",
            asset_plan=AssetPlan(strategy=AssetStrategy.GENERATE_IMAGE),
            drift_x=24.0,
        ),
        ShotLayer(
            role=LayerRole.SUBJECT,
            prompt="a student, seen from behind",
            asset_plan=AssetPlan(strategy=AssetStrategy.GENERATE_IMAGE),
            drift_x=subject_drift_x,
        ),
    ]


def _render_fingerprint(**overrides) -> str:
    kwargs = {
        "timeline": _timeline(),
        "asset_content_hashes": {"sh_01": "hash-a"},
        "secondary_content_hashes": {"sh_01": ""},
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
        "sfx_diegetic_shot_carry_s": 2.0,
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


# ---------------------------------------------------------------------------
# compute_render_fingerprint
# ---------------------------------------------------------------------------


def test_no_layers_is_deterministic_and_identical_across_calls():
    """`layers=[]` -> today's behaviour: two calls on the identical
    no-layers timeline still fingerprint identically (nothing about the
    new `shot_layers` payload entry introduces incidental non-
    determinism, e.g. from dict ordering)."""
    assert _render_fingerprint() == _render_fingerprint()


def test_adding_layers_changes_the_fingerprint():
    with_layers = _timeline(layers=_two_layers())
    assert _render_fingerprint(timeline=_timeline()) != _render_fingerprint(timeline=with_layers)


def test_changing_a_layers_drift_rate_changes_the_fingerprint():
    a = _timeline(layers=_two_layers(subject_drift_x=110.0))
    b = _timeline(layers=_two_layers(subject_drift_x=90.0))
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_changing_a_layers_scale_changes_the_fingerprint():
    a = _timeline(layers=_two_layers())
    b = _timeline(layers=_two_layers())
    b.scenes[0].shots[0].layers[1].scale = 1.4
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_changing_a_layers_role_changes_the_fingerprint():
    """Swapping which role a layer plays changes composited output even
    if every other field is identical - roles decide keying/overlay
    order in `parallax.py`."""
    a = _timeline(layers=_two_layers())
    b = _timeline(layers=_two_layers())
    b.scenes[0].shots[0].layers[0] = ShotLayer(
        role=LayerRole.FOREGROUND,
        prompt=b.scenes[0].shots[0].layers[0].prompt,
        asset_plan=b.scenes[0].shots[0].layers[0].asset_plan,
        drift_x=b.scenes[0].shots[0].layers[0].drift_x,
    )
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_adding_a_third_layer_changes_the_fingerprint():
    """Layer COUNT, not just per-layer values, must be covered (R2)."""
    two = _timeline(layers=_two_layers())
    three = _timeline(layers=[*_two_layers(), ShotLayer(role=LayerRole.FOREGROUND, drift_x=230.0)])
    assert _render_fingerprint(timeline=two) != _render_fingerprint(timeline=three)


def test_two_identical_layer_lists_fingerprint_identically():
    a = _timeline(layers=_two_layers())
    b = _timeline(layers=_two_layers())
    assert _render_fingerprint(timeline=a) == _render_fingerprint(timeline=b)


def test_unchanged_non_layer_fields_do_not_move_when_layer_hashes_are_absent():
    """Not passing `layer_content_hashes` at all (every call site today,
    since render.py is not wired to F2 in this pass) must behave exactly
    like passing an empty dict - a caller who does not know about layers
    yet gets today's behaviour."""
    assert _render_fingerprint() == _render_fingerprint(layer_content_hashes={})
    assert _render_fingerprint() == _render_fingerprint(layer_content_hashes=None)


def test_layer_content_hashes_are_a_real_fingerprint_input():
    """The layer's resolved image BYTES (I2 - never on the Timeline
    itself) must be covered too, the same shape as
    `secondary_content_hashes` - two renders of the SAME Shot.layers
    creative data but different generated images must not collide."""
    timeline = _timeline(layers=_two_layers())
    fp_a = _render_fingerprint(
        timeline=timeline, layer_content_hashes={"sh_01": ["bg-hash-1", "sub-hash-1"]}
    )
    fp_b = _render_fingerprint(
        timeline=timeline, layer_content_hashes={"sh_01": ["bg-hash-2", "sub-hash-1"]}
    )
    assert fp_a != fp_b


def test_changing_only_enter_on_fragment_changes_the_fingerprint():
    """F4 (illustrated_faceless.md §2/F4), the task this file's own R2
    docstring exists for: `Shot.layers` creative fields ride into
    `compute_render_fingerprint` for free via the full `timeline.model_
    dump` - "should be" is not verification, so this asserts it directly
    for the two NEW fields, changing ONLY one at a time."""
    a = _timeline(layers=_two_layers())
    b = _timeline(layers=_two_layers())
    b.scenes[0].shots[0].layers[1].enter_on_fragment = 2
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_changing_only_enter_offset_s_changes_the_fingerprint():
    a = _timeline(layers=_two_layers())
    b = _timeline(layers=_two_layers())
    b.scenes[0].shots[0].layers[1].enter_offset_s = 1.4
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_layer_content_hash_dict_key_order_does_not_matter():
    timeline = _timeline(layers=_two_layers())
    hashes = {"sh_01": ["bg-hash", "sub-hash"]}
    fp_a = _render_fingerprint(timeline=timeline, layer_content_hashes=dict(hashes))
    fp_b = _render_fingerprint(
        timeline=timeline, layer_content_hashes={k: list(v) for k, v in hashes.items()}
    )
    assert fp_a == fp_b


# ---------------------------------------------------------------------------
# compute_shot_stream_fingerprint - hand-picks fields, so layers need an
# EXPLICIT entry (unlike compute_render_fingerprint's free ride via the
# full timeline dump).
# ---------------------------------------------------------------------------


def _shot_stream_fingerprint(shot: Shot, **overrides) -> str:
    kwargs = {
        "shot": shot,
        "asset_hash": "hash-a",
        "render_settings": _SETTINGS,
        "ffmpeg_version": "ffmpeg version 9.0",
    }
    kwargs.update(overrides)
    return compute_shot_stream_fingerprint(**kwargs)


def _shot(layers: list[ShotLayer] | None = None, **overrides) -> Shot:
    fields = {
        "id": "sh_01",
        "order": 0,
        "intent": ShotIntent.EXPLAIN,
        "duration_s": 3.0,
        "camera": Camera(),
        "layers": layers or [],
    }
    fields.update(overrides)
    return Shot(**fields)


def test_shot_stream_fingerprint_no_layers_is_deterministic():
    shot = _shot()
    assert _shot_stream_fingerprint(shot) == _shot_stream_fingerprint(shot)


def test_shot_stream_fingerprint_changes_when_layers_are_added():
    plain = _shot()
    layered = _shot(layers=_two_layers())
    assert _shot_stream_fingerprint(plain) != _shot_stream_fingerprint(layered)


def test_shot_stream_fingerprint_changes_when_a_layers_drift_changes():
    a = _shot(layers=_two_layers(subject_drift_x=110.0))
    b = _shot(layers=_two_layers(subject_drift_x=200.0))
    assert _shot_stream_fingerprint(a) != _shot_stream_fingerprint(b)


def test_shot_stream_fingerprint_changes_when_only_enter_on_fragment_changes():
    a = _shot(layers=_two_layers())
    b = _shot(layers=_two_layers())
    b.layers[1].enter_on_fragment = 2
    assert _shot_stream_fingerprint(a) != _shot_stream_fingerprint(b)


def test_shot_stream_fingerprint_changes_when_only_enter_offset_s_changes():
    a = _shot(layers=_two_layers())
    b = _shot(layers=_two_layers())
    b.layers[1].enter_offset_s = 1.4
    assert _shot_stream_fingerprint(a) != _shot_stream_fingerprint(b)


def test_shot_stream_fingerprint_layer_asset_hashes_are_a_real_input():
    shot = _shot(layers=_two_layers())
    fp_a = _shot_stream_fingerprint(shot, layer_asset_hashes=["bg-1", "sub-1"])
    fp_b = _shot_stream_fingerprint(shot, layer_asset_hashes=["bg-2", "sub-1"])
    assert fp_a != fp_b


def test_shot_stream_fingerprint_defaults_layer_asset_hashes_to_empty():
    shot = _shot()
    assert _shot_stream_fingerprint(shot) == _shot_stream_fingerprint(shot, layer_asset_hashes=None)
    assert _shot_stream_fingerprint(shot) == _shot_stream_fingerprint(shot, layer_asset_hashes=[])


def test_shot_stream_fingerprint_unaffected_by_layers_when_only_camera_duration_and_asset_are_shared():
    """Regression shape check: two shots differing ONLY in `id`/`text_
    card`/`intent_text` (fields this function deliberately excludes, same
    as `transition_out`) still fingerprint identically when `layers` and
    every other included field match - proves the new `layers` entry did
    not accidentally widen what this function is sensitive to."""
    a = _shot(id="sh_01", intent_text="a", text_card="x")
    b = _shot(id="sh_01", intent_text="different text entirely", text_card="y")
    assert _shot_stream_fingerprint(a) == _shot_stream_fingerprint(b)


# ---------------------------------------------------------------------------
# compute_run_fingerprint - already does a full `shot.model_dump`, so the
# creative half of `layers` rides in for free; only the layer asset hashes
# need an explicit hook.
# ---------------------------------------------------------------------------


def test_run_fingerprint_changes_when_layers_are_added():
    plain = [_shot()]
    layered = [_shot(layers=_two_layers())]
    fp_plain = compute_run_fingerprint(
        shots=plain,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
    )
    fp_layered = compute_run_fingerprint(
        shots=layered,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
    )
    assert fp_plain != fp_layered


def test_run_fingerprint_layer_content_hashes_are_a_real_input():
    shots = [_shot(layers=_two_layers())]
    fp_a = compute_run_fingerprint(
        shots=shots,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
        layer_content_hashes={"sh_01": ["bg-1", "sub-1"]},
    )
    fp_b = compute_run_fingerprint(
        shots=shots,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
        layer_content_hashes={"sh_01": ["bg-2", "sub-1"]},
    )
    assert fp_a != fp_b


def test_run_fingerprint_layer_content_hashes_default_to_empty():
    shots = [_shot()]
    fp_default = compute_run_fingerprint(
        shots=shots,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
    )
    fp_explicit_none = compute_run_fingerprint(
        shots=shots,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
        layer_content_hashes=None,
    )
    assert fp_default == fp_explicit_none
