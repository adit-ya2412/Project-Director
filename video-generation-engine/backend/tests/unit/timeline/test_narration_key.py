"""Writer and reader must agree on a scene's narration cache key.

The bug this guards (2026-09-17): `tone` was added to
`compute_narration_content_hash` and only `NarrationStep` was updated.
Rows were written under the with-tone key and looked up by `RenderStep`
under the without-tone key, so a correctly synthesised scene rendered as
"no narration row exists ... cannot mux audio that was never persisted".

Note what the existing tests did NOT cover, because it is the whole
lesson: there was a test proving tone changes the hash, and an
integration test proving a tone change re-synthesises. Both exercised the
WRITER. Nothing asserted that the reader computes the same key - which is
the only property a cache actually needs.
"""

from pathlib import Path

import pytest

from app.core.config import settings
from app.providers.elevenlabs import compute_narration_content_hash
from app.schemas.timeline import Scene
from app.timeline.narration_key import narration_content_hash_for_scene

_KW = {"voice_id": "v1", "speed": 1.0, "language_code": "hi"}


def _scene(tone: str | None) -> Scene:
    return Scene(
        id="sc_01",
        order=0,
        title="t",
        narration_text="2001 का साल।",
        duration_s=1.0,
        narration_tone=tone,
    )


def test_tone_reaches_the_key():
    assert narration_content_hash_for_scene(
        _scene("excited"), **_KW
    ) != narration_content_hash_for_scene(_scene(None), **_KW)


def test_an_untoned_scene_keeps_the_pre_tone_key():
    """Every row synthesised before this feature existed must stay a cache
    hit, or adding tone silently re-bills every prior project."""
    scene = _scene(None)
    assert narration_content_hash_for_scene(scene, **_KW) == compute_narration_content_hash(
        text=scene.narration_text,
        voice_id="v1",
        model=settings.elevenlabs_model,
        output_format=settings.elevenlabs_output_format,
        speed=1.0,
        language_code="hi",
    )


@pytest.mark.parametrize("tone", [None, "excited", "whispers"])
def test_the_key_is_stable_for_the_same_scene(tone):
    assert narration_content_hash_for_scene(
        _scene(tone), **_KW
    ) == narration_content_hash_for_scene(_scene(tone), **_KW)


def test_no_call_site_computes_the_key_itself():
    """The structural guard, and the one that would actually have caught
    the bug. Three modules assembled this key by hand from seven fields;
    a field added to the hash reached one of them. They must all go
    through `narration_key`, so that adding an eighth input is one line
    rather than a hunt.
    """
    root = Path(__file__).resolve().parents[3] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "narration_key.py" or path.parts[-2:] == ("providers", "elevenlabs.py"):
            continue
        if path.name == "elevenlabs.py":
            continue  # defines it
        text = path.read_text(encoding="utf-8")
        # A bare mention in a docstring or comment is fine; a CALL is not.
        if "compute_narration_content_hash(" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], (
        "these modules call compute_narration_content_hash directly instead of "
        f"narration_key.narration_content_hash_for_scene: {offenders}. That is exactly "
        "how the writer and reader drifted apart."
    )
