"""F2b (illustrated_faceless.md §8.5, 2026-09-05): the pure helpers a
layer's generation and render-time lookup both share -
`layer_styled_prompt`, `_layer_seed`, and `layer_prompt_hash`. No DB, no
network - the DB-touching generation paths themselves
(`generate_layer_image_real`/`_generate_layer_fake`) are exercised
against the real generation pipeline the same way `generate_image_real`
already is, in `tests/integration/`.
"""

import uuid

from app.core.config import settings
from app.schemas.timeline import CreativeContext, LayerRole, Shot, ShotIntent, ShotLayer
from app.script.styles import RenderFormat, resolve_generation_request_format
from app.workflow.steps.resolve_assets import (
    _layer_seed,
    _project_seed,
    generation_prompt_hash,
    layer_prompt_hash,
    layer_styled_prompt,
)


def _shot(prompt: str = "a quiet room") -> Shot:
    return Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt=prompt)


def _layer(role: LayerRole, prompt: str) -> ShotLayer:
    return ShotLayer(role=role, prompt=prompt)


# --- layer_styled_prompt -------------------------------------------------


def test_layer_prompt_replaces_the_shots_own_prompt_not_appends_to_it():
    shot = _shot("a quiet room")
    layer = _layer(LayerRole.SUBJECT, "a seated figure on a magenta field")
    result = layer_styled_prompt(shot, layer, CreativeContext())
    assert result == "a seated figure on a magenta field"
    assert "a quiet room" not in result


def test_layer_prompt_gets_the_same_visual_style_and_landscape_treatment():
    """The layer goes through the IDENTICAL `_styled_prompt` pipeline a
    shot's own prompt does - the visual_style cap and the landscape
    suffix both apply."""
    shot = _shot("a quiet room")
    layer = _layer(LayerRole.BACKGROUND, "an empty room")
    cc = CreativeContext(visual_style="1940s archival, desaturated")
    portrait = layer_styled_prompt(shot, layer, cc, frame=RenderFormat(width=720, height=1280))
    assert portrait == "an empty room, 1940s archival, desaturated"
    landscape = layer_styled_prompt(shot, layer, cc, frame=RenderFormat(width=1280, height=720))
    assert landscape.endswith("Composed for a landscape 16:9 frame.")


def test_two_different_roles_on_the_same_shot_get_different_prompts():
    shot = _shot()
    background = layer_styled_prompt(
        shot, _layer(LayerRole.BACKGROUND, "an empty room"), CreativeContext()
    )
    subject = layer_styled_prompt(
        shot, _layer(LayerRole.SUBJECT, "a seated figure"), CreativeContext()
    )
    assert background != subject


# --- _layer_seed ----------------------------------------------------------


def test_background_layer_keeps_the_bare_project_seed():
    project_seed = _project_seed("some-project")
    assert _layer_seed(project_seed, 0) == project_seed


def test_subject_layer_seed_varies_deterministically_and_is_stable():
    project_seed = _project_seed("some-project")
    first = _layer_seed(project_seed, 1)
    second = _layer_seed(project_seed, 1)
    assert first == second  # deterministic, never random/wall-clock
    assert first != project_seed


def test_layer_seed_never_depends_on_generated_clip_count():
    """Unlike `_generate_image_once`'s own attempt-count seed, a layer's
    seed is a pure function of (project_seed, layer_index) - not `async`,
    no DB read anywhere in this function's own body."""
    import asyncio
    import inspect

    assert not asyncio.iscoroutinefunction(_layer_seed)
    body = inspect.getsource(_layer_seed).split('"""', 2)[-1]  # strip the docstring
    assert "count_for_shot" not in body
    assert "clip_repo" not in body


# --- layer_prompt_hash -----------------------------------------------------


def test_layer_prompt_hash_is_deterministic():
    shot = _shot()
    layer = _layer(LayerRole.SUBJECT, "a seated figure on a magenta field")
    project_uuid = uuid.uuid4()
    first = layer_prompt_hash(
        shot, layer, layer_index=1, project_uuid=project_uuid, creative_context=CreativeContext()
    )
    second = layer_prompt_hash(
        shot, layer, layer_index=1, project_uuid=project_uuid, creative_context=CreativeContext()
    )
    assert first == second


def test_layer_prompt_hash_differs_by_prompt_role_and_project():
    project_uuid = uuid.uuid4()
    shot = _shot()
    background = layer_prompt_hash(
        shot,
        _layer(LayerRole.BACKGROUND, "an empty room"),
        layer_index=0,
        project_uuid=project_uuid,
        creative_context=CreativeContext(),
    )
    subject = layer_prompt_hash(
        shot,
        _layer(LayerRole.SUBJECT, "a seated figure"),
        layer_index=1,
        project_uuid=project_uuid,
        creative_context=CreativeContext(),
    )
    assert background != subject

    other_project = layer_prompt_hash(
        shot,
        _layer(LayerRole.BACKGROUND, "an empty room"),
        layer_index=0,
        project_uuid=uuid.uuid4(),
        creative_context=CreativeContext(),
    )
    assert other_project != background


def test_layer_prompt_hash_changes_when_the_layer_prompt_changes():
    """R2/§4.1: a changed layer is exactly what must change the render
    fingerprint - `layer_prompt_hash`'s output is what `render.py` feeds
    into `layer_content_hashes`, so this is the load-bearing sensitivity
    check for that path."""
    project_uuid = uuid.uuid4()
    shot = _shot()
    original = layer_prompt_hash(
        shot,
        _layer(LayerRole.SUBJECT, "a seated figure"),
        layer_index=1,
        project_uuid=project_uuid,
        creative_context=CreativeContext(),
    )
    edited = layer_prompt_hash(
        shot,
        _layer(LayerRole.SUBJECT, "a standing figure"),
        layer_index=1,
        project_uuid=project_uuid,
        creative_context=CreativeContext(),
    )
    assert original != edited


def test_layer_prompt_hash_dry_run_branch_never_reads_the_project_seed(monkeypatch):
    """DRY_RUN's own branch must not depend on the project id at all -
    `FakeImageProvider` never varies by seed, and `generation_prompt_hash`
    is called with no seed argument in that branch."""
    monkeypatch.setattr(settings, "dry_run", True)
    shot = _shot()
    layer = _layer(LayerRole.BACKGROUND, "an empty room")
    a = layer_prompt_hash(
        shot, layer, layer_index=0, project_uuid=uuid.uuid4(), creative_context=CreativeContext()
    )
    b = layer_prompt_hash(
        shot, layer, layer_index=0, project_uuid=uuid.uuid4(), creative_context=CreativeContext()
    )
    assert a == b


def test_layer_prompt_hash_matches_generation_prompt_hash_directly_for_real_mode(monkeypatch):
    """Pins the exact formula real-mode `layer_prompt_hash` computes, so a
    future refactor can't silently change what gets hashed without a test
    noticing - this is the SAME value `render.py` must be able to
    recompute to find an already-resolved layer clip."""
    monkeypatch.setattr(settings, "dry_run", False)
    project_uuid = uuid.uuid4()
    shot = _shot()
    layer = _layer(LayerRole.SUBJECT, "a seated figure")
    prompt = layer_styled_prompt(
        shot, layer, CreativeContext(), frame=RenderFormat(width=720, height=1280)
    )
    project_seed = _project_seed(str(project_uuid))
    seed = _layer_seed(project_seed, 1)
    # Derived, never a literal: 749x1332 was hardcoded here and broke the
    # moment `substrate_crop_oversize_fraction` was retuned 0.04 -> 0.08
    # on a real measurement (config.py's own table). A test that restates
    # production arithmetic as a magic number does not verify the
    # arithmetic, it just pins today's output of it - and the R1 lesson
    # this codebase already paid for is that one rule expressed in two
    # places drifts. Read the same resolver production reads.
    request_frame = resolve_generation_request_format(
        "illustrated_risograph", RenderFormat(width=720, height=1280)
    )
    expected = generation_prompt_hash(
        prompt,
        settings.fal_image_model,
        seed,
        width=request_frame.width,
        height=request_frame.height,
    )
    actual = layer_prompt_hash(
        shot,
        layer,
        layer_index=1,
        project_uuid=project_uuid,
        creative_context=CreativeContext(),
        style="illustrated_risograph",
    )
    assert actual == expected
