"""`GET /projects/{id}/deletion-preview` and `DELETE /projects/{id}`
share this response shape - see `app/projects/deletion.py` for the
computation, and that module's own docstring for the verified FK
deletion order and the cross-project detection's exact honest limits.
"""

from pydantic import BaseModel


class NarrationDependency(BaseModel):
    """One of THIS project's `narration` rows whose `content_hash` is
    also what another project's OWN narration lookup resolves to right
    now - i.e. deleting this row does not just cost THIS project a
    re-synthesis, it breaks `render/only` for the other project outright
    (`app/workflow/steps/render.py::_resolve_narration_rows` raises
    `PermanentError` on a missing row once a timeline is
    `narration_locked`). See `app/projects/deletion.py::
    _narration_dependencies` for how this is computed - a real
    recomputation of the other project's own hash, not a proxy."""

    narration_id: str
    scene_id: str
    content_hash: str
    depended_on_by_project_id: str
    depended_on_by_project_name: str
    depended_on_by_scene_id: str
    # The row's own recorded spend where known (same request would cost
    # the same again); falls back to a fresh character-rate estimate for
    # a zero-cost row (dry-run/fake rows never paid anything the first
    # time, so `0` would understate what a REAL re-synthesis costs).
    respend_estimate_cents: int


class GeneratedClipDependency(BaseModel):
    """One of THIS project's `generated_clip` rows that a `shot_binding`
    belonging to ANOTHER project currently points at (`clip_id` or the
    split-screen `secondary_clip_id`). Deleting the row would violate
    that binding's own FK, so `delete_project` releases the binding
    (clears the id, resets its state to `pending`) rather than letting
    Postgres reject the whole delete - see `app/projects/deletion.py`'s
    module docstring for why that reset is the correct, not merely
    convenient, thing to do."""

    clip_id: str
    shot_id: str
    prompt_hash: str
    depended_on_by_project_id: str
    depended_on_by_project_name: str
    depended_on_by_shot_id: str
    panel: str  # "primary" | "secondary"
    respend_estimate_cents: int


class ProjectDeletionSummary(BaseModel):
    """What deleting (or previewing the deletion of) one project touches.
    The preview and the post-delete summary are the identical shape -
    the second is what the first promised, captured before anything was
    actually removed (row counts would otherwise trivially read back as
    zero)."""

    project_id: str
    project_name: str
    row_counts: dict[str, int]
    storage_path: str
    storage_exists: bool
    storage_bytes: int
    narration_dependencies: list[NarrationDependency]
    generated_clip_dependencies: list[GeneratedClipDependency]
    # Union of both dependency lists' project ids, sorted for a stable
    # response - what the frontend confirmation dialog names.
    affected_project_ids: list[str]
    total_respend_estimate_cents: int
