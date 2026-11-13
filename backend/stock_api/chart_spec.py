"""Chart specs for the UI (SCRUM-36), built from tool results the agent already fetched."""

from __future__ import annotations

from typing import Any

CHART_TOOLS = {"get_price_history", "compute_indicators", "run_scenario"}

# Indicator keys from compute_indicators that the chart can draw, mapped to its toggles.
CHART_TOGGLES = {
    "sma_20": "sma20",
    "sma_50": "sma50",
    "bollinger_20": "bollinger",
    "rsi_14": "rsi",
    "macd": "macd",
}


def chart_from_tool(name: str, payload: Any) -> dict[str, Any] | None:
    """A chart spec from a price or scenario tool result, or None for other tools."""
    if name not in CHART_TOOLS or not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    if name == "run_scenario":
        return scenario_chart(payload, data)
    candles = data.get("candles")
    if not isinstance(candles, list) or not candles:
        return None
    return {
        "kind": "price",
        "symbol": data.get("symbol"),
        "name": data.get("name"),
        "period": data.get("period"),
        "interval": data.get("interval"),
        "adjusted": bool(data.get("adjusted", False)),
        "candles": candles,
        "source": payload.get("source"),
        "as_of": payload.get("as_of"),
        "indicators": [
            CHART_TOGGLES[key] for key in (data.get("indicators") or {}) if key in CHART_TOGGLES
        ],
    }


def scenario_chart(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
    """Projected revenue per case, plus the case table (SCRUM-31)."""
    chart = data.get("chart")
    if not isinstance(chart, dict) or not chart.get("series"):
        return None
    return {
        "kind": "scenario",
        "symbol": data.get("symbol"),
        "name": data.get("name"),
        "metric": chart.get("metric", "revenue"),
        "unit": chart.get("unit", "USD"),
        "base_year": chart.get("base_year"),
        "base_value": chart.get("base_value"),
        "series": chart["series"],
        "table": data.get("table") or [],
        "price": (data.get("starting_point") or {}).get("price"),
        "source": payload.get("source"),
        "as_of": payload.get("as_of"),
    }
