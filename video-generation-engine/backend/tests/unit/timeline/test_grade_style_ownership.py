"""R5 fix (motion_new_styles_and_long_form_videos.md §13.5, "R5",
2026-08-18, user-confirmed scenario): `TimelineMetadata.grade_style` is
the new, independently-mutable knob `POST /{project_id}/grade` sets -
this proves the exact mechanism that endpoint relies on
(`find_additive_violations`'s `owns` handling of a dotted path) without
needing a DB, an app instance, or `TimelineService`.
"""

from app.schemas.timeline import TimelineMetadata
from app.timeline.additive import find_additive_violations


def test_grade_style_defaults_to_none():
    assert TimelineMetadata().grade_style is None


def _metadata_dict(*, render_style: str | None, grade_style: str | None) -> dict:
    return TimelineMetadata(render_style=render_style, grade_style=grade_style).model_dump(
        mode="json"
    )


def test_changing_grade_style_alone_is_allowed_when_owned():
    old = {"metadata": _metadata_dict(render_style="documentary_archival", grade_style=None)}
    new = {
        "metadata": _metadata_dict(
            render_style="documentary_archival", grade_style="retention_fast"
        )
    }

    violations = find_additive_violations(old, new, frozenset({"metadata.grade_style"}))
    assert violations == []


def test_re_changing_an_already_set_grade_style_is_rejected_without_ownership():
    """Proves the field is genuinely protected by the SAME additive-only
    mechanism as everything else - only `POST /grade`'s own
    `owns={"metadata.grade_style"}` call is allowed to change it. Filling
    a null field is always allowed regardless of ownership (the additive-
    only rule's own baseline), so this starts from an already-SET value
    to exercise the real ownership check, not the null-fill exemption."""
    old = {"metadata": _metadata_dict(render_style="documentary_archival", grade_style="stillness")}
    new = {
        "metadata": _metadata_dict(
            render_style="documentary_archival", grade_style="retention_fast"
        )
    }

    violations = find_additive_violations(old, new, frozenset())
    assert any("grade_style" in v for v in violations)


def test_clearing_grade_style_back_to_none_is_allowed_when_owned():
    old = {"metadata": _metadata_dict(render_style="documentary_archival", grade_style="stillness")}
    new = {"metadata": _metadata_dict(render_style="documentary_archival", grade_style=None)}

    violations = find_additive_violations(old, new, frozenset({"metadata.grade_style"}))
    assert violations == []


def test_owning_grade_style_does_not_grant_ownership_of_render_style():
    """The whole point of R5's fix: the grade knob and the frozen
    planning knob (`render_style`) are independent - owning one must
    never accidentally permit changing the other."""
    old = {"metadata": _metadata_dict(render_style="documentary_archival", grade_style=None)}
    new = {"metadata": _metadata_dict(render_style="retention_fast", grade_style="retention_fast")}

    violations = find_additive_violations(old, new, frozenset({"metadata.grade_style"}))
    assert any("render_style" in v for v in violations)
