"""`app/workflow/steps/generate_timeline.py::_force_generation_only_picture_path`
(illustrated_faceless.md §3.2, F1) - the code-level enforcement point for
`resolve_picture_path(style) is PicturePath.GENERATION_ONLY`.

Pure/fast: builds `Scene`/`Shot`/`AssetPlan` objects directly and calls the
real function - no DB, no workflow engine, no LLM. This is deliberately
NOT tested by asking a fake/real Asset Planner to "always generate" -
§3.2's whole point is that the Asset Planner never sees `render_style` and
so cannot be asked at all; the override happens strictly after it returns.
"""

from app.schemas.timeline import (
    ASSET_LADDER,
    AssetPlan,
    AssetStrategy,
    PreferredMediaType,
    Scene,
    Shot,
    ShotIntent,
)
from app.workflow.steps.generate_timeline import _force_generation_only_picture_path


def _shot(index: int, *, strategy: AssetStrategy, preferred_type: PreferredMediaType) -> Shot:
    return Shot(
        id=f"sh_{index:03d}",
        order=index,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        prompt="a figure at a desk",
        asset_plan=AssetPlan(
            entity="Some Named Thing",
            strategy=strategy,
            search_queries=["some query"],
            preferred_type=preferred_type,
            fallback_chain=[
                s for s in ASSET_LADDER if ASSET_LADDER.index(s) >= ASSET_LADDER.index(strategy)
            ],
            licence_requirements=["public_domain"],
        ),
    )


def test_run_actually_calls_the_override_after_the_asset_planner_returns():
    """Structural proof the override is wired into the real pipeline, not
    just a standalone function nothing calls. `GenerateTimelineStep.run`
    delegates the real (non-DRY_RUN) planning chain to `_run_real`, which
    must call `resolve_picture_path` and, when it says GENERATION_ONLY,
    `_force_generation_only_picture_path`, both after `AssetPlanner(...)
    .plan(...)` and before the resulting scenes are persisted. Source
    inspection only (no DB/LLM), matching
    `test_generate_timeline_style_bounds.py`'s own
    `test_is_fully_planned_and_runs_own_gate_can_no_longer_disagree`."""
    import inspect

    from app.workflow.steps import generate_timeline

    source = inspect.getsource(generate_timeline.GenerateTimelineStep._run_real)
    plan_pos = source.index("AssetPlanner(provider, llm_call_repo).plan(")
    resolve_pos = source.index("resolve_picture_path(", plan_pos)
    override_pos = source.index("_force_generation_only_picture_path(", resolve_pos)
    apply_pos = source.index("_apply_assets", override_pos)
    assert plan_pos < resolve_pos < override_pos < apply_pos


def test_run_real_threads_the_timelines_render_style_into_the_director_call():
    """illustrated_faceless.md P-IF-F1-review3: the Director needs to know
    the project's picture path to append its own generation-only override
    (`app/planners/director/planner.py::_system_prompt_for`). RV2
    ("resolve once, thread explicitly") - `_run_real` must thread the
    already-loaded `timeline.metadata.render_style` through the
    `DirectorPlanner(...).plan(...)` call, not have the planner reach into
    settings or the DB itself. Source inspection only (no DB/LLM), same
    shape as `test_run_actually_calls_the_override_after_the_asset_planner_
    returns` above."""
    import inspect

    from app.workflow.steps import generate_timeline

    source = inspect.getsource(generate_timeline.GenerateTimelineStep._run_real)
    director_call_pos = source.index("DirectorPlanner(provider, llm_call_repo).plan(")
    render_style_pos = source.index(
        "render_style=timeline.metadata.render_style", director_call_pos
    )
    # The kwarg must belong to the SAME call - nothing else (e.g. a later,
    # unrelated call site) between them.
    next_call_pos = source.find("DirectorPlanner(", director_call_pos + 1)
    assert director_call_pos < render_style_pos
    assert next_call_pos == -1 or render_style_pos < next_call_pos


def test_every_shots_asset_plan_collapses_to_generate_image_only():
    """The real shape of a retrieval-first plan (e.g. `historical_search`
    with a five-rung fallback chain) must collapse to the single-rung
    generation-only chain, regardless of what the Asset Planner picked."""
    scene = Scene(
        id="sc_001",
        order=0,
        title="scene",
        duration_s=3.0,
        shots=[
            _shot(
                0,
                strategy=AssetStrategy.HISTORICAL_SEARCH,
                preferred_type=PreferredMediaType.IMAGE,
            )
        ],
    )
    [forced] = _force_generation_only_picture_path([scene])
    [shot] = forced.shots
    assert shot.asset_plan is not None
    assert shot.asset_plan.strategy == AssetStrategy.GENERATE_IMAGE
    assert shot.asset_plan.fallback_chain == [AssetStrategy.GENERATE_IMAGE]
    assert shot.asset_plan.preferred_type == PreferredMediaType.IMAGE


def test_a_video_preferred_shot_is_forced_to_stills_too():
    """F1 is stills only (no motion, no layers - that's F2+). A shot the
    Asset Planner would have sent to `generate_video` must come back as
    `preferred_type=image`, not just `strategy=generate_image` with a
    stale video preference."""
    scene = Scene(
        id="sc_001",
        order=0,
        title="scene",
        duration_s=3.0,
        shots=[
            _shot(
                0,
                strategy=AssetStrategy.GENERATE_VIDEO,
                preferred_type=PreferredMediaType.VIDEO,
            )
        ],
    )
    [forced] = _force_generation_only_picture_path([scene])
    [shot] = forced.shots
    assert shot.asset_plan is not None
    assert shot.asset_plan.strategy == AssetStrategy.GENERATE_IMAGE
    assert shot.asset_plan.fallback_chain == [AssetStrategy.GENERATE_IMAGE]
    assert shot.asset_plan.preferred_type == PreferredMediaType.IMAGE


def test_the_forced_chain_is_a_legal_ascending_ladder_subsequence():
    """`AssetPlan.fallback_chain` has a real pydantic validator
    (`_fallback_chain_is_ladder_subsequence` in app/schemas/timeline.py)
    requiring an ascending subsequence of `ASSET_LADDER`. `[generate_image]`
    is legal by construction (one element trivially satisfies ascending) -
    proven here by round-tripping the forced plan back through the model,
    not just asserted."""
    scene = Scene(
        id="sc_001",
        order=0,
        title="scene",
        duration_s=3.0,
        shots=[
            _shot(
                0,
                strategy=AssetStrategy.PROJECT_ASSETS,
                preferred_type=PreferredMediaType.IMAGE,
            )
        ],
    )
    [forced] = _force_generation_only_picture_path([scene])
    [shot] = forced.shots
    assert shot.asset_plan is not None
    # Re-validates the round trip through pydantic - would raise if the
    # forced chain were ever an illegal (non-ascending, or non-subsequence)
    # ladder order.
    AssetPlan.model_validate(shot.asset_plan.model_dump())


def test_multiple_shots_and_scenes_are_all_forced_independently():
    scenes = [
        Scene(
            id="sc_001",
            order=0,
            title="scene one",
            duration_s=6.0,
            shots=[
                _shot(
                    0, strategy=AssetStrategy.STOCK_SEARCH, preferred_type=PreferredMediaType.IMAGE
                ),
                _shot(
                    1,
                    strategy=AssetStrategy.GENERATE_VIDEO,
                    preferred_type=PreferredMediaType.VIDEO,
                ),
            ],
        ),
        Scene(
            id="sc_002",
            order=1,
            title="scene two",
            duration_s=3.0,
            shots=[
                _shot(
                    2, strategy=AssetStrategy.PUBLIC_DOMAIN, preferred_type=PreferredMediaType.IMAGE
                )
            ],
        ),
    ]
    forced = _force_generation_only_picture_path(scenes)
    all_shots = [shot for scene in forced for shot in scene.shots]
    assert len(all_shots) == 3
    for shot in all_shots:
        assert shot.asset_plan is not None
        assert shot.asset_plan.strategy == AssetStrategy.GENERATE_IMAGE
        assert shot.asset_plan.fallback_chain == [AssetStrategy.GENERATE_IMAGE]
        assert shot.asset_plan.preferred_type == PreferredMediaType.IMAGE


def test_a_shot_with_no_asset_plan_is_left_alone_not_crashed_on():
    """Defensive: `AssetPlanner.plan` always fills `asset_plan` before this
    runs (it is the very next step after the Asset Planner returns), but
    the override must not assume that and crash on a `None`."""
    scene = Scene(
        id="sc_001",
        order=0,
        title="scene",
        duration_s=3.0,
        shots=[Shot(id="sh_000", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)],
    )
    [forced] = _force_generation_only_picture_path([scene])
    [shot] = forced.shots
    assert shot.asset_plan is None


def test_secondary_asset_plan_is_left_untouched():
    """illustrated_faceless.md's own DO-NOT list: F1 does not touch
    `split_frame`, `secondary_prompt`, or `secondary_asset_plan`. A
    split_frame shot's bottom-panel plan must survive this override
    exactly as the Asset Planner produced it, even while the shot's own
    primary `asset_plan` is forced generation-only."""
    secondary = AssetPlan(
        strategy=AssetStrategy.STOCK_SEARCH,
        search_queries=["bottom panel query"],
        preferred_type=PreferredMediaType.IMAGE,
        fallback_chain=[AssetStrategy.STOCK_SEARCH, AssetStrategy.GENERATE_IMAGE],
        licence_requirements=["pexels_licence"],
    )
    shot = _shot(
        0, strategy=AssetStrategy.HISTORICAL_SEARCH, preferred_type=PreferredMediaType.IMAGE
    ).model_copy(update={"secondary_asset_plan": secondary})
    scene = Scene(id="sc_001", order=0, title="scene", duration_s=3.0, shots=[shot])

    [forced] = _force_generation_only_picture_path([scene])
    [forced_shot] = forced.shots
    assert forced_shot.secondary_asset_plan == secondary
    assert forced_shot.asset_plan is not None
    assert forced_shot.asset_plan.fallback_chain == [AssetStrategy.GENERATE_IMAGE]


def test_entity_and_search_queries_are_left_alone_not_scrubbed():
    """§3.2 only asks for `fallback_chain`/`strategy` (and `preferred_type`,
    for the stills-only guarantee) to be overridden. `entity`/
    `search_queries`/`licence_requirements` are harmless leftovers - a
    fallback_chain of only `generate_image` never reaches the search/entity
    rungs those fields would otherwise drive."""
    scene = Scene(
        id="sc_001",
        order=0,
        title="scene",
        duration_s=3.0,
        shots=[
            _shot(
                0,
                strategy=AssetStrategy.HISTORICAL_SEARCH,
                preferred_type=PreferredMediaType.IMAGE,
            )
        ],
    )
    [forced] = _force_generation_only_picture_path([scene])
    [shot] = forced.shots
    assert shot.asset_plan is not None
    assert shot.asset_plan.entity == "Some Named Thing"
    assert shot.asset_plan.search_queries == ["some query"]
    assert shot.asset_plan.licence_requirements == ["public_domain"]
