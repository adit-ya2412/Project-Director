"""`app/workflow/steps/resolve_assets.py::styled_prompt` - pure string
logic, no ffmpeg/DB needed. The real collage failure this caps against
was found and verified against real Seedream generations during A8's
bake-off (motion_new_styles_and_long_form_videos.md, 2026-08-18) - see
that function's own docstring for the two rejected fix attempts and why
this one (a mechanical word cap) is what actually worked.
"""

from app.schemas.timeline import CreativeContext, Shot, ShotIntent
from app.script.styles import RenderFormat
from app.workflow.steps.resolve_assets import _MAX_VISUAL_STYLE_WORDS, styled_prompt


def _shot(prompt: str = "a coal mine") -> Shot:
    return Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, prompt=prompt)


def test_no_visual_style_leaves_the_prompt_untouched():
    assert styled_prompt(_shot(), CreativeContext()) == "a coal mine"


def test_a_short_visual_style_is_appended_in_full():
    cc = CreativeContext(visual_style="1940s archival, desaturated")
    assert styled_prompt(_shot(), cc) == "a coal mine, 1940s archival, desaturated"


def test_a_long_multi_era_visual_style_is_capped_to_the_first_n_words():
    """The real bake-off finding: `visual_style` describing a multi-part
    narrative arc ("...then...ending with...") made Seedream generate a
    multi-panel collage of the whole arc instead of one photograph of
    this one shot - reproduced here as a pure string assertion, not just
    a real API call, so a future edit can't silently widen the cap back
    out without a test noticing."""
    long_style = (
        "Archival industrial documentary: black-and-white WWII coal mines, "
        "hydrogenation and Fischer-Tropsch plant records, wartime fuel maps, then "
        "muted-color South African refinery and Sasol archive imagery, ending with "
        "contemporary energy infrastructure and emissions-aware coal imagery."
    )
    result = styled_prompt(_shot(), CreativeContext(visual_style=long_style))

    appended = result.removeprefix("a coal mine, ")
    assert len(appended.split()) == _MAX_VISUAL_STYLE_WORDS
    # The truncation must land BEFORE the narrative's own sequencing
    # words - if "then"/"ending with" ever appear in the capped output,
    # the cap is too generous and the collage failure mode is back.
    assert "then" not in appended
    assert "ending with" not in appended


def test_the_cap_is_a_word_count_not_a_character_count():
    """A word-boundary cap, not `text[:N]` - a character-count cap would
    cut mid-word and could still leave `visual_style`'s own last visible
    word truncated/garbled in the actual prompt sent to the model."""
    cc = CreativeContext(visual_style=" ".join(f"word{i}" for i in range(50)))
    result = styled_prompt(_shot(), cc)
    appended = result.removeprefix("a coal mine, ")
    words = appended.split()
    assert len(words) == _MAX_VISUAL_STYLE_WORDS
    assert words[-1] == f"word{_MAX_VISUAL_STYLE_WORDS - 1}"  # not a partial word


def test_landscape_frame_appends_a_composition_line():
    cc = CreativeContext(visual_style="archival")
    result = styled_prompt(
        _shot(), cc, frame=RenderFormat(width=1280, height=720)
    )
    assert result.endswith("Composed for a landscape 16:9 frame.")
    portrait = styled_prompt(
        _shot(), cc, frame=RenderFormat(width=720, height=1280)
    )
    assert "Composed for" not in portrait
