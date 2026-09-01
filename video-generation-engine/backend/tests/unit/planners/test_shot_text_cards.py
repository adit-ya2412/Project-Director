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
        sfx_cue="",
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
    'base prompt already does the right thing' (None), never an error.
    `documentary_archival` and `stillness` USED to belong on this list
    (§1.2/A1 and A4 of long_form_direction.md), but both now have their
    own fragments - see
    `test_stillness_fragment_loads_and_the_other_styles_are_unaffected`
    and `test_documentary_archival_fragment_loads_and_the_other_styles_are_unaffected`
    below. Only a genuinely unregistered style, or no style at all,
    belongs here now."""
    assert load_style_fragment("shot_planner", None) is None
    assert load_style_fragment("shot_planner", "not_a_real_style") is None


def test_stillness_fragment_loads_and_the_other_styles_are_unaffected():
    """A1 (long_form_direction.md §3): `stillness` reached the Shot
    Planner with the generic base prompt only, contradicting its own
    suitability blurb ("long static holds, no camera motion, deliberate
    quiet" - §1.2). This is the loader-level proof that the new fragment
    file is actually picked up, plus a regression guard that adding it
    left the other three styles' resolution untouched."""
    fragment = load_style_fragment("shot_planner", "stillness")
    assert fragment is not None
    assert "static" in fragment
    assert "slow_push" in fragment
    for token in ("punch_in", "pull_back", "slow_zoom", "pan", "split_frame"):
        assert token in fragment, f"off-limits camera vocabulary {token!r} missing"
    for token in ("cut", "dissolve"):
        assert token in fragment, f"transition vocabulary {token!r} missing"

    # The other two styles must resolve exactly as before. (documentary_archival
    # is checked separately below - A4 gave it a fragment too.)
    assert load_style_fragment("shot_planner", "retention_fast") is not None
    assert load_style_fragment("shot_planner", "archival_montage") is not None


def test_documentary_archival_fragment_loads_and_the_other_styles_are_unaffected():
    """A4 (long_form_direction.md §3): `documentary_archival` reached the
    Shot Planner with the generic base prompt only, so it had no chapter-
    card / act-boundary / long-form pacing direction at all (§1.1/§1.5).
    This is the loader-level proof the new fragment file is picked up,
    plus a regression guard that adding it left the other three styles'
    resolution untouched.

    Note the trade this fragment makes (long_form_direction.md §4.1):
    `documentary_archival` is `settings.default_render_style`, so giving
    it a fragment switches off the Director's per-project
    `camera_language` line for every landscape project, not just
    long-form ones (`suppress_camera_language=style_fragment is not
    None` in `app/planners/shot/planner.py`). The fragment therefore
    carries its own fixed camera-restraint clause to replace that line,
    checked below alongside the long-form vocabulary."""
    fragment = load_style_fragment("shot_planner", "documentary_archival")
    assert fragment is not None
    # The long-form vocabulary the fragment must reference to be usable
    # against A6's "Long-form context" block (act / opens this act / canvas).
    assert "act:" in fragment
    assert "opens this act: yes" in fragment
    assert "text_card" in fragment
    assert "fadeblack" in fragment
    # punch_in is named as off-limits, not merely omitted.
    assert "punch_in" in fragment
    for token in ("pan", "slow_push", "pull_back", "static", "slow_zoom"):
        assert token in fragment, f"camera vocabulary {token!r} missing"
    for token in ("cut", "dissolve"):
        assert token in fragment, f"transition vocabulary {token!r} missing"
    # The camera_language replacement clause (§4.1's trade), stated plainly.
    assert "camera_language" in fragment
    # A5 owns vertical pan / CameraDirection.UP/DOWN - must not appear here.
    assert "UP" not in fragment
    assert "DOWN" not in fragment
    assert "vertical" not in fragment.lower()

    # The other three styles must resolve exactly as before.
    assert load_style_fragment("shot_planner", "stillness") is not None
    assert load_style_fragment("shot_planner", "retention_fast") is not None
    assert load_style_fragment("shot_planner", "archival_montage") is not None
