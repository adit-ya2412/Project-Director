"""P0 (docs/plans/gate_panel_overrides.md): bulk prompt export - pure
functions, no DB, no network. `build_prompt_export_entries` never touches
a shot binding or generated clip; it derives every prompt straight from
the Timeline, exactly as `resolve_assets_generate` itself would, before
anything has actually been generated.

The identity test (`test_...byte_identical_to_the_real_generation_path`)
is the point of this slice per the plan's own "Done when": every exported
prompt must be provably the SAME string `styled_prompt`/`layer_styled_
prompt` would build, asserted against those functions directly - never a
hardcoded expected string, which could drift in lockstep with a bug in
`build_prompt_export_entries` and never notice.
"""

from __future__ import annotations

from app.assets.prompt_export import build_prompt_export_entries, render_prompt_export_text
from app.core.clock import utcnow
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    CreativeContext,
    LayerRole,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
    Timeline,
    TimelineMetadata,
)
from app.script.styles import resolve_generation_request_format, resolve_render_format
from app.workflow.steps.resolve_assets import layer_styled_prompt, styled_prompt


def _plain_shot(shot_id: str, prompt: str = "a coal mine") -> Shot:
    return Shot(id=shot_id, order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt=prompt)


def _parallax_shot(shot_id: str, prompt: str = "a seated figure, wide shot") -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt=prompt,
        camera=Camera(movement=CameraMovement.PARALLAX),
        layers=[
            ShotLayer(role=LayerRole.BACKGROUND, prompt="an empty archival room"),
            ShotLayer(role=LayerRole.SUBJECT, prompt="a seated figure, seen from behind"),
        ],
    )


def _timeline(
    scenes: list[Scene],
    *,
    render_style: str | None = None,
    frame_aspect: str | None = None,
    visual_style: str = "",
) -> Timeline:
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        created_at=utcnow(),
        scenes=scenes,
        metadata=TimelineMetadata(render_style=render_style, frame_aspect=frame_aspect),
        creative_context=CreativeContext(visual_style=visual_style),
    )


def test_ordering_is_scene_then_shot():
    scene_a = Scene(
        id="sc_a", order=0, title="a", duration_s=6.0,
        shots=[_plain_shot("a1"), _plain_shot("a2")],
    )
    scene_b = Scene(
        id="sc_b", order=1, title="b", duration_s=3.0,
        shots=[_plain_shot("b1")],
    )
    entries = build_prompt_export_entries(_timeline([scene_a, scene_b]))
    assert [(e.scene_id, e.shot_id) for e in entries] == [
        ("sc_a", "a1"),
        ("sc_a", "a2"),
        ("sc_b", "b1"),
    ]


def test_a_plain_shot_exports_one_entry_a_parallax_shot_exports_three():
    scene = Scene(
        id="sc_01", order=0, title="t", duration_s=6.0,
        shots=[_plain_shot("plain"), _parallax_shot("para")],
    )
    entries = build_prompt_export_entries(_timeline([scene]))
    by_shot: dict[str, list] = {}
    for e in entries:
        by_shot.setdefault(e.shot_id, []).append(e)

    assert len(by_shot["plain"]) == 1
    assert by_shot["plain"][0].image_label == "primary"

    assert len(by_shot["para"]) == 3
    labels = [e.image_label for e in by_shot["para"]]
    assert labels == ["primary", "layer_0", "layer_1"]
    assert by_shot["para"][1].role == "background"
    assert by_shot["para"][2].role == "subject"


def test_only_a_parallax_shots_primary_is_flagged_as_the_render_time_fallback():
    """§3 P0's own framing: a parallax shot's primary IS still generated
    by the real pipeline (`ResolveAssetsStep` never suppresses it for this
    movement), but `render.py`'s own lookup only reaches for it when a
    plane fails to resolve - flagging it is what stops the user spending a
    Grok generation on a picture the finished film will only show on a
    degrade. No other entry (a plain shot's primary, or either layer) is
    ever a fallback."""
    scene = Scene(
        id="sc_01", order=0, title="t", duration_s=6.0,
        shots=[_plain_shot("plain"), _parallax_shot("para")],
    )
    entries = build_prompt_export_entries(_timeline([scene]))
    flagged = {(e.shot_id, e.image_label) for e in entries if e.is_parallax_fallback}
    assert flagged == {("para", "primary")}


def test_prompts_are_byte_identical_to_the_real_generation_path():
    """The identity test. `illustrated_risograph` is the real style the
    plan's own measurements were taken against (778x1383 request size for
    a 720x1280 canvas) - deliberately used here rather than the default
    style so this test exercises the same GENERATION_ONLY path a real
    parallax film actually runs under, not an unrelated default.

    Every prompt asserted against a DIRECT call to `styled_prompt`/
    `layer_styled_prompt` - never a hardcoded string - so a future change
    to either function is automatically re-verified here rather than
    silently diverging from what this export claims to send."""
    style = "illustrated_risograph"
    visual_style = "1940s archival, desaturated, grainy risograph print"
    plain = _plain_shot("plain", prompt="a coal mine at dusk")
    parallax = _parallax_shot("para")
    scene = Scene(id="sc_01", order=0, title="t", duration_s=6.0, shots=[plain, parallax])
    timeline = _timeline([scene], render_style=style, visual_style=visual_style)

    entries = build_prompt_export_entries(timeline)
    by_shot: dict[str, list] = {}
    for e in entries:
        by_shot.setdefault(e.shot_id, []).append(e)

    frame = resolve_render_format(style, frame_aspect=timeline.metadata.frame_aspect)
    creative_context = timeline.creative_context

    assert by_shot["plain"][0].prompt == styled_prompt(plain, creative_context, frame=frame)

    para_entries = by_shot["para"]
    assert para_entries[0].prompt == styled_prompt(parallax, creative_context, frame=frame)
    assert para_entries[1].prompt == layer_styled_prompt(
        parallax, parallax.layers[0], creative_context, frame=frame
    )
    assert para_entries[2].prompt == layer_styled_prompt(
        parallax, parallax.layers[1], creative_context, frame=frame
    )
    # Not vacuous - the truncated visual_style really did land in each one.
    assert "risograph" in para_entries[0].prompt
    assert "risograph" in para_entries[1].prompt
    assert "risograph" in para_entries[2].prompt


def test_header_names_the_target_size_from_resolve_generation_request_format():
    """§7/§4.5: never a hardcoded pixel size in a test - the oversize
    fraction is a tunable constant (`settings.substrate_crop_oversize_
    fraction`) and has already been retuned once (0.04 -> 0.08, per
    `test_layer_generation.py`'s own note). Derive the expected size the
    same way the export itself must."""
    style = "illustrated_risograph"
    scene = Scene(id="sc_01", order=0, title="t", duration_s=3.0, shots=[_plain_shot("s1")])
    timeline = _timeline([scene], render_style=style)
    frame = resolve_render_format(style, frame_aspect=timeline.metadata.frame_aspect)
    expected = resolve_generation_request_format(style, frame)

    entries = build_prompt_export_entries(timeline)
    text = render_prompt_export_text(timeline, entries, project_name="The City Rats")

    assert f"{expected.width}x{expected.height}" in text
    # The canvas and the request size differ for a GENERATION_ONLY style -
    # a test that only checked the CANVAS size would pass even if the
    # header regressed to naming the wrong one.
    assert (expected.width, expected.height) != (frame.width, frame.height)


def test_header_also_tells_the_human_to_set_the_providers_own_aspect_control():
    """§7.1/§3 P0: words alone did not hold for Qwen - it obeyed only its
    UI aspect control. The export must say both, never rely on the prompt
    words alone to carry the whole burden."""
    scene = Scene(id="sc_01", order=0, title="t", duration_s=3.0, shots=[_plain_shot("s1")])
    timeline = _timeline([scene])
    entries = build_prompt_export_entries(timeline)
    text = render_prompt_export_text(timeline, entries, project_name="p")

    assert "aspect-ratio control" in text or "aspect ratio control" in text


def test_every_entry_carries_its_own_orientation_sentence():
    """Repeated per entry, not stated once in the header - a human who
    copies a single prompt block (today's actual one-shot-at-a-time habit)
    must still get the reminder even without the file's opening lines."""
    scene = Scene(
        id="sc_01", order=0, title="t", duration_s=6.0,
        shots=[_plain_shot("a"), _parallax_shot("b")],
    )
    # illustrated_risograph is portrait (9:16) by default - the real
    # parallax style this plan was measured against (§7). The overall
    # default style (`documentary_archival`) is landscape, which would
    # make this assertion vacuous for the wrong reason.
    timeline = _timeline([scene], render_style="illustrated_risograph")
    entries = build_prompt_export_entries(timeline)
    text = render_prompt_export_text(timeline, entries, project_name="p")

    assert text.count("Vertical portrait image, 9:16") == len(entries)


def test_landscape_style_gets_the_landscape_sentence_not_the_portrait_one():
    scene = Scene(id="sc_01", order=0, title="t", duration_s=3.0, shots=[_plain_shot("s1")])
    timeline = _timeline([scene], render_style="illustrated_risograph", frame_aspect="16:9")
    entries = build_prompt_export_entries(timeline)
    text = render_prompt_export_text(timeline, entries, project_name="p")

    assert "Horizontal landscape image, 16:9" in text
    assert "Vertical portrait image" not in text
