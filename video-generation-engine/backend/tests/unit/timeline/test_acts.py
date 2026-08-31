"""C7: act grouping and the music fingerprint hash."""

from datetime import UTC, datetime

from app.schemas.timeline import (
    ActMusicBed,
    MusicPlan,
    MusicTrackSelection,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
)
from app.timeline.acts import (
    act_time_ranges,
    group_scenes_by_act,
    music_content_hash_for,
    uses_per_act_beds,
)


def _shot(shot_id: str, order: int, duration_s: float = 2.0) -> Shot:
    return Shot(id=shot_id, order=order, intent=ShotIntent.EXPLAIN, duration_s=duration_s)


def _timeline(scenes: list[Scene], *, act_beds=None, selected=None) -> Timeline:
    return Timeline(
        timeline_id="tl",
        project_id="p",
        version=1,
        produced_by=ProducedBy.DIRECTOR,
        created_at=datetime.now(UTC),
        scenes=scenes,
        music_plan=MusicPlan(
            mood="sombre",
            tempo="slow",
            search_terms=["x"],
            selected_track=selected,
            act_beds=act_beds or [],
        ),
    )


def test_path_a_has_no_act_beds():
    scenes = [Scene(id="sc", order=0, title="S", duration_s=2.0, shots=[_shot("sh", 0)])]
    assert uses_per_act_beds(_timeline(scenes)) is False
    assert group_scenes_by_act(scenes) == [("_none", scenes)]


def test_consecutive_same_act_id_groups_together():
    scenes = [
        Scene(id="s1", order=0, title="a", duration_s=2.0, act_id="act_1", shots=[_shot("a", 0)]),
        Scene(id="s2", order=1, title="b", duration_s=2.0, act_id="act_1", shots=[_shot("b", 0)]),
        Scene(id="s3", order=2, title="c", duration_s=2.0, act_id="act_2", shots=[_shot("c", 0)]),
    ]
    groups = group_scenes_by_act(scenes)
    assert [g[0] for g in groups] == ["act_1", "act_2"]
    assert [s.id for s in groups[0][1]] == ["s1", "s2"]
    assert uses_per_act_beds(_timeline(scenes)) is True


def test_act_time_ranges_tile_the_timeline():
    scenes = [
        Scene(
            id="s1", order=0, title="a", duration_s=4.0, act_id="act_1", shots=[_shot("a", 0, 4.0)]
        ),
        Scene(
            id="s2", order=1, title="b", duration_s=3.0, act_id="act_2", shots=[_shot("b", 0, 3.0)]
        ),
    ]
    ranges = act_time_ranges(_timeline(scenes))
    assert ranges[0] == ("act_1", 0.0, 4.0)
    assert ranges[1] == ("act_2", 4.0, 7.0)


def test_music_hash_joins_act_beds_in_order_not_sorted():
    def _sel(track_id: str, content_hash: str) -> MusicTrackSelection:
        return MusicTrackSelection(
            provider="local",
            track_id=track_id,
            source_url="u",
            licence="cc0",
            content_hash=content_hash,
        )

    scenes = [Scene(id="sc", order=0, title="S", duration_s=2.0, shots=[_shot("sh", 0)])]
    timeline = _timeline(
        scenes,
        selected=_sel("first", "aaa"),
        act_beds=[
            ActMusicBed(act_id="act_2", selected_track=_sel("z", "bbb")),
            ActMusicBed(act_id="act_1", selected_track=_sel("a", "aaa")),
        ],
    )
    # Act-bed order is the mix, even if hashes would sort the other way.
    assert music_content_hash_for(timeline) == "bbb|aaa"


def test_old_timeline_document_without_acts_field_still_validates():
    """A3 (long_form_direction.md): `Timeline.acts` must default cleanly
    when loading a JSON document written before this field existed - the
    same "predates this field" convention `Scene.act_id` and every other
    additive field on this schema already follows. No Alembic migration
    is needed either: `TimelineVersionModel.document` is a JSONB blob
    (`app/models/timeline_version.py`), so an old row simply has no
    `acts` key and Pydantic supplies the `default_factory=list`."""
    document = {
        "timeline_id": "tl",
        "project_id": "p",
        "version": 1,
        "produced_by": "director",
        "created_at": datetime.now(UTC).isoformat(),
        "scenes": [],
    }
    assert "acts" not in document
    timeline = Timeline.model_validate(document)
    assert timeline.acts == []


def test_music_hash_falls_back_to_selected_track():
    sel = MusicTrackSelection(
        provider="local", track_id="t", source_url="u", licence="cc0", content_hash="only"
    )
    scenes = [Scene(id="sc", order=0, title="S", duration_s=2.0, shots=[_shot("sh", 0)])]
    assert music_content_hash_for(_timeline(scenes, selected=sel)) == "only"
