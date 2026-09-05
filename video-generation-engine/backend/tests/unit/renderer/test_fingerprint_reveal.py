"""`app/renderer/fingerprint.py`'s F5 coverage for `Shot.reveal_direction`/
`reveal_start_fragment`/`reveal_end_fragment`/`reveal_start_offset_s`/
`reveal_duration_s` (illustrated_faceless.md §2/F5, R2 - "the likeliest way
this ships broken").

Same shape as `test_fingerprint_parallax.py` (F2/F4's own R2 coverage):
`compute_render_fingerprint`/`compute_run_fingerprint` dump the whole
`Shot`, so the reveal fields ride in for free - verified directly, not
assumed. `compute_shot_stream_fingerprint` hand-picks fields and needed
an explicit `"reveal"` entry (this file's own proof that entry actually
does something), the identical gap F2's `layers` field found in that
function first.

Kept in its own file for the same reason `test_fingerprint_parallax.py`
is: `test_fingerprint.py`'s own `_fingerprint()` helper is missing an
unrelated, pre-existing required kwarg on this branch - this file builds
its own complete kwargs so a failure here is unambiguously this task's
own regression.
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
    RevealDirection,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)

_SETTINGS = RenderSettings(width=720, height=1280, fps=30, pixel_format="yuv420p")


def _reveal_shot(**overrides) -> Shot:
    fields = {
        "id": "sh_01",
        "order": 0,
        "intent": ShotIntent.EXPLAIN,
        "duration_s": 3.0,
        "prompt": "a risograph bar chart",
        "camera": Camera(movement=CameraMovement.STATIC),
        "reveal_direction": RevealDirection.BOTTOM_TO_TOP,
        "reveal_start_fragment": 1,
        "reveal_end_fragment": 2,
        "reveal_start_offset_s": 0.5,
        "reveal_duration_s": 1.0,
    }
    fields.update(overrides)
    return Shot(**fields)


def _timeline(shot: Shot) -> Timeline:
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


def _render_fingerprint(**overrides) -> str:
    kwargs = {
        "timeline": _timeline(_reveal_shot()),
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
# compute_render_fingerprint - full timeline dump, so reveal fields ride in
# for free. Verified, not assumed.
# ---------------------------------------------------------------------------


def test_no_reveal_is_deterministic_and_identical_across_calls():
    no_reveal = _timeline(
        _reveal_shot(reveal_direction=None, reveal_start_fragment=None, reveal_end_fragment=None)
    )
    assert _render_fingerprint(timeline=no_reveal) == _render_fingerprint(timeline=no_reveal)


def test_adding_a_reveal_changes_the_fingerprint():
    no_reveal = _timeline(
        _reveal_shot(reveal_direction=None, reveal_start_fragment=None, reveal_end_fragment=None)
    )
    with_reveal = _timeline(_reveal_shot())
    assert _render_fingerprint(timeline=no_reveal) != _render_fingerprint(timeline=with_reveal)


def test_changing_only_reveal_direction_changes_the_fingerprint():
    a = _timeline(_reveal_shot(reveal_direction=RevealDirection.BOTTOM_TO_TOP))
    b = _timeline(_reveal_shot(reveal_direction=RevealDirection.LEFT_TO_RIGHT))
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_changing_only_reveal_start_fragment_changes_the_fingerprint():
    a = _timeline(_reveal_shot(reveal_start_fragment=1))
    b = _timeline(_reveal_shot(reveal_start_fragment=2))
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_changing_only_reveal_end_fragment_changes_the_fingerprint():
    a = _timeline(_reveal_shot(reveal_end_fragment=2))
    b = _timeline(_reveal_shot(reveal_end_fragment=3))
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_changing_only_reveal_start_offset_s_changes_the_fingerprint():
    a = _timeline(_reveal_shot(reveal_start_offset_s=0.5))
    b = _timeline(_reveal_shot(reveal_start_offset_s=0.7))
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_changing_only_reveal_duration_s_changes_the_fingerprint():
    a = _timeline(_reveal_shot(reveal_duration_s=1.0))
    b = _timeline(_reveal_shot(reveal_duration_s=1.4))
    assert _render_fingerprint(timeline=a) != _render_fingerprint(timeline=b)


def test_two_identical_reveals_fingerprint_identically():
    a = _timeline(_reveal_shot())
    b = _timeline(_reveal_shot())
    assert _render_fingerprint(timeline=a) == _render_fingerprint(timeline=b)


# ---------------------------------------------------------------------------
# compute_shot_stream_fingerprint - hand-picks fields, so reveal needs an
# EXPLICIT entry (the "reveal" payload key added alongside "layers").
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


def test_shot_stream_fingerprint_no_reveal_is_deterministic():
    shot = _reveal_shot(reveal_direction=None, reveal_start_fragment=None, reveal_end_fragment=None)
    assert _shot_stream_fingerprint(shot) == _shot_stream_fingerprint(shot)


def test_shot_stream_fingerprint_changes_when_a_reveal_is_added():
    plain = _reveal_shot(
        reveal_direction=None, reveal_start_fragment=None, reveal_end_fragment=None
    )
    revealed = _reveal_shot()
    assert _shot_stream_fingerprint(plain) != _shot_stream_fingerprint(revealed)


def test_shot_stream_fingerprint_changes_when_only_reveal_direction_changes():
    a = _reveal_shot(reveal_direction=RevealDirection.BOTTOM_TO_TOP)
    b = _reveal_shot(reveal_direction=RevealDirection.LEFT_TO_RIGHT)
    assert _shot_stream_fingerprint(a) != _shot_stream_fingerprint(b)


def test_shot_stream_fingerprint_changes_when_only_reveal_start_offset_s_changes():
    a = _reveal_shot(reveal_start_offset_s=0.5)
    b = _reveal_shot(reveal_start_offset_s=0.9)
    assert _shot_stream_fingerprint(a) != _shot_stream_fingerprint(b)


def test_shot_stream_fingerprint_changes_when_only_reveal_duration_s_changes():
    a = _reveal_shot(reveal_duration_s=1.0)
    b = _reveal_shot(reveal_duration_s=1.6)
    assert _shot_stream_fingerprint(a) != _shot_stream_fingerprint(b)


def test_shot_stream_fingerprint_unaffected_by_reveal_when_only_text_card_and_id_differ():
    """Regression shape check mirroring test_fingerprint_parallax.py's
    own: two shots differing only in fields this function deliberately
    excludes (`id`, `text_card`) but identical reveal fields still
    fingerprint the same."""
    a = _reveal_shot(id="sh_01", text_card="x")
    b = _reveal_shot(id="sh_01", text_card="y")
    assert _shot_stream_fingerprint(a) == _shot_stream_fingerprint(b)


# ---------------------------------------------------------------------------
# compute_run_fingerprint - full shot dump, so reveal rides in for free too.
# ---------------------------------------------------------------------------


def test_run_fingerprint_changes_when_a_reveal_is_added():
    plain = [
        _reveal_shot(reveal_direction=None, reveal_start_fragment=None, reveal_end_fragment=None)
    ]
    revealed = [_reveal_shot()]
    fp_plain = compute_run_fingerprint(
        shots=plain,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
    )
    fp_revealed = compute_run_fingerprint(
        shots=revealed,
        shot_content_hashes={"sh_01": "hash-a"},
        render_settings=_SETTINGS,
        ffmpeg_version="ffmpeg version 9.0",
    )
    assert fp_plain != fp_revealed
