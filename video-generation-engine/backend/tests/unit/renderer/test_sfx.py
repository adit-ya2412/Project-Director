"""`derive_sfx_events` — punch-ins, text cards, non-cut transitions."""

from datetime import UTC, datetime

from app.renderer.ken_burns import punch_in_frame_offsets
from app.renderer.sfx import derive_sfx_events
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    ProducedBy,
    Scene,
    SfxKind,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
    Transition,
    TransitionType,
)


def _timeline(shots: list[Shot]) -> Timeline:
    duration = sum(s.duration_s for s in shots)
    scene = Scene(id="sc_01", order=0, title="S", duration_s=duration, shots=shots)
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


def test_static_shot_with_a_cut_emits_no_events():
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    assert derive_sfx_events(_timeline([shot]), fps=30, whoosh_enabled=True) == []


def test_punch_in_emits_a_whoosh_at_each_snap():
    camera = Camera(movement=CameraMovement.PUNCH_IN, intensity=0.5)
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, camera=camera)
    events = derive_sfx_events(_timeline([shot]), fps=30, whoosh_enabled=True)
    frames = punch_in_frame_offsets(camera, frames=90)
    assert frames is not None
    assert [e.kind for e in events] == [SfxKind.WHOOSH] * len(frames)
    assert [round(e.offset_s, 5) for e in events] == [round(f / 30, 5) for f in frames]


def test_text_card_emits_a_stinger_at_shot_start():
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.INTRODUCE,
        duration_s=2.0,
        text_card="Part One",
    )
    events = derive_sfx_events(_timeline([shot]), fps=30, whoosh_enabled=True)
    assert [(e.kind, e.offset_s) for e in events] == [(SfxKind.STINGER, 0.0)]


def test_dissolve_emits_a_transition_sfx_at_the_overlap():
    first = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        transition_out=Transition(type=TransitionType.DISSOLVE, duration_s=0.5),
    )
    second = Shot(id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    events = derive_sfx_events(_timeline([first, second]), fps=30, whoosh_enabled=True)
    assert any(e.kind == SfxKind.TRANSITION and abs(e.offset_s - 2.5) < 1e-6 for e in events)


def test_whoosh_enabled_false_drops_whoosh_but_keeps_other_kinds():
    """`derive_sfx_events` no longer resolves style itself (review of P2,
    analysis.md RV2) - the caller resolves `whoosh_enabled` once and hands
    it in, so this test exercises the gate parameter directly rather than
    a style name. The style->bool mapping (only `retention_fast` resolves
    to False) is covered separately in
    tests/unit/script/test_styles.py::test_retention_fast_gates_whoosh_off_and_others_stay_on
    (RV5, review of P1+P2, 2026-08-24)."""
    camera = Camera(movement=CameraMovement.PUNCH_IN, intensity=0.5)
    punch = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, camera=camera)
    card = Shot(
        id="sh_02",
        order=1,
        intent=ShotIntent.INTRODUCE,
        duration_s=2.0,
        text_card="Part One",
    )
    timeline = _timeline([punch, card])
    events = derive_sfx_events(timeline, fps=30, whoosh_enabled=False)
    assert events, "stingers/transitions must survive the whoosh gate"
    assert all(e.kind != SfxKind.WHOOSH for e in events)
    assert any(e.kind == SfxKind.STINGER for e in events)


def test_whoosh_enabled_true_keeps_whoosh():
    """The default/gate-open case. Which style resolves to `True` (all of
    them except `retention_fast`) is covered separately in
    tests/unit/script/test_styles.py::test_retention_fast_gates_whoosh_off_and_others_stay_on
    (RV5, review of P1+P2, 2026-08-24) - this test only proves the `True`
    path through `derive_sfx_events` itself."""
    camera = Camera(movement=CameraMovement.PUNCH_IN, intensity=0.5)
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, camera=camera)
    events = derive_sfx_events(_timeline([shot]), fps=30, whoosh_enabled=True)
    assert any(e.kind == SfxKind.WHOOSH for e in events)
