"""`app/planners/director/planner.py::_system_prompt_for` (illustrated_
faceless.md P-IF-F1-review3) - the Director's own generation-only carve-
out, the same bug P-IF-F1-review2 fixed in `script_suitability`: the base
prompt's "Documentary default" and its provenance-flavoured constraints
("licensed footage", "consent is documented") are wrong for a style that
never retrieves anything, and those constraints are later checked by a
vision model against every generated image - a false rejection is still
billed.

Pure/fast: calls the real composition function directly, no provider, no
DB, no repair loop - the same loader-level shape as `tests/unit/planners/
test_illustrated_risograph_fragment.py` uses for the Shot Planner's own
style fragment. `--noconftest`-safe.
"""

from app.planners.director.planner import _system_prompt_for
from app.prompts.loader import load_prompt

_BASE = load_prompt("director", "v1")


def test_generation_only_style_appends_the_override_block():
    prompt = _system_prompt_for("illustrated_risograph")
    assert prompt != _BASE
    assert prompt.startswith(_BASE)
    assert prompt == f"{_BASE}\n\n{load_prompt('director', 'generation_only')}"


def test_the_regression_that_matters_system_prompt_is_byte_identical_otherwise():
    """The exact regression P-IF-F1-review2's own "Generalisation for F2+"
    note predicted for the next planner this bug reached: every retrieval
    style, `None`, and an unknown style name must all still get the base
    prompt completely unchanged."""
    for style in ("documentary_archival", "retention_fast", "archival_montage", "stillness"):
        assert _system_prompt_for(style) == _BASE
    assert _system_prompt_for(None) == _BASE
    assert _system_prompt_for("not_a_real_style") == _BASE


def test_override_block_reasons_about_depiction_not_provenance():
    override = load_prompt("director", "generation_only")
    lower = override.lower()
    # The provenance vocabulary the base prompt's constraints reach for
    # (licensing, footage rights, consent, archival sourcing) must still be
    # NAMED here - so the model is told explicitly not to write it - but
    # only inside an instruction telling the model to drop it, never as
    # something the model is asked to include.
    for banned in ("licens", "licenc", "footage", "consent", "archival sourcing"):
        assert banned in lower, f"expected the override to name and reject {banned!r}"
    assert "provenance" in lower
    assert "depiction" in lower
    assert "one still image" in lower


def test_override_block_requires_a_plain_stated_setting_not_an_invented_era():
    override = load_prompt("director", "generation_only")
    assert "historical_period" in override
    assert "contemporary, 2020s" in override.lower() or "contemporary" in override.lower()


def test_override_block_does_not_argue_about_camera_language():
    """Mirrors the Shot Planner's `suppress_camera_language=style_fragment
    is not None` reasoning (`app/planners/shot/planner.py`): a style
    fragment owns camera direction downstream, so the Director's own
    override must not add camera-language instructions that could
    contradict it with no stated precedence."""
    override = load_prompt("director", "generation_only")
    assert "camera" not in override.lower()


def test_override_block_gives_visual_style_cast_subject_mood_setting_not_medium():
    """illustrated_faceless.md §4.9 / P-IF-F1-fixes: measured live (project
    7df10f6c) that the Director wrote `visual_style` containing "hand-
    painted digital gouache and pencil textures" for a risograph project -
    two contradictory world descriptions in one request. The override must
    now say `visual_style` owns cast/subject/mood/setting and must NOT
    describe medium/palette/technique, which belong to the named style."""
    override = load_prompt("director", "generation_only")
    lower = override.lower()
    assert "cast" in lower
    assert "subject" in lower
    assert "mood" in lower
    assert "setting" in lower
    assert "medium" in lower
    assert "palette" in lower
    assert "technique" in lower
    # The measured regression itself, named so a future editor understands
    # why this rule exists.
    assert "gouache" in lower


def test_override_block_asks_for_a_recurring_character_figure_block():
    """illustrated_faceless.md F1-fixes, fix 1: a real render (project
    7df10f6c-e6b9-4275-b88a-7f07d0178011) showed the same named character
    ("Ji-ho") rendered as a different person in different shots, because
    nothing carried a fixed description to every Shot Planner call. The
    Director must be told to put a figure block in `visual_style` when the
    script has a recurring character - build, hair, skin tone, signature
    garment/object - grounded in the script, never invented."""
    override = load_prompt("director", "generation_only")
    lower = override.lower()
    assert "figure block" in lower
    assert "recurring" in lower
    assert "build" in lower
    assert "hair" in lower
    assert "skin tone" in lower
    # Must not invent a character the script doesn't have.
    assert "never invent a character" in lower


def test_no_director_styles_directory_was_created():
    """The brief's central instruction: this is ONE block keyed on picture
    path, not a per-style-name fragment under a new `director_styles/`
    directory - that would need duplicating for every future generation-
    only world, exactly the duplication P-IF-F1-review was dispatched to
    remove one level down."""
    from app.prompts.loader import _PROMPTS_ROOT

    assert not (_PROMPTS_ROOT / "director_styles").exists()
