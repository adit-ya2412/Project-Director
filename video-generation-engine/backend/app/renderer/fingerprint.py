"""Render fingerprint (M8 step 6, I5 - "rendering is a pure function").

Same fingerprint means the exact same inputs would produce the exact
same output bytes, so a render whose fingerprint matches one already on
disk is skipped entirely and the existing file is reused - this is how
I5 gets DEMONSTRATED (an actual before/after-byte comparison exists, see
tests/integration/test_render_determinism.py), not merely asserted in a
docstring.

Every genuine input to the pixels/samples that end up in the final file
is included: the canonical Timeline content (scenes, shots, camera,
transitions - everything `render_timeline` reads), every visual asset's
own content hash (not its path - two assets at different paths with
identical bytes must fingerprint the same), the narration audio actually
muxed in (if any), the music track actually muxed in (if any), the
render settings that actually affect the output pixels (width, height,
fps, pixel format - NOT `ffmpeg_binary`/`ffprobe_binary`, which are just
executable paths on this machine, not inputs to the encode), the audio
mix settings that actually affect the output SAMPLES (`music_bed_gain_db`/
`music_duck_gain_db` - read straight from config at mux time by
`app/renderer/music.py::mux_music`, never from the Timeline, so nothing
else here would ever catch a change to them), and the installed ffmpeg's
own version (a version bump can change encoder behaviour even given
byte-identical inputs, so it must invalidate old cache entries rather
than silently serving a render made by a different binary).

**R2 (2026-08-16): the mix gains were missing entirely, and it cost
real money.** `music_bed_gain_db`/`music_duck_gain_db` are read from
config at mux time (see `RenderStep.render_video`'s call into
`mux_music`) exactly like every other render setting above, but were
never part of this function's payload - so raising the bed gain and
re-rendering to listen returned the OLD, cached bytes at the OLD
(quieter) gain, with no re-encode and no error. The two live-testing
sessions this happened in only surfaced the bug at all because the
previous `final.mp4` had separately been deleted, so the cache lookup
missed on the absent file rather than on the fingerprint - the
fingerprint match itself was silent and wrong. Fixed by adding both
values to the payload below, unconditionally, the same way
`music_content_hash` is always present (as `None` when there is no
music) rather than only when relevant - I5's promise is "same
fingerprint -> provably identical output", so a value that CAN affect
output must be hashed even on a render where it happens not to (no
music selected, so the gains are moot for that particular file): the
cost of that is a possible false MISS on an unrelated config change,
never a false HIT, which is exactly the tolerance this module's own
closing paragraph already accepts for `music_plan`'s other fields. This
invalidates every fingerprint computed before this fix - correct and
harmless, since a cache MISS only ever means "render for real", not
"produce wrong output".

**Captions (2026-08-17), following the R2 pattern exactly.**
`burn_captions`/`caption_font_hash`/`cue_list_hash` are the same shape of
gap R2 fixed: `burn_captions`/`caption_font` are read from config at the
same point `music_bed_gain_db`/`music_duck_gain_db` are (see
`RenderStep.render_video`), and the actual cue text/timing depends on the
Timeline's narration content in a way this function cannot derive from
`timeline`/`narration_content_hashes` alone (those hash the AUDIO, not
the derived cue list - a segmentation-rule change or a burn on/off
toggle changes zero bytes of either). All three are present
unconditionally, `caption_font_hash`/`cue_list_hash` as `None` when
`burn_captions` is `False`, mirroring `music_content_hash`'s own "always
present, `None` when moot" rule - a caption-off render and a caption-on
render of the identical Timeline must never collide on one cache entry
(docs/14_Captions_Plan.md §6/§8.5).

**Watermark (2026-08-17), same pattern again.**
`watermark_enabled`/`watermark_asset_hash`/`watermark_params_hash`
mirror the captions fields exactly, for the identical reason: the logo
file's bytes and its position/size/opacity are real inputs to output
pixels that nothing else in this payload can see. `watermark_asset_hash`
is the vendored logo FILE's content hash, not its path (swapping the
logo must invalidate the cache); `watermark_params_hash` folds
position/margin/width/opacity into one value. Both `None` when
`watermark_enabled` is `False`.

**Parallax layers (illustrated_faceless.md F2, 2026-09-04), R2 named as
the likeliest way this ships broken.** `Shot.layers` is a new field on
`Shot`, so its creative half (role, prompt, asset_plan, drift_x, drift_y,
scale - "layer count, roles, drift rates, scale") rides into
`compute_render_fingerprint`/`compute_run_fingerprint` for FREE via the
existing full `timeline`/`shot` dumps below - the same way
`secondary_prompt`/`secondary_asset_plan` already do. What the dump
cannot see is a layer's resolved image BYTES (I2 - the Timeline carries
no media): `layer_content_hashes`/`layer_asset_hashes` are that hook,
same shape as `secondary_content_hashes`/`secondary_asset_hash` above.
`compute_shot_stream_fingerprint` is the one function in this module that
does NOT dump the whole `Shot` (it hand-picks fields), so `layers` is
added there explicitly - see that function's own docstring.

Bookkeeping fields (`version`, `parent_version`, `produced_by`, `status`,
`created_at`, `timeline_id`, `project_id`, `schema_version`) are
EXCLUDED from the hashed Timeline content - the same set
`TimelineService`'s own additive-only check already treats as
non-content (`_BOOKKEEPING_FIELDS`, `app/timeline/service.py`), for the
identical reason: none of them affect a single rendered pixel. Without
this, two projects with byte-for-byte identical scenes, creative
context, and music plan - a very real case for this codebase's own
test-fixture-driven development, where the same script gets re-planned
into a fresh project repeatedly - would never fingerprint the same,
purely because `project_id`/`timeline_id`/`version` differ. Excluding
them is what makes cross-project reuse possible at all, not just same-
project resume - and it can never cause a false HIT, since none of the
excluded fields can change what `render_timeline` actually draws.

Everything else is deliberately conservative: `music_plan`'s own
selection-input fields (mood, tempo, search_terms, licence_requirements)
are hashed too, even though only `selected_track.content_hash` (passed
separately as `music_content_hash`, sourced with the OTHER real media
inputs below) actually reaches the output bytes. That is a missed cache
opportunity, never a wrong one: I5's promise is "same fingerprint ->
provably identical output", not "maximally aggressive caching", and a
false MISS is safe where a false HIT would silently serve stale video.
"""

import asyncio
import hashlib
import json

from app.core.errors import PermanentError
from app.renderer.loudness import DEFAULT_LRA
from app.renderer.slideshow import RenderSettings
from app.renderer.split_screen import SPLIT_PANEL_FIT
from app.schemas.timeline import Shot, Timeline

# Mirrors `app.timeline.service._BOOKKEEPING_FIELDS` exactly (kept as its
# own local copy rather than an import, to avoid a renderer -> timeline
# peer-module dependency neither side otherwise needs) - fields the
# TimelineService itself stamps on every write, describing WHICH version
# this is, never planning/rendering content.
_TIMELINE_BOOKKEEPING_FIELDS = frozenset(
    {
        "schema_version",
        "timeline_id",
        "project_id",
        "version",
        "parent_version",
        "produced_by",
        "status",
        "created_at",
    }
)


async def get_ffmpeg_version(ffmpeg_binary: str) -> str:
    """The first line of `ffmpeg -version` (e.g. "ffmpeg version
    9.0-full_build-www.gyan.dev Copyright ...") - enough to distinguish
    genuinely different builds without hashing the entire, very long
    configuration banner."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg_binary,
        "-version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise PermanentError(f"{ffmpeg_binary} -version failed: {stderr.decode(errors='replace')}")
    first_line = stdout.decode(errors="replace").splitlines()[0] if stdout else ""
    return first_line.strip()


def _canonical_json(value: object) -> str:
    """Sorted keys, no incidental whitespace - the same dict must always
    serialise to the same bytes regardless of construction order (I5:
    "no unordered set/dict iteration when building" anything the output
    depends on)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_render_fingerprint(
    *,
    timeline: Timeline,
    asset_content_hashes: dict[str, str],
    narration_content_hashes: list[str],
    music_content_hash: str | None,
    render_settings: RenderSettings,
    music_bed_gain_db: float,
    music_duck_gain_db: float,
    music_gain_offset_db: float,
    music_amix_normalize: int,
    loudness_normalize: bool,
    loudness_target_lufs: float,
    loudness_true_peak_db: float,
    narration_level_match: bool,
    burn_captions: bool,
    caption_font_hash: str | None,
    cue_list_hash: str | None,
    duck_envelope_hash: str | None,
    watermark_enabled: bool,
    watermark_asset_hash: str | None,
    watermark_params_hash: str | None,
    burn_text_cards: bool,
    text_card_font_hash: str | None,
    sfx_content_hashes: list[str],
    sfx_gain_db: float,
    sfx_max_clip_s: float,
    sfx_diegetic_max_clip_s: float,
    sfx_diegetic_shot_carry_s: float,
    sfx_whoosh_enabled: bool,
    sfx_transition_structural_only: bool = False,
    sfx_normalize_target_db: float,
    sfx_kind_gain_overrides_db: dict[str, float | None],
    sfx_diegetic_normalize_target_lufs: float,
    sfx_diegetic_loudness_min_duration_s: float,
    sfx_diegetic_duck_depth_db: float,
    ffmpeg_version: str,
    secondary_content_hashes: dict[str, str] | None = None,
    shot_focal: dict[str, str] | None = None,
    layer_content_hashes: dict[str, list[str]] | None = None,
) -> str:
    timeline_document = timeline.model_dump(mode="json")
    content_only = {
        k: v for k, v in timeline_document.items() if k not in _TIMELINE_BOOKKEEPING_FIELDS
    }
    # R-C6: `approved_scenes` is a review record, not a pixel input.
    # It must not share the fingerprint with `render_style`/`grade_style`
    # (those stay hashed; dropping all of `metadata` would reopen R6).
    # Click order of per-scene approve must not fork the cache key.
    metadata = content_only.get("metadata")
    if isinstance(metadata, dict) and "approved_scenes" in metadata:
        metadata = dict(metadata)
        metadata.pop("approved_scenes", None)
        content_only = {**content_only, "metadata": metadata}
    payload = {
        "timeline": content_only,
        # R16: assignment, not a bag. A flat sorted list could not tell
        # the top panel from the bottom, nor shot A from shot B. Keyed
        # by shot_id in timeline order. Empty string when a panel is
        # missing, so a later resolve cannot cache-HIT the gap.
        "shot_media": [
            {
                "shot_id": shot.id,
                "hash": asset_content_hashes.get(shot.id, ""),
                "secondary_hash": (secondary_content_hashes or {}).get(shot.id, ""),
            }
            for shot in timeline.all_shots()
        ],
        # OQ-2 (2026-08-28): subject focal is model-derived from the
        # image, so shot_media's content hash does NOT cover it (R2).
        # R16 assignment: keyed by shot_id in timeline order. Empty
        # string when unresolved so a later resolve cannot cache-HIT
        # the gap. Present unconditionally.
        "shot_focal": [
            {
                "shot_id": shot.id,
                "focal": (shot_focal or {}).get(shot.id, ""),
            }
            for shot in timeline.all_shots()
        ],
        # illustrated_faceless.md F2 (2026-09-04), R2: a layer's own
        # creative fields (role, prompt, asset_plan, drift_x, drift_y,
        # scale - so "layer count, roles, drift rates, scale" the plan
        # names) already ride into `content_only["timeline"]` above for
        # free, via the same full `timeline.model_dump` every other
        # `Shot` field (prompt, camera, secondary_prompt, ...) already
        # gets - no separate entry needed for those, exactly as
        # `secondary_prompt`/`secondary_asset_plan` need none today. What
        # the timeline dump CANNOT see is the layer's resolved image
        # BYTES (I2 - Timeline carries no media): this entry is the
        # `shot_media`-shaped hook for that, keyed by shot_id, ordered to
        # match `Shot.layers`. Empty list when a shot has no layers or
        # when a caller has not wired layer resolution yet (every caller
        # today - this fingerprint function ships ahead of the render.py
        # wiring that would populate `layer_content_hashes` for real).
        "shot_layers": [
            {
                "shot_id": shot.id,
                "hashes": (layer_content_hashes or {}).get(shot.id, []),
            }
            for shot in timeline.all_shots()
        ],
        "narration_content_hashes": sorted(narration_content_hashes),
        "music_content_hash": music_content_hash,
        "render_settings": {
            "width": render_settings.width,
            "height": render_settings.height,
            "fps": render_settings.fps,
            "pixel_format": render_settings.pixel_format,
        },
        # R2 (2026-08-16): read from config at mux time
        # (`app/renderer/music.py::mux_music`), never from the Timeline -
        # the only two render inputs that used to have nowhere to be
        # caught by this function at all. Present unconditionally, same
        # as `music_content_hash` above, even on a render with no music
        # selected (where they happen not to affect this particular
        # file's bytes) - see this module's own docstring for why that
        # is a deliberately conservative choice, not an oversight.
        "music_bed_gain_db": music_bed_gain_db,
        "music_duck_gain_db": music_duck_gain_db,
        # Decision 7 (analysis.md, 2026-08-24): the uploaded track's dB
        # offset changes the mixed loudness directly, so flipping it must
        # miss the cache - same unconditional-presence rule as the gains
        # above (R2). 0.0 on every provider-selected track.
        "music_gain_offset_db": music_gain_offset_db,
        # OQ-1d (2026-08-28): mux_music's amix normalize flag. Default
        # ffmpeg normalize=1 attenuated narration ~−6 dB under any bed;
        # fixed to normalize=0. Hashed unconditionally (R2) so cached
        # pre-fix mixes cannot HIT.
        "music_amix_normalize": music_amix_normalize,
        # OQ-1a (2026-08-28): final-mix loudness target. Config knobs,
        # not measured values — pass-1 measurements are recomputed from
        # the same bytes (deterministic, ride in free). Unconditional
        # presence (R2), same rule as music_bed_gain_db.
        "loudness_normalize": loudness_normalize,
        "loudness_target_lufs": loudness_target_lufs,
        "loudness_true_peak_db": loudness_true_peak_db,
        # Constant LRA fed to loudnorm (not a Settings knob). Hashed so a
        # change cannot cache-HIT (same shape as split_panel_fit).
        "loudness_lra": DEFAULT_LRA,
        # OQ-1c (2026-08-28): per-scene narration mean-LUFS gain match
        # before concat. Flag only — measured gains derive from narration
        # bytes already in narration_content_hashes (do not hash LUFS).
        # Unconditional presence (R2).
        "narration_level_match": narration_level_match,
        # Captions (2026-08-17), same unconditional-presence rule as the
        # gains above - see this module's own docstring.
        "burn_captions": burn_captions,
        "caption_font_hash": caption_font_hash,
        "cue_list_hash": cue_list_hash,
        # OQ-1b (2026-08-28): alignment-derived duck windows are not
        # determined by scene structure alone (timeline dump) or by
        # narration audio bytes. When alignment is present the render
        # step hashes the canonical interval list (+ merge/ramp
        # constants); when absent this is None and the file-duration
        # fallback is fully determined by narration_content_hashes.
        # Unconditional presence (R2), None when no music / no
        # alignment / no intervals.
        "duck_envelope_hash": duck_envelope_hash,
        # Watermark (2026-08-17), same unconditional-presence rule.
        "watermark_enabled": watermark_enabled,
        "watermark_asset_hash": watermark_asset_hash,
        "watermark_params_hash": watermark_params_hash,
        # Text cards (2026-08-17), same unconditional-presence rule as
        # captions/watermark above - `burn_text_cards` is a `Settings`/
        # `RenderSettings` toggle, not Timeline content, so two renders of
        # the IDENTICAL Timeline with this flag on vs off must NOT
        # fingerprint identically (the R2 shape: a config value that can
        # change output bytes but has nowhere to be caught). Deliberately
        # NO separate cue-list hash here, unlike captions'
        # `cue_list_hash` - a text card's cue text, start, and end are
        # ALL already fully determined by data already inside `timeline`
        # above (`shot.text_card`, `duration_s`, `transition_out`), so
        # hashing a second, derived copy of the same information would be
        # redundant, not merely harmless. The one thing that legitimately
        # needs its own hash is the font FILE (`text_card_font_hash`,
        # mirroring `caption_font_hash`'s own reasoning exactly) -
        # swapping the vendored file must invalidate this fingerprint too.
        "burn_text_cards": burn_text_cards,
        "text_card_font_hash": text_card_font_hash,
        # SFX (plan §5.5). ⚠ `sfx_content_hashes` is REDUNDANT and kept
        # deliberately, not because it is load-bearing (§15.6 corrected
        # the reason this comment used to give): every clip hash is
        # already inside `SfxClipSelection.content_hash` in the timeline
        # document hashed above, so this entry restates it. Kept anyway
        # for the same reason `music_content_hash` is - one obvious line
        # per real mux input, so the next person adding a mix stage sees
        # the pattern rather than having to prove the timeline dump
        # already covers them. `sfx_gain_db` is the entry that genuinely
        # has nowhere else to live: it is config-time, like
        # music_bed_gain_db (R2). Both unconditional.
        "sfx_content_hashes": sorted(sfx_content_hashes),
        "sfx_gain_db": sfx_gain_db,
        # R12: `atrim=0:{sfx_max_clip_s}` is a real mix input, same shape
        # as `sfx_gain_db` / R2. Unconditional so a config bump cannot
        # cache-HIT the old, shorter mix.
        "sfx_max_clip_s": sfx_max_clip_s,
        # long_form_direction.md A8: diegetic's OWN ceiling (R12's rule
        # applied a second time - a real mix input with nowhere else to
        # live). Unconditional so a config bump cannot cache-HIT the old,
        # shorter (or longer) diegetic mix, even on a project with no
        # diegetic clips yet.
        "sfx_diegetic_max_clip_s": sfx_diegetic_max_clip_s,
        # A15 (long_form_direction.md, 2026-09-01): the per-shot ceiling
        # is now `min(sfx_diegetic_max_clip_s, shot.duration_s + this)`
        # (`_diegetic_ceiling_s`) - `shot.duration_s` itself already rides
        # in via the timeline document dump above, but this carry
        # allowance does not live anywhere else, same R2 shape as
        # `sfx_diegetic_max_clip_s` immediately above.
        "sfx_diegetic_shot_carry_s": sfx_diegetic_shot_carry_s,
        # Decisions 5 + 5a (analysis.md, 2026-08-24): the per-style WHOOSH
        # gate decides which overlay events get mixed at all, so flipping
        # it changes output bytes. Style-derived (render_style in the
        # timeline dump above already moves it indirectly), but hashed
        # explicitly anyway per this module's own R2 rule: one obvious
        # line per real mux input, present unconditionally.
        "sfx_whoosh_enabled": sfx_whoosh_enabled,
        # A15: a per-style gate that silences the swoosh on plain
        # dissolves. Changes real output bytes, so R2 requires it here.
        "sfx_transition_structural_only": sfx_transition_structural_only,
        # C3c (analysis.md, decision 5b): the normalization target and the
        # per-kind dB offsets are real mix inputs - changing either
        # changes output samples even with byte-identical clips.
        # Unconditional presence per this module's R2 rule. Clip peaks
        # and durations themselves ride in via the timeline document
        # above, so they need no separate entry here.
        "sfx_normalize_target_db": sfx_normalize_target_db,
        "sfx_kind_gain_overrides_db": sfx_kind_gain_overrides_db,
        # A11 (long_form_direction.md, 2026-09-01): DIEGETIC's loudness
        # target/floor and the diegetic-cue duck depth are real mix
        # inputs with nowhere else to live - same R2 shape as
        # `sfx_normalize_target_db` immediately above. `clip.loudness_lufs`
        # itself needs no separate entry here: it rides in via
        # `SfxClipSelection` inside the timeline document dump, exactly
        # like `peak_dbfs`/`duration_s` already do.
        "sfx_diegetic_normalize_target_lufs": sfx_diegetic_normalize_target_lufs,
        "sfx_diegetic_loudness_min_duration_s": sfx_diegetic_loudness_min_duration_s,
        "sfx_diegetic_duck_depth_db": sfx_diegetic_duck_depth_db,
        "ffmpeg_version": ffmpeg_version,
        # Padded-panel verdict 2026-08-20: crop-to-fill. A letterbox
        # revert must miss every cached split encode (§7).
        "split_panel_fit": SPLIT_PANEL_FIT,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_run_fingerprint(
    *,
    shots: list[Shot],
    shot_content_hashes: dict[str, str],
    render_settings: RenderSettings,
    ffmpeg_version: str,
    secondary_content_hashes: dict[str, str] | None = None,
    shot_focal: dict[str, str] | None = None,
    layer_content_hashes: dict[str, list[str]] | None = None,
) -> str:
    """Fingerprint of one `group_into_runs` run (Track C C3 remainder).

    The silent-video encode is per-run; captions/watermark/grade/music/
    narration land after concat and are NOT in this hash. Shot order is
    the run's order (not sorted): swapping two shots' media must miss.
    `kind: run_v1` keeps a run hash from colliding with a full-render
    hash of an otherwise-similar payload.
    """
    payload = {
        "kind": "run_v1",
        # Full dump is conservative (N3): prompt/intent/asset_plan/text_card
        # do not affect the silent per-run encode, so a prompt-only edit
        # misses this cache. Safe direction; the shot-stream cache absorbs
        # the re-encode when camera/media did not change.
        "shots": [shot.model_dump(mode="json") for shot in shots],
        "assets": [
            {
                "shot_id": shot.id,
                "hash": shot_content_hashes.get(shot.id),
                # Split-screen bottom panel. Empty string when the shot
                # has no second still so a later resolve cannot cache-HIT
                # the single-image encode (R2 / §7).
                "secondary_hash": (secondary_content_hashes or {}).get(shot.id, ""),
                # OQ-2: focal is not in the shot dump (not on Camera).
                "focal": (shot_focal or {}).get(shot.id, ""),
                # illustrated_faceless.md F2, R2: layer image bytes, same
                # shape as secondary_hash immediately above - `layers`'
                # own creative fields (role/prompt/asset_plan/drift/
                # scale) already ride in via the full `shot.model_dump`
                # below, but the resolved image bytes never do (I2).
                "layer_hashes": (layer_content_hashes or {}).get(shot.id, []),
            }
            for shot in shots
        ],
        "render_settings": {
            "width": render_settings.width,
            "height": render_settings.height,
            "fps": render_settings.fps,
            "pixel_format": render_settings.pixel_format,
        },
        "ffmpeg_version": ffmpeg_version,
        "split_panel_fit": SPLIT_PANEL_FIT,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_shot_stream_fingerprint(
    *,
    shot: Shot,
    asset_hash: str,
    render_settings: RenderSettings,
    ffmpeg_version: str,
    secondary_asset_hash: str = "",
    focal: str = "",
    layer_asset_hashes: list[str] | None = None,
) -> str:
    """Fingerprint of one shot's normalised/zoompanned stream (C3 (d)).

    Transition-out is excluded: it only affects the xfade pass, so a
    dissolve-duration edit must reuse this file. Camera and duration
    stay in — they change the pixels. `focal` (OQ-2) is hashed too:
    the asset content hash does not cover a model-derived aim point.

    illustrated_faceless.md F2, R2: unlike `compute_render_fingerprint`/
    `compute_run_fingerprint` above, this function does NOT dump the
    whole `Shot` - it hand-picks the fields that affect this ONE shot's
    own stream (deliberately excluding `transition_out`, per the
    docstring above). That means `Shot.layers` needs an EXPLICIT entry
    here or a layer-only edit would silently miss this cache (the R2 gap
    this whole fingerprint module exists to close) - `layers`' own
    creative fields (role/prompt/asset_plan/drift_x/drift_y/scale, i.e.
    "layer count, roles, drift rates, scale") are dumped directly since
    they are already on `shot`; `layer_asset_hashes` is the resolved-
    image-bytes half (I2 - not on the Timeline), same shape as
    `secondary_asset_hash` immediately above.
    """
    payload = {
        "kind": "shot_stream_v1",
        "shot_id": shot.id,
        "duration_s": shot.duration_s,
        "camera": shot.camera.model_dump(mode="json"),
        "asset_hash": asset_hash,
        "secondary_asset_hash": secondary_asset_hash,
        "focal": focal,
        "layers": [layer.model_dump(mode="json") for layer in shot.layers],
        "layer_asset_hashes": list(layer_asset_hashes or []),
        "render_settings": {
            "width": render_settings.width,
            "height": render_settings.height,
            "fps": render_settings.fps,
            "pixel_format": render_settings.pixel_format,
        },
        "ffmpeg_version": ffmpeg_version,
        "split_panel_fit": SPLIT_PANEL_FIT,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
