"""Indicators checked against pandas as the reference implementation."""

import math
import random
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from financial_mcp import indicators as ind
from financial_mcp.market_data import Candle
from financial_mcp.server import mcp
from financial_mcp.services import Services, set_services


def make_candles(count: int = 500, seed: int = 7) -> list[Candle]:
    rng = random.Random(seed)
    price, day = 100.0, date(2024, 1, 2)
    out: list[Candle] = []
    while len(out) < count:
        if day.weekday() < 5:
            open_ = price
            price = max(5.0, price * (1 + rng.gauss(0.0005, 0.02)))
            high = max(open_, price) * (1 + abs(rng.gauss(0, 0.006)))
            low = min(open_, price) * (1 - abs(rng.gauss(0, 0.006)))
            out.append(
                Candle(
                    day.isoformat(),
                    round(open_, 4),
                    round(high, 4),
                    round(low, 4),
                    round(price, 4),
                    rng.randint(1_000_000, 9_000_000),
                )
            )
        day += timedelta(days=1)
    return out


CANDLES = make_candles()
CLOSES = [c.close for c in CANDLES]
FRAME = pd.DataFrame([c.to_dict() for c in CANDLES])
TAIL = 150  # EMA-style series are compared after they have converged


def assert_close(
    ours: list[float | None], reference: pd.Series, tail: int | None = None, tolerance: float = 1e-8
) -> None:
    pairs = list(zip(ours, reference.tolist(), strict=True))
    if tail:
        pairs = pairs[-tail:]
    for mine, theirs in pairs:
        if theirs is None or (isinstance(theirs, float) and math.isnan(theirs)):
            assert mine is None
        else:
            assert mine == pytest.approx(theirs, abs=tolerance)


def test_sma_matches_rolling_mean() -> None:
    assert_close(ind.sma(CLOSES, 20), FRAME.close.rolling(20).mean())


def test_ema_matches_pandas_ewm() -> None:
    assert_close(ind.ema(CLOSES, 20), FRAME.close.ewm(span=20, adjust=False).mean(), TAIL)


def test_rsi_matches_wilder_smoothing() -> None:
    change = FRAME.close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    assert_close(ind.rsi(CLOSES, 14), 100 - 100 / (1 + gain / loss), TAIL, 1e-6)


def test_macd_matches_pandas() -> None:
    line = (
        FRAME.close.ewm(span=12, adjust=False).mean()
        - FRAME.close.ewm(span=26, adjust=False).mean()
    )
    signal = line.ewm(span=9, adjust=False).mean()
    result = ind.macd(CLOSES)
    assert_close(result["macd"], line, TAIL, 1e-6)
    assert_close(result["signal"], signal, TAIL, 1e-6)
    assert_close(result["histogram"], line - signal, TAIL, 1e-6)


def test_bollinger_matches_rolling_population_std() -> None:
    mean = FRAME.close.rolling(20).mean()
    sd = FRAME.close.rolling(20).std(ddof=0)
    bands = ind.bollinger(CLOSES, 20, 2)
    assert_close(bands["upper"], mean + 2 * sd, tolerance=1e-6)
    assert_close(bands["lower"], mean - 2 * sd, tolerance=1e-6)


def test_atr_matches_wilder_true_range() -> None:
    previous = FRAME.close.shift()
    true_range = pd.concat(
        [FRAME.high - FRAME.low, (FRAME.high - previous).abs(), (FRAME.low - previous).abs()],
        axis=1,
    ).max(axis=1)
    reference = true_range.iloc[1:].ewm(alpha=1 / 14, adjust=False).mean()
    assert_close(ind.atr(CANDLES, 14)[1:], reference, TAIL, 1e-6)


def test_vwap_matches_cumulative_formula() -> None:
    typical = (FRAME.high + FRAME.low + FRAME.close) / 3
    reference = (typical * FRAME.volume).cumsum() / FRAME.volume.cumsum()
    assert_close(ind.vwap(CANDLES), reference, tolerance=1e-6)


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("SMA 50", "sma_50"),
        ("rsi", "rsi_14"),
        ("bb", "bollinger_20"),
        ("MACD", "macd"),
        ("ema-9", "ema_9"),
        ("vwap", "vwap"),
    ],
)
def test_parse_indicator(text: str, key: str) -> None:
    assert ind.parse_indicator(text).key == key


@pytest.mark.parametrize("text", ["stochastic", "sma_1", "sma_500"])
def test_parse_indicator_rejects(text: str) -> None:
    with pytest.raises(ind.IndicatorError):
        ind.parse_indicator(text)


# --- the MCP tool --------------------------------------------------------------------


class LongPrices:
    source = "Fake long history (tests)"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        self.calls.append((symbol, period, interval))
        return CANDLES


@pytest.fixture
def long_prices(directory: Any) -> Any:
    prices = LongPrices()
    set_services(Services(directory=directory, prices=prices))
    yield prices
    set_services(None)


async def test_tool_warms_up_long_windows_and_reports_the_period(long_prices: LongPrices) -> None:
    result = await mcp.call_tool(
        "compute_indicators",
        {"symbol": "AAPL", "indicators": ["sma_200", "rsi", "macd"], "period": "6mo"},
    )
    body: Any = getattr(result, "structured_content", None)
    data = body["data"]
    assert long_prices.calls == [("AAPL", "2y", "1d")]  # extra history for warm-up
    last = date.fromisoformat(CANDLES[-1].time)
    assert date.fromisoformat(data["first_bar"]) >= last - timedelta(days=183)
    assert data["bars"] == len(data["candles"]) < len(CANDLES)
    assert set(data["indicators"]) == {"sma_200", "rsi_14", "macd"}
    expected_sma = round(sum(CLOSES[-200:]) / 200, 4)
    assert data["indicators"]["sma_200"]["latest"]["value"] == expected_sma
    assert len(data["indicators"]["rsi_14"]["recent"]["value"]) == 30
    assert set(data["indicators"]["macd"]["latest"]) == {"macd", "signal", "histogram"}
    assert "overbought" in data["explanations"]["rsi"]
    assert any("SMA" in s or "sma_200" in s for s in data["signals"])
    assert body["as_of"] == CANDLES[-1].time


async def test_tool_rejects_bad_requests(long_prices: LongPrices) -> None:
    with pytest.raises(ToolError, match="Unknown indicator"):
        await mcp.call_tool("compute_indicators", {"symbol": "AAPL", "indicators": ["kdj"]})
    with pytest.raises(ToolError, match="not listed on NASDAQ"):
        await mcp.call_tool("compute_indicators", {"symbol": "IBM"})
    with pytest.raises(ToolError, match="at most"):
        await mcp.call_tool("compute_indicators", {"symbol": "AAPL", "indicators": ["sma"] * 9})


async def test_short_history_explains_missing_values(services: Any) -> None:
    result = await mcp.call_tool(
        "compute_indicators", {"symbol": "AAPL", "indicators": ["sma_50"], "period": "1mo"}
    )
    body: Any = getattr(result, "structured_content", None)
    entry = body["data"]["indicators"]["sma_50"]
    assert entry["latest"]["value"] is None
    assert "Not enough bars" in entry["note"]
