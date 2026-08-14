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

    # --- Pexels (M6+) ---
    pexels_api_key: str | None = None

    # --- Music (M8+) ---
    music_provider: str = "pixabay"
    pixabay_api_key: str | None = None
    freesound_api_key: str | None = None
    music_bed_gain_db: float = -22.0
    music_duck_gain_db: float = -32.0

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
    caption_font: str = "Inter"

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
