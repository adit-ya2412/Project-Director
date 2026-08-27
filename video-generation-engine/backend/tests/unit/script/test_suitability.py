"""prompt_fixes.md §3.1: suitability descriptions must cover every
registered style, and an unknown style must fail loudly rather than
feeding the model its own name as a description.

Pure - no DB, no LLM, `--noconftest`-safe.
"""

import pytest

from app.script.styles import STYLE_PACING_BANDS
from app.script.suitability import _STYLE_DESCRIPTIONS, _description_for


def test_style_descriptions_cover_every_pacing_band():
    """Style #5 fails this on the day it is added, rather than shipping
    a fabricated verdict because `.get(style, style)` papered over the
    miss (prompt_fixes.md §2.2 / §3.1)."""
    assert set(_STYLE_DESCRIPTIONS) == set(STYLE_PACING_BANDS)


def test_archival_montage_has_a_real_description_not_its_own_name():
    text = _description_for("archival_montage")
    assert text != "archival_montage"
    assert "text card" in text.lower() or "9:16" in text


@pytest.mark.parametrize("style", list(STYLE_PACING_BANDS))
def test_every_registered_style_resolves_to_a_description(style):
    text = _description_for(style)
    assert text.strip()
    assert text != style


def test_unknown_style_raises_instead_of_falling_back_to_the_name():
    with pytest.raises(KeyError, match="no suitability description"):
        _description_for("not_a_real_style")
