"""Financial Analysis MCP server.

Exposes market-data and analysis tools to the agent harness over MCP (streamable HTTP).
Every tool returns {data, source, as_of, units} so answers can always cite their source.

Run locally:  python -m financial_mcp.server   (listens on MCP_HOST:MCP_PORT, path /mcp)
"""

import os
from datetime import date
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from financial_mcp.envelope import envelope
from financial_mcp.indicators import (
    EXPLANATIONS,
    LOOKBACK_PERIOD,
    IndicatorError,
    analyse,
    parse_indicator,
    period_start,
)
from financial_mcp.market_data import (
    MAX_CANDLES,
    PriceDataError,
    build_quote,
    validate_period_interval,
)
from financial_mcp.sec import SOURCE_LABEL as SEC_SOURCE
from financial_mcp.sec import SecError, build_statement
from financial_mcp.services import get_services
from financial_mcp.symbols import (
    SOURCE_LABEL as DIRECTORY_SOURCE,
)
from financial_mcp.symbols import (
    DirectoryUnavailableError,
    NotNasdaqListedError,
)

SERVER_NAME = "financial-analysis"
SERVER_VERSION = "0.3.0"

mcp = MCPServer(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Market data and analysis tools for NASDAQ-listed stocks only. "
        "Every tool returns {data, source, as_of, units}; quote numbers only from these "
        "results and cite the source and as_of time."
    ),
)

PRICE_UNITS = {"prices": "USD", "volume": "shares"}


def _require_listing(symbol: str) -> dict[str, Any]:
    try:
        return get_services().directory.require(symbol).to_dict()
    except (NotNasdaqListedError, DirectoryUnavailableError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(description="Check that the Financial Analysis MCP server is reachable.")
def ping() -> dict[str, Any]:
    return envelope("pong", source=SERVER_NAME)


@mcp.tool(
    description=(
        "Find NASDAQ-listed securities by ticker or company name, e.g. 'apple' or 'NVD'. "
        "Use this to resolve a company name to its NASDAQ ticker before other tools."
    )
)
def search_symbol(query: str, limit: int = 10) -> dict[str, Any]:
    directory = get_services().directory
    try:
        matches = directory.search(query, limit=limit)
    except DirectoryUnavailableError as exc:
        raise ToolError(str(exc)) from exc
    return envelope(
        {"query": query, "matches": [m.to_dict() for m in matches]},
        source=DIRECTORY_SOURCE,
        as_of=directory.as_of,
    )


@mcp.tool(
    description=(
        "Latest daily price for a NASDAQ symbol: price, open, high, low, volume, previous close "
        "and change versus the previous trading day. Data may be delayed."
    )
)
def get_quote(symbol: str) -> dict[str, Any]:
    listing = _require_listing(symbol)
    services = get_services()
    try:
        candles = services.prices.history(listing["symbol"], period="5d", interval="1d")
        quote = build_quote(listing["symbol"], candles)
    except PriceDataError as exc:
        raise ToolError(str(exc)) from exc
    quote["name"] = listing["name"]
    return envelope(
        quote,
        source=services.prices.source,
        as_of=quote["trading_day"],
        units={"price": "USD", "change_percent": "percent", "volume": "shares"},
    )


@mcp.tool(
    description=(
        "OHLCV candles for a NASDAQ symbol. period: 5d, 1mo, 3mo, 6mo, ytd, 1y, 2y, 5y, 10y, max. "
        "interval: 5m, 15m, 30m (period up to 1mo), 1h (up to 1y), 1d, 1wk, 1mo. "
        "Prices are not adjusted for splits or dividends."
    )
)
def get_price_history(symbol: str, period: str = "6mo", interval: str = "1d") -> dict[str, Any]:
    listing = _require_listing(symbol)
    try:
        validate_period_interval(period, interval)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    services = get_services()
    try:
        candles = services.prices.history(listing["symbol"], period=period, interval=interval)
    except PriceDataError as exc:
        raise ToolError(str(exc)) from exc
    if not candles:
        raise ToolError(f"No price data returned for {listing['symbol']}.")

    truncated = len(candles) > MAX_CANDLES
    candles = candles[-MAX_CANDLES:]
    return envelope(
        {
            "symbol": listing["symbol"],
            "name": listing["name"],
            "period": period,
            "interval": interval,
            "adjusted": False,
            "count": len(candles),
            "truncated": truncated,
            "candles": [c.to_dict() for c in candles],
        },
        source=services.prices.source,
        as_of=candles[-1].time,
        units=PRICE_UNITS,
    )


MAX_INDICATORS = 8
DAILY_OR_LONGER = ("1d", "1wk", "1mo")


@mcp.tool(
    description=(
        "Technical indicators for a NASDAQ symbol, computed on real price candles: "
        "sma, ema, rsi, macd, bollinger, atr, vwap. Add a window with an underscore, e.g. "
        "['sma_50', 'rsi_14', 'macd']. Returns the latest value and the last 30 values of "
        "each, factual signals (e.g. RSI above 70) and a plain-language explanation of each "
        "indicator for beginners. period and interval as in get_price_history."
    )
)
def compute_indicators(
    symbol: str,
    indicators: list[str] | None = None,
    period: str = "6mo",
    interval: str = "1d",
) -> dict[str, Any]:
    listing = _require_listing(symbol)
    try:
        validate_period_interval(period, interval)
        requested = indicators or ["sma_20", "rsi_14", "macd"]
        if len(requested) > MAX_INDICATORS:
            raise IndicatorError(f"Ask for at most {MAX_INDICATORS} indicators at a time.")
        specs = list({spec.key: spec for spec in map(parse_indicator, requested)}.values())
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    # Fetch extra history so long windows (e.g. SMA 200) are warmed up for the period shown.
    extended = interval in DAILY_OR_LONGER and period in LOOKBACK_PERIOD
    fetch_period = LOOKBACK_PERIOD[period] if extended else period
    services = get_services()
    try:
        candles = services.prices.history(listing["symbol"], period=fetch_period, interval=interval)
    except PriceDataError as exc:
        raise ToolError(str(exc)) from exc
    if not candles:
        raise ToolError(f"No price data returned for {listing['symbol']}.")
    start = period_start(period, date.fromisoformat(candles[-1].time[:10])) if extended else None
    try:
        analysis = analyse(candles, specs, start)
    except IndicatorError as exc:
        raise ToolError(str(exc)) from exc
    return envelope(
        {
            "symbol": listing["symbol"],
            "name": listing["name"],
            "period": period,
            "interval": interval,
            "adjusted": False,
            **analysis,
            "explanations": {spec.kind: EXPLANATIONS[spec.kind] for spec in specs},
        },
        source=services.prices.source,
        as_of=analysis["last_bar"],
        units={"prices": "USD", "rsi": "0-100", "atr": "USD", "volume": "shares"},
    )


@mcp.tool(
    description=(
        "Financial statements from the company's SEC filings (10-K annual, 10-Q quarterly). "
        "statement: income (revenue, gross profit, operating income, net income, EPS), "
        "balance (cash, assets, liabilities, debt, equity) or cash_flow (operating cash flow, "
        "capex, free cash flow, dividends, buybacks). freq: annual or quarterly. years: 1-10. "
        "Values are in USD (EPS in USD per share); each period links to its filing."
    )
)
def get_financial_statements(
    symbol: str, statement: str = "income", freq: str = "annual", years: int = 5
) -> dict[str, Any]:
    listing = _require_listing(symbol)
    sec = get_services().sec
    if sec is None:
        raise ToolError("SEC data is not configured on this server.")
    years = max(1, min(int(years), 10))
    count = years if freq == "annual" else min(years * 4, 20)
    try:
        cik, filer_name = sec.lookup(listing["symbol"])
        data = build_statement(sec.company_facts(cik), cik, statement, freq, count)
    except SecError as exc:
        raise ToolError(str(exc)) from exc
    return envelope(
        {"symbol": listing["symbol"], "name": filer_name, "cik": cik, **data},
        source=SEC_SOURCE,
        as_of=data["latest_filed"],
        units={"values": "USD; EPS in USD per share; shares in shares"},
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION})


def _allowed_hosts() -> list[str]:
    # Host headers accepted by the MCP endpoint (DNS-rebinding protection).
    # "mcp:8100" is the Docker Compose service name used by the API container.
    default = "localhost:*,127.0.0.1:*,mcp:*"
    return [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", default).split(",") if h.strip()]


def create_app() -> Starlette:
    return mcp.streamable_http_app(
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_allowed_hosts(),
            allowed_origins=[],
        ),
    )


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8100")),
    )


if __name__ == "__main__":
    main()
