"""Application settings, loaded from environment variables (and `.env` in development)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Stock Research Assistant API"
    app_version: str = "0.1.0"
    app_env: str = "development"

    database_url: str = "postgresql://stock:stock@postgres:5432/stock"
    redis_url: str = "redis://redis:6379/0"
    mcp_server_url: str = "http://mcp:8100/mcp"
    mcp_health_url: str = "http://mcp:8100/health"

    cors_origins: list[str] = ["http://localhost:5173"]

    # Seconds to wait for each dependency in /health before reporting it as down.
    health_check_timeout: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
