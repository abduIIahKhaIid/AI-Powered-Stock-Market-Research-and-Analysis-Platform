"""Harness tools that start background jobs from the chat (SCRUM-33).

The tool names start with ``start_job`` so the policy asks for the user's approval
before any job is queued (SCRUM-26).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ..jobs.queue import Queue
from ..jobs.registry import MAX_SCAN_SYMBOLS, JobInputError, JobKind
from ..jobs.store import Job, JobStore
from .toolbox import Toolbox, ToolOutcome, ToolSpec

START_SCAN = "start_job_indicator_scan"

SCAN_SPEC = ToolSpec(
    name=START_SCAN,
    description=(
        "Start a background job that computes technical indicators for several NASDAQ "
        f"symbols at once (up to {MAX_SCAN_SYMBOLS}). Use it when the user wants to scan or "
        "screen three or more symbols; for one or two symbols call compute_indicators "
        "instead. Returns a job id at once. The job's progress and a summary of its results "
        "appear in the chat when it finishes, so do not report any figures from it now."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": MAX_SCAN_SYMBOLS,
                "description": "NASDAQ ticker symbols, for example ['AAPL', 'MSFT', 'NVDA'].",
            },
            "indicators": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Indicator names such as rsi_14, macd, sma_50, ema_20, bbands_20. "
                "Defaults to rsi_14, macd and sma_50.",
            },
            "period": {
                "type": "string",
                "enum": ["1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y"],
                "description": "How much history to report on. Defaults to 6mo.",
            },
        },
        "required": ["symbols"],
    },
)

TOOL_KINDS = {START_SCAN: "indicator_scan"}


class JobLauncher:
    """Validates, records and queues a job; the same steps as POST /jobs."""

    def __init__(
        self,
        store: Callable[[], JobStore],
        registry: Callable[[], dict[str, JobKind]],
        queue: Queue,
    ) -> None:
        self._store = store
        self._registry = registry
        self._queue = queue

    def _start(self, kind_name: str, params: dict[str, Any], conversation_id: str) -> Job:
        kind = self._registry()[kind_name]
        valid = kind.validate(params)
        job = self._store().create(
            kind.name, valid, conversation_id, max_attempts=kind.max_attempts
        )
        self._queue.enqueue(job, kind)
        return job

    async def start(self, kind_name: str, params: dict[str, Any], conversation_id: str) -> Job:
        return await asyncio.to_thread(self._start, kind_name, params, conversation_id)

    def title(self, kind_name: str) -> str:
        kind = self._registry().get(kind_name)
        return kind.title if kind else kind_name


class JobToolbox:
    """An MCP toolbox plus the job tools, bound to one conversation."""

    def __init__(self, inner: Toolbox, launcher: JobLauncher, conversation_id: str) -> None:
        self.inner = inner
        self.launcher = launcher
        self.conversation_id = conversation_id

    async def list_tools(self) -> list[ToolSpec]:
        return [*await self.inner.list_tools(), SCAN_SPEC]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        kind_name = TOOL_KINDS.get(name)
        if kind_name is None:
            return await self.inner.call(name, arguments)
        try:
            job = await self.launcher.start(kind_name, arguments, self.conversation_id)
        except JobInputError as exc:
            return ToolOutcome.failure(name, arguments, str(exc))
        except Exception as exc:  # noqa: BLE001 - e.g. the queue or the database is down
            return ToolOutcome.failure(
                name, arguments, f"The job could not be queued ({type(exc).__name__}: {exc})."
            )
        return ToolOutcome(
            name=name,
            arguments=arguments,
            ok=True,
            payload={
                "job_id": job.id,
                "kind": job.kind,
                "title": self.launcher.title(job.kind),
                "status": job.status,
                "symbols": job.params.get("symbols"),
                "note": "Started in the background. Progress and results will appear in the "
                "chat; no results are available yet.",
            },
        )
