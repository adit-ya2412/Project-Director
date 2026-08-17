"""Render fingerprint (M8 step 6, I5 - "rendering is a pure function").

Same fingerprint means the exact same inputs would produce the exact
same output bytes, so a render whose fingerprint matches one already on
disk is skipped entirely and the existing file is reused - this is how
I5 gets DEMONSTRATED (an actual before/after-byte comparison exists, see
tests/integration/test_render_determinism.py), not merely asserted in a
docstring.

Every genuine input to the pixels/samples that end up in the final file
is included: the canonical Timeline content (scenes, shots, camera,
transitions - everything `render_timeline` reads), every visual asset's
own content hash (not its path - two assets at different paths with
identical bytes must fingerprint the same), the narration audio actually
muxed in (if any), the music track actually muxed in (if any), the
render settings that actually affect the output pixels (width, height,
fps, pixel format - NOT `ffmpeg_binary`/`ffprobe_binary`, which are just
executable paths on this machine, not inputs to the encode), the audio
mix settings that actually affect the output SAMPLES (`music_bed_gain_db`/
`music_duck_gain_db` - read straight from config at mux time by
`app/renderer/music.py::mux_music`, never from the Timeline, so nothing
else here would ever catch a change to them), and the installed ffmpeg's
own version (a version bump can change encoder behaviour even given
byte-identical inputs, so it must invalidate old cache entries rather
than silently serving a render made by a different binary).

**R2 (2026-08-16): the mix gains were missing entirely, and it cost
real money.** `music_bed_gain_db`/`music_duck_gain_db` are read from
config at mux time (see `RenderStep.render_video`'s call into
`mux_music`) exactly like every other render setting above, but were
never part of this function's payload - so raising the bed gain and
re-rendering to listen returned the OLD, cached bytes at the OLD
(quieter) gain, with no re-encode and no error. The two live-testing
sessions this happened in only surfaced the bug at all because the
previous `final.mp4` had separately been deleted, so the cache lookup
missed on the absent file rather than on the fingerprint - the
fingerprint match itself was silent and wrong. Fixed by adding both
values to the payload below, unconditionally, the same way
`music_content_hash` is always present (as `None` when there is no
music) rather than only when relevant - I5's promise is "same
fingerprint -> provably identical output", so a value that CAN affect
output must be hashed even on a render where it happens not to (no
music selected, so the gains are moot for that particular file): the
cost of that is a possible false MISS on an unrelated config change,
never a false HIT, which is exactly the tolerance this module's own
closing paragraph already accepts for `music_plan`'s other fields. This
invalidates every fingerprint computed before this fix - correct and
harmless, since a cache MISS only ever means "render for real", not
"produce wrong output".

**Captions (2026-08-17), following the R2 pattern exactly.**
`burn_captions`/`caption_font_hash`/`cue_list_hash` are the same shape of
gap R2 fixed: `burn_captions`/`caption_font` are read from config at the
same point `music_bed_gain_db`/`music_duck_gain_db` are (see
`RenderStep.render_video`), and the actual cue text/timing depends on the
Timeline's narration content in a way this function cannot derive from
`timeline`/`narration_content_hashes` alone (those hash the AUDIO, not
the derived cue list - a segmentation-rule change or a burn on/off
toggle changes zero bytes of either). All three are present
unconditionally, `caption_font_hash`/`cue_list_hash` as `None` when
`burn_captions` is `False`, mirroring `music_content_hash`'s own "always
present, `None` when moot" rule - a caption-off render and a caption-on
render of the identical Timeline must never collide on one cache entry
(docs/14_Captions_Plan.md §6/§8.5).

Bookkeeping fields (`version`, `parent_version`, `produced_by`, `status`,
`created_at`, `timeline_id`, `project_id`, `schema_version`) are
EXCLUDED from the hashed Timeline content - the same set
`TimelineService`'s own additive-only check already treats as
non-content (`_BOOKKEEPING_FIELDS`, `app/timeline/service.py`), for the
identical reason: none of them affect a single rendered pixel. Without
this, two projects with byte-for-byte identical scenes, creative
context, and music plan - a very real case for this codebase's own
test-fixture-driven development, where the same script gets re-planned
into a fresh project repeatedly - would never fingerprint the same,
purely because `project_id`/`timeline_id`/`version` differ. Excluding
them is what makes cross-project reuse possible at all, not just same-
project resume - and it can never cause a false HIT, since none of the
excluded fields can change what `render_timeline` actually draws.

Everything else is deliberately conservative: `music_plan`'s own
selection-input fields (mood, tempo, search_terms, licence_requirements)
are hashed too, even though only `selected_track.content_hash` (passed
separately as `music_content_hash`, sourced with the OTHER real media
inputs below) actually reaches the output bytes. That is a missed cache
opportunity, never a wrong one: I5's promise is "same fingerprint ->
provably identical output", not "maximally aggressive caching", and a
false MISS is safe where a false HIT would silently serve stale video.
"""

import asyncio
import hashlib
import json

from app.core.errors import PermanentError
from app.renderer.slideshow import RenderSettings
from app.schemas.timeline import Timeline

# Mirrors `app.timeline.service._BOOKKEEPING_FIELDS` exactly (kept as its
# own local copy rather than an import, to avoid a renderer -> timeline
# peer-module dependency neither side otherwise needs) - fields the
# TimelineService itself stamps on every write, describing WHICH version
# this is, never planning/rendering content.
_TIMELINE_BOOKKEEPING_FIELDS = frozenset(
    {
        "schema_version",
        "timeline_id",
        "project_id",
        "version",
        "parent_version",
        "produced_by",
        "status",
        "created_at",
    }
)


async def get_ffmpeg_version(ffmpeg_binary: str) -> str:
    """The first line of `ffmpeg -version` (e.g. "ffmpeg version
    9.0-full_build-www.gyan.dev Copyright ...") - enough to distinguish
    genuinely different builds without hashing the entire, very long
    configuration banner."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg_binary,
        "-version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise PermanentError(f"{ffmpeg_binary} -version failed: {stderr.decode(errors='replace')}")
    first_line = stdout.decode(errors="replace").splitlines()[0] if stdout else ""
    return first_line.strip()


def _canonical_json(value: object) -> str:
    """Sorted keys, no incidental whitespace - the same dict must always
    serialise to the same bytes regardless of construction order (I5:
    "no unordered set/dict iteration when building" anything the output
    depends on)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_render_fingerprint(
    *,
    timeline: Timeline,
    asset_content_hashes: list[str],
    narration_content_hashes: list[str],
    music_content_hash: str | None,
    render_settings: RenderSettings,
    music_bed_gain_db: float,
    music_duck_gain_db: float,
    burn_captions: bool,
    caption_font_hash: str | None,
    cue_list_hash: str | None,
    ffmpeg_version: str,
) -> str:
    timeline_document = timeline.model_dump(mode="json")
    content_only = {
        k: v for k, v in timeline_document.items() if k not in _TIMELINE_BOOKKEEPING_FIELDS
    }
    payload = {
        "timeline": content_only,
        # Sorted, never trusted in caller-supplied order (I5) - two
        # equivalent renders whose bindings merely got resolved in a
        # different sequence must still fingerprint identically.
        "asset_content_hashes": sorted(asset_content_hashes),
        "narration_content_hashes": sorted(narration_content_hashes),
        "music_content_hash": music_content_hash,
        "render_settings": {
            "width": render_settings.width,
            "height": render_settings.height,
            "fps": render_settings.fps,
            "pixel_format": render_settings.pixel_format,
        },
        # R2 (2026-08-16): read from config at mux time
        # (`app/renderer/music.py::mux_music`), never from the Timeline -
        # the only two render inputs that used to have nowhere to be
        # caught by this function at all. Present unconditionally, same
        # as `music_content_hash` above, even on a render with no music
        # selected (where they happen not to affect this particular
        # file's bytes) - see this module's own docstring for why that
        # is a deliberately conservative choice, not an oversight.
        "music_bed_gain_db": music_bed_gain_db,
        "music_duck_gain_db": music_duck_gain_db,
        # Captions (2026-08-17), same unconditional-presence rule as the
        # gains above - see this module's own docstring.
        "burn_captions": burn_captions,
        "caption_font_hash": caption_font_hash,
        "cue_list_hash": cue_list_hash,
        "ffmpeg_version": ffmpeg_version,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
