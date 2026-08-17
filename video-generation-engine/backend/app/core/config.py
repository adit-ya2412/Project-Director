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

    # --- ElevenLabs (M5+) ---
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_output_format: str = "mp3_44100_128"
    # Rough cost estimate in cents per character (pre-approval estimate and
    # budget-cap check only - not billing, same spirit as the fal_*_cost_
    # cents_estimate values above). ElevenLabs bills per character of input
    # text; refine this after real usage.
    elevenlabs_cost_cents_per_character: float = 0.018

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
    # and Videos - see app/providers/pixabay_music.py). "openverse" (no
    # API key, aggregates Jamendo + Freesound, verified live the same
    # day) is the real, working default now.
    music_provider: str = "openverse"
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
    default_language: str = "en"

    # --- Cost control ---
    project_budget_cap_cents: int = 1000
    require_cost_estimate_before_approval: bool = True
    max_concurrent_image_jobs: int = 4
    max_concurrent_video_jobs: int = 2
    max_concurrent_asset_downloads: int = 8

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_path: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
