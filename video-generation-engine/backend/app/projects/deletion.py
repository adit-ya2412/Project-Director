"""Project deletion — DB rows + storage bytes for one project, and the
cross-project cost this specific delete would impose via the two GLOBAL
caches (`narration.content_hash`, `generated_clip.prompt_hash` - see
those models' own docstrings for why the dedup key is global, not
per-project: ladder rung 0, the single biggest cost saving in the
system).

This codebase's own test workflow makes the hazard concrete, not
hypothetical: every ad-hoc test render costs real money (fal.ai,
ElevenLabs), so testing repeatedly means testing from the SAME script
over and over - which means every test project's narration and image
rows are densely hash-shared with every other one. Deleting project A's
OWN `narration`/`generated_clip` rows can delete the only copy project
B's `render/only` pass has ever actually depended on, even though B has
never inserted a row of its own for that hash (`NarrationRepository
.get_by_content_hash`/`GeneratedClipRepository.get_by_prompt_hash`
resolve to WHICHEVER project happened to synthesise/generate it first).
`build_deletion_preview` computes that impact BEFORE anything is
touched; `delete_project` performs the deletion an operator has already
seen the preview for.

## FK deletion order (verified against every `app/models/*.py` FK
declaration, 2026-09-05 - not assumed from the table list alone)

Every project-scoped table declares a plain `ForeignKey("project.id")`
EXCEPT:
- `workflow_step_attempt`, which FKs to `workflow_run.id` instead (one
  level removed from `project` - `WorkflowRunModel`/
  `WorkflowStepAttemptModel` in `app/models/workflow.py`).
- `shot_binding`, which ALSO FKs to `asset.id` and `generated_clip.id` -
  twice each (`asset_id`/`secondary_asset_id`,
  `clip_id`/`secondary_clip_id`, the split-screen panel pair,
  `app/models/shot_binding.py`).

No other table is referenced by any project-scoped FK - `asset`,
`generated_clip`, `narration`, `render`, `script`, `timeline_version`,
`domain_event`, and `llm_call` are all leaves once `shot_binding` is
gone. That makes the safe order:

    workflow_step_attempt -> shot_binding -> {the 8 leaves + workflow_run} -> project

(`workflow_run` deletes safely inside that middle group because its own
child, `workflow_step_attempt`, is already gone by then. Order WITHIN
the 8 leaves + `workflow_run` does not matter - none of them reference
each other.)

## The one wrinkle the FK order above doesn't cover on its own

`asset.content_hash` dedup is deliberately PER-PROJECT, not global
(`AssetModel`'s own docstring: "two different projects that both happen
to download the same photo should each get their own Asset row"), so an
`asset` row is never expected to be pointed at by another project's
`shot_binding` - this module does not defend against that case, and an
unexpected cross-project `asset` reference would surface as a genuine
Postgres FK-violation `IntegrityError` (a loud failure pointing at
exactly the row involved, not a silent skip).

`generated_clip.prompt_hash`, unlike `asset`, IS the global cache -
which means another project's `shot_binding` CAN legitimately point at a
clip this project owns, right now, in the shared dev database (see the
module intro). Deleting that clip row out from under a live FK would
either be rejected outright by Postgres, or - if it somehow weren't -
leave that binding's `state` (`"resolved"`/`"generated"`) claiming a shot
is filled when its media no longer exists anywhere. `delete_project`
handles this the same way `ShotBindingModel`'s own docstring already
describes for partial regeneration ("reset one row and re-run"): every
such binding is updated (never deleted) back to `state="pending"` with
its dangling id cleared, BEFORE the clip rows themselves are removed -
so the affected project's next resolve/render pass re-decides that shot
from scratch instead of crashing or lying about its state. This reset
is exactly the same set of bindings `_generated_clip_dependencies`
already found and reported in the preview - nothing is touched here that
the preview didn't already name.

## Cross-project detection: what each half catches and what it can't

**Narration** (`content_hash` global-unique, `_narration_dependencies`):
for every OTHER project's LATEST timeline_version, recompute
`compute_narration_content_hash` per scene using THAT project's own
resolved voice_id/model/output_format/speed/language_code - the exact
algorithm `RenderStep._resolve_narration_rows` uses to look a row up
(`app/workflow/steps/render.py`). This is a real recomputation, not a
proxy: it does not depend on the other project having a `narration` row
of its own - that absence is precisely the case that matters (project B
depends on project A's row because B's own hash lookup has always
resolved to A's row, never inserting one of its own). It CANNOT catch:
(a) a project whose latest timeline predates `narration_locked` /
never actually reached narration - nothing to recompute against, same
gate `_resolve_narration_rows` itself uses; (b) a dependency living only
in an EARLIER, non-latest timeline version of another project (a
superseded version's scenes are never re-checked - moot unless a human
somehow rolls a project back to it); (c) a project that does not exist
yet.

**GeneratedClip** (`prompt_hash` global-unique,
`_generated_clip_dependencies`): deliberately NOT a hash recomputation -
shot-image prompt construction lives in the shot planner (out of scope
for this change, and duplicating that logic here would violate "one
source of truth per computation"). Instead this is a direct, exact query
over `shot_binding`: any row belonging to ANOTHER project whose
`clip_id`/`secondary_clip_id` points at one of this project's
`generated_clip` rows. This is exhaustive, not a proxy - a clip is by
construction only ever "depended on" by whichever LIVE bindings actually
point at it. It CANNOT catch a project that would independently compute
the identical prompt_hash on some FUTURE plan/regenerate pass but has no
binding pointing at this clip yet (not yet planned, or a shot never
bound) - there is no way to know a not-yet-computed hash in advance.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.asset import AssetModel
from app.models.domain_event import DomainEventModel
from app.models.generated_clip import GeneratedClipModel
from app.models.llm_call import LlmCallModel
from app.models.narration import NarrationModel
from app.models.project import ProjectModel
from app.models.render import RenderModel
from app.models.script import ScriptModel
from app.models.shot_binding import ShotBindingModel
from app.models.timeline_version import TimelineVersionModel
from app.models.workflow import WorkflowRunModel, WorkflowStepAttemptModel
from app.timeline.narration_key import narration_content_hash_for_scene
from app.schemas.project_deletion import (
    GeneratedClipDependency,
    NarrationDependency,
    ProjectDeletionSummary,
)
from app.schemas.timeline import Timeline
from app.script.styles import resolve_narration_speed


def resolve_project_storage_dir(project_id: str) -> Path:
    """`settings.storage_root / project_id`, resolved and checked to be
    strictly inside the resolved storage root before any caller is
    handed the path to remove anything from it.

    `settings.storage_root` is `Path("./storage")` - CWD-relative (open
    issue §8.3, docs/plans/illustrated_faceless.md; not this change's to
    fix, just to resolve the exact same way every other call site
    already does). Resolving BOTH sides before comparing is what makes
    this check mean anything: an unresolved `storage_root / project_id`
    could contain `..` segments (if `project_id` ever weren't already a
    validated UUID by the time it reaches here - see `delete_project`'s
    own UUID check, which runs first) that a naive string/prefix check
    would miss entirely.

    Raises `RuntimeError`, not a caught/handled error type - reaching
    the `else` branch below means the UUID gate upstream was bypassed,
    which should be impossible, not a normal, expected failure a caller
    is meant to recover from.
    """
    root = settings.storage_root.resolve()
    candidate = (settings.storage_root / project_id).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise RuntimeError(
            f"refusing to touch {candidate!r} - it is not strictly inside storage root {root!r}"
        )
    return candidate


def _dir_size_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


async def _row_counts(session: AsyncSession, project_uuid: uuid.UUID) -> dict[str, int]:
    async def count(model) -> int:
        result = await session.execute(
            select(func.count()).select_from(model).where(model.project_id == project_uuid)
        )
        return int(result.scalar_one())

    # workflow_step_attempt has no project_id of its own (see module
    # docstring) - counted via its parent workflow_run instead.
    step_attempt_result = await session.execute(
        select(func.count())
        .select_from(WorkflowStepAttemptModel)
        .join(WorkflowRunModel, WorkflowStepAttemptModel.workflow_run_id == WorkflowRunModel.id)
        .where(WorkflowRunModel.project_id == project_uuid)
    )
    return {
        "workflow_step_attempt": int(step_attempt_result.scalar_one()),
        "workflow_run": await count(WorkflowRunModel),
        "shot_binding": await count(ShotBindingModel),
        "asset": await count(AssetModel),
        "generated_clip": await count(GeneratedClipModel),
        "narration": await count(NarrationModel),
        "render": await count(RenderModel),
        "script": await count(ScriptModel),
        "timeline_version": await count(TimelineVersionModel),
        "domain_event": await count(DomainEventModel),
        "llm_call": await count(LlmCallModel),
    }


async def _narration_dependencies(
    session: AsyncSession, project_uuid: uuid.UUID
) -> list[NarrationDependency]:
    """See module docstring's "Narration" section."""
    own_rows = (
        (
            await session.execute(
                select(NarrationModel).where(NarrationModel.project_id == project_uuid)
            )
        )
        .scalars()
        .all()
    )
    if not own_rows:
        return []
    own_by_hash = {row.content_hash: row for row in own_rows}

    other_projects = (
        (await session.execute(select(ProjectModel).where(ProjectModel.id != project_uuid)))
        .scalars()
        .all()
    )
    if not other_projects:
        return []
    projects_by_id = {p.id: p for p in other_projects}

    # Every OTHER project's timeline_version rows, newest first WITHIN
    # each project - the first row seen per project_id below is that
    # project's latest, without a second round-trip per project.
    version_rows = (
        (
            await session.execute(
                select(TimelineVersionModel)
                .where(TimelineVersionModel.project_id.in_(projects_by_id))
                .order_by(TimelineVersionModel.project_id, TimelineVersionModel.version.desc())
            )
        )
        .scalars()
        .all()
    )
    latest_by_project: dict[uuid.UUID, TimelineVersionModel] = {}
    for row in version_rows:
        latest_by_project.setdefault(row.project_id, row)

    dependencies: list[NarrationDependency] = []
    for other_project_id, version_row in latest_by_project.items():
        try:
            timeline = Timeline.model_validate(version_row.document)
        except Exception:
            # A project this codebase has accumulated over many schema
            # revisions (measured: 1800+ rows in the shared dev database,
            # most of them stale test artifacts predating some field this
            # module never touched) can carry a `document` an OLDER
            # `Timeline.schema_version` produced, which
            # `_check_schema_version` rejects outright. This function
            # does not own that migration story and a project whose
            # timeline cannot even be parsed is not one any running code
            # path reads narration hashes from either - skipping it is
            # the same "cannot recompute against it" outcome as the
            # `narration_locked` gate just below, not a swallowed bug.
            continue
        if not timeline.metadata.narration_locked:
            # Mirrors `_resolve_narration_rows`'s own gate (render.py) -
            # a timeline that never reached (or predates) narration has
            # no hash to look anything up against, so it cannot depend
            # on this project's rows.
            continue
        voice_id = timeline.metadata.voice_id or settings.elevenlabs_voice_id
        if not voice_id:
            continue
        language_code = timeline.metadata.language_code or settings.elevenlabs_language_code
        speed = resolve_narration_speed(timeline.metadata.render_style)
        other_project = projects_by_id[other_project_id]
        for scene in timeline.scenes:
            content_hash = narration_content_hash_for_scene(
                scene,
                voice_id=voice_id,
                speed=speed,
                language_code=language_code,
            )
            owned = own_by_hash.get(content_hash)
            if owned is None:
                continue
            # A zero-cost row (dry-run/fake synthesis) never really paid
            # anything the first time - fall back to a fresh
            # character-rate estimate so the re-spend is never reported
            # as free when a REAL re-synthesis would not be.
            respend = owned.cost_cents or round(
                len(owned.text) * settings.elevenlabs_cost_cents_per_character
            )
            dependencies.append(
                NarrationDependency(
                    narration_id=str(owned.id),
                    scene_id=owned.scene_id,
                    content_hash=content_hash,
                    depended_on_by_project_id=str(other_project_id),
                    depended_on_by_project_name=other_project.name,
                    depended_on_by_scene_id=scene.id,
                    respend_estimate_cents=respend,
                )
            )
    return dependencies


async def _generated_clip_dependencies(
    session: AsyncSession, project_uuid: uuid.UUID
) -> list[GeneratedClipDependency]:
    """See module docstring's "GeneratedClip" section."""
    own_clip_rows = (
        (
            await session.execute(
                select(GeneratedClipModel).where(GeneratedClipModel.project_id == project_uuid)
            )
        )
        .scalars()
        .all()
    )
    if not own_clip_rows:
        return []
    own_clips_by_id = {clip.id: clip for clip in own_clip_rows}

    other_bindings = (
        (
            await session.execute(
                select(ShotBindingModel).where(
                    ShotBindingModel.project_id != project_uuid,
                    or_(
                        ShotBindingModel.clip_id.in_(own_clips_by_id),
                        ShotBindingModel.secondary_clip_id.in_(own_clips_by_id),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    if not other_bindings:
        return []

    other_project_ids = {b.project_id for b in other_bindings}
    other_projects = (
        (await session.execute(select(ProjectModel).where(ProjectModel.id.in_(other_project_ids))))
        .scalars()
        .all()
    )
    projects_by_id = {p.id: p for p in other_projects}

    def respend_estimate(clip: GeneratedClipModel) -> int:
        if clip.cost_cents:
            return clip.cost_cents
        # Same "never report a real re-spend as free" reasoning as the
        # narration side above. `duration_s is not None` is this
        # module's own cheap video/image discriminator (mirrors the
        # classification `render_timeline` makes elsewhere) - good
        # enough for an estimate, not claimed as anything more precise.
        return (
            settings.fal_video_cost_cents_estimate
            if clip.duration_s is not None
            else settings.fal_image_cost_cents_estimate
        )

    dependencies: list[GeneratedClipDependency] = []
    for binding in other_bindings:
        other_project = projects_by_id.get(binding.project_id)
        project_name = other_project.name if other_project is not None else "?"
        for clip_id, panel in (
            (binding.clip_id, "primary"),
            (binding.secondary_clip_id, "secondary"),
        ):
            clip = own_clips_by_id.get(clip_id) if clip_id is not None else None
            if clip is None:
                continue
            dependencies.append(
                GeneratedClipDependency(
                    clip_id=str(clip.id),
                    shot_id=clip.shot_id,
                    prompt_hash=clip.prompt_hash,
                    depended_on_by_project_id=str(binding.project_id),
                    depended_on_by_project_name=project_name,
                    depended_on_by_shot_id=binding.shot_id,
                    panel=panel,
                    respend_estimate_cents=respend_estimate(clip),
                )
            )
    return dependencies


async def build_deletion_preview(
    session: AsyncSession, project_id: str
) -> ProjectDeletionSummary | None:
    """Read-only. Returns `None` for a project that does not exist -
    including a `project_id` that isn't even a well-formed UUID, the
    same "can't possibly match a row, same as not found" precedent
    `PostgresProjectRepository.get` already sets."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return None
    project = await session.get(ProjectModel, project_uuid)
    if project is None:
        return None

    row_counts = await _row_counts(session, project_uuid)
    storage_dir = resolve_project_storage_dir(str(project_uuid))
    narration_deps = await _narration_dependencies(session, project_uuid)
    clip_deps = await _generated_clip_dependencies(session, project_uuid)
    affected_ids = sorted(
        {d.depended_on_by_project_id for d in narration_deps}
        | {d.depended_on_by_project_id for d in clip_deps}
    )
    total_respend = sum(d.respend_estimate_cents for d in narration_deps) + sum(
        d.respend_estimate_cents for d in clip_deps
    )

    return ProjectDeletionSummary(
        project_id=str(project_uuid),
        project_name=project.name,
        row_counts=row_counts,
        storage_path=str(storage_dir),
        storage_exists=storage_dir.is_dir(),
        storage_bytes=_dir_size_bytes(storage_dir),
        narration_dependencies=narration_deps,
        generated_clip_dependencies=clip_deps,
        affected_project_ids=affected_ids,
        total_respend_estimate_cents=total_respend,
    )


async def delete_project(session: AsyncSession, project_id: str) -> ProjectDeletionSummary | None:
    """Performs the deletion `build_deletion_preview` describes, returning
    the SAME summary (what was actually removed, captured before any of
    it was) - `None` for a project that does not exist, same as the
    preview.

    One transaction for every DB write (dangling bindings released, then
    every row deleted in the verified FK-safe order - see module
    docstring); the storage directory is only removed AFTER that
    transaction commits, so a crash mid-delete leaves an orphaned
    directory (cheap to find and clean up by hand) rather than deleted
    rows whose files still linger with no row to ever reference them
    again."""
    summary = await build_deletion_preview(session, project_id)
    if summary is None:
        return None
    project_uuid = uuid.UUID(project_id)

    # Release every OTHER project's binding still pointing at a
    # generated_clip row this delete is about to remove - see module
    # docstring's "one wrinkle" section. Exactly the set
    # `_generated_clip_dependencies` already found and reported.
    clip_ids = {uuid.UUID(dep.clip_id) for dep in summary.generated_clip_dependencies}
    if clip_ids:
        other_bindings = (
            (
                await session.execute(
                    select(ShotBindingModel).where(
                        ShotBindingModel.project_id != project_uuid,
                        or_(
                            ShotBindingModel.clip_id.in_(clip_ids),
                            ShotBindingModel.secondary_clip_id.in_(clip_ids),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for binding in other_bindings:
            if binding.clip_id in clip_ids:
                binding.clip_id = None
                binding.state = "pending"
                binding.rung = None
                binding.last_error = None
            if binding.secondary_clip_id in clip_ids:
                binding.secondary_clip_id = None
                binding.secondary_state = "pending"
                binding.secondary_last_error = None
        await session.flush()

    run_ids_subq = select(WorkflowRunModel.id).where(WorkflowRunModel.project_id == project_uuid)
    await session.execute(
        delete(WorkflowStepAttemptModel).where(
            WorkflowStepAttemptModel.workflow_run_id.in_(run_ids_subq)
        )
    )
    await session.execute(
        delete(ShotBindingModel).where(ShotBindingModel.project_id == project_uuid)
    )
    for model in (
        AssetModel,
        GeneratedClipModel,
        NarrationModel,
        RenderModel,
        ScriptModel,
        TimelineVersionModel,
        DomainEventModel,
        LlmCallModel,
        WorkflowRunModel,
    ):
        await session.execute(delete(model).where(model.project_id == project_uuid))
    await session.execute(delete(ProjectModel).where(ProjectModel.id == project_uuid))
    await session.commit()

    storage_dir = resolve_project_storage_dir(project_id)
    if storage_dir.is_dir():
        shutil.rmtree(storage_dir)

    return summary
