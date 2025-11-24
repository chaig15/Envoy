"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


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
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

