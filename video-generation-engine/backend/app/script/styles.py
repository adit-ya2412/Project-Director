"""Style pacing bands (motion_new_styles_and_long_form_videos.md §3.5.2,
decided 2026-08-17): a small, standalone registry the feasibility check
(`preflight.py`) reads. Track B (2026-08-17) extends this same registry
- `Timeline.metadata.render_style` and the real enforcement points
(`app/workflow/steps/generate_timeline.py`, `app/planners/shot/
planner.py`) now read `resolve_constraint_bundle` below - rather than
duplicating a second copy of these numbers.

Only three styles ship in v1 (plan §2.8: "three presets, not eight" -
every style is a behaviour four planners can regress against).
"""

import math
from dataclasses import dataclass
from enum import StrEnum

from app.core.config import settings

# A fast style's dead-stop ceiling is expressed as a multiple of its own
# target shot duration, not a flat constant - a style with a slower
# target should tolerate a proportionally longer outlier fragment before
# it reads as a dead stop. 2x is a starting point, not a measured
# constant (unlike the chars/sec figures in Settings, no real long
# fragment has been rendered against this ceiling yet - see the plan's
# Q5, "target pacing bands per style... blocked on calibration data").
_DEAD_STOP_CEILING_MULTIPLIER = 2.0


class PicturePath(StrEnum):
    """Where a style's shots get their picture from (docs/plans/
    illustrated_faceless.md §2.1/§3.2, F1). `RETRIEVAL_LADDER` is every
    style's behaviour before F1: the Asset Planner picks a `strategy`
    and `fallback_chain` that may search before it generates.
    `GENERATION_ONLY` means this style's pictures are ALWAYS AI-
    generated - see `resolve_picture_path`'s own docstring for how that
    is enforced (in code, after the Asset Planner returns, never by
    asking the Asset Planner to "always generate" in its prompt)."""

    RETRIEVAL_LADDER = "retrieval_ladder"
    GENERATION_ONLY = "generation_only"


@dataclass(frozen=True)
class StylePacingBand:
    """One style's feasibility inputs (plan §3.1, §3.5.2).

    `target_shot_duration_s=None` means this style has no pacing FLOOR
    to check at all - true of every style slower than the fastest
    physically reachable pace (plan §3.1's asymmetry: a script can always
    be cut SLOWER by merging fragments, never faster than one fragment
    per shot, so only fast styles can genuinely be infeasible).
    `max_fragment_duration_s=None` follows the same reasoning for the
    per-shot "dead stop" ceiling (plan §2.5.1) - both are computed from
    `target_shot_duration_s` when it is set, never supplied separately,
    so the two numbers can never drift apart for one style.
    `max_shots_override=None` means "use `settings.max_shots_per_project`
    directly" - only a style whose target pace needs materially more
    shots at the standard duration cap (`retention_fast`) overrides it.
    `min_shot_duration_s_override` follows the same "None = use the flat
    setting" shape, for the planning-time floor a fast style needs
    lowered (plan §2.5 Route 2, §4.2 - `narration_locked` already exempts
    MEASURED durations from this bound regardless, so lowering it only
    affects the Shot Planner's pre-narration estimate, never real,
    reconciled shot lengths).

    `narration_speed` is the narration speaking-rate multiplier for this
    style (parent plan §2.1 / R8) - applied via ffmpeg `atempo`
    (`app/renderer/narration_tempo.py`, 2026-08-24), not an ElevenLabs
    request parameter (eleven_v3's own `voice_settings.speed` is a
    documented no-op). Default 1.0 keeps the pre-R8 four-value
    narration cache key. `retention_fast` overrides it (1.4×, bumped
    from 1.2× the same day v3 exposed how much v3's own natural pacing
    varies call to call - see `providers/elevenlabs.py`'s `_SPEED_MAX`
    comment for the live numbers); `archival_montage` overrides it to
    1.25× (its own field comment below has the Hinglish-degradation
    warning); `illustrated_risograph` overrides it to 1.15×
    (illustrated_faceless.md P-IF-F1-fixes, the conservative end of that
    same Hinglish-safe band) — speed is a voice lever that matches
    delivery to cutting, not a pacing lever that changes the
    voice. Hashed into `compute_narration_content_hash`.

    `music_bed_gain_db` / `music_duck_gain_db` are None to mean "use
    `settings.*`" (parent plan §5.2 / leftover item 5). Archival keeps
    the measured mix. Fast-cut and stillness override. `0.0` is a
    legitimate value — resolve with `is not None`, never `or`.

    `whoosh_enabled` is the per-style WHOOSH SFX gate (analysis.md
    decisions 5 + 5a, 2026-08-24): only `retention_fast` turns the layer
    off — its punch-in density made one clip play ~100 times per reel
    (analysis.md A4/D3); archival and stillness keep their occasional
    whooshes. A plain bool defaulting True (the historical behaviour),
    not Optional-with-settings-fallback: there is no settings-level
    master switch behind it. Read through `resolve_sfx_whoosh_enabled`,
    never directly from the band at use sites.

    `max_shot_duration_s_override` is the Shot Planner's real validation
    bound - a SEPARATE number from `max_fragment_duration_s` below, fixed
    2026-08-18 (motion_new_styles_and_long_form_videos.md §13.7, "R7").
    Before this field existed, `resolve_constraint_bundle` read
    `max_fragment_duration_s` for this purpose - but that property is a
    pre-flight DIAGNOSTIC (the §2.5.1 dead-stop ceiling for a single
    narration FRAGMENT, derived from `_DEAD_STOP_CEILING_MULTIPLIER`,
    which is explicitly uncalibrated - see that constant's own comment),
    not a planning bound. Sharing one number meant Q5's still-open
    calibration of the diagnostic would have silently retuned a real
    planning constraint the moment someone adjusted the multiplier. The
    two numbers happen to be equal for `retention_fast` today (3.5), but
    are now two independent fields that merely agree, not one field
    serving two purposes.
    """

    name: str
    target_shot_duration_s: float | None
    max_shots_override: int | None
    min_shot_duration_s_override: float | None = None
    max_shot_duration_s_override: float | None = None
    narration_speed: float = 1.0
    music_bed_gain_db: float | None = None
    music_duck_gain_db: float | None = None
    # Decisions 5 + 5a (analysis.md, 2026-08-24): per-style WHOOSH gate.
    # See the class docstring paragraph above for why this is a plain
    # bool rather than the Optional shape the numeric fields use.
    whoosh_enabled: bool = True
    # A15 (long_form_direction.md, 2026-09-02): the sibling gate for the
    # TRANSITION layer. `False` (today's behaviour) fires a swoosh on
    # every non-cut transition; `True` restricts it to the transitions the
    # base prompt itself calls "a genuinely deliberate structural beat" -
    # `fadeblack`, `wipeleft` and the three `glitch_*` - and leaves plain
    # `dissolve` silent.
    #
    # Measured on the first finished long-form video (77 shots,
    # documentary_archival): 45 of 77 shots fired a transition swoosh,
    # because that style dissolves heavily, all at the flat
    # `sfx_gain_db = -8.0` - 10 dB LOUDER than its diegetic cues. The user
    # heard it as "the woosh" and asked for control. 45-of-77 is texture,
    # not punctuation. Ear-signed 2026-09-02 against a rendered A/B
    # (`tmp/sfx-a15/`, 45 transitions vs 5).
    #
    # A plain bool for the same reason `whoosh_enabled` is: this is a
    # behaviour switch, not a level with a settings-level default behind
    # it. Read through `resolve_transition_sfx_structural_only`.
    transition_sfx_structural_only: bool = False
    # None -> settings.render_width/height. `is not None`, never `or`
    # (same rule as music gains). Format rides render_style, frozen at
    # planning start — never grade_style (§19).
    render_width: int | None = None
    render_height: int | None = None
    # F1 (illustrated_faceless.md §2.1/§3.2), 2026-09-04: a plain enum
    # defaulting to `RETRIEVAL_LADDER` - the same "additive default,
    # existing styles never move" shape as `whoosh_enabled` and
    # `transition_sfx_structural_only` above, not the Optional-with-
    # settings-fallback shape the numeric fields use, because there is
    # no settings-level master switch behind it either. Read through
    # `resolve_picture_path`, never directly from the band at a use
    # site - same R1 lesson `resolve_sfx_whoosh_enabled`'s own docstring
    # cites.
    picture_path: PicturePath = PicturePath.RETRIEVAL_LADDER

    @property
    def max_fragment_duration_s(self) -> float | None:
        """Pre-flight ceiling ONLY (plan §2.5.1) - the ceiling a single
        narration fragment must not exceed before it reads as a dead
        stop, used by `preflight.py::check_feasibility`. NOT the Shot
        Planner's validation bound - see `max_shot_duration_s_override`'s
        own docstring for why those stopped being the same field (R7)."""
        if self.target_shot_duration_s is None:
            return None
        return self.target_shot_duration_s * _DEAD_STOP_CEILING_MULTIPLIER


# Registry, keyed by the style name `Timeline.metadata.render_style` also
# uses (plan §2.3) - one vocabulary, not two.
STYLE_PACING_BANDS: dict[str, StylePacingBand] = {
    "documentary_archival": StylePacingBand(
        name="documentary_archival",
        # A15: long-form dissolves heavily; see the field comment.
        transition_sfx_structural_only=True,
        target_shot_duration_s=None,
        max_shots_override=None,
        # §19.7: 1280×720, the transpose of today's pixel count.
        render_width=1280,
        render_height=720,
    ),
    "retention_fast": StylePacingBand(
        # 90s / 1.75s/shot =~ 51 shots; budgeted to ~58 for headroom
        # (plan §4.2's "budget ~55-60"). Floor lowered to 0.8s (§2.5
        # Route 2) - a planning-time estimate only, per the docstring
        # above. `max_shot_duration_s_override=3.5` matches
        # `max_fragment_duration_s`'s current value (1.75 * 2.0) - same
        # number today, independent field since R7 (see StylePacingBand's
        # own docstring for why sharing one was the bug).
        name="retention_fast",
        target_shot_duration_s=1.75,
        max_shots_override=58,
        min_shot_duration_s_override=0.8,
        max_shot_duration_s_override=3.5,
        narration_speed=1.4,
        # §5.2 set these as offsets from the measured archival mix
        # (-14 / -20), explicitly "not a new listening pass".
        # ⚠ EAR-SIGNED 2026-08-29 (output_quality_pass.md §15.1): the duck
        # went -14 -> -18. Once the pause detector actually worked, a 4 dB
        # duck depth left the bed nothing to swell back into - the user's
        # verdict on the fixed envelope at 4 dB was "works, but not much
        # noticeable change". Four depths were rendered on real narration
        # and compared by ear: 4 dB (too shallow), 8 dB (chosen), 12 dB
        # and 14 dB (both "start to feel weird" - the music reads as
        # absent under the voice rather than pushed back).
        # The bed stays -10: in A/B/C the pause level is identical, so
        # what the ear is judging is how far the music DROPS under speech,
        # not how loud it returns.
        music_bed_gain_db=-10.0,
        music_duck_gain_db=-18.0,
        # Decisions 5 + 5a (analysis.md, 2026-08-24): the WHOOSH layer is
        # OFF for this style - two punch-ins per ~1.75s shot meant one
        # clip played ~100 times per reel (A4/D3). Stinger and transition
        # layers are unaffected (D3).
        whoosh_enabled=False,
        render_width=720,
        render_height=1280,
    ),
    "archival_montage": StylePacingBand(
        # Feature B (style_extensions.md §4.3, decided 2026-08-25):
        # harder cutting than documentary_archival, full-frame text cards
        # leaned on more (via the Shot Planner fragment +
        # ShotPlanOutput.text_card), music more upfront than archival.
        #
        # EVERY number below is a reasoned starting point interpolated
        # from the two neighbouring styles' shipped values - NOT a
        # measured constant, the same epistemic status as
        # `_DEAD_STOP_CEILING_MULTIPLIER` above. Recalibrate all six
        # after a real listening/viewing pass (§4.3).
        name="archival_montage",
        # 90s / 2.25s ≈ 40 shots; budgeted to ~46 for headroom, the
        # same ~1.14x ratio retention_fast used (58/51).
        target_shot_duration_s=2.25,
        max_shots_override=46,
        min_shot_duration_s_override=1.2,
        max_shot_duration_s_override=4.5,  # target * 2.0, matching the
        # dead-stop ceiling shape (R7: independent field that merely
        # agrees with max_fragment_duration_s = 2.25 * 2.0 today).
        # 1.25, raised from 1.15 on 2026-08-27 — still below
        # retention_fast's 1.4x, and the TOP of the ~1.15-1.25x practical
        # ceiling the parent plan cites (past that ElevenLabs prosody
        # degrades).
        #
        # Measured cause (project 606f393e, "OSHO the legend", 36
        # fragments): at the time, the narration duration cap was
        # `(n_fragments/31) * max_video_duration_s`, which for 36
        # fragments was 104.5s — algebraically a RATE limit of 2.903
        # s/fragment, not a length limit. At 1.15x, three of four
        # candidate voices overshot it (by 0.04s, 6.7s and 13.5s); at
        # 1.25x, three of the four clear it. Raising the speed keeps the
        # reel ~102s instead of letting the cap rise and the video
        # sprawl past 120s.
        #
        # ⚠ SUPERSEDED 2026-09-01 (long_form_direction.md §3 A9): that
        # rate-limit formula was the SHORT-FORM-density bug A9 fixed - it
        # capped every style at ~2.9s/fragment regardless of how slow the
        # style actually runs. `resolve_constraint_bundle` now bounds
        # duration by shot CAPACITY (`shots_available *
        # max_shot_duration_s`) instead. The 104.5s figure above is
        # preserved as the historical reason this project's speed was
        # bumped, not as a description of the current formula.
        #
        # ⚠ Hinglish (this project's language_code=hi) is called out in
        # the parent plan as likely to degrade EARLIER and differently
        # than English at a given speed. 1.25 is the documented ceiling,
        # not a safe default — listen before trusting it, and drop back
        # to 1.15 (accepting a slower voice) if prosody suffers.
        #
        # Speed is in `compute_narration_content_hash`, so changing it
        # invalidates every cached narration for this style.
        narration_speed=1.25,
        music_bed_gain_db=-11.0,  # between archival's -14 and
        music_duck_gain_db=-15.0,  # retention_fast's -10/-14: more
        # upfront than archival, leaning toward retention_fast's mix
        # since the pace decision leans that way too (§4.3).
        # whoosh OFF, 2026-08-27 — measured, replacing the assumption
        # this line used to carry ("archival_montage is not the dense-cut
        # style whoosh was disabled for", written when the style shipped
        # and never checked against a real run).
        #
        # Real run d3a4d00d (75s, 39 shots): 9 punch_in shots x 2 punches
        # = 18 whoosh events, inside a total SFX layer of ~41 events —
        # one every 1.8s. That IS the density problem analysis.md
        # decision 5/5a disabled whoosh for on retention_fast; this style
        # simply did not exist when that decision was taken, so it
        # inherited the default rather than the reasoning.
        #
        # Note this is a RENDER-time gate (resolved from the style in
        # render.py, hashed into the fingerprint), not a planning
        # decision — flipping it re-renders existing projects correctly
        # rather than needing a re-plan.
        whoosh_enabled=False,
        render_width=720,  # 9:16, decided 2026-08-25 (§4.6) - this
        render_height=1280,  # plan originated from a "styles for reels" ask.
    ),
    "stillness": StylePacingBand(
        name="stillness",
        # A15: long-form dissolves heavily; see the field comment.
        transition_sfx_structural_only=True,
        target_shot_duration_s=None,
        max_shots_override=None,
        # §5.2: near-absent. 8 dB quieter bed than the measured mix.
        music_bed_gain_db=-22.0,
        music_duck_gain_db=-28.0,
        # Default 16:9 (long contemplative). `frame_aspect="9:16"` on the
        # project opts into a vertical Ken Burns reel (§19.12).
        render_width=1280,
        render_height=720,
    ),
    # F1 (docs/plans/illustrated_faceless.md §2.1), 2026-09-04: the
    # illustrated-format opt-in, stills only ("no motion, no layers" -
    # those are F2-F5).
    #
    # ⚠ COLLAPSED from two rows (`illustrated_risograph_vertical` /
    # `_horizontal`) to one, follow-up to F1's review (2026-09-04): both
    # were the SAME world (W2 risograph, §1.6), the SAME prompt fragment
    # content, and differed only in canvas plus one framing bullet - the
    # W2 world token itself lived in two files, which is exactly
    # long_form_direction.md §4.3's named lesson, "two styles, one base
    # table - do not fix this twice" (there, A1/A4 sharing a base camera
    # table; here, two fragment files sharing a world token no shared-
    # include mechanism exists for). One row now, default 9:16 (the
    # `_vertical` canvas - the primary edit per §1's own framing), with
    # `frame_aspect="16:9"` opting into the other canvas exactly the way
    # `stillness` already opts into ITS other canvas below - see
    # `style_accepts_frame_aspect`. §4.2/§6 Q5's "9:16 and 16:9 are
    # different EDITS, planned as separate projects" is UNCHANGED by this
    # collapse: format still rides `render_style`, frozen at planning
    # start, so a project still ends up at exactly one canvas - the
    # collapse only changes how many REGISTRY ROWS express "which style,
    # which canvas", not the one-project-one-canvas rule itself (§6 Q5
    # note added the same day this collapse landed, so a later reader
    # does not mistake the two for having ever been in tension).
    #
    # No `target_shot_duration_s`/`max_shots_override`/music-gain/whoosh
    # overrides: none of §1's four probes measured a pacing, mix, or SFX
    # difference for this format, so every one of those stays at
    # documentary_archival's inert default rather than guessing at a
    # number nobody watched. `picture_path=GENERATION_ONLY` is the one
    # behaviour this format actually changes structurally - see
    # `resolve_picture_path`.
    #
    # `world` is deliberately NOT a per-project field here (§6 Q2 already
    # settled `world` as per-project for FUTURE multi-world support, but
    # nothing in this collapse needs it yet): one style row per world
    # means two or three worlds is two or three fragments with zero
    # duplication between them, exactly like `documentary_archival` and
    # `stillness` already coexist as separate rows/fragments today. A
    # `world` field would only earn its cost once a single project needs
    # to CHOOSE its world at runtime rather than the style choice already
    # implying it - not the case yet, so it is not built.
    "illustrated_risograph": StylePacingBand(
        name="illustrated_risograph",
        target_shot_duration_s=None,
        max_shots_override=None,
        picture_path=PicturePath.GENERATION_ONLY,
        # P-IF-F1-fixes (2026-09-04), fix 3: measured on a real render
        # (project 7df10f6c) as too slow at the 1.0 default. This
        # project is `language_code=hi` (Hinglish), and
        # `archival_montage`'s own narration_speed comment above states
        # Hinglish degrades EARLIER and differently than English at a
        # given speed, with 1.25 as the documented ceiling and an
        # explicit instruction to drop back to 1.15 if prosody suffers.
        # 1.15 is chosen here - the conservative end of that band, not
        # the ceiling - and is UN-EARED: nobody has listened to this
        # style at 1.15 yet, so it must be confirmed by ear on the next
        # render, same as archival_montage's own value was.
        # `retention_fast`'s 1.4 is a different style's punch-in pacing
        # decision, not a bound that applies here.
        #
        # Speed is hashed into `compute_narration_content_hash`
        # (narration_tempo.py) - changing it from the 1.0 default
        # invalidates every cached narration for this style, so the next
        # render of any illustrated_risograph project pays for TTS again
        # (single-digit cents at Ji-ho's ~30s length).
        narration_speed=1.15,
        render_width=720,
        render_height=1280,
    ),
}


def resolve_narration_speed(style: str | None) -> float:
    """Style-owned speaking rate (parent plan §2.1 / R8).

    Unknown / unset styles resolve to 1.0 — the ElevenLabs default and
    the pre-R8 cache key — the same fallback `resolve_constraint_bundle`
    uses for an unrecognised name.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        return 1.0
    return band.narration_speed


def resolve_sfx_whoosh_enabled(style: str | None) -> bool:
    """Style-owned WHOOSH SFX gate (analysis.md decisions 5 + 5a).

    Unknown style names resolve to True (there is no band to consult).
    An UNSET style resolves through `settings.default_render_style`'s
    band - it inherits whatever the default style says rather than being
    pinned open here, so it is True today only because that default is
    `documentary_archival` (config.py). Same fallback shape
    `resolve_narration_speed` uses for an unrecognised name.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        return True
    return band.whoosh_enabled


def resolve_transition_sfx_structural_only(style: str | None) -> bool:
    """Style-owned TRANSITION SFX gate (A15, long_form_direction.md).

    `True` means only structural transitions (`fadeblack`, `wipeleft`,
    `glitch_*`) fire a swoosh; a plain `dissolve` stays silent.

    Unknown style names resolve to False - today's behaviour, so an
    unrecognised name never silently loses a layer. An UNSET style
    resolves through `settings.default_render_style`'s band, exactly like
    `resolve_sfx_whoosh_enabled`, so it inherits the default style's
    answer rather than being pinned here.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        return False
    return band.transition_sfx_structural_only


def resolve_picture_path(style: str | None) -> PicturePath:
    """Style-owned picture-acquisition path (illustrated_faceless.md
    §3.2, F1). `GENERATION_ONLY` means every shot in this style must be
    AI-generated - the Asset Planner's reuse-before-generate ladder
    never runs for it.

    **Why this is a resolver and not a prompt instruction:** verified
    2026-09-04, `app/planners/asset/planner.py::_build_user_content`
    sends the Asset Planner only the scene title and, per shot,
    `intent | framing | camera | prompt` - it never sees `render_style`
    at all, so there is no wording that could tell it to always
    generate. Telling it anyway (e.g. by leaking the instruction through
    the Shot Planner's `prompt` field) would usually work, and *usually*
    is the defect: this is a deterministic structural fact ("this
    project never retrieves"), and `app/planners/fragments.py`'s own
    module docstring is the standing lesson for why a deterministic fact
    is asked of code, never of a language model - "Models cannot count
    characters reliably - that is not a prompt-quality problem, and it
    is not a post-processing problem. It is the wrong thing to ask for."
    The same shape of mistake, one level out.

    So the real enforcement is not here - it is the caller in
    `app/workflow/steps/generate_timeline.py`, which overrides every
    shot's `asset_plan.strategy`/`fallback_chain`/`preferred_type` to
    generation-only AFTER the Asset Planner returns, once this resolver
    says to. This function is the single place that decision is made;
    every call site reads through it and none reads
    `band.picture_path` directly - the same R1 shape
    `resolve_sfx_whoosh_enabled` already uses ("a single function
    neither call site can bypass is what makes that true, not just
    making both agree today").

    Unknown style names resolve to `RETRIEVAL_LADDER` - there is no band
    to consult, and this is the OPPOSITE safe direction from
    `resolve_sfx_whoosh_enabled`'s True-for-unknown default: getting
    picture path wrong for a typo'd style would silently start
    generating (and billing for) every picture instead of silently
    dropping an SFX layer, so the unknown-name fallback here is the
    cheaper, more conservative behaviour rather than the historical one.
    An UNSET style resolves through `settings.default_render_style`'s
    band, exactly like the other resolve_* helpers in this module, so it
    inherits the default style's answer (today, `RETRIEVAL_LADDER` -
    `documentary_archival` has no override) rather than being pinned
    open or closed independently.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        return PicturePath.RETRIEVAL_LADDER
    return band.picture_path


@dataclass(frozen=True)
class MusicGains:
    """Resolved bed/duck mix for one style (parent plan §5.2)."""

    bed_gain_db: float
    duck_gain_db: float


def resolve_music_gains(style: str | None) -> MusicGains:
    """Style-owned music mix. None / unknown / archival fall through
    to `settings.music_*_gain_db` (the measured mix, leftover item 5).
    `0.0` is a real override — `is not None`, never `or`.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    bed = settings.music_bed_gain_db
    duck = settings.music_duck_gain_db
    if band is not None:
        if band.music_bed_gain_db is not None:
            bed = band.music_bed_gain_db
        if band.music_duck_gain_db is not None:
            duck = band.music_duck_gain_db
    return MusicGains(bed_gain_db=bed, duck_gain_db=duck)


@dataclass(frozen=True)
class RenderFormat:
    """Resolved canvas for one style (plan §19)."""

    width: int
    height: int

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height

    @property
    def aspect_ratio(self) -> str:
        return "16:9" if self.is_landscape else "9:16"


FRAME_ASPECTS = frozenset({"9:16", "16:9"})

# Styles that accept a `frame_aspect` override to opt into the OTHER
# canvas from their band's own default - `stillness` (16:9 default, 9:16
# opt-in Ken Burns reel, §19.12) and `illustrated_risograph` (9:16
# default, 16:9 opt-in, F1 collapse - illustrated_faceless.md §2.1/§6 Q5).
# A frozenset of names, not a field on `StylePacingBand`: which styles
# opt in is a small, rarely-changing fact about the mechanism itself, not
# a per-style tuning number every band author needs to see and set (the
# other band fields, like `render_width`, describe what the canvas IS;
# this describes whether the canvas is ALLOWED to flip). Read through
# `style_accepts_frame_aspect` everywhere - no call site compares a style
# name to a literal (the R1 shape `resolve_sfx_whoosh_enabled` already
# uses): `frame_aspect_error`, `resolve_render_format`, and both
# `app/api/projects.py` write paths (`create_project`, `set_render_style`)
# all read through the one function below.
_FRAME_ASPECT_OVERRIDE_STYLES = frozenset({"stillness", "illustrated_risograph"})


def style_accepts_frame_aspect(style: str | None) -> bool:
    """True if `style` accepts a `frame_aspect` override at all. The
    single source of truth `frame_aspect_error`, `resolve_render_format`,
    and the two API write paths all read through - see
    `_FRAME_ASPECT_OVERRIDE_STYLES`'s own comment for why this is a
    function over a frozenset rather than a per-band field, and why no
    call site should ever write `style == "stillness"` (or any other
    style name) itself."""
    return style in _FRAME_ASPECT_OVERRIDE_STYLES


def frame_aspect_error(style: str | None, frame_aspect: str | None) -> str | None:
    """None if legal. `frame_aspect` is only for styles that opt in - see
    `style_accepts_frame_aspect`."""
    if frame_aspect is None:
        return None
    if frame_aspect not in FRAME_ASPECTS:
        return f"unknown frame_aspect {frame_aspect!r} - use 9:16 or 16:9"
    if not style_accepts_frame_aspect(style):
        return (
            "frame_aspect is only settable when render_style opts in "
            f"({sorted(_FRAME_ASPECT_OVERRIDE_STYLES)})"
        )
    return None


def resolve_render_format(style: str | None, *, frame_aspect: str | None = None) -> RenderFormat:
    """Style-owned canvas. Unknown names use the default style's format
    (not raw settings). A style in `_FRAME_ASPECT_OVERRIDE_STYLES` swaps
    to the OTHER canvas when `frame_aspect` names the aspect that is NOT
    its band's own default - `stillness` defaults 16:9, opts into 9:16;
    `illustrated_risograph` defaults 9:16, opts into 16:9. Both are a
    transpose of the same band's width/height, not a second pair of
    numbers - so this stays correct for any future opt-in style without
    a new branch here, as long as its "other" canvas really is its own
    transpose (true of both styles today).
    """
    resolved = style if style in STYLE_PACING_BANDS else settings.default_render_style
    band = STYLE_PACING_BANDS[resolved]
    width = settings.render_width
    height = settings.render_height
    if band.render_width is not None:
        width = band.render_width
    if band.render_height is not None:
        height = band.render_height
    default_fmt = RenderFormat(width=width, height=height)
    if (
        style_accepts_frame_aspect(resolved)
        and frame_aspect is not None
        and frame_aspect != default_fmt.aspect_ratio
    ):
        return RenderFormat(width=default_fmt.height, height=default_fmt.width)
    return default_fmt


def resolve_draft_format(style: str | None, *, frame_aspect: str | None = None) -> RenderFormat:
    """Same aspect as the style, at the draft short-side (480)."""
    fmt = resolve_render_format(style, frame_aspect=frame_aspect)
    short, long = settings.draft_width, settings.draft_height
    if fmt.is_landscape:
        return RenderFormat(width=long, height=short)
    return RenderFormat(width=short, height=long)


def get_pacing_band(style: str) -> StylePacingBand:
    """Raises `KeyError` on an unknown style name - deliberately, not a
    silent fallback to some default band. An endpoint calling this
    translates the KeyError into a 400 naming the valid styles; guessing
    a band for a typo'd style name would produce a feasibility verdict
    that looks real but checks the wrong thing."""
    return STYLE_PACING_BANDS[style]


# Track C C1 §2.3: projected from the five short fixtures (plan §0).
# ~3.2 fragments/scene, ~0.9 shots/fragment. 31 fragments ≈ today's 90 s
# (that ratio used to also size the duration cap via `_N_AT_SHORT_CAP`,
# retired 2026-09-01 - long_form_direction.md §3 A9 - because it baked
# SHORT-FORM density into every style's duration ceiling; the shot/scene
# sizing below is unrelated to that bug and is untouched).
_FRAGS_PER_SCENE = 3.2
_SHOTS_PER_FRAG = 0.9
_SCENE_HEADROOM = 5
_SHOT_SCALE = 1.18  # 206 * 0.9 * 1.18 ≈ 220 at 10 min


@dataclass(frozen=True)
class ConstraintBundle:
    """The one resolved set of planning bounds (Track C C1, R1).

    Unpackable as the historical 3-tuple
    `(min_shot_duration_s, max_shot_duration_s, max_shots_per_project)`
    so existing call sites keep working. `max_scenes` and
    `max_video_duration_s` used to be read from flat settings beside
    this function — that is the R1 shape; they live here now.
    Track C C6 adds `budget_cap_cents` and `max_video_shots_per_project`
    the same way: length-aware, and `n_fragments=None` is today's 1000¢
    / 5 video shots.
    """

    min_shot_duration_s: float
    max_shot_duration_s: float
    max_shots_per_project: int
    max_scenes: int
    max_video_duration_s: float
    budget_cap_cents: int
    max_video_shots_per_project: int
    # illustrated_faceless.md §4.3/F2a: same sub-linear-in-length shape
    # as `max_video_shots_per_project` immediately above, over parallax
    # layer count rather than video-shot count. See
    # `resolve_constraint_bundle`'s own computation for the formula.
    max_parallax_layers_per_project: int

    def __iter__(self):
        yield self.min_shot_duration_s
        yield self.max_shot_duration_s
        yield self.max_shots_per_project


def resolve_constraint_bundle(
    style: str | None, *, n_fragments: int | None = None
) -> ConstraintBundle:
    """Length-aware, style-aware bounds for the real enforcement points.

    `style=None` and `n_fragments=None` (every Timeline predating both
    fields, and every caller that has not yet split the script) resolve
    to EXACTLY the numbers those flat `settings.*` reads always
    produced. Length sets the base (`max(today's cap, f(N))`); style
    multiplies the shot cap (retention_fast 58/40). Not "whichever is
    larger" — that silently drops one of the two (Track C §2.3).
    C6: budget scales linearly with the duration cap (90 s → 1000¢);
    the motion-shot cap scales with `sqrt(duration / 90 s)` so a
    10-minute video cannot spend the whole cap on ~130 motion shots.
    """
    band = STYLE_PACING_BANDS.get(style or settings.default_render_style)
    if band is None:
        band = STYLE_PACING_BANDS[settings.default_render_style]
    min_shot_duration_s = (
        band.min_shot_duration_s_override
        if band.min_shot_duration_s_override is not None
        else settings.min_shot_duration_s
    )
    max_shot_duration_s = (
        band.max_shot_duration_s_override
        if band.max_shot_duration_s_override is not None
        else settings.max_shot_duration_s
    )

    if n_fragments:
        max_scenes = max(
            settings.max_scenes, math.ceil(n_fragments / _FRAGS_PER_SCENE) + _SCENE_HEADROOM
        )
        shots_base = max(
            settings.max_shots_per_project,
            math.ceil(n_fragments * _SHOTS_PER_FRAG * _SHOT_SCALE),
        )
    else:
        max_scenes = settings.max_scenes
        shots_base = settings.max_shots_per_project

    # Length sets the base; style multiplies. retention_fast's 58 is
    # 58/40 of the 90 s cap; at 10 min that same ratio applies to the
    # length-scaled base, not "max(220, 58)".
    if band.max_shots_override is not None:
        style_mult = band.max_shots_override / settings.max_shots_per_project
        max_shots_per_project = math.ceil(shots_base * style_mult)
    else:
        max_shots_per_project = shots_base

    if n_fragments:
        # A9 (docs/plans/long_form_direction.md §3): bound duration by
        # what the shots can actually CARRY, not by short-form density
        # extrapolated to any length. The old formula
        # `(n_fragments / _N_AT_SHORT_CAP) * settings.max_video_duration_s`
        # encoded "a 90s short has ~31 fragments" - SHORT-FORM density -
        # and applied it to every length, so a documentary (which runs
        # slower per fragment by nature) hit this proxy long before any
        # real constraint. A shot may own a CONTIGUOUS RANGE of
        # fragments, so shots <= fragments; each shot is bounded by
        # `max_shot_duration_s` (the resolved, style-aware bound above,
        # not the flat setting). The product is therefore the true upper
        # bound on how much video this script's STRUCTURE can support.
        # Uses the final resolved `max_shots_per_project` (post style
        # multiplier), not `shots_base`, so the two numbers cannot
        # silently disagree.
        shots_available = min(max_shots_per_project, n_fragments)
        capacity_s = shots_available * max_shot_duration_s
        max_video_duration_s = min(
            settings.max_long_form_duration_s,
            max(settings.max_video_duration_s, capacity_s),
        )
    else:
        max_video_duration_s = settings.max_video_duration_s

    # C6: 90 s → project_budget_cap_cents (1000). 10 min → ~6667¢ (~$67).
    # ceil so a fractional second never silently drops a cent of room.
    budget_cap_cents = math.ceil(
        max_video_duration_s * settings.project_budget_cap_cents / settings.max_video_duration_s
    )
    # Sub-linear in length (D4): sqrt(6.67) × 5 ≈ 13 motion shots at
    # 10 min, not 5 × 6.67 ≈ 33, and nowhere near 130.
    duration_ratio = max_video_duration_s / settings.max_video_duration_s
    max_video_shots_per_project = max(
        settings.max_video_shots_per_project,
        math.ceil(settings.max_video_shots_per_project * math.sqrt(duration_ratio)),
    )
    # illustrated_faceless.md §4.3/F2a: identical sub-linear shape, over
    # `max_parallax_layers_per_project` instead of the video-shot cap -
    # a 10-minute project may reasonably want more total layers than a
    # 90s one, but not linearly more (D4's same reasoning: sqrt, not a
    # flat multiple).
    max_parallax_layers_per_project = max(
        settings.max_parallax_layers_per_project,
        math.ceil(settings.max_parallax_layers_per_project * math.sqrt(duration_ratio)),
    )

    return ConstraintBundle(
        min_shot_duration_s=min_shot_duration_s,
        max_shot_duration_s=max_shot_duration_s,
        max_shots_per_project=max_shots_per_project,
        max_scenes=max_scenes,
        max_video_duration_s=max_video_duration_s,
        budget_cap_cents=budget_cap_cents,
        max_video_shots_per_project=max_video_shots_per_project,
        max_parallax_layers_per_project=max_parallax_layers_per_project,
    )
