"""Harness tools that start background jobs from the chat (SCRUM-33, SCRUM-28).

The tool names start with ``start_job`` or ``run_python``, so the policy asks for the
user's approval before any job is queued (SCRUM-26).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..jobs.queue import Queue
from ..jobs.registry import (
    MAX_CODE_CHARS,
    MAX_PYTHON_SYMBOLS,
    MAX_SCAN_SYMBOLS,
    MAX_SWEEP_CASES,
    MAX_SWEEP_SYMBOLS,
    SWEEP_FIELDS,
    JobInputError,
    JobKind,
)
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

RUN_PYTHON = "run_python_analysis"

PYTHON_SPEC = ToolSpec(
    name=RUN_PYTHON,
    description=(
        "Run Python code in an isolated sandbox for calculations the other tools cannot do, "
        "such as custom statistics, correlations, volatility or simple backtests. The daily "
        "price history of each symbol you list is in the file prices_<SYMBOL>.csv in the "
        "current folder (also INPUT_DIR + '/prices_<SYMBOL>.csv'), with columns date, open, "
        "high, low, close, volume. "
        "numpy, pandas, scipy, statsmodels and ta are installed. Set a variable named result "
        "to a JSON-serializable dict with the numbers to report; plots and images are not "
        "returned. With several symbols, keep each symbol's numbers under its own key, for "
        "example {'AAPL': {'volatility': ...}, 'MSFT': {'volatility': ...}}. The code has no "
        "network access and may write only under /tmp; it is stopped after 30 seconds. Report "
        "only numbers from the returned result."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "maxLength": MAX_CODE_CHARS,
                "description": "Python source that sets the variable result.",
            },
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_PYTHON_SYMBOLS,
                "description": "NASDAQ tickers whose price history the code reads.",
            },
            "period": {
                "type": "string",
                "enum": ["1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y"],
                "description": "How much daily price history to provide. Defaults to 1y.",
            },
        },
        "required": ["code"],
    },
)

START_SWEEP = "start_job_scenario_sweep"

_CASE_PROPERTIES = {
    field: {"type": "number", "description": "percent" if field != "horizon_years" else "years"}
    for field in SWEEP_FIELDS
}

SWEEP_SPEC = ToolSpec(
    name=START_SWEEP,
    description=(
        "Start a background job that runs many what-if scenarios (more than 3, up to "
        f"{MAX_SWEEP_CASES}) or the same scenarios for several symbols (up to "
        f"{MAX_SWEEP_SYMBOLS}). Give either cases (a list, each with a name and the "
        "assumptions it changes) or grid (for each assumption a list of values; every "
        "combination becomes one scenario). Assumptions are in percent: revenue_growth, "
        "net_margin, discount_rate, terminal_growth, plus horizon_years. Unchanged values "
        "come from the base case, as in run_scenario. Returns a job id at once; progress per "
        "scenario and a summary table appear in the chat when it finishes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": MAX_SWEEP_SYMBOLS,
            },
            "cases": {
                "type": "array",
                "maxItems": MAX_SWEEP_CASES,
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, **_CASE_PROPERTIES},
                },
            },
            "grid": {
                "type": "object",
                "properties": {
                    field: {"type": "array", "items": {"type": "number"}} for field in SWEEP_FIELDS
                },
            },
            "assumptions": {
                "type": "object",
                "properties": _CASE_PROPERTIES,
                "description": "Base-case values shared by every scenario.",
            },
        },
        "required": ["symbols"],
    },
)

TOOL_KINDS = {START_SCAN: "indicator_scan", START_SWEEP: "scenario_sweep"}
SPECS = {START_SCAN: SCAN_SPEC, START_SWEEP: SWEEP_SPEC}
# Tools that run a job and wait for its result, instead of leaving it in the background.
WAITING_TOOL_KINDS = {RUN_PYTHON: "python_analysis"}


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

    def offers(self, kind_name: str) -> bool:
        return kind_name in self._registry()

    async def wait(self, job_id: str, timeout: float, poll: float = 0.5) -> Job:
        """The job once it finished, or as it is when `timeout` runs out."""
        store = self._store()
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            job = await asyncio.to_thread(store.get, job_id)
            if job.done or asyncio.get_running_loop().time() >= deadline:
                return job
            await asyncio.sleep(poll)


class JobToolbox:
    """An MCP toolbox plus the job tools, bound to one conversation."""

    def __init__(
        self,
        inner: Toolbox,
        launcher: JobLauncher,
        conversation_id: str,
        wait_seconds: float = 75.0,
    ) -> None:
        self.inner = inner
        self.launcher = launcher
        self.conversation_id = conversation_id
        self.wait_seconds = wait_seconds

    async def list_tools(self) -> list[ToolSpec]:
        specs = [*await self.inner.list_tools()]
        specs += [spec for name, spec in SPECS.items() if self.launcher.offers(TOOL_KINDS[name])]
        if self.launcher.offers("python_analysis"):
            specs.append(PYTHON_SPEC)
        return specs

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name in WAITING_TOOL_KINDS:
            started = time.perf_counter()
            outcome = await self._run_and_wait(name, WAITING_TOOL_KINDS[name], arguments)
            return replace(outcome, latency_ms=int((time.perf_counter() - started) * 1000))
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

    async def _run_and_wait(
        self, name: str, kind_name: str, arguments: dict[str, Any]
    ) -> ToolOutcome:
        try:
            job = await self.launcher.start(kind_name, arguments, self.conversation_id)
        except JobInputError as exc:
            return ToolOutcome.failure(name, arguments, str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolOutcome.failure(
                name, arguments, f"The job could not be queued ({type(exc).__name__}: {exc})."
            )
        job = await self.launcher.wait(job.id, self.wait_seconds)
        if job.status == "succeeded" and isinstance(job.result, dict):
            data = job.result
            sources = data.get("sources") or []
            price = sources[0] if sources else None
            return ToolOutcome(
                name=name,
                arguments=arguments,
                ok=True,
                payload={
                    "job_id": job.id,
                    "data": {"result": data.get("result"), "stdout": data.get("stdout", "")},
                    "inputs": data.get("inputs", []),
                    "source": "Python sandbox"
                    + (f" on {price['source']} price data" if price else ""),
                    "as_of": price.get("as_of") if price else None,
                },
            )
        if job.status in ("failed", "cancelled"):
            return ToolOutcome.failure(
                name, arguments, job.error or f"The analysis was {job.status}."
            )
        return ToolOutcome.failure(
            name,
            arguments,
            f"The analysis is still running (job {job.id}). Its result will be added to "
            "this conversation when it finishes; do not guess it.",
        )
