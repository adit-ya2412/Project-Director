"""The one place a scene's narration cache key is computed.

Exists because of a real failure (2026-09-17). `tone` was added to
`compute_narration_content_hash` for the eleven_v3 audio-tag feature and
only ONE of its three call sites was updated: `NarrationStep` wrote every
row under the with-tone key while `RenderStep` looked them up under the
without-tone key, so a correctly-synthesised, correctly-persisted scene
came back as

    timeline is produced_by=narration but no narration row exists for
    scene sc_01 (content_hash a82d3e23...) - cannot mux audio that was
    never persisted

The audio was on disk and in the database the whole time. Writer and
reader simply disagreed about the key.

The lesson is not "remember to pass tone". A cache key assembled from
seven fields at three call sites will drift again the next time a field
is added - the same way `speed` and `language_code` each had to be
threaded through by hand before it. So the assembly lives here, takes the
scene itself rather than its fields, and every call site asks this
function. Adding an eighth input means changing one line, not finding
three.

`tests/unit/timeline/test_narration_key.py` fails if a call site goes
back to calling `compute_narration_content_hash` directly.
"""

from __future__ import annotations

from app.core.config import settings
from app.providers.elevenlabs import compute_narration_content_hash
from app.schemas.timeline import Scene


def narration_content_hash_for_scene(
    scene: Scene,
    *,
    voice_id: str,
    speed: float,
    language_code: str | None,
) -> str:
    """The cache key for `scene`'s narration, as every caller must compute it.

    `voice_id`, `speed` and `language_code` stay parameters because they
    are resolved from the timeline's metadata with a settings fallback,
    and that resolution differs slightly per caller. Everything that
    comes off the scene itself - its text and its tone - is read here, so
    a caller cannot omit one by forgetting it exists.
    """
    return compute_narration_content_hash(
        text=scene.narration_text,
        voice_id=voice_id,
        model=settings.elevenlabs_model,
        output_format=settings.elevenlabs_output_format,
        speed=speed,
        language_code=language_code,
        tone=scene.narration_tone,
    )
