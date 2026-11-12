from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import fake_services, scripted_gateway, text_turn, tool_turn

from financial_mcp.server import mcp as financial_mcp_server
from financial_mcp.services import set_services
from stock_api import charts
from stock_api.agent import Agent, MCPToolbox, MemoryConversationStore
from stock_api.chart_spec import chart_from_tool
from stock_api.main import app


@pytest.fixture(autouse=True)
def market(tmp_path: Path) -> Iterator[None]:
    set_services(fake_services(tmp_path))
    yield
    set_services(None)


@pytest.fixture
def client() -> Iterator[httpx.AsyncClient]:
    app.dependency_overrides[charts.toolbox_dependency] = lambda: (
        lambda: MCPToolbox.connect(financial_mcp_server)
    )
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_agent_sends_a_chart_after_price_history() -> None:
    gateway, _ = scripted_gateway(
        tool_turn(("get_price_history", {"symbol": "AAPL", "period": "1mo", "interval": "1d"})),
        text_turn("AAPL closed at 107.1 on 2026-11-11."),
    )
    agent = Agent(
        gateway, lambda: MCPToolbox.connect(financial_mcp_server), MemoryConversationStore()
    )
    events = [event async for event in agent.run("AAPL last month?")]
    kinds = [event.type for event in events]
    chart = next(event.data for event in events if event.type == "chart")
    assert kinds.index("chart") == kinds.index("tool_result") + 1
    assert chart["kind"] == "price"
    assert (chart["symbol"], chart["period"], chart["interval"]) == ("AAPL", "1mo", "1d")
    assert chart["candles"][-1] == {
        "time": "2026-11-11",
        "open": 105.0,
        "high": 107.5,
        "low": 104.0,
        "close": 107.1,
        "volume": 1500000,
    }
    assert chart["source"] == "Fake price source (tests)"
    assert chart["adjusted"] is False
    assert chart["indicators"] == []


async def test_quote_does_not_make_a_chart() -> None:
    gateway, _ = scripted_gateway(
        tool_turn(("get_quote", {"symbol": "AAPL"})), text_turn("AAPL is 107.1.")
    )
    agent = Agent(
        gateway, lambda: MCPToolbox.connect(financial_mcp_server), MemoryConversationStore()
    )
    assert "chart" not in [event.type async for event in agent.run("AAPL?")]


def test_chart_from_tool_ignores_other_payloads() -> None:
    assert chart_from_tool("get_quote", {"data": {"candles": [1]}}) is None
    assert chart_from_tool("get_price_history", {"data": {"candles": []}}) is None
    assert chart_from_tool("get_price_history", "text") is None


async def test_prices_endpoint_returns_a_chart_spec(client: httpx.AsyncClient) -> None:
    response = await client.get("/prices/aapl", params={"period": "3mo", "interval": "1d"})
    assert response.status_code == 200
    spec = response.json()
    assert (spec["symbol"], spec["period"], spec["interval"]) == ("AAPL", "3mo", "1d")
    assert len(spec["candles"]) == 3


@pytest.mark.parametrize(
    ("path", "params", "status"),
    [
        ("/prices/IBM", {}, 404),  # not listed on NASDAQ
        ("/prices/AAPL", {"period": "1y", "interval": "5m"}, 400),  # intraday limit
        ("/prices/AAPL", {"period": "7y"}, 422),
        ("/prices/1ABC", {}, 422),  # not a ticker
        ("/prices/..%2Fetc", {}, 404),  # no such route
    ],
)
async def test_prices_endpoint_errors(
    client: httpx.AsyncClient, path: str, params: dict[str, str], status: int
) -> None:
    response = await client.get(path, params=params)
    assert response.status_code == status


async def test_prices_endpoint_reports_unreachable_service() -> None:
    @asynccontextmanager
    async def broken() -> AsyncIterator[Any]:
        raise ConnectionError("down")
        yield  # pragma: no cover

    app.dependency_overrides[charts.toolbox_dependency] = lambda: broken
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as plain:
            response = await plain.get("/prices/AAPL")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502


def test_indicator_results_turn_on_matching_chart_toggles() -> None:
    payload = {
        "data": {
            "symbol": "AAPL",
            "period": "6mo",
            "interval": "1d",
            "candles": [{"time": "2026-11-11", "close": 1}],
            "indicators": {"sma_50": {}, "rsi_14": {}, "atr_14": {}, "macd": {}},
        },
        "source": "s",
    }
    spec = chart_from_tool("compute_indicators", payload)
    assert spec is not None
    assert spec["indicators"] == ["sma50", "rsi", "macd"]
