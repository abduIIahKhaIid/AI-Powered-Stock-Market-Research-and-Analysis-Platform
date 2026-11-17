"""SCRUM-23: Redis TTL cache for tools, durable market data and the refresh tool."""

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conftest import FakePrices
from test_valuation import UA, fetch

from financial_mcp.cache import (
    DAILY_TTL,
    INTRADAY_TTL,
    QUOTE_TTL,
    MemoryCache,
    cache_key,
    cached_tool,
    clear_symbol,
)
from financial_mcp.market_data import Candle, PriceDataError
from financial_mcp.sec import RateLimiter, SecClient
from financial_mcp.server import mcp
from financial_mcp.services import Services, set_services
from financial_mcp.store import MemoryMarketStore, RecordingPrices, fact_rows


class Flaky(FakePrices):
    """Fails while `down` is set, like Yahoo Finance having a bad day."""

    def __init__(self) -> None:
        super().__init__()
        self.down = False

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        if self.down:
            raise PriceDataError("Price provider error: Yahoo is down.")
        return super().history(symbol, period, interval)


@pytest.fixture
def setup(directory: Any, tmp_path: Path) -> Any:
    prices, cache, store = Flaky(), MemoryCache(), MemoryMarketStore()
    sec = SecClient(UA, tmp_path, fetcher=fetch, limiter=RateLimiter(interval=0.0))
    services = Services(
        directory=directory,
        prices=RecordingPrices(prices, store),
        sec=sec,
        cache=cache,
        store=store,
    )
    set_services(services)
    yield prices, cache, store
    set_services(None)


async def call(name: str, arguments: dict[str, Any]) -> Any:
    return getattr(await mcp.call_tool(name, arguments), "structured_content", None)


async def test_quotes_and_candles_are_cached_with_their_ttl(
    setup: Any, caplog: pytest.LogCaptureFixture
) -> None:
    prices, cache, _ = setup
    caplog.set_level(logging.INFO, logger="financial_mcp.cache")
    first = await call("get_quote", {"symbol": "AAPL"})
    second = await call("get_quote", {"symbol": "AAPL"})
    assert first == second and len(prices.calls) == 1
    assert [r.getMessage() for r in caplog.records] == [
        "cache miss tool=get_quote symbol=AAPL",
        "cache hit tool=get_quote symbol=AAPL",
    ]
    await call("get_price_history", {"symbol": "AAPL", "period": "1mo", "interval": "1d"})
    await call("get_price_history", {"symbol": "AAPL", "period": "5d", "interval": "15m"})
    ttls = {key.split(":")[1] + ":" + str(ttl) for key, ttl in cache.ttls.items()}
    assert ttls == {
        f"get_quote:{QUOTE_TTL}",
        f"get_price_history:{DAILY_TTL}",
        f"get_price_history:{INTRADAY_TTL}",
    }


def test_expired_entries_are_fetched_again() -> None:
    now = [0.0]
    cache, calls = MemoryCache(clock=lambda: now[0]), []

    @cached_tool(60, lambda: cache)
    def tool(symbol: str) -> dict[str, int]:
        calls.append(symbol)
        return {"n": len(calls)}

    assert tool("AAPL") == {"n": 1} and tool(symbol="AAPL") == {"n": 1}
    now[0] = 61
    assert tool("AAPL") == {"n": 2}


def test_a_broken_cache_does_not_break_the_tool() -> None:
    class Broken:
        def get(self, key: str) -> Any:
            raise ConnectionError("redis down")

        def set(self, key: str, value: Any, ttl: int) -> None:
            raise ConnectionError("redis down")

        def delete_matching(self, pattern: str) -> int:
            return 0

    @cached_tool(60, lambda: Broken())
    def tool(symbol: str) -> str:
        return symbol

    assert tool("AAPL") == "AAPL"


def test_keys_carry_the_symbol_so_one_symbol_can_be_cleared() -> None:
    cache = MemoryCache()
    cache.set(cache_key("get_quote", {"symbol": "aapl"}), 1, 60)
    cache.set(cache_key("get_quote", {"symbol": "MSFT"}), 2, 60)
    assert cache_key("get_quote", {"symbol": "aapl"}).startswith("mcp:get_quote:AAPL:")
    assert clear_symbol(cache, "AAPL") == 1
    assert cache.get(cache_key("get_quote", {"symbol": "MSFT"})) == 2


async def test_daily_candles_are_saved_and_served_when_sources_fail(setup: Any) -> None:
    prices, cache, store = setup
    await call("get_price_history", {"symbol": "AAPL", "period": "1mo"})
    assert len(store.candles) == 3
    assert store.candles[("AAPL", "2026-11-11")][1] == "Fake price source (tests)"
    await call("get_price_history", {"symbol": "AAPL", "period": "5d", "interval": "15m"})
    assert len(store.candles) == 3  # intraday bars are not stored

    prices.down = True
    clear_symbol(cache, "AAPL")
    saved = await call("get_price_history", {"symbol": "AAPL", "period": "1mo"})
    assert saved["source"].startswith("Saved daily prices (ohlcv_daily, from Fake price source")
    assert saved["data"]["candles"][-1]["close"] == 107.1
    with pytest.raises(Exception, match="Yahoo is down"):
        await mcp.call_tool("get_price_history", {"symbol": "MSFT", "period": "1mo"})


async def test_statements_are_saved_as_financial_facts(setup: Any) -> None:
    _, _, store = setup
    await call("get_financial_statements", {"symbol": "AAPL", "statement": "income"})
    row = store.facts[("AAPL", "income", "annual", "2024-09-28", "revenue")]
    assert row["value"] == 400e9 and row["cik"] == 320193 and row["form"] == "10-K"
    assert row["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert row["link"].endswith("/000032019324000123/")


def test_fact_rows_skip_missing_values() -> None:
    data = {
        "statement": "income",
        "freq": "annual",
        "periods": [{"end": "2024-09-28", "values": {"revenue": 1.0, "eps_basic": None}}],
    }
    assert [r["item"] for r in fact_rows("AAPL", 1, data)] == ["revenue"]


async def test_refresh_market_data(setup: Any) -> None:
    prices, cache, store = setup
    await call("get_quote", {"symbol": "AAPL"})
    body = await call("refresh_market_data", {"symbol": "AAPL"})
    data = body["data"]
    assert data["daily_bars"] == 3 and data["cache_entries_cleared"] == 1
    assert data["facts_saved"] > 10 and len(store.candles) == 3
    assert ("1y", "1d") in {(p, i) for _, p, i in prices.calls}
    assert any(key[1] == "cash_flow" for key in store.facts)


@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="needs a Redis test server")
def test_redis_cache_round_trip() -> None:
    from financial_mcp.cache import RedisCache

    cache = RedisCache(os.environ["TEST_REDIS_URL"])
    key = cache_key("get_quote", {"symbol": "ZZTEST"})
    cache.set(key, {"price": 1.5, "day": date(2026, 11, 13)}, 5)
    assert cache.get(key) == {"price": 1.5, "day": "2026-11-13"}
    assert clear_symbol(cache, "ZZTEST") == 1 and cache.get(key) is None
