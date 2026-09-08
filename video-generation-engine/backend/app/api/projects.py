"""Project, script, render, and workflow endpoints (docs/09_API_Specification.md).

`POST /render` starts (or resumes) the workflow engine; `POST /render/only`
(R3) invokes ONLY the render step, structurally unable to reach a paid
provider (see `app/workflow/render_only.py`). `POST /timeline/approve`
approves the active timeline and resumes the same run - the
human-in-the-loop gate (ADR-008) is a real stop between two separate HTTP
calls, not a blocked coroutine.

`POST /{id}/assets` (M6.5, A8/A23/A27) and
`POST /{id}/shots/{shot_id}/override` (M6.5, A9/A10/A24/A25/A29) are the
two human-media endpoints this phase adds - an optional upload matched to
shots later by the existing relevance gate, and a per-shot override that
bypasses every gate and locks that shot's asset. Neither one runs the
workflow engine synchronously except the override, which resumes it
(A26's only remedy for a shot stuck `failed` at the review gate).

`POST /{id}/music/retry` (M3) and `POST /{id}/narration/retry` (N1) are
the same "an automated creative choice, redone by a human" shape applied
to music and narration respectively - both resume the engine too, and
both share their common tail with `_resume_after_human_correction`
(see that helper's own docstring for why the per-shot override above
does NOT also use it).

## F0a (2026-08-16): every trigger above returns immediately

Every endpoint that used to `await engine.run()` inline - `render_project`,
`approve_timeline`, `override_shot_asset`, `retry_music_selection`,
`retry_narration_voice`, and the new `render_only` - now calls
`app.workflow.trigger.start_workflow_run` instead, which claims (or joins)
this project's `workflow_run` row and hands the actual pipeline execution
to `BackgroundTasks`, returning a `WorkflowTriggerResult` (a run id to
poll, not an outcome) with `202`. `GET /status`/`GET /progress` are the
client's real answer to "what happened" - see `app/workflow/trigger.py`'s
own module docstring for why `BackgroundTasks` over a queue, and how
concurrent triggers on one project are prevented from starting two runs.

## F0b (2026-08-16): serving image bytes

`GET /{id}/shots/{shot_id}/asset` and `GET /{id}/thumbnail` are the first
endpoints in this file that serve real media bytes rather than JSON or an
already-finished file (`GET /video`/`GET /video/draft` stream a file
directly too, but never need to CREATE one) - `asset.local_path`/
`generated_clip.local_path`/`project.video_path` are all server
filesystem paths a browser cannot load. Both lazily generate and cache a
displayable image on disk, keyed on the source file's own mtime -
`app/assets/thumbnails.py` owns that logic; see its module docstring for
why mtime and not a content hash. `GET /{id}/shots/{shot_id}/asset` also
sets `Cache-Control: no-cache` (Task 7, 2026-08-16) so a browser always
revalidates - a regenerate/override rebinds the same URL to a different
underlying file, and Starlette's own `ETag`/`Last-Modified` (computed
fresh per request from that file's current `os.stat`) only protect
against staleness if the browser is actually forced to check them.

## The one-gate redesign (2026-08-16) - see docs/13_Implementation_Guide.md

`approve_timeline` now refuses (400) if any shot at the active version
has no media yet (Task 2 - the money guard the one-gate design depends
on), and `generate_shot_image` (`POST /shots/{id}/generate`) gained an
optional edited `prompt` (Task 4 - a Timeline change, `append_version`d
before generating) and reports `cache_hit`/an honest `cost_cents` (Task
6). See each endpoint's own docstring for the full reasoning, and the
implementation guide's "one-gate redesign" section for the whole picture
across all seven tasks.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_repo, get_timeline_service
from app.assets.cost import (
    budget_cap_cents_for,
    estimate_project_cost_cents,
    total_project_spend_cents,
)
from app.assets.focal import (
    FOCAL_SOURCE_HUMAN,
    normalize_focal,
    persist_vision_focal,
    read_focal_sidecar,
    write_focal_sidecar,
)
from app.assets.focal_check import locate_subject_focal
from app.assets.music_upload import music_upload_warnings
from app.assets.prompt_export import build_prompt_export_entries, render_prompt_export_text
from app.assets.sfx_levels import measure_peak_dbfs
from app.assets.sfx_override import apply_sfx_clip_override
from app.assets.thumbnails import (
    cached_resized_image,
    cached_video_frame,
    is_video_file,
    shot_frame_cache_path,
)
from app.assets.validation import (
    mime_type_for_extension,
    validate_and_identify_audio,
    validate_and_identify_image,
    validate_and_identify_video,
)
from app.core.config import settings
from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
from app.projects.deletion import build_deletion_preview, delete_project
from app.providers.fakes.image import FakeImageProvider
from app.providers.fal_image import FalImageProvider
from app.providers.fal_video import FalVideoProvider
from app.providers.openai_provider import OpenAIPlanningProvider
from app.renderer.retention import purge_expired_drafts
from app.renderer.slideshow import RenderSettings
from app.repositories.asset_repository import AssetRepository
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.narration_repository import NarrationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.repositories.workflow_repository import WorkflowRunRepository
from app.schemas.project import Project, ProjectStatus
from app.schemas.project_deletion import ProjectDeletionSummary
from app.schemas.script_preflight import (
    BreakSuggestionOut,
    FragmentEstimateOut,
    RewriteFeasibilityOut,
    ScriptPreflightRequest,
    ScriptPreflightResponse,
    ScriptRewriteRequest,
    ScriptRewriteResponse,
    StyleSuitabilityOut,
)
from app.schemas.timeline import (
    CameraMovement,
    MusicTrackSelection,
    ProducedBy,
    SfxClipSelection,
    SfxKind,
    Timeline,
    TimelineStatus,
)
from app.script.preflight import check_feasibility
from app.script.rewrite import rewrite_script
from app.script.styles import (
    STYLE_PACING_BANDS,
    frame_aspect_error,
    resolve_draft_format,
    style_accepts_frame_aspect,
)
from app.script.suggestions import suggest_breaks
from app.script.suitability import check_suitability
from app.timeline.duration import compute_shot_start_times
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.render_only import RENDER_ONLY_STEPS, render_precondition_gap
from app.workflow.steps.render import render_video
from app.workflow.steps.resolve_assets import (
    generate_image_real,
    poll_video_job,
    submit_video_generation,
)
from app.workflow.trigger import WorkflowTriggerResult, start_workflow_run

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])

_TERMINAL_SHOT_STATES = ("resolved", "generated")
_OVERRIDE_PANELS = frozenset({"primary", "secondary"})


def _unfilled_shot_ids(shots, bindings_by_shot: dict) -> list[str]:
    return [
        shot.id
        for shot in shots
        if bindings_by_shot.get(shot.id) is None
        or bindings_by_shot[shot.id].state not in _TERMINAL_SHOT_STATES
    ]


def _merge_approved_scenes(timeline: Timeline, add: list[str]) -> list[str]:
    """Monotonic append: existing ids keep their order, new ones are
    added in `add` order without duplicates."""
    merged = list(timeline.metadata.approved_scenes)
    seen = set(merged)
    for scene_id in add:
        if scene_id not in seen:
            merged.append(scene_id)
            seen.add(scene_id)
    return merged


def _all_scenes_approved(timeline: Timeline) -> bool:
    return all(scene.id in timeline.metadata.approved_scenes for scene in timeline.scenes)


def _failed_regenerate_cost_cents(n_failed: int) -> int:
    return n_failed * settings.fal_image_cost_cents_estimate


def _progress_etag_response(payload: dict, request: Request) -> JSONResponse | Response:
    """§13.4: ETag from the assembled payload, not `timeline.version` —
    a binding resolving does not bump the version, so a version-keyed
    etag would serve stale progress during generation."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    etag = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


async def _resolved_media_detail(
    session: AsyncSession, *, asset_id, clip_id
) -> tuple[dict | None, dict | None]:
    """`asset_id` wins over `clip_id`, mirrored from `_resolve_bound_media_
    path` below - the same rule, built into the JSON shape `/progress`
    hands the gate instead of a filesystem path. Shared between the
    primary and secondary (P3a) halves of `_shot_progress_entry` because
    they build this identically for whichever pair of ids they're given
    (R1: one rule, one place - two independent copies of "asset_id wins,
    then clip_id, then neither" would drift the moment one of them grew a
    field the other didn't)."""
    asset_detail = None
    if asset_id is not None:
        asset = await session.get(AssetModel, asset_id)
        if asset is not None:
            asset_detail = {
                "provider": asset.provider,
                "source_url": asset.source_url,
                "licence": asset.licence,
                "attribution": asset.attribution,
                "local_path": asset.local_path,
            }
    clip_detail = None
    if clip_id is not None:
        clip = await session.get(GeneratedClipModel, clip_id)
        if clip is not None:
            clip_detail = {
                "provider": clip.provider,
                "model_id": clip.model_id,
                "status": clip.status,
                "local_path": clip.local_path,
            }
    return asset_detail, clip_detail


async def _shot_progress_entry(
    session: AsyncSession,
    *,
    scene,
    shot,
    binding,
    locked: bool,
    start_times: dict,
) -> dict:
    asset_detail, clip_detail = await _resolved_media_detail(
        session, asset_id=binding.asset_id, clip_id=binding.clip_id
    )
    says = None
    if shot.narration_span is not None:
        start_char, end_char = shot.narration_span
        says = scene.narration_text[start_char:end_char]

    # P3a (docs/plans/gate_panel_overrides.md): `panel=secondary` has
    # worked server-side since R16 (`override_shot_asset`/`get_shot_asset`
    # both accept it, 400ing unless `camera.movement == SPLIT_FRAME`), but
    # this payload never said a shot WAS split_frame, let alone anything
    # about its bottom panel - so the gate had no way to know a second
    # image existed, and every hand-supplied split-screen shot has shipped
    # with one provider on top and fal.ai on the bottom, mismatched inside
    # a single frame (measured, happening "fairly often").
    #
    # `secondary` is `None` for every non-split shot - the frontend's
    # "this shot has no bottom panel at all" signal - and an OBJECT for
    # every `split_frame` shot regardless of whether that panel has
    # resolved yet: its own `asset`/`clip` are `None` while unresolved and
    # `state`/`last_error` say why, exactly the "distinguish absent from
    # unresolved" property the gate needs to decide whether to show a
    # spinner, an error, or an upload slot. One existence check
    # (`shot.secondary != null`) is enough to gate rendering the second
    # slot - matching, rather than duplicating, `_OVERRIDE_PANELS`'s own
    # SPLIT_FRAME-only gate for `panel=secondary` above, so "can this
    # shot's bottom panel be touched" cannot drift between the two halves
    # of this file.
    #
    # Nested under one key instead of four more flat `secondary_*` entries
    # beside `state`/`last_error`/`asset`/`clip` above: it mirrors the
    # grouping those four already have, and the frontend gets the single
    # existence check above instead of four separate `!= null` reads that
    # could disagree with each other.
    #
    # READ THIS BEFORE WRITING THE FRONTEND. A12 (2026-09-02) added
    # `sfx_cue` to the frontend `Shot` type and rendered a row for it at
    # the review gate, but never added it HERE - so `shot.sfx_cue` was
    # always `undefined` in the browser, the row silently never appeared,
    # and the TypeScript build still passed: TypeScript types describe the
    # API, they do not verify it. Do not repeat that for `secondary` - the
    # payload field and the frontend `Shot` type both have to exist, and a
    # test asserting the PAYLOAD (not just the type) carries this field is
    # what would have caught A12's mistake.
    secondary = None
    if shot.camera.movement == CameraMovement.SPLIT_FRAME:
        secondary_asset_detail, secondary_clip_detail = await _resolved_media_detail(
            session,
            asset_id=binding.secondary_asset_id,
            clip_id=binding.secondary_clip_id,
        )
        secondary = {
            "prompt": shot.secondary_prompt,
            "state": binding.secondary_state,
            "last_error": binding.secondary_last_error,
            "asset": secondary_asset_detail,
            "clip": secondary_clip_detail,
        }

    return {
        "shot_id": binding.shot_id,
        "scene_id": scene.id,
        "state": binding.state,
        "rung": binding.rung,
        "last_error": binding.last_error,
        "will_generate": binding.state == "awaiting_generation",
        "locked": locked,
        "asset": asset_detail,
        "clip": clip_detail,
        "says": says,
        "prompt": shot.prompt,
        "intent": shot.intent,
        "duration_s": shot.duration_s,
        "starts_at_s": start_times.get(shot.id),
        # Emitted for every shot, not only split_frame ones - cheap, and
        # the gap this closes (nothing here named the shot's own camera
        # movement at all) is bigger than split-screen alone; a future
        # panel-shaped movement gets this for free.
        "camera_movement": shot.camera.movement,
        "secondary": secondary,
        # A12 added the cue to the frontend `Shot` type and rendered a row
        # for it at the review gate, but never here - so `shot.sfx_cue` was
        # always `undefined` in the browser and the row silently never
        # appeared. TypeScript types describe the API; they do not verify
        # it, so the build passed and the omission was invisible until a
        # human looked for the cue and found nothing (2026-09-02).
        "sfx_cue": shot.sfx_cue,
    }


class CreateProjectRequest(BaseModel):
    name: str
    # `None` = "use settings.default_render_style" (Track B, 2026-08-17)
    # - validated against `STYLE_PACING_BANDS` in `create_project` below,
    # same as `set_render_style`'s own check.
    render_style: str | None = None
    # Only settable for a style that opts in (`style_accepts_frame_aspect`
    # - today, `stillness` and `illustrated_risograph`); rejected for any
    # other style (`frame_aspect_error`). For `stillness`: `9:16` is a
    # vertical Ken Burns reel, `16:9` / None is the default landscape
    # contemplative frame. For `illustrated_risograph`: `16:9` opts into
    # the landscape edit, `9:16` / None is the default portrait canvas.
    frame_aspect: str | None = None
    # ISO 639-1 hint for ElevenLabs' `language_code` param (2026-08-24).
    # Set here so a code-switched (Hindi/Hinglish, Spanish/Spanglish,
    # Arabic, ...) project's FIRST narration pass already uses the
    # right hint, instead of paying for a wrong-hint pass and correcting
    # it afterwards via `POST /narration/retry-language`. No validation
    # against a fixed language list, same lack-of-validation precedent
    # as `voice_id` - ElevenLabs itself silently ignores a code its
    # model doesn't support, so a typo here degrades gracefully rather
    # than needing this codebase to maintain its own copy of ElevenLabs'
    # supported-language list.
    language_code: str | None = None


class SetRenderStyleRequest(BaseModel):
    render_style: str
    frame_aspect: str | None = None


class SetLanguageRequest(BaseModel):
    # Same "real value, not a placeholder" note as SetGradeRequest's own
    # grade_style: None is the explicit "no language_code hint" choice
    # (most projects), not an unset field.
    language_code: str | None = None


class SetGradeRequest(BaseModel):
    # `None` clears the override, reverting to whatever `render_style`'s
    # own grade is - a real, useful reset case (R5, §13.5), not just a
    # required-field placeholder.
    grade_style: str | None


class UploadedAssetResult(BaseModel):
    asset_id: str
    filename: str
    duplicate: bool


class MusicUploadResult(WorkflowTriggerResult):
    """`POST /{id}/music/upload`'s response - a trigger result (the upload
    resumes the engine like every human correction) plus the decision-6a/
    6b length warnings, computed BEFORE the 202 so the client can show
    them while the re-render runs."""

    warnings: list[str] = []


class RetryMusicSelectionRequest(BaseModel):
    # `None` (the default, and what an empty request body deserialises
    # to) means "try again with the Director's own search_terms,
    # unchanged" - e.g. after a code fix (M1's prompt vocabulary, M2's
    # duration floor) that a human expects to help even without
    # supplying anything themselves. A non-empty list overrides the
    # Timeline's frozen `music_plan.search_terms` outright - the only way
    # to escape terms that were bad from the start, since re-running
    # unchanged terms against an unfixed vocabulary problem finds nothing
    # new.
    search_terms: list[str] | None = None


class RetryNarrationVoiceRequest(BaseModel):
    # Required, unlike RetryMusicSelectionRequest's optional search_terms
    # - there is no meaningful "retry with the same voice" for narration
    # (it would just hit the same cache entry and produce an identical,
    # wasted version bump), so an actual new voice is always the point of
    # calling this.
    voice_id: str


class RetryNarrationLanguageRequest(BaseModel):
    # Unlike voice_id, None is a meaningful, real value here - it is how
    # a project explicitly clears a previously-set hint and goes back to
    # ElevenLabs' own language auto-detection (settings.
    # elevenlabs_language_code defaults to None for the same reason: most
    # projects narrate in one language and need no hint at all). ISO
    # 639-1, e.g. "hi" for a Hindi/Hinglish code-switched script.
    language_code: str | None = None


class UploadScriptRequest(BaseModel):
    content: str


async def _get_project_or_404(project_id: str, repo: ProjectRepository) -> Project:
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return project


async def _resume_after_human_correction(
    project_id: str,
    active: Timeline,
    *,
    timeline_service: TimelineService,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
    transform: Callable[[Timeline], Timeline],
    owns: frozenset[str],
) -> WorkflowTriggerResult:
    """The shared tail of "a human corrects an automated creative
    choice" - used by `retry_music_selection` (M3) and
    `retry_narration_voice` (N1) below: record the correction as a
    `produced_by=HUMAN` `append_version` (I3, never mutated in place),
    re-approve if the timeline had already moved past DRAFT so resuming
    doesn't demand a redundant second human click, then resume the
    engine.

    **A considered call, not an assumed one** (this is the third
    instance of the same "automated choice, human redo path" shape -
    per-shot image override, M3's music retry, and this - so the
    question of whether they want ONE shape was asked explicitly rather
    than skipped): the FRONT half of each - what precondition to check,
    what the correction even IS, what `transform`/`owns` it needs - is
    genuinely different per domain (an uploaded file plus asset dedup
    for a shot, search terms for music, a bare voice id for narration),
    and forcing that into one generic shape would hide the interesting,
    domain-specific logic behind a parameter bag - the "speculative
    framework" explicitly not wanted here. The BACK half above, though,
    is now byte-for-byte identical between music-retry and narration-
    retry, which is a different claim than "these features are the same
    feature": it is reusable PLUMBING, not shared POLICY, and extracting
    exactly that (nothing more) is the considered middle ground.

    **`override_shot_asset` (the original, per-shot override) deliberately
    still does NOT use this helper**, and that is also a considered
    choice, not an oversight: it must create/populate a `ShotBinding` row
    using the NEW version's id, and that has to happen strictly BETWEEN
    the `append_version` call and `start_workflow_run` - the backgrounded
    engine reads bindings for the active version as soon as it starts
    (F0a schedules it on `BackgroundTasks`, which only run AFTER this
    request's own session has committed, but the binding row still has
    to exist in that commit), so the binding must already be flushed
    before this function's own commit, or the override would appear to
    do nothing until a second, unrelated resume. Adding a mid-flow hook
    parameter to this helper just to fit that one case back in would
    reintroduce the exact "generic parameter bag" problem this function
    exists to avoid - three near-identical endpoints are clearer than one
    endpoint with a callback threaded through its middle.
    """
    # 2026-08-16 (Task 1): used to also treat `active.produced_by ==
    # ProducedBy.NARRATION` as approval-equivalent here, which was safe
    # ONLY under the OLD pipeline order (approve, then narrate) where
    # narration could never produce a version except on an
    # already-approved lineage. `NarrationStep` now runs BEFORE
    # `AwaitApprovalStep` (see `app/workflow/engine.DEFAULT_PIPELINE`),
    # so `produced_by == NARRATION` is routinely the ordinary, UNAPPROVED
    # state a project sits in while a human is still deciding at the one
    # gate - e.g. right after the very first narration pass, before
    # anyone has clicked approve. Treating that as "already approved"
    # here would self-approve (and then resume the engine into paid
    # generation for) a project nobody has approved yet - a real I6
    # violation, not a cosmetic one. `status == APPROVED` is now the only
    # signal.
    was_already_approved = active.status == TimelineStatus.APPROVED
    new_timeline = await timeline_service.append_version(
        project_id,
        produced_by=ProducedBy.HUMAN,
        transform=transform,
        owns=owns,
    )
    if was_already_approved:
        await timeline_service.approve(project_id, new_timeline.version)

    # An active timeline (checked by every caller before this) implies a
    # script already exists (`create_initial` requires one) -
    # `start_workflow_run` always has something to resume from here.
    return await start_workflow_run(project_id, session, background_tasks)


@router.post("", response_model=Project)
async def create_project(
    body: CreateProjectRequest,
    repo: ProjectRepository = Depends(get_repo),
) -> Project:
    if body.render_style is not None and body.render_style not in STYLE_PACING_BANDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown style {body.render_style!r} - "
                f"known styles: {sorted(STYLE_PACING_BANDS)}"
            ),
        )
    aspect_err = frame_aspect_error(body.render_style, body.frame_aspect)
    if aspect_err is not None:
        raise HTTPException(status_code=400, detail=aspect_err)
    return await repo.create(
        name=body.name,
        render_style=body.render_style,
        frame_aspect=body.frame_aspect,
        language_code=body.language_code,
    )


@router.get("", response_model=list[Project])
async def list_projects(
    repo: ProjectRepository = Depends(get_repo),
) -> list[Project]:
    return await repo.list_all()


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> Project:
    return await _get_project_or_404(project_id, repo)


@router.get("/{project_id}/deletion-preview", response_model=ProjectDeletionSummary)
async def get_deletion_preview(
    project_id: str,
    session: AsyncSession = Depends(get_db),
) -> ProjectDeletionSummary:
    """What `DELETE /{project_id}` would destroy, and what it would cost
    OTHER projects - see `app/projects/deletion.py`'s module docstring
    for the full accounting (row counts, storage bytes, the verified FK
    order) and the cross-project detection's exact honest limits.
    Read-only - safe for a confirmation dialog to call as often as it
    needs to before a human actually commits to deleting anything."""
    summary = await build_deletion_preview(session, project_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return summary


@router.delete("/{project_id}", response_model=ProjectDeletionSummary)
async def delete_project_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_db),
) -> ProjectDeletionSummary:
    """Deletes every DB row belonging to this project (verified FK-safe
    order, one transaction - `app/projects/deletion.py`) and its storage
    directory, then returns what was removed: the same shape
    `GET .../deletion-preview` already showed the caller before they
    confirmed. Silently releases (never deletes) any OTHER project's
    `shot_binding` still pointing at one of this project's
    `generated_clip` rows, resetting it to `pending` rather than leaving
    a dangling reference or failing the whole delete on Postgres' FK
    constraint - see that module's docstring for why."""
    summary = await delete_project(session, project_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return summary


@router.post("/{project_id}/script", response_model=Project)
async def upload_script(
    project_id: str,
    body: UploadScriptRequest,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
) -> Project:
    """Persists the script `ScriptModel` already versions immutably
    (`_append_script_if_changed`), the same discipline as
    `TimelineService.append_version` (I3) - each real edit is a new,
    permanent row, never an overwrite.

    **Freeze check, added with the script pre-flight
    (motion_new_styles_and_long_form_videos.md §3.5):** planning reads
    this project's script to produce shots, narration spans, and asset
    plans; a script edit AFTER a timeline exists would silently
    invalidate every version already built on the old text, with nothing
    to signal that any of it happened. Checked directly - no such guard
    existed before this change, so the script could be (and was)
    overwritten at any time regardless of pipeline state. `POST
    /{project_id}/script/preflight` below is the intended way to try out
    edits before this point; nothing here checks feasibility or
    suitability, only whether it is still safe to persist at all.
    """
    project = await _get_project_or_404(project_id, repo)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="script content must not be empty")
    active = await timeline_service.get_active(project_id)
    if active is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "script cannot be changed after planning has started - "
                f"project {project_id} already has an active timeline"
            ),
        )
    project.script = body.content
    project.status = ProjectStatus.SCRIPT_UPLOADED
    return await repo.update(project)


@router.get("/{project_id}/script")
async def get_script(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> dict:
    project = await _get_project_or_404(project_id, repo)
    return {"project_id": project.id, "content": project.script}


@router.post("/{project_id}/style", response_model=Project)
async def set_render_style(
    project_id: str,
    body: SetRenderStyleRequest,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
) -> Project:
    """Sets (or changes) this project's pre-planning style choice
    (motion_new_styles_and_long_form_videos.md, Track B) - separate from
    `create_project`'s own `render_style` so a style picked at creation
    can still be changed right up to the point planning starts (plan
    §2.1: "style is freely changeable up to the gate and frozen after
    it" - here, "the gate" is planning itself, not the later human-
    approval gate, because style affects the Shot Planner's own
    fragment-granularity decisions before any Timeline content exists to
    approve).

    **Same freeze check as `upload_script`, for the same reason**: once
    `GenerateTimelineStep` has created the initial Timeline (copying this
    field into `Timeline.metadata.render_style` and `frame_aspect`, frozen
    from then on), this project's OWN style columns are never read again -
    changing them here would silently do nothing rather than silently
    invalidating anything, but refusing is still the honest answer
    (a user who thinks they just changed the style deserves to be told
    it is too late, not to have the request quietly no-op).
    `frame_aspect` is only settable for a style that opts in - see
    `style_accepts_frame_aspect` (today, `stillness` and
    `illustrated_risograph`; `9:16` = vertical Ken Burns reel for the
    former, `16:9` = the landscape edit for the latter).
    """
    project = await _get_project_or_404(project_id, repo)
    if body.render_style not in STYLE_PACING_BANDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown style {body.render_style!r} - "
                f"known styles: {sorted(STYLE_PACING_BANDS)}"
            ),
        )
    aspect_err = frame_aspect_error(body.render_style, body.frame_aspect)
    if aspect_err is not None:
        raise HTTPException(status_code=400, detail=aspect_err)
    active = await timeline_service.get_active(project_id)
    if active is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "render style cannot be changed after planning has started - "
                f"project {project_id} already has an active timeline"
            ),
        )
    project.render_style = body.render_style
    # A style that does not opt in (`style_accepts_frame_aspect`) cannot
    # carry an override; a style that does, without a value, gets its own
    # default canvas. Always write, never keep a stale override from a
    # previous style choice - this used to hardcode `== "stillness"`,
    # which meant `create_project` (validates via `frame_aspect_error`
    # and persists `body.frame_aspect` as-is) and this endpoint agreed
    # for `stillness` but silently DISAGREED for any later style that
    # opted in: `create_project` would honour `frame_aspect="16:9"` for
    # `illustrated_risograph` while this line discarded it back to
    # `None`, so switching an EXISTING project to that style at 16:9
    # passed validation above and then silently persisted the wrong
    # canvas with no error anywhere - an R1 violation caught before ship,
    # not after. Fixed by reading through the same resolver
    # `frame_aspect_error` itself already reads.
    project.frame_aspect = (
        body.frame_aspect if style_accepts_frame_aspect(body.render_style) else None
    )
    return await repo.update(project)


@router.post("/{project_id}/language", response_model=Project)
async def set_language(
    project_id: str,
    body: SetLanguageRequest,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
) -> Project:
    """`language_code`'s own pre-planning counterpart to `set_render_style`
    just above - same reason it exists: `CreateProjectRequest.language_code`
    freezes onto `Timeline.metadata.language_code` the moment
    `GenerateTimelineStep` creates the initial Timeline (2026-08-25), so a
    project whose creation call raced ahead of the human finishing their
    language choice (the UI creates the project as soon as the script
    preflight check needs one, which can be well before the human is done
    picking) needs a way to correct it before that freeze happens. After
    the freeze, `POST /narration/retry-language` is the correction path
    instead - this endpoint would otherwise silently no-op past that
    point, so it refuses instead, same as `set_render_style`.

    Note this is a genuinely different default from `settings
    .elevenlabs_language_code` (`None` - no hint, since most projects
    need none): the CREATE form defaults its own selector to `"hi"` in
    the absence of an explicit human choice, since this codebase's real
    usage skews Hindi/Hinglish - but that is a UI default, not a second
    global one, and nothing stops a human picking anything else, or
    clearing it, right here."""
    project = await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "language cannot be changed here after planning has started - "
                f"project {project_id} already has an active timeline; use "
                "POST /narration/retry-language instead"
            ),
        )
    project.language_code = body.language_code
    return await repo.update(project)


@router.post("/{project_id}/grade", response_model=Timeline)
async def set_grade(
    project_id: str,
    body: SetGradeRequest,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
) -> Timeline:
    """R5 fix (motion_new_styles_and_long_form_videos.md §13.5, "R5",
    2026-08-18, user-confirmed scenario): the grade is the cheapest,
    fastest-to-iterate knob in the whole style system (§9 - eyes-on grade
    tuning against a real render is exactly the human time that does not
    parallelise), and §2.1 promised it stays freely changeable
    ("re-render is cheap") separately from the planner-facing levels
    that freeze at planning start. Before this endpoint, there was only
    `POST /{project_id}/style` above, which changes `render_style` and
    IS frozen once planning starts - so the grade was, in practice, the
    most locked knob instead of the most flexible one.

    **Deliberately NOT behind the freeze check `POST /style` has.** That
    check protects PLANNING inputs (a style change after planning starts
    would need a re-plan to take effect for the Shot Planner/prompt
    levels). The grade touches none of that - it only changes which `eq`
    filter `RenderStep` applies - so this works at any time, including
    after a project has already rendered. The caller still needs to
    trigger a re-render (`POST /render` or `POST /render/only`) to
    actually see the new look; this endpoint only records the decision.

    `grade_style=None` clears the override, reverting to whatever
    `render_style`'s own grade is - a deliberate reset, not just an
    unset default.
    """
    await _get_project_or_404(project_id, repo)
    if body.grade_style is not None and body.grade_style not in STYLE_PACING_BANDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown style {body.grade_style!r} - known styles: {sorted(STYLE_PACING_BANDS)}"
            ),
        )
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(
            status_code=400,
            detail=f"project {project_id} has no timeline yet to set a grade override on",
        )

    def _apply_grade(base: Timeline) -> Timeline:
        base.metadata.grade_style = body.grade_style
        return base

    return await timeline_service.append_version(
        project_id,
        produced_by=ProducedBy.HUMAN,
        transform=_apply_grade,
        owns=frozenset({"metadata.grade_style"}),
    )


@router.post("/{project_id}/script/preflight", response_model=ScriptPreflightResponse)
async def preflight_script(
    project_id: str,
    body: ScriptPreflightRequest,
    repo: ProjectRepository = Depends(get_repo),
    session: AsyncSession = Depends(get_db),
) -> ScriptPreflightResponse:
    """Checks a candidate script against a style BEFORE it is persisted
    and BEFORE planning ever runs (motion_new_styles_and_long_form_
    videos.md, Track D) - not a workflow step, so the run keeps exactly
    one gate (the 2026-08-16 one-gate redesign is not reopened here).

    **Stateless by design (plan §3.5.3).** `body.script`/`body.style`
    travel in the request, nothing is read from or written to this
    project's persisted state - `POST /{project_id}/script` (above) is
    the separate, deliberate act of persisting a script once the user is
    done. This is what makes it safe for a frontend to call on every
    keystroke or style change: a check here can never create a new
    `ScriptModel` version, which would fight that table's own "append
    only on a real, deliberate change" discipline.

    Two checks, run in this order because the second is free only when
    the first has already failed (plan §3.1, §3.2):
    - **Feasibility** (`app/script/preflight.py`, deterministic, no LLM
      call) - `passed=False` means an unambiguous mismatch between what
      this script's punctuation can produce and what `style` needs.
      `suggested_breaks` (level 2, `app/script/suggestions.py`) is only
      populated in this case - a feasible script has nothing to suggest
      breaking. R2: the list is transitive (every round of marks in one
      response). `further_suggestions_available` is True only if the
      cap was hit while still infeasible. `suggestions_would_pass` is
      True only if applying every returned mark makes feasibility pass
      (R23) — the two flags are not inverses. `punctuation_cannot_fix`
      is set when the remaining violation is not pace (R24: duration
      against the 10-minute ceiling).
    - **Suitability** (`app/script/suitability.py`, one LLM call) - a
      judgement about subject/tone fit, always attempted regardless of
      the feasibility verdict, and always advisory: `suitability` is
      `None` only when no verdict was computed at all (DRY_RUN, or no
      LLM provider configured), never a fabricated opinion. This
      endpoint never blocks on it, unlike `passed` above - see
      `StyleSuitabilityVerdict`'s own docstring for why.

    `KeyError` from an unrecognised `style` is translated to `400` here
    rather than letting a typo silently check against a default style's
    band, which would produce a verdict that looks real but checks the
    wrong thing.
    """
    await _get_project_or_404(project_id, repo)
    if body.style not in STYLE_PACING_BANDS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown style {body.style!r} - known styles: {sorted(STYLE_PACING_BANDS)}",
        )

    feasibility = check_feasibility(body.script, body.style)
    break_plan = suggest_breaks(body.script, body.style) if not feasibility.passed else None

    llm_provider = None if settings.dry_run else OpenAIPlanningProvider()
    suitability = await check_suitability(
        body.script,
        body.style,
        provider=llm_provider,
        llm_call_repo=LlmCallRepository(session),
        project_id=project_id,
    )
    if not settings.dry_run:
        await session.commit()

    return ScriptPreflightResponse(
        style=body.style,
        passed=feasibility.passed,
        violations=feasibility.violations,
        warnings=feasibility.warnings,
        fragment_count=feasibility.fragment_count,
        estimated_total_duration_s=feasibility.estimated_total_duration_s,
        estimated_average_shot_duration_s=feasibility.estimated_average_shot_duration_s,
        fragments=[
            FragmentEstimateOut(
                index=e.fragment.index,
                text=e.fragment.text,
                estimated_duration_s=e.estimated_duration_s,
            )
            for e in feasibility.fragment_estimates
        ],
        suggested_breaks=[
            BreakSuggestionOut(
                offset=s.offset,
                mark=s.mark,
                preview_before=s.preview_before,
                preview_after=s.preview_after,
                reason=s.reason,
            )
            for s in (break_plan.suggestions if break_plan is not None else [])
        ],
        further_suggestions_available=(
            break_plan.further_available if break_plan is not None else False
        ),
        suggestions_would_pass=(break_plan.would_pass if break_plan is not None else False),
        punctuation_cannot_fix=(list(break_plan.unfixable) if break_plan is not None else []),
        suitability=(
            StyleSuitabilityOut(suitable=suitability.suitable, reason=suitability.reason)
            if suitability is not None
            else None
        ),
    )


@router.post("/{project_id}/script/rewrite", response_model=ScriptRewriteResponse)
async def rewrite_script_endpoint(
    project_id: str,
    body: ScriptRewriteRequest,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> ScriptRewriteResponse:
    """Level 3 of the script pre-flight (motion_new_styles_and_long_form_
    videos.md §3.2/§3.3) - rephrases a script into more, shorter shots
    when levels 1-2 (re-punctuation alone, `POST /script/preflight`'s
    `suggested_breaks`) can't reach a fast style's pacing target.

    **Stateless by default, like `POST /script/preflight`** - `body.script`
    travels in the request rather than being read from the project, so a
    rewrite can be tried against draft text before it's ever uploaded.
    Nothing is persisted unless `body.persist=True`, and even then, only
    when the rewrite passed every backstop in `app/script/rewrite.py`
    (`accepted=True`) - a rejected rewrite (a changed number, a dropped
    entity, or a no-op) is never persisted regardless of the flag, per
    §3.3's own "reject it" language.

    **Same freeze check as `upload_script`/`POST /style`, for the same
    reason** - persisting a rewrite after planning has started would
    silently invalidate everything already built on the old script text.
    Checked only when `persist=True` actually reaches that branch, not
    on every stateless "just show me the diff" call.
    """
    await _get_project_or_404(project_id, repo)
    if body.style not in STYLE_PACING_BANDS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown style {body.style!r} - known styles: {sorted(STYLE_PACING_BANDS)}",
        )

    llm_provider = None if settings.dry_run else OpenAIPlanningProvider()
    result = await rewrite_script(
        body.script,
        body.style,
        provider=llm_provider,
        llm_call_repo=LlmCallRepository(session),
        project_id=project_id,
    )
    if not settings.dry_run:
        await session.commit()

    if result is None:
        return ScriptRewriteResponse(attempted=False)

    persisted = False
    if body.persist and result.accepted:
        active = await timeline_service.get_active(project_id)
        if active is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "script cannot be changed after planning has started - "
                    f"project {project_id} already has an active timeline"
                ),
            )
        await repo.append_rewritten_script(project_id, result.rewritten_script)
        persisted = True

    feasibility = result.feasibility
    return ScriptRewriteResponse(
        attempted=True,
        accepted=result.accepted,
        rejection_reasons=result.rejection_reasons,
        rewritten_script=result.rewritten_script,
        original_fragment_count=result.original_fragment_count,
        rewritten_fragment_count=result.rewritten_fragment_count,
        feasibility=(
            RewriteFeasibilityOut(
                passed=feasibility.passed,
                violations=feasibility.violations,
                fragment_count=feasibility.fragment_count,
                estimated_total_duration_s=feasibility.estimated_total_duration_s,
                estimated_average_shot_duration_s=feasibility.estimated_average_shot_duration_s,
            )
            if feasibility is not None
            else None
        ),
        persisted=persisted,
    )


@router.post("/{project_id}/assets", response_model=list[UploadedAssetResult])
async def upload_assets(
    project_id: str,
    files: list[UploadFile] = File(...),
    descriptions: list[str] = Form(...),
    repo: ProjectRepository = Depends(get_repo),
    session: AsyncSession = Depends(get_db),
) -> list[UploadedAssetResult]:
    """M6.5, A8/A23/A27: media a human already has for this project,
    supplied alongside the script - entirely optional; a project that
    never calls this endpoint behaves exactly as it did before M6.5
    (`LocalProjectAssetProvider.search` returns `[]` and the ladder falls
    through unchanged). Each file carries its own short human-written
    `description` - matching against a filename would be worthless (A23)
    - and is validated and hashed on arrival (A27): the same
    `validate_and_identify_image` path every searched asset already goes
    through, so a file that claims to be an image and isn't fails HERE,
    not inside ffmpeg during the render. Matching to a specific shot
    happens later, automatically, through the existing relevance gate
    (`app/assets/relevance.py`) the next time `resolve_assets_search`
    runs - never here, and never through a planner (A3 stands)."""
    await _get_project_or_404(project_id, repo)
    if not files:
        raise HTTPException(status_code=400, detail="at least one file is required")
    if len(files) != len(descriptions):
        raise HTTPException(
            status_code=400,
            detail=f"{len(files)} file(s) but {len(descriptions)} description(s) - "
            "exactly one description per file is required",
        )

    project_uuid = uuid.UUID(project_id)
    asset_repo = AssetRepository(session)
    assets_dir = settings.storage_root / project_id / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    results: list[UploadedAssetResult] = []
    for upload, description in zip(files, descriptions, strict=True):
        if not description.strip():
            raise HTTPException(
                status_code=400,
                detail=f"{upload.filename}: a description is required (A23) - matching "
                "against a filename alone is not reliable",
            )
        content = await upload.read()
        try:
            ext, _width, _height = validate_and_identify_image(content)
        except PermanentError as exc:
            raise HTTPException(status_code=400, detail=f"{upload.filename}: {exc}") from exc

        content_hash = hashlib.sha256(content).hexdigest()
        existing = await asset_repo.get_by_content_hash(project_uuid, content_hash)
        if existing is not None:
            # Same bytes already on file for this project (M6, hash
            # dedup) - not an error, just nothing new to store.
            results.append(
                UploadedAssetResult(
                    asset_id=str(existing.id), filename=upload.filename or "", duplicate=True
                )
            )
            continue

        path = assets_dir / f"{content_hash}.{ext}"
        path.write_bytes(content)
        asset = await asset_repo.insert(
            project_id=project_uuid,
            provider="project_assets",
            source_url=None,
            type="image",
            local_path=str(path),
            licence="human_upload",
            attribution=None,
            content_hash=content_hash,
            confidence=1.0,
            description=description.strip(),
        )
        results.append(
            UploadedAssetResult(
                asset_id=str(asset.id), filename=upload.filename or "", duplicate=False
            )
        )

    await session.commit()
    return results


@router.get("/{project_id}/timeline", response_model=Timeline)
async def get_timeline(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
) -> Timeline:
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=404, detail="no timeline generated yet")
    return active


@router.get("/{project_id}/prompts/export")
async def export_prompts(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
) -> Response:
    """P0 (docs/plans/gate_panel_overrides.md): every image prompt the
    active timeline will ever ask a provider for, as one plain-text blob a
    human can paste into a provider whose quota they already pay for
    (§1's measured workflow - copy a prompt, generate it in Grok, upload
    via `override_shot_asset` instead of paying fal.ai). See
    `app/assets/prompt_export.py`'s own module docstring for the full
    reasoning - in short, every prompt here is built by calling the exact
    same `styled_prompt`/`layer_styled_prompt` functions
    `resolve_assets_generate` itself calls (R1), never a re-derivation,
    and layer prompts are included even though P0 does not make them
    uploadable (P1 does) - the user can already generate them by hand,
    they just had no way to see them before this endpoint existed.

    `Content-Disposition: attachment` so a direct navigation (or the
    frontend's own `<a download>`) saves a `.txt` file instead of
    rendering a page of prompt text in the browser; a caller that fetches
    this for the "copy everything to the clipboard" gesture reads the same
    bytes and simply ignores the header."""
    project = await _get_project_or_404(project_id, repo)
    timeline = await timeline_service.get_active(project_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="no timeline generated yet")
    entries = build_prompt_export_entries(timeline)
    text = render_prompt_export_text(timeline, entries, project_name=project.name)
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{project_id}-prompts.txt"'},
    )


@router.post("/{project_id}/render", status_code=202, response_model=WorkflowTriggerResult)
async def render_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """Starts (or resumes) the workflow engine in the background (F0a) -
    returns immediately with a run id; poll `GET /status`/`GET /progress`
    for what actually happens next (AWAITING_APPROVAL, AWAITING_REVIEW,
    COMPLETED, or FAILED). This is the "advance the whole workflow"
    trigger - it can plan, search, generate, AND render, in that order,
    stopping at the first unsatisfied step. `POST /render/only` (R3) is
    the narrower sibling that touches only the render step, structurally
    unable to reach any of the paid steps this endpoint is allowed to
    run."""
    project = await _get_project_or_404(project_id, repo)
    if not project.script:
        raise HTTPException(status_code=400, detail="upload a script before rendering")
    return await start_workflow_run(project_id, session, background_tasks)


@router.post("/{project_id}/render/only", status_code=202, response_model=WorkflowTriggerResult)
async def render_only(
    project_id: str,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """R3: re-render without re-running the rest of the pipeline - the
    endpoint that "changed the mix, want to hear it" is supposed to hit,
    at zero risk of a paid provider call (see `app/workflow/render_only.py`
    for exactly why that is a structural guarantee, not a policy one).

    Fails loudly with `409` rather than silently advancing the workflow
    when a render genuinely is not possible yet (plan unapproved,
    narration never run, a shot still waiting on generation or review) -
    `render_precondition_gap` names the first step still blocking it, so
    the error tells a human what to do (usually: call `POST /render`
    instead, which IS allowed to advance those steps)."""
    project = await _get_project_or_404(project_id, repo)
    if not project.script:
        raise HTTPException(status_code=400, detail="upload a script before rendering")

    ctx = RunContext(
        project_id=project_id, session=session, repo=repo, timeline_service=timeline_service
    )
    blocking_step = await render_precondition_gap(ctx)
    if blocking_step is not None:
        raise HTTPException(
            status_code=409,
            detail=f"project is not ready for a render-only pass yet - step "
            f"'{blocking_step}' has not completed. Use POST /render to advance the "
            "full workflow, or GET /progress to see what's outstanding.",
        )

    return await start_workflow_run(project_id, session, background_tasks, steps=RENDER_ONLY_STEPS)


@router.post("/{project_id}/render/draft")
async def render_draft(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """A fast, low-res preview of the CURRENT active timeline (M8 step 6,
    "always render a fast draft first") - independent of `POST /render`'s
    own workflow-engine progression, so a human can preview a timeline
    that hasn't been approved yet, and can re-preview after any edit
    without disturbing `project.video_path`/`project.status` at all: this
    endpoint never touches either, only writes `draft.mp4` and a `render`
    row.

    Reuses `render_video` (`app/workflow/steps/render.py`) directly with
    `settings.draft_width/draft_height` and `output_filename="draft.mp4"`
    - the exact same fingerprinted, cached, deterministic pipeline the
    final render uses, just at a different resolution. Draft and final
    can never collide on one cache entry (width/height are themselves
    part of the fingerprint - see `app/renderer/fingerprint.py`).

    Opportunistically sweeps expired drafts (`settings.draft_retention_days`,
    D3) on every call - see `app/renderer/retention.py` for why a request-
    triggered sweep, rather than a scheduler, is the right amount of
    infrastructure here.

    **Deliberately NOT backgrounded (F0a scope note, 2026-08-16)**: F0a's
    own evidence (`POST /render` measured past 600s) is about the FULL
    workflow - planning, paid search/generation, and render together -
    never about this endpoint, which only ever calls `render_video`
    directly (no planners, no providers) at a resolution chosen
    specifically so iteration is fast (M8 Advice: "iteration at 8 seconds
    beats iteration at 4 minutes"). Backgrounding it would add a poll
    round-trip to the one render path meant to feel instant; revisit if a
    real draft is ever measured taking long enough to need it.
    """
    await _get_project_or_404(project_id, repo)
    timeline = await timeline_service.get_active(project_id)
    if timeline is None:
        raise HTTPException(status_code=400, detail="no timeline to render a draft of yet")

    purged = await purge_expired_drafts(session)

    draft = resolve_draft_format(
        timeline.metadata.render_style,
        frame_aspect=timeline.metadata.frame_aspect,
    )
    render_settings = RenderSettings(
        width=draft.width,
        height=draft.height,
        fps=settings.render_fps,
        pixel_format=settings.render_pixel_format,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
        # burn_captions/watermark_enabled deliberately omitted (both
        # default False) - drafts never burn captions or the watermark
        # regardless of the config toggles (docs/14_Captions_Plan.md
        # §4.3; docs/plans/watermark_implementation_plan.md §5).
    )
    ctx = RunContext(
        project_id=project_id, session=session, repo=repo, timeline_service=timeline_service
    )
    try:
        output_path = await render_video(
            ctx, timeline, render_settings, output_filename="draft.mp4", is_draft=True
        )
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()

    return {
        "project_id": project_id,
        "timeline_version": timeline.version,
        "draft_path": str(output_path),
        "expired_drafts_purged": purged,
    }


@router.get("/{project_id}/video/draft")
async def get_draft_video(
    project_id: str, repo: ProjectRepository = Depends(get_repo)
) -> FileResponse:
    project = await _get_project_or_404(project_id, repo)
    path = settings.storage_root / project_id / "renders" / "draft.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no draft render for this project yet")
    return FileResponse(path, media_type="video/mp4", filename=f"{project.id}_draft.mp4")


@router.post(
    "/{project_id}/timeline/approve", status_code=202, response_model=WorkflowTriggerResult
)
async def approve_timeline(
    project_id: str,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
    confirmed_cost_cents: int | None = None,
) -> WorkflowTriggerResult:
    """Approves the active timeline and resumes the engine (which, under
    the one-gate redesign, runs straight through narration-review into
    paid generation - see `app/workflow/engine.DEFAULT_PIPELINE`).

    **Task 2 (2026-08-16, the one-gate redesign) - refuses with 400 if any
    shot at the active version has no media bound yet.** A shot counts as
    filled when its `ShotBinding.state` is `"resolved"` (found by search,
    or supplied via override) or `"generated"` (already generated,
    including via `POST /shots/{shot_id}/generate` before approval) -
    the same `_TERMINAL_SHOT_STATES` `GET /progress` already reports
    `completed_shots` against. Anything else - no binding row at all,
    `"awaiting_generation"`, `"pending"`, `"failed"` - blocks approval and
    names the specific shots, so a human knows exactly what to fix.

    This is A26's "you cannot finish with a gap" moved EARLIER, to "you
    cannot approve with a gap" - strictly better, since it is caught
    before anything is spent rather than after a batch of unattended
    generation has already run. It is also the actual money guard the
    one-gate design depends on: without it, approving a plan with empty
    shots would immediately let `resolve_assets_generate` batch-generate
    every one of them unattended, right after this endpoint returns -
    exactly the unsupervised spend this whole redesign exists to prevent.
    A human is expected to have already looked at (or explicitly
    generated, via the per-shot endpoint) every shot's picture before
    ever calling this endpoint.

    Track C C5: also stamps every remaining scene id into
    `metadata.approved_scenes` (the one source of truth; the flat
    Approve button is sugar over the same field). Per-scene
    `POST /scenes/{id}/approve` records a review without starting
    the pipeline; this endpoint is what actually gates paid
    generation.

    Track C C6: when `require_cost_estimate_before_approval` is on,
    `DRY_RUN` is off, and spent + remaining estimate is greater than
    zero, the caller must echo that total as `confirmed_cost_cents`
    (query). Dry-run spend is fake and may omit it. The remaining
    estimate is least accurate for shots with no binding yet.

    Consequence, worth being explicit about: `resolve_assets_generate`
    does not stop being useful - a shot can still reach it in the
    `awaiting_generation` state that this guard blocks on IF this guard
    didn't exist, but since it does, every shot must already be
    `resolved`/`generated` by the time approval succeeds, so that step
    becomes a no-op safety net (nothing left for it to do) rather than
    the thing that actually spends the project's money.
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to approve yet")
    if active.status == TimelineStatus.APPROVED:
        raise HTTPException(status_code=400, detail="timeline is already approved")

    bindings_by_shot = {
        b.shot_id: b
        for b in await ShotBindingRepository(session).list_for_version(
            uuid.UUID(project_id), active.version
        )
    }
    unfilled_shot_ids = _unfilled_shot_ids(active.all_shots(), bindings_by_shot)
    if unfilled_shot_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "cannot approve - these shots have no image yet: "
                f"{unfilled_shot_ids}. Upload one (POST /shots/{{shot_id}}/override) "
                "or generate one (POST /shots/{shot_id}/generate) for each before "
                "approving."
            ),
        )

    # C5: remaining scene ids are stamped in `timeline_service.approve`
    # on this same version (in-place, like `status=APPROVED`). An
    # `append_version` here would flip `produced_by` to HUMAN and make
    # `NarrationStep.is_satisfied` false, re-running TTS after the gate.

    binding_states = {shot_id: b.state for shot_id, b in bindings_by_shot.items()}
    estimated_cost_cents = estimate_project_cost_cents(active, binding_states)
    spent_cost_cents = await total_project_spend_cents(
        clip_repo=GeneratedClipRepository(session),
        narration_repo=NarrationRepository(session),
        project_id=uuid.UUID(project_id),
    )
    expected_cents = spent_cost_cents + estimated_cost_cents
    if (
        settings.require_cost_estimate_before_approval
        and not settings.dry_run
        and expected_cents > 0
        and confirmed_cost_cents != expected_cents
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "confirm the project cost before approving: send "
                f"confirmed_cost_cents={expected_cents} (spent "
                f"{spent_cost_cents} + remaining estimate {estimated_cost_cents}). "
                "The remaining estimate is least accurate for shots with no "
                "binding yet (it falls back to the plan's primary strategy)."
            ),
        )

    await timeline_service.approve(project_id, active.version)
    return await start_workflow_run(project_id, session, background_tasks)


class SceneApprovalResult(BaseModel):
    scene_id: str
    approved: bool
    approved_scenes: list[str]
    all_scenes_approved: bool


@router.post("/{project_id}/scenes/{scene_id}/approve", response_model=SceneApprovalResult)
async def approve_scene(
    project_id: str,
    scene_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> SceneApprovalResult:
    """C5 / Q6: record that a human approved one scene. Monotonic — the
    id is appended to `metadata.approved_scenes` and never removed.
    Idempotent: a second call for an already-approved scene is a no-op
    (no version bump).

    This is a review record, not a lock and not the engine gate. It
    does not freeze the scene against later regenerate/override, and it
    does not stamp document `APPROVED` or start the pipeline — that
    stays `POST /timeline/approve`, which also fills any remaining
    scene ids. `AwaitApprovalStep` keeps checking document status only.

    Refuses (400) if any shot in this scene is not yet `resolved` /
    `generated` — the same filled-media rule `approve_timeline` uses,
    scoped to the scene so a human can approve scene 1 while scene 12
    still has a gap.
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to approve a scene on yet")
    scene = next((s for s in active.scenes if s.id == scene_id), None)
    if scene is None:
        raise HTTPException(
            status_code=404, detail=f"scene {scene_id} not found in the active timeline"
        )

    bindings_by_shot = {
        b.shot_id: b
        for b in await ShotBindingRepository(session).list_for_version(
            uuid.UUID(project_id), active.version
        )
    }
    unfilled_shot_ids = _unfilled_shot_ids(scene.shots, bindings_by_shot)
    if unfilled_shot_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                f"cannot approve scene {scene_id} - these shots have no image yet: "
                f"{unfilled_shot_ids}. Upload one (POST /shots/{{shot_id}}/override) "
                "or generate one (POST /shots/{shot_id}/generate) for each before "
                "approving."
            ),
        )

    if scene_id in active.metadata.approved_scenes:
        return SceneApprovalResult(
            scene_id=scene_id,
            approved=True,
            approved_scenes=list(active.metadata.approved_scenes),
            all_scenes_approved=_all_scenes_approved(active),
        )

    def _add_scene(base: Timeline) -> Timeline:
        base.metadata.approved_scenes = _merge_approved_scenes(base, [scene_id])
        return base

    try:
        active = await timeline_service.append_version(
            project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_add_scene,
            owns=frozenset({"metadata.approved_scenes"}),
        )
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SceneApprovalResult(
        scene_id=scene_id,
        approved=True,
        approved_scenes=list(active.metadata.approved_scenes),
        all_scenes_approved=_all_scenes_approved(active),
    )


class RegenerateFailedResult(BaseModel):
    scene_id: str
    shot_ids: list[str]
    estimated_cost_cents: int
    regenerated: bool
    results: list[GenerateShotImageResult] = []


@router.post(
    "/{project_id}/scenes/{scene_id}/regenerate-failed",
    response_model=RegenerateFailedResult,
)
async def regenerate_failed_in_scene(
    project_id: str,
    scene_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
    confirmed_cost_cents: int | None = None,
) -> RegenerateFailedResult:
    """C5: regenerate every `failed` shot in one scene. A batch wrapper
    over `POST /shots/{id}/generate` (the existing per-shot image
    endpoint) — motion clips stay on `POST /shots/{id}/generate/video`
    because that path is async and has no dry-run fake.

    Always returns an estimate and requires `confirmed_cost_cents`
    matching it when the estimate is greater than zero. Unlike timeline
    approve, dry-run does not skip the confirmation: a 12-shot bulk
    click is the thing §6 said must not fire on the first press.

    Scene approval is not a lock (A25/A20): this runs on failed shots
    even inside an already-approved scene — that is Q6's repair path.
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to regenerate failed shots on yet")
    scene = next((s for s in active.scenes if s.id == scene_id), None)
    if scene is None:
        raise HTTPException(
            status_code=404, detail=f"scene {scene_id} not found in the active timeline"
        )

    bindings_by_shot = {
        b.shot_id: b
        for b in await ShotBindingRepository(session).list_for_version(
            uuid.UUID(project_id), active.version
        )
    }
    failed_shots = [
        shot
        for shot in scene.shots
        if bindings_by_shot.get(shot.id) is not None and bindings_by_shot[shot.id].state == "failed"
    ]
    if not failed_shots:
        raise HTTPException(
            status_code=400, detail=f"scene {scene_id} has no failed shots to regenerate"
        )

    estimated_cost_cents = _failed_regenerate_cost_cents(len(failed_shots))
    shot_ids = [shot.id for shot in failed_shots]
    if estimated_cost_cents > 0 and confirmed_cost_cents != estimated_cost_cents:
        raise HTTPException(
            status_code=400,
            detail=(
                "confirm the regenerate cost before running: send "
                f"confirmed_cost_cents={estimated_cost_cents} for "
                f"{len(failed_shots)} failed shot(s) in scene {scene_id}."
            ),
        )

    results: list[GenerateShotImageResult] = []
    for shot in failed_shots:
        try:
            results.append(
                await _generate_shot_image_now(
                    session=session,
                    project_id=project_id,
                    timeline=active,
                    shot=shot,
                )
            )
        except PermanentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RegenerateFailedResult(
        scene_id=scene_id,
        shot_ids=shot_ids,
        estimated_cost_cents=estimated_cost_cents,
        regenerated=True,
        results=results,
    )


def apply_override_to_binding(binding, asset, *, panel: str) -> None:
    """Write a human upload onto the primary or the split-screen bottom
    panel. R16: assignment is already in the render fingerprint, so
    swapping the bottom panel misses the cache."""
    if panel == "secondary":
        binding.secondary_asset_id = asset.id
        binding.secondary_clip_id = None
        binding.secondary_state = "resolved"
        binding.secondary_last_error = None
        return
    binding.asset_id = asset.id
    binding.clip_id = None
    binding.state = "resolved"
    binding.rung = "project_assets"
    binding.last_error = None


@router.post(
    "/{project_id}/shots/{shot_id}/override", status_code=202, response_model=WorkflowTriggerResult
)
async def override_shot_asset(
    project_id: str,
    shot_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    description: str = Form(""),
    panel: str = Query("primary"),
    focal_x: float | None = Form(None),
    focal_y: float | None = Form(None),
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """M6.5, A9/A10/A24/A25/A29: a human names a shot directly and
    supplies its media themselves. Bypasses relevance and licence gates
    entirely (A24) - a human pointing at a specific shot has already made
    the judgement those gates exist to approximate. Works on ANY shot,
    not only a failed one (a Done-when criterion of this phase is "swap
    or override any of them"), and is also the sole remedy for the A26
    review gate when a shot ends `failed`.

    Recorded as an `append_version` with `produced_by=HUMAN` that sets
    `shot.asset_locked` (A10/A25) - once locked, no later version may
    change that shot's `prompt`/`asset_plan` at all
    (`TimelineService._reject_locked_shot_drift`), and its binding
    carries forward unconditionally across every future version
    (`TimelineService._carry_forward_bindings`). A29: this changes ONLY
    the binding and the lock flag - `duration_s`, narration, framing,
    camera and transitions are never touched, so an override is always a
    free, instant swap, never a paid re-narration.

    `panel=secondary` writes the split-screen bottom still and does
    not change the top panel's binding. The shot is still
    `asset_locked` (A25) regardless of panel — a later re-plan cannot
    change this shot's `prompt` / `asset_plan` / `secondary_*` either.
    That is conservative (the upload survives) and is the same lock a
    primary override has always taken. Refuses unless the shot is
    `split_frame`. Default `panel=primary` is the original contract.

    Validated and hashed on arrival exactly like the general upload
    endpoint (A27). If the plan was already approved, the new locked
    version is immediately re-approved too - the same "belt and braces"
    pattern `NarrationStep` already uses to append-then-approve in two
    commits - so resuming does not demand a redundant second human click.
    A project that had never been approved yet is left in DRAFT and the
    workflow is NOT resumed: `NarrationStep.is_satisfied` keys off
    `produced_by == NARRATION`, so a HUMAN override would look like
    "narration is stale" and bounce the review UI to /progress. Approve
    is what should start the next steps. Voice retry is a different
    endpoint and still resumes.

    long_form_direction.md A13: an upload used to get no focal sidecar at
    all, so the Ken Burns aim fell back to the geometric centre of a
    photograph the vision pipeline never looked at. Now, per content
    hash: `focal_x`/`focal_y` supplied (0..1, image space) are recorded
    verbatim under `FOCAL_SOURCE_HUMAN` and always win, overwriting any
    existing sidecar - the same "human decision outranks everything
    computed" precedent `asset_locked` already sets. Absent, and only
    when no sidecar exists yet for this hash, one `locate_subject_focal`
    vision call is made and persisted exactly as `resolve_assets.py`
    already does for a searched asset. A vision failure, refusal, or
    `None` answer degrades silently to today's centred behaviour and
    never blocks the upload - a focal is an improvement, not a
    precondition. Providing only one of the two coordinates, or a
    non-finite value, is a 400 (`normalize_focal` cannot validate a
    half-answer into something usable).
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to override a shot on yet")
    shot = next((s for s in active.all_shots() if s.id == shot_id), None)
    if shot is None:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )
    if panel not in _OVERRIDE_PANELS:
        raise HTTPException(
            status_code=400,
            detail=f"panel must be one of {sorted(_OVERRIDE_PANELS)}, got {panel!r}",
        )
    if panel == "secondary" and shot.camera.movement != CameraMovement.SPLIT_FRAME:
        raise HTTPException(
            status_code=400,
            detail=f"shot {shot_id} is not split_frame; cannot override the bottom panel",
        )

    # A13b: a human stating the focal directly outranks a vision guess -
    # validated with `normalize_focal`'s own rules (finite, both-or-
    # neither), not a new bounds check. A half-answer (one coordinate
    # supplied, or a non-finite value) is a clear 4xx here rather than a
    # silent fall-through to A13a's vision call or to a centre.
    focal_coords_supplied = focal_x is not None or focal_y is not None
    human_focal = normalize_focal(focal_x, focal_y) if focal_coords_supplied else None
    if focal_coords_supplied and human_focal is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "focal_x and focal_y must both be supplied as finite numbers "
                f"in 0..1, got focal_x={focal_x!r} focal_y={focal_y!r}"
            ),
        )

    content = await file.read()
    # A human may hand over a MOTION clip, not only a still (2026-09-02,
    # at the user's request while mid-edit: they had a generated clip and
    # no way to put it in a shot). Try the image validator first - it is
    # the overwhelmingly common case and needs no subprocess - then fall
    # back to the video one. Both already exist and apply the same
    # "positively confirm real media" discipline; nothing new is being
    # trusted here.
    #
    # `max_video_shots_per_project` deliberately does NOT apply to a
    # hand-supplied clip, and nothing here needs to enforce that: the cap
    # lives in the Asset Planner (`planners/asset/planner.py`), which
    # downgrades excess VIDEO shots to image before generation is ever
    # attempted. Its whole purpose is to bound what the planner SPENDS on
    # `generate_video`. A file the user already owns costs nothing, so the
    # cap has no claim on it - decided by the user, 2026-09-02.
    media_type = "image"
    try:
        ext, _width, _height = validate_and_identify_image(content)
    except PermanentError as image_exc:
        try:
            ext, _width, _height = await validate_and_identify_video(content)
        except PermanentError as video_exc:
            # Report BOTH failures: "not a valid video" alone is baffling
            # when the user uploaded a corrupt JPEG, and vice versa.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"file is neither a valid image ({image_exc}) "
                    f"nor a valid video ({video_exc})"
                ),
            ) from video_exc
        media_type = "video"

    project_uuid = uuid.UUID(project_id)
    asset_repo = AssetRepository(session)
    content_hash = hashlib.sha256(content).hexdigest()
    assets_dir = settings.storage_root / project_id / "assets"
    asset = await asset_repo.get_by_content_hash(project_uuid, content_hash)
    if asset is None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        path = assets_dir / f"{content_hash}.{ext}"
        path.write_bytes(content)
        asset = await asset_repo.insert(
            project_id=project_uuid,
            provider="project_assets",
            source_url=None,
            type=media_type,
            local_path=str(path),
            licence="human_override",
            attribution=None,
            content_hash=content_hash,
            confidence=1.0,
            description=description.strip() or None,
        )

    # long_form_direction.md A13: this endpoint used to bypass focal
    # entirely - a human-uploaded photo aimed its Ken Burns move at the
    # geometric centre, a framing the engine never examined (unlike a
    # searched asset, which always runs `locate_subject_focal`). Keyed by
    # `content_hash` exactly like `resolve_assets.py`'s own sidecar, so a
    # repeat upload of identical bytes (or a second override of the same
    # photo) never re-pays for a vision call.
    #
    # A focal point is meaningless for a MOTION clip - it aims a Ken Burns
    # crop over a fixed image, and the renderer never runs Ken Burns on a
    # clip (`motion.py` sends it down the duration-fit branch instead). The
    # search rung applies exactly this guard as `not is_video_candidate`;
    # since 2026-09-02 this endpoint accepts video too, so the guard has to
    # be real here rather than satisfied by construction.
    if media_type == "video":
        human_focal = None
    elif human_focal is not None:
        # A13b: a human answer always wins - written last, unconditionally,
        # overwriting any prior vision (or earlier human) sidecar for this
        # hash. Same "human decision outranks everything computed"
        # precedent `asset_locked` sets for a re-plan.
        write_focal_sidecar(
            assets_dir,
            content_hash,
            focal_x=human_focal[0],
            focal_y=human_focal[1],
            source=FOCAL_SOURCE_HUMAN,
        )
    elif read_focal_sidecar(assets_dir, content_hash) is None:
        # A13a: the same two calls `resolve_assets.py:1352-1370` already
        # makes for a searched asset's top candidate. A focal is an
        # improvement to a shot, not a precondition for having one - any
        # failure here (a refusal, a provider error already swallowed
        # inside `locate_subject_focal`, or anything unexpected from this
        # new call site) degrades silently to today's centred behaviour
        # and must never fail the upload itself.
        vision_focal: tuple[float, float] | None = None
        try:
            vision_provider = None if settings.dry_run else OpenAIPlanningProvider()
            vision_focal = await locate_subject_focal(
                provider=vision_provider,
                llm_call_repo=LlmCallRepository(session),
                project_id=project_uuid,
                image=content,
                image_content_type=mime_type_for_extension(ext),
                shot_id=shot_id,
            )
        except Exception:
            logger.warning(
                "focal.override_vision_call_failed",
                extra={"shot_id": shot_id, "content_hash": content_hash},
                exc_info=True,
            )
            vision_focal = None
        if vision_focal is not None:
            persist_vision_focal(
                assets_dir,
                content_hash,
                focal_x=vision_focal[0],
                focal_y=vision_focal[1],
                shot_id=shot_id,
            )

    # See the identical comment in `_resume_after_human_correction` above
    # for why `produced_by == ProducedBy.NARRATION` is no longer treated
    # as approval-equivalent here (2026-08-16, Task 1) - narration now
    # runs BEFORE the approval gate, so seeing it on the active version
    # is routinely proof of nothing more than "narration has run once",
    # not "a human already approved this".
    was_already_approved = active.status == TimelineStatus.APPROVED

    def _lock_shot(base: Timeline) -> Timeline:
        # R22: `asset_locked` is shot-wide, not per panel. A bottom-panel
        # override still freezes prompt/asset_plan/secondary_* against
        # later re-plans so the upload cannot be planned away.
        for scene in base.scenes:
            for shot in scene.shots:
                if shot.id == shot_id:
                    shot.asset_locked = True
        return base

    new_timeline = await timeline_service.append_version(
        project_id,
        produced_by=ProducedBy.HUMAN,
        transform=_lock_shot,
        owns=frozenset({"scenes"}),
    )

    binding_repo = ShotBindingRepository(session)
    binding = await binding_repo.get_or_create_pending(project_uuid, new_timeline.version, shot_id)
    apply_override_to_binding(binding, asset, panel=panel)
    await session.flush()

    if was_already_approved:
        await timeline_service.approve(project_id, new_timeline.version)
        await session.commit()
        # Post-approval (the review backstop, or a swap on a finished
        # video): resume so generate/render can continue. The first-gate
        # path below must NOT resume — see that branch.
        return await start_workflow_run(project_id, session, background_tasks)

    await session.commit()
    # Still at the first approval gate (DRAFT). Resuming would re-run
    # NarrationStep because this HUMAN version is not `produced_by=
    # NARRATION` — A29 says an override is never a re-narration, and the
    # review UI bounced to /progress ("Recording narration") then back.
    # The photo is already bound; Approve is what should start the next
    # steps. Voice retry still resumes (it is a different endpoint).
    run_row = await WorkflowRunRepository(session).get_latest(project_uuid)
    if run_row is None:
        raise HTTPException(
            status_code=400,
            detail="no workflow run to attach this override to",
        )
    return WorkflowTriggerResult(
        project_id=project_id,
        workflow_run_id=str(run_row.id),
        state=run_row.state,
        joined_existing_run=True,
    )


@router.post(
    "/{project_id}/shots/{shot_id}/sfx-cue/clear",
    status_code=202,
    response_model=WorkflowTriggerResult,
)
async def clear_shot_sfx_cue(
    project_id: str,
    shot_id: str,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """long_form_direction.md A12: a human vetoes one shot's planner-
    authored diegetic SFX cue before `GenerateDiegeticSfxStep` spends on
    it (`~sfx_diegetic_cost_cents_estimate` cents each, post-approval).

    **Why this narrow endpoint, not `POST /sfx/{kind}/override`:** that
    endpoint 400s for `kind=diegetic` on purpose (see its own docstring)
    - its one-clip-per-kind model would wipe every shot's cue and replace
    them all with one ungrounded clip. A12 also considered clearing
    through an existing generic timeline-edit path instead of a new
    endpoint; none exists - the closest thing, `generate_shot_image`'s
    prompt edit, is bundled with a paid generation call, not a bare field
    change - so this is the "add a narrow per-shot endpoint" branch of
    that task's own choice, kept minimal and shaped exactly like
    `override_shot_asset` just above (same pre-check order, same
    was-already-approved branch, same `append_version`/`owns` shape).

    **Clearing means "no sound for this shot", never "regenerate".** Both
    gates that matter read `Shot.sfx_cue` directly, not a separate flag:
    `generate_diegetic_sfx.py::_cue_bearing_shots` (what
    `GenerateDiegeticSfxStep.run`/`is_satisfied` iterate) and
    `renderer/sfx.py::derive_sfx_events` (what schedules the actual mux
    event) both skip a shot whose `sfx_cue` is blank. So a shot cleared
    here drops out of the generation step entirely - it is never marked
    `failed`, never retried - and the renderer never schedules an event
    for it. A `SfxClipSelection` already recorded for this shot from an
    earlier run of `GenerateDiegeticSfxStep` (if the cue was cleared only
    after generation already happened) is left in `sfx_plan.clips`
    untouched; it is inert rather than a leak, since `derive_sfx_events`
    is what decides whether a shot gets a DIEGETIC event at all, and it
    never consults `sfx_plan.clips`.

    Same first-gate/already-approved branch as `override_shot_asset`:
    if the timeline was already approved (the review backstop, or a cue
    cleared after `GenerateDiegeticSfxStep` already ran once), the new
    version is re-approved and the workflow resumed; still at the first
    gate (DRAFT), it is left there for Approve to advance, for the same
    reason given there (resuming here would look like "narration is
    stale" to `NarrationStep.is_satisfied`, which this is not).
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to clear a cue on yet")
    shot = next((s for s in active.all_shots() if s.id == shot_id), None)
    if shot is None:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )
    if not (shot.sfx_cue or "").strip():
        raise HTTPException(status_code=400, detail=f"shot {shot_id} has no sfx cue to clear")

    was_already_approved = active.status == TimelineStatus.APPROVED

    def _clear_cue(base: Timeline) -> Timeline:
        for scene in base.scenes:
            for sh in scene.shots:
                if sh.id == shot_id:
                    sh.sfx_cue = None
        return base

    new_timeline = await timeline_service.append_version(
        project_id,
        produced_by=ProducedBy.HUMAN,
        transform=_clear_cue,
        owns=frozenset({"scenes"}),
    )

    if was_already_approved:
        await timeline_service.approve(project_id, new_timeline.version)
        await session.commit()
        # Post-approval: resume so generation/render can continue, exactly
        # like `override_shot_asset`'s equivalent branch.
        return await start_workflow_run(project_id, session, background_tasks)

    await session.commit()
    # Still at the first approval gate (DRAFT) - see `override_shot_asset`
    # just above for why resuming here would be wrong.
    run_row = await WorkflowRunRepository(session).get_latest(uuid.UUID(project_id))
    if run_row is None:
        raise HTTPException(
            status_code=400,
            detail="no workflow run to attach this correction to",
        )
    return WorkflowTriggerResult(
        project_id=project_id,
        workflow_run_id=str(run_row.id),
        state=run_row.state,
        joined_existing_run=True,
    )


class GenerateShotImageRequest(BaseModel):
    # Task 4 (2026-08-16): optional. `None` (the default, and what a
    # bare `POST` with no body deserialises to) means "regenerate with
    # the shot's EXISTING prompt, unchanged" - this endpoint's whole
    # original contract. A non-blank value that differs from the shot's
    # current `prompt` is treated as an edit - see the endpoint's own
    # docstring for why that is a Timeline change, not a parameter.
    prompt: str | None = None


class GenerateShotImageResult(BaseModel):
    shot_id: str
    clip_id: str
    # Task 6 (2026-08-16): what THIS call cost - always `0` on a cache
    # hit, never the clip row's ORIGINAL charge (which may have been
    # paid by an earlier click, or by the automatic pipeline). Before
    # this field existed, a cache hit reported the original charge and a
    # human clicking "generate" twice on an unchanged shot had no way to
    # tell "just spent 4 cents" from "reused an existing image, free".
    cost_cents: int
    # Task 6: explicit, rather than making the caller infer it from
    # `cost_cents == 0` (which is also true of a shot generation
    # configured to cost nothing - not a real scenario today, but not a
    # distinction this response should quietly rely on `cost_cents`
    # alone to carry).
    cache_hit: bool


@router.post("/{project_id}/shots/{shot_id}/generate", response_model=GenerateShotImageResult)
async def generate_shot_image(
    project_id: str,
    shot_id: str,
    body: GenerateShotImageRequest = GenerateShotImageRequest(),
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> GenerateShotImageResult:
    """A human, at the one asset-review gate, generates (or regenerates)
    exactly one shot's image on demand - the endpoint the review-gate
    redesign needed, since `resolve_assets_generate` only ever runs
    unattended across every shot at once, after approval.

    Deliberately synchronous, unlike every trigger above - no
    `background_tasks`, no `start_workflow_run`. A human sitting at this
    gate may click this several times across several shots before
    approving anything; resuming the workflow engine on every click
    would race the pipeline forward mid-review. Calls the exact same
    `generate_image_real` the post-approval pass itself calls
    (`app.workflow.steps.resolve_assets`), so a shot generated here and
    a shot generated automatically after approval behave identically -
    same cache key, same budget check, same clip record. Task 3
    (2026-08-16): repeat clicks on the SAME prompt now actually re-roll
    the image (`_generate_image_once`'s seed folds in how many clips
    already exist for this shot) rather than silently re-serving the
    first result for free - see that function's own docstring.

    **Task 4 (2026-08-16): `body.prompt` lets a human edit the prompt AND
    generate in one call.** Omitted, it behaves exactly as before -
    regenerate with the shot's existing `prompt`. Supplied and DIFFERENT
    from the shot's current `prompt`, it is a Timeline change (I2 -
    prompts are creative decisions, never something an endpoint mutates
    in place) and is recorded as its own `append_version(produced_by=
    HUMAN)` - touching only `scenes` (that one shot's `prompt`, nothing
    else) - BEFORE anything is generated; the freshly generated clip is
    then bound at THIS new version, not the one the request started
    against. The stored `shot.prompt` is the RAW edited text, exactly as
    a planner's own prompt is stored - `styled_prompt` (inside
    `generate_image_real`) still layers `creative_context.visual_style`
    on top at generation time for a human-edited prompt exactly as it
    does for a planner-written one, so a human edit does not skip the
    styling every other shot gets (decided by the user, 2026-08-16).
    A29 holds: this transform touches only `prompt` on the one named
    shot - `duration_s`, narration, framing, camera, and transitions on
    EVERY shot (including this one) are untouched, so editing a prompt
    never triggers a re-narration.

    **This endpoint no longer refuses to run on an `asset_locked` shot**
    (reversing the original per-shot-override-only reading; decided by
    the user, 2026-08-16: generate and override are peers, either may
    follow the other - a human may regenerate an AI alternative for a
    shot they previously overrode, or override again after generating).
    That symmetry has a real, surfaced limit, not a silently patched one:
    `TimelineService._reject_locked_shot_drift` (A25) unconditionally
    refuses ANY later version that changes a locked shot's `prompt`,
    regardless of `produced_by` - so calling this endpoint on a LOCKED
    shot WITHOUT an edited prompt still works (no Timeline change is
    attempted at all), but supplying an edited prompt for a locked shot
    raises here, translated to `400`, exactly like every other
    `append_version` rejection this file already surfaces. There is
    deliberately no bypass added for this - A25's own guarantee ("my
    photo is always in the plan") is exactly what would break if a
    locked shot's prompt could drift, and unlocking a shot is an
    explicitly deferred, separate feature (see A25a's own "known gap" -
    an unlock endpoint, not built here).
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to generate a shot image for yet")
    shot = next((s for s in active.all_shots() if s.id == shot_id), None)
    if shot is None:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )

    edited_prompt = body.prompt.strip() if body.prompt is not None else None
    if edited_prompt is not None and not edited_prompt:
        raise HTTPException(status_code=400, detail="prompt, if supplied, must not be blank")

    if edited_prompt is not None and edited_prompt != shot.prompt:

        def _set_prompt(base: Timeline) -> Timeline:
            for scene in base.scenes:
                for sh in scene.shots:
                    if sh.id == shot_id:
                        sh.prompt = edited_prompt
            return base

        try:
            active = await timeline_service.append_version(
                project_id,
                produced_by=ProducedBy.HUMAN,
                transform=_set_prompt,
                owns=frozenset({"scenes"}),
            )
        except PermanentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        shot = next(s for s in active.all_shots() if s.id == shot_id)

    try:
        return await _generate_shot_image_now(
            session=session,
            project_id=project_id,
            timeline=active,
            shot=shot,
        )
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _generate_shot_image_now(
    *,
    session: AsyncSession,
    project_id: str,
    timeline: Timeline,
    shot,
) -> GenerateShotImageResult:
    """The shared body of `POST /shots/{id}/generate` and C5's bulk
    regenerate-failed: one `generate_image_real` plus a commit. Callers
    own prompt-edit `append_version` and HTTP translation."""
    project_uuid = uuid.UUID(project_id)
    project_dir = settings.storage_root / project_id
    (project_dir / "clips").mkdir(parents=True, exist_ok=True)

    image_provider = FakeImageProvider() if settings.dry_run else FalImageProvider()
    clip_repo = GeneratedClipRepository(session)
    narration_repo = NarrationRepository(session)
    binding_repo = ShotBindingRepository(session)
    binding = await binding_repo.get_or_create_pending(project_uuid, timeline.version, shot.id)

    clip, cache_hit = await generate_image_real(
        shot,
        binding,
        project_uuid=project_uuid,
        project_dir=project_dir,
        image_provider=image_provider,
        clip_repo=clip_repo,
        narration_repo=narration_repo,
        creative_context=timeline.creative_context,
        cap_cents=budget_cap_cents_for(timeline),
        style=timeline.metadata.render_style,
        frame_aspect=timeline.metadata.frame_aspect,
    )
    await session.commit()
    return GenerateShotImageResult(
        shot_id=shot.id,
        clip_id=str(clip.id),
        cost_cents=0 if cache_hit else clip.cost_cents,
        cache_hit=cache_hit,
    )


class GenerateShotVideoResult(BaseModel):
    shot_id: str
    clip_id: str
    # `None` only ever on a `"completed"` clip predating `insert_pending`
    # (the fake/dry-run `insert()` path never sets one) - every real
    # submit-and-poll row (the only kind either endpoint below can ever
    # produce) has one from the moment it exists.
    job_id: str | None
    # "pending" | "completed" | "failed" - collapses the model's own
    # `"submitted"`/`"in_progress"` DB states into one API-facing
    # "pending" (see `_video_status_label`), matching A6's own wording in
    # the plan exactly rather than leaking an internal distinction the
    # caller never needs to act on differently.
    status: str
    error: str | None = None


def _video_status_label(clip: GeneratedClipModel) -> str:
    if clip.status in ("submitted", "in_progress"):
        return "pending"
    return clip.status


@router.post(
    "/{project_id}/shots/{shot_id}/generate/video",
    status_code=202,
    response_model=GenerateShotVideoResult,
)
async def generate_shot_video(
    project_id: str,
    shot_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> GenerateShotVideoResult:
    """A6 (motion_new_styles_and_long_form_videos.md Track A, 2026-08-18):
    a human, at the one asset-review gate, generates (or regenerates) one
    shot's VIDEO on demand - the video-path sibling of `generate_shot_
    image` above, wiring rather than invention: `submit_video_generation`
    is exactly `ResolveAssetsStep`'s own fresh-submission logic
    (`app.workflow.steps.resolve_assets`), called directly with no engine
    and no workflow trigger, for the identical reason `generate_shot_
    image` already gives - a human clicking across several shots before
    approving anything must never race the pipeline forward mid-review.

    **DECIDED 2026-08-18: this blocks while the keyframe generates
    (typically seconds - `FalImageProvider`'s 60s is a give-up ceiling,
    not the expected time), then returns `202`.** Kling stays image-to-
    video (A3a), so a still must exist before the video job can be
    submitted; the alternative (returning instantly and generating the
    keyframe in the background) would create an in-flight row with no
    `job_id` yet, an orphan state M7's own resume logic
    (`get_in_flight_for_shot`) does not expect and has no reaper for. See
    the plan's own A6 for the full reasoning.

    Explicitly polling, not synchronous, past this point - regeneration
    itself takes minutes, so the response here only ever reports
    `"pending"` for a fresh submission (or `"completed"`/an existing
    `"pending"` if this shot's video was already done or already
    in-flight - idempotent by construction, see `submit_video_
    generation`'s own docstring). `GET` on this same URL is how a caller
    learns the real outcome.

    No `DRY_RUN` support: unlike image generation, there is no fake video
    provider (`_resolve_one_fake` never generates video at all - every
    fake shot gets a fake IMAGE regardless of `preferred_type`), a
    pre-existing gap this endpoint does not attempt to close - refusing
    loudly here is preferable to a confusing failure three calls deep."""
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to generate a shot video for yet")
    shot = next((s for s in active.all_shots() if s.id == shot_id), None)
    if shot is None:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )
    if settings.dry_run:
        raise HTTPException(
            status_code=400,
            detail="video generation is not available under DRY_RUN - no fake video provider exists",
        )

    project_uuid = uuid.UUID(project_id)
    project_dir = settings.storage_root / project_id
    (project_dir / "clips").mkdir(parents=True, exist_ok=True)

    clip_repo = GeneratedClipRepository(session)
    narration_repo = NarrationRepository(session)
    binding_repo = ShotBindingRepository(session)
    binding = await binding_repo.get_or_create_pending(project_uuid, active.version, shot_id)

    try:
        clip, _is_fresh = await submit_video_generation(
            shot,
            binding,
            project_uuid=project_uuid,
            project_dir=project_dir,
            image_provider=FalImageProvider(),
            video_provider=FalVideoProvider(),
            clip_repo=clip_repo,
            narration_repo=narration_repo,
            creative_context=active.creative_context,
            cap_cents=budget_cap_cents_for(active),
            style=active.metadata.render_style,
            frame_aspect=active.metadata.frame_aspect,
        )
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    return GenerateShotVideoResult(
        shot_id=shot_id, clip_id=str(clip.id), job_id=clip.job_id, status=_video_status_label(clip)
    )


@router.get(
    "/{project_id}/shots/{shot_id}/generate/video",
    response_model=GenerateShotVideoResult,
)
async def poll_shot_video(
    project_id: str,
    shot_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> GenerateShotVideoResult:
    """The poll half of A6 - calls `poll_video_job`
    (`app.workflow.steps.resolve_assets`) directly, the SAME resume logic
    `ResolveAssetsStep` already used for crash recovery (M7), so a human
    polling from the gate and the automatic pipeline resuming after a
    restart observe the identical state machine. Never submits anything
    itself - a GET must not have the side effect of a fresh, paid
    generation - so `404`s if there is nothing in flight for this shot
    (nothing ever `POST`ed, or it already resolved and a caller is
    polling a stale reference) rather than silently starting one."""
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to poll a shot video for yet")
    shot = next((s for s in active.all_shots() if s.id == shot_id), None)
    if shot is None:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )
    if settings.dry_run:
        raise HTTPException(
            status_code=400,
            detail="video generation is not available under DRY_RUN - no fake video provider exists",
        )

    project_uuid = uuid.UUID(project_id)
    project_dir = settings.storage_root / project_id
    clip_repo = GeneratedClipRepository(session)
    binding_repo = ShotBindingRepository(session)
    binding = await binding_repo.get_or_create_pending(project_uuid, active.version, shot_id)

    clip = await poll_video_job(
        shot,
        binding,
        project_uuid=project_uuid,
        project_dir=project_dir,
        video_provider=FalVideoProvider(),
        clip_repo=clip_repo,
    )
    if clip is None:
        raise HTTPException(
            status_code=404,
            detail=f"no pending video generation for shot {shot_id} - call POST first",
        )

    await session.commit()
    return GenerateShotVideoResult(
        shot_id=shot_id,
        clip_id=str(clip.id),
        job_id=clip.job_id,
        status=_video_status_label(clip),
        error=clip.error,
    )


@router.post("/{project_id}/music/retry", status_code=202, response_model=WorkflowTriggerResult)
async def retry_music_selection(
    project_id: str,
    body: RetryMusicSelectionRequest,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """A selection miss is otherwise permanent: `SelectMusicStep.is_satisfied`
    returns true once `music_plan.selection_attempted` is set, so a
    project that found nothing suitable can never try again - not a bug
    in that check (a plain re-run with the SAME search terms would just
    fail the SAME way, wasting a real API round-trip to relearn nothing),
    but a real gap once the terms themselves might be the problem. Music
    is an asset choice like any other (M6.5's own principle): an
    automated choice a human disagrees with, or that came back empty,
    must be correctable - this is that correction, scoped to exactly this
    and nothing more (no music upload endpoint - a per-shot-image-upload
    analogue would fall out of this design if ever wanted, but was not
    asked for here and is not built).

    Resets `selected_track` to `None` and `selection_attempted` to
    `False` via a normal `append_version` (I3 - never mutated in place),
    optionally overriding the Timeline's own frozen `music_plan
    .search_terms` with human-supplied ones in the SAME version (`body
    .search_terms`, when given) - necessary because the existing terms
    are exactly what a human is trying to escape; resuming the engine
    with `is_satisfied` now false again re-runs `SelectMusicStep` for
    real, against whichever terms this call left in place. A project
    that has never yet attempted a selection is untouched by any of
    this - `is_satisfied`'s own logic isn't changed here at all, only
    reset to the same "nothing tried yet" state it already recognises.

    Shares its "record as HUMAN, re-approve if needed, resume" tail with
    `retry_narration_voice` (N1) via `_resume_after_human_correction` -
    see that helper's own docstring for why this one qualifies for the
    shared shape and `override_shot_asset` deliberately does not.
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to retry music selection on yet")
    if active.music_plan is None:
        raise HTTPException(status_code=400, detail="this timeline has no music_plan to retry")
    if body.search_terms is not None and not body.search_terms:
        raise HTTPException(status_code=400, detail="search_terms, if supplied, must not be empty")

    def _reset_music_plan(base: Timeline) -> Timeline:
        assert base.music_plan is not None
        base.music_plan.selected_track = None
        base.music_plan.act_beds = []
        base.music_plan.selection_attempted = False
        if body.search_terms is not None:
            base.music_plan.search_terms = body.search_terms
        return base

    return await _resume_after_human_correction(
        project_id,
        active,
        timeline_service=timeline_service,
        session=session,
        background_tasks=background_tasks,
        transform=_reset_music_plan,
        owns=frozenset({"music_plan"}),
    )


# Decision 7 (analysis.md, 2026-08-24): sane bounds on the upload slider -
# wide enough for any mastering mismatch C1a #4 describes, tight enough
# that a fat-fingered value cannot push the bed into clipping or silence.
_MUSIC_GAIN_OFFSET_DB_MIN = -40.0
_MUSIC_GAIN_OFFSET_DB_MAX = 24.0


@router.post("/{project_id}/music/upload", status_code=202, response_model=MusicUploadResult)
async def upload_music(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    gain_offset_db: float = Form(0.0),
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> MusicUploadResult:
    """C1 (analysis.md, resolved decisions 2/6a/6b/7): a human's own BGM.

    The fourth instance of the "automated creative choice, human redo"
    shape (after the per-shot override, music retry, and narration retry)
    - with the same `_resume_after_human_correction` tail: record as
    HUMAN via `append_version`, re-approve if already approved, resume
    the engine so the render fingerprint (changed by the new
    `content_hash`) produces a fresh render.

    Safety rails, each traced against a concrete failure mode in
    analysis.md C1a:

    - the bytes are ffprobe-validated HERE (`validate_and_identify_audio`,
      A27), never trusted from the extension;
    - the file is stored under its REAL container extension and
      `_music_file` globs by content hash, so a .wav/.m4a/.ogg/.flac
      upload resolves at render time instead of raising "file missing"
      (C1a #1);
    - `act_beds` is explicitly cleared, so `_music_segments`'s two-or-
      more-beds branch can never silently keep playing the old per-act
      tracks over an uploaded single bed (C1a #5 - the failure that ships
      looking done);
    - length NEVER rejects (decision 6a/6b): short tracks loop and long
      tracks trim from the start exactly as `mux_music` always behaved;
      the response carries human-readable warnings instead;
    - `gain_offset_db` rides on top of the style bed gain and is hashed
      into the render fingerprint (decision 7 / R2).

    Licence is `user_supplied` - A24's precedent: a human's own file is
    judged by the human; no CC0/CC-BY gate applies."""
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to attach music to yet")
    if active.music_plan is None:
        raise HTTPException(status_code=400, detail="this timeline has no music_plan")
    if not _MUSIC_GAIN_OFFSET_DB_MIN <= gain_offset_db <= _MUSIC_GAIN_OFFSET_DB_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"gain_offset_db must be between {_MUSIC_GAIN_OFFSET_DB_MIN:g} and "
                f"{_MUSIC_GAIN_OFFSET_DB_MAX:g}"
            ),
        )

    content = await file.read()
    try:
        ext, track_duration_s = await validate_and_identify_audio(
            content, ffprobe_binary=settings.ffprobe_binary
        )
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=f"{file.filename}: {exc}") from exc

    content_hash = hashlib.sha256(content).hexdigest()
    music_dir = settings.storage_root / project_id / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    (music_dir / f"{content_hash}.{ext}").write_bytes(content)

    filename = (file.filename or "").strip()
    attribution = (
        f"Supplied by the project owner ({filename})"
        if filename
        else "Supplied by the project owner"
    )

    def _set_uploaded_track(base: Timeline) -> Timeline:
        assert base.music_plan is not None
        base.music_plan.selected_track = MusicTrackSelection(
            provider="project_music",
            track_id=f"{content_hash}.{ext}",
            source_url="",
            licence="user_supplied",
            attribution=attribution,
            content_hash=content_hash,
            gain_offset_db=gain_offset_db,
        )
        # An upload IS an attempt outcome: SelectMusicStep must not think
        # this project still needs a search when the engine resumes.
        base.music_plan.selection_attempted = True
        # Decision 2 (analysis.md): ONE bed for the whole video. Without
        # this explicit clear, `_music_segments`'s len(beds) >= 2 branch
        # wins over `selected_track` and the render keeps playing the old
        # auto-picked per-act beds - success in the UI, wrong audio on
        # disk, no error anywhere (C1a #5).
        base.music_plan.act_beds = []
        return base

    video_duration_s = sum(shot.duration_s for shot in active.all_shots())
    warnings_ = music_upload_warnings(track_duration_s, video_duration_s)

    result = await _resume_after_human_correction(
        project_id,
        active,
        timeline_service=timeline_service,
        session=session,
        background_tasks=background_tasks,
        transform=_set_uploaded_track,
        owns=frozenset({"music_plan"}),
    )
    return MusicUploadResult(**result.model_dump(), warnings=warnings_)


@router.post(
    "/{project_id}/sfx/{kind}/override", status_code=202, response_model=WorkflowTriggerResult
)
async def override_sfx_kind(
    project_id: str,
    kind: SfxKind,
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(None),
    enabled: bool = Form(True),
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """C3f (analysis.md, decision 4): human control over ONE SFX kind -
    replace its clip with an uploaded file, or disable the kind outright.
    No clip-picker UI (decision 4); `kind` is validated by FastAPI against
    the `SfxKind` enum, then narrowed to the three STRUCTURAL kinds
    (whoosh / stinger / transition) below - `diegetic` (A8,
    long_form_direction.md) is per-shot, not one clip for the whole video,
    and is rejected with a 400 rather than silently mishandled by this
    endpoint's one-clip-per-kind model.

    Exactly one of two operations per call:

    - **`file` supplied** → ffprobe-validated here (`validate_and_identify_audio`,
      A27), hashed, stored at `storage/{project}/sfx/{sha256}.{real_ext}`,
      and that kind's entry in `sfx_plan.clips` is replaced. The glob
      lookup `_sfx_overlays` already uses (C1a #1 fix) means a .wav/.m4a/
      .ogg upload resolves at render time. Licence is `user_supplied`
      (A24 - a human's own file is judged by the human).
    - **`file` omitted + `enabled=false`** → every clip of that kind is
      REMOVED from `sfx_plan.clips`. Disable costs nothing extra: the
      renderer's `by_kind.get(kind)` miss already skips an absent kind,
      and `sfx_content_hashes` shrinking changes the render fingerprint,
      so the re-render is correct, not coincidental.

    Recorded via the correction family's shared tail
    (`_resume_after_human_correction`, `owns={"sfx_plan"}`) - HUMAN
    provenance per I3, re-approve if approved, backgrounded resume so the
    changed fingerprint produces a fresh render.

    Deliberately NOT built (decision 4): a clip-picker UI. The undo path
    for an override or disable applied here is `POST /sfx/retry`
    (`retry_sfx_selection`, below), which resets the kind and re-runs
    selection."""
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to override sfx on yet")
    if active.sfx_plan is None:
        raise HTTPException(status_code=400, detail="this timeline has no sfx_plan")
    if kind == SfxKind.DIEGETIC:
        # long_form_direction.md A8: DIEGETIC is per-SHOT (one clip per
        # distinct cue, keyed by `SfxClipSelection.shot_id`), not one
        # shared clip for the whole video like WHOOSH/STINGER/TRANSITION.
        # `apply_sfx_clip_override` below removes every clip of a kind
        # and replaces it with (at most) one - correct for the three
        # structural kinds, but applied to DIEGETIC it would silently
        # wipe every shot's cue and replace them all with a single
        # ungrounded (no `shot_id`) clip that no event could ever match.
        # No per-shot override endpoint exists yet; reject loudly rather
        # than accept a request this endpoint cannot honour correctly.
        raise HTTPException(
            status_code=400,
            detail=(
                "diegetic sfx is per-shot, not a single video-wide clip - this "
                "endpoint's one-clip-per-kind override does not apply to it"
            ),
        )

    if file is None and enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                "nothing to do: supply an audio file to replace this kind's "
                "clip, or enabled=false to disable the kind"
            ),
        )
    if file is not None and not enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                "conflicting request: uploading a file replaces the kind's "
                "clip (always enabled) - send either a file or enabled=false"
            ),
        )

    replacement: SfxClipSelection | None = None
    if file is not None:
        content = await file.read()
        try:
            ext, upload_duration_s = await validate_and_identify_audio(
                content, ffprobe_binary=settings.ffprobe_binary
            )
        except PermanentError as exc:
            raise HTTPException(status_code=400, detail=f"{file.filename}: {exc}") from exc

        content_hash = hashlib.sha256(content).hexdigest()
        sfx_dir = settings.storage_root / project_id / "sfx"
        sfx_dir.mkdir(parents=True, exist_ok=True)
        stored_path = sfx_dir / f"{content_hash}.{ext}"
        stored_path.write_bytes(content)
        # C3c/C3d: measure the uploaded clip once, here - same contract as
        # SelectSfxStep (None on failure -> flat-gain fallback at render).
        upload_peak_dbfs = await measure_peak_dbfs(
            stored_path, ffmpeg_binary=settings.ffmpeg_binary
        )

        filename = (file.filename or "").strip()
        replacement = SfxClipSelection(
            kind=kind,
            provider="project_sfx",
            track_id=f"{content_hash}.{ext}",
            source_url="",
            licence="user_supplied",
            attribution=(
                f"Supplied by the project owner ({filename})"
                if filename
                else "Supplied by the project owner"
            ),
            content_hash=content_hash,
            peak_dbfs=upload_peak_dbfs,
            duration_s=upload_duration_s,
        )

    def _apply_override(base: Timeline) -> Timeline:
        assert base.sfx_plan is not None
        base.sfx_plan.clips = apply_sfx_clip_override(base.sfx_plan.clips, kind, replacement)
        return base

    return await _resume_after_human_correction(
        project_id,
        active,
        timeline_service=timeline_service,
        session=session,
        background_tasks=background_tasks,
        transform=_apply_override,
        owns=frozenset({"sfx_plan"}),
    )


@router.post("/{project_id}/sfx/retry", status_code=202, response_model=WorkflowTriggerResult)
async def retry_sfx_selection(
    project_id: str,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """C3f / review of P5 RV8: the UNDO for per-kind SFX overrides and
    disables. `SelectSfxStep`'s skip check is
    `bool(sfx_plan.clips) or sfx_plan.selection_attempted`, so without
    this endpoint a disable was a ONE-WAY door - and not only for whoosh:
    stinger (every text-card shot, every style) and transition
    (non-cut xfades on archival/stillness) are equally disable-able and
    were equally unrecoverable.

    Exact mirror of `retry_music_selection`'s shape: reset `clips` to
    empty and `selection_attempted` to False via a normal
    `append_version` (I3), then resume through the correction family's
    shared tail - resuming re-runs `SelectSfxStep` for real against the
    local library. Previously uploaded override FILES remain on disk
    under their content hashes but become unreferenced (hash dedup means
    a future re-upload of the same bytes writes nothing new).

    Also clears `diegetic_failed_shot_ids` (A8, long_form_direction.md):
    wiping `clips` alone would leave a previously-failed cue-bearing shot
    permanently skipped (`GenerateDiegeticSfxStep.is_satisfied` treats a
    shot id in that list as terminal, the same way a `failed` ShotBinding
    is). This is the only retry surface diegetic generation has today -
    resuming re-attempts every cue-bearing shot, and a cue that already
    generated successfully hits the mandatory prompt-hash cache (no
    re-spend), so this is cheap even though it looks like a full
    re-selection."""
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to retry sfx selection on yet")
    if active.sfx_plan is None:
        raise HTTPException(status_code=400, detail="this timeline has no sfx_plan to retry")

    def _reset_sfx_plan(base: Timeline) -> Timeline:
        assert base.sfx_plan is not None
        base.sfx_plan.clips = []
        base.sfx_plan.selection_attempted = False
        base.sfx_plan.diegetic_failed_shot_ids = []
        return base

    return await _resume_after_human_correction(
        project_id,
        active,
        timeline_service=timeline_service,
        session=session,
        background_tasks=background_tasks,
        transform=_reset_sfx_plan,
        owns=frozenset({"sfx_plan"}),
    )


@router.post("/{project_id}/narration/retry", status_code=202, response_model=WorkflowTriggerResult)
async def retry_narration_voice(
    project_id: str,
    body: RetryNarrationVoiceRequest,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """N1 (2026-08-15): narration is otherwise permanently frozen at
    whichever voice it first ran with - `NarrationStep.is_satisfied`
    returns true whenever the active version is `produced_by ==
    NARRATION`, with no way back once that is true. The third instance
    of the same shape as the per-shot override and M3's music retry: an
    automated creative choice (here, ElevenLabs synthesising with
    whichever voice was configured) that a human may disagree with and
    must be able to redo.

    The fix needs no new plumbing: `NarrationStep.run` already reads
    `timeline.metadata.voice_id or settings.elevenlabs_voice_id`, so a
    per-project voice override is already honoured end to end - nothing
    calls it today because nothing ever WRITES `metadata.voice_id`. This
    endpoint is that write: a `produced_by=HUMAN` `append_version`
    setting `metadata.voice_id` makes the active version no longer
    `NARRATION`, so `is_satisfied` goes false and resuming the engine
    re-runs `NarrationStep` for real, with the new voice.

    Two properties fall out of the EXISTING narration cache and
    duration-reconciliation code, unchanged by this endpoint, and are
    exactly what make this safe to use experimentally (try a voice,
    dislike it, try another):

    - **Switching back is free.** The narration cache key is `hash(text
      + voice_id + model + output_format [+ speed if not 1.0])`
      (`compute_narration_content_hash`) - voice_id and speed are part
      of the hash, so a previously-used voice's audio is still on disk
      under its own content hash and is never re-synthesised, whatever
      DID change is (re-)synthesised once and cached the same way.
    - **Durations recompute, and a stale render is never served.**
      `NarrationStep` reconciles every shot's `duration_s` against the
      NEW voice's real spoken pace (D1, the master clock) in its own
      subsequent `append_version` - this endpoint does not need to touch
      `scenes` itself. Human-locked bindings still carry forward across
      that bump unconditionally (A11/A20/A25 - already proven under real
      conditions by the first live render). The render fingerprint
      (`app/renderer/fingerprint.py`) also changes: it is built from
      `narration_content_hashes`, and since voice_id is part of THAT hash
      too, a different voice always produces a different fingerprint -
      `RenderStep`'s cache-hit check can never serve the OLD voice's
      `final.mp4` for the new version. Belt and braces: `RenderStep
      .is_satisfied` independently invalidates too, since every
      `append_version` call (this one, and NarrationStep's own
      reconciliation) re-inserts every ShotBinding row via `TimelineService
      ._carry_forward_bindings`, and a freshly-inserted row's `updated_at`
      is always newer than the existing rendered file's mtime.

    Shares its "record as HUMAN, re-approve if needed, resume" tail with
    `retry_music_selection` (M3) via `_resume_after_human_correction` -
    see that helper's own docstring for the considered decision behind
    sharing exactly this much and no more.
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to retry narration on yet")
    if not body.voice_id.strip():
        raise HTTPException(status_code=400, detail="voice_id must not be empty")

    def _set_voice(base: Timeline) -> Timeline:
        base.metadata.voice_id = body.voice_id
        return base

    return await _resume_after_human_correction(
        project_id,
        active,
        timeline_service=timeline_service,
        session=session,
        background_tasks=background_tasks,
        transform=_set_voice,
        owns=frozenset({"metadata"}),
    )


@router.post(
    "/{project_id}/narration/retry-language",
    status_code=202,
    response_model=WorkflowTriggerResult,
)
async def retry_narration_language(
    project_id: str,
    body: RetryNarrationLanguageRequest,
    background_tasks: BackgroundTasks,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> WorkflowTriggerResult:
    """Same shape as `retry_narration_voice` (N1) just above, for the
    `language_code` hint ElevenLabs' `language_code` parameter uses
    (2026-08-24, added while fixing a Hindi/Hinglish narration quality
    issue - see `hinglish_voice_probe.py`). `NarrationStep.run` already
    reads `timeline.metadata.language_code or settings
    .elevenlabs_language_code`, so this endpoint is the write half of
    that read, exactly like `retry_narration_voice` is for `voice_id`.

    Every property that endpoint's own docstring argues for `voice_id`
    holds here for the identical reason: `language_code` is part of
    `compute_narration_content_hash`, so switching it (or clearing it
    back to `None`) never re-pays for a hash already synthesised, and
    `RenderStep`'s fingerprint/cache-hit checks invalidate the same way.
    Unlike voice_id, `None` is accepted here - it is the explicit "clear
    the hint" case, not an empty-string mistake to reject.
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to retry narration on yet")

    def _set_language(base: Timeline) -> Timeline:
        base.metadata.language_code = body.language_code
        return base

    return await _resume_after_human_correction(
        project_id,
        active,
        timeline_service=timeline_service,
        session=session,
        background_tasks=background_tasks,
        transform=_set_language,
        owns=frozenset({"metadata"}),
    )


@router.get("/{project_id}/status")
async def get_status(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> dict:
    project = await _get_project_or_404(project_id, repo)
    return {"project_id": project.id, "status": project.status, "error": project.error}


@router.get("/{project_id}/progress")
async def get_progress(
    project_id: str,
    request: Request,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
    expand: str | None = None,
):
    """Progress is derived from shot_binding state, never stored as a
    number - a stored percentage drifts the moment anything fails
    (implementation guide, Phase M4 advice).

    Track C §13.4: default payload is scene summaries (`scenes[]`) plus
    counts. Per-shot detail (`shots[]`) is opt-in via `expand=shots` or
    `GET /scenes/{scene_id}/shots`. ETag is a hash of the assembled
    payload, not `timeline.version`.
    """
    project = await _get_project_or_404(project_id, repo)
    run_row = await WorkflowRunRepository(session).get_latest(uuid.UUID(project_id))

    base = {
        "project_id": project.id,
        "status": project.status,
        "workflow_state": run_row.state if run_row else None,
        "current_step": run_row.current_step if run_row else None,
    }

    timeline = await timeline_service.get_active(project_id)
    if timeline is None:
        return _progress_etag_response(
            {
                **base,
                "total_shots": 0,
                "completed_shots": 0,
                "failed_shots": 0,
                "progress": None,
                "estimated_cost_cents": 0,
                "spent_cost_cents": 0,
                "budget_cap_cents": settings.project_budget_cap_cents,
                "shots": [],
                "scenes": [],
            },
            request,
        )

    bindings = await ShotBindingRepository(session).list_for_version(
        uuid.UUID(project_id), timeline.version
    )
    total = len(timeline.all_shots())
    completed = sum(1 for b in bindings if b.state in _TERMINAL_SHOT_STATES)
    failed = sum(1 for b in bindings if b.state == "failed")

    # Per-shot detail - this is the only place shot_binding state is
    # exposed today (M9's dedicated shot-review surface doesn't exist
    # yet), so a failed shot's reason (e.g. a constraint violation that
    # exhausted its regeneration attempts, M6.5 A14/A19) must be visible
    # here rather than only as an aggregate count.
    #
    # M6.5 (A5/A21/A22): the whole point of moving free search before the
    # approval gate is that a human sees, per shot, what was ALREADY
    # FOUND (with its real source - `asset`, populated whenever
    # `asset_id` is set) versus what WILL BE GENERATED
    # (`will_generate`, true exactly when the search-only pass deferred
    # this shot rather than found or failed it). There is no frontend yet
    # (M9) - this is the API surface that stands in for "the human sees
    # the images": the resolved asset's provenance plus its path on disk.
    # M6.5, A9/A10: whether a human already locked this shot's asset via
    # the override endpoint - the other half of "a human can see, and
    # swap or override, any shot's asset" (this phase's Done-when
    # criterion): a locked shot's own state proves the override survives.
    locked_by_shot = {s.id: s.asset_locked for s in timeline.all_shots()}

    # M9 (folding shot semantics into /progress): everything below joins
    # execution state (shot_binding) with the CREATIVE meaning that only
    # lives on the Timeline itself (narration, prompt, intent, timing) -
    # without this, a human at the approval gate can see THAT a shot
    # resolved but not what it is or whether its picture is right.
    # `starts_at_s` reuses `compute_shot_start_times` (D5's own run/overlap
    # arithmetic - see app/timeline/duration.py) rather than a naive
    # cumulative sum of duration_s, which would be wrong the moment any
    # transition overlaps two shots.
    bindings_by_shot = {b.shot_id: b for b in bindings}
    start_times = compute_shot_start_times(timeline.all_shots())

    include_shots = expand == "shots"
    approved_set = set(timeline.metadata.approved_scenes)
    shots_detail = []
    scenes_detail = []
    for scene in timeline.scenes:
        scene_shot_ids: list[str] = []
        completed_in_scene = 0
        failed_in_scene = 0
        unfilled_in_scene = 0
        scene_starts_at: float | None = None
        for shot in scene.shots:
            scene_shot_ids.append(shot.id)
            b = bindings_by_shot.get(shot.id)
            start = start_times.get(shot.id)
            if scene_starts_at is None and start is not None:
                scene_starts_at = start
            if b is None:
                unfilled_in_scene += 1
                continue
            if b.state in _TERMINAL_SHOT_STATES:
                completed_in_scene += 1
            elif b.state == "failed":
                failed_in_scene += 1
                unfilled_in_scene += 1
            else:
                unfilled_in_scene += 1

            if include_shots:
                shots_detail.append(
                    await _shot_progress_entry(
                        session,
                        scene=scene,
                        shot=shot,
                        binding=b,
                        locked=locked_by_shot.get(b.shot_id, False),
                        start_times=start_times,
                    )
                )

        scenes_detail.append(
            {
                "id": scene.id,
                "act_id": scene.act_id,
                "title": scene.title,
                "shot_ids": scene_shot_ids,
                "total_shots": len(scene.shots),
                "completed_shots": completed_in_scene,
                "failed_shots": failed_in_scene,
                "unfilled_shots": unfilled_in_scene,
                "approved": scene.id in approved_set,
                "starts_at_s": scene_starts_at,
                "regenerate_failed_cost_cents": _failed_regenerate_cost_cents(failed_in_scene),
            }
        )

    # Estimated before generation runs (implementation guide, Phase M7
    # advice: "estimate cost before the approval gate and show it").
    # Task 5 (2026-08-16): passes each shot's OWN binding state
    # (`bindings_by_shot`, already built above for `shots_detail`) so the
    # estimate counts every shot the search pass has already determined
    # will fall through to generation (`"awaiting_generation"`), not only
    # shots whose PLAN's primary strategy happens to already be a
    # generation rung - see `estimate_project_cost_cents`'s own docstring
    # for the real run this was measured against (10 of 14 shots
    # generating, this number reading 0).
    estimated_cost_cents = estimate_project_cost_cents(
        timeline, {shot_id: b.state for shot_id, b in bindings_by_shot.items()}
    )
    spent_cost_cents = await total_project_spend_cents(
        clip_repo=GeneratedClipRepository(session),
        narration_repo=NarrationRepository(session),
        project_id=uuid.UUID(project_id),
    )
    budget_cap_cents = budget_cap_cents_for(timeline)

    return _progress_etag_response(
        {
            **base,
            "total_shots": total,
            "completed_shots": completed,
            "failed_shots": failed,
            "progress": (completed / total) if total else None,
            "estimated_cost_cents": estimated_cost_cents,
            "spent_cost_cents": spent_cost_cents,
            "budget_cap_cents": budget_cap_cents,
            "shots": shots_detail,
            "scenes": scenes_detail,
        },
        request,
    )


@router.get("/{project_id}/scenes/{scene_id}/shots")
async def get_scene_shots(
    project_id: str,
    scene_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """§13.4: shot detail for one expanded scene. The default
    `/progress` payload is scene summaries; this is what an opened
    group fetches."""
    await _get_project_or_404(project_id, repo)
    timeline = await timeline_service.get_active(project_id)
    if timeline is None:
        raise HTTPException(status_code=400, detail="no timeline yet")
    scene = next((s for s in timeline.scenes if s.id == scene_id), None)
    if scene is None:
        raise HTTPException(
            status_code=404, detail=f"scene {scene_id} not found in the active timeline"
        )

    bindings_by_shot = {
        b.shot_id: b
        for b in await ShotBindingRepository(session).list_for_version(
            uuid.UUID(project_id), timeline.version
        )
    }
    locked_by_shot = {s.id: s.asset_locked for s in timeline.all_shots()}
    start_times = compute_shot_start_times(timeline.all_shots())
    shots_detail = []
    for shot in scene.shots:
        b = bindings_by_shot.get(shot.id)
        if b is None:
            continue
        shots_detail.append(
            await _shot_progress_entry(
                session,
                scene=scene,
                shot=shot,
                binding=b,
                locked=locked_by_shot.get(b.shot_id, False),
                start_times=start_times,
            )
        )
    return {"scene_id": scene_id, "shots": shots_detail}


@router.get("/{project_id}/video")
async def get_video(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> FileResponse:
    project = await _get_project_or_404(project_id, repo)
    if not project.video_path:
        raise HTTPException(status_code=404, detail="no rendered video for this project yet")
    path = Path(project.video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="rendered video file is missing on disk")
    # Same fix as `GET /shots/{shot_id}/asset` (Task 7) and the identical
    # reason: this URL is stable per project, but a re-render (new voice,
    # new music, a corrected shot) overwrites the same `final.mp4` path
    # with different bytes. Without `Cache-Control`, a browser can serve
    # the OLD video from its own cache without ever asking again.
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{project_id}.mp4",
        headers={"Cache-Control": "no-cache"},
    )


async def _resolve_bound_media_path(
    session: AsyncSession, binding, *, panel: str = "primary"
) -> Path | None:
    """The shot's resolved media path, `asset_id` winning over `clip_id` -
    the SAME resolution rule `app/workflow/steps/render.py
    ::_resolved_path_and_hash` already applies for the renderer, kept as
    its own two-line copy here rather than an import: that function also
    returns a content hash for the render fingerprint, which this
    endpoint has no use for, and the actual shared RULE is short enough
    that importing it would trade one line of duplication for a real
    cross-layer dependency (an API route reaching into a workflow step
    module) neither side otherwise needs. `panel=secondary` is the
    split-screen bottom still."""
    if binding is None:
        return None
    if panel == "secondary":
        if binding.secondary_asset_id is not None:
            asset = await session.get(AssetModel, binding.secondary_asset_id)
            return Path(asset.local_path) if asset is not None and asset.local_path else None
        if binding.secondary_clip_id is not None:
            clip = await session.get(GeneratedClipModel, binding.secondary_clip_id)
            return Path(clip.local_path) if clip is not None and clip.local_path else None
        return None
    if binding.asset_id is not None:
        asset = await session.get(AssetModel, binding.asset_id)
        return Path(asset.local_path) if asset is not None and asset.local_path else None
    if binding.clip_id is not None:
        clip = await session.get(GeneratedClipModel, binding.clip_id)
        return Path(clip.local_path) if clip is not None and clip.local_path else None
    return None


@router.get("/{project_id}/shots/{shot_id}/asset")
async def get_shot_asset(
    project_id: str,
    shot_id: str,
    panel: str = Query("primary"),
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    """F0b: the image bound to this shot, for the approval screen -
    `asset.local_path`/`generated_clip.local_path` are server filesystem
    paths a browser cannot load directly. A plain image is streamed
    straight from disk with no derived cache at all (nothing needs
    generating); a bound GENERATED clip that is a video (rung 5,
    image-to-video - `generated_clip.local_path` ending in `.mp4`) gets a
    representative frame lazily extracted and cached instead, via the
    exact same mechanism (and mtime invalidation) `GET /thumbnail` below
    uses for a finished render.

    **Task 7 (2026-08-16): `Cache-Control: no-cache` on every response.**
    This URL is stable per shot (`/shots/{shot_id}/asset`), but the bytes
    behind it are not - a regenerate (`POST /shots/{shot_id}/generate`,
    now producing a genuinely different image per Task 3) or an override
    rebinds this shot to a DIFFERENT underlying file on the SAME URL.
    Starlette's `FileResponse` already computes `ETag`/`Last-Modified`
    fresh on every call from the file it is actually given (`os.stat` at
    send time, keyed on that file's real mtime/size - never a stale,
    reused value), so the validators themselves are already correct.
    What was missing is `Cache-Control`: with none set, a browser applies
    HEURISTIC freshness (RFC 7234 4.2.2) and may serve a PRIOR response
    for this same URL from its own cache without even asking the server
    again - the exact "stale picture after regenerating" bug. `no-cache`
    (which, despite the name, still permits caching - it forbids using
    the cached copy WITHOUT revalidating first) forces a conditional
    request on every load, so the always-current `ETag`/`Last-Modified`
    computed above is actually consulted rather than skipped. Fixed here,
    not by asking the frontend to cache-bust the URL with a query
    param - that would fix only clients that remember to do it."""
    await _get_project_or_404(project_id, repo)
    timeline = await timeline_service.get_active(project_id)
    if timeline is None or shot_id not in {s.id for s in timeline.all_shots()}:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )
    if panel not in _OVERRIDE_PANELS:
        raise HTTPException(
            status_code=400,
            detail=f"panel must be one of {sorted(_OVERRIDE_PANELS)}, got {panel!r}",
        )

    binding = await ShotBindingRepository(session).get(
        uuid.UUID(project_id), timeline.version, shot_id
    )
    path = await _resolve_bound_media_path(session, binding, panel=panel)
    if path is None or not path.exists():
        which = "bottom panel" if panel == "secondary" else "resolved media"
        raise HTTPException(status_code=404, detail=f"shot {shot_id} has no {which} yet")

    no_cache_headers = {"Cache-Control": "no-cache"}
    if is_video_file(path):
        cache_path = shot_frame_cache_path(project_id, shot_id)
        served_path = await cached_video_frame(
            path,
            cache_path,
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
        )
        return FileResponse(served_path, media_type="image/jpeg", headers=no_cache_headers)

    return FileResponse(
        path,
        media_type=mime_type_for_extension(path.suffix.lstrip(".")),
        headers=no_cache_headers,
    )


@router.get("/{project_id}/shots/{shot_id}/clip")
async def get_shot_clip(
    project_id: str,
    shot_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    """R10 fix (motion_new_styles_and_long_form_videos.md §13.10, 2026-08-18):
    A1's own stated requirement - "the review screen must play a clip" -
    was never actually met. `GET /shots/{shot_id}/asset` above
    deliberately serves a cached representative STILL FRAME for a bound
    video (the right thing for a grid of thumbnails), which means the
    human at the one gate - the gate that, since the 2026-08-16 one-gate
    redesign, IS the quality check that replaced the automated
    constraint pass - was approving ~50c of generated motion by looking
    at a single extracted frame of it. That specifically undermines any
    judgement about whether synthetic motion reads as real (A8's own
    bake-off question), which cannot be made from a still by
    construction.

    This endpoint is the other half: it streams the actual video bytes
    for a shot bound to a generated clip, so a frontend can put it in a
    `<video>` element instead. 404 for a shot with no binding, no
    resolved media, or media that is not a video - `GET /asset` above
    remains the right endpoint for a still image or a video's thumbnail;
    this one is deliberately narrow rather than degrading to a frame,
    since a caller that reaches for `/clip` specifically wants to judge
    motion, and a silent frame fallback would defeat that.

    Same `Cache-Control: no-cache` reasoning as `/asset` (Task 7): this
    URL is stable per shot, but a regenerate or override rebinds it to
    different bytes on the same URL.
    """
    await _get_project_or_404(project_id, repo)
    timeline = await timeline_service.get_active(project_id)
    if timeline is None or shot_id not in {s.id for s in timeline.all_shots()}:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )

    binding = await ShotBindingRepository(session).get(
        uuid.UUID(project_id), timeline.version, shot_id
    )
    path = await _resolve_bound_media_path(session, binding)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail=f"shot {shot_id} has no resolved media yet")
    if not is_video_file(path):
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id}'s bound media is a still image, not a clip"
        )

    # `mime_type_for_extension` (used by `/asset` above) only knows IMAGE
    # extensions and would silently mislabel this as `image/png` - never
    # actually reached there because `/asset` intercepts video paths
    # earlier, but reached here by construction. `video/mp4` matches
    # `GET /video`'s own hardcoded type, for the same reason: every video
    # this codebase produces or downloads is mp4 (validation.py's own
    # module docstring).
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/{project_id}/thumbnail")
async def get_project_thumbnail(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    """F0b/F1: one representative image per project, for the project-list
    screen. Source order (F1, agreed with the user 2026-08-16):

    1. `final.mp4` exists -> a frame roughly 10% in, clamped to
       [0.5s, 3s] (never frame 0 - routinely a fade-in or a dark frame).
    2. No video yet -> the FIRST shot's bound asset, in TIMELINE order
       (scene order, then shot order - `timeline.all_shots()`, never
       `shot_id` order, for the same reason `GET /progress` already
       reorders: nothing enforces the two coinciding), resized.
    3. Neither -> `404`, and the project-list card falls back to its
       status chip (F1's own explicit fallback, not an error state).

    Both real cases share one on-disk cache file, keyed on the real
    source's own mtime (`app/assets/thumbnails.py`) - including across a
    project moving from case 2 to case 1 the first time it renders: the
    freshly-written `final.mp4` is newer than whatever was cached from
    the shot asset, so the very next request regenerates from the video
    without any special-cased "which source made the current cache"
    bookkeeping.
    """
    project = await _get_project_or_404(project_id, repo)
    cache_path = settings.storage_root / project_id / "cache" / "thumbnail.jpg"

    if project.video_path:
        video_path = Path(project.video_path)
        if video_path.exists():
            served_path = await cached_video_frame(
                video_path,
                cache_path,
                ffmpeg_binary=settings.ffmpeg_binary,
                ffprobe_binary=settings.ffprobe_binary,
            )
            return FileResponse(served_path, media_type="image/jpeg")

    timeline = await timeline_service.get_active(project_id)
    if timeline is not None and timeline.all_shots():
        first_shot = timeline.all_shots()[0]
        binding = await ShotBindingRepository(session).get(
            uuid.UUID(project_id), timeline.version, first_shot.id
        )
        path = await _resolve_bound_media_path(session, binding)
        if path is not None and path.exists():
            if is_video_file(path):
                served_path = await cached_video_frame(
                    path,
                    cache_path,
                    ffmpeg_binary=settings.ffmpeg_binary,
                    ffprobe_binary=settings.ffprobe_binary,
                )
            else:
                served_path = cached_resized_image(path, cache_path)
            return FileResponse(served_path, media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="no thumbnail available yet")
