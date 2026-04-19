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
    app_name: str = "Quotation Intelligence API"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # API
    host: str = "0.0.0.0"
    port: int = 8000
    api_workers: int = 1

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost/quotation_db"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    storage_type: Literal["local", "s3"] = "local"
    storage_local_path: str = "./temp"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "us-east-1"
    s3_bucket_name: str | None = None

    # LLM — via LiteLLM (provider/model format)
    # Examples: "anthropic/claude-3-5-sonnet-20241022", "openai/gpt-4o",
    #           "ollama/llama3.2", "groq/llama3-70b-8192", "gemini/gemini-1.5-pro"
    llm_model: str = "anthropic/claude-3-5-sonnet-20241022"
    llm_api_key: str | None = None          # Generic key; or set provider-specific env vars
    llm_api_base: str | None = None         # Optional: custom base URL (e.g. Ollama endpoint)
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3
    llm_retry_backoff_factor: float = 2.0

    # Processing
    max_file_size_mb: int = 10
    max_pages_per_pdf: int = 50
    processing_timeout_seconds: int = 120
    enable_ocr_fallback: bool = True

    # Security
    secret_key: str = "change-me-in-production"
    api_key_header: str = "X-API-Key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Monitoring
    enable_prometheus: bool = True
    sentry_dsn: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_logs: bool = False

    @property
    def database_url_sync(self) -> str:
        """Get synchronous database URL for Alembic/Celery."""
        return self.database_url.replace("+asyncpg", "")


settings = Settings()
