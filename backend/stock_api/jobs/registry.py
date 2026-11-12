"""Job kinds: what each background job does, its queue and its time limits (SCRUM-32).

Handlers raise TransientJobError for provider, network and rate-limit errors; the runner
then retries the job with exponential backoff (SCRUM-34).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..agent.toolbox import MCPToolbox, ToolOutcome
from .results import ResultStore, check_name
from .store import JobStore

ToolRunner = Callable[[str, dict[str, Any]], ToolOutcome]

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MAX_SCAN_SYMBOLS = 10


class JobCancelled(Exception):
    """The user cancelled the job; it stops at the next progress update."""


class JobInputError(ValueError):
    """The job's parameters are not valid."""


class TransientJobError(RuntimeError):
    """A temporary provider, network or rate-limit error: worth another attempt."""


# Error text from data providers and the MCP transport that means "try again later".
_TRANSIENT = re.compile(
    r"rate.?limit|too many requests|\b429\b|\b50[234]\b|timed? ?out|timeout|temporar"
    r"|unavailable|connection|connect error|network|reset by peer|try again",
    re.IGNORECASE,
)


def is_transient_message(text: str | None) -> bool:
    return bool(text) and bool(_TRANSIENT.search(text or ""))


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TransientJobError | ConnectionError | TimeoutError):
        return True
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 502, 503, 504}
    return False


class JobContext:
    """What a handler uses to report progress and save files; also notices cancellation."""

    def __init__(
        self,
        store: JobStore,
        job_id: str,
        attempt: int = 1,
        max_attempts: int = 1,
        results: ResultStore | None = None,
    ) -> None:
        self.store = store
        self.job_id = job_id
        self.attempt = attempt
        self.max_attempts = max_attempts
        self.results = results
        self.files: list[dict[str, Any]] = []

    @property
    def last_attempt(self) -> bool:
        return self.attempt >= self.max_attempts

    def progress(self, percent: int, stage: str) -> None:
        if self.store.get(self.job_id).cancel_requested:
            raise JobCancelled
        self.store.update(self.job_id, progress=percent, stage=stage)

    def check(self, outcome: ToolOutcome) -> ToolOutcome:
        """Raise TransientJobError for a temporary tool error, unless this is the last try."""
        if not outcome.ok and is_transient_message(outcome.error) and not self.last_attempt:
            raise TransientJobError(f"{outcome.name}: {outcome.error}")
        return outcome

    def save_file(self, name: str, data: bytes | str, media_type: str) -> None:
        """Save a downloadable file for this job; saving the same name again replaces it."""
        if self.results is None:
            return
        check_name(name)
        raw = data.encode() if isinstance(data, str) else data
        size = self.results.write(self.job_id, name, raw)
        self.files = [f for f in self.files if f["name"] != name]
        self.files.append({"name": name, "bytes": size, "media_type": media_type})


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
    # One line for the saved analyses list, from the params and the result.
    summarize: Callable[[dict[str, Any], Any], str] | None = None


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
            outcome = ctx.check(
                runner(
                    "compute_indicators",
                    {
                        "symbol": symbol,
                        "indicators": params["indicators"],
                        "period": params["period"],
                    },
                )
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
        ctx.progress(100, "Saving results")
        ctx.save_file("indicator_scan.csv", scan_csv(rows), "text/csv")
        return {
            "symbols": symbols,
            "indicators": params["indicators"],
            "period": params["period"],
            "rows": rows,
            "sources": [{"source": s, "as_of": a} for s, a in sources.items()],
        }

    return handle


def scan_csv(rows: dict[str, Any]) -> str:
    """One line per symbol: last close, the latest value of each indicator, and signals."""
    columns = sorted({name for row in rows.values() for name in row.get("latest", {})})
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["symbol", "last_bar", "last_close", *columns, "signals", "error"])
    for symbol, row in rows.items():
        latest = row.get("latest", {})
        values = [
            json.dumps(latest[c]) if isinstance(latest.get(c), dict) else latest.get(c, "")
            for c in columns
        ]
        signals = "; ".join(str(s) for s in row.get("signals", []))
        writer.writerow(
            [
                symbol,
                row.get("last_bar", ""),
                row.get("last_close", ""),
                *values,
                signals,
                row.get("error", ""),
            ]
        )
    return out.getvalue()


def summarize_scan(params: dict[str, Any], result: Any) -> str:
    names = ", ".join(params["indicators"])
    return f"{names} for {', '.join(params['symbols'])} ({params['period']})"


# --- scheduled refresh of the NASDAQ symbol directory -----------------------------------


def refresh_directory(runner: ToolRunner) -> Callable[[dict[str, Any], JobContext], Any]:
    def handle(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        ctx.progress(10, "Refreshing the NASDAQ symbol directory")
        outcome = ctx.check(runner("search_symbol", {"query": "A", "limit": 1}))
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
            summarize=summarize_scan,
        ),
        JobKind(
            "refresh_directory",
            "Symbol directory refresh",
            queue="ingest",
            soft_limit=60,
            hard_limit=90,
            validate=lambda params: {},
            handler=refresh_directory(runner),
            summarize=lambda params, result: "NASDAQ symbol directory refreshed",
        ),
    ]
    return {kind.name: kind for kind in kinds}
