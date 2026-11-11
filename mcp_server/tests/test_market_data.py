import pandas as pd
import pytest

from financial_mcp import market_data
from financial_mcp.market_data import (
    Candle,
    PriceDataError,
    YFinanceProvider,
    build_quote,
    validate_period_interval,
)


@pytest.mark.parametrize(
    "period, interval", [("6mo", "1d"), ("5y", "1wk"), ("1mo", "5m"), ("1y", "1h")]
)
def test_valid_period_interval(period: str, interval: str) -> None:
    validate_period_interval(period, interval)


@pytest.mark.parametrize(
    "period, interval, message",
    [
        ("7d", "1d", "Unsupported period"),
        ("1y", "2m", "Unsupported interval"),
        ("1y", "5m", "only available"),
    ],
)
def test_invalid_period_interval(period: str, interval: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_period_interval(period, interval)


def test_build_quote_computes_change() -> None:
    quote = build_quote(
        "AAPL",
        [Candle("2026-11-10", 1, 1, 1, 200.0, 10), Candle("2026-11-11", 1, 1, 1, 210.0, 20)],
    )
    assert quote["price"] == 210.0
    assert quote["previous_close"] == 200.0
    assert quote["change"] == 10.0
    assert quote["change_percent"] == 5.0
    assert quote["trading_day"] == "2026-11-11"


def test_build_quote_single_bar_has_no_change() -> None:
    quote = build_quote("AAPL", [Candle("2026-11-11", 1, 1, 1, 210.0, 20)])
    assert quote["change"] is None and quote["previous_close"] is None


def test_build_quote_without_data_fails() -> None:
    with pytest.raises(PriceDataError):
        build_quote("AAPL", [])


class _FakeTicker:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def history(self, **kwargs: object) -> pd.DataFrame:
        return self._frame


def _patch_yfinance(monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame) -> None:
    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: _FakeTicker(frame))


def test_yfinance_provider_converts_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    index = pd.DatetimeIndex(["2026-11-10", "2026-11-11"], tz="America/New_York")
    frame = pd.DataFrame(
        {
            "Open": [1.0, 2.0],
            "High": [1.5, 2.5],
            "Low": [0.5, 1.5],
            "Close": [1.25, 2.256789],
            "Volume": [100, 200],
        },
        index=index,
    )
    _patch_yfinance(monkeypatch, frame)
    candles = YFinanceProvider().history("AAPL", "5d", "1d")
    assert candles[-1] == Candle("2026-11-11", 2.0, 2.5, 1.5, 2.2568, 200)


def test_yfinance_provider_empty_frame_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yfinance(monkeypatch, pd.DataFrame())
    with pytest.raises(PriceDataError, match="No price data"):
        YFinanceProvider().history("AAPL", "5d", "1d")


def test_max_candles_constant_is_reasonable() -> None:
    assert 500 <= market_data.MAX_CANDLES <= 10_000
