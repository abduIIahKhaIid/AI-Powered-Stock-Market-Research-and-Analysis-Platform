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

    # LLM gateway. Any OpenAI-compatible endpoint works: Ollama (local, or on Colab
    # behind an ngrok URL), Groq, Gemini, OpenAI, OpenRouter, Anthropic or a custom URL.
    llm_provider: str = "ollama"
    llm_model: str = ""
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_timeout: float = 120.0
    llm_max_retries: int = 1
    # Extra HTTP headers sent with every LLM request, as JSON: {"X-Header": "value"}.
    llm_extra_headers: dict[str, str] = {}
    # USD per million tokens, used only for cost logging. Leave at 0 for local models.
    llm_price_input_per_mtok: float = 0.0
    llm_price_output_per_mtok: float = 0.0

    # Optional second provider, used when the primary is unreachable (e.g. Colab is off).
    llm_fallback_provider: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_base: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_price_input_per_mtok: float = 0.0
    llm_fallback_price_output_per_mtok: float = 0.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
