"""Build the Agent from settings."""

from __future__ import annotations

from functools import lru_cache

from ..config import Settings, get_settings
from ..llm import build_gateway
from .context import RedisConversationStore
from .planner import Agent
from .policy import ToolPolicy
from .toolbox import MCPToolbox


def create_agent(settings: Settings) -> Agent:
    """Raises LLMConfigError when the LLM settings are incomplete."""
    gateway = build_gateway(settings)
    return Agent(
        gateway,
        lambda: MCPToolbox.connect(settings.mcp_server_url, timeout=settings.mcp_call_timeout),
        RedisConversationStore(settings.redis_url, settings.conversation_ttl_seconds),
        policy=ToolPolicy(max_tool_calls=settings.agent_max_tool_calls),
        max_steps=settings.agent_max_steps,
        tool_result_max_chars=settings.agent_tool_result_max_chars,
        history_messages=settings.agent_history_messages,
    )


@lru_cache
def get_agent() -> Agent:
    """One agent per process, so the gateway's clients and cooldown state are shared."""
    return create_agent(get_settings())
