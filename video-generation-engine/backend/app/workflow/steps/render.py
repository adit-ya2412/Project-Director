"""Step 4: Timeline + resolved media -> MP4.

Any shot whose binding never resolved (missing, pending, or failed) gets
a placeholder frame rather than blocking the render - the same
per-task failure isolation `ResolveAssetsStep` applies (Principle 10).

## Narration (M8 step 3)

The silent visual path (`render_timeline`, unchanged) always runs first,
to a work-directory file rather than straight to `final.mp4`. Whether
that silent file becomes the final output as-is, or gets narration muxed
onto it, is decided by `_resolve_narration_audio` - see its docstring for
exactly which projects get audio and which stay silent, and why both are
correct rather than one being a fallback for the other. The renderer
itself (`app/renderer/audio.py`) stays a pure function: this step reads
narration from paths resolved here and passed in, the same contract
`RenderStep` already has with `shot_images` - it never queries the
database from inside `app/renderer/`.

## Music (M8 step 4)

A third, final pass: whatever the narration stage produced (narrated or
silent) gets music mixed in - or doesn't - decided by
`_resolve_music_track`, mirroring `_resolve_narration_audio`'s own
DRY_RUN/no-op reasoning exactly. `app/renderer/music.py` stays a pure
function too: it reads a video path, a music path, and (optionally) the
same ordered narration paths this step already resolved - never the
database.

## The fingerprint (M8 step 6, I5)

Before doing any of the above, `render_video` computes a fingerprint of
every real input to the output bytes (`app/renderer/fingerprint.py`) and
checks `render` (`RenderRepository`) for an existing COMPLETED render
with that exact fingerprint. A hit means this exact content, at this
exact quality, has provably already been produced - its bytes are copied
into this project's own output path (never a live cross-project file
reference: if the source project's storage is ever cleaned up, this
project's own copy must still exist) and the entire render/mux pipeline
below is skipped. A miss renders for real, then records a new `render`
row so a later, identical request - this project's own resumed run, or a
different project that happens to reproduce byte-identical content - can
reuse it.

## Draft mode (M8 step 6)

`render_video` is parameterised by `RenderSettings` and an output
filename specifically so the SAME function serves both the automated
final render (`RenderStep`, `settings.render_width/height`,
`final.mp4`) and an on-demand low-res preview
(`POST /projects/{id}/render/draft`, `settings.draft_width/height`,
`draft.mp4`) - "always render a fast draft first" (M8 Advice). Draft and
final can never collide on one fingerprint/cache entry: width/height are
themselves part of the fingerprint, so the two modes are provably
different renders even of the identical Timeline content.
"""

import uuid as uuid_module
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.focal import format_focal_fingerprint, resolve_shot_focals
from app.assets.sfx_levels import (
    diegetic_effective_gain_db,
    effective_gain_db,
    end_aligned_trim_start,
)
from app.core.config import settings
from app.core.errors import EngineError, PermanentError, TransientError
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
from app.models.narration import NarrationModel
from app.providers.elevenlabs import compute_narration_content_hash
from app.renderer.audio import mux_narration
from app.renderer.captions import (
    FONT_DIR,
    CaptionStyle,
    caption_font_content_hash,
    cue_list_content_hash,
    derive_caption_cues,
    serialize_ass,
    subtitles_filter_fragment,
)
from app.renderer.fingerprint import compute_render_fingerprint, get_ffmpeg_version
from app.renderer.grading import grade_filter_fragment
from app.renderer.loudness import apply_loudness_target
from app.renderer.music import (
    assemble_act_bed,
    duck_envelope_content_hash,
    mux_music,
    offset_bed_and_duck_gain_db,
    speaking_intervals_from_alignment,
)
from app.renderer.placeholder import render_placeholder
from app.renderer.sfx import SfxOverlay, derive_sfx_events, mux_sfx
from app.renderer.slideshow import RenderSettings, probe_duration_seconds, render_timeline
from app.renderer.text_cards import (
    TextCardStyle,
    derive_text_card_cues,
    serialize_text_card_ass,
    text_card_filter_fragment,
)
from app.renderer.video_filters import apply_video_filters
from app.renderer.watermark import (
    LOGO_PATH,
    watermark_content_hash,
    watermark_filter_fragment,
)
from app.renderer.watermark import (
    watermark_params_hash as compute_watermark_params_hash,
)
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.repositories.render_repository import RenderRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.schemas.project import ProjectStatus
from app.schemas.timeline import SfxKind, Timeline
from app.script.styles import (
    resolve_music_gains,
    resolve_narration_speed,
    resolve_render_format,
    resolve_sfx_whoosh_enabled,
    resolve_transition_sfx_structural_only,
)
from app.timeline.acts import act_time_ranges, music_content_hash_for
from app.workflow.context import RunContext
from app.workflow.step import StepResult
from app.workflow.steps.resolve_assets import layer_prompt_hash


class RenderStep:
    name = "render"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        project = await ctx.repo.get(ctx.project_id)
        if project is None or not project.video_path:
            return False
        video_path = Path(project.video_path)
        if not video_path.exists():
            return False

        # A video file existing isn't enough: if resolve_assets re-resolved
        # any shot (e.g. a fixed provider bug turned a placeholder into a
        # real photo) after this file was rendered, the file is stale and
        # must be redone - otherwise a retry silently ships the OLD render
        # forever, even though every upstream shot binding improved.
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return False
        binding_repo = ShotBindingRepository(ctx.session)
        bindings = await binding_repo.list_for_version(
            uuid_module.UUID(ctx.project_id), timeline.version
        )
        if not bindings:
            return True
        latest_binding_update = max(b.updated_at for b in bindings)
        video_mtime = datetime.fromtimestamp(video_path.stat().st_mtime, tz=UTC)
        return video_mtime >= latest_binding_update

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to render")

        frame = resolve_render_format(
            timeline.metadata.render_style,
            frame_aspect=timeline.metadata.frame_aspect,
        )
        render_settings = RenderSettings(
            width=frame.width,
            height=frame.height,
            fps=settings.render_fps,
            pixel_format=settings.render_pixel_format,
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
            burn_captions=settings.burn_captions,
            watermark_enabled=settings.watermark_enabled,
            burn_text_cards=settings.burn_text_cards,
        )
        try:
            output_path = await render_video(
                ctx, timeline, render_settings, output_filename="final.mp4"
            )
        except TransientError as exc:
            return StepResult(outcome="retry", error=str(exc))
        except EngineError as exc:
            return StepResult(outcome="failed", error=str(exc))

        project = await ctx.repo.get(ctx.project_id)
        if project is None:
            return StepResult(outcome="failed", error="project vanished mid-render")
        project.video_path = str(output_path)
        project.status = ProjectStatus.RENDERING
        await ctx.repo.update(project)
        return StepResult(outcome="ok")


async def render_video(
    ctx: RunContext,
    timeline: Timeline,
    render_settings: RenderSettings,
    *,
    output_filename: str,
    is_draft: bool = False,
) -> Path:
    """The whole render/mux pipeline, parameterised so `RenderStep` (the
    automated `final.mp4`) and the on-demand draft endpoint (`draft.mp4`,
    M8 step 6) are the same code path, never two - see this module's own
    docstring for why. Checks the fingerprint (I5) BEFORE doing any real
    work; a hit copies an existing render's bytes into this project's own
    output path and returns immediately, a miss renders for real and then
    records one."""
    project_uuid = uuid_module.UUID(ctx.project_id)
    binding_repo = ShotBindingRepository(ctx.session)
    bindings_by_shot = {
        b.shot_id: b for b in await binding_repo.list_for_version(project_uuid, timeline.version)
    }

    project_dir = settings.storage_root / ctx.project_id
    work_dir = project_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path = project_dir / "renders" / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    media_content_hashes: dict[str, str] = {}
    secondary_content_hashes: dict[str, str] = {}
    shot_images: dict[str, Path] = {}
    shot_secondary_images: dict[str, Path] = {}
    # illustrated_faceless.md F2b (2026-09-05): `Shot.layers`' resolved-
    # image counterpart to `shot_secondary_images` above. Populated below
    # by recomputing each layer's `layer_prompt_hash` (the SAME cache key
    # `ResolveAssetsStep`'s own `generate_layer_image_real`/
    # `_generate_layer_fake` compute - never a second copy of that
    # arithmetic, the R1 lesson) and looking the resulting clip up by
    # content hash - there is no per-layer binding column to read a clip
    # id FROM (see `layer_prompt_hash`'s own docstring for why), so this
    # is the one place a layer's resolved path is found, on every render.
    # A shot whose layer clip is missing (never generated, or generation
    # failed and was isolated per-shot) simply gets no entry here, which
    # is exactly what `should_composite_parallax`'s own missing-input
    # degrade rule already expects.
    shot_layer_images: dict[str, list[Path]] = {}
    layer_content_hashes: dict[str, list[str]] = {}
    clip_repo = GeneratedClipRepository(ctx.session)
    for shot in timeline.all_shots():
        binding = bindings_by_shot.get(shot.id)
        path, content_hash = await _resolved_path_and_hash(ctx.session, binding)
        if content_hash is not None:
            media_content_hashes[shot.id] = content_hash
        if path is None:
            path = work_dir / f"{shot.id}_placeholder.png"
            path.write_bytes(
                render_placeholder(shot.id, render_settings.width, render_settings.height)
            )
        # Classification (still vs a real motion clip, A1) and the
        # GIF-flatten gate this comment used to describe both now live in
        # `render_timeline` itself - the one place that needs to make
        # that decision - see that function's own docstring.
        shot_images[shot.id] = path
        sec_path, sec_hash = await _resolved_secondary_path_and_hash(ctx.session, binding)
        if sec_hash is not None:
            secondary_content_hashes[shot.id] = sec_hash
        if sec_path is not None:
            shot_secondary_images[shot.id] = sec_path
        if shot.layers:
            layer_paths: list[Path] = []
            layer_hashes: list[str] = []
            for index, layer in enumerate(shot.layers):
                phash = layer_prompt_hash(
                    shot,
                    layer,
                    layer_index=index,
                    project_uuid=project_uuid,
                    creative_context=timeline.creative_context,
                    style=timeline.metadata.render_style,
                    frame_aspect=timeline.metadata.frame_aspect,
                )
                clip = await clip_repo.get_by_prompt_hash(phash)
                if clip is None or not clip.local_path or not Path(clip.local_path).exists():
                    layer_paths = []
                    break
                layer_paths.append(Path(clip.local_path))
                layer_hashes.append(phash)
            if layer_paths:
                shot_layer_images[shot.id] = layer_paths
                layer_content_hashes[shot.id] = layer_hashes

    # OQ-2: resolve subject focals once from asset sidecars (RV2). Missing
    # sidecar → None → centre Ken Burns + logged fallback. Never re-read
    # at the zoompan call site.
    shot_focals = resolve_shot_focals(
        shot_ids=[shot.id for shot in timeline.all_shots()],
        content_hashes=media_content_hashes,
        assets_dir=project_dir / "assets",
    )
    shot_focal_fingerprints = {
        shot_id: format_focal_fingerprint(focal) for shot_id, focal in shot_focals.items()
    }

    narration_rows = await _resolve_narration_rows(ctx.session, timeline)
    narration_paths = (
        [Path(row.local_path) for row in narration_rows] if narration_rows is not None else None
    )
    narration_content_hashes = (
        [row.content_hash for row in narration_rows] if narration_rows is not None else []
    )
    music_segments = _music_segments(timeline, ctx.project_id)
    music_content_hash = music_content_hash_for(timeline) if music_segments is not None else None

    # Captions (2026-08-17): mirrors the R2 gain pattern exactly (see
    # fingerprint.py's own docstring) - cues are derived here, before the
    # cache-hit check, purely so their hash can be fingerprinted; they are
    # only actually serialised/burned below on a real cache MISS.
    caption_cues = (
        derive_caption_cues(timeline, narration_rows)
        if render_settings.burn_captions and narration_rows is not None
        else None
    )
    cue_hash = cue_list_content_hash(caption_cues) if caption_cues is not None else None
    caption_font_hash = (
        caption_font_content_hash(settings.caption_font) if render_settings.burn_captions else None
    )

    # OQ-1b (2026-08-28): alignment-derived duck windows are pure (no
    # ffmpeg) — derive before the cache check so duck_envelope_hash can
    # be fingerprinted, same reason captions derive cues here. When
    # alignment is absent the hash is None; file-duration fallback is
    # fully determined by narration_content_hashes already in the
    # fingerprint.
    alignment_by_scene = (
        [row.alignment for row in narration_rows] if narration_rows is not None else None
    )
    if music_content_hash is not None and alignment_by_scene is not None:
        duck_intervals = speaking_intervals_from_alignment(alignment_by_scene)
        duck_envelope_hash = duck_envelope_content_hash(duck_intervals) if duck_intervals else None
    else:
        duck_envelope_hash = None

    # Watermark (docs/plans/watermark_implementation_plan.md §4): same
    # unconditional-presence rule as captions - both hashes are computed
    # here, before the cache check, purely so they reach the fingerprint;
    # the overlay itself is only actually built below on a real MISS.
    watermark_asset_hash = watermark_content_hash() if render_settings.watermark_enabled else None
    watermark_params_hash_value = (
        compute_watermark_params_hash(
            position=settings.watermark_position,
            width_fraction=settings.watermark_width_fraction,
            margin_fraction=settings.watermark_margin_fraction,
            opacity=settings.watermark_opacity,
        )
        if render_settings.watermark_enabled
        else None
    )

    # Text cards (motion_new_styles_and_long_form_videos.md §2.6, Tier 2,
    # 2026-08-17): cues are derived here, before the cache check, same
    # reasoning as captions above - the cue TEXT itself needs no separate
    # fingerprint entry (see fingerprint.py's own comment for why: it is
    # already fully determined by data already in `timeline`), but the
    # font file and the `burn_text_cards` TOGGLE do, since neither lives
    # in the Timeline.
    text_card_cues = derive_text_card_cues(timeline) if render_settings.burn_text_cards else []
    text_card_font_hash = (
        caption_font_content_hash(settings.caption_font)
        if render_settings.burn_text_cards
        else None
    )

    ffmpeg_version = await get_ffmpeg_version(render_settings.ffmpeg_binary)
    # Leftover item 5: style-owned mix. Resolve once so the fingerprint
    # and the mux_music call cannot drift (R2's own lesson).
    music_gains = resolve_music_gains(timeline.metadata.render_style)
    # Decisions 5 + 5a (analysis.md, 2026-08-24): resolve ONCE beside the
    # music gains and hand the SAME value both to the fingerprint below
    # and to `_sfx_overlays`/`derive_sfx_events` further down - one
    # resolution feeding both consumers is what makes drift structurally
    # impossible, the same pattern as `music_gains` (review of P2,
    # analysis.md RV2; leftover item 5 / R2's own lesson).
    sfx_whoosh_enabled = resolve_sfx_whoosh_enabled(timeline.metadata.render_style)
    # A15: resolved ONCE here, same RV2 discipline as the whoosh gate -
    # this single value must reach both `compute_render_fingerprint` and
    # `derive_sfx_events`, or the cache serves a mix the derivation would
    # not produce.
    sfx_transition_structural_only = resolve_transition_sfx_structural_only(
        timeline.metadata.render_style
    )
    # Decision 7 (analysis.md, 2026-08-24): the uploaded track's dB offset
    # (0.0 for every provider-selected track). Resolved once beside the
    # style gains so the fingerprint below and the mux_music call share
    # it - same single-resolution pattern as `music_gains`.
    music_gain_offset_db = (
        timeline.music_plan.selected_track.gain_offset_db
        if timeline.music_plan is not None and timeline.music_plan.selected_track is not None
        else 0.0
    )
    # OQ-1d (2026-08-28): mux_music amix normalize=0. Constant resolved
    # once beside music_gains so fingerprint and filter cannot drift.
    music_amix_normalize = 0
    # OQ-1a (2026-08-28): final-mix loudness target. Resolve ONCE beside
    # music_gains so the fingerprint and apply_loudness_target share the
    # same values (RV2).
    loudness_normalize = settings.loudness_normalize
    loudness_target_lufs = settings.loudness_target_lufs
    loudness_true_peak_db = settings.loudness_true_peak_db
    # OQ-1c (2026-08-28): per-scene narration level match. Resolve ONCE
    # so the fingerprint and mux_narration share the same value (RV2).
    narration_level_match = settings.narration_level_match
    fingerprint = compute_render_fingerprint(
        timeline=timeline,
        asset_content_hashes=media_content_hashes,
        secondary_content_hashes=secondary_content_hashes,
        narration_content_hashes=narration_content_hashes,
        music_content_hash=music_content_hash,
        render_settings=render_settings,
        # R2 (2026-08-16): these are a real mux input. Style-resolved
        # as of leftover item 5; still hashed unconditionally.
        music_bed_gain_db=music_gains.bed_gain_db,
        music_duck_gain_db=music_gains.duck_gain_db,
        music_gain_offset_db=music_gain_offset_db,
        music_amix_normalize=music_amix_normalize,
        loudness_normalize=loudness_normalize,
        loudness_target_lufs=loudness_target_lufs,
        loudness_true_peak_db=loudness_true_peak_db,
        narration_level_match=narration_level_match,
        burn_captions=render_settings.burn_captions,
        caption_font_hash=caption_font_hash,
        cue_list_hash=cue_hash,
        duck_envelope_hash=duck_envelope_hash,
        watermark_enabled=render_settings.watermark_enabled,
        watermark_asset_hash=watermark_asset_hash,
        watermark_params_hash=watermark_params_hash_value,
        burn_text_cards=render_settings.burn_text_cards,
        text_card_font_hash=text_card_font_hash,
        sfx_content_hashes=_sfx_content_hashes(timeline),
        sfx_gain_db=settings.sfx_gain_db,
        sfx_max_clip_s=settings.sfx_max_clip_s,
        sfx_diegetic_max_clip_s=settings.sfx_diegetic_max_clip_s,
        sfx_diegetic_shot_carry_s=settings.sfx_diegetic_shot_carry_s,
        sfx_whoosh_enabled=sfx_whoosh_enabled,
        sfx_transition_structural_only=sfx_transition_structural_only,
        # C3c (analysis.md, decision 5b): normalization target + per-kind
        # offsets are real mix inputs - changing either changes output
        # samples even with byte-identical clips. Unconditional presence
        # per the R2 rule (clip peaks/durations ride in via the timeline
        # document above; these knobs live outside it).
        sfx_normalize_target_db=settings.sfx_normalize_target_db,
        sfx_kind_gain_overrides_db={
            "whoosh": settings.sfx_whoosh_gain_db,
            "stinger": settings.sfx_stinger_gain_db,
            "transition": settings.sfx_transition_gain_db,
            "diegetic": settings.sfx_diegetic_gain_db,
        },
        # A11 (long_form_direction.md, 2026-09-01): DIEGETIC's loudness
        # normalisation target/floor and the diegetic-cue duck depth are
        # config-time values with nowhere else to live - same R2 shape as
        # `sfx_normalize_target_db` above. `clip.loudness_lufs` itself
        # rides in via the timeline document dump (SfxClipSelection), not
        # here - same pattern as `peak_dbfs`/`duration_s` already follow.
        sfx_diegetic_normalize_target_lufs=settings.sfx_diegetic_normalize_target_lufs,
        sfx_diegetic_loudness_min_duration_s=settings.sfx_diegetic_loudness_min_duration_s,
        sfx_diegetic_duck_depth_db=settings.sfx_diegetic_duck_depth_db,
        ffmpeg_version=ffmpeg_version,
        shot_focal=shot_focal_fingerprints,
        layer_content_hashes=layer_content_hashes,
    )

    render_repo = RenderRepository(ctx.session)
    cached = await render_repo.get_completed_by_fingerprint(fingerprint)
    if cached is not None and cached.output_path and Path(cached.output_path).exists():
        # Same fingerprint == provably the same output bytes (I5) - copy
        # rather than reference the other render's path directly, so this
        # project's own file survives independently of whatever happens
        # to the source project's storage later.
        output_path.write_bytes(Path(cached.output_path).read_bytes())
    else:
        # The silent video always lands in the work dir first, never at
        # `output_path` directly - `narration_pairs`/`music_path` above
        # decide whether that silent file simply BECOMES the final
        # output, or gets narration/music muxed onto it in further passes
        # (M8 steps 3-4). Either way `render_timeline`'s own graph
        # (crossfades, hard cuts, Ken Burns) is exactly what it always was.
        silent_path = work_dir / f"silent_{output_path.stem}.mp4"
        captioned_path = work_dir / f"captioned_{output_path.stem}.mp4"
        narrated_path = work_dir / f"narrated_{output_path.stem}.mp4"
        await render_timeline(
            timeline,
            shot_images,
            render_settings,
            silent_path,
            work_dir=work_dir,
            shot_secondary_images=shot_secondary_images,
            shot_focals=shot_focals,
            shot_layer_images=shot_layer_images,
        )

        # The "video filter pass" (docs/plans/watermark_implementation_plan.md
        # §1): captions and the watermark are two independent concerns that
        # happen to share the one video re-encode neither can avoid
        # (subtitles=/overlay= both require it). Composed as filter_complex
        # FRAGMENTS chained through a running (label, extra-inputs) pair,
        # never as two separate ffmpeg passes - done here, once, on the
        # smaller silent file, before narration/music muxing (both of which
        # stream-copy video and would otherwise force a second re-encode or
        # have to run before this one).
        #
        # Grade (motion_new_styles_and_long_form_videos.md §2.4, Tier 1,
        # 2026-08-17) joins the SAME pass, FIRST in the chain - text and
        # the watermark sit crisp on top of the graded image, not graded
        # themselves. See `app/renderer/grading.py`'s own docstring for
        # why this needs no new fingerprint parameter: `render_style` is
        # already part of `compute_render_fingerprint`'s payload via the
        # timeline document dump, and the grade itself is a fixed
        # code-level lookup, not an independently-tunable config value.
        filter_fragments: list[str] = []
        extra_inputs: list[Path] = []
        current_label = "0:v"

        # R5 fix (§13.5, 2026-08-18): `grade_style` overrides `render_style`
        # for grading purposes ONLY, when a human has explicitly set one via
        # `POST /{project_id}/grade` - the mutable knob that lets the grade
        # be re-iterated after planning/rendering without touching anything
        # planner-facing. `None` (the common case) falls through to
        # `render_style` exactly as before this fix.
        grade_fragment = grade_filter_fragment(
            timeline.metadata.grade_style or timeline.metadata.render_style,
            current_label,
            "graded",
        )
        if grade_fragment is not None:
            filter_fragments.append(grade_fragment)
            current_label = "graded"

        # Text cards (§2.6, Tier 2) BEFORE captions: a title card is
        # centered (ASS Alignment=5) and captions sit in the bottom band
        # clear of platform UI (Alignment=2) - they occupy different
        # areas of the frame in the normal case, so this ordering is
        # about the rare overlap, not the common one: spoken captions
        # stay legible on top if a text card and a caption ever do
        # collide on the same frame.
        if text_card_cues:
            card_ass_path = work_dir / f"{output_path.stem}_card.ass"
            card_style = TextCardStyle(
                resolution=(render_settings.width, render_settings.height),
                font_family=settings.caption_font,
            )
            card_ass_path.write_text(
                serialize_text_card_ass(text_card_cues, card_style), encoding="utf-8"
            )
            filter_fragments.append(
                text_card_filter_fragment(current_label, "carded", card_ass_path, FONT_DIR)
            )
            current_label = "carded"

        if caption_cues is not None:
            ass_path = work_dir / f"{output_path.stem}.ass"
            style = CaptionStyle(
                resolution=(render_settings.width, render_settings.height),
                font_family=settings.caption_font,
            )
            ass_path.write_text(serialize_ass(caption_cues, style), encoding="utf-8")
            filter_fragments.append(
                subtitles_filter_fragment(current_label, "captioned", ass_path, FONT_DIR)
            )
            current_label = "captioned"

        if render_settings.watermark_enabled:
            extra_inputs.append(LOGO_PATH)
            logo_input_index = len(extra_inputs)  # video is always input 0
            filter_fragments.append(
                watermark_filter_fragment(
                    current_label,
                    "watermarked",
                    logo_input_index,
                    frame_width=render_settings.width,
                    position=settings.watermark_position,
                    width_fraction=settings.watermark_width_fraction,
                    margin_fraction=settings.watermark_margin_fraction,
                    opacity=settings.watermark_opacity,
                )
            )
            current_label = "watermarked"

        if not filter_fragments:
            silent_path.replace(captioned_path)
        else:
            await apply_video_filters(
                silent_path,
                captioned_path,
                render_settings,
                extra_inputs=extra_inputs,
                filter_complex=";".join(filter_fragments),
                output_label=current_label,
            )

        if narration_paths is None:
            captioned_path.replace(narrated_path)
        else:
            await mux_narration(
                captioned_path,
                narration_paths,
                narrated_path,
                render_settings,
                level_match=narration_level_match,
            )

        # Both intermediates live in `work_dir`, never beside the finished
        # file in `renders/` (§15.6): every other stage of this pipeline
        # already stages through the work directory, and `renders/` is
        # the directory a human (and `GET /projects/{id}/video`) treats as
        # "the outputs" - a half-mixed `_pre_sfx_final.mp4` sitting there
        # is indistinguishable by name from a real render. OQ-1a's
        # pre_loudness intermediate follows the same rule.
        sfx_overlays = _sfx_overlays(
            timeline,
            ctx.project_id,
            fps=render_settings.fps,
            whoosh_enabled=sfx_whoosh_enabled,
            transition_structural_only=sfx_transition_structural_only,
        )
        # A11 (long_form_direction.md, 2026-09-01): computed from the
        # TIMELINE (never the SFX audio - it does not exist at this point
        # in the pipeline, narration -> music -> sfx), so this is safe to
        # resolve before `mux_music` runs even though `mux_sfx` itself is
        # still several lines below.
        diegetic_duck_windows = _diegetic_duck_windows(
            timeline,
            fps=render_settings.fps,
            whoosh_enabled=sfx_whoosh_enabled,
            transition_structural_only=sfx_transition_structural_only,
        )
        # When loudness runs, music/SFX land in work_dir so a failed
        # loudnorm never leaves a half-normalized file in renders/.
        if sfx_overlays and loudness_normalize:
            mixed_path = work_dir / f"pre_sfx_{output_path.stem}.mp4"
            post_mix_path = work_dir / f"pre_loudness_{output_path.stem}.mp4"
        elif sfx_overlays:
            mixed_path = work_dir / f"pre_sfx_{output_path.stem}.mp4"
            post_mix_path = output_path
        elif loudness_normalize:
            mixed_path = work_dir / f"pre_loudness_{output_path.stem}.mp4"
            post_mix_path = mixed_path
        else:
            mixed_path = output_path
            post_mix_path = output_path
        if music_segments is None:
            narrated_path.replace(mixed_path)
        else:
            if len(music_segments) == 1:
                music_path = music_segments[0][0]
            else:
                music_path = await assemble_act_bed(
                    music_segments,
                    work_dir / f"music_bed_{output_path.stem}.m4a",
                    render_settings,
                )
            offset_bed_gain_db, offset_duck_gain_db = offset_bed_and_duck_gain_db(
                music_gains.bed_gain_db, music_gains.duck_gain_db, music_gain_offset_db
            )
            # A11: the effect duck target is a DEPTH off the same
            # offset-adjusted bed level narration ducks from, so the
            # human's upload gain-offset slider shifts both consistently
            # (RV6's own reasoning, extended to the second duck depth).
            effect_duck_gain_db = offset_bed_gain_db - settings.sfx_diegetic_duck_depth_db
            await mux_music(
                narrated_path,
                music_path,
                narration_paths,
                mixed_path,
                render_settings,
                # Decision 7 (analysis.md, 2026-08-24) / RV6 fix
                # (analysis.md, 2026-08-24): the human's dB offset shifts
                # the WHOLE envelope - bed and ducked floor alike -
                # preserving the style's duck depth. A prior version
                # applied the offset to the bed only, which left
                # `_volume_chain`'s ducked level pinned at the style's
                # absolute `duck_gain_db` and inverted ducking (music got
                # LOUDER under narration) once the offset passed roughly
                # -4 to -6 dB depending on style. See
                # `offset_bed_and_duck_gain_db`'s own docstring.
                bed_gain_db=offset_bed_gain_db,
                duck_gain_db=offset_duck_gain_db,
                amix_normalize=music_amix_normalize,
                # OQ-1b (RV2): same alignment list fingerprinted above.
                alignment_by_scene=alignment_by_scene,
                # A11: empty on every project with no diegetic cues -
                # `mux_music` takes the exact pre-A11 code path in that
                # case (see its own docstring).
                effect_intervals=diegetic_duck_windows,
                effect_duck_gain_db=effect_duck_gain_db,
            )
        if sfx_overlays:
            await mux_sfx(
                mixed_path,
                sfx_overlays,
                post_mix_path,
                render_settings,
                max_clip_s=settings.sfx_max_clip_s,
            )
        # OQ-1a: final loudness pass on the finished mux (after music +
        # SFX). Owns writing `output_path` when enabled.
        if loudness_normalize:
            await apply_loudness_target(
                post_mix_path,
                output_path,
                render_settings,
                target_lufs=loudness_target_lufs,
                true_peak_db=loudness_true_peak_db,
            )

    duration_s = await probe_duration_seconds(output_path, render_settings.ffprobe_binary)
    await render_repo.insert_completed(
        project_id=project_uuid,
        output_path=str(output_path),
        fingerprint=fingerprint,
        settings={
            "width": render_settings.width,
            "height": render_settings.height,
            "fps": render_settings.fps,
            "pixel_format": render_settings.pixel_format,
        },
        width=render_settings.width,
        height=render_settings.height,
        fps=render_settings.fps,
        duration_s=duration_s,
        is_draft=is_draft,
    )
    return output_path


async def _resolve_narration_audio(
    session: AsyncSession, timeline: Timeline
) -> list[tuple[Path, str]] | None:
    """Thin wrapper over `_resolve_narration_rows` for callers that only
    need the audio path/hash, not the full row (alignment included) -
    kept so `mux_narration`'s own contract (ordered per-scene path/hash
    pairs) doesn't change shape. See `_resolve_narration_rows` for the
    actual resolution logic and why both `None` cases are correct."""
    rows = await _resolve_narration_rows(session, timeline)
    if rows is None:
        return None
    return [(Path(row.local_path), row.content_hash) for row in rows]


async def _resolve_narration_rows(
    session: AsyncSession, timeline: Timeline
) -> list[NarrationModel] | None:
    """Ordered per-scene narration rows for the active timeline, or
    `None` when this project has no real narration to mux - the render
    then stays exactly the silent video it already was. Also the single
    source of correctly voice-matched rows for caption cue derivation
    (`app/renderer/captions.py::derive_caption_cues`) - see that module's
    own docstring for why it does not re-resolve voice selection itself.

    Two deliberately distinct "no narration" cases collapse to that same
    silent-render behaviour, and neither is a fallback for a missing
    feature - both are the correct, decided output for what they
    describe:

    - `settings.dry_run`: `NarrationStep` still runs and still writes
      `narration` rows (DRY_RUN exercises the reconciliation arithmetic
      end to end via `FakeNarrationProvider` - implementation guide 4.1,
      fakes are kept forever), but its "audio" is a literal fake byte
      string, not decodable media - muxing it would not degrade
      gracefully, it would crash the render with an ffmpeg decode error.
      DRY_RUN's whole contract is "zero spend, always produces something
      runnable"; a silent .mp4 satisfies that, a crash does not.
    - `not timeline.metadata.narration_locked`: covers both an older
      project whose active version predates this step's existence and
      any pipeline that runs `RenderStep` with `NarrationStep` excluded
      (see `tests/integration/test_narration_pipeline_ordering.py`). In
      neither case has anything reconciled this timeline's shot
      durations against real spoken timings, so there is no audio whose
      timing is actually known to agree with the picture - silence is
      the honest output here, not a best-effort guess.

    long_form_direction.md A8 (2026-09-01) fix: this used to check
    `timeline.produced_by != ProducedBy.NARRATION` directly - correct only
    as long as NOTHING ever appends a further version after narration,
    which stopped being true the moment the one-gate model let a human
    correct a shot/track/sfx choice post-approval (`produced_by=HUMAN`/
    `MUSIC_SELECTION`/`SFX_SELECTION`) and, now, the moment
    `GenerateDiegeticSfxStep` runs post-approval too. `produced_by`
    describes only the version that JUST landed, so any later version -
    for any reason - fell straight back out of this check and silenced
    every subsequent render, even though nothing about the actual
    reconciled durations or narration rows had changed. `Timeline.
    metadata.narration_locked` is the field the SAME 2026-08-16 hardening
    ("A26 is a deadlock in practice") already introduced to solve this
    exact "produced_by doesn't survive later versions" problem for
    `validate_constraints` - `NarrationStep` sets `narration_locked=True`
    in the identical version it stamps `produced_by=NARRATION` (see
    `narration.py::_apply_durations`), so every timeline this check used
    to accept is still accepted, and every later, unrelated correction
    that used to wrongly silence the render is now correctly still
    narrated.

    Past both of those checks, this project's narration IS supposed to
    exist (this exact scene's row is what its shots' `duration_s` were
    reconciled against in `NarrationStep`) - a missing row from here on
    is a genuine data-integrity failure, not a case to quietly degrade
    for, so it raises `PermanentError` rather than silently falling back
    to a silent render that would contradict the timeline's own
    `narration_locked` flag (same refuse-to-guess philosophy as
    `app/timeline/narration_fit.py`).
    """
    if settings.dry_run:
        return None
    if not timeline.metadata.narration_locked:
        return None

    # Mirrors NarrationStep's own voice AND language_code resolution
    # exactly (same fallback order for both) - it must, since the content
    # hash below is only a cache hit if computed identically to how
    # NarrationStep computed it when the row was written. A previous
    # version of this function read `settings.elevenlabs_language_code`
    # directly instead of resolving it the same way NarrationStep does
    # (`Timeline.metadata.language_code or settings...`) - correct only
    # by accident when metadata.language_code happened to be unset for
    # every project, and a real mux failure the first time a project set
    # it (2026-08-24: "no narration row exists... cannot mux audio that
    # was never persisted").
    voice_id = timeline.metadata.voice_id or settings.elevenlabs_voice_id
    if not voice_id:
        raise PermanentError(
            "timeline is produced_by=narration but no voice_id can be resolved - "
            "narration cannot have run without one"
        )
    language_code = timeline.metadata.language_code or settings.elevenlabs_language_code

    narration_repo = NarrationRepository(session)
    rows: list[NarrationModel] = []
    speed = resolve_narration_speed(timeline.metadata.render_style)
    for scene in timeline.scenes:
        content_hash = compute_narration_content_hash(
            text=scene.narration_text,
            voice_id=voice_id,
            model=settings.elevenlabs_model,
            output_format=settings.elevenlabs_output_format,
            speed=speed,
            language_code=language_code,
        )
        row = await narration_repo.get_by_content_hash(content_hash)
        if row is None:
            raise PermanentError(
                f"timeline is produced_by=narration but no narration row exists for "
                f"scene {scene.id} (content_hash {content_hash}) - cannot mux audio "
                "that was never persisted"
            )
        rows.append(row)
    return rows


def _music_file(project_id: str, content_hash: str) -> Path:
    """Glob lookup on the content hash, not a hard-coded `.mp3` (analysis.md
    C1a #1): an uploaded track keeps its real container's extension
    (`validate_and_identify_audio`), so `music/` may hold `{hash}.wav`,
    `.m4a`, `.ogg`, or `.flac`. The hash is hex, so it is glob-safe."""
    path = next(
        iter((settings.storage_root / project_id / "music").glob(f"{content_hash}.*")),
        None,
    )
    if path is None:
        raise PermanentError(
            f"timeline has a selected music track (content_hash {content_hash}) but its "
            "audio file is missing on disk - cannot mux music that was never persisted"
        )
    return path


def _music_segments(timeline: Timeline, project_id: str) -> list[tuple[Path, float]] | None:
    """Source files to mux, or `None` when there is nothing to mux.

    Mirrors `_resolve_narration_audio`'s DRY_RUN/no-op reasoning: fake
    bytes are never written, so muxing them would fail rather than
    degrade. A missing file on a real selection is data-integrity, not
    a silent skip.

    Path A (no `act_beds`, or a single bed): one file; duration is unused
    because `mux_music` still loop+trims to the video. Path B (two or
    more beds): one `(path, act_duration_s)` per act, assembled on the
    cache-miss path so a fingerprint hit never pays the concat.
    """
    if settings.dry_run:
        return None
    if timeline.music_plan is None:
        return None

    beds = [bed for bed in timeline.music_plan.act_beds if bed.selected_track is not None]
    if len(beds) >= 2:
        ranges = {act_id: (start, end) for act_id, start, end in act_time_ranges(timeline)}
        segments: list[tuple[Path, float]] = []
        for bed in beds:
            path = _music_file(project_id, bed.selected_track.content_hash)
            start, end = ranges.get(bed.act_id, (0.0, 0.0))
            duration_s = end - start
            if duration_s <= 0:
                continue
            segments.append((path, duration_s))
        return segments or None

    if timeline.music_plan.selected_track is None:
        return None
    path = _music_file(project_id, timeline.music_plan.selected_track.content_hash)
    return [(path, 0.0)]


def _sfx_content_hashes(timeline: Timeline) -> list[str]:
    if timeline.sfx_plan is None:
        return []
    return [clip.content_hash for clip in timeline.sfx_plan.clips]


def _diegetic_ceiling_s(shot_duration_s: float | None) -> float:
    """A15 (long_form_direction.md, 2026-09-01): a diegetic cue's played
    length is bounded by the SHOT it belongs to, not only by the flat
    `sfx_diegetic_max_clip_s` (Problem 1 - 6 of 7 real cues overran their
    shot by 2.8-4.8s because the global 8.0s ceiling never consulted the
    shot). `sfx_diegetic_shot_carry_s` allows a short, deliberate bleed
    past the cut (a sound bridge is a real editing device), never the
    multi-second overrun this replaces - see that setting's own comment.
    `shot_duration_s=None` (a caller that could not resolve the shot) is
    the pre-A15 behaviour: the flat ceiling alone. Shared by
    `_diegetic_duck_windows` (the bed-ducking window) and `_sfx_overlays`
    (the audible trim) so the two never drift apart - the former's own
    docstring already promises this."""
    ceiling = settings.sfx_diegetic_max_clip_s
    if shot_duration_s is not None:
        ceiling = min(ceiling, shot_duration_s + settings.sfx_diegetic_shot_carry_s)
    return ceiling


def _diegetic_duck_windows(
    timeline: Timeline,
    *,
    fps: int,
    whoosh_enabled: bool,
    transition_structural_only: bool = False,
) -> list[tuple[float, float]]:
    """A11 (long_form_direction.md, 2026-09-01): a duck window per
    DIEGETIC cue, computed from the TIMELINE alone (shot start times via
    `derive_sfx_events`, plus the clip's own persisted `duration_s` and
    the shot-bounded ceiling from `_diegetic_ceiling_s`, A15) - never from
    the SFX audio file. `render_video`'s own pipeline order is narration
    -> music -> sfx, so at the point `mux_music` runs, no SFX audio has
    been mixed (or even necessarily downloaded/copied into this project's
    `sfx/` dir) yet; `_sfx_overlays` (the function that DOES read those
    files) only runs afterward. The window length mirrors `_sfx_overlays`'
    own ceiling math exactly (`_diegetic_ceiling_s`, shared) so the duck
    window and the audible clip agree on how long the cue actually plays -
    A15 found this function was the SECOND place the flat ceiling leaked
    in (Problem 1 named only generation and the mux trim), and fixed it
    here too rather than leave the duck window over-ducking the bed past
    the point the now-shorter cue actually stops. Every input here
    already rides inside the hashed timeline document or an
    already-fingerprinted config value (R2) - no new fingerprint entry is
    needed for the windows themselves."""
    if timeline.sfx_plan is None or not timeline.sfx_plan.clips:
        return []
    diegetic_by_shot = {
        clip.shot_id: clip
        for clip in timeline.sfx_plan.clips
        if clip.kind == SfxKind.DIEGETIC and clip.shot_id
    }
    if not diegetic_by_shot:
        return []
    shots_by_id = {shot.id: shot for shot in timeline.all_shots()}
    windows: list[tuple[float, float]] = []
    for event in derive_sfx_events(
        timeline,
        fps=fps,
        whoosh_enabled=whoosh_enabled,
        transition_structural_only=transition_structural_only,
    ):
        if event.kind != SfxKind.DIEGETIC:
            continue
        clip = diegetic_by_shot.get(event.shot_id)
        if clip is None:
            continue
        shot = shots_by_id.get(event.shot_id)
        ceiling = _diegetic_ceiling_s(shot.duration_s if shot is not None else None)
        played_s = min(clip.duration_s, ceiling) if clip.duration_s is not None else ceiling
        if played_s <= 0:
            continue
        windows.append((event.offset_s, event.offset_s + played_s))
    return windows


def _sfx_overlays(
    timeline: Timeline,
    project_id: str,
    *,
    fps: int,
    whoosh_enabled: bool,
    transition_structural_only: bool = False,
) -> list[SfxOverlay]:
    """Full mix inputs per scheduled SFX event, or empty when DRY_RUN /
    no clips. Per clip (C3c): its stored peak measurement - or the flat
    `sfx_gain_db` fallback when unmeasured - is turned into a volume
    factor through `sfx_normalize_target_db` and the optional per-kind
    offset. Per clip (C3d): its stored duration becomes an end-aligned
    trim start when it exceeds its own ceiling. Both values live on the
    clip inside the hashed timeline document, so this whole assembly is
    deterministic (I5).

    long_form_direction.md A8: the three structural kinds still resolve
    through `by_kind` - one shared clip per kind, unchanged. DIEGETIC is
    looked up through `diegetic_by_shot` instead, since `SfxPlan.clips`
    can hold several different DIEGETIC clips (one per distinct cue) and
    `SfxEvent.shot_id` says which one this event answers. Its own,
    longer ceiling now comes from `_diegetic_ceiling_s` (A15,
    long_form_direction.md 2026-09-01: bounded by the shot's own
    `duration_s`, not the flat `sfx_diegetic_max_clip_s` alone - Problem
    1, "a cue must end when its shot does") and rides on the overlay
    itself (`SfxOverlay.max_clip_s`), never on the shared `mux_sfx`
    call-level ceiling - see that field's own docstring."""
    if settings.dry_run:
        return []
    if timeline.sfx_plan is None or not timeline.sfx_plan.clips:
        return []
    by_kind = {clip.kind: clip for clip in timeline.sfx_plan.clips if clip.kind != SfxKind.DIEGETIC}
    diegetic_by_shot = {
        clip.shot_id: clip
        for clip in timeline.sfx_plan.clips
        if clip.kind == SfxKind.DIEGETIC and clip.shot_id
    }
    shots_by_id = {shot.id: shot for shot in timeline.all_shots()}
    kind_offsets = {
        SfxKind.WHOOSH: settings.sfx_whoosh_gain_db,
        SfxKind.STINGER: settings.sfx_stinger_gain_db,
        SfxKind.TRANSITION: settings.sfx_transition_gain_db,
        SfxKind.DIEGETIC: settings.sfx_diegetic_gain_db,
    }
    overlays: list[SfxOverlay] = []
    for event in derive_sfx_events(
        timeline,
        fps=fps,
        whoosh_enabled=whoosh_enabled,
        transition_structural_only=transition_structural_only,
    ):
        clip = (
            diegetic_by_shot.get(event.shot_id)
            if event.kind == SfxKind.DIEGETIC
            else by_kind.get(event.kind)
        )
        if clip is None:
            continue
        # Same glob fix as `_music_file` (C1a #1): override uploads store
        # non-mp3 extensions too.
        path = next(
            iter((settings.storage_root / project_id / "sfx").glob(f"{clip.content_hash}.*")),
            None,
        )
        if path is None:
            continue
        # A11 (long_form_direction.md, 2026-09-01): DIEGETIC alone takes
        # the loudness-based path (`diegetic_effective_gain_db`) - peak
        # normalisation is wrong for a high-crest ambience/impact clip
        # (see that function's own docstring). The three structural
        # kinds call `effective_gain_db` exactly as before this slice -
        # byte-identical, asserted directly by
        # `test_structural_kinds_gain_is_unchanged_by_a11`.
        if event.kind == SfxKind.DIEGETIC:
            gain_db = diegetic_effective_gain_db(
                clip.loudness_lufs,
                clip.peak_dbfs,
                clip.duration_s,
                loudness_target_lufs=settings.sfx_diegetic_normalize_target_lufs,
                peak_target_db=settings.sfx_normalize_target_db,
                fallback_db=settings.sfx_gain_db,
                min_loudness_duration_s=settings.sfx_diegetic_loudness_min_duration_s,
                kind_offset_db=kind_offsets.get(event.kind),
            )
        else:
            gain_db = effective_gain_db(
                clip.peak_dbfs,
                target_db=settings.sfx_normalize_target_db,
                fallback_db=settings.sfx_gain_db,
                kind_offset_db=kind_offsets.get(event.kind),
            )
        if event.kind == SfxKind.DIEGETIC:
            shot = shots_by_id.get(event.shot_id)
            max_clip_s = _diegetic_ceiling_s(shot.duration_s if shot is not None else None)
        else:
            max_clip_s = None
        ceiling = max_clip_s if max_clip_s is not None else settings.sfx_max_clip_s
        overlays.append(
            SfxOverlay(
                path=path,
                offset_s=event.offset_s,
                volume_factor=10 ** (gain_db / 20),
                trim_start_s=end_aligned_trim_start(clip.duration_s, ceiling),
                max_clip_s=max_clip_s,
            )
        )
    return overlays


async def _resolved_path_and_hash(session, binding) -> tuple[Path | None, str | None]:
    """The shot's resolved media path, and a content-identifying hash of
    it for the render fingerprint (M8 step 6) - `Asset.content_hash` for
    a searched/uploaded image, `GeneratedClip.prompt_hash` for a
    generated one (there is no separate output-content hash for
    generated media; `prompt_hash` already uniquely determines what was
    generated, via the same cache this pipeline already trusts for
    reuse - see `ResolveAssetsStep`)."""
    if binding is None:
        return None, None
    if binding.asset_id is not None:
        asset = await session.get(AssetModel, binding.asset_id)
        if asset is None or not asset.local_path:
            return None, None
        return Path(asset.local_path), asset.content_hash
    if binding.clip_id is not None:
        clip = await session.get(GeneratedClipModel, binding.clip_id)
        if clip is None or not clip.local_path:
            return None, None
        return Path(clip.local_path), clip.prompt_hash
    return None, None


async def _resolved_secondary_path_and_hash(session, binding) -> tuple[Path | None, str | None]:
    """Bottom panel of a split-screen shot. Same asset-before-clip
    precedence as the primary. Missing is a degrade, not a placeholder."""
    if binding is None:
        return None, None
    if binding.secondary_asset_id is not None:
        asset = await session.get(AssetModel, binding.secondary_asset_id)
        if asset is None or not asset.local_path:
            return None, None
        return Path(asset.local_path), asset.content_hash
    if binding.secondary_clip_id is not None:
        clip = await session.get(GeneratedClipModel, binding.secondary_clip_id)
        if clip is None or not clip.local_path:
            return None, None
        return Path(clip.local_path), clip.prompt_hash
    return None, None
