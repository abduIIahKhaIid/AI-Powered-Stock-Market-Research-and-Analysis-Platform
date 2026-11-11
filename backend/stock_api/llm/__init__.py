"""LLM gateway: OpenAI-compatible chat with tool calling, provider presets and fallback."""

from __future__ import annotations

from ..config import Settings
from .gateway import (
    ChatResult,
    LLMError,
    LLMGateway,
    LLMUnavailableError,
    ToolCall,
    Usage,
    mcp_tool_to_openai,
)
from .providers import PRESETS, LLMConfigError, ProviderConfig, resolve_provider

__all__ = [
    "PRESETS",
    "ChatResult",
    "LLMConfigError",
    "LLMError",
    "LLMGateway",
    "LLMUnavailableError",
    "ProviderConfig",
    "ToolCall",
    "Usage",
    "build_gateway",
    "mcp_tool_to_openai",
    "resolve_provider",
]


def build_gateway(settings: Settings) -> LLMGateway:
    """Create the gateway from settings. Raises LLMConfigError if they are incomplete."""
    primary = resolve_provider(
        settings.llm_provider,
        settings.llm_model,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        extra_headers=settings.llm_extra_headers,
        price_input_per_mtok=settings.llm_price_input_per_mtok,
        price_output_per_mtok=settings.llm_price_output_per_mtok,
    )
    fallback = None
    if settings.llm_fallback_provider.strip():
        fallback = resolve_provider(
            settings.llm_fallback_provider,
            settings.llm_fallback_model,
            api_base=settings.llm_fallback_api_base,
            api_key=settings.llm_fallback_api_key,
            extra_headers=settings.llm_extra_headers,
            price_input_per_mtok=settings.llm_fallback_price_input_per_mtok,
            price_output_per_mtok=settings.llm_fallback_price_output_per_mtok,
        )
    return LLMGateway(
        primary,
        fallback,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )
