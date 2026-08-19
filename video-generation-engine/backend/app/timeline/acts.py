"""Act grouping for Track C C7.

`Scene.act_id` is set by Path B planning (N > 70) and is None on every
shorter project. Music is the one consumer that needs acts at render
time: group consecutive scenes that share an `act_id`, then time-range
each group with D5 shot-start arithmetic so beds tile the video.
"""

from app.schemas.timeline import Scene, Timeline
from app.timeline.duration import compute_shot_start_times, compute_timeline_duration


def uses_per_act_beds(timeline: Timeline) -> bool:
    """Path B left act ids on the scenes. Path A (and every pre-C1
    timeline) has none, so music stays one bed for the whole video."""
    return any(scene.act_id for scene in timeline.scenes)


def group_scenes_by_act(scenes: list[Scene]) -> list[tuple[str, list[Scene]]]:
    """Consecutive scenes sharing `act_id`, in timeline order. A missing
    `act_id` is its own group (`"_none"`) so a mixed document still
    tiles rather than dropping scenes."""
    groups: list[tuple[str, list[Scene]]] = []
    for scene in scenes:
        act_id = scene.act_id or "_none"
        if groups and groups[-1][0] == act_id:
            groups[-1][1].append(scene)
        else:
            groups.append((act_id, [scene]))
    return groups


def act_time_ranges(timeline: Timeline) -> list[tuple[str, float, float]]:
    """`(act_id, start_s, end_s)` covering the rendered timeline without
    gaps. End of act i is the start of act i+1 (or the timeline end)."""
    shots = timeline.all_shots()
    if not shots:
        return []
    starts = compute_shot_start_times(shots)
    total = compute_timeline_duration(shots)
    groups = group_scenes_by_act(timeline.scenes)
    ranges: list[tuple[str, float, float]] = []
    for i, (act_id, scenes) in enumerate(groups):
        group_shots = [shot for scene in scenes for shot in scene.shots]
        if not group_shots:
            continue
        start = starts.get(group_shots[0].id, 0.0)
        if i + 1 < len(groups):
            next_shots = [shot for scene in groups[i + 1][1] for shot in scene.shots]
            end = starts.get(next_shots[0].id, total) if next_shots else total
        else:
            end = total
        if end > start:
            ranges.append((act_id, start, end))
    return ranges


def music_content_hash_for(timeline: Timeline) -> str | None:
    """Fingerprint input: act beds in order when present, else the
    single `selected_track`. Order is the mix, so it is not sorted."""
    plan = timeline.music_plan
    if plan is None:
        return None
    act_hashes = [
        bed.selected_track.content_hash for bed in plan.act_beds if bed.selected_track is not None
    ]
    if act_hashes:
        return "|".join(act_hashes)
    if plan.selected_track is not None:
        return plan.selected_track.content_hash
    return None
