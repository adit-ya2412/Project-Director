"""Central application settings.

Every module that needs configuration imports `settings` from here.
Never call `os.getenv()` directly outside this file (Principle 13).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root, not cwd: pydantic-settings resolves a relative `env_file`
# against the process's current working directory, so ".env" silently
# resolves to nothing (all defaults, no error) whenever this app is
# invoked from anywhere but the repo root - e.g. `cd backend && alembic
# ...`, or a test runner launched from backend/. An absolute path removes
# the ambiguity entirely.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: str = "local"
    log_level: str = "INFO"
    log_format: str = "json"
    dry_run: bool = True

    # --- Storage ---
    storage_root: Path = Path("./storage")
    max_download_bytes: int = 104_857_600
    draft_retention_days: int = 7

    # --- Database (M2+) ---
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "video_engine"
    postgres_user: str = "video_engine"
    postgres_password: str = ""

    # --- Redis (M2+) ---
    redis_url: str = "redis://localhost:6379/0"

    # --- OpenAI: planning only (M5+) ---
    openai_api_key: str | None = None
    openai_org_id: str | None = None
    openai_planning_model: str = "gpt-5.6-terra"
    openai_planning_model_cheap: str = "gpt-4o-mini"
    openai_temperature: float = 0.3
    planner_max_repair_attempts: int = 1
    # Vision constraint check on generated media (M6.5, A12) - a separate,
    # smaller model than the planning model: vision support isn't
    # guaranteed on every planning model choice, and this is a mechanical
    # check, not creative judgement, so a cheap real vision-capable model
    # is the right default rather than reusing the planning model's.
    openai_vision_model: str = "gpt-4o-mini"
    # OQ-2 / output_quality_pass.md §14 (2026-08-29): subject LOCATION is
    # a separate, harder question than the A30a plausibility gate and gets
    # its own model. Measured on real assets: gpt-4o-mini put the aim on
    # the kart instead of the driver, on the wrong car of two, and on
    # empty track beside the pack; gpt-5.5 got all three right. The gate
    # itself stays on `openai_vision_model` because A30a's false-accept /
    # false-reject balance was calibrated twice against that model - a
    # silent model swap underneath it would re-open that calibration.
    openai_focal_model: str = "gpt-5.5"
    # Longest edge the focal call sends. 97% of that call's input tokens
    # were the image, and the answer is a normalised coordinate, so full
    # resolution bought nothing: measured across five sizes on real
    # assets, answer drift vs the full-size answer is FLAT from 1024 down
    # to 512 (0.077 / 0.074 / 0.084) and only degrades at 384 (0.133).
    # 512 costs 10% of the tokens full size did. See output_quality_pass.md
    # §14.7.
    focal_image_max_px: int = 512
    # Longest edge the A30a depiction gate sends. Separate from
    # `focal_image_max_px` on purpose: focal's answer is a normalised
    # coordinate (512 held), but this gate's accept/reject balance was
    # calibrated twice against full-size images on gpt-4o-mini.
    # Re-measured 2026-08-29 (output_quality_pass.md P-OQ-15.4): on 11
    # on-disk assets, 512 flipped one verdict vs full-res
    # (`ft_diagram_keep`: full True → 512 False = extra false accept);
    # 1024 held with 0 flips. Ship 1024.
    depiction_image_max_px: int = 1024
    # Hard cap on generations per shot (M6.5, A13): attempt 0 (original
    # prompt) + up to 2 bounded retries (revised prompt/same seed, then
    # revised prompt/varied seed) before a constraint-violating shot is
    # marked failed and surfaced to a human (A14) rather than looped.
    max_generation_attempts_per_shot: int = 3

    # --- fal.ai: image (rung 6) + video (rung 5) generation (M7+) ---
    # Model ids are a config value, never hardcoded in a provider class —
    # swapping models is the reason media generation routes through an
    # aggregator at all. The defaults below are a direct pick, NOT the
    # result of the guide's Step 0 bake-off — that comparison was
    # deliberately skipped to avoid spending real money on a side-by-side
    # that didn't happen. The video model is image-to-video, not
    # text-to-video: every video generation chains through the image
    # model first for a keyframe (see ResolveAssetsStep._generate_video_real).
    # If a generation call 404s, the model id has moved; check
    # https://fal.ai/models and update the single line below.
    fal_key: str | None = None
    fal_image_model: str = "fal-ai/bytedance/seedream/v4/text-to-image"
    fal_video_model: str = "fal-ai/kling-video/o3/standard/image-to-video"
    fal_poll_interval_seconds: int = 15
    fal_max_poll_minutes: int = 20
    # Rough per-generation cost estimates in cents, used only for the
    # pre-approval cost estimate and the budget-cap check — not billing.
    # fal's actual per-model pricing varies; refine these after real usage.
    fal_image_cost_cents_estimate: int = 4
    fal_video_cost_cents_estimate: int = 50
    # LLM token pricing lives in module-level `LLM_USD_PER_1M_TOKENS`
    # (OQ-4.4) — not an env knob; see that constant below Settings.

    # --- ElevenLabs (M5+) ---
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    # Switched from eleven_multilingual_v2 on 2026-08-24: live A/B probe
    # (backend/scripts/hinglish_voice_probe.py) against a real Hindi/
    # English code-switched line showed multilingual_v2 stalling hard at
    # every script boundary (~30% of total duration was silence, longest
    # gap 0.9s) regardless of voice_settings.stability tuning, while v3
    # produced natural-length pauses (~9-11% silence, longest gap 0.3s).
    # Confirmed by ear, not just the silence-gap numbers. See that
    # script's docstring for the full probe. CAVEAT: v3's voice_settings.
    # speed did not reproduce R8's clean, monotonic scaling when re-
    # checked live the same day - repeat identical requests at the same
    # speed varied by >1s of duration, and 1.0-vs-1.2 (the actual
    # production range) was not reliably distinguishable. `speed` is
    # still wired through for v3, but retention_fast's audible pacing
    # boost should be re-verified by ear, not assumed.
    elevenlabs_model: str = "eleven_v3"
    # ISO 639-1 hint sent as `language_code`. Documented as unsupported
    # (silently ignored) on eleven_multilingual_v2; on eleven_v3 the
    # probe above found it accepted (200 OK, no error) alongside a
    # slightly cleaner switch-boundary pause pattern than the v3
    # default, confirmed by ear. Global default is None (no hint) - this
    # codebase narrates BOTH English-only and Hindi/Hinglish projects
    # (see hindi_test_project.json / hinglish_test_project.json /
    # m8_test_project.json fixtures), so forcing "hi" here would
    # mispronounce every English-only project's narration AND bust its
    # narration cache. Same shape as `elevenlabs_voice_id`: a global
    # fallback, overridden per-project by `Timeline.metadata
    # .language_code` (`retry_narration_language`, 2026-08-24).
    elevenlabs_language_code: str | None = None
    elevenlabs_output_format: str = "mp3_44100_128"
    # Pre-approval estimate and budget-cap check only - not billing, same
    # spirit as the fal_*_cost_cents_estimate values above. Calibrated
    # 2026-08-19 against ElevenLabs Starter Multilingual v2 (Track C
    # §3.3): ₹8.80 / 1K chars ≈ 0.0103 ¢/char. The previous 0.018 was a
    # 1.74× over-estimate; narration is still ~1.4% of the per-minute cap.
    elevenlabs_cost_cents_per_character: float = 0.0103

    # --- Wikimedia (M6+) ---
    wikimedia_user_agent: str = "VideoGenerationEngine/0.1 (https://example.com; you@example.com)"
    wikimedia_api_url: str = "https://commons.wikimedia.org/w/api.php"
    wikimedia_rate_limit_per_second: int = 5

    # --- Wikipedia entity retrieval (M6.5+, A1/A2) ---
    # Entity -> images resolution (WikipediaEntityAssetProvider) needs two
    # endpoints beyond Commons itself: the English Wikipedia API (to find
    # the article an entity name refers to) and its REST media-list
    # endpoint (to take that article's own curated images). Both verified
    # against the live API before use, not guessed - see
    # app/providers/wikimedia.py.
    wikipedia_search_api_url: str = "https://en.wikipedia.org/w/api.php"
    wikipedia_media_list_api_url: str = "https://en.wikipedia.org/api/rest_v1/page/media-list"

    # --- Pexels (M6+) ---
    pexels_api_key: str | None = None

    # --- Asset relevance gate (M6+) ---
    # A candidate scoring below this on `app/assets/relevance.py`'s
    # term-overlap score is discarded before download/ranking, exactly like
    # the licence gate - never merely deprioritised. 0.25 sits strictly
    # between the highest score measured for a real WRONG match (0.143, a
    # single shared generic word such as "South" or "coal") and the lowest
    # score measured for a real CORRECT match (0.333, a single shared
    # distinctive word such as "Leuna") in the regression corpus in
    # tests/unit/assets/test_relevance.py - tightening much further starts
    # rejecting genuine matches and pushing shots to (paid) generation.
    asset_relevance_threshold: float = 0.25

    # --- Music (M8+) ---
    # "pixabay" was the original spec pick; verified live 2026-08-15 that
    # Pixabay has no public Music/Audio search API at all (only Images
    # and Videos - see app/providers/pixabay_music.py). "openverse" was
    # the real, working default for a while, but it depends on a live,
    # thin, sometimes-empty third-party search (that module's own
    # docstring: "a narrow music_plan legitimately finds nothing on a
    # real search"). "local" (motion_new_styles_and_long_form_videos.md
    # §11 step 6, 2026-08-18) is the curated 54-track library built to
    # replace it - never empty, never rate-limited, no network call at
    # fetch time - and is now the default. "openverse" stays registered
    # and selectable via config, not removed.
    music_provider: str = "local"
    music_library_root: Path = Path("./storage/music_library")
    pixabay_api_key: str | None = None
    freesound_api_key: str | None = None
    # Tuned live, 2026-08-16, against the restored `hinglish_final_project`
    # fixture (R1 unblocked this - three independent re-renders, each free,
    # to compare gains against real narration): the ORIGINAL -22.0/-32.0
    # made the bed nearly inaudible under this script's near-continuous
    # speech - measured -52.6dB mean on the ducked bed alone (isolated via
    # `tests/integration/test_render_music_mix.py`'s own measurement
    # approach), against a full-mix loudness of -26.4dB that never moved
    # across any of the three renders (narration is unaffected by this
    # setting - only the bed is). Raising bed/duck by 8dB moved the ducked
    # bed to -46.6dB, still barely there; a second raise to these values
    # reached -40.6dB - 12dB louder than the original, comfortably audible
    # under the narrator without the bed ever competing with it. Do not
    # "tidy" these back toward the old numbers without re-measuring: they
    # were not a stylistic guess, they were the result of the bed being
    # nearly silent.
    music_bed_gain_db: float = -14.0
    music_duck_gain_db: float = -20.0
    # Rough cost estimate in cents, folded into `check_budget` the same
    # way `fal_image_cost_cents_estimate`/narration are (M8 build order
    # item 4) - 0 by default because both Openverse and Pixabay search
    # are genuinely free; kept as a real config value (not hardcoded 0
    # inline) so a future paid music provider only ever needs a config
    # change here, never a new call site.
    music_cost_cents_estimate: int = 0

    # --- SFX (parent plan §5.5) ---
    # "local" is a small curated library downloaded from Openverse
    # (CC0/CC-BY, short clips). "openverse" stays available for a live
    # search when the library has no hit for a kind.
    sfx_provider: str = "local"
    sfx_library_root: Path = Path("./storage/sfx_library")
    sfx_gain_db: float = -8.0
    # C3c (analysis.md, decision 5b/5c): a clip with a MEASURED peak is
    # normalized onto this target; `sfx_gain_db` above remains the
    # fallback for unmeasured clips (old timelines, failed probes,
    # DRY_RUN). The per-kind dB offsets below ride on top of either
    # path; None = no offset for that kind.
    #
    # This is an ABSOLUTE OUTPUT PEAK TARGET in dBFS, not a gain - a
    # different quantity from `sfx_gain_db` above, which is a flat GAIN
    # applied on top of a clip's existing level. The two must never be
    # conflated (see analysis.md RV11): a previous revision (P6)
    # mistakenly reused sfx_gain_db's -8.0 for this field, which made
    # every real SFX clip LOUDER (peaks were already below -8 dBFS), the
    # opposite of the desired effect.
    #
    # -20.0, lowered from C3c's original "~-12 dBFS" spec 2026-08-27.
    # ⚠ This is NOT a repeat of the P6 mistake above (that one conflated
    # the two quantities and raised the level); this lowers it, on new
    # measured evidence C3c never had:
    #
    #   narration alone (d3a4d00d, real render): mean -22.3 dB, peak -2.8
    #   SFX normalized onto the old -12.0 peak target
    #     -> every stinger/whoosh transient landed ~10 dB ABOVE the
    #        average narration level it is supposed to bed under.
    #
    # Speech has a high crest factor, so a peak-referenced target chosen
    # in isolation says nothing about how the effect sits against the
    # voice. -20.0 puts SFX peaks near the narration's own average
    # instead of over it. Still a starting point, not a measured
    # constant - go to ~-24 if it remains too present, and prefer the
    # per-kind offsets below for a single problem clip.
    sfx_normalize_target_db: float = -20.0
    sfx_whoosh_gain_db: float | None = None
    sfx_stinger_gain_db: float | None = None
    sfx_transition_gain_db: float | None = None
    sfx_max_clip_s: float = 1.5

    # --- Rendering ---
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    render_width: int = 720
    render_height: int = 1280
    render_fps: int = 30
    render_pixel_format: str = "yuv420p"
    draft_width: int = 480
    draft_height: int = 854
    default_transition_duration_s: float = 0.4
    burn_captions: bool = True
    # Noto Sans Devanagari, not Inter (which has zero Devanagari coverage):
    # docs/14_Captions_Plan.md §3.2/§8.4. Vendored at backend/vendor/fonts/
    # (app/renderer/captions.py resolves the family name to that file), not
    # host fontconfig - a fallback stack is disqualified under I5, since
    # libass's fallback resolution is platform-dependent.
    caption_font: str = "Noto Sans Devanagari"

    # OQ-1a (output_quality_pass.md §4.1, 2026-08-28): final-mix loudness
    # target via two-pass linear loudnorm. −16 LUFS / −1.0 dBTP is a
    # short-form starting default awaiting a human listen — not an
    # ear-signed target, and not a per-format split. Kill switch
    # `loudness_normalize` leaves the mux unnormalized when False.
    loudness_normalize: bool = True
    loudness_target_lufs: float = -16.0
    loudness_true_peak_db: float = -1.0

    # OQ-1c (output_quality_pass.md §4.3): per-scene narration gain match
    # to the mean of measurable scenes' integrated LUFS, applied before
    # concat. Flattens scene-boundary level jumps; not a second absolute
    # LUFS target (OQ-1a owns the mix). Kill switch leaves concat as-is.
    narration_level_match: bool = True

    # Text cards (motion_new_styles_and_long_form_videos.md §2.6, Tier 2,
    # 2026-08-17) - a per-shot structural title/heading overlay, gated on
    # `shot.text_card` being set (Timeline-level, per shot), not by this
    # flag alone; this is a global kill switch (mirrors `watermark_
    # enabled`'s own shape) for the rare case a bug is found in text-card
    # rendering after real shots already carry one. Reuses `caption_font`
    # - no separate vendored font asset for a v1 feature this small.
    burn_text_cards: bool = True

    # Channel branding (docs/plans/watermark_implementation_plan.md).
    # Enabled 2026-08-17 after the real-render verification in §10.4.
    # Position/margin/width are fractions of frame dimensions, never
    # absolute pixels (§3): the same proportions must hold regardless of
    # render resolution. The logo file itself is vendored
    # (backend/vendor/branding/logo.png), not a configurable path - one
    # channel, one logo (§8.1).
    watermark_enabled: bool = True
    watermark_position: str = "top_right"
    # 15%, not the sketch's 4% - verified against a real render (docs/
    # plans/watermark_implementation_plan.md §10.4): at 10% this specific
    # logo's wordmark was borderline legible; 15% reads clearly on both a
    # plain and a busy/dense background without dominating the frame.
    watermark_width_fraction: float = 0.15
    watermark_margin_fraction: float = 0.03
    watermark_opacity: float = 0.65

    # --- Creative constraints (D7) ---
    max_video_duration_s: float = 90.0
    max_shots_per_project: int = 40
    min_shot_duration_s: float = 1.5
    max_shot_duration_s: float = 8.0
    max_scenes: int = 12
    # Minimum number of shots between two text cards, enforced
    # PROJECT-WIDE after the per-scene gather (`_cap_text_cards`,
    # planners/shot/planner.py). 2026-08-27, measured.
    #
    # The prompt asks for "roughly one card every four to six shots",
    # but the Shot Planner sees ONE SCENE per call - and scenes average
    # ~4 shots. Every scene independently concluded "about one for me",
    # so the whole-video rate came out at the per-scene rate: real run
    # d3a4d00d produced 17 cards across 39 shots (~1 per 2.3), roughly
    # 2x the intended rate, and with it 17 stinger SFX hits.
    #
    # Same class as the glitch cap and `max_video_shots_per_project`:
    # a rate no single per-scene call can see. 4 = the low end of the
    # prompt's own range, so this only ever trims genuine excess.
    text_card_min_shot_gap: int = 4
    default_language: str = "en"
    # Track C C1: scripts with more than this many fragments take Path B
    # (act pass, then per-act scene planning). Deliberate guess, safe
    # only in this direction (§11 Q2) — do not raise without measuring.
    scene_planner_act_threshold: int = 70
    min_acts: int = 3
    max_acts: int = 7
    # Hard ceiling for length-aware max_video_duration_s (10 min).
    max_long_form_duration_s: float = 600.0

    # A4 (motion_new_styles_and_long_form_videos.md, 2026-08-18): an
    # absolute cap, not a fraction of shot count - `fal_video_cost_cents_
    # estimate` (50c) is ~12x `fal_image_cost_cents_estimate` (4c), so an
    # uncalibrated planner choosing video freely is a real budget event.
    # A flat cap bounds worst-case spend predictably regardless of
    # project size, the same reasoning `max_shots_per_project` already
    # applies to shot count. Enforced in `AssetPlanner.plan()`, mirroring
    # that same function's own "loud failure, never silent merging" cap
    # check exactly (`shot/planner.py`).
    max_video_shots_per_project: int = 5

    # --- Script pre-flight (motion_new_styles_and_long_form_videos.md
    # §3, Track D) - estimates a script's spoken duration BEFORE any
    # narration exists, from character count alone. Each constant is
    # Calibrated for the configured voice (`0muxiGNHAVvmM1qWRtyV`)
    # against live Multilingual v2 (Q8, 2026-08-20): English 15.1,
    # Hinglish 14.0, Hindi 14.9 — one constant near 14.4 lands within 5%
    # of all three. The old `script_chars_per_second_hi = 12.9` was 15.5%
    # too slow on real Hindi and is gone (R11 / Q8). Speed is applied by
    # `preflight._chars_per_second` via `resolve_narration_speed(style)`.
    script_chars_per_second_en: float = 14.4
    script_preflight_margin_fraction: float = 0.2
    # Q7: warning-only floor. A 400-char script (~28 s) is legal; the
    # author may have wanted that. `check_feasibility` reports it on
    # `warnings`, never `violations`, so `passed` stays true.
    script_preflight_min_duration_s: float = 60.0

    # --- Render style (motion_new_styles_and_long_form_videos.md, Track
    # B) - `documentary_archival` is today's existing behaviour, named
    # rather than left implicit, so a project that never sets a style
    # (every fixture and test predating this field) resolves to EXACTLY
    # the constraint bundle and prompt it always used - see
    # `app/script/styles.py::resolve_constraint_bundle`'s own docstring
    # for the `None`-means-default reasoning this depends on.
    default_render_style: str = "documentary_archival"

    # Track C C4: reuse penalty is a temporal window, not a global set.
    # Uncalibrated taste default (plan §5.2) — full penalty at 0 s gap,
    # linear decay to zero at this horizon. retention_fast packs ~3× the
    # shots into the same runtime, so its window is shorter; do not tune
    # one and assume it transfers.
    asset_reuse_window_s: float = 60.0
    asset_reuse_window_s_fast: float = 20.0

    # --- Cost control ---
    project_budget_cap_cents: int = 1000
    require_cost_estimate_before_approval: bool = True
    max_concurrent_image_jobs: int = 4
    max_concurrent_video_jobs: int = 2
    max_concurrent_asset_downloads: int = 8
    # Search I/O fan-out (Commons/Pexels/entity/download). Rank and bind
    # stay serial so C4 reuse sees earlier picks in timeline order.
    # Wikimedia's own RateLimiter still caps Commons at 5 calls/s.
    asset_search_concurrency: int = 8

    # Track C §3.2 / §11 Q4: four consumers of `bounded_gather`, four
    # different quantities. A semaphore approximates TPM; per-call
    # backoff is what actually absorbs a 429. `RateLimiter` (calls/sec)
    # matches none of these and must not be reused — it stays on the
    # Wikimedia path, where calls/sec genuinely is the constraint.
    # ElevenLabs Starter concurrent-request cap (not 4–6; Q4 withdrew
    # that guess).
    narration_concurrency: int = 3
    # ~34% of gpt-5.6-terra's 500,000 TPM at ~1,750 tokens/call and
    # ~12 calls/min per in-flight slot. Ceiling 16; do not start there
    # — 8 leaves room for a second project planning concurrently.
    # Shot planner and asset planner share this number (same TPM
    # budget); the two loops stay sequential with respect to each
    # other. See `planner_concurrency()`.
    planner_concurrency: int = 8
    # ffmpeg_run_concurrency = max(1, cpu_count - ffmpeg_reserved_cores).
    ffmpeg_reserved_cores: int = 2
    # Per-item TransientError retries inside bounded_gather, so a 429
    # never reaches step level (§2.5). Independent of the engine's
    # own step-level max_attempts.
    bounded_gather_max_attempts: int = 3

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_path: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# OQ-4.4 (2026-08-29): USD per 1M tokens (input, output) for llm_call
# inserts. Dated OpenAI snapshot ids (e.g. gpt-4o-mini-2024-07-18) match
# by longest prefix — see `app.assets.llm_pricing.llm_call_pricing`.
# Bump the date comment when rates change; historical rows store the
# rates they used on the row itself.
LLM_USD_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-5.5": (5.0, 30.0),
    "gpt-5.6-terra": (2.0, 12.0),
    "gpt-4o-mini": (0.15, 0.60),
}
