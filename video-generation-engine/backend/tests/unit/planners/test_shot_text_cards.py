"""Feature B (style_extensions.md §4.4/§4.5): text cards as a planner-
driven mechanism, and the per-planner style-fragment matrix.

Pure unit tests - no DB, no live LLM, `--noconftest`-safe. The DB-backed
golden-file tests in test_shot_planner.py cover the planner's fragment/
duration validation; this file covers what Feature B actually added:

1. `ShotPlanOutput.text_card` -> `Shot.text_card` threading (the §4.4
   confirmation the plan demanded BEFORE writing the prompt fragment:
   text cards were render-side only until now - `Shot.text_card` and
   `text_cards.py` pre-exist Feature B, but the Shot Planner had no way
   to emit one).
2. The §4.5 matrix rows that reduce to filesystem facts: only the Shot
   Planner has per-style fragments today; Director/Scene/Asset planners
   are not style-branched at all (verified by reading them, logged in
   P-B). archival_montage's fragment must reference REAL mechanisms
   (§2.6) - the actual field name and actual enum values.
"""

from app.planners.fragments import split_narration_fragments
from app.planners.shot.planner import _to_domain_shot
from app.planners.shot.schemas import (
    ShotCameraOutput,
    ShotPlanOutput,
    ShotTransitionOutput,
)
from app.prompts.loader import load_style_fragment
from app.schemas.timeline import (
    CameraDirection,
    CameraMovement,
    Framing,
    ShotIntent,
    TransitionType,
)

_NARRATION = "Coal wealth shaped the region. Then the mines closed."


def _shot_output(text_card: str) -> ShotPlanOutput:
    return ShotPlanOutput(
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
        transition_out=ShotTransitionOutput(type=TransitionType.CUT, duration_s=0.0),
        prompt="archival photograph",
        secondary_prompt="",
        text_card=text_card,
    )


def _domain_shot(text_card: str):
    fragments = split_narration_fragments(_NARRATION)
    assert len(fragments) == 2
    return _to_domain_shot(_shot_output(text_card), scene_id="sc_01", fragments=fragments)


# ---------------------------------------------------------------------------
# Threading: ShotPlanOutput.text_card -> Shot.text_card (§4.4)
# ---------------------------------------------------------------------------


def test_a_non_empty_text_card_threads_through_to_the_persisted_shot():
    shot = _domain_shot("1923: Hyperinflation")
    assert shot.text_card == "1923: Hyperinflation"


def test_an_empty_or_whitespace_text_card_persists_as_none():
    """The persisted model's 'no card' shape is None; empty string is
    what strict-mode structured output makes the model send instead."""
    assert _domain_shot("").text_card is None
    assert _domain_shot("   ").text_card is None


# ---------------------------------------------------------------------------
# §4.5 matrix rows that are filesystem facts (§4.3's "check, don't assume")
# ---------------------------------------------------------------------------


def test_only_the_shot_planner_has_per_style_fragments_today():
    """§4.3: if director/scene/asset planners had per-style override
    directories analogous to shot_planner_styles/, archival_montage would
    need matching coverage. They do not - NO style does - so this is
    logged here in code rather than silently skipped. If this test ever
    fails because such directories appeared, Feature B's coverage
    decision needs revisiting for the new planner."""
    from app.prompts.loader import _PROMPTS_ROOT

    for agent in ("director", "scene_planner", "asset_planner"):
        assert not (_PROMPTS_ROOT / f"{agent}_styles").exists(), (
            f"{agent} gained a style-fragment directory; archival_montage "
            "(and any new style) now needs fragments there too"
        )
    # ...while the Shot Planner genuinely has them.
    assert (_PROMPTS_ROOT / "shot_planner_styles" / "archival_montage.md").is_file()


def test_archival_montage_fragment_loads_and_references_real_mechanisms():
    """§2.6: a style fragment must reference vocabulary that actually
    exists - the real `text_card` field name and real camera/transition
    enum values, never invented ones."""
    fragment = load_style_fragment("shot_planner", "archival_montage")
    assert fragment is not None
    assert "text_card" in fragment
    for token in ("pan", "slow_push", "punch_in", "pull_back", "static"):
        assert token in fragment, f"camera vocabulary {token!r} missing"
    for token in ("cut", "dissolve"):
        assert token in fragment, f"transition vocabulary {token!r} missing"


def test_styles_without_fragments_still_resolve_to_none():
    """The loader contract Feature B must not break: missing fragment ==
    'base prompt already does the right thing' (None), never an error -
    documentary_archival/stillness have no fragment even though they are
    registered styles."""
    assert load_style_fragment("shot_planner", None) is None
    assert load_style_fragment("shot_planner", "documentary_archival") is None
    assert load_style_fragment("shot_planner", "stillness") is None
    assert load_style_fragment("shot_planner", "not_a_real_style") is None
