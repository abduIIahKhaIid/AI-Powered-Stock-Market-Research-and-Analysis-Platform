"""SCRUM-22: Alpha Vantage as the second data source, through its MCP server."""

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FakePrices
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from financial_mcp.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageError,
    AlphaVantageLimitError,
    AlphaVantagePrices,
    FallbackPrices,
    McpCaller,
    company_overview,
)
from financial_mcp.market_data import PriceDataError
from financial_mcp.server import mcp
from financial_mcp.services import Services, set_services


def daily(days: int = 60, start_close: float = 100.0) -> dict[str, Any]:
    rows = {}
    for i in range(days):
        day = f"2026-{9 + (i // 28):02d}-{(i % 28) + 1:02d}"
        close = start_close + i
        rows[day] = {
            "1. open": f"{close - 1:.4f}",
            "2. high": f"{close + 1:.4f}",
            "3. low": f"{close - 2:.4f}",
            "4. close": f"{close:.4f}",
            "5. volume": "1000",
        }
    return {"Meta Data": {"2. Symbol": "SMLC"}, "Time Series (Daily)": rows}


OVERVIEW = {
    "Symbol": "AAPL",
    "Name": "Apple Inc",
    "Exchange": "NASDAQ",
    "Sector": "TECHNOLOGY",
    "Industry": "ELECTRONIC COMPUTERS",
    "Description": "Apple designs phones. " * 50,
    "MarketCapitalization": "3400000000000",
    "PERatio": "35.2",
    "PEGRatio": "None",
    "EPS": "6.6",
    "DividendYield": "0.0044",
    "ProfitMargin": "0.24",
    "52WeekHigh": "260.1",
    "52WeekLow": "164.08",
    "LatestQuarter": "2026-09-30",
}


class Caller:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, function: str, params: dict[str, Any]) -> Any:
        self.calls.append((function, params))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self) -> None:
        self.now = 1_794_000_000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def client(tmp_path: Path, caller: Caller, clock: Clock, limit: int = 25) -> AlphaVantageClient:
    return AlphaVantageClient(caller, tmp_path, limit, 1.2, clock, clock.sleep)


# --- client: cache, spacing and the daily limit --------------------------------------


def test_responses_are_cached_until_their_time_to_live(tmp_path: Path) -> None:
    caller, clock = Caller({"Global Quote": {"05. price": "1"}}, {"Global Quote": {}}), Clock()
    av = client(tmp_path, caller, clock)
    first = av.fetch("GLOBAL_QUOTE", {"symbol": "AAPL"})
    assert av.fetch("GLOBAL_QUOTE", {"symbol": "AAPL"}) == first and len(caller.calls) == 1
    clock.now += 61  # quotes live 60 s
    av.fetch("GLOBAL_QUOTE", {"symbol": "AAPL"})
    assert len(caller.calls) == 2 and av.calls_today() == 2
    assert clock.slept == []  # 61 s apart, no need to wait


def test_calls_are_spaced_out(tmp_path: Path) -> None:
    caller, clock = Caller({"Symbol": "A"}, {"Symbol": "B"}), Clock()
    av = client(tmp_path, caller, clock)
    av.fetch("COMPANY_OVERVIEW", {"symbol": "A"})
    av.fetch("COMPANY_OVERVIEW", {"symbol": "B"})
    assert clock.slept == [pytest.approx(1.2)]


def test_the_daily_limit_stops_calls_and_stale_copies_are_used(tmp_path: Path) -> None:
    caller, clock = Caller({"Symbol": "A"}), Clock()
    av = client(tmp_path, caller, clock, limit=1)
    av.fetch("COMPANY_OVERVIEW", {"symbol": "A"})
    clock.now += 25 * 3600  # a day later the copy is stale, and a new day has a fresh budget
    caller.answers.append({"Information": "We have detected your API key... 25 requests per day"})
    assert av.fetch("COMPANY_OVERVIEW", {"symbol": "A"}) == {"Symbol": "A"}
    with pytest.raises(AlphaVantageLimitError, match="25 requests a day|limit of 1"):
        av.fetch("COMPANY_OVERVIEW", {"symbol": "B"})


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ({"Error Message": "Invalid API call."}, AlphaVantageError),
        ({"Information": "This is a premium endpoint."}, AlphaVantageLimitError),
        (
            {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is..."},
            AlphaVantageLimitError,
        ),
        (ConnectionError("refused"), AlphaVantageError),
        ("not json", AlphaVantageError),
    ],
)
def test_alpha_vantage_errors(tmp_path: Path, answer: Any, error: type[Exception]) -> None:
    av = client(tmp_path, Caller(answer), Clock())
    with pytest.raises(error):
        av.fetch("TIME_SERIES_DAILY", {"symbol": "AAPL"})


# --- prices and the fallback ---------------------------------------------------------


def test_daily_candles_are_parsed_and_trimmed_to_the_period(tmp_path: Path) -> None:
    caller = Caller(daily())
    prices = AlphaVantagePrices(client(tmp_path, caller, Clock()))
    candles = prices.history("SMLC", "1mo", "1d")
    assert caller.calls == [("TIME_SERIES_DAILY", {"symbol": "SMLC", "outputsize": "compact"})]
    assert candles[-1].time == "2026-11-04" and candles[-1].close == 159.0
    assert all(c.time > "2026-10-04" for c in candles) and len(candles) == 28
    with pytest.raises(PriceDataError, match="daily, weekly and monthly"):
        prices.history("SMLC", "5d", "5m")


def test_fallback_uses_alpha_vantage_only_when_the_primary_fails(tmp_path: Path) -> None:
    caller = Caller(daily())
    fallback = FallbackPrices(FakePrices(), AlphaVantagePrices(client(tmp_path, caller, Clock())))
    assert fallback.history("AAPL", "1mo", "1d")[-1].close == 107.1
    assert fallback.source == "Fake price source (tests)" and caller.calls == []
    candles = fallback.history("SMLC", "6mo", "1d")  # FakePrices fails for SMLC
    assert candles[-1].close == 159.0
    assert fallback.source.startswith("Alpha Vantage (official MCP server), used because")


def test_fallback_explains_when_both_sources_fail(tmp_path: Path) -> None:
    caller = Caller({"Information": "25 requests per day reached"})
    fallback = FallbackPrices(FakePrices(), AlphaVantagePrices(client(tmp_path, caller, Clock())))
    with pytest.raises(PriceDataError, match="No price data returned for SMLC.*Fallback to Alpha"):
        fallback.history("SMLC", "6mo", "1d")


def test_company_overview_fields(tmp_path: Path) -> None:
    overview = company_overview(client(tmp_path, Caller(OVERVIEW), Clock()), "AAPL")
    assert overview["market_cap"] == 3.4e12 and overview["pe_ratio"] == 35.2
    assert overview["peg_ratio"] is None
    assert overview["dividend_yield_pct"] == 0.44 and overview["profit_margin_pct"] == 24.0
    assert overview["description"].endswith("…") and len(overview["description"]) == 601


# --- the tools -------------------------------------------------------------------------


@pytest.fixture
def av_services(directory: Any, tmp_path: Path) -> Any:
    caller = Caller(daily(), OVERVIEW)
    av = client(tmp_path, caller, Clock())
    prices = FallbackPrices(FakePrices(), AlphaVantagePrices(av))
    set_services(Services(directory=directory, prices=prices, alpha_vantage=av))
    yield caller
    set_services(None)


async def structured(name: str, arguments: dict[str, Any]) -> Any:
    return getattr(await mcp.call_tool(name, arguments), "structured_content", None)


async def test_tools_fall_back_to_alpha_vantage(av_services: Caller) -> None:
    history = await structured("get_price_history", {"symbol": "SMLC", "period": "1mo"})
    assert history["source"].startswith("Alpha Vantage (official MCP server), used because")
    assert history["data"]["candles"][-1]["close"] == 159.0
    # The cached series also feeds the indicators, without another request.
    indicators = await structured(
        "compute_indicators", {"symbol": "SMLC", "indicators": ["rsi_14"], "period": "1mo"}
    )
    assert indicators["data"]["last_close"] == 159.0
    assert indicators["source"].startswith("Alpha Vantage")
    assert [function for function, _ in av_services.calls] == ["TIME_SERIES_DAILY"]

    overview = await structured("get_company_overview", {"symbol": "AAPL"})
    assert overview["data"]["sector"] == "TECHNOLOGY"
    assert overview["source"] == "Alpha Vantage (official MCP server)"
    assert overview["as_of"] == "2026-09-30"


async def test_overview_without_a_key(services: Any) -> None:
    with pytest.raises(ToolError, match="ALPHAVANTAGE_API_KEY"):
        await mcp.call_tool("get_company_overview", {"symbol": "AAPL"})


# --- the MCP protocol: direct tools or TOOL_CALL ---------------------------------------


def direct_server() -> MCPServer:
    server = MCPServer(name="alpha-vantage-direct")

    @server.tool(name="GLOBAL_QUOTE")
    def global_quote(symbol: str) -> str:
        return json.dumps({"Global Quote": {"01. symbol": symbol, "05. price": "231.5"}})

    return server


def progressive_server() -> MCPServer:
    server = MCPServer(name="alpha-vantage-progressive")

    @server.tool(name="TOOL_LIST")
    def tool_list() -> str:
        return json.dumps(["GLOBAL_QUOTE", "TIME_SERIES_DAILY"])

    @server.tool(name="TOOL_CALL")
    def tool_call(tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name != "GLOBAL_QUOTE":
            raise ValueError("unknown function")
        return json.dumps({"Global Quote": {"01. symbol": arguments["symbol"], "05. price": "1"}})

    return server


@pytest.mark.parametrize(("server", "price"), [(direct_server, "231.5"), (progressive_server, "1")])
def test_mcp_caller_finds_the_function(server: Any, price: str) -> None:
    caller = McpCaller("demo", target=server())
    answer = caller("GLOBAL_QUOTE", {"symbol": "AAPL"})
    assert answer == {"Global Quote": {"01. symbol": "AAPL", "05. price": price}}


def test_mcp_caller_reports_missing_functions() -> None:
    with pytest.raises(AlphaVantageError, match="does not offer RSI"):
        McpCaller("demo", target=direct_server())("RSI", {"symbol": "AAPL"})
