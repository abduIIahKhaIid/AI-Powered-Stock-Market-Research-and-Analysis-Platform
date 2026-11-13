"""Build the Agent from settings."""

from __future__ import annotations

from functools import lru_cache

from ..config import Settings, get_settings
from ..llm import build_gateway
from .approvals import ApprovalBroker
from .audit import PostgresAuditLog
from .context import RedisConversationStore
from .job_tools import JobLauncher, JobToolbox
from .planner import Agent
from .policy import ToolPolicy
from .toolbox import MCPToolbox, Toolbox


@lru_cache
def get_approval_broker() -> ApprovalBroker:
    """Shared by the chat stream (waits) and POST /approvals (decides)."""
    return ApprovalBroker(get_settings().approval_timeout_seconds)


def create_agent(settings: Settings, approvals: ApprovalBroker | None = None) -> Agent:
    """Raises LLMConfigError when the LLM settings are incomplete."""
    gateway = build_gateway(settings)
    wrapper = None
    if settings.agent_jobs_enabled:
        from ..jobs import get_job_store, get_registry
        from ..jobs.queue import Queue

        launcher = JobLauncher(get_job_store, get_registry, Queue())

        def wrapper(toolbox: Toolbox, conversation_id: str) -> Toolbox:
            return JobToolbox(
                toolbox, launcher, conversation_id, settings.agent_python_wait_seconds
            )

    return Agent(
        gateway,
        lambda: MCPToolbox.connect(settings.mcp_server_url, timeout=settings.mcp_call_timeout),
        RedisConversationStore(settings.redis_url, settings.conversation_ttl_seconds),
        policy=ToolPolicy(
            max_tool_calls=settings.agent_max_tool_calls,
            approval_tools=frozenset(settings.agent_approval_tools),
        ),
        max_steps=settings.agent_max_steps,
        tool_result_max_chars=settings.agent_tool_result_max_chars,
        history_messages=settings.agent_history_messages,
        approvals=approvals,
        audit=PostgresAuditLog(settings.database_url) if settings.audit_enabled else None,
        toolbox_wrapper=wrapper,
    )


@lru_cache
def get_agent() -> Agent:
    """One agent per process, so the gateway's clients and cooldown state are shared."""
    return create_agent(get_settings(), get_approval_broker())
