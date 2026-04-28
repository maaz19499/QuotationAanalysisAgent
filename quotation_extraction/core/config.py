"""Application configuration and settings."""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Quotation Extraction API"
    app_version: str = "2.0.0"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # API
    host: str = "0.0.0.0"
    port: int = 8000
    api_workers: int = 1

    # Database
    database_url: str | None = None
    
    # Redis
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: str | None = None

    # Storage
    storage_type: Literal["local", "s3"] = "local"
    storage_local_path: str = "./temp"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "us-east-1"
    s3_bucket_name: str | None = None

    # ── LLM — via LiteLLM (provider/model format) ──────────────────────
    # Main vision model for PDF page extraction (Gemini Pro, GPT-4o, etc.)
    llm_model: str = "gemini/gemini-2.5-flash"
    # Optional: Separate model for the text-only merge pass
    llm_merge_model: str | None = None
    # Optional: Cheap/fast model for page classification pre-filtering
    flash_model: str | None = None
    # Generic API key (or use provider-specific env vars)
    llm_api_key: str | None = None
    gemini_api_key_free: str | None = None
    gemini_api_key_paid: str | None = None
    llm_api_base: str | None = None
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3
    llm_retry_backoff_factor: float = 2.0
    flash_timeout_seconds: float = 15.0

    # ── Pipeline feature flags ─────────────────────────────────────────
    enable_page_filtering: bool = True
    enable_image_preprocessing: bool = True

    # Processing
    max_file_size_mb: int = 10
    max_pages_per_pdf: int = 50
    processing_timeout_seconds: int = 120

    # Vision-based extraction
    vision_dpi: int = 100
    vision_batch_size: int = 1

    # Security
    secret_key: str = "change-me-in-production"
    api_key_header: str = "X-API-Key"

    # Monitoring
    sentry_dsn: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_logs: bool = False


settings = Settings()
