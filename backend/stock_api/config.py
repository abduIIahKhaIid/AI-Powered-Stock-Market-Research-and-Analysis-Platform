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
    # After the primary fails as unreachable, use the fallback first for this many seconds.
    llm_primary_cooldown_seconds: float = 120.0

    # Agent harness
    agent_max_steps: int = 6
    agent_max_tool_calls: int = 8
    agent_tool_result_max_chars: int = 6000
    agent_history_messages: int = 8
    conversation_ttl_seconds: int = 7 * 24 * 3600
    mcp_call_timeout: float = 60.0

    # Background jobs (SCRUM-34): retries, and where large results and files are kept.
    job_retry_base_seconds: float = 5.0
    job_retry_max_seconds: float = 120.0
    job_result_inline_max_bytes: int = 64 * 1024
    job_results_dir: str = ".data/job-results"
    # Let the agent start background jobs from the chat (each one needs the user's approval).
    agent_jobs_enabled: bool = True
    # Policy (SCRUM-26). Tools needing approval beyond the built-in rules, as JSON list.
    agent_approval_tools: list[str] = []
    approval_timeout_seconds: float = 300.0
    audit_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
