"""Application configuration and settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "antikythera-f1-generator"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_HOST: str = "postgres.antikythera.co.za"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "AntikytheraF1Series"
    DATABASE_USER: str = ""
    DATABASE_PASSWORD: str = ""
    DATABASE_URL: Optional[str] = None

    @property
    def database_url(self) -> str:
        """Construct database URL if not provided."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    # MinIO Object Storage
    MINIO_ENDPOINT: str = "minio.antikythera.co.za:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_SECURE: bool = True

    # MinIO Buckets
    MINIO_BUCKET_CHARACTERS: str = "f1-characters"
    MINIO_BUCKET_SCENE_IMAGES: str = "f1-scene-images"
    MINIO_BUCKET_VIDEO_CLIPS: str = "f1-video-clips"
    MINIO_BUCKET_FINAL_VIDEOS: str = "f1-final-videos"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-haiku-20240307"
    ANTHROPIC_MAX_TOKENS: int = 4096
    ANTHROPIC_TEMPERATURE: float = 0.8

    # Haiku pricing (per 1K tokens)
    HAIKU_INPUT_COST_PER_1K: float = 0.00025
    HAIKU_OUTPUT_COST_PER_1K: float = 0.00125

    # Gemini / Nano Banana Pro (Image Generation)
    GEMINI_API_KEY: str = ""
    GEMINI_IMAGE_MODEL: str = "gemini-2.0-flash-exp"  # Supports multi-modal input with reference images
    GEMINI_IMAGE_RESOLUTION: str = "1024x1536"  # Portrait orientation for character images
    GEMINI_STYLE_REFERENCE_COUNT: int = 4  # Number of style reference images to feed

    # Ovi (HuggingFace Gradio)
    OVI_SPACE: str = "alexnasa/Ovi-ZEROGPU"  # Working space with API params
    OVI_TIMEOUT_SECONDS: int = 300
    OVI_QUALITY: str = "standard"  # draft, standard, high, ultra
    HUGGINGFACE_TOKEN: str = ""  # HF token for private spaces

    # YouTube API
    YOUTUBE_CLIENT_ID: str = ""
    YOUTUBE_CLIENT_SECRET: str = ""
    YOUTUBE_CREDENTIALS_PATH: str = "~/.credentials/antikythera-f1/youtube_credentials.json"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Video Generation Settings
    VIDEO_SCENE_COUNT: int = 24
    VIDEO_SCENE_DURATION_SECONDS: int = 5
    VIDEO_TOTAL_DURATION_SECONDS: int = 120
    VIDEO_FRAME_RATE: int = 24
    VIDEO_RESOLUTION: str = "1080p"
    VIDEO_CODEC: str = "libx264"
    VIDEO_AUDIO_CODEC: str = "aac"
    VIDEO_CRF: int = 23

    # Retry Configuration
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_BASE_DELAY_SECONDS: int = 5
    RETRY_MAX_DELAY_SECONDS: int = 300

    # Storage Retention
    STORAGE_RETENTION_RACES: int = 3

    # Scheduling
    TRIGGER_CHECK_INTERVAL_MINUTES: int = 15
    PRE_RACE_DELAY_MINUTES: int = 30
    POST_RACE_DELAY_MINUTES: int = 60


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
