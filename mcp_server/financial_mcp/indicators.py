"""Technical indicators on price candles (SCRUM-29).

Definitions (the same ones the chart uses in the browser):
- SMA: mean of the last n closes.
- EMA: seeded with the SMA of the first n closes, then k = 2 / (n + 1).
- RSI: Wilder smoothing of average gains and losses over n bars.
- MACD: EMA(12) - EMA(26), signal EMA(9) of MACD, histogram = MACD - signal.
- Bollinger Bands: SMA(n) +/- k population standard deviations.
- ATR: Wilder average of the true range over n bars.
- VWAP: cumulative (typical price x volume) / cumulative volume over the period shown.
Every series has one value per candle; None until enough bars exist.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .market_data import Candle

Series = list[float | None]

DEFAULT_WINDOWS = {"sma": 20, "ema": 20, "rsi": 14, "atr": 14, "bollinger": 20}
MAX_WINDOW = 200
SUPPORTED = ("sma", "ema", "rsi", "macd", "bollinger", "atr", "vwap")

EXPLANATIONS = {
    "sma": "Simple moving average: the average closing price over the last N bars. Price above "
    "it often means the recent trend is up; below it, down.",
    "ema": "Exponential moving average: like the SMA but gives more weight to recent prices, so "
    "it reacts faster.",
    "rsi": "Relative Strength Index (0 to 100): compares recent gains with recent losses. Above "
    "70 is usually called overbought, below 30 oversold.",
    "macd": "MACD: the gap between a fast (12) and slow (26) moving average. When the MACD line "
    "crosses above its signal line, momentum is turning up; below, turning down.",
    "bollinger": "Bollinger Bands: a band two standard deviations around the 20-bar average. "
    "Wide bands mean the price is moving a lot (volatile); narrow bands mean calm.",
    "atr": "Average True Range: the average size of a bar's full price range, in dollars. A "
    "higher ATR means bigger daily swings.",
    "vwap": "Volume-weighted average price: the average price paid per share over the period, "
    "weighted by how many shares traded at each price.",
}

_SPEC = re.compile(r"^\s*(sma|ema|rsi|macd|bollinger|bb|atr|vwap)[\s_:\-]*(\d+)?\s*$", re.I)


class IndicatorError(ValueError):
    """An indicator name or window that cannot be computed."""


@dataclass(frozen=True)
class IndicatorSpec:
    kind: str
    window: int | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}_{self.window}" if self.window else self.kind


def parse_indicator(text: str) -> IndicatorSpec:
    match = _SPEC.match(text)
    if not match:
        raise IndicatorError(
            f"Unknown indicator '{text}'. Use: {', '.join(SUPPORTED)} "
            "(optionally with a window, e.g. sma_50 or rsi_14)."
        )
    kind = match.group(1).lower()
    kind = "bollinger" if kind == "bb" else kind
    if kind in ("macd", "vwap"):
        return IndicatorSpec(kind)
    window = int(match.group(2)) if match.group(2) else DEFAULT_WINDOWS[kind]
    if not 2 <= window <= MAX_WINDOW:
        raise IndicatorError(f"Window for {kind} must be between 2 and {MAX_WINDOW}.")
    return IndicatorSpec(kind, window)


def sma(values: Sequence[float], window: int) -> Series:
    out: Series = [None] * len(values)
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        if i >= window - 1:
            out[i] = total / window
    return out


def ema(values: Sequence[float], window: int) -> Series:
    out: Series = [None] * len(values)
    if len(values) < window:
        return out
    k = 2 / (window + 1)
    previous = sum(values[:window]) / window
    out[window - 1] = previous
    for i in range(window, len(values)):
        previous = values[i] * k + previous * (1 - k)
        out[i] = previous
    return out


def rsi(values: Sequence[float], window: int = 14) -> Series:
    out: Series = [None] * len(values)
    if len(values) <= window:
        return out
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gain = sum(max(c, 0) for c in changes[:window]) / window
    loss = sum(max(-c, 0) for c in changes[:window]) / window

    def value() -> float:
        return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)

    out[window] = value()
    for i in range(window + 1, len(values)):
        change = changes[i - 1]
        gain = (gain * (window - 1) + max(change, 0)) / window
        loss = (loss * (window - 1) + max(-change, 0)) / window
        out[i] = value()
    return out


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, Series]:
    fast_ema, slow_ema = ema(values, fast), ema(values, slow)
    line: Series = [
        f - s if f is not None and s is not None else None
        for f, s in zip(fast_ema, slow_ema, strict=True)
    ]
    signal_line: Series = [None] * len(values)
    start = next((i for i, v in enumerate(line) if v is not None), None)
    if start is not None:
        tail = ema([v for v in line[start:] if v is not None], signal)
        signal_line[start:] = tail
    histogram: Series = [
        m - s if m is not None and s is not None else None
        for m, s in zip(line, signal_line, strict=True)
    ]
    return {"macd": line, "signal": signal_line, "histogram": histogram}


def bollinger(
    values: Sequence[float], window: int = 20, deviations: float = 2.0
) -> dict[str, Series]:
    middle = sma(values, window)
    upper: Series = [None] * len(values)
    lower: Series = [None] * len(values)
    for i in range(window - 1, len(values)):
        mean = middle[i]
        assert mean is not None
        sd = math.sqrt(sum((v - mean) ** 2 for v in values[i - window + 1 : i + 1]) / window)
        upper[i] = mean + deviations * sd
        lower[i] = mean - deviations * sd
    return {"upper": upper, "middle": middle, "lower": lower}


def atr(candles: Sequence[Candle], window: int = 14) -> Series:
    out: Series = [None] * len(candles)
    if len(candles) <= window:
        return out
    ranges = [
        max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        for prev, c in zip(candles, candles[1:], strict=False)
    ]
    average = sum(ranges[:window]) / window
    out[window] = average
    for i in range(window + 1, len(candles)):
        average = (average * (window - 1) + ranges[i - 1]) / window
        out[i] = average
    return out


def vwap(candles: Sequence[Candle]) -> Series:
    out: Series = []
    price_volume = 0.0
    volume = 0
    for c in candles:
        price_volume += (c.high + c.low + c.close) / 3 * c.volume
        volume += c.volume
        out.append(price_volume / volume if volume else None)
    return out


def compute(spec: IndicatorSpec, candles: Sequence[Candle]) -> dict[str, Series]:
    closes = [c.close for c in candles]
    if spec.kind == "sma":
        return {"value": sma(closes, spec.window or 20)}
    if spec.kind == "ema":
        return {"value": ema(closes, spec.window or 20)}
    if spec.kind == "rsi":
        return {"value": rsi(closes, spec.window or 14)}
    if spec.kind == "atr":
        return {"value": atr(candles, spec.window or 14)}
    if spec.kind == "vwap":
        return {"value": vwap(candles)}
    if spec.kind == "macd":
        return macd(closes)
    return bollinger(closes, spec.window or 20)


# Extra history fetched so long windows are warmed up before the period the user asked for.
LOOKBACK_PERIOD = {
    "5d": "6mo",
    "1mo": "1y",
    "3mo": "2y",
    "6mo": "2y",
    "ytd": "2y",
    "1y": "2y",
    "2y": "5y",
    "5y": "10y",
    "10y": "max",
    "max": "max",
}
PERIOD_DAYS = {
    "5d": 7,
    "1mo": 31,
    "3mo": 92,
    "6mo": 183,
    "1y": 366,
    "2y": 731,
    "5y": 1827,
    "10y": 3653,
}


def period_start(period: str, last_day: date) -> date | None:
    if period == "ytd":
        return date(last_day.year, 1, 1)
    days = PERIOD_DAYS.get(period)
    return last_day - timedelta(days=days) if days else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _signals(key: str, kind: str, series: dict[str, Series], close: float) -> list[str]:
    """Plain factual labels for the latest values (no advice)."""
    latest = {name: values[-1] for name, values in series.items()}
    labels: list[str] = []
    value = latest.get("value")
    if kind == "rsi" and value is not None:
        if value >= 70:
            labels.append(f"{key} is {value:.1f}, at or above 70 (often called overbought).")
        elif value <= 30:
            labels.append(f"{key} is {value:.1f}, at or below 30 (often called oversold).")
    if kind in ("sma", "ema", "vwap") and value is not None:
        side = "above" if close > value else "below" if close < value else "at"
        labels.append(f"The last close ({close}) is {side} {key} ({value:.2f}).")
    if kind == "macd":
        line, signal = series["macd"], series["signal"]
        if len(line) > 1 and None not in (line[-1], line[-2], signal[-1], signal[-2]):
            before = line[-2] - signal[-2]  # type: ignore[operator]
            now = line[-1] - signal[-1]  # type: ignore[operator]
            if before <= 0 < now:
                labels.append("MACD crossed above its signal line on the last bar.")
            elif before >= 0 > now:
                labels.append("MACD crossed below its signal line on the last bar.")
    if kind == "bollinger" and latest.get("upper") is not None:
        if close > latest["upper"]:  # type: ignore[operator]
            labels.append("The last close is above the upper Bollinger Band.")
        elif close < latest["lower"]:  # type: ignore[operator]
            labels.append("The last close is below the lower Bollinger Band.")
    return labels


def analyse(
    candles: Sequence[Candle], specs: Sequence[IndicatorSpec], start: date | None, recent: int = 30
) -> dict[str, Any]:
    """Compute on the full history, report on the bars from `start` on."""
    first = 0
    if start is not None:
        first = next(
            (i for i, c in enumerate(candles) if date.fromisoformat(c.time[:10]) >= start), 0
        )
    shown = list(candles[first:])
    if not shown:
        raise IndicatorError("No price bars in the requested period.")
    close = shown[-1].close
    results: dict[str, Any] = {}
    signals: list[str] = []
    for spec in specs:
        series = {name: values[first:] for name, values in compute(spec, candles).items()}
        latest = {name: _round(values[-1]) for name, values in series.items()}
        entry: dict[str, Any] = {
            "latest": latest,
            "recent": {
                name: [
                    {"time": c.time, "value": _round(v)}
                    for c, v in zip(shown[-recent:], values[-recent:], strict=True)
                ]
                for name, values in series.items()
            },
        }
        if all(v is None for v in latest.values()):
            entry["note"] = f"Not enough bars to compute {spec.key} in this period."
        results[spec.key] = entry
        signals += _signals(spec.key, spec.kind, series, close)
    return {
        "first_bar": shown[0].time,
        "last_bar": shown[-1].time,
        "last_close": close,
        "bars": len(shown),
        "indicators": results,
        "signals": signals,
        "candles": [c.to_dict() for c in shown],
    }
