"""Background analysis jobs: store, kinds, runner and Celery wiring."""

from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .registry import JobKind, build_registry, mcp_tool_runner
from .store import Job, JobStore, MemoryJobStore, PostgresJobStore

__all__ = [
    "Job",
    "JobKind",
    "JobStore",
    "MemoryJobStore",
    "PostgresJobStore",
    "get_job_store",
    "get_registry",
]


@lru_cache
def get_job_store() -> JobStore:
    return PostgresJobStore(get_settings().database_url)


@lru_cache
def get_registry() -> dict[str, JobKind]:
    settings = get_settings()
    return build_registry(mcp_tool_runner(settings.mcp_server_url, settings.mcp_call_timeout))
