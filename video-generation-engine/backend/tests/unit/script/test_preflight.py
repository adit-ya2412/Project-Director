"""`app/script/preflight.py` (motion_new_styles_and_long_form_videos.md,
Track D) - pure arithmetic, no network, no model, no DB. Values below are
checked directly against `backend/tests/fixtures/m8_test_project.json`'s
real script and measured against the real splitter - not against this
module's own internal logic reproduced a second time.
"""

import json
from pathlib import Path

import pytest

from app.script.preflight import check_feasibility, estimate_duration_s
from app.script.styles import STYLE_PACING_BANDS

_FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "m8_test_project.json").read_text(
        encoding="utf-8"
    )
)
_SCRIPT = _FIXTURE["script"]


def test_feasibility_passes_for_a_style_with_no_pacing_floor():
    """documentary_archival has no `target_shot_duration_s` - plan
    §3.1's asymmetry: a slow style can always be reached by merging
    fragments, so nothing here can fail on pace."""
    result = check_feasibility(_SCRIPT, "documentary_archival")
    assert result.passed
    assert result.violations == []
    assert result.fragment_count == 13  # measured against the real splitter, 2026-08-17


def test_feasibility_fails_for_a_fast_style_on_a_slow_script():
    """The real fixture cannot reach retention_fast's pace - verified by
    hand against the real splitter before this test was written (D/N =
    3.54s vs a 1.75s target, longest fragment ~8.0s vs a 3.5s ceiling)."""
    result = check_feasibility(_SCRIPT, "retention_fast")
    assert not result.passed
    assert len(result.violations) == 2  # average pace AND the dead-stop ceiling


def test_unknown_style_raises_rather_than_silently_defaulting():
    """`get_pacing_band`'s own contract (styles.py) - a typo'd style name
    must never silently check against some default band."""
    with pytest.raises(KeyError):
        check_feasibility(_SCRIPT, "not_a_real_style")


def test_every_registered_style_has_a_derived_or_absent_ceiling():
    """`StylePacingBand.max_fragment_duration_s` is a computed property,
    never set independently - this is what makes the pace target and the
    dead-stop ceiling structurally unable to drift apart for one style."""
    for band in STYLE_PACING_BANDS.values():
        if band.target_shot_duration_s is None:
            assert band.max_fragment_duration_s is None
        else:
            assert band.max_fragment_duration_s == band.target_shot_duration_s * 2.0


def test_hindi_calibration_selected_for_a_mixed_devanagari_script():
    """Selection is by the SCRIPT'S OWN character composition, not a
    `language` field (preflight.py's own docstring: the real
    `hinglish_final_project` fixture's `language` field reads "en"
    despite being ~39% Devanagari) - constructed here directly rather
    than trusting fixture metadata."""
    mixed_script = "यह एक इतिहास है। " * 20  # well over the 15% non-ASCII threshold
    english_script = "This is a plain English sentence. " * 20

    mixed_duration = estimate_duration_s(mixed_script)
    english_duration = estimate_duration_s(english_script)

    # Same rough length; a lower chars/sec constant means a LONGER
    # estimated duration for the same character count.
    assert mixed_duration / len(mixed_script) > english_duration / len(english_script)


def test_total_duration_check_is_not_margin_widened():
    """Unlike the two style-pace checks, the video-length cap mirrors
    `Timeline._validate_structural_invariants`, which is exact - widening
    it here would let a script pass pre-flight that real planning is
    guaranteed to reject."""
    from app.core.config import settings

    # A script whose estimated duration sits JUST over the cap, not
    # comfortably past it - if a margin were (incorrectly) applied here,
    # this would still pass.
    chars_needed = int(settings.max_video_duration_s * settings.script_chars_per_second_en) + 50
    long_script = ("a" * chars_needed) + "."
    result = check_feasibility(long_script, "documentary_archival")
    assert not result.passed
    assert any("exceeds" in v for v in result.violations)
