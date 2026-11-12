"""Job kinds: what each background job does, its queue and its time limits (SCRUM-32)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..agent.toolbox import MCPToolbox, ToolOutcome
from .store import JobStore

ToolRunner = Callable[[str, dict[str, Any]], ToolOutcome]

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MAX_SCAN_SYMBOLS = 10


class JobCancelled(Exception):
    """The user cancelled the job; it stops at the next progress update."""


class JobInputError(ValueError):
    """The job's parameters are not valid."""


class JobContext:
    """What a handler uses to report progress; also where cancellation is noticed."""

    def __init__(self, store: JobStore, job_id: str) -> None:
        self.store = store
        self.job_id = job_id

    def progress(self, percent: int, stage: str) -> None:
        if self.store.get(self.job_id).cancel_requested:
            raise JobCancelled
        self.store.update(self.job_id, progress=percent, stage=stage)


@dataclass(frozen=True)
class JobKind:
    name: str
    title: str
    queue: str
    soft_limit: int
    hard_limit: int
    validate: Callable[[dict[str, Any]], dict[str, Any]]
    handler: Callable[[dict[str, Any], JobContext], Any]
    max_attempts: int = 3


def mcp_tool_runner(server: Any, timeout: float = 60.0) -> ToolRunner:
    """Calls one MCP tool per invocation, from synchronous worker code."""

    async def call(name: str, arguments: dict[str, Any]) -> ToolOutcome:
        async with MCPToolbox.connect(server, timeout=timeout) as toolbox:
            return await toolbox.call(name, arguments)

    def run(name: str, arguments: dict[str, Any]) -> ToolOutcome:
        return asyncio.run(call(name, arguments))

    return run


# --- indicator scan: indicators for several symbols -------------------------------------


def validate_scan(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("symbols")
    if not isinstance(raw, list) or not raw:
        raise JobInputError("symbols must be a non-empty list of tickers.")
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in raw))
    if len(symbols) > MAX_SCAN_SYMBOLS:
        raise JobInputError(f"Scan at most {MAX_SCAN_SYMBOLS} symbols at a time.")
    bad = [s for s in symbols if not _TICKER.match(s)]
    if bad:
        raise JobInputError(f"Not valid tickers: {', '.join(bad)}.")
    indicators = params.get("indicators") or ["rsi_14", "macd", "sma_50"]
    if not isinstance(indicators, list) or len(indicators) > 8:
        raise JobInputError("indicators must be a list of at most 8 names.")
    period = params.get("period", "6mo")
    if period not in {"1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y"}:
        raise JobInputError(f"Unsupported period '{period}'.")
    return {"symbols": symbols, "indicators": indicators, "period": period}


def indicator_scan(runner: ToolRunner) -> Callable[[dict[str, Any], JobContext], Any]:
    def handle(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        symbols = params["symbols"]
        rows: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        for index, symbol in enumerate(symbols):
            ctx.progress(
                int(index / len(symbols) * 100),
                f"Computing indicators for {symbol} ({index + 1} of {len(symbols)})",
            )
            outcome = runner(
                "compute_indicators",
                {"symbol": symbol, "indicators": params["indicators"], "period": params["period"]},
            )
            if not outcome.ok:
                rows[symbol] = {"error": outcome.error}
                continue
            data = outcome.payload["data"]
            rows[symbol] = {
                "last_close": data["last_close"],
                "last_bar": data["last_bar"],
                "latest": {k: v["latest"] for k, v in data["indicators"].items()},
                "signals": data["signals"],
            }
            if outcome.source:
                sources[outcome.source] = outcome.as_of
        ctx.progress(100, "Done")
        return {
            "symbols": symbols,
            "indicators": params["indicators"],
            "period": params["period"],
            "rows": rows,
            "sources": [{"source": s, "as_of": a} for s, a in sources.items()],
        }

    return handle


# --- scheduled refresh of the NASDAQ symbol directory -----------------------------------


def refresh_directory(runner: ToolRunner) -> Callable[[dict[str, Any], JobContext], Any]:
    def handle(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        ctx.progress(10, "Refreshing the NASDAQ symbol directory")
        outcome = runner("search_symbol", {"query": "A", "limit": 1})
        if not outcome.ok:
            raise RuntimeError(outcome.error or "Directory refresh failed.")
        ctx.progress(100, "Done")
        return {"directory_as_of": outcome.as_of}

    return handle


def build_registry(runner: ToolRunner) -> dict[str, JobKind]:
    kinds = [
        JobKind(
            "indicator_scan",
            "Indicator scan",
            queue="analysis",
            soft_limit=120,
            hard_limit=150,
            validate=validate_scan,
            handler=indicator_scan(runner),
        ),
        JobKind(
            "refresh_directory",
            "Symbol directory refresh",
            queue="ingest",
            soft_limit=60,
            hard_limit=90,
            validate=lambda params: {},
            handler=refresh_directory(runner),
        ),
    ]
    return {kind.name: kind for kind in kinds}
