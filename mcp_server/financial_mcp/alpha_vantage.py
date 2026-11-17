"""Alpha Vantage as a second market-data source (SCRUM-22).

The client talks to the official remote Alpha Vantage MCP server
(https://mcp.alphavantage.co/mcp?apikey=...). It calls a function such as GLOBAL_QUOTE or
TIME_SERIES_DAILY directly when the server lists it, or through the server's TOOL_CALL
entry point when it only offers TOOL_LIST/TOOL_CALL.

The free tier allows about 25 requests a day, so every response is cached on disk with a
time to live, calls are spaced out, and a daily counter stops before the limit. When the
limit is reached or Alpha Vantage refuses, a stale cached copy is used if there is one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .market_data import Candle, PriceDataError, PriceProvider

logger = logging.getLogger("financial_mcp.alpha_vantage")

DEFAULT_URL = "https://mcp.alphavantage.co/mcp"
SOURCE_LABEL = "Alpha Vantage (official MCP server)"
DAILY_LIMIT = 25
TTL = {
    "GLOBAL_QUOTE": 60,
    "TIME_SERIES_DAILY": 12 * 3600,
    "TIME_SERIES_WEEKLY": 24 * 3600,
    "TIME_SERIES_MONTHLY": 24 * 3600,
    "COMPANY_OVERVIEW": 24 * 3600,
}
SERIES = {
    "1d": ("TIME_SERIES_DAILY", "Time Series (Daily)"),
    "1wk": ("TIME_SERIES_WEEKLY", "Weekly Time Series"),
    "1mo": ("TIME_SERIES_MONTHLY", "Monthly Time Series"),
}
PERIOD_DAYS = {"5d": 7, "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827}
_LIMIT_WORDS = ("rate limit", "call frequency", "requests per day", "premium", "25 requests")

Caller = Callable[[str, dict[str, Any]], Any]


class AlphaVantageError(RuntimeError):
    pass


class AlphaVantageLimitError(AlphaVantageError):
    """The free-tier limit is reached, or the function needs a premium plan."""


def _parse(value: Any) -> Any:
    """MCP text content to JSON; some servers wrap the JSON in a string once more."""
    for _ in range(2):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                break
    return value


class McpCaller:
    """Calls Alpha Vantage functions on its MCP server, from synchronous tool code."""

    def __init__(
        self, api_key: str, url: str = DEFAULT_URL, timeout: float = 30.0, target: Any = None
    ) -> None:
        # `target` lets tests pass an in-process MCP server instead of the URL.
        self.target = target if target is not None else f"{url}?apikey={api_key}"
        self.timeout = timeout
        self._tools: set[str] | None = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="alpha-vantage")

    async def _call(self, function: str, params: dict[str, Any]) -> Any:
        from mcp import Client

        result = None
        # Errors are raised after the session closes: raised inside it, they would arrive
        # wrapped in an ExceptionGroup from the session's task group.
        async with Client(self.target, read_timeout_seconds=self.timeout) as client:
            if self._tools is None:
                self._tools = {tool.name for tool in (await client.list_tools()).tools}
            if function in self._tools:
                result = await client.call_tool(function, params)
            elif "TOOL_CALL" in self._tools:
                result = await client.call_tool(
                    "TOOL_CALL", {"tool_name": function, "arguments": params}
                )
        if result is None:
            raise AlphaVantageError(f"The Alpha Vantage MCP server does not offer {function}.")
        text = "\n".join(getattr(block, "text", "") for block in result.content or [])
        if result.is_error:
            raise AlphaVantageError(text or f"{function} failed.")
        data = _parse(text) if text else result.structured_content
        if isinstance(data, dict) and set(data) == {"result"}:
            data = _parse(data["result"])
        return data

    def __call__(self, function: str, params: dict[str, Any]) -> Any:
        # Tools run inside the MCP server's event loop, so the client gets its own thread.
        future = self._pool.submit(asyncio.run, self._call(function, params))
        return future.result(timeout=self.timeout + 15)


class AlphaVantageClient:
    def __init__(
        self,
        caller: Caller,
        cache_dir: Path,
        daily_limit: int = DAILY_LIMIT,
        min_interval: float = 1.2,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.caller = caller
        self.cache_dir = Path(cache_dir) / "alpha_vantage"
        self.daily_limit = daily_limit
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._last_call = 0.0
        self._lock = threading.Lock()

    def _path(self, function: str, params: dict[str, Any]) -> Path:
        key = json.dumps([function, params], sort_keys=True)
        return self.cache_dir / f"{function}-{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"

    def _budget_file(self) -> Path:
        today = datetime.fromtimestamp(self.clock(), UTC).date().isoformat()
        return self.cache_dir / f"calls-{today}.txt"

    def calls_today(self) -> int:
        path = self._budget_file()
        return int(path.read_text()) if path.exists() else 0

    def fetch(self, function: str, params: dict[str, Any], ttl: float | None = None) -> Any:
        ttl = TTL.get(function, 3600) if ttl is None else ttl
        path = self._path(function, params)
        cached = json.loads(path.read_text()) if path.exists() else None
        if cached and problem_in(cached.get("data")) is not None:
            cached = None  # an error saved by an older version: never serve it
        if cached and self.clock() - cached["fetched_at"] < ttl:
            logger.info("alpha_vantage cache hit %s %s", function, params.get("symbol", ""))
            return cached["data"]
        logger.info("alpha_vantage cache miss %s %s", function, params.get("symbol", ""))
        try:
            data = self._request(function, params)
        except AlphaVantageError as exc:
            if cached:
                logger.warning("alpha_vantage using a stale copy of %s: %s", function, exc)
                return cached["data"]
            raise
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_text(json.dumps({"fetched_at": self.clock(), "data": data}))
        partial.replace(path)
        return data

    def _request(self, function: str, params: dict[str, Any]) -> Any:
        with self._lock:
            used = self.calls_today()
            if used >= self.daily_limit:
                raise AlphaVantageLimitError(
                    f"The Alpha Vantage free-tier limit of {self.daily_limit} requests a day is "
                    "used up; try again tomorrow."
                )
            wait = self.min_interval - (self.clock() - self._last_call)
            if wait > 0:
                self.sleep(wait)
            self._last_call = self.clock()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._budget_file().write_text(str(used + 1))
        try:
            data = self.caller(function, params)
        except AlphaVantageError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport errors from the MCP client
            raise AlphaVantageError(f"Alpha Vantage could not be reached ({exc}).") from exc
        problem = problem_in(data)
        if problem is not None:
            raise problem
        if not data:
            raise AlphaVantageError(f"Alpha Vantage returned no data for {function}.")
        return data


def problem_in(data: Any) -> AlphaVantageError | None:
    """The error an Alpha Vantage answer carries, or None for real data.

    Errors come as the API's own envelope ({"Error Message"|"Information"|"Note": ...}) or,
    from the official MCP server, as {"error": {"type": ..., "message": ...}}.
    """
    if not isinstance(data, dict):
        return AlphaVantageError("Alpha Vantage returned no data.")
    error = data.get("error")
    if isinstance(error, dict) and len(data) <= 2:
        kind = str(error.get("type") or "")
        message = str(error.get("message") or error.get("detail") or kind or "unknown error")
        if kind == "invalid_api_key":
            return AlphaVantageError(
                f"Alpha Vantage rejected the API key ({message}). Check ALPHAVANTAGE_API_KEY."
            )
        if kind == "rate_limit" or any(word in message.lower() for word in _LIMIT_WORDS):
            return AlphaVantageLimitError(f"Alpha Vantage: {message}")
        return AlphaVantageError(f"Alpha Vantage: {message}")
    notice = data.get("Error Message") or data.get("Information") or data.get("Note")
    if notice and len(data) <= 2:
        if any(word in str(notice).lower() for word in _LIMIT_WORDS):
            return AlphaVantageLimitError(f"Alpha Vantage: {notice}")
        return AlphaVantageError(f"Alpha Vantage: {notice}")
    return None


def _float(value: Any) -> float | None:
    try:
        number = float(str(value).rstrip("%"))
    except (TypeError, ValueError):
        return None
    return number


class AlphaVantagePrices:
    """Daily, weekly and monthly candles from Alpha Vantage (the free tier has no intraday)."""

    source = SOURCE_LABEL

    def __init__(self, client: AlphaVantageClient) -> None:
        self.client = client

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        if interval not in SERIES:
            raise PriceDataError(
                "The Alpha Vantage fallback has daily, weekly and monthly bars only."
            )
        function, key = SERIES[interval]
        params = {"symbol": symbol}
        if function == "TIME_SERIES_DAILY":
            params["outputsize"] = "compact"  # the last 100 days; full history is premium
        try:
            data = self.client.fetch(function, params)
        except AlphaVantageError as exc:
            raise PriceDataError(str(exc)) from exc
        rows = data.get(key)
        if not isinstance(rows, dict) or not rows:
            raise PriceDataError(f"Alpha Vantage returned no {interval} bars for {symbol}.")
        candles = []
        for day, bar in sorted(rows.items()):
            values = [_float(bar.get(k)) for k in ("1. open", "2. high", "3. low", "4. close")]
            if None in values:
                continue
            open_, high, low, close = (v for v in values if v is not None)
            candles.append(
                Candle(day, open_, high, low, close, int(_float(bar.get("5. volume")) or 0))
            )
        return _trim(candles, period)


def _trim(candles: list[Candle], period: str) -> list[Candle]:
    if not candles or period in ("max", "10y"):
        return candles
    last = date.fromisoformat(candles[-1].time[:10])
    start = date(last.year, 1, 1) if period == "ytd" else last - timedelta(PERIOD_DAYS[period])
    return [c for c in candles if date.fromisoformat(c.time[:10]) > start]


class FallbackPrices:
    """The primary provider (yfinance), and Alpha Vantage when the primary fails."""

    def __init__(self, primary: PriceProvider, secondary: PriceProvider) -> None:
        self.primary = primary
        self.secondary = secondary
        self._local = threading.local()

    @property
    def source(self) -> str:
        return getattr(self._local, "source", self.primary.source)

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        try:
            candles = self.primary.history(symbol, period, interval)
            self._local.source = self.primary.source
            return candles
        except PriceDataError as first:
            logger.warning("primary prices failed for %s, trying Alpha Vantage: %s", symbol, first)
            try:
                candles = self.secondary.history(symbol, period, interval)
            except PriceDataError as second:
                raise PriceDataError(
                    f"{first} Fallback to Alpha Vantage also failed: {second}"
                ) from second
            self._local.source = (
                f"{self.secondary.source}, used because {self.primary.source} failed"
            )
            return candles

    def __getattr__(self, name: str) -> Any:
        # Optional extras such as next_earnings_date come from the primary.
        return getattr(self.primary, name)


OVERVIEW_FIELDS = {
    "market_cap": "MarketCapitalization",
    "pe_ratio": "PERatio",
    "peg_ratio": "PEGRatio",
    "eps": "EPS",
    "dividend_yield_pct": "DividendYield",
    "beta": "Beta",
    "week_52_high": "52WeekHigh",
    "week_52_low": "52WeekLow",
    "analyst_target_price": "AnalystTargetPrice",
    "profit_margin_pct": "ProfitMargin",
    "revenue_ttm": "RevenueTTM",
    "shares_outstanding": "SharesOutstanding",
}
PERCENT_FIELDS = {"dividend_yield_pct", "profit_margin_pct"}


def company_overview(client: AlphaVantageClient, symbol: str) -> dict[str, Any]:
    data = client.fetch("COMPANY_OVERVIEW", {"symbol": symbol})
    if not data.get("Symbol"):
        raise AlphaVantageError(f"Alpha Vantage has no company overview for {symbol}.")
    figures: dict[str, float | None] = {}
    for key, field in OVERVIEW_FIELDS.items():
        value = _float(data.get(field))
        if value is not None and key in PERCENT_FIELDS:
            value = round(value * 100, 2)  # Alpha Vantage gives fractions
        figures[key] = value
    description = str(data.get("Description") or "")
    return {
        "symbol": data["Symbol"],
        "name": data.get("Name"),
        "exchange": data.get("Exchange"),
        "sector": data.get("Sector"),
        "industry": data.get("Industry"),
        "country": data.get("Country"),
        "currency": data.get("Currency"),
        "fiscal_year_end": data.get("FiscalYearEnd"),
        "latest_quarter": data.get("LatestQuarter"),
        "description": description[:600] + ("…" if len(description) > 600 else ""),
        **figures,
    }
