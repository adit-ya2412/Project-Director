"""`shot_planner_styles/illustrated_risograph.md` (illustrated_faceless.md
§2.1, F1) - loader-level proof the fragment is actually picked up and
carries the three measured prompt rules (§1.2/§1.3/§1.7) that must not be
softened, plus a regression guard that adding it left the four
pre-existing styles' fragment resolution untouched.

Collapsed from two files (`illustrated_risograph_vertical.md` /
`_horizontal.md`) to one, follow-up to F1's review (2026-09-04): the two
differed only in a heading, a style-name sentence, and one framing bullet,
so the world token itself lived in two places - long_form_direction.md
§4.3's named lesson, "two styles, one base table - do not fix this
twice." One fragment now carries a single canvas-conditional framing
bullet instead, keyed off the `- canvas: WxH (...)` line the base prompt
(`shot_planner/v1.md`) already supplies.

Pure unit test - no DB, no live LLM, `--noconftest`-safe (same shape as
`test_shot_text_cards.py`'s own fragment-matrix tests).
"""

from pathlib import Path

from app.prompts.loader import load_style_fragment

_STYLE_NAME = "illustrated_risograph"


def test_fragment_loads():
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None, f"{_STYLE_NAME} fragment failed to load"
    assert fragment.startswith(f"## Style override: {_STYLE_NAME}")


def _world_token_line(fragment: str) -> str:
    """The actual, quoted world token - the `>` blockquote line - as
    distinct from the surrounding prose (which legitimately discusses
    and names the removed phrase in an explanatory comment, same as this
    test file's own docstrings do)."""
    (line,) = (line for line in fragment.splitlines() if line.strip().startswith(">"))
    return line


def test_the_world_token_is_present_and_the_artefact_noun_is_gone():
    """§1.7: name the medium and technique, never an object made of it.
    The measured failure was the trailing "...like a printed protest
    poster" turning into a physical paper border in the bake-off - so
    the TOKEN ITSELF (the actual text a shot's `prompt` carries into
    generation) must not contain "poster", while the technique
    vocabulary that actually describes the world must. The surrounding
    fragment may still (and does) discuss the removed phrase in an
    explanatory comment - see test_a_comment_explains_why_the_artefact_
    noun_was_removed below."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    token_line = _world_token_line(fragment)
    assert "poster" not in token_line.lower()
    for token in (
        "risograph",
        "spot colours",
        "deep teal",
        "fluorescent orange",
        "off-white uncoated paper",
        "ink grain",
        "halftone",
        "misregistration",
    ):
        assert token in token_line, f"missing world-token vocabulary {token!r}"


def test_the_comment_cites_the_plan_and_names_no_artefact():
    """The comment must point at the plan, and must NOT spell out the
    forbidden nouns.

    `load_style_fragment` appends this ENTIRE file to the Shot Planner's
    system prompt - HTML comments included, and it does not strip them.
    An earlier version of this file explained §1.7 inline, which put
    "poster" (x5), "notebook", "printed on", "paper border", "signature
    mark" and "stamp" into the prompt on every scene call: the exact
    nouns §1.7 exists to keep away from the model, and three of them the
    very artefacts that appeared in the bad still. A comment is obvious
    to a human reader as a note rather than an instruction; to a model
    receiving the file as text there is no such distinction. So the
    rationale lives in the plan and the comment names nothing."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    assert "<!--" in fragment and "-->" in fragment
    comment_start = fragment.index("<!--")
    comment = fragment[comment_start : fragment.index("-->")]
    assert "§1.7" in comment
    assert "illustrated_faceless.md" in comment
    # The comment must sit AFTER the token line, not before it.
    assert fragment.index(_world_token_line(fragment)) < comment_start


def test_the_whole_fragment_names_no_artefact_or_negation_noun():
    """The load-bearing invariant, checked over the WHOLE file rather
    than the token alone - because the whole file is what reaches the
    model. Every noun below is one a real render or bake-off reproduced
    literally in a frame (§1.3, §1.7)."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    lower = fragment.lower()
    for noun in (
        "poster",
        "notebook",
        "printed on",
        "page",
        "sheet",
        "book",
        "stamp",
        "signature",
        "border",
        "open background",
        "no face",
    ):
        assert noun not in lower, (
            f"{noun!r} appears in the fragment, which is sent verbatim to the model - "
            "explain it in illustrated_faceless.md instead"
        )


def test_facelessness_is_all_four_positive_framings_and_instructs_variety():
    """§1.3: all four measured-passing treatments must be present, and
    varying across them must be instructed. The fragment may still name
    "no face" as the negative instruction to avoid writing (as this
    test's own docstring and the plan itself both do) - what matters is
    that the four POSITIVE framings below are the ones actually offered
    to the planner as the thing to write."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    for token in (
        "seen from behind",
        "silhouette",
        "blank, featureless face",
        "cropped above the chin",
    ):
        assert token in fragment, f"missing faceless framing {token!r}"
    assert "vary" in fragment.lower()


def test_ethnicity_and_hair_colour_must_be_stated_explicitly():
    """§1.2: skin tone drifted lighter with abstraction and an unstated
    hair colour came back ginger - the fragment must instruct stating
    both explicitly, not leave either to the model's default."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    assert "ethnicity" in fragment.lower()
    assert "hair colour" in fragment.lower()


def test_plain_flat_background_is_the_required_wording():
    """§1.3: "open background" was read as "open BOOK" for a chart shot -
    the fragment must require the shot planner to WRITE "plain flat
    background" for graphic/data shots. It may still name "open
    background" as the failing phrase to avoid (as this test's own
    docstring and the plan itself both do) - that is an instruction
    about what not to write, not a use of it in a generation prompt, so
    it does not reproduce §1.3's failure."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    assert "plain flat background" in fragment.lower()


def test_split_frame_is_discouraged_for_this_style():
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    assert "split_frame" in fragment


def test_subject_layer_prompt_asks_for_matching_scale():
    """P-IF-F2c, DEFECT 2 (prompt-side, option (b) - illustrated_faceless.md
    §7's P-IF-F2c log entry has the reasoning): the subject layer used to be
    generated as its own frame-filling portrait with nothing to say
    otherwise, so a full-frame figure landed on top of a full-frame room and
    read as a collage. The fragment must now tell the planner to describe
    the figure at the scale it would actually read at inside the setting
    the background layer describes, expressed positively (§4.10 - no
    negation) and naming no artefact noun."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    lower = fragment.lower()
    assert "same scale and distance" in lower
    assert "lower third to half of the frame" in lower


def test_framing_bullet_is_canvas_conditional_not_two_files():
    """§6 Q5: vertical wants tighter framing, one subject/graphic at a
    time; horizontal wants room to establish, more than one element per
    frame. Both directions now live in the ONE fragment, gated by the
    canvas the base prompt already tells the planner about (`- canvas:
    WxH (...)`), rather than by which of two files got loaded."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    assert "canvas" in fragment.lower()
    assert "9:16" in fragment
    assert "16:9" in fragment
    # The portrait (tighter) direction:
    assert "one figure or one graphic dominate" in fragment
    # The landscape (room-to-establish) direction:
    assert "room to establish an environment" in fragment
    # Never reframed one into the other.
    assert "never one reframed into the other" in fragment


def test_the_world_token_no_longer_names_a_physical_substrate():
    """P-IF-F1-fixes, fix 2: §1.7's rule was applied only to "printed
    protest poster" - the token still said "...printed on off-white
    uncoated paper", a real render's shot-1 SOURCE STILL came back with a
    visible paper border/signature/stamp, and it was invisible in the
    finished video only because Ken Burns crops the edges off. The token
    must not say the image is "printed on" anything, and paper must read
    as a texture woven through the image, not a page/sheet it sits on."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    token_line = _world_token_line(fragment)
    assert "printed on" not in token_line.lower()
    assert "off-white uncoated paper" in token_line.lower()
    # The first attempt at this fix expressed the rule as a NEGATION
    # ("never a page or sheet the picture sits on"), which contradicted
    # this same fragment's own measured rule that a face-biased model
    # honours a negation unreliably - and put the forbidden nouns into
    # the prompt. It is now the POSITIVE form of the same intent.
    for negation in ("never a page", "page or sheet", "not a page"):
        assert negation not in token_line.lower(), f"token carries a negation: {negation!r}"
    assert "edge to edge" in token_line.lower()


def test_the_ken_burns_masking_finding_is_recorded_in_the_plan_not_the_prompt():
    """The finding itself must survive - a Ken Burns crop can hide a
    substrate artefact, so absence in a rendered video is not evidence
    the token is clean; check the source still. But it belongs in the
    PLAN, not in the prompt file, for the reason
    test_the_comment_cites_the_plan_and_names_no_artefact gives."""
    plan = (
        (Path(__file__).resolve().parents[4] / "docs" / "plans" / "illustrated_faceless.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "ken burns" in plan
    assert "source still" in plan
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    assert "ken burns" not in fragment.lower()


def test_shot_planner_must_reproduce_the_directors_figure_block_verbatim():
    """P-IF-F1-fixes, fix 1: a real render (project 7df10f6c-e6b9-4275-
    b88a-7f07d0178011) showed the same named character rendered as a
    different person from shot to shot, because each scene's Shot Planner
    call invented its own figure instead of reusing the Director's fixed
    description. The fragment must instruct reproducing it essentially
    verbatim, the same reasoning already used for the world token."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    lower = fragment.lower()
    assert "figure block" in lower
    assert "verbatim" in lower
    assert "visual_style" in fragment


def test_a_timed_entry_is_taught_as_rarer_than_parallax_itself():
    """F4 (illustrated_faceless.md §2/F4): the fragment must teach the
    Shot Planner `enter_on_fragment`, that it must fall within THIS
    shot's own fragment range, that the background layer never gets one,
    and a rate cue rarer than parallax's own "one shot in four" (§4.10:
    the rate cue lives here, in the fragment; the reasoning/justification
    for the chosen rate lives in the plan, not in this file)."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    lower = fragment.lower()
    assert "enter_on_fragment" in fragment
    assert "fragment_start" in lower and "fragment_end" in lower
    assert "one parallax shot in three" in lower
    assert "background" in lower and "never gets one" in lower


def test_element_reveal_is_taught_and_bridges_with_the_parallax_skip_bullet():
    """F5 (illustrated_faceless.md §2/F5): the fragment must teach the
    Shot Planner `reveal_direction`/`reveal_start_fragment`/
    `reveal_end_fragment`, both reveal directions, the `camera.movement=
    static` requirement, and that this targets the SAME shots the
    `parallax` bullet already tells the planner to skip - "a flat
    graphic, a chart... nothing to separate" - so the two bullets must
    not contradict each other."""
    fragment = load_style_fragment("shot_planner", _STYLE_NAME)
    assert fragment is not None
    lower = fragment.lower()
    assert "reveal_direction" in fragment
    assert "reveal_start_fragment" in fragment and "reveal_end_fragment" in fragment
    assert "bottom_to_top" in fragment and "left_to_right" in fragment
    assert "camera.movement` to `static" in fragment or "camera.movement" in lower
    assert "static" in lower
    # Bridges explicitly with the parallax-skip bullet, rather than
    # silently targeting the same shots without saying so.
    assert "chart" in lower and "diagram" in lower
    assert "parallax" in lower and "skip" in lower


def test_the_other_four_styles_fragment_resolution_is_unaffected():
    for style in ("documentary_archival", "retention_fast", "archival_montage", "stillness"):
        assert load_style_fragment("shot_planner", style) is not None
    assert load_style_fragment("shot_planner", "not_a_real_style") is None
    assert load_style_fragment("shot_planner", None) is None
    # The two collapsed style names no longer resolve to anything.
    assert load_style_fragment("shot_planner", "illustrated_risograph_vertical") is None
    assert load_style_fragment("shot_planner", "illustrated_risograph_horizontal") is None


def test_no_other_agent_gained_a_style_fragment_directory_for_this_style():
    """Same guard `test_shot_text_cards.py` runs for archival_montage:
    only the Shot Planner is style-branched today (§4.5's matrix).
    Adding a new format must not silently start branching the Director,
    Scene Planner, or Asset Planner too."""
    from app.prompts.loader import _PROMPTS_ROOT

    for agent in ("director", "scene_planner", "asset_planner"):
        assert not (_PROMPTS_ROOT / f"{agent}_styles" / f"{_STYLE_NAME}.md").exists()
