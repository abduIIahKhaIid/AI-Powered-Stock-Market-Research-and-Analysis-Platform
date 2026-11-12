from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from financial_mcp.server import mcp

ENVELOPE_KEYS = {"data", "source", "as_of", "units"}


async def call(name: str, arguments: dict[str, Any]) -> Any:
    return await mcp.call_tool(name, arguments)


def payload(result: Any) -> dict[str, Any]:
    assert not result.is_error, result
    return result.structured_content


async def test_tools_are_registered() -> None:
    names = {tool.name for tool in await mcp.list_tools()}
    assert {
        "ping",
        "search_symbol",
        "get_quote",
        "get_price_history",
        "compute_indicators",
    } <= names


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("ping", {}),
        ("search_symbol", {"query": "apple"}),
        ("get_quote", {"symbol": "AAPL"}),
        ("get_price_history", {"symbol": "NVDA", "period": "1mo", "interval": "1d"}),
    ],
)
async def test_every_tool_returns_the_standard_envelope(
    services: object, name: str, arguments: dict[str, Any]
) -> None:
    body = payload(await call(name, arguments))
    assert set(body) == ENVELOPE_KEYS
    assert body["source"]
    assert body["as_of"]


async def test_search_symbol(services: object) -> None:
    body = payload(await call("search_symbol", {"query": "nvidia", "limit": 3}))
    assert body["data"]["matches"][0]["symbol"] == "NVDA"
    assert "Nasdaq Trader" in body["source"]
    assert body["as_of"].startswith("2026-11-11T16:01")


async def test_get_quote(services: object) -> None:
    body = payload(await call("get_quote", {"symbol": "aapl"}))
    data = body["data"]
    assert data["symbol"] == "AAPL"
    assert data["name"] == "Apple Inc."
    assert data["price"] == 107.1
    assert data["previous_close"] == 105.0
    assert data["change_percent"] == 2.0
    assert body["as_of"] == "2026-11-11"
    assert body["units"]["price"] == "USD"


async def test_get_price_history(services: object, fake_prices: Any) -> None:
    body = payload(
        await call("get_price_history", {"symbol": "nvda", "period": "3mo", "interval": "1wk"})
    )
    data = body["data"]
    assert data["symbol"] == "NVDA" and data["count"] == 3 and data["truncated"] is False
    assert data["candles"][0] == {
        "time": "2026-11-09",
        "open": 100.0,
        "high": 103.0,
        "low": 99.0,
        "close": 102.0,
        "volume": 1_000_000,
    }
    assert fake_prices.calls[-1] == ("NVDA", "3mo", "1wk")


@pytest.mark.parametrize("tool", ["get_quote", "get_price_history"])
async def test_non_nasdaq_symbols_are_rejected(services: object, tool: str) -> None:
    # The MCP protocol layer turns ToolError into an `isError` result for the client.
    with pytest.raises(ToolError, match="not listed on NASDAQ"):
        await call(tool, {"symbol": "IBM"})


async def test_invalid_interval_is_rejected(services: object) -> None:
    with pytest.raises(ToolError, match="only available"):
        await call("get_price_history", {"symbol": "AAPL", "period": "1y", "interval": "5m"})


async def test_provider_failure_becomes_tool_error(services: object) -> None:
    with pytest.raises(ToolError, match="No price data"):
        await call("get_quote", {"symbol": "SMLC"})
