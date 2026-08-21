"""§19.1: default 720×1280 is omitted from the digest."""

import hashlib

from app.core.config import settings
from app.workflow.steps.resolve_assets import (
    _CACHE_KEY_BASELINE,
    generation_prompt_hash,
)


def test_default_canvas_matches_the_legacy_four_part_digest():
    prompt, model, seed = "a coal mine", "fal-seedream", "abc"
    legacy = hashlib.sha256(f"{prompt}|{model}|{seed}".encode()).hexdigest()
    assert (
        generation_prompt_hash(
            prompt,
            model,
            seed,
            width=settings.render_width,
            height=settings.render_height,
        )
        == legacy
    )


def test_non_default_canvas_is_in_the_digest():
    prompt, model, seed = "a coal mine", "fal-seedream", "abc"
    default = generation_prompt_hash(
        prompt, model, seed, width=720, height=1280
    )
    landscape = generation_prompt_hash(
        prompt, model, seed, width=1280, height=720
    )
    assert default != landscape


def test_omission_baseline_is_the_historical_720x1280_constant():
    """§19.12 required order: pin this before any settings/stillness
    format flip, so existing 720×1280 rows stay hits."""
    assert _CACHE_KEY_BASELINE == (720, 1280)
    omitted = generation_prompt_hash("p", "m", width=720, height=1280)
    suffixed = generation_prompt_hash("p", "m", width=1280, height=720)
    assert omitted != suffixed
