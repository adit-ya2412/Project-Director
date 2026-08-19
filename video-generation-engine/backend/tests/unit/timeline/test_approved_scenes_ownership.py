"""C5: `TimelineMetadata.approved_scenes` is the one source of truth
for per-scene review, written via `owns={"metadata.approved_scenes"}`.
Same dotted-path mechanism as `metadata.grade_style`.
"""

from app.schemas.timeline import TimelineMetadata
from app.timeline.additive import find_additive_violations


def test_approved_scenes_defaults_to_empty():
    assert TimelineMetadata().approved_scenes == []


def _metadata_dict(*, approved_scenes: list[str]) -> dict:
    return TimelineMetadata(approved_scenes=approved_scenes).model_dump(mode="json")


def test_filling_approved_scenes_is_allowed_when_owned():
    old = {"metadata": _metadata_dict(approved_scenes=[])}
    new = {"metadata": _metadata_dict(approved_scenes=["sc_01"])}

    violations = find_additive_violations(old, new, frozenset({"metadata.approved_scenes"}))
    assert violations == []


def test_appending_another_scene_is_allowed_when_owned():
    old = {"metadata": _metadata_dict(approved_scenes=["sc_01"])}
    new = {"metadata": _metadata_dict(approved_scenes=["sc_01", "sc_02"])}

    violations = find_additive_violations(old, new, frozenset({"metadata.approved_scenes"}))
    assert violations == []


def test_changing_approved_scenes_is_rejected_without_ownership():
    old = {"metadata": _metadata_dict(approved_scenes=["sc_01"])}
    new = {"metadata": _metadata_dict(approved_scenes=["sc_01", "sc_02"])}

    violations = find_additive_violations(old, new, frozenset())
    assert any("approved_scenes" in v for v in violations)


def test_owning_approved_scenes_does_not_grant_ownership_of_grade_style():
    old = {
        "metadata": TimelineMetadata(approved_scenes=["sc_01"], grade_style="stillness").model_dump(
            mode="json"
        )
    }
    new = {
        "metadata": TimelineMetadata(
            approved_scenes=["sc_01", "sc_02"], grade_style="retention_fast"
        ).model_dump(mode="json")
    }

    violations = find_additive_violations(old, new, frozenset({"metadata.approved_scenes"}))
    assert any("grade_style" in v for v in violations)
