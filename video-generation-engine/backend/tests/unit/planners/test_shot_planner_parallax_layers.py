"""`ShotPlanOutput.layers` (illustrated_faceless.md §2.2/F2a) - the Shot
Planner's authoring path for `CameraMovement.PARALLAX`.

Same shape as `test_split_frame_without_secondary_prompt_is_rejected`/
`test_split_frame_secondary_prompt_lands_on_the_shot` in
`test_shot_planner.py`: a movement/field pair must agree both directions,
enforced as a hard failure (the model already had every fact it needed in
this same call, unlike the project-wide caps in `_cap_*`).
"""

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import async_session_factory
from app.planners.shot.planner import ShotPlanner
from app.planners.shot.schemas import (
    ShotCameraOutput,
    ShotLayerOutput,
    ShotPlannerOutput,
    ShotPlanOutput,
    ShotTransitionOutput,
)
from app.repositories.llm_call_repository import LlmCallRepository
from app.repositories.project_repository import PostgresProjectRepository
from app.schemas.timeline import (
    CameraDirection,
    CameraMovement,
    CreativeContext,
    Framing,
    LayerRole,
    Scene,
    ShotIntent,
)

from .helpers import FakePlanningProvider

NARRATION = "Germany possessed abundant coal. It fueled every furnace in the Ruhr."


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("shot-planner-test")
        return project.id


def _scene() -> Scene:
    return Scene(id="sc_01", order=0, title="Coal wealth", narration_text=NARRATION, duration_s=4.0)


def _shot_output(**overrides) -> ShotPlanOutput:
    fields = dict(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        intent_text="text",
        fragment_start=1,
        fragment_end=2,
        duration_s=4.0,
        framing=Framing.WIDE,
        camera=ShotCameraOutput(
            movement=CameraMovement.STATIC, direction=CameraDirection.NONE, intensity=0.0
        ),
        transition_out=ShotTransitionOutput(type="cut", duration_s=0.0),
        prompt="an illustration",
        secondary_prompt="",
        text_card="",
        sfx_cue="",
        layers=[],
    )
    fields.update(overrides)
    return ShotPlanOutput(**fields)


async def _plan(scene: Scene, output: ShotPlanOutput, project_id: str, *, attempts: int = 1):
    async with async_session_factory() as session:
        response = ShotPlannerOutput(shots=[output])
        provider = FakePlanningProvider(responses=[response] * attempts)
        planner = ShotPlanner(provider, LlmCallRepository(session))
        return await planner.plan(
            project_id=project_id,
            scenes=[scene],
            creative_context=CreativeContext(),
            min_shot_duration_s=1.0,
            max_shot_duration_s=8.0,
            max_shots_per_project=40,
            max_parallax_layers_per_project=100,
        )


_LAYER_OUTPUTS = [
    ShotLayerOutput(role=LayerRole.BACKGROUND, prompt="a quiet room"),
    ShotLayerOutput(role=LayerRole.SUBJECT, prompt="a seated figure"),
]


async def test_parallax_without_layers_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        camera=ShotCameraOutput(
            movement=CameraMovement.PARALLAX, direction=CameraDirection.NONE, intensity=0.0
        )
    )
    with pytest.raises(PermanentError, match="parallax needs exactly 2 layers"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_layers_on_a_non_parallax_shot_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(layers=_LAYER_OUTPUTS)
    with pytest.raises(PermanentError, match="layers is only for parallax"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_parallax_with_wrong_role_order_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        camera=ShotCameraOutput(
            movement=CameraMovement.PARALLAX, direction=CameraDirection.NONE, intensity=0.0
        ),
        layers=[
            ShotLayerOutput(role=LayerRole.SUBJECT, prompt="a seated figure"),
            ShotLayerOutput(role=LayerRole.BACKGROUND, prompt="a quiet room"),
        ],
    )
    with pytest.raises(PermanentError, match="first layer must be role=background"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_parallax_with_an_empty_layer_prompt_is_rejected(project_id, monkeypatch):
    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    scene = _scene()
    bad = _shot_output(
        camera=ShotCameraOutput(
            movement=CameraMovement.PARALLAX, direction=CameraDirection.NONE, intensity=0.0
        ),
        layers=[
            ShotLayerOutput(role=LayerRole.BACKGROUND, prompt="   "),
            ShotLayerOutput(role=LayerRole.SUBJECT, prompt="a seated figure"),
        ],
    )
    with pytest.raises(PermanentError, match="background layer needs a non-empty prompt"):
        await _plan(scene, bad, project_id, attempts=2)


async def test_a_valid_parallax_shot_lands_on_the_domain_shot(project_id):
    scene = _scene()
    good = _shot_output(
        camera=ShotCameraOutput(
            movement=CameraMovement.PARALLAX, direction=CameraDirection.NONE, intensity=0.0
        ),
        layers=_LAYER_OUTPUTS,
    )
    planned = await _plan(scene, good, project_id)
    shot = planned[0].shots[0]
    assert shot.camera.movement == CameraMovement.PARALLAX
    assert [layer.role for layer in shot.layers] == [LayerRole.BACKGROUND, LayerRole.SUBJECT]
    assert [layer.prompt for layer in shot.layers] == ["a quiet room", "a seated figure"]
    # Not authored by this planner (later scope, same as the shot's own
    # top-level `asset_plan`).
    assert all(layer.asset_plan is None for layer in shot.layers)


async def test_a_non_parallax_shot_keeps_layers_empty(project_id):
    scene = _scene()
    good = _shot_output()
    planned = await _plan(scene, good, project_id)
    assert planned[0].shots[0].layers == []
