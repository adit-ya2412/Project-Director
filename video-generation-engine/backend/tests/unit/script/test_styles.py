"""`app/script/styles.py::resolve_constraint_bundle` (motion_new_styles_
and_long_form_videos.md, Track B) - the function that closes the gap
`preflight.py`'s own module docstring flagged: the two real enforcement
points (`generate_timeline.py`, `shot/planner.py`) now read this instead
of flat `settings.*` values directly.
"""

import pytest

from app.core.config import settings
from app.script.styles import (
    STYLE_PACING_BANDS,
    StylePacingBand,
    frame_aspect_error,
    resolve_constraint_bundle,
    resolve_draft_format,
    resolve_music_gains,
    resolve_narration_speed,
    resolve_render_format,
    resolve_sfx_whoosh_enabled,
)


def test_none_resolves_byte_identical_to_flat_settings():
    """Every Timeline predating this field has `render_style=None` -
    this must be indistinguishable from the flat settings reads it
    replaced, not merely similar."""
    bundle = resolve_constraint_bundle(None)
    assert bundle.min_shot_duration_s == settings.min_shot_duration_s
    assert bundle.max_shot_duration_s == settings.max_shot_duration_s
    assert bundle.max_shots_per_project == settings.max_shots_per_project
    assert bundle.max_scenes == settings.max_scenes
    assert bundle.max_video_duration_s == settings.max_video_duration_s
    assert bundle.budget_cap_cents == settings.project_budget_cap_cents
    assert bundle.max_video_shots_per_project == settings.max_video_shots_per_project


def test_documentary_archival_resolves_identical_to_none():
    """The named default style must be exactly as inert as no style at
    all - it has no overrides in `STYLE_PACING_BANDS`."""
    assert resolve_constraint_bundle("documentary_archival") == resolve_constraint_bundle(None)


def test_stillness_resolves_identical_to_none():
    assert resolve_constraint_bundle("stillness") == resolve_constraint_bundle(None)


def test_retention_fast_overrides_all_three_bounds():
    min_s, max_s, shots = resolve_constraint_bundle("retention_fast")
    assert min_s == 0.8
    assert max_s == 3.5  # 1.75 * 2.0 dead-stop ceiling multiplier
    assert shots == 58
    assert resolve_constraint_bundle("retention_fast").max_scenes == settings.max_scenes


def test_length_raises_caps_and_style_multiplies_the_shot_base():
    """Track C §2.3: length sets the base, style multiplies. N=206
    (10 min projection) must raise scenes/shots; retention_fast must
    apply 58/40 to that base, not `max(length, 58)`."""
    long = resolve_constraint_bundle(None, n_fragments=206)
    assert long.max_scenes >= 70
    assert long.max_shots_per_project >= 200
    assert long.max_video_duration_s == pytest.approx(settings.max_long_form_duration_s, abs=5)
    import math

    fast = resolve_constraint_bundle("retention_fast", n_fragments=206)
    assert fast.max_shots_per_project == math.ceil(long.max_shots_per_project * 58 / 40)


def test_short_n_keeps_todays_caps():
    """Path A fixtures (N around 13) must not silently raise the 90 s caps."""
    short = resolve_constraint_bundle(None, n_fragments=13)
    assert short.max_scenes == settings.max_scenes
    assert short.max_shots_per_project == settings.max_shots_per_project
    assert short.max_video_duration_s == settings.max_video_duration_s
    assert short.budget_cap_cents == settings.project_budget_cap_cents
    assert short.max_video_shots_per_project == settings.max_video_shots_per_project


def test_long_form_budget_scales_linearly_and_motion_cap_sublinearly():
    """C6: 90 s → 1000¢ / 5 video shots. 10 min → ~6667¢, 13 video shots
    (sqrt(600/90)×5), not 33 (linear) and not 130 (uncapped)."""
    import math

    long = resolve_constraint_bundle(None, n_fragments=206)
    assert long.max_video_duration_s == pytest.approx(settings.max_long_form_duration_s, abs=5)
    assert long.budget_cap_cents == math.ceil(
        long.max_video_duration_s
        * settings.project_budget_cap_cents
        / settings.max_video_duration_s
    )
    # ~$66, not today's $10, and not a linear 6.7× motion count.
    assert long.budget_cap_cents == pytest.approx(6667, abs=50)
    ratio = long.max_video_duration_s / settings.max_video_duration_s
    assert long.max_video_shots_per_project == math.ceil(
        settings.max_video_shots_per_project * math.sqrt(ratio)
    )
    assert long.max_video_shots_per_project == 13
    assert long.max_video_shots_per_project < math.ceil(
        settings.max_video_shots_per_project * ratio
    )


def test_unrecognised_style_falls_back_rather_than_raising():
    """Deliberately different from `get_pacing_band` (which raises) -
    this function runs deep inside planning, where a raised `KeyError`
    would surface as a confusing crash far from the actual mistake; the
    create-project/set-style endpoints already validate against
    `STYLE_PACING_BANDS` before a style name ever reaches here."""
    assert resolve_constraint_bundle("not_a_real_style") == resolve_constraint_bundle(None)


def test_every_registered_style_is_reachable():
    for style in STYLE_PACING_BANDS:
        resolve_constraint_bundle(style)  # must not raise


def test_max_shot_duration_s_override_is_independent_of_the_dead_stop_ceiling():
    """R7 fix (§13.7): `max_shot_duration_s_override` and
    `max_fragment_duration_s` are separate fields that happen to agree
    for `retention_fast` today - not one field doing both jobs. Proven by
    changing the (uncalibrated, still-open Q5) dead-stop multiplier's
    input and confirming the planning bound does not move with it."""
    band = STYLE_PACING_BANDS["retention_fast"]
    assert band.max_shot_duration_s_override == 3.5
    assert band.max_fragment_duration_s == 3.5  # equal today, not the same field
    # The real proof: a band whose target changes (moving max_fragment_duration_s)
    # must not move max_shot_duration_s_override, since they are independent.
    moved = StylePacingBand(
        name="hypothetical",
        target_shot_duration_s=1.0,  # -> max_fragment_duration_s = 2.0
        max_shots_override=None,
        max_shot_duration_s_override=3.5,
    )
    assert moved.max_fragment_duration_s == 2.0
    _min, max_shot_duration_s, _shots = resolve_constraint_bundle("retention_fast")
    assert max_shot_duration_s == band.max_shot_duration_s_override


def test_retention_fast_narration_speed_is_1_4_and_others_stay_at_default():
    """R8: speed is a style parameter. Default 1.0 keeps the pre-R8
    four-value cache key; only retention_fast overrides it (1.4x as of
    2026-08-24 - see StylePacingBand's own narration_speed docstring)."""
    assert resolve_narration_speed(None) == 1.0
    assert resolve_narration_speed("documentary_archival") == 1.0
    assert resolve_narration_speed("stillness") == 1.0
    assert resolve_narration_speed("retention_fast") == 1.4


def test_retention_fast_gates_whoosh_off_and_others_stay_on():
    """Decisions 5 + 5a (analysis.md, 2026-08-24) / RV5 (review of P1+P2,
    2026-08-24): the WHOOSH SFX layer is a per-style gate, resolved once
    by the caller (`render.py`, RV2) rather than re-resolved at each use
    site. Only `retention_fast` turns it off - same fallback shape as
    `resolve_narration_speed` above."""
    assert resolve_sfx_whoosh_enabled("retention_fast") is False
    assert resolve_sfx_whoosh_enabled("documentary_archival") is True
    assert resolve_sfx_whoosh_enabled("stillness") is True
    # True here because settings.default_render_style (documentary_archival)
    # keeps whoosh_enabled at its True default - unset is NOT pinned open
    # independently of the style registry, it inherits the default style's
    # own band (see resolve_sfx_whoosh_enabled's own docstring).
    assert resolve_sfx_whoosh_enabled(None) is True
    # No band to consult for an unrecognised name - True, the same
    # no-band fallback resolve_narration_speed uses.
    assert resolve_sfx_whoosh_enabled("no_such_style") is True


def test_documentary_archival_is_1280x720_and_retention_fast_stays_portrait():
    archival = resolve_render_format("documentary_archival")
    assert (archival.width, archival.height) == (1280, 720)
    assert archival.is_landscape
    fast = resolve_render_format("retention_fast")
    assert (fast.width, fast.height) == (720, 1280)
    assert not fast.is_landscape
    stillness = resolve_render_format("stillness")
    assert (stillness.width, stillness.height) == (1280, 720)
    assert stillness.is_landscape


def test_stillness_9_16_is_a_vertical_reel_and_16_9_keeps_the_default():
    reel = resolve_render_format("stillness", frame_aspect="9:16")
    assert (reel.width, reel.height) == (720, 1280)
    assert not reel.is_landscape
    landscape = resolve_render_format("stillness", frame_aspect="16:9")
    assert (landscape.width, landscape.height) == (1280, 720)
    assert resolve_render_format("stillness", frame_aspect=None) == landscape
    # Other styles ignore the reel flag at resolve time; the API rejects it.
    assert resolve_render_format("retention_fast", frame_aspect="9:16").width == 720
    assert resolve_render_format("documentary_archival", frame_aspect="9:16").width == 1280


def test_frame_aspect_is_only_legal_on_stillness():
    assert frame_aspect_error("stillness", None) is None
    assert frame_aspect_error("stillness", "9:16") is None
    assert frame_aspect_error("stillness", "16:9") is None
    assert frame_aspect_error(None, None) is None
    assert "only settable" in (frame_aspect_error("documentary_archival", "9:16") or "")
    assert "only settable" in (frame_aspect_error("retention_fast", "16:9") or "")
    assert "unknown" in (frame_aspect_error("stillness", "4:3") or "")


def test_unknown_style_uses_the_default_style_format():
    """§19.11 residual 3: unrecognised names follow documentary_archival,
    not raw settings (720×1280)."""
    default = resolve_render_format(None)
    assert default == resolve_render_format("documentary_archival")
    assert resolve_render_format("not_a_real_style") == default
    assert (default.width, default.height) == (1280, 720)


def test_draft_format_follows_the_style_aspect():
    assert (
        resolve_draft_format("retention_fast").width < resolve_draft_format("retention_fast").height
    )
    draft = resolve_draft_format("documentary_archival")
    assert draft.width > draft.height
    assert (draft.width, draft.height) == (settings.draft_height, settings.draft_width)
    still_draft = resolve_draft_format("stillness")
    assert (still_draft.width, still_draft.height) == (
        settings.draft_height,
        settings.draft_width,
    )
    reel_draft = resolve_draft_format("stillness", frame_aspect="9:16")
    assert (reel_draft.width, reel_draft.height) == (
        settings.draft_width,
        settings.draft_height,
    )
    assert resolve_narration_speed("not_a_real_style") == 1.0
    assert STYLE_PACING_BANDS["retention_fast"].narration_speed == 1.4


def test_music_gains_are_style_owned_and_archival_keeps_the_measured_mix():
    """Leftover item 5 / §5.2. Archival is today's measured mix;
    retention_fast has a louder bed; stillness is quieter.

    ⚠ This test used to also assert retention_fast was LESS ducked than
    archival, from §5.2's "driving, barely ducked" intent - which that
    section set as an arithmetic offset and explicitly flagged as "not a
    new listening pass". A listening pass happened 2026-08-29
    (output_quality_pass.md §15.1) once the pause detector actually
    worked, and overturned it: at a 4 dB depth the bed had nothing to
    swell back into ("works, but not much noticeable change"), and 12/14
    dB "started to feel weird". 8 dB was chosen by ear. So retention_fast
    is now MORE ducked than archival, and the old inequality is gone
    deliberately - do not restore it from the prose in §5.2.
    """
    archival = resolve_music_gains("documentary_archival")
    assert archival == resolve_music_gains(None)
    assert archival.bed_gain_db == settings.music_bed_gain_db == -14.0
    assert archival.duck_gain_db == settings.music_duck_gain_db == -20.0

    fast = resolve_music_gains("retention_fast")
    assert fast.bed_gain_db == -10.0
    assert fast.duck_gain_db == -18.0
    # Ear-signed depth. The bed stays louder than archival's; what changed
    # is how far the music drops under the voice.
    assert fast.bed_gain_db > archival.bed_gain_db
    assert (fast.bed_gain_db - fast.duck_gain_db) == 8.0

    still = resolve_music_gains("stillness")
    assert still.bed_gain_db == -22.0
    assert still.duck_gain_db == -28.0
    assert still.bed_gain_db < archival.bed_gain_db

    assert resolve_music_gains("not_a_real_style") == archival


def test_a_zero_music_gain_override_is_honoured_not_treated_as_unset():
    """Same `or`-trap as R7: 0.0 dB is unity gain, a real mix value."""
    STYLE_PACING_BANDS["hypothetical_unity"] = StylePacingBand(
        name="hypothetical_unity",
        target_shot_duration_s=None,
        max_shots_override=None,
        music_bed_gain_db=0.0,
        music_duck_gain_db=0.0,
    )
    try:
        gains = resolve_music_gains("hypothetical_unity")
        assert gains.bed_gain_db == 0.0
        assert gains.duck_gain_db == 0.0
    finally:
        del STYLE_PACING_BANDS["hypothetical_unity"]


def test_a_zero_override_is_honoured_not_treated_as_unset():
    """The `x or y` trap R7 fixed: `0`/`0.0` is a legitimate override
    value (e.g. a future style with no per-shot ceiling), and must not
    silently fall back to the flat setting the way `or` would."""
    zero_band = StylePacingBand(
        name="hypothetical_zero",
        target_shot_duration_s=None,
        max_shots_override=0,
        min_shot_duration_s_override=0.0,
        max_shot_duration_s_override=0.0,
    )
    STYLE_PACING_BANDS["hypothetical_zero"] = zero_band
    try:
        min_s, max_s, shots = resolve_constraint_bundle("hypothetical_zero")
        assert min_s == 0.0
        assert max_s == 0.0
        assert shots == 0
    finally:
        del STYLE_PACING_BANDS["hypothetical_zero"]


# ---------------------------------------------------------------------------
# Feature B: archival_montage (style_extensions.md §4)
# ---------------------------------------------------------------------------


def test_archival_montage_resolves_its_decided_band():
    """§4.3's decided starting points: harder cutting than archival,
    ~46-shot budget, 1.2-4.5s bounds. These pin the registry values so a
    calibration pass (which SHOULD move them) shows up as a deliberate
    diff here, not silent drift."""
    bundle = resolve_constraint_bundle("archival_montage")
    assert bundle.min_shot_duration_s == 1.2
    assert bundle.max_shot_duration_s == 4.5
    assert bundle.max_shots_per_project == 46


def test_archival_montage_narration_speed_music_and_whoosh():
    """Speed below retention_fast's 1.4x; music more upfront than
    archival's measured mix but short of retention_fast.

    Whoosh is OFF as of 2026-08-27 — this assertion previously pinned
    `is True` on the assumption that "this is not the dense-cut style
    whoosh was disabled for". A real run disproved it: d3a4d00d (75s,
    39 shots) had 9 punch_in shots -> 18 whoosh events inside a ~41-event
    SFX layer, one every 1.8s. That is the same density problem
    analysis.md decision 5/5a disabled whoosh for on retention_fast;
    archival_montage did not exist then, so it inherited the default
    rather than the reasoning."""
    # 1.25 as of 2026-08-27 (raised from 1.15): the narration duration
    # cap is a rate limit of `max_video_duration_s / 31` per fragment,
    # and at 1.15x most candidate voices overshot it on a real 36-
    # fragment script. Still under retention_fast's 1.4x and at the top
    # of the documented ~1.15-1.25x quality ceiling.
    assert resolve_narration_speed("archival_montage") == 1.25
    assert resolve_narration_speed("archival_montage") < resolve_narration_speed(
        "retention_fast"
    )

    gains = resolve_music_gains("archival_montage")
    assert gains.bed_gain_db == -11.0
    assert gains.duck_gain_db == -15.0
    # Strictly between the measured archival mix and retention_fast's.
    assert settings.music_bed_gain_db < gains.bed_gain_db < -10.0

    assert resolve_sfx_whoosh_enabled("archival_montage") is False
    # The two 9:16 fast-cut styles now agree; the slower 16:9 styles,
    # where punch_in is rare, keep it.
    assert resolve_sfx_whoosh_enabled("retention_fast") is False
    assert resolve_sfx_whoosh_enabled("documentary_archival") is True
    assert resolve_sfx_whoosh_enabled("stillness") is True


def test_archival_montage_is_9_16_and_rejects_the_stillness_only_aspect_flag():
    """§4.6: natively vertical like retention_fast; `frame_aspect`
    remains a stillness-only opt-in."""
    fmt = resolve_render_format("archival_montage")
    assert (fmt.width, fmt.height) == (720, 1280)
    assert not fmt.is_landscape
    assert "only settable" in (frame_aspect_error("archival_montage", "9:16") or "")


def test_archival_montage_dead_stop_ceiling_agrees_with_but_is_independent_of_the_override():
    """Same R7 shape as retention_fast: max_fragment_duration_s (the
    pre-flight diagnostic, target * _DEAD_STOP_CEILING_MULTIPLIER) equals
    max_shot_duration_s_override today - two fields that agree, not one
    field serving both jobs."""
    band = STYLE_PACING_BANDS["archival_montage"]
    assert band.max_fragment_duration_s == 4.5
    assert band.max_shot_duration_s_override == 4.5
