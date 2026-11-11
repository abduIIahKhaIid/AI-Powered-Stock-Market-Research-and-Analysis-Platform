"""Financial Analysis MCP server.

Exposes market-data and analysis tools to the agent harness over MCP (streamable HTTP).
Every tool returns {data, source, as_of, units} so answers can always cite their source.

Run locally:  python -m financial_mcp.server   (listens on MCP_HOST:MCP_PORT, path /mcp)
"""

import os
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from financial_mcp.envelope import envelope
from financial_mcp.market_data import (
    MAX_CANDLES,
    PriceDataError,
    build_quote,
    validate_period_interval,
)
from financial_mcp.services import get_services
from financial_mcp.symbols import (
    SOURCE_LABEL as DIRECTORY_SOURCE,
)
from financial_mcp.symbols import (
    DirectoryUnavailableError,
    NotNasdaqListedError,
)

SERVER_NAME = "financial-analysis"
SERVER_VERSION = "0.2.0"

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
