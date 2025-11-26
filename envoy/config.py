"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Telegram
    telegram_bot_token: str

    # Database
    database_url: str

    # Encryption for Resy tokens
    encryption_key: str

    # Resy API
    resy_api_base: str = "https://api.resy.com"

    # Monitoring settings
    check_interval_seconds: int = 30
    max_concurrent_checks: int = 5  # Rate limit for Resy API

    # LLM settings
    llm_enabled: bool = False  # Set to True to enable natural language mode
    llm_provider: str = "anthropic"  # anthropic, openai, ollama, openrouter, vllm
    llm_model: Optional[str] = None  # Override default model for provider

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
