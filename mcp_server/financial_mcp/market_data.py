"""Price data (quotes and OHLCV candles).

The provider is behind a small Protocol so tests can use a fake and a second source
(Alpha Vantage, SCRUM-22) can be added without touching the tools.
"""

from dataclasses import asdict, dataclass
from typing import Any, Protocol

ALLOWED_PERIODS = ("5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max")
ALLOWED_INTERVALS = ("5m", "15m", "30m", "1h", "1d", "1wk", "1mo")
# Yahoo only keeps intraday bars for a limited window.
INTRADAY_PERIODS = {
    "5m": {"5d", "1mo"},
    "15m": {"5d", "1mo"},
    "30m": {"5d", "1mo"},
    "1h": {"5d", "1mo", "3mo", "6mo", "ytd", "1y"},
}
MAX_CANDLES = 2500


class PriceDataError(RuntimeError):
    """Price data could not be fetched or was empty."""


@dataclass(frozen=True)
class Candle:
    time: str  # ISO date for daily+ bars, ISO datetime for intraday bars
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PriceProvider(Protocol):
    source: str

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]: ...


def validate_period_interval(period: str, interval: str) -> None:
    if period not in ALLOWED_PERIODS:
        raise ValueError(
            f"Unsupported period '{period}'. Use one of: {', '.join(ALLOWED_PERIODS)}."
        )
    if interval not in ALLOWED_INTERVALS:
        raise ValueError(
            f"Unsupported interval '{interval}'. Use one of: {', '.join(ALLOWED_INTERVALS)}."
        )
    allowed = INTRADAY_PERIODS.get(interval)
    if allowed is not None and period not in allowed:
        raise ValueError(
            f"Interval '{interval}' is only available for periods: {', '.join(sorted(allowed))}."
        )


class YFinanceProvider:
    """Yahoo Finance through the unofficial yfinance library (development source)."""

    source = "Yahoo Finance via yfinance (unofficial, may be delayed)"

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        import yfinance as yf  # imported lazily: heavy, and not needed by the tests' fakes

        try:
            frame = yf.Ticker(symbol).history(
                period=period, interval=interval, auto_adjust=False, actions=False
            )
        except Exception as exc:  # noqa: BLE001 - surface any provider failure as one error
            raise PriceDataError(f"Price provider error for {symbol}: {exc}") from exc
        if frame is None or frame.empty:
            raise PriceDataError(f"No price data returned for {symbol} ({period}, {interval}).")

        intraday = interval in INTRADAY_PERIODS
        candles: list[Candle] = []
        for stamp, row in frame.iterrows():
            when = stamp.isoformat() if intraday else stamp.date().isoformat()
            candles.append(
                Candle(
                    time=when,
                    open=round(float(row["Open"]), 4),
                    high=round(float(row["High"]), 4),
                    low=round(float(row["Low"]), 4),
                    close=round(float(row["Close"]), 4),
                    volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                )
            )
        return candles


def build_quote(symbol: str, candles: list[Candle]) -> dict[str, Any]:
    """Latest price and change versus the previous bar, from daily candles."""
    if not candles:
        raise PriceDataError(f"No price data returned for {symbol}.")
    last = candles[-1]
    previous = candles[-2] if len(candles) > 1 else None
    quote: dict[str, Any] = {
        "symbol": symbol,
        "price": last.close,
        "open": last.open,
        "day_high": last.high,
        "day_low": last.low,
        "volume": last.volume,
        "trading_day": last.time,
        "previous_close": previous.close if previous else None,
        "change": None,
        "change_percent": None,
    }
    if previous and previous.close:
        change = last.close - previous.close
        quote["change"] = round(change, 4)
        quote["change_percent"] = round(change / previous.close * 100, 2)
    return quote
