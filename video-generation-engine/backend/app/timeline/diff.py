"""Timeline diffing — pure functions, no DB access, no versioning policy.

`TimelineService.diff` calls `compute_diff` directly; it is also usable
standalone (the M9 approval UI needs "what did the Shot Planner just
change?" and this is where that answer comes from).
"""

from typing import Any

from pydantic import BaseModel

from app.schemas.timeline import Scene, Shot, Timeline

# Fields compared at each granularity. Nested structures (camera,
# transition_out, asset_plan) are reported whole rather than drilled into
# field-by-field - "readable scene/shot-level changes" means enough detail
# to explain a change, not a full recursive diff.
_METADATA_FIELDS = ("language", "aspect_ratio", "resolution", "fps", "total_duration_s", "voice_id")
_SCENE_FIELDS = ("title", "summary", "emotion", "narrative_purpose", "narration_text", "duration_s")
_SHOT_FIELDS = (
    "intent",
    "intent_text",
    "duration_s",
    "framing",
    "camera",
    "transition_out",
    "prompt",
    "asset_plan",
)


class FieldChange(BaseModel):
    field: str
    old: Any
    new: Any


class ShotDiff(BaseModel):
    shot_id: str
    changes: list[FieldChange]


class SceneDiff(BaseModel):
    scene_id: str
    changes: list[FieldChange]
    shots_added: list[str]
    shots_removed: list[str]
    shots_changed: list[ShotDiff]


class TimelineDiff(BaseModel):
    from_version: int
    to_version: int
    metadata_changes: list[FieldChange]
    scenes_added: list[str]
    scenes_removed: list[str]
    scenes_changed: list[SceneDiff]

    def is_empty(self) -> bool:
        return not (
            self.metadata_changes or self.scenes_added or self.scenes_removed or self.scenes_changed
        )


def _field_changes(old: BaseModel, new: BaseModel, fields: tuple[str, ...]) -> list[FieldChange]:
    changes = []
    for field in fields:
        old_value = getattr(old, field)
        new_value = getattr(new, field)
        if isinstance(old_value, BaseModel):
            old_value = old_value.model_dump(mode="json")
        if isinstance(new_value, BaseModel):
            new_value = new_value.model_dump(mode="json")
        if old_value != new_value:
            changes.append(FieldChange(field=field, old=old_value, new=new_value))
    return changes


def _diff_shots(
    old_shots: list[Shot], new_shots: list[Shot]
) -> tuple[list[str], list[str], list[ShotDiff]]:
    old_by_id = {s.id: s for s in old_shots}
    new_by_id = {s.id: s for s in new_shots}

    added = [sid for sid in new_by_id if sid not in old_by_id]
    removed = [sid for sid in old_by_id if sid not in new_by_id]
    changed = []
    for shot_id in old_by_id:
        if shot_id not in new_by_id:
            continue
        changes = _field_changes(old_by_id[shot_id], new_by_id[shot_id], _SHOT_FIELDS)
        if changes:
            changed.append(ShotDiff(shot_id=shot_id, changes=changes))

    return added, removed, changed


def _diff_scenes(
    old_scenes: list[Scene], new_scenes: list[Scene]
) -> tuple[list[str], list[str], list[SceneDiff]]:
    old_by_id = {s.id: s for s in old_scenes}
    new_by_id = {s.id: s for s in new_scenes}

    added = [sid for sid in new_by_id if sid not in old_by_id]
    removed = [sid for sid in old_by_id if sid not in new_by_id]
    changed = []
    for scene_id in old_by_id:
        if scene_id not in new_by_id:
            continue
        old_scene, new_scene = old_by_id[scene_id], new_by_id[scene_id]
        scene_field_changes = _field_changes(old_scene, new_scene, _SCENE_FIELDS)
        shots_added, shots_removed, shots_changed = _diff_shots(old_scene.shots, new_scene.shots)
        if scene_field_changes or shots_added or shots_removed or shots_changed:
            changed.append(
                SceneDiff(
                    scene_id=scene_id,
                    changes=scene_field_changes,
                    shots_added=shots_added,
                    shots_removed=shots_removed,
                    shots_changed=shots_changed,
                )
            )

    return added, removed, changed


def compute_diff(old: Timeline, new: Timeline) -> TimelineDiff:
    metadata_changes = _field_changes(old.metadata, new.metadata, _METADATA_FIELDS)
    scenes_added, scenes_removed, scenes_changed = _diff_scenes(old.scenes, new.scenes)
    return TimelineDiff(
        from_version=old.version,
        to_version=new.version,
        metadata_changes=metadata_changes,
        scenes_added=scenes_added,
        scenes_removed=scenes_removed,
        scenes_changed=scenes_changed,
    )
